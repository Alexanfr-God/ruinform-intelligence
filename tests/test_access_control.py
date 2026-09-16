from fastapi.testclient import TestClient

from ruinform_intelligence.server import app


def test_health_is_public(monkeypatch) -> None:
    monkeypatch.delenv("RUINFORM_API_TOKEN", raising=False)
    response = TestClient(app).get("/health")
    assert response.status_code == 200


def test_studio_auth_routes_bypass_api_token_gateway(monkeypatch) -> None:
    monkeypatch.setenv("RUINFORM_API_TOKEN", "test-token")
    monkeypatch.setenv("RUINFORM_LAB_USER", "alex")
    monkeypatch.setenv("RUINFORM_LAB_PASSWORD", "studio-secret")
    client = TestClient(app)

    login = client.get("/studio-login")
    assert login.status_code == 200
    assert "RUINFORM / PRIVATE STUDIO" in login.text

    deep_link = client.get("/studio/missing", follow_redirects=False)
    assert deep_link.status_code == 303
    assert deep_link.headers["location"].startswith("/studio-login?next=/studio/missing")


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
