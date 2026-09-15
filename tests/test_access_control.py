from fastapi.testclient import TestClient

from ruinform_intelligence.server import app


def test_health_is_public(monkeypatch) -> None:
    monkeypatch.delenv("RUINFORM_API_TOKEN", raising=False)
    response = TestClient(app).get("/health")
    assert response.status_code == 200


def test_v1_routes_require_access_token(monkeypatch) -> None:
    monkeypatch.setenv("RUINFORM_API_TOKEN", "test-token")
    client = TestClient(app)
    unauthorized = client.get("/v1/live-transformations/missing")
    authorized = client.get(
        "/v1/live-transformations/missing",
        headers={"x-ruinform-key": "test-token"},
    )
    assert unauthorized.status_code == 401
    assert authorized.status_code == 404
