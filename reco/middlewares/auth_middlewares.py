from functools import wraps
from flask import request, current_app as app, abort


def internal_auth_required(f):
    """
    Decorator to be used in endpoints which are used by internal services.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        client_id = request.headers.get('X-CLIENT-ID')
        client_secret = request.headers.get('X-CLIENT-SECRET')

        if client_id != app.config["CLIENT_ID"] or client_secret != app.config["CLIENT_SECRET"]:
            abort(401, "Wrong or missing auth credentials!")

        return f(*args, **kwargs)

    return decorated
