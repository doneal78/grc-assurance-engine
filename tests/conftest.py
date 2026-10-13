"""Shared pytest fixtures."""

import pytest

from app import create_app


@pytest.fixture
def app(tmp_path):
    """Create an app configured for tests, with runtime data in a temp folder."""
    return create_app({"TESTING": True, "DATABASE": str(tmp_path / "test.sqlite3")})


@pytest.fixture
def client(app):
    """A test client that sends requests without starting a server."""
    return app.test_client()
