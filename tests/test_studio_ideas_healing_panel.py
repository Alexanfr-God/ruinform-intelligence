from ruinform_intelligence.idea_store import IdeaBatch
from ruinform_intelligence.studio_ideas import _self_healing_panel


def _item(trace: dict) -> IdeaBatch:
    return IdeaBatch(
        batch_id="batch",
        session_id="session",
        project_id="project",
        background_mode="ruinform_world",
        difficulty_mode="medium",
        source_items=["umbrella", "chain"],
        source_material_ids=["m1", "m2"],
        futures_snapshot={"selected_futures": [], "retrieval_trace": trace},
    )


def test_self_healing_panel_shows_before_after_and_remaining_rejects() -> None:
    html = _self_healing_panel(
        _item(
            {
                "self_healing": {
                    "version": "wave3_self_healing_v1",
                    "enabled": True,
                    "attempted": True,
                    "targets": [
                        {
                            "candidate_id": "preview_04",
                            "action": "replace",
                            "before_name": "Old Reject",
                            "after_name": "New Attempt",
                            "before_status": "reject",
                            "after_status": "reject",
                            "remaining_required_changes": ["simplify"],
                        }
                    ],
                    "remaining_rejects": ["preview_04"],
                    "policy": "one pass only",
                }
            }
        )
    )

    assert "SELF-HEALING AUDIT" in html
    assert "Old Reject" in html
    assert "New Attempt" in html
    assert "still rejected" in html
    assert "preview_04" in html


def test_self_healing_panel_surfaces_fallback_error() -> None:
    html = _self_healing_panel(
        _item(
            {
                "self_healing": {
                    "version": "wave3_self_healing_v1",
                    "enabled": True,
                    "attempted": True,
                    "error": "repair failed",
                    "fallback": "original_flagged_candidates_preserved",
                    "targets": [],
                }
            }
        )
    )

    assert "FALLBACK" in html
    assert "repair failed" in html
    assert "original_flagged_candidates_preserved" in html
