from __future__ import annotations

import json
import os
from pathlib import Path

from openai import AsyncOpenAI

from .future_models import CandidateForm, FeasibilityReview, VisualBrief
from .models import ProjectState


DEFAULT_MODEL = "gpt-5.6"
PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "visual_brief.md"


class VisualBriefError(RuntimeError):
    pass


def load_visual_brief_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def unresolved_property_keys(state: ProjectState) -> list[str]:
    keys: set[str] = set()
    for material in state.materials:
        for unknown in material.unknowns:
            keys.add(unknown.property_key or unknown.question)
    return sorted(keys)


def _enforce_renderer_boundaries(
    *,
    state: ProjectState,
    candidate: CandidateForm,
    brief: VisualBrief,
) -> VisualBrief:
    if brief.candidate_id != candidate.candidate_id:
        raise VisualBriefError("Visual brief candidate_id does not match candidate")

    expected_material_ids = {use.material_item_id for use in candidate.material_uses}
    brief_material_ids = {trace.material_item_id for trace in brief.material_traces}
    if brief_material_ids != expected_material_ids:
        raise VisualBriefError(
            "Visual brief material traces must exactly match candidate source materials"
        )

    unresolved = unresolved_property_keys(state)
    unknowns = list(dict.fromkeys([*brief.unknowns_to_keep_ambiguous, *unresolved]))

    deterministic_forbidden = [
        "Do not invent exact dimensions that are not established in ProjectState.",
        "Do not invent material grade, composition, strength, or load capacity.",
        "Do not invent hidden fasteners, supports, or internal structure not declared by the candidate.",
        "Do not add source materials or purchased parts that are absent from the approved candidate.",
        "Do not depict the render as engineering proof or certification.",
    ]
    for key in unresolved:
        deterministic_forbidden.append(f"Do not visually resolve unknown property: {key}.")

    forbidden = list(
        dict.fromkeys([*brief.forbidden_inventions, *deterministic_forbidden])
    )
    return brief.model_copy(
        update={
            "unknowns_to_keep_ambiguous": unknowns,
            "forbidden_inventions": forbidden,
        }
    )


async def generate_visual_brief(
    *,
    state: ProjectState,
    candidate: CandidateForm,
    review: FeasibilityReview,
    client: AsyncOpenAI | None = None,
    model: str | None = None,
) -> VisualBrief:
    if review.candidate_id != candidate.candidate_id or review.status != "pass":
        raise VisualBriefError("Visual briefs may be generated only for passed candidates")

    model = model or os.getenv("RUINFORM_VISUAL_BRIEF_MODEL", DEFAULT_MODEL)
    client = client or AsyncOpenAI()

    response = await client.responses.create(
        model=model,
        reasoning={"effort": "medium"},
        instructions=load_visual_brief_prompt(),
        input=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": (
                            "Create a renderer-safe visual brief for this approved future form.\n\n"
                            f"Project state: {state.model_dump_json()}\n\n"
                            f"Approved candidate: {candidate.model_dump_json()}\n\n"
                            f"Feasibility review: {review.model_dump_json()}"
                        ),
                    }
                ],
            }
        ],
        text={
            "format": {
                "type": "json_schema",
                "name": "ruinform_visual_brief",
                "strict": True,
                "schema": VisualBrief.model_json_schema(),
            }
        },
    )

    if not response.output_text:
        raise VisualBriefError("Visual Brief agent returned no brief")
    try:
        brief = VisualBrief.model_validate(json.loads(response.output_text))
    except (json.JSONDecodeError, ValueError) as exc:
        raise VisualBriefError("Visual Brief agent returned invalid structured output") from exc

    return _enforce_renderer_boundaries(
        state=state,
        candidate=candidate,
        brief=brief,
    )
