"""JSON intake API.

These routes compute an assessment and return it. They write a synthetic
risk only when the body sets persist to true and includes a human disposition
and rationale. When REQUIRE_AUTH is enabled they use the same HTTP Basic
check as the rest of the application, outside the public Try it pages.
"""

from flask import Blueprint, jsonify, request

from app.db import get_db
from app.services.bot_intake import (
    BotRequestError, assess_request_text, contract_document, error_document,
)
from app.services.demo_auth import request_is_signed_in

bp = Blueprint("api", __name__, url_prefix="/api/v1")


def _error(kind, problems, status):
    return jsonify(error_document(kind, problems)), status


@bp.get("/intake/contract")
def intake_contract():
    return jsonify(contract_document())


@bp.post("/intake/assess")
def intake_assess():
    if not request.is_json:
        return _error("validation", ["Content-Type must be application/json."], 415)
    try:
        raw = request.get_data(as_text=True)
    except UnicodeDecodeError:
        return _error("validation", ["The request body is not UTF-8 text."], 400)
    try:
        document = assess_request_text(
            raw, db=get_db(), accept_authenticated_effort=request_is_signed_in(),
            accept_cash_savings=request_is_signed_in(),
            bind_sandbox=True,
        )
    except BotRequestError as exc:
        return _error("validation", exc.problems, 400)
    except Exception as exc:
        return _error("engine", [f"{type(exc).__name__}: {exc}"], 500)
    return jsonify(document)
