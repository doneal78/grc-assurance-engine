"""Browser sandbox ids for the public demo register.

A sandbox id is a random opaque token. It is not a user account, not a
login, and not a tenant. The id is stored in a signed cookie. Anyone who
holds that cookie can read and update that sandbox. Clearing the cookie
drops the link to it. The versioned scenario fixtures stay visible to every
visitor as shared read-only examples. Rows with no sandbox id stay visible
to every visitor as well: they are the local CLI saves and anything stored
before sandboxes existed.

Cleanup deletes a stale sandbox's risks and that sandbox's event chain.
It does not rewrite the shared chain or any other sandbox chain.
"""

import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.services.event_chain import delete_chain_tip


COOKIE_NAME = "grc_sandbox"
COOKIE_SALT = "grc-visitor-sandbox"
DEFAULT_TTL_SECONDS = 14 * 24 * 60 * 60
DEFAULT_MAX_RISKS = 25
SANDBOX_ID_RE = re.compile(r"^[0-9a-f]{32}$")


class _Unscoped:
    """Sentinel: a service call that is not a browser request."""

    def __repr__(self):
        return "UNSCOPED"


UNSCOPED = _Unscoped()


def new_sandbox_id():
    """Return a new opaque id. The value is not derived from an address or a name."""
    return secrets.token_hex(16)


def sign_sandbox_cookie(sandbox_id, secret):
    """Sign one sandbox id. The cookie value is not the id by itself."""
    if not isinstance(sandbox_id, str) or not SANDBOX_ID_RE.fullmatch(sandbox_id):
        raise ValueError("sandbox id must be 32 lowercase hex characters")
    serializer = URLSafeTimedSerializer(str(secret), salt=COOKIE_SALT)
    return serializer.dumps(sandbox_id)


def read_sandbox_cookie(token, secret, max_age):
    """Return the sandbox id, or ``None`` when the cookie is missing or rejected.

    A bad signature, an expired timestamp, and a payload that is not an
    opaque id are all rejected. The rejected text is not used as an id.
    """
    if not isinstance(token, str) or not token or not secret:
        return None
    serializer = URLSafeTimedSerializer(str(secret), salt=COOKIE_SALT)
    try:
        value = serializer.loads(token, max_age=max_age)
    except (BadSignature, SignatureExpired):
        return None
    if not isinstance(value, str) or not SANDBOX_ID_RE.fullmatch(value):
        return None
    return value


def resolve_secret_key(app):
    """Use ``SECRET_KEY`` when it is set. Otherwise keep a random file key.

    The file lives under the Flask instance directory, which is not committed.
    Two processes on one host share that file. A blank key is treated as unset.
    """
    configured = app.config.get("SECRET_KEY") or os.environ.get("SECRET_KEY")
    if isinstance(configured, str) and configured.strip():
        app.config["SECRET_KEY"] = configured.strip()
        return
    directory = Path(app.instance_path)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "sandbox_secret"
    if path.is_file():
        stored = path.read_text(encoding="utf-8").strip()
        if stored:
            app.config["SECRET_KEY"] = stored
            return
    key = secrets.token_hex(32)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    try:
        descriptor = os.open(path, flags, 0o600)
    except FileExistsError:
        stored = path.read_text(encoding="utf-8").strip()
        app.config["SECRET_KEY"] = stored or key
        return
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(key)
    app.config["SECRET_KEY"] = key


def touch_sandbox(db, sandbox_id, now):
    """Insert or refresh one sandbox row. Does not commit."""
    stamp = now.astimezone(timezone.utc).isoformat(timespec="seconds")
    db.execute(
        """INSERT INTO sandboxes (sandbox_id, created_at, last_seen_at)
           VALUES (?, ?, ?)
           ON CONFLICT(sandbox_id) DO UPDATE SET last_seen_at = excluded.last_seen_at""",
        (sandbox_id, stamp, stamp),
    )


def cleanup_stale_sandboxes(db, *, now, ttl_seconds):
    """Delete sandboxes that have not been seen within ``ttl_seconds``.

    Shared rows, which have no sandbox id, are not deleted. Each deleted
    sandbox loses its risks, decisions, remediation, events, and chain tip.
    Returns the number of sandboxes removed. Commits only when it removes one.
    """
    if not isinstance(ttl_seconds, int) or ttl_seconds < 1:
        return 0
    if not isinstance(now, datetime):
        return 0
    cutoff = (now.astimezone(timezone.utc) - timedelta(seconds=ttl_seconds)).isoformat(timespec="seconds")
    stale = [
        row["sandbox_id"]
        for row in db.execute(
            "SELECT sandbox_id FROM sandboxes WHERE last_seen_at < ?",
            (cutoff,),
        ).fetchall()
    ]
    if not stale:
        return 0
    for sandbox_id in stale:
        risk_ids = [
            row["risk_id"]
            for row in db.execute(
                "SELECT risk_id FROM risks WHERE sandbox_id = ?",
                (sandbox_id,),
            ).fetchall()
        ]
        for risk_id in risk_ids:
            db.execute("DELETE FROM decisions WHERE risk_id = ?", (risk_id,))
            db.execute("DELETE FROM remediation_actions WHERE risk_id = ?", (risk_id,))
            db.execute("DELETE FROM workflow_events WHERE risk_id = ?", (risk_id,))
        db.execute("DELETE FROM workflow_events WHERE sandbox_id = ?", (sandbox_id,))
        db.execute("DELETE FROM risks WHERE sandbox_id = ?", (sandbox_id,))
        delete_chain_tip(db, sandbox_id)
        db.execute("DELETE FROM sandboxes WHERE sandbox_id = ?", (sandbox_id,))
    db.commit()
    return len(stale)
