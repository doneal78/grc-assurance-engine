"""Application factory for the GRC Assurance Engine."""

import os
from collections.abc import Mapping

from flask import Flask


def create_app(test_config: Mapping[str, object] | None = None) -> Flask:
    """Create and configure the Flask application."""

    app = Flask(__name__, instance_relative_config=True)

    app.config.from_mapping(
        DATABASE=os.path.join(app.instance_path, "grc_assurance.sqlite3"),
        TESTING=False,
    )

    if test_config is not None:
        app.config.from_mapping(test_config)

    # Ensure the local runtime-data directory exists.
    # The instance directory is excluded from Git.
    os.makedirs(app.instance_path, exist_ok=True)

    # Register route blueprints. Imported here, inside the factory,
    # so route modules can safely import from the app package later.
    from app.routes.dashboard import bp as dashboard_bp
    from app.routes.health import bp as health_bp

    app.register_blueprint(dashboard_bp)
    app.register_blueprint(health_bp)

    return app
