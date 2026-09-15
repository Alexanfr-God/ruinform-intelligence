from __future__ import annotations

import re
from uuid import uuid4

from pydantic import BaseModel, Field

from .material_eye import analyze_materials
from .models import EvidenceItem, ProjectState


class MeasurementInput(BaseModel):
    label: str
    value: float | str
    unit: str | None = None
    method: str | None = None
    note: str | None = None


class EvidenceLoopResult(BaseModel):
    project_state: ProjectState
    analysis_summary: str
    resolved_unknown_keys: list[str] = Field(default_factory=list)
    new_unknown_keys: list[str] = Field(default_factory=list)


def _normalize_key(value: str) -> str:
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9]+", "_", value)
    return value.strip("_")[:96]


def unknown_keys(state: ProjectState) -> set[str]:
    keys: set[str] = set()
    for material in state.materials:
        for unknown in material.unknowns:
            keys.add(unknown.property_key or _normalize_key(unknown.question))
    return keys


def _supplemental_context(
    *,
    current_state: ProjectState,
    user_statement: str | None,
    measurements: list[MeasurementInput],
) -> str:
    parts = [
        "This is a follow-up evidence turn. Reconcile the new evidence against the prior state.",
        f"Prior state: {current_state.model_dump_json()}",
    ]
    if user_statement:
        parts.append(f"New user statement: {user_statement}")
    for measurement in measurements:
        unit = f" {measurement.unit}" if measurement.unit else ""
        method = f"; method={measurement.method}" if measurement.method else ""
        note = f"; note={measurement.note}" if measurement.note else ""
        parts.append(f"New measurement: {measurement.label}={measurement.value}{unit}{method}{note}")
    return "\n".join(parts)


def _existing_image_urls(state: ProjectState) -> list[str]:
    return [item.uri for item in state.evidence if item.source_type == "image" and item.uri]


def _new_non_image_evidence(
    *,
    user_statement: str | None,
    measurements: list[MeasurementInput],
) -> list[EvidenceItem]:
    items: list[EvidenceItem] = []
    if user_statement:
        items.append(
            EvidenceItem(
                evidence_id=f"user_{uuid4().hex[:12]}",
                source_type="user_statement",
                text=user_statement,
            )
        )
    for measurement in measurements:
        unit = f" {measurement.unit}" if measurement.unit else ""
        items.append(
            EvidenceItem(
                evidence_id=f"measure_{uuid4().hex[:12]}",
                source_type="measurement",
                text=f"{measurement.label}: {measurement.value}{unit}",
            )
        )
    return items


async def continue_evidence_loop(
    *,
    current_state: ProjectState,
    new_image_urls: list[str] | None = None,
    user_statement: str | None = None,
    measurements: list[MeasurementInput] | None = None,
) -> EvidenceLoopResult:
    new_image_urls = new_image_urls or []
    measurements = measurements or []
    if not new_image_urls and not user_statement and not measurements:
        raise ValueError("At least one new evidence item is required")

    image_urls = _existing_image_urls(current_state) + new_image_urls
    if not image_urls:
        raise ValueError("Evidence loop currently requires at least one image in project state")

    before = unknown_keys(current_state)
    context = _supplemental_context(
        current_state=current_state,
        user_statement=user_statement,
        measurements=measurements,
    )

    next_state, summary = await analyze_materials(
        image_urls=image_urls,
        user_context=context,
        constraints=current_state.constraints,
        project_id=current_state.project_id,
    )

    next_state.evidence.extend(
        _new_non_image_evidence(
            user_statement=user_statement,
            measurements=measurements,
        )
    )

    after = unknown_keys(next_state)
    return EvidenceLoopResult(
        project_state=next_state,
        analysis_summary=summary,
        resolved_unknown_keys=sorted(before - after),
        new_unknown_keys=sorted(after - before),
    )
