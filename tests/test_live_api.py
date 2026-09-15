from ruinform_intelligence.server import app


def test_live_transformation_routes_registered() -> None:
    paths = set(app.openapi()["paths"])
    assert "/v1/live-transformations/start" in paths
    assert "/v1/live-transformations/{session_id}" in paths
    assert "/v1/live-transformations/{session_id}/futures" in paths
    assert "/v1/live-transformations/{session_id}/render/{candidate_id}" in paths
