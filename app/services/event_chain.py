"""SHA-256 hash chain for the local workflow-event table.

Each event stores ``prev_hash`` and ``hash``. ``hash`` is the SHA-256 hex
digest of a canonical JSON object: the event fields plus ``prev_hash``.
The first event uses a fixed genesis ``prev_hash``. Later events use the
previous row's ``hash``. Rows are checked in ``event_id`` order.

``chain_origin`` is ``appended`` when the application hashed the row as it
was written. It is ``chained_after_the_fact`` when startup hashed a row that
already existed. That mark is part of the hashed JSON.

The chain makes an edited field, a broken link, or a reordered sequence
visible. It does not stop someone who can rewrite the database from
computing a new chain that matches the new rows. An empty table checks as
intact. Deleting only the last row leaves the earlier links consistent
unless the stored tip still names the removed row. This is tamper-evident.
It is not tamper-proof, immutable storage, a production audit log, or a
certification.

``verify_event_chain`` does not import Flask and does not open a database.
"""

import hashlib
import json
import sqlite3
from collections.abc import Mapping

GENESIS_PREV_HASH = "0" * 64
CHAIN_ORIGIN_APPENDED = "appended"
CHAIN_ORIGIN_BACKFILLED = "chained_after_the_fact"
BACKFILL_META_KEY = "workflow_event_chain_backfill"
TIP_EVENT_ID_KEY = "workflow_event_chain_tip_event_id"
TIP_HASH_KEY = "workflow_event_chain_tip_hash"
CHAIN_LABEL = "tamper-evident, not tamper-proof"

_CANONICAL_FIELDS = (
    "chain_origin",
    "detail",
    "event_id",
    "event_type",
    "occurred_at",
    "prev_hash",
    "risk_id",
)
_CHAIN_COLUMNS = ("prev_hash", "hash", "chain_origin")


def canonical_event(event):
    """Return the JSON object covered by the hash, with keys sorted."""
    if not isinstance(event, Mapping):
        raise TypeError("event must be a mapping")
    return {field: event[field] for field in _CANONICAL_FIELDS}


def canonical_json(event):
    """Serialize ``canonical_event`` with stable separators and UTF-8 text."""
    return json.dumps(
        canonical_event(event),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def event_digest(event):
    """SHA-256 hex digest of the canonical event JSON."""
    return hashlib.sha256(canonical_json(event).encode("utf-8")).hexdigest()


def verify_event_chain(events, *, tip_event_id=None, tip_hash=None):
    """Return ``"intact"`` or the first broken event id.

    ``events`` is the claimed chain order, normally ascending ``event_id``.
    A row is broken when ``prev_hash`` is not the previous row's hash (the
    genesis value for the first row) or when ``hash`` is not the digest of
    the canonical JSON. The function stops at the first such row.

    ``tip_event_id`` and ``tip_hash`` are optional. When both are omitted,
    only the given rows are checked. When they are present, the last row
    must be that tip. A missing tip row is returned as the broken id. An
    empty list with no tip is intact.
    """
    previous_hash = GENESIS_PREV_HASH
    rows = list(events)
    seen = []
    for event in rows:
        event_id = event.get("event_id") if isinstance(event, Mapping) else None
        if not isinstance(event, Mapping):
            return event_id
        try:
            expected = event_digest(event)
        except (KeyError, TypeError):
            return event_id
        if event.get("prev_hash") != previous_hash or event.get("hash") != expected:
            return event_id
        previous_hash = event["hash"]
        seen.append(event_id)
    if tip_event_id is None and tip_hash is None:
        return "intact"
    if not seen:
        return tip_event_id
    last = rows[-1]
    if last.get("event_id") != tip_event_id or last.get("hash") != tip_hash:
        if tip_event_id not in seen:
            return tip_event_id
        return last.get("event_id")
    return "intact"


def describe_event_chain(events, *, tip_event_id=None, tip_hash=None):
    """Build the page result from ``verify_event_chain``.

    The summary states the check result. It does not calculate a risk score,
    an observed metric, or a cost.
    """
    rows = list(events)
    result = verify_event_chain(rows, tip_event_id=tip_event_id, tip_hash=tip_hash)
    backfilled = sum(
        1 for event in rows
        if isinstance(event, Mapping) and event.get("chain_origin") == CHAIN_ORIGIN_BACKFILLED
    )
    if result == "intact":
        status = "intact"
        event_id = None
        summary = (
            f"Chain check: intact ({len(rows)} events). "
            "Each stored hash is SHA-256 of the canonical JSON of that event's fields and prev_hash."
        )
    else:
        status = "broken"
        event_id = result
        summary = (
            f"Chain check: broken at event {result}. "
            "That row is the first whose stored hash or prev_hash does not match."
        )
    if backfilled == 0:
        backfill_note = "No stored event was chained after the fact."
    elif backfilled == 1:
        backfill_note = (
            "1 event was chained after the fact. It already existed when the hash chain was added. "
            "The mark is stored on the row. It does not mean the original write was hashed."
        )
    else:
        backfill_note = (
            f"{backfilled} events were chained after the fact. They already existed when the hash "
            "chain was added. The mark is stored on those rows. It does not mean the original "
            "writes were hashed."
        )
    return {
        "label": CHAIN_LABEL,
        "status": status,
        "event_id": event_id,
        "event_count": len(rows),
        "backfilled_count": backfilled,
        "summary": summary,
        "backfill_note": backfill_note,
        "limit": (
            "Someone who can rewrite the database can rebuild the whole chain. "
            "This check is not immutable storage, a production audit log, or a certification. "
            "It does not change observed register counts or the illustrative cost formula."
        ),
    }


def _meta_table(connection):
    connection.execute(
        """CREATE TABLE IF NOT EXISTS schema_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )"""
    )


def _meta_value(connection, key):
    row = connection.execute(
        "SELECT value FROM schema_meta WHERE key = ?", (key,)
    ).fetchone()
    if row is None:
        return None
    return row[0] if not isinstance(row, sqlite3.Row) else row["value"]


def write_chain_tip(connection, event_id, digest):
    """Store the latest event id and hash. Does not commit."""
    _meta_table(connection)
    for key, value in (
        (TIP_EVENT_ID_KEY, str(event_id)),
        (TIP_HASH_KEY, digest),
    ):
        connection.execute(
            """INSERT INTO schema_meta (key, value) VALUES (?, ?)
               ON CONFLICT(key) DO UPDATE SET value = excluded.value""",
            (key, value),
        )


def read_chain_tip(connection):
    """Return ``(tip_event_id, tip_hash)``. Missing keys stay ``None``."""
    tables = {
        row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    if "schema_meta" not in tables:
        return None, None
    raw_id = _meta_value(connection, TIP_EVENT_ID_KEY)
    tip_hash = _meta_value(connection, TIP_HASH_KEY)
    tip_event_id = int(raw_id) if isinstance(raw_id, str) and raw_id.isdigit() else None
    if not isinstance(tip_hash, str):
        tip_hash = None
    return tip_event_id, tip_hash


def read_event_chain(connection):
    """Load workflow events in ``event_id`` order and describe the chain."""
    rows = [dict(row) for row in connection.execute(
        """SELECT event_id, risk_id, event_type, detail, occurred_at,
                  prev_hash, hash, chain_origin
           FROM workflow_events
           ORDER BY event_id"""
    ).fetchall()]
    tip_event_id, tip_hash = read_chain_tip(connection)
    if rows and (tip_event_id is None or tip_hash is None):
        described = describe_event_chain(rows)
        described["status"] = "broken"
        described["event_id"] = rows[-1]["event_id"]
        described["summary"] = (
            f"Chain check: broken at event {rows[-1]['event_id']}. "
            "The chain tip is missing."
        )
        return described
    return describe_event_chain(rows, tip_event_id=tip_event_id, tip_hash=tip_hash)


def ensure_event_chain(connection):
    """Add chain columns and hash existing rows once. Does not commit.

    Rows hashed here are marked ``chained_after_the_fact``. A later call sees
    the schema_meta flag and does not rehash, so an edited row stays visible.
    """
    tables = {
        row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    if "workflow_events" not in tables:
        return
    columns = {row[1] for row in connection.execute("PRAGMA table_info(workflow_events)")}
    for name in _CHAIN_COLUMNS:
        if name not in columns:
            connection.execute(f"ALTER TABLE workflow_events ADD COLUMN {name} TEXT")
    _meta_table(connection)
    if _meta_value(connection, BACKFILL_META_KEY) == "done":
        return
    rows = connection.execute(
        """SELECT event_id, risk_id, event_type, detail, occurred_at,
                  prev_hash, hash, chain_origin
           FROM workflow_events
           ORDER BY event_id"""
    ).fetchall()
    previous = GENESIS_PREV_HASH
    for row in rows:
        stored_hash = row["hash"]
        if stored_hash:
            previous = stored_hash
            continue
        payload = {
            "event_id": row["event_id"],
            "risk_id": row["risk_id"],
            "event_type": row["event_type"],
            "detail": row["detail"],
            "occurred_at": row["occurred_at"],
            "prev_hash": previous,
            "chain_origin": CHAIN_ORIGIN_BACKFILLED,
        }
        digest = event_digest(payload)
        connection.execute(
            """UPDATE workflow_events
               SET prev_hash = ?, hash = ?, chain_origin = ?
               WHERE event_id = ?""",
            (previous, digest, CHAIN_ORIGIN_BACKFILLED, row["event_id"]),
        )
        previous = digest
    if rows:
        write_chain_tip(connection, rows[-1]["event_id"], previous)
    connection.execute(
        "INSERT INTO schema_meta (key, value) VALUES (?, 'done')",
        (BACKFILL_META_KEY,),
    )
