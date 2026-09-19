from ruinform_intelligence.future_models import FeasibilityReview
from ruinform_intelligence.studio import _critic_panel, _critic_tags


def _review(status: str, changes: list[str]) -> FeasibilityReview:
    return FeasibilityReview(
        candidate_id="preview_01",
        status=status,
        feasibility_score=72,
        material_fit_score=80,
        buildability_score=68,
        originality_score=84,
        artistic_impact_score=88,
        usefulness_score=40,
        value_potential_score=82,
        reasons=["Strong source-driven gesture."],
        required_changes=changes,
        unresolved_dependencies=[],
    )


def test_critic_tags_extract_standardized_flags() -> None:
    tags = _critic_tags(
        [
            "[MECHANISM_CREEP] simplify the linkage",
            "[SOURCE_ROLE_REPETITION] change the dominant source",
            "plain note",
        ]
    )
    assert tags == ["MECHANISM_CREEP", "SOURCE_ROLE_REPETITION"]


def test_critic_panel_exposes_status_tags_and_changes() -> None:
    panel = _critic_panel(
        _review("revise", ["[MECHANISM_CREEP] Remove the secondary linkage."])
    )
    assert "PRE-RENDER CRITIC / REVISE" in panel
    assert "MECHANISM_CREEP" in panel
    assert "Remove the secondary linkage" in panel
