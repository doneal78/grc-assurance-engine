"""Bind the signed sandbox cookie to the current HTTP request.

The cookie is HttpOnly and SameSite=Lax. It is not a session login. A
missing or rejected cookie does not select another visitor's sandbox.
"""

from datetime import datetime, timezone

from flask import current_app, g, request

from app.db import get_db
from app.services.sandbox import (
    COOKIE_NAME,
    cleanup_stale_sandboxes,
    new_sandbox_id,
    read_sandbox_cookie,
    sign_sandbox_cookie,
    touch_sandbox,
)


def request_scope():
    """The sandbox id for this request, or ``None`` when there is no valid cookie.

    ``None`` means the request may see shared rows only. It is not the
    unscoped service sentinel.
    """
    return getattr(g, "sandbox_id", None)


def load_request_sandbox():
    """Read the cookie. A bad cookie sets no sandbox id."""
    g.sandbox_id = None
    g.sandbox_cookie = None
    g.sandbox_invalid = False
    raw = request.cookies.get(COOKIE_NAME)
    if not raw:
        return
    parsed = read_sandbox_cookie(
        raw,
        current_app.config.get("SECRET_KEY", ""),
        int(current_app.config.get("SANDBOX_TTL_SECONDS", 0)),
    )
    if parsed is None:
        g.sandbox_invalid = True
        return
    g.sandbox_id = parsed


def issue_sandbox():
    """Return this request's sandbox id, creating one when the cookie is absent.

    The new row is committed before the risk insert so a later rollback of a
    rejected save does not drop the id the cookie names. An existing valid
    cookie is reused. A rejected cookie is not reused.
    """
    if getattr(g, "sandbox_id", None):
        touch_sandbox(get_db(), g.sandbox_id, datetime.now(timezone.utc))
        get_db().commit()
        return g.sandbox_id
    sandbox_id = new_sandbox_id()
    touch_sandbox(get_db(), sandbox_id, datetime.now(timezone.utc))
    get_db().commit()
    g.sandbox_id = sandbox_id
    g.sandbox_cookie = sign_sandbox_cookie(sandbox_id, current_app.config["SECRET_KEY"])
    return sandbox_id


def bind_visitor_sandbox():
    """Refresh a valid sandbox and delete stale ones. Health and static stay read-only."""
    endpoint = request.endpoint or ""
    if endpoint in {"static", "health.health"}:
        return None
    load_request_sandbox()
    db = get_db()
    ttl = int(current_app.config.get("SANDBOX_TTL_SECONDS", 0))
    cleanup_stale_sandboxes(db, now=datetime.now(timezone.utc), ttl_seconds=ttl)
    if g.sandbox_id:
        touch_sandbox(db, g.sandbox_id, datetime.now(timezone.utc))
        db.commit()
    return None


def attach_sandbox_cookie(response):
    """Set the cookie only when this request issued a new sandbox id."""
    token = getattr(g, "sandbox_cookie", None)
    if not token:
        return response
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=int(current_app.config.get("SANDBOX_TTL_SECONDS", 0)),
        httponly=True,
        samesite="Lax",
        secure=bool(current_app.config.get("SANDBOX_COOKIE_SECURE")),
        path="/",
    )
    return response
