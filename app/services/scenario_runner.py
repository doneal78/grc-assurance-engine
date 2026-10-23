"""Load and run repeatable synthetic demonstration scenarios."""

import json
from copy import deepcopy
from datetime import date
from pathlib import Path

from app.services.control_mapper import map_claims
from app.services.evidence_validator import validate_assessment
from app.services.org_policy import load_org_policy
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
    policy = load_org_policy()
    checked = validate_assessment(scenario["claims"], scenario["evidence"],
                                  date.fromisoformat(scenario_set["as_of"]),
                                  policy["required_contract_clauses"])
    risk = evaluate({**scenario["assessment"], "claims": checked["claims"]},
                    clause_check=checked["clause_check"])
    mappings = map_claims(checked["claims"])
    return {
        "scenario_id": scenario["scenario_id"],
        "name": scenario["name"],
        "summary": scenario["summary"],
        "synthetic_data": scenario_set["synthetic_data"],
        "as_of": scenario_set["as_of"],
        "scenario_set_version": scenario_set["scenario_set_version"],
        "assessment_inputs": scenario["assessment"],
        "evidence_policy_version": checked["evidence_policy_version"],
        "claims": checked["claims"],
        "risk": risk,
        "mappings": mappings,
    }
