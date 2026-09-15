from ruinform_intelligence.lab_dialogue import (
    compose_answer_statement,
    parse_measurements,
    suggested_choices,
)


def test_dimension_unknown_offers_measurement_path() -> None:
    choices = suggested_choices("wall_thickness")
    assert "I will enter a measurement below" in choices
    assert "not sure" in choices


def test_material_unknown_offers_common_material_choices() -> None:
    choices = suggested_choices("material_composition")
    assert "glass" in choices
    assert "plastic / polymer" in choices
    assert "not sure" in choices


def test_compose_answer_statement_combines_choice_and_custom_answer() -> None:
    statement = compose_answer_statement(
        material_name="Green bottle",
        property_key="material_composition",
        choice="glass",
        custom_answer="wine bottle glass; no maker mark visible",
    )
    assert statement == (
        "Green bottle / material_composition: glass; "
        "wine bottle glass; no maker mark visible"
    )


def test_parse_measurements_creates_structured_evidence() -> None:
    measurements, rejected = parse_measurements(
        "bottle_height = 31 cm\nneck_diameter: 28 mm\nled_voltage = 12 V"
    )
    assert rejected == []
    assert [item.label for item in measurements] == [
        "bottle_height",
        "neck_diameter",
        "led_voltage",
    ]
    assert [item.value for item in measurements] == [31.0, 28.0, 12.0]
    assert [item.unit for item in measurements] == ["cm", "mm", "V"]


def test_parse_measurements_reports_bad_lines() -> None:
    measurements, rejected = parse_measurements("height about thirty cm")
    assert measurements == []
    assert rejected == ["height about thirty cm"]
