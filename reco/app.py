import env
import time
import logging
from datetime import datetime
from pythonjsonlogger import jsonlogger
from logging.handlers import WatchedFileHandler
from flask import Flask, current_app, request, jsonify, make_response, abort, g as app_ctx

from recommenders.clips_recommender import init_clips_models, get_all_recommended_clips, init_new_users_clips
from error_handlers import unauthorized_request_handler, bad_request_handler
from middlewares.auth_middlewares import internal_auth_required
from helpers import csv_to_list

formatter = jsonlogger.JsonFormatter()

log_handler = WatchedFileHandler(env.LOG_FILE_PATH)
log_handler.setFormatter(formatter)

logging.getLogger().addHandler(log_handler)
logging.getLogger().setLevel(logging.DEBUG)

# Removes flask's default logging
logging.getLogger("werkzeug").setLevel(logging.WARN)

init_clips_models()
init_new_users_clips()

app = Flask(__name__)

app.config["CLIENT_ID"] = env.CLIENT_ID
app.config["CLIENT_SECRET"] = env.CLIENT_SECRET

app.config["MODELS_METADATA_RESPONSE"] = {
    "video_score_matrix": env.get_model_metadata("video_score_matrix"),
    "watch_history_graph": env.get_model_metadata("watch_history_graph"),
}

app.register_error_handler(401, unauthorized_request_handler)
app.register_error_handler(400, bad_request_handler)


@app.before_request
def before_request():
    app_ctx.start_time = time.perf_counter()


@app.after_request
def after_request(response):
    t = time.perf_counter() - app_ctx.start_time
    time_in_ms = t * 1000

    ip_addr = request.headers.get('X-Forwarded-For', request.remote_addr)

    current_app.logger.info(msg={
        "message": "req_resp_info",
        "time_taken_ms": time_in_ms,
        "req_headers": dict(request.headers),
        "ip_addr": ip_addr,
        "method": request.method,
        "path": request.full_path,
        "current_time": datetime.utcnow(),
        "resp_status": response.status,
        "resp_headers": dict(response.headers),
        "args": dict(request.args),
    })

    return response


@app.route("/api/v1/clips/", methods=["GET"])
@internal_auth_required
def get_recommended_clips():
    query_params = request.args
    user_id = query_params.get("user_id")

    # Manipulates the api to use a list of clip uids
    # as watch history for the recommendation. Solves
    # the cold start problem
    custom_clips_csv = query_params.get("custom_clips")
    custom_clips_li = csv_to_list(custom_clips_csv)

    # only single category_id is coming in filter as of now
    filter = query_params.get("filters")
    if filter == None:
        filter = ""

    if user_id is None or len(user_id.strip()) == 0:
        abort(400, "user_id query param is required!")

    formatted_user_uid = "u_{}".format(user_id)

    recommended_clips = []
    try:
        start_time = time.time()
        is_generic_suggestion, recommended_clips = get_all_recommended_clips(
            formatted_user_uid, custom_clips_li, filter
        )

        current_app.logger.info(msg={
            "func": "get_recommended_clips",
            "message": "model_exec_time",
            "time_taken_ms": ((time.time() - start_time) * 1000),
            "clips_length": len(recommended_clips),
            "user_id": user_id
        })
    except Exception as e:
        current_app.logger.info(msg={
            "func": "get_recommended_clips",
            "type": "error",
            "message": str(e),
            "error": e,
        })

    data = {
        "models_metadata": app.config["MODELS_METADATA_RESPONSE"],
        "clip_uids": recommended_clips,
        "is_generic_suggestion": is_generic_suggestion,
    }

    return make_response(jsonify(data=data), 200)


@app.route("/api/v1/clips/metadata/", methods=["GET"])
@internal_auth_required
def get_model_metadata_for_user():
    query_params = request.args
    user_id = query_params.get("user_id")

    # Note: user_id is not used as of now.
    # But since this api is related to thee get clips api,
    # user_id might be used later on.
    if user_id is None or len(user_id.strip()) == 0:
        abort(400, "user_id query param is required!")

    data = {
        "models_metadata": app.config["MODELS_METADATA_RESPONSE"],
    }

    return make_response(jsonify(data=data), 200)


@app.route("/health/", methods=["GET"])
def get_health():
    data = {
        "message": "health"
    }

    return make_response(jsonify(data=data), 200)


if __name__ == "__main__":
    app.run(host='0.0.0.0', debug=False)
