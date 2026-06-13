from flask import jsonify, make_response


def unauthorized_request_handler(e):
    """
    listen for abort from any endpoint with a 401 and a string message
    and use a common response format for that.
    """
    error_message = e.description
    return make_response(jsonify({
        "message": error_message,
    }), 401)


def bad_request_handler(e):
    """
    listen for abort from any endpoint with a 400 and a string message
    and use a common response format for that.
    """
    error_message = e.description
    return make_response(jsonify({
        "message": error_message,
    }), 400)
