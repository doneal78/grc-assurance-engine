"""Load and run repeatable synthetic demonstration scenarios."""

import json
from copy import deepcopy
from datetime import date
from pathlib import Path

from app.services.control_mapper import map_claims
from app.services.evidence_validator import validate
from app.services.risk_engine import evaluate

DEFAULT_SCENARIOS_PATH = Path(__file__).resolve().parent.parent / "data" / "demo_scenarios.json"


class ScenarioNotFoundError(LookupError):
    """Raised when a requested demonstration scenario does not exist."""


def load_scenarios(path=DEFAULT_SCENARIOS_PATH):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def list_scenarios(scenario_set=None):
    """Return scenario summaries without exposing mutable source fixtures."""
    scenario_set = scenario_set if scenario_set is not None else load_scenarios()
    return [{"scenario_id": item["scenario_id"], "name": item["name"],
             "summary": item["summary"], "synthetic_data": scenario_set["synthetic_data"]}
            for item in scenario_set["scenarios"]]


def run_scenario(scenario_id, scenario_set=None):
    """Evaluate a scenario through the same services used by assessments."""
    scenario_set = scenario_set if scenario_set is not None else load_scenarios()
    match = next((item for item in scenario_set["scenarios"]
                  if item["scenario_id"] == scenario_id), None)
    if match is None:
        raise ScenarioNotFoundError(scenario_id)

    scenario = deepcopy(match)
    evidence_result = validate(scenario["claims"], scenario["evidence"],
                               date.fromisoformat(scenario_set["as_of"]))
    risk = evaluate({**scenario["assessment"], "claims": evidence_result["claims"]})
    mappings = map_claims(evidence_result["claims"])
    return {
        "scenario_id": scenario["scenario_id"],
        "name": scenario["name"],
        "summary": scenario["summary"],
        "synthetic_data": scenario_set["synthetic_data"],
        "as_of": scenario_set["as_of"],
        "scenario_set_version": scenario_set["scenario_set_version"],
        "assessment_inputs": scenario["assessment"],
        "evidence_policy_version": evidence_result["evidence_policy_version"],
        "claims": evidence_result["claims"],
        "risk": risk,
        "mappings": mappings,
    }
