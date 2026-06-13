"""
Volt API — auth, stream-key management, RTMP publish gating, authed chat,
channel directory, viewer presence.

Design notes:
- Streamers publish to rtmp://host:1935/live/<username>?key=<stream_key>.
  nginx-rtmp's on_publish posts the form here; we 403 bad keys, so the
  HLS path is the public username and the key never reaches viewers.
- Chat is write-through-API: browsers only *subscribe* to MQTT (broker ACL
  makes anonymous clients read-only); sends come here with a JWT and we
  publish server-side with a verified username.
"""
import os
import re
import json
import time
import sqlite3
import secrets
import threading
import urllib.request

import jwt
import bcrypt
import paho.mqtt.client as mqtt
from fastapi import FastAPI, HTTPException, Header, Request
from pydantic import BaseModel

DB_PATH = os.environ.get("DB_PATH", "/data/volt.db")
JWT_SECRET = os.environ.get("JWT_SECRET", "volt-dev-secret")
JWT_TTL = 7 * 24 * 3600
MQTT_HOST = os.environ.get("MQTT_HOST", "mqtt")
MQTT_USER = os.environ.get("MQTT_USER", "api")
MQTT_PASSWORD = os.environ.get("MQTT_API_PASSWORD", "voltmqtt")
MEDIAMTX_API = os.environ.get("MEDIAMTX_API", "http://mediamtx:9997")
TRANSCODER_SECRET = os.environ.get("TRANSCODER_SECRET", "volt-transcoder-secret")
USERNAME_RE = re.compile(r"^[a-z0-9_]{3,20}$")
RENDITION_RE = re.compile(r"^[a-z0-9_]+_(1080|720|480|360)$")

app = FastAPI()

# ── storage ──────────────────────────────────────────────────────────────────
db_lock = threading.Lock()
db = sqlite3.connect(DB_PATH, check_same_thread=False)
db.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY,
        username TEXT UNIQUE NOT NULL,
        pass_hash BLOB NOT NULL,
        stream_key TEXT NOT NULL,
        title TEXT DEFAULT '',
        created_at REAL NOT NULL
    )""")
db.commit()

# ── chat rooms (presence + history + join/leave) ────────────
# liveness comes from mediamtx; here we run the chat room layer.
import collections
viewers = {}                # channel -> {sid: {"ts": float, "user": str|None}}
chat_history = {}           # channel -> deque[ {user,text,ts} ]   (last 50)
last_chat_at = {}           # username -> ts (rate limit)
HISTORY = 50
state_lock = threading.Lock()


def publish_chat(channel, payload):
    """Publish to the room topic and append to its rolling history."""
    mq.publish(f"volt/chat/{channel}", json.dumps(payload))
    with state_lock:
        hist = chat_history.setdefault(channel, collections.deque(maxlen=HISTORY))
        hist.append(payload)


def system_msg(channel, text):
    publish_chat(channel, {"user": "", "text": text, "ts": time.time(), "sys": True})


def mtx_paths():
    """Active paths from mediamtx's control API. [] if mediamtx is unreachable."""
    try:
        with urllib.request.urlopen(MEDIAMTX_API + "/v3/paths/list", timeout=2) as r:
            return json.load(r).get("items", [])
    except Exception:
        return []


def mtx_ready(name: str):
    for p in mtx_paths():
        if p.get("name") == name and p.get("ready"):
            return p
    return None

# ── mqtt (server-side chat publisher) ────────────────────────────────────────
mq = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="volt-api")
mq.username_pw_set(MQTT_USER, MQTT_PASSWORD)


def mqtt_connect_with_retry():
    while True:
        try:
            mq.connect(MQTT_HOST, 1883, keepalive=30)
            mq.loop_start()
            return
        except Exception:
            time.sleep(2)


threading.Thread(target=mqtt_connect_with_retry, daemon=True).start()

# ── helpers ──────────────────────────────────────────────────────────────────


def make_token(username: str) -> str:
    return jwt.encode({"sub": username, "exp": int(time.time()) + JWT_TTL},
                      JWT_SECRET, algorithm="HS256")


def auth_user(authorization: str) -> sqlite3.Row:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "missing token")
    try:
        claims = jwt.decode(authorization[7:], JWT_SECRET, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(401, "invalid token")
    with db_lock:
        row = db.execute("SELECT * FROM users WHERE username=?",
                         (claims["sub"],)).fetchone()
    if row is None:
        raise HTTPException(401, "unknown user")
    return row


def user_payload(row) -> dict:
    # row: id, username, pass_hash, stream_key, title, created_at
    return {
        "username": row[1],
        "stream_key": row[3],
        "title": row[4],
        "rtmp_url": "rtmp://localhost:1935",
        "publish_key": f"{row[1]}?user={row[1]}&pass={row[3]}",
    }


def users_in(channel):  # state_lock held; distinct logged-in users present
    return {d["user"] for d in viewers.get(channel, {}).values() if d.get("user")}


def prune_viewers(channel: str):  # state_lock held; returns users who fully left
    now = time.time()
    chan = viewers.get(channel, {})
    before = users_in(channel)
    for sid in [s for s, d in chan.items() if now - d["ts"] > 30]:
        del chan[sid]
    return before - users_in(channel)


def viewer_count(channel: str) -> int:
    with state_lock:
        prune_viewers(channel)
        return len(viewers.get(channel, {}))


def presence_pruner():
    """Every 10s, drop stale viewers and announce anyone who left."""
    while True:
        time.sleep(10)
        for ch in list(viewers.keys()):
            with state_lock:
                left = prune_viewers(ch)
            for u in left:
                system_msg(ch, f"{u} left")


threading.Thread(target=presence_pruner, daemon=True).start()


class Credentials(BaseModel):
    username: str
    password: str


class ChatMessage(BaseModel):
    text: str


class StreamSettings(BaseModel):
    title: str


class Heartbeat(BaseModel):
    sid: str
    user: str | None = None

# ── auth ─────────────────────────────────────────────────────────────────────


@app.post("/auth/signup")
def signup(body: Credentials):
    username = body.username.strip().lower()
    if not USERNAME_RE.match(username):
        raise HTTPException(400, "username must be 3-20 chars: a-z 0-9 _")
    if len(body.password) < 6:
        raise HTTPException(400, "password must be at least 6 chars")
    pass_hash = bcrypt.hashpw(body.password.encode(), bcrypt.gensalt())
    stream_key = secrets.token_hex(8)
    try:
        with db_lock:
            db.execute(
                "INSERT INTO users (username, pass_hash, stream_key, created_at) VALUES (?,?,?,?)",
                (username, pass_hash, stream_key, time.time()))
            db.commit()
    except sqlite3.IntegrityError:
        raise HTTPException(409, "username already taken")
    with db_lock:
        row = db.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    return {"token": make_token(username), "user": user_payload(row)}


@app.post("/auth/login")
def login(body: Credentials):
    username = body.username.strip().lower()
    with db_lock:
        row = db.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    if row is None or not bcrypt.checkpw(body.password.encode(), row[2]):
        raise HTTPException(401, "wrong username or password")
    return {"token": make_token(username), "user": user_payload(row)}


@app.get("/me")
def me(authorization: str = Header(None)):
    return {"user": user_payload(auth_user(authorization))}


@app.post("/me/reset_key")
def reset_key(authorization: str = Header(None)):
    row = auth_user(authorization)
    new_key = secrets.token_hex(8)
    with db_lock:
        db.execute("UPDATE users SET stream_key=? WHERE username=?", (new_key, row[1]))
        db.commit()
        row = db.execute("SELECT * FROM users WHERE username=?", (row[1],)).fetchone()
    return {"user": user_payload(row)}


@app.patch("/me/stream")
def set_title(body: StreamSettings, authorization: str = Header(None)):
    row = auth_user(authorization)
    with db_lock:
        db.execute("UPDATE users SET title=? WHERE username=?",
                   (body.title.strip()[:120], row[1]))
        db.commit()
        row = db.execute("SELECT * FROM users WHERE username=?", (row[1],)).fetchone()
    return {"user": user_payload(row)}

# ── stream-key gating (mediamtx HTTP auth hook) ──────────────────────────────


@app.post("/mediamtx/auth")
async def mediamtx_auth(req: Request):
    """
    mediamtx POSTs {action, path, user, password, protocol, ...} before every
    publish. We only gate `publish`: the RTMP path must be a registered username
    and the supplied password must equal that user's stream key. Read/playback
    are excluded in mediamtx.yml, so viewing stays open.
    """
    try:
        p = await req.json()
    except Exception:
        p = {}
    if p.get("action") != "publish":
        return {}
    path = (p.get("path") or "").strip()
    user = (p.get("user") or "").strip()
    pw = p.get("password") or ""
    # Internal transcoder pushing rendition rungs (<user>_720/_480/_360).
    if user == "__transcoder__":
        if secrets.compare_digest(pw, TRANSCODER_SECRET) and RENDITION_RE.match(path):
            return {}
        raise HTTPException(401, "bad transcoder auth")
    # Normal streamer: path must be their username and password their stream key.
    with db_lock:
        row = db.execute("SELECT stream_key FROM users WHERE username=?", (path,)).fetchone()
    if row is None or user != path or not secrets.compare_digest(row[0], pw):
        raise HTTPException(401, "invalid stream key")
    return {}

# ── channels / presence (liveness from mediamtx) ─────────────────────────────


def _ready_started(p) -> float:
    # mediamtx readyTime is RFC3339; fall back to now if unparseable.
    try:
        from datetime import datetime
        return datetime.fromisoformat(p["readyTime"].replace("Z", "+00:00")).timestamp()
    except Exception:
        return time.time()


@app.get("/channels")
def channels():
    with db_lock:
        titles = dict(db.execute("SELECT username, title FROM users").fetchall())
    out = []
    for p in mtx_paths():
        if not p.get("ready"):
            continue
        name = p.get("name", "")
        if RENDITION_RE.match(name):       # hide internal transcode rungs
            continue
        out.append({
            "name": name,
            "title": titles.get(name, ""),
            "started": _ready_started(p),
            "viewers": viewer_count(name),
            "source": _srctype(p),
        })
    return {"channels": out}


def _srctype(p):
    # 'webrtc' (browser go-live) | 'rtmp' (OBS/ffmpeg) | other
    t = (p or {}).get("source", {}).get("type", "") or ""
    if "webRTC" in t or "whip" in t.lower():
        return "webrtc"
    if "rtmp" in t.lower():
        return "rtmp"
    return t or "other"


@app.get("/channels/{name}")
def channel(name: str):
    p = mtx_ready(name)
    with db_lock:
        row = db.execute("SELECT title FROM users WHERE username=?", (name,)).fetchone()
    return {
        "name": name,
        "live": p is not None,
        "started": _ready_started(p) if p else None,
        "title": row[0] if row else "",
        "viewers": viewer_count(name),
        "source": _srctype(p) if p else None,
    }


@app.post("/channels/{name}/heartbeat")
def heartbeat(name: str, body: Heartbeat):
    user = body.user if (body.user and USERNAME_RE.match(body.user)) else None
    with state_lock:
        before = users_in(name)
        viewers.setdefault(name, {})[body.sid[:64]] = {"ts": time.time(), "user": user}
        prune_viewers(name)
        joined = users_in(name) - before
        count = len(viewers[name])
    for u in joined:                       # announce new arrivals (once)
        system_msg(name, f"{u} joined")
    return {"viewers": count}

# ── chat rooms (write-through-API; broker is read-only for browsers) ─────────


@app.post("/chat/{channel}")
def chat(channel: str, body: ChatMessage, authorization: str = Header(None)):
    row = auth_user(authorization)
    username = row[1]
    text = body.text.strip()[:500]
    if not text:
        raise HTTPException(400, "empty message")
    if not USERNAME_RE.match(channel):
        raise HTTPException(400, "bad channel")
    now = time.time()
    with state_lock:
        if now - last_chat_at.get(username, 0) < 0.5:
            raise HTTPException(429, "slow down")
        last_chat_at[username] = now
    publish_chat(channel, {"user": username, "text": text, "ts": now})
    return {"ok": True}


@app.get("/chat/{channel}/history")
def chat_history_get(channel: str):
    with state_lock:
        msgs = list(chat_history.get(channel, []))
    return {"messages": msgs}


@app.get("/chat/{channel}/presence")
def chat_presence(channel: str):
    with state_lock:
        prune_viewers(channel)
        users = sorted(users_in(channel))
        count = len(viewers.get(channel, {}))
    return {"users": users, "online": len(users), "viewers": count}


@app.get("/health")
def health():
    return {"ok": True}


# ── demo seed (local convenience only) ───────────────────────────────────────
with db_lock:
    if db.execute("SELECT 1 FROM users WHERE username='demo'").fetchone() is None:
        db.execute(
            "INSERT INTO users (username, pass_hash, stream_key, title, created_at) VALUES (?,?,?,?,?)",
            ("demo", bcrypt.hashpw(b"demo123", bcrypt.gensalt()), "demokey",
             "Volt demo broadcast", time.time()))
        db.commit()
