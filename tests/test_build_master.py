import pytest

from ruinform_intelligence.build_master import BuildMasterError, _build_user_content, _validate_plan
from ruinform_intelligence.build_models import BuildPlan, BuildStep
from ruinform_intelligence.future_models import CandidateForm, FeasibilityReview, MaterialUse, ReviewedFuture
from ruinform_intelligence.models import MaterialItem, ProjectState


def _future(material_id: str = "material_1") -> ReviewedFuture:
    candidate = CandidateForm(
        candidate_id="candidate_01",
        name="Desk object",
        one_line="A simple transformed object.",
        category="functional_art",
        artistic_thesis="Keep source matter visible.",
        transformation_logic="Wrap and fasten the source matter into a new form.",
        material_uses=[
            MaterialUse(
                material_item_id=material_id,
                role="body",
                estimated_fraction=None,
                note=None,
            )
        ],
        added_materials=["zip ties"],
        required_tools=["scissors"],
        key_operations=["wrap", "fasten"],
        unresolved_dependencies=[],
    )
    review = FeasibilityReview(
        candidate_id="candidate_01",
        status="pass",
        feasibility_score=90,
        material_fit_score=90,
        buildability_score=90,
        originality_score=80,
        artistic_impact_score=80,
        usefulness_score=70,
        value_potential_score=70,
        reasons=[],
        required_changes=[],
        unresolved_dependencies=[],
    )
    return ReviewedFuture(candidate=candidate, review=review, rank_score=88)


def _plan(source_id: str = "material_1") -> BuildPlan:
    return BuildPlan(
        candidate_id="candidate_01",
        title="Prototype plan",
        plan_mode="concept_prototype",
        result_description="A small handmade transformed object.",
        difficulty="easy",
        estimated_time_minutes=30,
        added_materials=["zip ties"],
        tools=["scissors"],
        preparation_checks=["Inspect the source item."],
        steps=[
            BuildStep(
                step_number=1,
                title="Fit",
                action="Wrap the source matter and mark directly against the real object.",
                source_material_ids=[source_id],
                added_materials=[],
                tools=[],
                verify="The wrap sits without forced tension.",
                stop_if=[],
            ),
            BuildStep(
                step_number=2,
                title="Fasten",
                action="Secure the fitted form with the declared fastener.",
                source_material_ids=[source_id],
                added_materials=["zip ties"],
                tools=["scissors"],
                verify="The object keeps its intended shape.",
                stop_if=[],
            ),
        ],
        unresolved_before_use=[],
        safety_gates=[],
        final_verification=["Check all joins."],
        maker_note="Prototype first, refine second.",
    )


def test_build_plan_accepts_known_source_materials() -> None:
    state = ProjectState(materials=[MaterialItem(item_id="material_1", display_name="source")])
    _validate_plan(plan=_plan(), state=state, future=_future())


def test_build_plan_rejects_unknown_source_materials() -> None:
    state = ProjectState(materials=[MaterialItem(item_id="material_1", display_name="source")])
    with pytest.raises(BuildMasterError, match="unknown source material IDs"):
        _validate_plan(plan=_plan("invented_material"), state=state, future=_future())


def test_build_user_content_attaches_approved_render() -> None:
    state = ProjectState(materials=[MaterialItem(item_id="material_1", display_name="source")])
    content = _build_user_content(
        state=state,
        future=_future(),
        plan_mode="concept_prototype",
        render_image_url="https://example.com/approved-render.jpg",
    )

    assert content[0]["type"] == "input_text"
    assert "visual target" in content[0]["text"]
    assert content[1] == {
        "type": "input_image",
        "image_url": "https://example.com/approved-render.jpg",
        "detail": "high",
    }


def test_build_user_content_works_without_render() -> None:
    state = ProjectState(materials=[MaterialItem(item_id="material_1", display_name="source")])
    content = _build_user_content(
        state=state,
        future=_future(),
        plan_mode="verified",
        render_image_url=None,
    )

    assert len(content) == 1
    assert content[0]["type"] == "input_text"
