from fastapi.testclient import TestClient

from app.main import app


def test_health_check() -> None:
    response = TestClient(app).get("/api/v1/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_database_health_returns_unavailable_without_credentials(monkeypatch) -> None:
    monkeypatch.setattr("app.api.routes.health.database_is_available", lambda: False)

    response = TestClient(app).get("/api/v1/health/database")

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable", "database": "postgresql"}
