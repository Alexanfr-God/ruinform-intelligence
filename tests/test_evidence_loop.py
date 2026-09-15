from ruinform_intelligence.evidence_loop import MeasurementInput, unknown_keys
from ruinform_intelligence.models import MaterialItem, ProjectState, Unknown


def test_unknown_keys_prefers_property_key() -> None:
    state = ProjectState(
        materials=[
            MaterialItem(
                display_name="metal tube",
                unknowns=[
                    Unknown(
                        property_key="wall_thickness",
                        question="What is the wall thickness?",
                        reason="Needed for feasibility.",
                        consequence_if_unresolved="high",
                    )
                ],
            )
        ]
    )
    assert unknown_keys(state) == {"wall_thickness"}


def test_unknown_keys_falls_back_to_normalized_question() -> None:
    state = ProjectState(
        materials=[
            MaterialItem(
                display_name="fabric",
                unknowns=[
                    Unknown(
                        question="What is the usable width?",
                        reason="Needed for layout.",
                        consequence_if_unresolved="medium",
                    )
                ],
            )
        ]
    )
    assert unknown_keys(state) == {"what_is_the_usable_width"}


def test_measurement_input_is_structured() -> None:
    item = MeasurementInput(label="wall thickness", value=2.1, unit="mm", method="caliper")
    assert item.value == 2.1
    assert item.unit == "mm"
