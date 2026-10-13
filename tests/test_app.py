"""Phase 1 tests: application factory, health route, and dashboard."""

from app import create_app


def test_factory_defaults_to_not_testing():
    assert create_app().testing is False


def test_factory_applies_test_config(app):
    assert app.testing is True
    assert app.config["DATABASE"].endswith("test.sqlite3")


def test_health_returns_documented_response(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.get_json() == {"status": "ok", "service": "grc-assurance-engine"}


def test_health_rejects_post(client):
    assert client.post("/health").status_code == 405


def test_unknown_route_returns_404(client):
    assert client.get("/does-not-exist").status_code == 404


def test_dashboard_shows_honest_empty_state(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b"No assessments yet" in response.data
    assert b"Synthetic data only" in response.data
    assert b"assessments loaded" not in response.data


def test_stylesheet_is_served(client):
    assert client.get("/static/css/styles.css").status_code == 200
