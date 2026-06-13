"""
Volt transcoder — gives the platform an ABR ladder on top of mediamtx.

mediamtx does not transcode, so for every live SOURCE path we:
  1) run one ffmpeg that encodes 720/480/360 and pushes each back into
     mediamtx as `<src>_720|_480|_360`  → each is its own Low-Latency HLS
     stream (used for the player's manual low-latency quality picker).
  2) run a second ffmpeg that *copies* (no re-encode) the source + the three
     rungs into a single multivariant HLS master on disk → nginx serves it at
     /abr/<src>/master.m3u8 for auto-adapting (standard-latency) playback.

So only 3 encodes per channel; the ABR master is copy-only packaging.
Rendition publishes authenticate to the API with a shared transcoder secret.
"""
import os
import re
import json
import time
import shutil
import subprocess
import urllib.request

MEDIAMTX_RTMP = os.environ.get("MEDIAMTX_RTMP", "rtmp://mediamtx:1935")
MEDIAMTX_RTSP = os.environ.get("MEDIAMTX_RTSP", "rtsp://mediamtx:8554")
MEDIAMTX_API = os.environ.get("MEDIAMTX_API", "http://mediamtx:9997")
SECRET = os.environ.get("TRANSCODER_SECRET", "volt-transcoder-secret")
ABR_DIR = os.environ.get("ABR_DIR", "/data/abr")
RUNG = re.compile(r"_(1080|720|480|360)$")  # rendition paths we create ourselves

procs = {}   # source name -> [transcode_proc, package_proc]


def mtx_paths():
    try:
        with urllib.request.urlopen(MEDIAMTX_API + "/v3/paths/list", timeout=3) as r:
            return json.load(r).get("items", [])
    except Exception:
        return []


def live_sources():
    return [p["name"] for p in mtx_paths()
            if p.get("ready") and not RUNG.search(p.get("name", ""))]


def x264(bv, maxrate, bufsize, ba):
    return ["-c:v", "libx264", "-preset", "veryfast", "-tune", "zerolatency",
            "-profile:v", "main", "-b:v", bv, "-maxrate", maxrate, "-bufsize", bufsize,
            "-g", "60", "-keyint_min", "60", "-sc_threshold", "0",
            "-c:a", "aac", "-b:a", ba, "-ar", "44100"]


def start(u):
    # Read the source over RTSP — it carries Opus (from WebRTC/browser go-live),
    # which RTMP/FLV cannot. Audio is re-encoded to AAC for the H264/AAC rungs,
    # so RTMP sources and WebRTC sources both flow through the same ladder.
    src = f"{MEDIAMTX_RTSP}/{u}"

    def pub(r):
        return f"{MEDIAMTX_RTMP}/{u}_{r}?user=__transcoder__&pass={SECRET}"

    # 1) transcode ladder → mediamtx LL-HLS rungs (1080/720/480/360).
    # The 1080 rung is a clean re-encode when the source is >=1080; for smaller
    # sources it upscales (still a valid rung, just no extra detail).
    transcode = (
        ["ffmpeg", "-hide_banner", "-loglevel", "warning", "-rtsp_transport", "tcp", "-i", src,
         "-filter_complex",
         "[0:v]split=4[a][b][c][e];"
         "[a]scale=-2:1080[v10];[b]scale=-2:720[v7];[c]scale=-2:480[v4];[e]scale=-2:360[v3]"]
        + ["-map", "[v10]", "-map", "0:a?"] + x264("5000k", "5000k", "5000k", "160k") + ["-f", "flv", pub("1080")]
        + ["-map", "[v7]", "-map", "0:a?"] + x264("2800k", "2800k", "2800k", "128k") + ["-f", "flv", pub("720")]
        + ["-map", "[v4]", "-map", "0:a?"] + x264("1200k", "1200k", "1200k", "96k") + ["-f", "flv", pub("480")]
        + ["-map", "[v3]", "-map", "0:a?"] + x264("500k", "500k", "500k", "64k") + ["-f", "flv", pub("360")]
    )
    p1 = subprocess.Popen(transcode)
    time.sleep(4)  # let the rungs register before the packager reads them

    # 2) copy the rungs into one multivariant HLS master (ABR, standard latency)
    d = os.path.join(ABR_DIR, u)
    os.makedirs(d, exist_ok=True)
    package = [
        "ffmpeg", "-hide_banner", "-loglevel", "warning",
        "-i", f"{MEDIAMTX_RTMP}/{u}_1080",
        "-i", f"{MEDIAMTX_RTMP}/{u}_720",
        "-i", f"{MEDIAMTX_RTMP}/{u}_480",
        "-i", f"{MEDIAMTX_RTMP}/{u}_360",
        "-map", "0:v", "-map", "0:a?", "-map", "1:v", "-map", "1:a?",
        "-map", "2:v", "-map", "2:a?", "-map", "3:v", "-map", "3:a?",
        "-c", "copy", "-f", "hls",
        "-hls_time", "2", "-hls_list_size", "6",
        "-hls_flags", "delete_segments+independent_segments+omit_endlist",
        "-var_stream_map", "v:0,a:0,name:1080 v:1,a:1,name:720 v:2,a:2,name:480 v:3,a:3,name:360",
        os.path.join(d, "stream_%v.m3u8"),
    ]
    p2 = subprocess.Popen(package)
    # ffmpeg's own master generation chokes on copy-from-RTMP ("bandwidth info
    # not available"), so we write the multivariant master ourselves. Variants
    # (source/720/480/360) and their BANDWIDTH/RESOLUTION are known.
    write_master(d)
    procs[u] = [p1, p2]
    print(f"[transcoder] started ladder for '{u}'", flush=True)


def write_master(d):
    variants = [
        ("stream_1080.m3u8", 5500000, "1920x1080"),
        ("stream_720.m3u8", 3000000, "1280x720"),
        ("stream_480.m3u8", 1400000, "854x480"),
        ("stream_360.m3u8", 600000, "640x360"),
    ]
    lines = ["#EXTM3U", "#EXT-X-VERSION:6"]
    for pl, bw, res in variants:
        lines.append(f'#EXT-X-STREAM-INF:BANDWIDTH={bw},RESOLUTION={res}')
        lines.append(pl)
    with open(os.path.join(d, "master.m3u8"), "w") as f:
        f.write("\n".join(lines) + "\n")


def stop(u):
    for p in procs.get(u, []):
        try:
            p.terminate()
        except Exception:
            pass
    procs.pop(u, None)
    shutil.rmtree(os.path.join(ABR_DIR, u), ignore_errors=True)
    print(f"[transcoder] stopped '{u}'", flush=True)


def main():
    os.makedirs(ABR_DIR, exist_ok=True)
    print("[transcoder] watching mediamtx for live sources…", flush=True)
    while True:
        live = set(live_sources())
        # tear down sources that ended or whose ffmpeg died
        for u in list(procs):
            if u not in live or any(p.poll() is not None for p in procs[u]):
                stop(u)
        # spin up new sources
        for u in live:
            if u not in procs:
                try:
                    start(u)
                except Exception as e:
                    print(f"[transcoder] start error for '{u}': {e}", flush=True)
        time.sleep(3)


if __name__ == "__main__":
    main()
