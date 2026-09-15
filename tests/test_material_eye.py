import pytest

from ruinform_intelligence.material_eye import (
    MaterialEyeError,
    MaterialEyeOutput,
    MaterialOutput,
    ObservationOutput,
    UnknownOutput,
    _to_project_state,
)
from ruinform_intelligence.models import ClaimKind, EvidenceItem, ProjectConstraints


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
