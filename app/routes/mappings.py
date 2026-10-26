"""Browse the versioned control-mapping library."""

from flask import Blueprint, render_template

from app.services.control_mapper import list_library

bp = Blueprint("mappings", __name__)


@bp.get("/mappings")
def index():
    """List every mapping in the library. The template does not invent rows."""
    return render_template("mappings.html", library=list_library())
