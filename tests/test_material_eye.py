import pytest

from ruinform_intelligence.material_eye import (
    MaterialEyeError,
    MaterialEyeOutput,
    MaterialOutput,
    ObservationOutput,
    UnknownOutput,
    _to_project_state,
)
from ruinform_intelligence.models import (
    ClaimKind,
    EvidenceItem,
    EvidenceRef,
    MaterialItem,
    MaterialObservation,
    ProjectConstraints,
    ProjectState,
)


def test_material_eye_maps_exact_evidence_and_blocks_on_critical_unknown():
    output = MaterialEyeOutput(
        analysis_summary="Likely steel tube with unresolved wall thickness.",
        materials=[
            MaterialOutput(
                display_name="Steel tube",
                observations=[
                    ObservationOutput(
                        property_key="material_family",
                        label="Material appears to be steel",
                        claim_kind="hypothesis",
                        confidence=0.86,
                        evidence_ids=["image_001"],
                        consequence_if_wrong="high",
                        change_type="new",
                        prior_observation_ids=[],
                    )
                ],
                unknowns=[
                    UnknownOutput(
                        property_key="wall_thickness",
                        question="What is the wall thickness?",
                        reason="Required before structural use can be evaluated.",
                        consequence_if_unresolved="high",
                        preferred_evidence=["photo of open end beside ruler", "caliper measurement"],
                    )
                ],
            )
        ],
        next_user_request="Photograph the open end beside a ruler.",
    )

    state = _to_project_state(
        output=output,
        evidence=[
            EvidenceItem(
                evidence_id="image_001",
                source_type="image",
                uri="https://example.com/tube.jpg",
            )
        ],
        constraints=ProjectConstraints(),
        project_id="project-1",
    )

    observation = state.materials[0].observations[0]
    assert state.project_id == "project-1"
    assert observation.claim_kind == ClaimKind.HYPOTHESIS
    assert observation.property_key == "material_family"
    assert observation.evidence[0].evidence_id == "image_001"
    assert observation.evidence[0].source_type == "image"
    assert len(state.unresolved_critical_unknowns) == 1
    assert state.next_user_request == "Photograph the open end beside a ruler."


def test_unknown_evidence_id_rejects_model_output():
    output = MaterialEyeOutput(
        analysis_summary="Visible textile.",
        materials=[
            MaterialOutput(
                display_name="Textile",
                observations=[
                    ObservationOutput(
                        property_key="surface_color",
                        label="Blue woven textile",
                        claim_kind="fact",
                        confidence=1.0,
                        evidence_ids=["image_999"],
                        consequence_if_wrong="low",
                        change_type="new",
                        prior_observation_ids=[],
                    )
                ],
                unknowns=[],
            )
        ],
        next_user_request=None,
    )

    with pytest.raises(MaterialEyeError, match="unknown evidence ids"):
        _to_project_state(
            output=output,
            evidence=[
                EvidenceItem(
                    evidence_id="image_001",
                    source_type="image",
                    uri="https://example.com/textile.jpg",
                )
            ],
            constraints=ProjectConstraints(),
            project_id=None,
        )


def _prior_state_for_lineage() -> ProjectState:
    image_ref = EvidenceRef(evidence_id="image_001", source_type="image")
    return ProjectState(
        project_id="project-lineage",
        evidence=[EvidenceItem(evidence_id="image_001", source_type="image", uri="data:image/jpeg;base64,abc")],
        materials=[
            MaterialItem(
                item_id="material_1",
                display_name="Bottle",
                observations=[
                    MaterialObservation(
                        observation_id="obs_color",
                        property_key="surface_color",
                        label="Green",
                        claim_kind=ClaimKind.FACT,
                        confidence=0.98,
                        evidence=[image_ref],
                    ),
                    MaterialObservation(
                        observation_id="obs_material",
                        property_key="material_family",
                        label="Appears to be glass",
                        claim_kind=ClaimKind.HYPOTHESIS,
                        confidence=0.88,
                        evidence=[image_ref],
                    ),
                ],
            )
        ],
    )


def test_followup_repairs_prior_property_mismatch_instead_of_dropping_user_turn():
    prior_state = _prior_state_for_lineage()
    evidence = [
        *prior_state.evidence,
        EvidenceItem(
            evidence_id="user_001",
            source_type="user_statement",
            text="Bottle is definitely glass.",
        ),
    ]
    output = MaterialEyeOutput(
        analysis_summary="User confirms glass.",
        materials=[
            MaterialOutput(
                display_name="Bottle",
                observations=[
                    ObservationOutput(
                        property_key="material_family",
                        label="User identifies the vessel as glass",
                        claim_kind="fact",
                        confidence=0.99,
                        evidence_ids=["user_001"],
                        consequence_if_wrong="medium",
                        change_type="revised",
                        # Simulates the exact live failure: model linked this property to another property.
                        prior_observation_ids=["obs_color"],
                    )
                ],
                unknowns=[],
            )
        ],
        next_user_request=None,
    )

    state = _to_project_state(
        output=output,
        evidence=evidence,
        constraints=ProjectConstraints(),
        project_id=prior_state.project_id,
        prior_state=prior_state,
    )

    observation = state.materials[0].observations[0]
    assert observation.change_type == "revised"
    assert observation.prior_observation_ids == ["obs_material"]


def test_followup_reclassifies_change_as_new_when_property_has_no_prior_lineage():
    prior_state = _prior_state_for_lineage()
    output = MaterialEyeOutput(
        analysis_summary="A new measurement was supplied.",
        materials=[
            MaterialOutput(
                display_name="Bottle",
                observations=[
                    ObservationOutput(
                        property_key="overall_height",
                        label="Height is 31 cm",
                        claim_kind="fact",
                        confidence=0.99,
                        evidence_ids=["measure_001"],
                        consequence_if_wrong="medium",
                        change_type="confirmed",
                        prior_observation_ids=["obs_material"],
                    )
                ],
                unknowns=[],
            )
        ],
        next_user_request=None,
    )

    state = _to_project_state(
        output=output,
        evidence=[
            *prior_state.evidence,
            EvidenceItem(
                evidence_id="measure_001",
                source_type="measurement",
                property_key="overall_height",
                value=31,
                unit="cm",
            ),
        ],
        constraints=ProjectConstraints(),
        project_id=prior_state.project_id,
        prior_state=prior_state,
    )

    observation = state.materials[0].observations[0]
    assert observation.change_type == "new"
    assert observation.prior_observation_ids == []
