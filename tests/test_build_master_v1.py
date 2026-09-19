import asyncio

import pytest

import ruinform_intelligence.build_master as build_master
from ruinform_intelligence.build_master import BuildMasterError, _validate_plan
from ruinform_intelligence.build_models import (
    BuildCriticReview,
    BuildPlan,
    BuildStep,
    MeasurementRequirement,
)
from ruinform_intelligence.future_models import CandidateForm, FeasibilityReview, MaterialUse, ReviewedFuture
from ruinform_intelligence.models import EvidenceItem, MaterialItem, ProjectState


def _future() -> ReviewedFuture:
    candidate = CandidateForm(
        candidate_id="candidate_01",
        name="Captured source",
        one_line="A source object captured in a simple support.",
        category="functional_art",
        artistic_thesis="Keep source provenance visible.",
        transformation_logic="Measure the real source and capture it with a fitted support.",
        material_uses=[MaterialUse(material_item_id="material_1", role="body", estimated_fraction=None, note=None)],
        added_materials=["support stock"],
        required_tools=["drill"],
        key_operations=["measure", "capture"],
        unresolved_dependencies=[],
    )
    review = FeasibilityReview(
        candidate_id="candidate_01",
        status="pass",
        feasibility_score=85,
        material_fit_score=85,
        buildability_score=82,
        originality_score=75,
        artistic_impact_score=78,
        usefulness_score=72,
        value_potential_score=74,
        reasons=["Plausible fitted support."],
        required_changes=[],
        unresolved_dependencies=[],
    )
    return ReviewedFuture(candidate=candidate, review=review, rank_score=80)


def _plan(action: str = "Measure the real source and mark the support directly.") -> BuildPlan:
    return BuildPlan(
        plan_version="build_master_v1",
        candidate_id="candidate_01",
        title="Prototype plan",
        plan_mode="concept_prototype",
        result_description="A fitted support that preserves the source silhouette.",
        difficulty="moderate",
        estimated_time_minutes=60,
        known_facts=["The source item exists and is identified as material_1."],
        measurements_required=[
            MeasurementRequirement(
                measurement_id="M1",
                what_to_measure="Real source width at the capture point.",
                how_to_measure="Measure directly across the physical source at the intended support location.",
                used_for="Set the support opening without guessing.",
                blocks_step_numbers=[2],
            )
        ],
        engineering_assumptions=["The support geometry can be adjusted after a reversible dry fit."],
        added_materials=["support stock"],
        tools=["drill"],
        substitute_options=[],
        preparation_checks=["Inspect the source for cracks or loose parts."],
        steps=[
            BuildStep(
                step_number=1,
                title="Measure and mock up",
                action=action,
                source_material_ids=["material_1"],
                added_materials=[],
                tools=[],
                verify="The measurement and mock-up describe the real contact area.",
                stop_if=["The source is damaged at the intended capture point."],
            ),
            BuildStep(
                step_number=2,
                title="Fit the support",
                action="Trim the support to the measured fit and capture the source without forced deformation.",
                source_material_ids=["material_1"],
                added_materials=["support stock"],
                tools=["drill"],
                verify="The source is stable and the approved silhouette is preserved.",
                stop_if=["The support requires forced deformation of the source."],
            ),
        ],
        unresolved_before_use=["Real-use load capacity has not been verified."],
        safety_gates=["Do not claim load-bearing capacity without a physical test."],
        final_verification=["Compare silhouette and source placement with the approved render."],
        maker_note="Prototype only until the remaining use conditions are verified.",
    )


def _state(*, measured: bool = False) -> ProjectState:
    evidence = []
    if measured:
        evidence.append(
            EvidenceItem(
                source_type="measurement",
                text="Measured source width is 42 cm.",
                value=42,
                unit="cm",
            )
        )
    return ProjectState(
        materials=[MaterialItem(item_id="material_1", display_name="source item")],
        evidence=evidence,
    )


def _engineering_review(status: str) -> BuildCriticReview:
    changes = ["[MISSING_MEASUREMENT] Keep the unknown width measure-to-fit."] if status == "revise" else []
    return BuildCriticReview(
        candidate_id="candidate_01",
        status=status,
        evidence_grounding_score=82,
        physical_credibility_score=80,
        sequence_quality_score=84,
        visual_fidelity_score=88,
        completeness_score=78,
        safety_completeness_score=81,
        reasons=["The plan is grounded enough for prototype work."],
        required_changes=changes,
        blocking_unknowns=[],
    )


def test_legacy_build_plan_payload_is_upgraded_without_breaking_old_sessions() -> None:
    payload = _plan().model_dump()
    for key in (
        "plan_version",
        "known_facts",
        "measurements_required",
        "engineering_assumptions",
        "substitute_options",
    ):
        payload.pop(key)
    loaded = BuildPlan.model_validate(payload)
    assert loaded.plan_version == "legacy_v0_2"
    assert loaded.measurements_required == []


def test_build_master_rejects_invented_physical_number() -> None:
    plan = _plan(action="Cut the support to 42 cm before checking the real source.")
    with pytest.raises(BuildMasterError, match="invented physical numbers"):
        _validate_plan(plan=plan, state=_state(measured=False), future=_future())


def test_build_master_allows_physical_number_present_in_project_evidence() -> None:
    plan = _plan(action="Use the verified 42 cm source width as the reference for the mock-up.")
    _validate_plan(plan=plan, state=_state(measured=True), future=_future())


def test_measurement_requirement_cannot_reference_missing_step() -> None:
    plan = _plan().model_copy(
        update={
            "measurements_required": [
                MeasurementRequirement(
                    measurement_id="M_BAD",
                    what_to_measure="Source width.",
                    how_to_measure="Measure directly.",
                    used_for="Support fit.",
                    blocks_step_numbers=[9],
                )
            ]
        }
    )
    with pytest.raises(BuildMasterError, match="unknown build steps"):
        _validate_plan(plan=plan, state=_state(), future=_future())


def test_reviewed_build_package_repairs_revise_exactly_once(monkeypatch) -> None:
    plan = _plan()
    reviews = [_engineering_review("revise"), _engineering_review("pass")]
    calls = {"draft": 0, "repair": 0, "review": 0}

    async def fake_generate_build_plan(**kwargs):
        calls["draft"] += 1
        return plan

    async def fake_revise_build_plan(**kwargs):
        calls["repair"] += 1
        return plan

    async def fake_review_build_plan(**kwargs):
        calls["review"] += 1
        return reviews.pop(0)

    monkeypatch.setattr(build_master, "generate_build_plan", fake_generate_build_plan)
    monkeypatch.setattr(build_master, "revise_build_plan", fake_revise_build_plan)
    monkeypatch.setattr(build_master, "review_build_plan", fake_review_build_plan)

    package = asyncio.run(
        build_master.generate_reviewed_build_package(
            state=_state(),
            future=_future(),
            accepted_image_url="https://example.test/approved.png",
            concept_mode=True,
            client=object(),
        )
    )

    assert calls == {"draft": 1, "repair": 1, "review": 2}
    assert package.review.status == "pass"
    assert package.revision_trace.attempted is True
    assert package.revision_trace.before_status == "revise"
    assert package.revision_trace.after_status == "pass"


def test_reviewed_build_package_does_not_auto_repair_block(monkeypatch) -> None:
    plan = _plan()
    calls = {"repair": 0}

    async def fake_generate_build_plan(**kwargs):
        return plan

    async def fake_review_build_plan(**kwargs):
        review = _engineering_review("block")
        return review.model_copy(update={"blocking_unknowns": ["Source frame condition is unknown."]})

    async def fake_revise_build_plan(**kwargs):
        calls["repair"] += 1
        return plan

    monkeypatch.setattr(build_master, "generate_build_plan", fake_generate_build_plan)
    monkeypatch.setattr(build_master, "review_build_plan", fake_review_build_plan)
    monkeypatch.setattr(build_master, "revise_build_plan", fake_revise_build_plan)

    package = asyncio.run(
        build_master.generate_reviewed_build_package(
            state=_state(),
            future=_future(),
            accepted_image_url="https://example.test/approved.png",
            concept_mode=True,
            client=object(),
        )
    )

    assert calls["repair"] == 0
    assert package.review.status == "block"
    assert package.revision_trace.attempted is False
