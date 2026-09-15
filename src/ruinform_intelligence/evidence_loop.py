from __future__ import annotations

import re
from uuid import uuid4

from pydantic import BaseModel, Field

from .evidence_contract import EvidenceContractReport, validate_state_contract
from .material_eye import analyze_evidence
from .models import EvidenceItem, ProjectState


class MeasurementInput(BaseModel):
    label: str
    value: float | str
    unit: str | None = None
    method: str | None = None
    note: str | None = None
    property_key: str | None = None


class ClaimTransition(BaseModel):
    property_key: str
    observation_id: str
    change_type: str
    prior_observation_ids: list[str] = Field(default_factory=list)


class EvidenceLoopResult(BaseModel):
    project_state: ProjectState
    analysis_summary: str
    resolved_unknown_keys: list[str] = Field(default_factory=list)
    new_unknown_keys: list[str] = Field(default_factory=list)
    claim_transitions: list[ClaimTransition] = Field(default_factory=list)
    evidence_contract: EvidenceContractReport


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


def _new_evidence(
    *,
    new_image_urls: list[str],
    user_statement: str | None,
    measurements: list[MeasurementInput],
) -> list[EvidenceItem]:
    items: list[EvidenceItem] = []
    for url in new_image_urls:
        items.append(
            EvidenceItem(
                evidence_id=f"image_{uuid4().hex[:12]}",
                source_type="image",
                uri=url,
            )
        )
    if user_statement:
        items.append(
            EvidenceItem(
                evidence_id=f"user_{uuid4().hex[:12]}",
                source_type="user_statement",
                text=user_statement,
            )
        )
    for measurement in measurements:
        property_key = measurement.property_key or _normalize_key(measurement.label)
        method = f"method={measurement.method}" if measurement.method else None
        note = f"note={measurement.note}" if measurement.note else None
        text = "; ".join(part for part in [measurement.label, method, note] if part)
        items.append(
            EvidenceItem(
                evidence_id=f"measure_{uuid4().hex[:12]}",
                source_type="measurement",
                property_key=property_key,
                value=measurement.value,
                unit=measurement.unit,
                text=text,
            )
        )
    return items


def _claim_transitions(state: ProjectState) -> list[ClaimTransition]:
    transitions: list[ClaimTransition] = []
    for material in state.materials:
        for observation in material.observations:
            if observation.property_key:
                transitions.append(
                    ClaimTransition(
                        property_key=observation.property_key,
                        observation_id=observation.observation_id,
                        change_type=observation.change_type,
                        prior_observation_ids=observation.prior_observation_ids,
                    )
                )
    return transitions


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

    added_evidence = _new_evidence(
        new_image_urls=new_image_urls,
        user_statement=user_statement,
        measurements=measurements,
    )
    ledger = [*current_state.evidence, *added_evidence]
    if not any(item.source_type == "image" for item in ledger):
        raise ValueError("Evidence loop currently requires at least one image in project state")

    before = unknown_keys(current_state)
    next_state, summary = await analyze_evidence(
        evidence=ledger,
        user_context=(
            "Follow-up evidence turn. Reconcile all evidence against the prior project state. "
            "Use exact evidence IDs and exact prior observation IDs when describing claim changes."
        ),
        constraints=current_state.constraints,
        project_id=current_state.project_id,
        prior_state=current_state,
    )

    after = unknown_keys(next_state)
    report = validate_state_contract(next_state)
    return EvidenceLoopResult(
        project_state=next_state,
        analysis_summary=summary,
        resolved_unknown_keys=sorted(before - after),
        new_unknown_keys=sorted(after - before),
        claim_transitions=_claim_transitions(next_state),
        evidence_contract=report,
    )
