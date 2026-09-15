from ruinform_intelligence.evidence_gate import can_advance_to_ideation
from ruinform_intelligence.models import MaterialItem, ProjectState, Unknown


def test_high_consequence_unknown_blocks_ideation() -> None:
    state = ProjectState(
        materials=[
            MaterialItem(
                display_name="metal tube",
                unknowns=[
                    Unknown(
                        question="What is the wall thickness?",
                        reason="Needed for structural feasibility.",
                        consequence_if_unresolved="high",
                        preferred_evidence=["measure wall thickness"],
                    )
                ],
            )
        ]
    )
    assert can_advance_to_ideation(state) is False
    assert len(state.unresolved_critical_unknowns) == 1


def test_low_consequence_unknown_does_not_block_ideation() -> None:
    state = ProjectState(
        materials=[
            MaterialItem(
                display_name="denim",
                unknowns=[
                    Unknown(
                        question="What brand is the denim?",
                        reason="Not required for transformation planning.",
                        consequence_if_unresolved="low",
                    )
                ],
            )
        ]
    )
    assert can_advance_to_ideation(state) is True
