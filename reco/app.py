"""Volt recommender service — Flask API used internally by the Volt API."""
import os
from functools import wraps

from flask import Flask, request, jsonify, make_response, abort

from recommender import recommend

CLIENT_ID = os.environ.get("CLIENT_ID", "volt-local")
CLIENT_SECRET = os.environ.get("CLIENT_SECRET", "volt-local-secret")

app = Flask(__name__)


def internal_auth_required(f):
    """Gate endpoints to internal callers via X-CLIENT-ID / X-CLIENT-SECRET."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if (request.headers.get("X-CLIENT-ID") != CLIENT_ID
                or request.headers.get("X-CLIENT-SECRET") != CLIENT_SECRET):
            abort(401, "wrong or missing auth credentials")
        return f(*args, **kwargs)
    return decorated


def csv_to_list(value):
    if not value:
        return []
    return [v.strip() for v in value.split(",") if v.strip()]


@app.get("/api/v1/clips/")
@internal_auth_required
def get_recommended_clips():
    user_id = (request.args.get("user_id") or "").strip()
    if not user_id:
        abort(400, "user_id query param is required")
    custom_clips = csv_to_list(request.args.get("custom_clips"))
    category = request.args.get("filters") or ""
    is_generic, clip_uids = recommend(user_id, custom_clips, category)
    return make_response(jsonify(data={
        "clip_uids": clip_uids,
        "is_generic_suggestion": is_generic,
        "models_metadata": {},
    }), 200)


@app.get("/health/")
def health():
    return make_response(jsonify(data={"message": "health"}), 200)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
