from ruinform_intelligence.material_eye import (
    MaterialEyeOutput,
    MaterialOutput,
    ObservationOutput,
    UnknownOutput,
    _to_project_state,
)
from ruinform_intelligence.models import ClaimKind, ProjectConstraints


def test_material_eye_maps_evidence_and_blocks_on_critical_unknown():
    output = MaterialEyeOutput(
        analysis_summary="Likely steel tube with unresolved wall thickness.",
        materials=[
            MaterialOutput(
                display_name="Steel tube",
                observations=[
                    ObservationOutput(
                        label="Material appears to be steel",
                        claim_kind="hypothesis",
                        confidence=0.86,
                        evidence_ids=["image_001"],
                        consequence_if_wrong="high",
                    )
                ],
                unknowns=[
                    UnknownOutput(
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
        image_urls=["https://example.com/tube.jpg"],
        constraints=ProjectConstraints(),
        project_id="project-1",
    )

    assert state.project_id == "project-1"
    assert state.materials[0].observations[0].claim_kind == ClaimKind.HYPOTHESIS
    assert state.materials[0].observations[0].evidence[0].evidence_id == "image_001"
    assert len(state.unresolved_critical_unknowns) == 1
    assert state.next_user_request == "Photograph the open end beside a ruler."


def test_unknown_evidence_ids_are_not_fabricated_into_state():
    output = MaterialEyeOutput(
        analysis_summary="Visible textile.",
        materials=[
            MaterialOutput(
                display_name="Textile",
                observations=[
                    ObservationOutput(
                        label="Blue woven textile",
                        claim_kind="fact",
                        confidence=1.0,
                        evidence_ids=["image_001", "image_999"],
                        consequence_if_wrong="low",
                    )
                ],
                unknowns=[],
            )
        ],
        next_user_request=None,
    )

    state = _to_project_state(
        output=output,
        image_urls=["https://example.com/textile.jpg"],
        constraints=ProjectConstraints(),
        project_id=None,
    )

    refs = state.materials[0].observations[0].evidence
    assert [ref.evidence_id for ref in refs] == ["image_001"]
