"""Methods and assumptions page for the portfolio demonstration."""

from flask import Blueprint, render_template

from app.db import get_db
from app.services.control_mapper import list_library
from app.services.cost_model import avoided_incident_value, calculate_cost
from app.services.evidence_validator import load_policy
from app.services.intake_questionnaire import load_questionnaire
from app.services.org_policy import load_org_policy
from app.services.risk_engine import load_rules
from app.services.workflow_metrics import observed_metrics

bp = Blueprint("methodology", __name__)


@bp.get("/methodology")
def index():
    rules = load_rules()
    library = list_library()
    avoided = avoided_incident_value()
    return render_template("methodology.html", cost=calculate_cost(),
                           observed=observed_metrics(get_db(), avoided_incident=avoided),
                           avoided_incident=avoided,
                           mapping_set_version=library["mapping_set_version"],
                           mapping_count=len(library["mappings"]),
                           risk_model_version=rules["rule_set_version"],
                           escalation_rules=rules["escalation_rules"],
                           org_policy=load_org_policy(),
                           questionnaire_version=load_questionnaire()["questionnaire_version"],
                           evidence_policy_version=load_policy()["evidence_policy_version"])
