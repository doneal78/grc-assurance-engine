"""Methods and assumptions page for the portfolio demonstration."""

from flask import Blueprint, render_template

from app.services.cost_model import calculate_cost
from app.services.evidence_validator import load_policy
from app.services.risk_engine import load_rules

bp = Blueprint("methodology", __name__)


@bp.get("/methodology")
def index():
    return render_template("methodology.html", cost=calculate_cost(),
                           risk_model_version=load_rules()["rule_set_version"],
                           evidence_policy_version=load_policy()["evidence_policy_version"])
