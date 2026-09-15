import pytest

from ruinform_intelligence.form_architect import FormArchitectError, _validate_candidate_pool
from ruinform_intelligence.future_models import (
    CandidateForm,
    CandidatePool,
    FeasibilityReview,
    FuturePreferences,
    MaterialUse,
    RevisionRecord,
)
from ruinform_intelligence.future_pipeline import (
    prioritize_revision_candidates,
    rank_score,
    select_top_futures,
)
from ruinform_intelligence.models import MaterialItem, ProjectState


def _candidate(candidate_id: str, material_id: str) -> CandidateForm:
    return CandidateForm(
        candidate_id=candidate_id,
        name=f"Future {candidate_id}",
        one_line="A materially honest transformation.",
        category="functional_art",
        artistic_thesis="Preserve the source trace while changing its role.",
        transformation_logic="Reconfigure existing matter into a new composition.",
        material_uses=[
            MaterialUse(
                material_item_id=material_id,
                role="primary body",
                estimated_fraction=None,
                note=None,
            )
        ],
        added_materials=[],
        required_tools=[],
        key_operations=["reconfigure"],
        unresolved_dependencies=[],
    )


def _review(
    candidate_id: str,
    *,
    status: str = "pass",
    originality: int = 80,
    usefulness: int = 60,
) -> FeasibilityReview:
    return FeasibilityReview(
        candidate_id=candidate_id,
        status=status,
        feasibility_score=85,
        material_fit_score=90,
        buildability_score=75,
        originality_score=originality,
        artistic_impact_score=88,
        usefulness_score=usefulness,
        value_potential_score=70,
        reasons=[],
        required_changes=[],
        unresolved_dependencies=[],
    )


def test_candidate_pool_rejects_unknown_material_ids() -> None:
    material = MaterialItem(item_id="material_1", display_name="denim")
    state = ProjectState(materials=[material])
    pool = CandidatePool(
        candidates=[_candidate(f"candidate_{index:02d}", "missing") for index in range(1, 7)]
    )

    with pytest.raises(FormArchitectError, match="unknown material IDs"):
        _validate_candidate_pool(pool=pool, state=state, preferences=FuturePreferences())


def test_rank_score_respects_user_priorities() -> None:
    review = _review("candidate_01", originality=95, usefulness=20)
    originality_first = FuturePreferences(
        originality=3,
        artistic_impact=1,
        usefulness=0,
        ease=0,
        value=0,
    )
    usefulness_first = FuturePreferences(
        originality=0,
        artistic_impact=0,
        usefulness=3,
        ease=0,
        value=0,
    )

    assert rank_score(review, originality_first) > rank_score(review, usefulness_first)


def test_revision_queue_prioritizes_strongest_revisable_candidates() -> None:
    pool = CandidatePool(
        candidates=[
            _candidate("candidate_01", "material_1"),
            _candidate("candidate_02", "material_1"),
            _candidate("candidate_03", "material_1"),
        ]
    )
    reviews = {
        "candidate_01": _review("candidate_01", status="revise", originality=60),
        "candidate_02": _review("candidate_02", status="revise", originality=95),
        "candidate_03": _review("candidate_03", status="pass", originality=100),
    }

    queued = prioritize_revision_candidates(
        pool=pool,
        reviews_by_id=reviews,
        preferences=FuturePreferences(originality=3, usefulness=0, artistic_impact=0, ease=0, value=0),
        limit=1,
    )

    assert [candidate.candidate_id for candidate in queued] == ["candidate_02"]


def test_selection_hides_non_passing_candidates() -> None:
    material_id = "material_1"
    pool = CandidatePool(
        candidates=[
            _candidate("candidate_01", material_id),
            _candidate("candidate_02", material_id),
            _candidate("candidate_03", material_id),
        ]
    )
    reviews = {
        "candidate_01": _review("candidate_01", status="pass", originality=80),
        "candidate_02": _review("candidate_02", status="reject", originality=100),
        "candidate_03": _review("candidate_03", status="pass", originality=70),
    }

    selected = select_top_futures(
        pool=pool,
        reviews_by_id=reviews,
        preferences=FuturePreferences(),
        limit=3,
    )

    assert [item.candidate.candidate_id for item in selected] == ["candidate_01", "candidate_03"]


def test_selection_preserves_revision_lineage() -> None:
    before = _candidate("candidate_01", "material_1")
    after = before.model_copy(update={"name": "Future candidate_01 revised"})
    history = [
        RevisionRecord(
            round_index=1,
            critique_status="revise",
            requested_changes=["reduce unsupported span"],
            candidate_before=before,
            candidate_after=after,
        )
    ]

    selected = select_top_futures(
        pool=CandidatePool(candidates=[after]),
        reviews_by_id={"candidate_01": _review("candidate_01")},
        preferences=FuturePreferences(),
        revision_history_by_id={"candidate_01": history},
        limit=1,
    )

    assert selected[0].revision_history[0].candidate_before.name == before.name
    assert selected[0].revision_history[0].candidate_after.name == after.name
