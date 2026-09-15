from __future__ import annotations

import json
import os
from pathlib import Path

from openai import AsyncOpenAI

from .evidence_contract import EvidenceContractError, assert_state_contract
from .evidence_gate import can_advance_to_ideation
from .future_models import CandidatePool, FuturePreferences
from .models import ProjectState


DEFAULT_MODEL = "gpt-5.6"
PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "form_architect.md"


class FormArchitectError(RuntimeError):
    pass


def load_form_architect_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def _validate_candidate_pool(
    *,
    pool: CandidatePool,
    state: ProjectState,
    preferences: FuturePreferences,
) -> None:
    if len(pool.candidates) < 6:
        raise FormArchitectError("Form Architect returned too few distinct candidates")

    candidate_ids = [candidate.candidate_id for candidate in pool.candidates]
    if len(candidate_ids) != len(set(candidate_ids)):
        raise FormArchitectError("Form Architect returned duplicate candidate IDs")

    material_ids = {material.item_id for material in state.materials}
    avoided = {value.strip().lower() for value in preferences.avoid_categories}
    for candidate in pool.candidates:
        if not candidate.material_uses:
            raise FormArchitectError(f"{candidate.candidate_id} uses no source material")
        unknown_material_ids = {
            use.material_item_id
            for use in candidate.material_uses
            if use.material_item_id not in material_ids
        }
        if unknown_material_ids:
            raise FormArchitectError(
                f"{candidate.candidate_id} references unknown material IDs: "
                + ", ".join(sorted(unknown_material_ids))
            )
        if preferences.only_use_owned_materials and candidate.added_materials:
            raise FormArchitectError(
                f"{candidate.candidate_id} violates only_use_owned_materials"
            )
        if candidate.category.lower() in avoided:
            raise FormArchitectError(
                f"{candidate.candidate_id} violates avoid_categories: {candidate.category}"
            )


async def generate_candidate_pool(
    *,
    state: ProjectState,
    preferences: FuturePreferences | None = None,
    user_intent: str | None = None,
    client: AsyncOpenAI | None = None,
    model: str | None = None,
) -> CandidatePool:
    try:
        assert_state_contract(state)
    except EvidenceContractError as exc:
        raise FormArchitectError("Project state failed the Evidence Contract") from exc
    if not can_advance_to_ideation(state):
        raise FormArchitectError("Project state still has critical physical unknowns")

    preferences = preferences or FuturePreferences()
    model = model or os.getenv("RUINFORM_FORM_ARCHITECT_MODEL", DEFAULT_MODEL)
    client = client or AsyncOpenAI()

    response = await client.responses.create(
        model=model,
        reasoning={"effort": "high"},
        instructions=load_form_architect_prompt(),
        input=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": (
                            "Discover future forms from this trusted physical state.\n\n"
                            f"Project state: {state.model_dump_json()}\n\n"
                            f"Preferences: {preferences.model_dump_json()}\n\n"
                            f"User intent: {user_intent or 'open exploration'}"
                        ),
                    }
                ],
            }
        ],
        text={
            "format": {
                "type": "json_schema",
                "name": "ruinform_candidate_pool",
                "strict": True,
                "schema": CandidatePool.model_json_schema(),
            }
        },
    )

    if not response.output_text:
        raise FormArchitectError("Form Architect returned no candidate pool")
    try:
        pool = CandidatePool.model_validate(json.loads(response.output_text))
    except (json.JSONDecodeError, ValueError) as exc:
        raise FormArchitectError("Form Architect returned invalid structured output") from exc

    _validate_candidate_pool(pool=pool, state=state, preferences=preferences)
    return pool
