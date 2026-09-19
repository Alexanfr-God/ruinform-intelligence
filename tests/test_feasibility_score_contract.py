from ruinform_intelligence.feasibility import _normalize_review_score_scale
from ruinform_intelligence.future_models import FeasibilityReview


def _review(score: int) -> FeasibilityReview:
    return FeasibilityReview(
        candidate_id="preview_01",
        status="revise",
        feasibility_score=score,
        material_fit_score=score,
        buildability_score=score,
        originality_score=score,
        artistic_impact_score=score,
        usefulness_score=score,
        value_potential_score=score,
        reasons=["test"],
        required_changes=["[MECHANISM_CREEP] simplify"],
        unresolved_dependencies=[],
    )


def test_normalizes_apparent_five_point_scale_to_hundred() -> None:
    normalized = _normalize_review_score_scale(_review(4))
    assert normalized.feasibility_score == 80
    assert normalized.artistic_impact_score == 80
    assert any("0–5 scale" in reason for reason in normalized.reasons)


def test_normalizes_apparent_ten_point_scale_to_hundred() -> None:
    normalized = _normalize_review_score_scale(_review(8))
    assert normalized.feasibility_score == 80
    assert normalized.value_potential_score == 80
    assert any("0–10 scale" in reason for reason in normalized.reasons)


def test_preserves_true_hundred_point_scores() -> None:
    original = _review(78)
    normalized = _normalize_review_score_scale(original)
    assert normalized.feasibility_score == 78
    assert normalized.reasons == ["test"]
