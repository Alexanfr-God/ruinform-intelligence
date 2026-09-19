from __future__ import annotations

import json
import os
from typing import Literal

from openai import AsyncOpenAI
from pydantic import BaseModel, ConfigDict, Field

from .form_architect import FormArchitectError, validate_candidate_against_state
from .future_models import CandidateForm, CandidatePool, FeasibilityReview, FuturePreferences
from .models import ProjectState
from .prompt_loader import load_prompt_file
from .reasoning_state import compact_state_json


DEFAULT_MODEL = "gpt-5.6"


class PreviewRepairError(RuntimeError):
    pass


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RepairDirective(_StrictModel):
    candidate_id: str
    action: Literal["revise", "replace"]
    original_candidate: CandidateForm
    critic_review: FeasibilityReview


class RepairBatch(_StrictModel):
    candidates: list[CandidateForm] = Field(min_length=1, max_length=4)


def _repair_schema(material_ids: list[str], candidate_ids: list[str]) -> dict[str, object]:
    schema = RepairBatch.model_json_schema()
    defs = schema.get("$defs")
    if isinstance(defs, dict):
        material_use = defs.get("MaterialUse")
        if isinstance(material_use, dict):
            properties = material_use.get("properties")
            if isinstance(properties, dict):
                properties["material_item_id"] = {"type": "string", "enum": material_ids}

        candidate_form = defs.get("CandidateForm")
        if isinstance(candidate_form, dict):
            properties = candidate_form.get("properties")
            if isinstance(properties, dict):
                properties["candidate_id"] = {"type": "string", "enum": candidate_ids}

    properties = schema.get("properties")
    if isinstance(properties, dict):
        rows = properties.get("candidates")
        if isinstance(rows, dict):
            rows["minItems"] = len(candidate_ids)
            rows["maxItems"] = len(candidate_ids)
    return schema


def build_repair_directives(
    candidates: list[CandidateForm],
    reviews_by_id: dict[str, FeasibilityReview],
) -> list[RepairDirective]:
    directives: list[RepairDirective] = []
    for candidate in candidates:
        review = reviews_by_id.get(candidate.candidate_id)
        if review is None or review.status == "pass":
            continue
        directives.append(
            RepairDirective(
                candidate_id=candidate.candidate_id,
                action="replace" if review.status == "reject" else "revise",
                original_candidate=candidate,
                critic_review=review,
            )
        )
    return directives


def validate_repair_pool(
    *,
    pool: RepairBatch,
    directives: list[RepairDirective],
    state: ProjectState,
) -> None:
    expected = {directive.candidate_id for directive in directives}
    actual = [candidate.candidate_id for candidate in pool.candidates]
    if len(actual) != len(set(actual)):
        raise PreviewRepairError("Repair pass returned duplicate candidate IDs")
    if set(actual) != expected:
        raise PreviewRepairError(
            "Repair pass candidate IDs do not match targets: "
            f"expected={sorted(expected)} actual={sorted(set(actual))}"
        )

    preferences = FuturePreferences(concept_mode=True)
    for candidate in pool.candidates:
        try:
            validate_candidate_against_state(
                candidate=candidate,
                state=state,
                preferences=preferences,
            )
        except FormArchitectError as exc:
            raise PreviewRepairError(str(exc)) from exc


def _repair_instructions(memory_context: str | None) -> str:
    base = load_prompt_file("design_brain.md")
    memory = memory_context or ""
    return (
        base
        + "\n\n"
        + memory
        + "\n\nSELF-HEALING FUTURES / ONE PASS ONLY. "
        + "You are not generating a fresh four-concept batch. You are repairing only the flagged slots after a pre-render critic review. "
        + "PASS siblings are locked and must remain untouched. "
        + "For action=revise, preserve the strongest core gesture only if it is worth preserving, then directly remove the critic failure modes with fewer parts, clearer physics and lower craft burden. "
        + "For action=replace, abandon the rejected mechanism recipe and create a genuinely different transformation family that fits the source photos. "
        + "A replacement must not be a renamed sibling of the rejected idea or of a surviving PASS concept. "
        + "SOURCE ECONOMY: use the smallest coherent subset of current sources. Never add an object merely because it exists in the upload. "
        + "Do not reward source-count coverage. Every used source must earn a structural, material, spatial, functional or narrative role. "
        + "DIVERSITY: compare repaired candidates against the locked survivors. Prefer different primary operators, different dominant source roles and different silhouettes. "
        + "SIMPLICITY: repair by subtraction first. Do not solve critic feedback by adding more hardware, mechanisms, electronics or precision craft. "
        + "MEMORY CAP: retrieved memory is design grammar and warning evidence only; do not copy a prior object recipe. "
        + "Return exactly one candidate for each requested candidate_id and preserve those IDs."
    )


async def repair_preview_candidates(
    *,
    state: ProjectState,
    directives: list[RepairDirective],
    locked_survivors: list[CandidateForm],
    memory_context: str | None,
    client: AsyncOpenAI | None = None,
    model: str | None = None,
) -> dict[str, CandidateForm]:
    if not directives:
        return {}

    model = model or os.getenv("RUINFORM_PREVIEW_REPAIR_MODEL", DEFAULT_MODEL)
    client = client or AsyncOpenAI()
    effort = os.getenv("RUINFORM_PREVIEW_REPAIR_REASONING", "medium")
    if effort not in {"low", "medium", "high"}:
        effort = "medium"

    material_ids = [item.item_id for item in state.materials]
    target_ids = [directive.candidate_id for directive in directives]
    directive_payload = [directive.model_dump(mode="json") for directive in directives]
    survivor_payload = [
        {
            "candidate_id": candidate.candidate_id,
            "name": candidate.name,
            "category": candidate.category,
            "one_line": candidate.one_line,
            "transformation_logic": candidate.transformation_logic,
            "material_uses": [item.model_dump(mode="json") for item in candidate.material_uses],
        }
        for candidate in locked_survivors
    ]

    content: list[dict[str, object]] = [
        {
            "type": "input_text",
            "text": (
                "Repair the flagged RUINFORM preview slots using the ACTUAL source photographs attached to this message. "
                "This is a bounded one-pass repair before any paid image generation.\n\n"
                f"Project state: {compact_state_json(state)}\n\n"
                f"REPAIR DIRECTIVES: {json.dumps(directive_payload, ensure_ascii=False)}\n\n"
                f"LOCKED SURVIVORS — do not rewrite these; make repaired slots complementary rather than sibling copies: "
                f"{json.dumps(survivor_payload, ensure_ascii=False)}\n\n"
                "For REVISE slots, address every required_change that materially affects the concept. "
                "For REPLACE slots, start from current source geometry/material behavior and choose a different primary transformation family. "
                "The repaired concept must still work on a clean neutral background without relying on RUINFORM_WORLD scenery."
            ),
        }
    ]

    image_count = 0
    for evidence in state.evidence:
        if evidence.source_type != "image" or not evidence.uri:
            continue
        content.append({"type": "input_image", "image_url": evidence.uri})
        image_count += 1
        if image_count >= 6:
            break

    if image_count == 0:
        raise PreviewRepairError("Self-healing repair requires at least one original source photograph")

    try:
        response = await client.responses.create(
            model=model,
            reasoning={"effort": effort},
            instructions=_repair_instructions(memory_context),
            input=[{"role": "user", "content": content}],
            text={
                "format": {
                    "type": "json_schema",
                    "name": "ruinform_preview_repair",
                    "strict": True,
                    "schema": _repair_schema(material_ids, target_ids),
                }
            },
        )
    except Exception as exc:
        raise PreviewRepairError(f"Preview repair request failed: {exc}") from exc

    if not response.output_text:
        raise PreviewRepairError("Preview repair returned no candidates")
    try:
        batch = RepairBatch.model_validate(json.loads(response.output_text))
    except (json.JSONDecodeError, ValueError) as exc:
        raise PreviewRepairError("Preview repair returned invalid structured output") from exc

    validate_repair_pool(pool=batch, directives=directives, state=state)
    return {candidate.candidate_id: candidate for candidate in batch.candidates}
