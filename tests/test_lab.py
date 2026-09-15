from fastapi.testclient import TestClient

from ruinform_intelligence.server import app


def test_lab_requires_basic_auth(monkeypatch) -> None:
    monkeypatch.setenv("RUINFORM_LAB_PASSWORD", "test-password")
    client = TestClient(app)
    response = client.get("/lab")
    assert response.status_code == 401


def test_lab_opens_with_valid_credentials(monkeypatch) -> None:
    monkeypatch.setenv("RUINFORM_LAB_USER", "maker")
    monkeypatch.setenv("RUINFORM_LAB_PASSWORD", "test-password")
    client = TestClient(app)
    response = client.get("/lab", auth=("maker", "test-password"))
    assert response.status_code == 200
    assert "RUINFORM INTELLIGENCE" in response.text
    assert "READ" in response.text
