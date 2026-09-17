from fastapi.testclient import TestClient

from ruinform_intelligence.server import app
from ruinform_intelligence.studio_controls import router as studio_controls_router


def test_project_controls_route_is_registered() -> None:
    paths = {
        route.path
        for route in studio_controls_router.routes
        if hasattr(route, "path")
    }
    assert "/studio/{session_id}/controls" in paths


def test_legacy_lab_session_navigation_redirects_studio_cookie() -> None:
    client = TestClient(app)
    client.cookies.set("ruinform_studio_session", "present")
    response = client.get(
        "/lab/example-session-id",
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/studio/example-session-id"
