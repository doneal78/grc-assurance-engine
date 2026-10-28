"""Whether the current HTTP request passed the demo password gate.

The public try pages stay open even when the gate is on. A process with no
request, including the CLI, is not a signed-in reviewer.
"""

from flask import current_app, has_request_context, request


def request_is_signed_in():
    """Return whether this request presented the demo password.

    ``REQUIRE_AUTH`` off means nobody is signed in. Health, static files, and
    ``/try/`` stay open when the gate is on, so those requests are not signed in.
    A view that runs on any other endpoint has already passed the gate.
    """
    if not has_request_context():
        return False
    if not current_app.config.get("REQUIRE_AUTH"):
        return False
    endpoint = request.endpoint or ""
    if endpoint in {"health.health", "static"} or endpoint.startswith("try_demo."):
        return False
    return True
