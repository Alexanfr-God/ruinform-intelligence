from __future__ import annotations

import json
import os
from collections import defaultdict
from typing import Literal

from openai import AsyncOpenAI
from pydantic import BaseModel, ConfigDict, Field

from .evidence_contract import EvidenceContractError, assert_state_contract
from .evidence_gate import refresh_critical_unknowns
from .models import (
    ClaimKind,
    EvidenceItem,
    EvidenceRef,
    MaterialItem,
    MaterialObservation,
    ProjectConstraints,
    ProjectState,
    Unknown,
)
from .prompt_loader import load_prompt_file
from .reasoning_state import compact_state_json

DEFAULT_MODEL = "gpt-5.6"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ObservationOutput(StrictModel):
    property_key: str
    label: str
    claim_kind: Literal["fact", "hypothesis", "unknown"]
    confidence: float | None = Field(ge=0.0, le=1.0)
    evidence_ids: list[str]
    consequence_if_wrong: Literal["low", "medium", "high"]
    change_type: Literal["new", "confirmed", "revised", "contradicted"]
    prior_observation_ids: list[str]


class UnknownOutput(StrictModel):
    property_key: str
    question: str
    reason: str
    consequence_if_unresolved: Literal["low", "medium", "high"]
    preferred_evidence: list[str]


class MaterialOutput(StrictModel):
    display_name: str
    observations: list[ObservationOutput]
    unknowns: list[UnknownOutput]


class MaterialEyeOutput(StrictModel):
    analysis_summary: str
    materials: list[MaterialOutput]
    next_user_request: str | None


class MaterialEyeError(RuntimeError):
    pass


def load_material_eye_prompt() -> str:
    return load_prompt_file("material_eye.md")


def _structured_output_schema() -> dict:
    return MaterialEyeOutput.model_json_schema()


def _prior_observations(state: ProjectState | None) -> list[MaterialObservation]:
    if state is None:
        return []
    observations: list[MaterialObservation] = []
    seen: set[str] = set()
    for observation in state.claim_history:
        if observation.observation_id not in seen:
            observations.append(observation)
            seen.add(observation.observation_id)
    for material in state.materials:
        for observation in material.observations:
            if observation.observation_id not in seen:
                observations.append(observation)
                seen.add(observation.observation_id)
    return observations


def _prior_observation_ids(state: ProjectState | None) -> set[str]:
    return {observation.observation_id for observation in _prior_observations(state)}


def _prior_property_lineage(state: ProjectState | None) -> str:
    if state is None:
        return "none; this is the first inspection"
    grouped: dict[str, list[str]] = defaultdict(list)
    for observation in _prior_observations(state):
        if observation.property_key:
            grouped[observation.property_key].append(observation.observation_id)
    if not grouped:
        return "none"
    return "\n".join(
        f"{property_key}: {', '.join(observation_ids)}"
        for property_key, observation_ids in sorted(grouped.items())
    )


def _evidence_text(item: EvidenceItem) -> str:
    fields = [f"Evidence ID: {item.evidence_id}", f"source_type={item.source_type}"]
    if item.property_key:
        fields.append(f"property_key={item.property_key}")
    if item.value is not None:
        fields.append(f"value={item.value}")
    if item.unit:
        fields.append(f"unit={item.unit}")
    if item.text:
        fields.append(f"text={item.text}")
    return "; ".join(fields)


def _build_input(
    *,
    evidence: list[EvidenceItem],
    user_context: str | None,
    constraints: ProjectConstraints,
    prior_state: ProjectState | None,
) -> list[dict]:
    prior_state_text = compact_state_json(prior_state) if prior_state else "none; this is the first inspection"
    lineage = _prior_property_lineage(prior_state)
    content: list[dict] = [
        {
            "type": "input_text",
            "text": (
                "Inspect the supplied physical evidence. Do not design anything yet. Return only the requested structured inspection.\n\n"
                f"User context: {user_context or 'none supplied'}\n"
                f"Known constraints: {constraints.model_dump_json()}\n"
                f"Prior project state: {prior_state_text}\n\n"
                "PRIOR PROPERTY LINEAGE — when you mark a claim confirmed/revised/contradicted, "
                "prior_observation_ids MUST come only from the SAME property_key shown below:\n"
                f"{lineage}"
            ),
        }
    ]
    for item in evidence:
        content.append({"type": "input_text", "text": _evidence_text(item)})
        if item.source_type == "image":
            if not item.uri:
                raise ValueError(f"Image evidence {item.evidence_id} has no uri")
            content.append({"type": "input_image", "image_url": item.uri, "detail": "high"})
    return [{"role": "user", "content": content}]


def _history_from_prior_state(prior_state: ProjectState | None) -> list[MaterialObservation]:
    return _prior_observations(prior_state)


def _labels_equivalent(left: str, right: str) -> bool:
    normalize = lambda value: " ".join(value.lower().split())
    return normalize(left) == normalize(right)


def _repair_lineage(
    observation: ObservationOutput,
    *,
    prior_state: ProjectState | None,
) -> ObservationOutput:
    """Repair model-generated lineage without weakening the Evidence Contract.

    The model is responsible for the physical claim, but exact graph linkage is bookkeeping.
    A wrong prior ID should not erase the user's evidence turn. We deterministically constrain
    prior links to observations with the same stable property_key and let the contract validate
    the repaired state afterwards.
    """
    if prior_state is None:
        return observation.model_copy(update={"change_type": "new", "prior_observation_ids": []})

    prior = _prior_observations(prior_state)
    by_id = {item.observation_id: item for item in prior}
    same_property = [item for item in prior if item.property_key == observation.property_key]

    valid_same_property_ids = [
        prior_id
        for prior_id in observation.prior_observation_ids
        if prior_id in by_id and by_id[prior_id].property_key == observation.property_key
    ]

    if observation.change_type == "new":
        if not same_property:
            return observation.model_copy(update={"prior_observation_ids": []})
        latest = same_property[-1]
        inferred_change = (
            "confirmed"
            if latest.claim_kind.value == observation.claim_kind
            and _labels_equivalent(latest.label, observation.label)
            else "revised"
        )
        return observation.model_copy(
            update={
                "change_type": inferred_change,
                "prior_observation_ids": [latest.observation_id],
            }
        )

    if valid_same_property_ids:
        return observation.model_copy(update={"prior_observation_ids": valid_same_property_ids})

    if same_property:
        return observation.model_copy(
            update={"prior_observation_ids": [same_property[-1].observation_id]}
        )

    # The model said this changed an earlier claim, but no earlier claim exists for this key.
    # Treat it as a genuinely new property instead of linking it to a different property.
    return observation.model_copy(update={"change_type": "new", "prior_observation_ids": []})


def _to_project_state(
    *,
    output: MaterialEyeOutput,
    evidence: list[EvidenceItem],
    constraints: ProjectConstraints,
    project_id: str | None,
    prior_state: ProjectState | None = None,
) -> ProjectState:
    evidence_by_id: dict[str, EvidenceItem] = {}
    for item in evidence:
        if item.evidence_id in evidence_by_id:
            raise MaterialEyeError(f"Duplicate evidence id: {item.evidence_id}")
        evidence_by_id[item.evidence_id] = item

    materials: list[MaterialItem] = []
    for material_output in output.materials:
        observations: list[MaterialObservation] = []
        for raw_observation in material_output.observations:
            observation = _repair_lineage(raw_observation, prior_state=prior_state)
            missing_evidence = [
                evidence_id
                for evidence_id in observation.evidence_ids
                if evidence_id not in evidence_by_id
            ]
            if missing_evidence:
                raise MaterialEyeError(
                    "Material Eye referenced unknown evidence ids: "
                    + ", ".join(sorted(missing_evidence))
                )
            if observation.claim_kind in {"fact", "hypothesis"} and not observation.evidence_ids:
                raise MaterialEyeError(
                    f"Grounded claim {observation.property_key} has no evidence references"
                )

            refs = [
                EvidenceRef(
                    evidence_id=evidence_id,
                    source_type=evidence_by_id[evidence_id].source_type,
                )
                for evidence_id in observation.evidence_ids
            ]
            observations.append(
                MaterialObservation(
                    property_key=observation.property_key,
                    label=observation.label,
                    claim_kind=ClaimKind(observation.claim_kind),
                    confidence=observation.confidence,
                    evidence=refs,
                    consequence_if_wrong=observation.consequence_if_wrong,
                    change_type=observation.change_type,
                    prior_observation_ids=observation.prior_observation_ids,
                )
            )

        unknowns = [
            Unknown(
                property_key=unknown.property_key,
                question=unknown.question,
                reason=unknown.reason,
                consequence_if_unresolved=unknown.consequence_if_unresolved,
                preferred_evidence=unknown.preferred_evidence,
            )
            for unknown in material_output.unknowns
        ]
        materials.append(
            MaterialItem(
                display_name=material_output.display_name,
                observations=observations,
                unknowns=unknowns,
            )
        )

    resolved_project_id = project_id or (prior_state.project_id if prior_state else None)
    kwargs = {
        "stage": "material_understanding",
        "evidence": evidence,
        "materials": materials,
        "claim_history": _history_from_prior_state(prior_state),
        "constraints": constraints,
        "next_user_request": output.next_user_request,
    }
    if resolved_project_id:
        kwargs["project_id"] = resolved_project_id

    state = refresh_critical_unknowns(ProjectState(**kwargs))
    try:
        assert_state_contract(state)
    except EvidenceContractError as exc:
        details = "; ".join(
            f"{issue.code}: {issue.message}" for issue in exc.report.issues
        )
        raise MaterialEyeError(
            f"Evidence contract rejected Material Eye output after lineage repair: {details}"
        ) from exc
    return state


async def analyze_evidence(
    *,
    evidence: list[EvidenceItem],
    user_context: str | None = None,
    constraints: ProjectConstraints | None = None,
    project_id: str | None = None,
    prior_state: ProjectState | None = None,
    client: AsyncOpenAI | None = None,
    model: str | None = None,
) -> tuple[ProjectState, str]:
    if not evidence:
        raise ValueError("At least one evidence item is required")
    if sum(item.source_type == "image" for item in evidence) > 8:
        raise ValueError("Material Eye accepts at most 8 image evidence items per inspection")

    constraints = constraints or (
        prior_state.constraints if prior_state else ProjectConstraints()
    )
    model = model or os.getenv("RUINFORM_MATERIAL_EYE_MODEL", DEFAULT_MODEL)
    client = client or AsyncOpenAI()

    response = await client.responses.create(
        model=model,
        instructions=load_material_eye_prompt(),
        input=_build_input(
            evidence=evidence,
            user_context=user_context,
            constraints=constraints,
            prior_state=prior_state,
        ),
        text={
            "format": {
                "type": "json_schema",
                "name": "ruinform_material_eye",
                "strict": True,
                "schema": _structured_output_schema(),
            }
        },
    )
    if not response.output_text:
        raise MaterialEyeError("Material Eye returned no structured output")
    try:
        output = MaterialEyeOutput.model_validate(json.loads(response.output_text))
    except (json.JSONDecodeError, ValueError) as exc:
        raise MaterialEyeError("Material Eye returned invalid structured output") from exc

    state = _to_project_state(
        output=output,
        evidence=evidence,
        constraints=constraints,
        project_id=project_id,
        prior_state=prior_state,
    )
    return state, output.analysis_summary


async def analyze_materials(
    *,
    image_urls: list[str],
    user_context: str | None = None,
    constraints: ProjectConstraints | None = None,
    project_id: str | None = None,
    client: AsyncOpenAI | None = None,
    model: str | None = None,
) -> tuple[ProjectState, str]:
    if not image_urls:
        raise ValueError("At least one image URL is required")
    evidence = [
        EvidenceItem(
            evidence_id=f"image_{index:03d}",
            source_type="image",
            uri=url,
        )
        for index, url in enumerate(image_urls, start=1)
    ]
    return await analyze_evidence(
        evidence=evidence,
        user_context=user_context,
        constraints=constraints,
        project_id=project_id,
        client=client,
        model=model,
    )
