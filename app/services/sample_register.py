"""Load a few synthetic sample risks into one browser sandbox.

The rows are the existing scenario fixtures, labeled as sample data.
They are written only through ``register_scenario``, which appends workflow
events on that sandbox's hash chain. A missing sandbox id is refused, so
this module does not write the shared register.
"""

from flask import current_app, has_request_context

from app.services.sandbox import DEFAULT_MAX_RISKS, SANDBOX_ID_RE
from app.services.scenario_runner import run_scenario
from app.services.workflow_service import WorkflowInputError, register_scenario, risk_for_scenario

SAMPLE_SCENARIO_IDS = (
    "evidence-supported",
    "high-risk-ai",
    "prohibited-ai-decisions",
)
SAMPLE_LABEL = "Sample data · synthetic."


def _maximum():
    maximum = DEFAULT_MAX_RISKS
    if has_request_context():
        configured = current_app.config.get("SANDBOX_MAX_RISKS", DEFAULT_MAX_RISKS)
        if isinstance(configured, int) and configured >= 1:
            maximum = configured
    return maximum


def _sandbox_count(db, sandbox_id):
    return db.execute(
        "SELECT COUNT(*) AS n FROM risks WHERE sandbox_id = ?",
        (sandbox_id,),
    ).fetchone()["n"]


def visitor_has_risks(db, sandbox_id):
    """True when this browser sandbox already holds at least one saved risk."""
    if not isinstance(sandbox_id, str) or not SANDBOX_ID_RE.fullmatch(sandbox_id):
        return False
    return _sandbox_count(db, sandbox_id) > 0


def samples_loaded(db, sandbox_id):
    """True when this sandbox already holds every sample scenario.

    A missing sandbox id is not loaded. A partial set stays loadable.
    """
    if not isinstance(sandbox_id, str) or not SANDBOX_ID_RE.fullmatch(sandbox_id):
        return False
    return all(
        risk_for_scenario(db, scenario_id, sandbox_id=sandbox_id)
        for scenario_id in SAMPLE_SCENARIO_IDS
    )


def seed_sample_risks(db, sandbox_id):
    """Insert any missing sample scenarios into ``sandbox_id``.

    A second call does not insert duplicates. When the sandbox cannot hold
    every missing sample, nothing new is written. Returns a small result
    dict. Raises ``WorkflowInputError`` when the caller has no sandbox id
    or the cap would be exceeded.
    """
    if not isinstance(sandbox_id, str) or not SANDBOX_ID_RE.fullmatch(sandbox_id):
        raise WorkflowInputError(
            "Sample data is stored in this browser's sandbox. Nothing was written to the shared register."
        )
    existing = []
    missing = []
    for scenario_id in SAMPLE_SCENARIO_IDS:
        row = risk_for_scenario(db, scenario_id, sandbox_id=sandbox_id)
        if row:
            existing.append(row["risk_id"])
        else:
            missing.append(scenario_id)
    if not missing:
        return {"added": 0, "risk_ids": existing, "already_loaded": True}
    maximum = _maximum()
    count = _sandbox_count(db, sandbox_id)
    if count + len(missing) > maximum:
        raise WorkflowInputError(
            f"This browser sandbox can hold {maximum} saved assessments and already has {count}. "
            f"Loading {len(missing)} samples would pass that cap. Nothing new was saved."
        )
    added = []
    for scenario_id in missing:
        result = run_scenario(scenario_id)
        labeled = {
            **result,
            "name": f"Sample: {result['name']}",
            "summary": f"{SAMPLE_LABEL} {result['summary']}",
        }
        added.append(register_scenario(db, labeled, sandbox_id=sandbox_id))
    return {"added": len(added), "risk_ids": existing + added, "already_loaded": False}
