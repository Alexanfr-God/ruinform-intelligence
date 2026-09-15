from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Literal

from openai import AsyncOpenAI
from pydantic import BaseModel, ConfigDict, Field

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


DEFAULT_MODEL = "gpt-5.6"
PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "material_eye.md"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ObservationOutput(StrictModel):
    label: str
    claim_kind: Literal["fact", "hypothesis", "unknown"]
    confidence: float | None = Field(ge=0.0, le=1.0)
    evidence_ids: list[str]
    consequence_if_wrong: Literal["low", "medium", "high"]


class UnknownOutput(StrictModel):
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
    return PROMPT_PATH.read_text(encoding="utf-8")


def _structured_output_schema() -> dict:
    return MaterialEyeOutput.model_json_schema()


def _build_input(
    *,
    image_urls: list[str],
    user_context: str | None,
    constraints: ProjectConstraints,
) -> list[dict]:
    content: list[dict] = [
        {
            "type": "input_text",
            "text": (
                "Inspect the supplied physical objects as evidence. "
                "Do not design anything yet. Return only the requested structured inspection.\n\n"
                f"User context: {user_context or 'none supplied'}\n"
                f"Known constraints: {constraints.model_dump_json()}"
            ),
        }
    ]

    for index, image_url in enumerate(image_urls, start=1):
        content.append(
            {
                "type": "input_text",
                "text": f"Evidence image id: image_{index:03d}",
            }
        )
        content.append(
            {
                "type": "input_image",
                "image_url": image_url,
                "detail": "high",
            }
        )

    return [{"role": "user", "content": content}]


def _to_project_state(
    *,
    output: MaterialEyeOutput,
    image_urls: list[str],
    constraints: ProjectConstraints,
    project_id: str | None,
) -> ProjectState:
    evidence_items = [
        EvidenceItem(
            evidence_id=f"image_{index:03d}",
            source_type="image",
            uri=url,
        )
        for index, url in enumerate(image_urls, start=1)
    ]

    valid_evidence_ids = {item.evidence_id for item in evidence_items}
    materials: list[MaterialItem] = []

    for material_output in output.materials:
        observations: list[MaterialObservation] = []
        for observation in material_output.observations:
            evidence_refs = [
                EvidenceRef(evidence_id=evidence_id, source_type="image")
                for evidence_id in observation.evidence_ids
                if evidence_id in valid_evidence_ids
            ]
            observations.append(
                MaterialObservation(
                    label=observation.label,
                    claim_kind=ClaimKind(observation.claim_kind),
                    confidence=observation.confidence,
                    evidence=evidence_refs,
                    consequence_if_wrong=observation.consequence_if_wrong,
                )
            )

        unknowns = [
            Unknown(
                question=item.question,
                reason=item.reason,
                consequence_if_unresolved=item.consequence_if_unresolved,
                preferred_evidence=item.preferred_evidence,
            )
            for item in material_output.unknowns
        ]
        materials.append(
            MaterialItem(
                display_name=material_output.display_name,
                observations=observations,
                unknowns=unknowns,
            )
        )

    state_kwargs = {
        "stage": "material_understanding",
        "evidence": evidence_items,
        "materials": materials,
        "constraints": constraints,
        "next_user_request": output.next_user_request,
    }
    if project_id:
        state_kwargs["project_id"] = project_id

    state = ProjectState(**state_kwargs)
    return refresh_critical_unknowns(state)


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
    if len(image_urls) > 8:
        raise ValueError("Material Eye accepts at most 8 images per inspection")

    constraints = constraints or ProjectConstraints()
    model = model or os.getenv("RUINFORM_MATERIAL_EYE_MODEL", DEFAULT_MODEL)
    client = client or AsyncOpenAI()

    response = await client.responses.create(
        model=model,
        instructions=load_material_eye_prompt(),
        input=_build_input(
            image_urls=image_urls,
            user_context=user_context,
            constraints=constraints,
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
        image_urls=image_urls,
        constraints=constraints,
        project_id=project_id,
    )
    return state, output.analysis_summary
