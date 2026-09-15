from ruinform_intelligence.evidence_loop import MeasurementInput, _new_evidence, unknown_keys
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


def test_measurement_input_becomes_structured_evidence() -> None:
    measurement = MeasurementInput(
        label="wall thickness",
        property_key="wall_thickness",
        value=2.1,
        unit="mm",
        method="caliper",
    )
    items = _new_evidence(
        new_image_urls=[],
        user_statement=None,
        measurements=[measurement],
    )

    assert len(items) == 1
    assert items[0].source_type == "measurement"
    assert items[0].property_key == "wall_thickness"
    assert items[0].value == 2.1
    assert items[0].unit == "mm"
    assert items[0].evidence_id.startswith("measure_")
