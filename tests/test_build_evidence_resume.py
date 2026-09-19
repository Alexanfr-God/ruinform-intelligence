from ruinform_intelligence.build_evidence import (
    build_evidence_image_urls,
    build_evidence_panel,
    derive_build_evidence_request,
    parse_physical_value,
    state_for_build_candidate,
)
from ruinform_intelligence.build_models import (
    BuildCriticReview,
    BuildPlan,
    BuildStep,
    MeasurementRequirement,
)
from ruinform_intelligence.models import EvidenceItem, ProjectState


def _plan() -> BuildPlan:
    return BuildPlan(
        plan_version="build_master_v1",
        candidate_id="candidate_01",
        title="Wall folio",
        plan_mode="concept_prototype",
        result_description="A chain-mounted wall folio.",
        difficulty="moderate",
        estimated_time_minutes=None,
        known_facts=["The approved visual is wall mounted."],
        measurements_required=[
            MeasurementRequirement(
                measurement_id="M6_mass",
                what_to_measure="Completed assembly mass.",
                how_to_measure="Weigh the complete assembly on a suitable scale.",
                used_for="Mounting hardware capacity and wall support selection.",
                blocks_step_numbers=[2],
            ),
            MeasurementRequirement(
                measurement_id="M7_wall",
                what_to_measure="Wall substrate and sound anchoring locations.",
                how_to_measure="Confirm construction from records or qualified inspection.",
                used_for="Wall anchors, standoffs and drilling plan.",
                blocks_step_numbers=[2],
            ),
        ],
        engineering_assumptions=[],
        added_materials=["standoffs"],
        tools=["scale"],
        substitute_options=[],
        preparation_checks=["Inspect the wall."],
        steps=[
            BuildStep(
                step_number=1,
                title="Mock up",
                action="Create a reversible mock-up.",
                source_material_ids=[],
                added_materials=[],
                tools=[],
                verify="The silhouette matches.",
                stop_if=[],
            ),
            BuildStep(
                step_number=2,
                title="Mount",
                action="Install only after mounting evidence is verified.",
                source_material_ids=[],
                added_materials=["standoffs"],
                tools=["scale"],
                verify="Mounting remains stable.",
                stop_if=[],
            ),
        ],
        unresolved_before_use=[],
        safety_gates=["Do not drill into an unknown substrate."],
        final_verification=["Verify wall stability."],
        maker_note="Prototype only.",
    )


def _review(status: str = "revise") -> BuildCriticReview:
    return BuildCriticReview(
        candidate_id="candidate_01",
        status=status,
        evidence_grounding_score=90,
        physical_credibility_score=70,
        sequence_quality_score=76,
        visual_fidelity_score=88,
        completeness_score=82,
        safety_completeness_score=78,
        reasons=["Mounting load and wall conditions need real evidence."],
        required_changes=[
            "[UNVERIFIED_LOAD] Measure completed mass and confirm the wall substrate before selecting anchors.",
            "[SEQUENCE_ERROR] Move the mounting gate before irreversible drilling.",
        ],
        blocking_unknowns=[],
    )


def test_nonpass_review_becomes_concrete_evidence_request() -> None:
    request = derive_build_evidence_request(
        plan=_plan(),
        review=_review(),
        candidate_id="candidate_01",
    )
    assert request is not None
    assert request.version == "build_evidence_request_v1"
    assert 1 <= len(request.tasks) <= 5
    assert any(task.input_kind == "measurement" for task in request.tasks)
    assert any("mount" in (task.title + task.instruction + task.why_needed).lower() for task in request.tasks)


def test_pass_review_never_requests_more_evidence() -> None:
    assert derive_build_evidence_request(
        plan=_plan(),
        review=_review("pass"),
        candidate_id="candidate_01",
    ) is None


def test_build_evidence_is_scoped_to_selected_candidate() -> None:
    state = ProjectState(
        evidence=[
            EvidenceItem(evidence_id="source", source_type="user_statement", text="source fact"),
            EvidenceItem(
                evidence_id="a",
                source_type="measurement",
                property_key="build:candidate_01:measurement_mass",
                text="2.4 kg",
                value=2.4,
                unit="kg",
            ),
            EvidenceItem(
                evidence_id="b",
                source_type="image",
                property_key="build:candidate_02:mounting_photo",
                uri="data:image/jpeg;base64,AAAA",
            ),
        ]
    )
    filtered = state_for_build_candidate(state, "candidate_01")
    assert [item.evidence_id for item in filtered.evidence] == ["source", "a"]
    assert build_evidence_image_urls(filtered, "candidate_01") == []


def test_evidence_photo_is_exposed_only_for_matching_candidate() -> None:
    state = ProjectState(
        evidence=[
            EvidenceItem(
                evidence_id="photo",
                source_type="image",
                property_key="build:candidate_01:mounting_photo",
                uri="data:image/jpeg;base64,AAAA",
            )
        ]
    )
    assert build_evidence_image_urls(state, "candidate_01") == ["data:image/jpeg;base64,AAAA"]
    assert build_evidence_image_urls(state, "candidate_02") == []


def test_physical_value_parser_preserves_measurement_for_grounding() -> None:
    value, unit = parse_physical_value("Measured on a scale: 2.4 kg")
    assert value == 2.4
    assert unit == "kg"


def test_build_page_panel_resumes_same_project() -> None:
    panel = build_evidence_panel(
        session_id="session-1",
        plan=_plan(),
        review=_review(),
        candidate_id="candidate_01",
        evidence_round_count=0,
    )
    assert "RUINFORM NEEDS REAL-WORLD EVIDENCE" in panel
    assert "/studio/session-1/build/evidence" in panel
    assert "ADD EVIDENCE → RESUME BUILD" in panel
    assert "do not regenerate the image" in panel.lower()
