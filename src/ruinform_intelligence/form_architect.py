from __future__ import annotations

import json
import os

from openai import AsyncOpenAI

from .evidence_contract import EvidenceContractError, assert_state_contract
from .evidence_gate import can_advance_to_ideation
from .future_models import CandidateForm, CandidatePool, FuturePreferences
from .models import ProjectState
from .prompt_loader import load_prompt_file
from .reasoning_state import compact_state_json


DEFAULT_MODEL = "gpt-5.6"


class FormArchitectError(RuntimeError):
    pass


def load_form_architect_prompt() -> str:
    return load_prompt_file("form_architect.md")


def validate_candidate_against_state(
    *,
    candidate: CandidateForm,
    state: ProjectState,
    preferences: FuturePreferences,
) -> None:
    if not candidate.material_uses:
        raise FormArchitectError(f"{candidate.candidate_id} uses no source material")

    material_ids = {material.item_id for material in state.materials}
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

    avoided = {value.strip().lower() for value in preferences.avoid_categories}
    if candidate.category.lower() in avoided:
        raise FormArchitectError(
            f"{candidate.candidate_id} violates avoid_categories: {candidate.category}"
        )


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

    for candidate in pool.candidates:
        validate_candidate_against_state(
            candidate=candidate,
            state=state,
            preferences=preferences,
        )


def _concept_mode_context(state: ProjectState) -> str:
    unknowns: list[str] = []
    for material in state.materials:
        for unknown in material.unknowns:
            unknowns.append(
                f"- {material.display_name} / {unknown.property_key}: {unknown.question} "
                f"(consequence={unknown.consequence_if_unresolved})"
            )
    return (
        "CONCEPT MODE IS ACTIVE. The user explicitly chose exploratory ideation before all physical facts were verified.\n"
        "Treat every unresolved property as UNKNOWN, never as a fact. You may use conservative visual/design assumptions "
        "only to propose concepts, and every such assumption must remain visible in unresolved_dependencies. "
        "Do not claim engineering approval, structural safety, electrical safety, heat/flame safety, pressure safety, "
        "food-contact safety, regulatory compliance, or manufacturability. Avoid concepts whose core value depends on "
        "an unverified high-consequence property. Prefer reversible, non-load-bearing, low-energy, decorative or easily "
        "verifiable transformations until evidence improves.\n\n"
        "UNRESOLVED PROPERTIES:\n" + ("\n".join(unknowns) if unknowns else "- none")
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

    preferences = preferences or FuturePreferences()
    if not can_advance_to_ideation(state) and not preferences.concept_mode:
        raise FormArchitectError("Project state still has critical physical unknowns")

    model = model or os.getenv("RUINFORM_FORM_ARCHITECT_MODEL", DEFAULT_MODEL)
    client = client or AsyncOpenAI()
    mode_context = (
        _concept_mode_context(state)
        if preferences.concept_mode
        else "VERIFIED PATH. Use only established evidence and explicitly preserved unknowns."
    )

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
                            "Discover future forms from this physical project state.\n\n"
                            f"MODE POLICY:\n{mode_context}\n\n"
                            f"Project state: {compact_state_json(state)}\n\n"
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
