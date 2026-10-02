from ruinform_intelligence.future_models import (
    CandidateForm,
    FeasibilityReview,
    FutureFormsResult,
    MaterialUse,
    ReviewedFuture,
)
from ruinform_intelligence.live_futures import (
    _semantic_motif,
    _transformation_family,
    _visible_preview,
)


def _future(
    candidate_id: str,
    *,
    rank: float,
    logic: str,
    operations: list[str],
    artistic_thesis: str,
    material_ids: list[str],
    category: str = "functional_art",
    status: str = "pass",
    name: str | None = None,
    one_line: str | None = None,
) -> ReviewedFuture:
    candidate = CandidateForm(
        candidate_id=candidate_id,
        name=name or candidate_id,
        one_line=one_line or logic,
        category=category,
        artistic_thesis=artistic_thesis,
        transformation_logic=logic,
        material_uses=[
            MaterialUse(
                material_item_id=material_id,
                role="necessary",
                estimated_fraction=None,
                note=None,
            )
            for material_id in material_ids
        ],
        added_materials=[],
        required_tools=[],
        key_operations=operations,
        unresolved_dependencies=[],
    )
    review = FeasibilityReview(
        candidate_id=candidate_id,
        status=status,
        feasibility_score=80,
        material_fit_score=80,
        buildability_score=80,
        originality_score=85,
        artistic_impact_score=85,
        usefulness_score=70,
        value_potential_score=80,
        reasons=["credible"],
        required_changes=[],
        unresolved_dependencies=[],
    )
    return ReviewedFuture(candidate=candidate, review=review, rank_score=rank)


def test_transformation_family_detects_distinct_operator_types() -> None:
    folded = _future(
        "folded",
        rank=90,
        logic="Bend and fold the plate into a curved shell.",
        operations=["bend", "fold"],
        artistic_thesis="Domestic rigidity becomes protective shelter.",
        material_ids=["a"],
    )
    cascade = _future(
        "cascade",
        rank=88,
        logic="Repeat the rings in a progressive cascade.",
        operations=["repeat", "scale"],
        artistic_thesis="Value grows through repetition.",
        material_ids=["a", "b"],
    )
    assert _transformation_family(folded) == "reform"
    assert _transformation_family(cascade) == "repeat_scale"


def test_transformation_family_prefers_literal_operations_over_poetic_copy() -> None:
    future = _future(
        "horizon",
        rank=89,
        logic="Register the intact bottle inside a field so the horizon appears bent.",
        operations=["position", "register"],
        artistic_thesis="A stable horizon develops one optical fault.",
        material_ids=["a", "b"],
        one_line="The bottle bends a continuous horizon into an optical fault.",
    )
    assert _transformation_family(future) == "arrangement"


def test_semantic_motif_treats_fault_fissure_and_broken_as_one_family() -> None:
    faultline = _future(
        "faultline",
        rank=92,
        logic="Arrange stones around one deliberate opening.",
        operations=["arrange"],
        artistic_thesis="A fissure interrupts an otherwise stable field.",
        material_ids=["a", "b"],
        name="Faultline Table Field",
        one_line="A broken ring gathers around a fissure.",
    )
    horizon = _future(
        "horizon",
        rank=90,
        logic="Position a bottle through wire rings.",
        operations=["position"],
        artistic_thesis="One optical fault breaks a disciplined horizon.",
        material_ids=["b", "c"],
        name="Broken Horizon Vessel",
    )
    assert _semantic_motif(faultline) == "fracture"
    assert _semantic_motif(horizon) == "fracture"


def test_visible_preview_prefers_a_physically_and_semantically_diverse_second_future() -> None:
    strongest = _future(
        "preview_01",
        rank=92,
        logic="Arrange stones around one deliberate opening.",
        operations=["arrange"],
        artistic_thesis="A fissure interrupts an otherwise stable field.",
        material_ids=["a", "b"],
        name="Faultline Table Field",
    )
    semantic_sibling = _future(
        "preview_02",
        rank=91,
        logic="Position a bottle through a disciplined wire field.",
        operations=["position"],
        artistic_thesis="One optical fault breaks a continuous horizon.",
        material_ids=["b", "c"],
        name="Broken Horizon Vessel",
    )
    different = _future(
        "preview_03",
        rank=86,
        logic="Cut open the second source to reveal a negative-space frame.",
        operations=["cut", "reveal"],
        artistic_thesis="Absence becomes the part that carries attention.",
        material_ids=["c"],
        category="sculpture",
    )
    result = FutureFormsResult(
        internal_candidate_count=3,
        reviewed_candidate_count=3,
        selected_futures=[strongest, semantic_sibling, different],
    )

    visible = _visible_preview(result)
    assert [item.candidate.candidate_id for item in visible.selected_futures] == [
        "preview_01",
        "preview_03",
    ]


def test_visible_preview_does_not_choose_revise_for_diversity_when_two_pass_exist() -> None:
    strongest = _future(
        "preview_01",
        rank=92,
        logic="Fold the source into a shallow curved body.",
        operations=["bend", "fold"],
        artistic_thesis="Protection emerges from deformation.",
        material_ids=["a"],
    )
    second_pass = _future(
        "preview_02",
        rank=88,
        logic="Fold the second source around a void.",
        operations=["bend"],
        artistic_thesis="A protected absence becomes useful space.",
        material_ids=["b"],
    )
    tempting_revise = _future(
        "preview_03",
        rank=89,
        logic="Cut and reveal a radical negative-space frame.",
        operations=["cut", "reveal"],
        artistic_thesis="Absence becomes the part that carries attention.",
        material_ids=["c"],
        category="sculpture",
        status="revise",
    )
    result = FutureFormsResult(
        internal_candidate_count=3,
        reviewed_candidate_count=3,
        selected_futures=[strongest, tempting_revise, second_pass],
    )

    visible = _visible_preview(result)
    assert [item.review.status for item in visible.selected_futures] == ["pass", "pass"]
    assert [item.candidate.candidate_id for item in visible.selected_futures] == [
        "preview_01",
        "preview_02",
    ]
