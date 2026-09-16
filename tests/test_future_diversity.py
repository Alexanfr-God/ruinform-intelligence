from ruinform_intelligence.future_models import (
    CandidateForm,
    CandidatePool,
    FeasibilityReview,
    FuturePreferences,
    MaterialUse,
)
from ruinform_intelligence.future_pipeline import select_top_futures


def _candidate(candidate_id: str, category: str) -> CandidateForm:
    return CandidateForm(
        candidate_id=candidate_id,
        name=candidate_id,
        one_line="future",
        category=category,
        artistic_thesis="thesis",
        transformation_logic="transform",
        material_uses=[
            MaterialUse(
                material_item_id="material_1",
                role="body",
                estimated_fraction=None,
                note=None,
            )
        ],
        added_materials=[],
        required_tools=[],
        key_operations=["fold"],
        unresolved_dependencies=[],
    )


def _review(candidate_id: str, score: int) -> FeasibilityReview:
    return FeasibilityReview(
        candidate_id=candidate_id,
        status="pass",
        feasibility_score=score,
        material_fit_score=score,
        buildability_score=score,
        originality_score=score,
        artistic_impact_score=score,
        usefulness_score=score,
        value_potential_score=score,
        reasons=[],
        required_changes=[],
        unresolved_dependencies=[],
    )


def test_visible_futures_prefer_category_diversity() -> None:
    pool = CandidatePool(
        candidates=[
            _candidate("candidate_01", "sculpture"),
            _candidate("candidate_02", "sculpture"),
            _candidate("candidate_03", "lighting"),
            _candidate("candidate_04", "utility"),
        ]
    )
    reviews = {
        "candidate_01": _review("candidate_01", 95),
        "candidate_02": _review("candidate_02", 94),
        "candidate_03": _review("candidate_03", 90),
        "candidate_04": _review("candidate_04", 89),
    }

    selected = select_top_futures(
        pool=pool,
        reviews_by_id=reviews,
        preferences=FuturePreferences(),
        limit=3,
    )

    assert [item.candidate.candidate_id for item in selected] == [
        "candidate_01",
        "candidate_03",
        "candidate_04",
    ]
