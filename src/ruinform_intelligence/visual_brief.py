from __future__ import annotations

import json
import os

from openai import AsyncOpenAI

from .future_models import CandidateForm, FeasibilityReview, VisualBrief
from .models import ProjectState
from .prompt_loader import load_prompt_file


DEFAULT_MODEL = "gpt-5.6"


class VisualBriefError(RuntimeError):
    pass


def load_visual_brief_prompt() -> str:
    return load_prompt_file("visual_brief.md")


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
    concept_mode: bool,
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
    if concept_mode:
        deterministic_forbidden.extend(
            [
                "This is Concept Mode: keep proportions approximate where dimensions are unknown.",
                "Do not visually imply tested safety, structural adequacy, electrical compliance, heat resistance, or manufacturability.",
            ]
        )
    for key in unresolved:
        deterministic_forbidden.append(f"Do not visually resolve unknown property: {key}.")

    forbidden = list(dict.fromkeys([*brief.forbidden_inventions, *deterministic_forbidden]))
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
    concept_mode: bool = False,
    client: AsyncOpenAI | None = None,
    model: str | None = None,
) -> VisualBrief:
    if review.candidate_id != candidate.candidate_id or review.status != "pass":
        raise VisualBriefError("Visual briefs may be generated only for passed candidates")

    model = model or os.getenv("RUINFORM_VISUAL_BRIEF_MODEL", DEFAULT_MODEL)
    client = client or AsyncOpenAI()
    mode_policy = (
        "CONCEPT MODE: create an exploratory visualization only. Preserve all unknown dimensions/properties as ambiguous; "
        "do not turn assumptions into visible engineering facts."
        if concept_mode
        else "VERIFIED PATH: use the established project state and preserve remaining unknowns."
    )

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
                            f"MODE POLICY: {mode_policy}\n\n"
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
        concept_mode=concept_mode,
    )
