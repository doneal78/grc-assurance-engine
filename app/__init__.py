"""Application factory for the GRC Assurance Engine."""

import os
import secrets
from collections.abc import Mapping
from urllib.parse import urlparse

from flask import Flask, Response, request


def create_app(test_config: Mapping[str, object] | None = None) -> Flask:
    """Create and configure the Flask application."""

    app = Flask(__name__, instance_relative_config=True)

    app.config.from_mapping(
        DATABASE=os.environ.get(
            "DATABASE_PATH", os.path.join(app.instance_path, "grc_assurance.sqlite3")
        ),
        REQUIRE_AUTH=os.environ.get("REQUIRE_AUTH", "false").lower() == "true",
        DEMO_USERNAME=os.environ.get("DEMO_USERNAME", ""),
        DEMO_PASSWORD=os.environ.get("DEMO_PASSWORD", ""),
        TESTING=False,
    )

    if test_config is not None:
        app.config.from_mapping(test_config)

    # Flask's own default is None, which would leave uploads uncapped.
    # Ordinary form posts are capped again in the before-request check below.
    # The constant lives with the importer so the parser and the HTTP cap match.
    from app.services.intake_importer import IMPORT_MAX_BYTES
    if not app.config.get("MAX_CONTENT_LENGTH"):
        app.config["MAX_CONTENT_LENGTH"] = IMPORT_MAX_BYTES

    if app.config["REQUIRE_AUTH"] and not (
        app.config["DEMO_USERNAME"] and app.config["DEMO_PASSWORD"]
    ):
        raise ValueError("DEMO_USERNAME and DEMO_PASSWORD are required when REQUIRE_AUTH is enabled")

    # Ensure the local runtime-data directory exists.
    # The instance directory is excluded from Git.
    os.makedirs(app.instance_path, exist_ok=True)

    # Pages anyone may open without the demo password. The public "Try it"
    # pages run synthetic input through the real services and save nothing.
    PUBLIC_ENDPOINTS = {"health.health", "static"}
    FORM_MAX_BYTES = 16 * 1024
    IMPORT_ENDPOINTS = {"try_demo.import_preview", "try_demo.import_confirm"}

    @app.before_request
    def limit_request_body():
        """Keep ordinary form posts small, and cap import uploads separately."""
        endpoint = request.endpoint or ""
        limit = app.config["MAX_CONTENT_LENGTH"] if endpoint in IMPORT_ENDPOINTS else FORM_MAX_BYTES
        if request.content_length is not None and request.content_length > limit:
            return Response("Request body is too large", 413)

    @app.before_request
    def require_demo_authentication():
        """Protect hosted demo pages with HTTP Basic authentication."""
        endpoint = request.endpoint or ""
        if not app.config["REQUIRE_AUTH"] or endpoint in PUBLIC_ENDPOINTS or endpoint.startswith("try_demo."):
            return None

        credentials = request.authorization
        username = credentials.username if credentials else ""
        password = credentials.password if credentials else ""
        # Compare as UTF-8 bytes: compare_digest rejects non-ASCII str input.
        valid_username = secrets.compare_digest(
            username.encode("utf-8"), app.config["DEMO_USERNAME"].encode("utf-8")
        )
        valid_password = secrets.compare_digest(
            password.encode("utf-8"), app.config["DEMO_PASSWORD"].encode("utf-8")
        )
        if valid_username and valid_password:
            return None

        return Response(
            "Authentication required", 401,
            {"WWW-Authenticate": 'Basic realm="GRC Assurance Engine demo"'},
        )

    @app.before_request
    def reject_cross_site_writes():
        """Reject state-changing requests that do not come from this site.

        Browsers resend HTTP Basic credentials automatically, so a form on
        another site could otherwise submit changes on a signed-in user's
        behalf. Browsers attach an Origin header (or at least a Referer) to
        form posts, and other sites cannot forge either one.
        """
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return None
        if request.routing_exception is not None:
            return None  # Let Flask return its normal 404 or 405.
        source = request.headers.get("Origin") or request.headers.get("Referer")
        if source and urlparse(source).netloc == request.host:
            return None
        # Scripts call the JSON API without a browser Origin. Those routes do
        # not write to the risk register. A cross-site browser request still
        # sends Origin and is rejected when the host does not match.
        endpoint = request.endpoint or ""
        if endpoint.startswith("api.") and not source:
            return None
        return Response("Cross-site request rejected", 403)

    # Register route blueprints. Imported here, inside the factory,
    # so route modules can safely import from the app package later.
    from app.routes.api import bp as api_bp
    from app.routes.dashboard import bp as dashboard_bp
    from app.routes.demos import bp as demos_bp
    from app.routes.health import bp as health_bp
    from app.routes.methodology import bp as methodology_bp
    from app.routes.risks import bp as risks_bp
    from app.routes.try_demo import bp as try_demo_bp

    app.register_blueprint(api_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(demos_bp)
    app.register_blueprint(health_bp)
    app.register_blueprint(methodology_bp)
    app.register_blueprint(risks_bp)
    app.register_blueprint(try_demo_bp)

    from app.db import init_app as init_db_app
    init_db_app(app)

    return app
