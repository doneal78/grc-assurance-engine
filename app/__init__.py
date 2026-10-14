"""Application factory for the GRC Assurance Engine."""

import os
import secrets
from collections.abc import Mapping

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

    if app.config["REQUIRE_AUTH"] and not (
        app.config["DEMO_USERNAME"] and app.config["DEMO_PASSWORD"]
    ):
        raise ValueError("DEMO_USERNAME and DEMO_PASSWORD are required when REQUIRE_AUTH is enabled")

    # Ensure the local runtime-data directory exists.
    # The instance directory is excluded from Git.
    os.makedirs(app.instance_path, exist_ok=True)

    @app.before_request
    def require_demo_authentication():
        """Protect hosted demo pages with HTTP Basic authentication."""
        if not app.config["REQUIRE_AUTH"] or request.endpoint == "health.health":
            return None

        credentials = request.authorization
        username = credentials.username if credentials else ""
        password = credentials.password if credentials else ""
        valid_username = secrets.compare_digest(username, app.config["DEMO_USERNAME"])
        valid_password = secrets.compare_digest(password, app.config["DEMO_PASSWORD"])
        if valid_username and valid_password:
            return None

        return Response(
            "Authentication required", 401,
            {"WWW-Authenticate": 'Basic realm="GRC Assurance Engine demo"'},
        )

    # Register route blueprints. Imported here, inside the factory,
    # so route modules can safely import from the app package later.
    from app.routes.dashboard import bp as dashboard_bp
    from app.routes.demos import bp as demos_bp
    from app.routes.health import bp as health_bp
    from app.routes.methodology import bp as methodology_bp
    from app.routes.risks import bp as risks_bp

    app.register_blueprint(dashboard_bp)
    app.register_blueprint(demos_bp)
    app.register_blueprint(health_bp)
    app.register_blueprint(methodology_bp)
    app.register_blueprint(risks_bp)

    from app.db import init_app as init_db_app
    init_db_app(app)

    return app
