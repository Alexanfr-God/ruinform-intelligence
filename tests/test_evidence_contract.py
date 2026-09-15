from ruinform_intelligence.evidence_contract import validate_state_contract
from ruinform_intelligence.models import (
    EvidenceItem,
    EvidenceRef,
    MaterialItem,
    MaterialObservation,
    ProjectState,
)


def test_valid_grounded_claim_passes_contract() -> None:
    state = ProjectState(
        evidence=[
            EvidenceItem(
                evidence_id="measure_1",
                source_type="measurement",
                property_key="wall_thickness",
                value=2.1,
                unit="mm",
            )
        ],
        materials=[
            MaterialItem(
                display_name="tube",
                observations=[
                    MaterialObservation(
                        property_key="wall_thickness",
                        label="Wall thickness is 2.1 mm",
                        claim_kind="fact",
                        confidence=1.0,
                        evidence=[
                            EvidenceRef(
                                evidence_id="measure_1",
                                source_type="measurement",
                            )
                        ],
                    )
                ],
            )
        ],
    )

    report = validate_state_contract(state)
    assert report.passed is True
    assert report.issues == []


def test_ungrounded_fact_fails_contract() -> None:
    state = ProjectState(
        materials=[
            MaterialItem(
                display_name="tube",
                observations=[
                    MaterialObservation(
                        property_key="material_family",
                        label="This is steel",
                        claim_kind="fact",
                        confidence=1.0,
                    )
                ],
            )
        ]
    )

    report = validate_state_contract(state)
    assert report.passed is False
    assert "ungrounded_claim" in {issue.code for issue in report.issues}


def test_follow_up_claim_must_reference_history() -> None:
    prior = MaterialObservation(
        observation_id="obs_old",
        property_key="material_family",
        label="Appears to be steel",
        claim_kind="hypothesis",
        confidence=0.7,
        evidence=[EvidenceRef(evidence_id="image_1", source_type="image")],
    )
    current = MaterialObservation(
        observation_id="obs_new",
        property_key="material_family",
        label="Steel confirmed by stamped grade label",
        claim_kind="fact",
        confidence=0.98,
        evidence=[EvidenceRef(evidence_id="image_2", source_type="image")],
        change_type="confirmed",
        prior_observation_ids=["obs_old"],
    )
    state = ProjectState(
        evidence=[
            EvidenceItem(evidence_id="image_1", source_type="image", uri="https://example.com/1.jpg"),
            EvidenceItem(evidence_id="image_2", source_type="image", uri="https://example.com/2.jpg"),
        ],
        claim_history=[prior],
        materials=[MaterialItem(display_name="tube", observations=[current])],
    )

    report = validate_state_contract(state)
    assert report.passed is True


def test_existing_property_cannot_be_marked_new() -> None:
    prior = MaterialObservation(
        observation_id="obs_old",
        property_key="material_family",
        label="Appears metallic",
        claim_kind="hypothesis",
        confidence=0.6,
        evidence=[EvidenceRef(evidence_id="image_1", source_type="image")],
    )
    current = MaterialObservation(
        property_key="material_family",
        label="Appears to be steel",
        claim_kind="hypothesis",
        confidence=0.8,
        evidence=[EvidenceRef(evidence_id="image_2", source_type="image")],
        change_type="new",
    )
    state = ProjectState(
        evidence=[
            EvidenceItem(evidence_id="image_1", source_type="image", uri="https://example.com/1.jpg"),
            EvidenceItem(evidence_id="image_2", source_type="image", uri="https://example.com/2.jpg"),
        ],
        claim_history=[prior],
        materials=[MaterialItem(display_name="tube", observations=[current])],
    )

    report = validate_state_contract(state)
    assert report.passed is False
    assert "existing_property_marked_new" in {issue.code for issue in report.issues}
