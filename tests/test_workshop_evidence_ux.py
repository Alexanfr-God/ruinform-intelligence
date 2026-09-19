from ruinform_intelligence.build_models import BuildCriticReview, BuildPlan, BuildStep, MeasurementRequirement
from ruinform_intelligence.workshop_evidence_ux import (
    build_workshop_evidence_panel,
    derive_workshop_evidence_request,
)


def _plan() -> BuildPlan:
    return BuildPlan(
        plan_version="build_master_v1",
        candidate_id="candidate_01",
        title="Wall folio",
        plan_mode="concept_prototype",
        result_description="A chain-mounted wall folio.",
        difficulty="moderate",
        estimated_time_minutes=None,
        known_facts=["Wall-mounted approved visual."],
        measurements_required=[
            MeasurementRequirement(
                measurement_id="M1_chain_geometry",
                what_to_measure="Chain total usable length and link opening geometry.",
                how_to_measure="Measure the real chain with a ruler and calipers.",
                used_for="Leaf positions and connector geometry.",
                blocks_step_numbers=[2],
            ),
            MeasurementRequirement(
                measurement_id="M4_full_scale_layout_behavior",
                what_to_measure="Sag, curl, overlap and projection in the full-scale reversible mock-up.",
                how_to_measure="Support the actual pieces temporarily on a rigid mock-up board.",
                used_for="Final silhouette before irreversible work.",
                blocks_step_numbers=[3],
            ),
            MeasurementRequirement(
                measurement_id="M6_completed_assembly_mass",
                what_to_measure="Mass of the completed assembly.",
                how_to_measure="Weigh the complete assembly after production leaves are fastened.",
                used_for="Mounting hardware capacity.",
                blocks_step_numbers=[5],
            ),
            MeasurementRequirement(
                measurement_id="M7_wall_conditions",
                what_to_measure="Wall substrate and concealed services.",
                how_to_measure="Confirm from records/inspection and scan drilling areas.",
                used_for="Safe mounting location and hardware compatibility.",
                blocks_step_numbers=[5],
            ),
        ],
        engineering_assumptions=[],
        added_materials=[],
        tools=[],
        substitute_options=[],
        preparation_checks=[],
        steps=[
            BuildStep(
                step_number=1,
                title="Mock up",
                action="Create reversible mock-up.",
                source_material_ids=[],
                added_materials=[],
                tools=[],
                verify="Silhouette is visible.",
                stop_if=[],
            )
        ],
        unresolved_before_use=[],
        safety_gates=[],
        final_verification=[],
        maker_note="Prototype.",
    )


def _review() -> BuildCriticReview:
    return BuildCriticReview(
        candidate_id="candidate_01",
        status="revise",
        evidence_grounding_score=90,
        physical_credibility_score=70,
        sequence_quality_score=76,
        visual_fidelity_score=88,
        completeness_score=82,
        safety_completeness_score=78,
        reasons=["Mounting load and wall conditions need evidence."],
        required_changes=[
            "[UNVERIFIED_LOAD] Determine center-of-mass offset, support reactions and moment before selecting anchors.",
            "[HIDDEN_ASSUMPTION] Confirm whether the folded tab is integral or separate material.",
        ],
        blocking_unknowns=[],
    )


def test_request_is_phase_aware_and_defers_completed_mass() -> None:
    request = derive_workshop_evidence_request(plan=_plan(), review=_review(), candidate_id="candidate_01")
    assert request is not None
    assert request.version == "build_evidence_request_v2"
    phases = {task.task_id: task.phase for task in request.tasks}
    assert phases["measure_m1_chain_geometry"] == "now"
    assert phases["measure_m4_full_scale_layout_behavior"] == "after_mockup"
    assert phases["measure_m6_completed_assembly_mass"] == "after_assembly"
    assert phases["measure_m7_wall_conditions"] == "now"


def test_unverified_load_asks_for_raw_facts_not_engineering_math() -> None:
    request = derive_workshop_evidence_request(plan=_plan(), review=_review(), candidate_id="candidate_01")
    assert request is not None
    task = next(task for task in request.tasks if "unverified_load" in task.task_id)
    assert task.phase == "now"
    text = task.instruction.lower()
    assert "do not calculate" in text
    assert "ruinform must derive" in text


def test_panel_exposes_only_active_phase_controls_and_shows_later_queue() -> None:
    panel = build_workshop_evidence_panel(
        session_id="session-1",
        plan=_plan(),
        review=_review(),
        candidate_id="candidate_01",
        evidence_round_count=0,
    )
    assert "RFM-INT-0024.2 / WORKSHOP EVIDENCE" in panel
    assert "DO THIS NOW" in panel
    assert "You provide raw facts. RUINFORM does the engineering." in panel
    assert "LATER / AFTER MOCK-UP" in panel
    assert "LATER / AFTER ASSEMBLY" in panel
    assert "LOCKED UNTIL THIS PHASE" in panel
    # Later tasks are informational cards, not extra answer controls.
    assert "answer__measure_m6_completed_assembly_mass" not in panel
    assert "/studio/session-1/build/evidence" in panel
