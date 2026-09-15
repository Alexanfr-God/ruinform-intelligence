from __future__ import annotations

import re

from .evidence_loop import MeasurementInput


_DIMENSION_HINTS = {
    "dimension",
    "height",
    "width",
    "length",
    "diameter",
    "thickness",
    "radius",
    "size",
    "spacing",
    "distance",
}


def suggested_choices(property_key: str) -> list[str]:
    key = property_key.lower()
    if any(token in key for token in _DIMENSION_HINTS):
        return ["I will enter a measurement below", "not sure"]
    if "material" in key or "composition" in key or "family" in key:
        return [
            "glass",
            "plastic / polymer",
            "metal",
            "textile / fabric",
            "leather",
            "wood",
            "composite",
            "not sure",
        ]
    if "voltage" in key:
        return ["5 V", "12 V", "24 V", "other — see custom answer", "not sure"]
    if "condition" in key or "damage" in key or "intact" in key:
        return ["intact", "minor wear", "damaged", "not sure"]
    if "water" in key or "environment" in key or "coating" in key:
        return ["indoor / dry only", "water-resistant", "waterproof", "not sure"]
    if "flex" in key or "bend" in key:
        return ["flexible", "semi-rigid", "rigid", "not sure"]
    return ["yes / confirmed", "no / not present", "not sure", "other — see custom answer"]


def compose_answer_statement(
    *,
    material_name: str,
    property_key: str,
    choice: str | None,
    custom_answer: str | None,
) -> str | None:
    parts: list[str] = []
    if choice and choice.strip():
        parts.append(choice.strip())
    if custom_answer and custom_answer.strip():
        parts.append(custom_answer.strip())
    if not parts:
        return None
    return f"{material_name} / {property_key}: " + "; ".join(parts)


_MEASUREMENT_RE = re.compile(
    r"^\s*(?P<label>[^:=]+?)\s*[:=]\s*"
    r"(?P<value>[-+]?\d+(?:[.,]\d+)?)\s*"
    r"(?P<unit>[A-Za-zµμ°%Ω]+)?\s*"
    r"(?:\((?P<note>.*)\))?\s*$"
)


def parse_measurements(text: str) -> tuple[list[MeasurementInput], list[str]]:
    measurements: list[MeasurementInput] = []
    rejected: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = _MEASUREMENT_RE.match(line)
        if match is None:
            rejected.append(line)
            continue
        value = float(match.group("value").replace(",", "."))
        measurements.append(
            MeasurementInput(
                label=match.group("label").strip(),
                value=value,
                unit=(match.group("unit") or "").strip() or None,
                method="user supplied in RUINFORM lab",
                note=(match.group("note") or "").strip() or None,
            )
        )
    return measurements, rejected
