from __future__ import annotations

import json
import os
from typing import Literal

from openai import AsyncOpenAI
from pydantic import BaseModel, ConfigDict, Field

from .future_models import ReviewedFuture
from .models import ProjectState
from .prompt_loader import load_prompt_file
from .reasoning_state import compact_state_json


RenderMode = Literal["art_object", "design_product", "realistic_prototype"]
DEFAULT_MODEL = "gpt-5.6"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class VisualDirection(StrictModel):
    render_mode: RenderMode
    hero_material_id: str
    hero_object: str
    secondary_material_ids: list[str]
    accent_material_ids: list[str]
    object_type: str
    visual_thesis: str = Field(min_length=12)
    conceptual_tension: str = Field(min_length=12)
    material_relationship: str = Field(min_length=12)
    signature_gesture: str = Field(min_length=12)
    ordinary_solution_to_reject: str = Field(min_length=12)
    silhouette: str = Field(min_length=12)
    negative_space: str = Field(min_length=8)
    color_strategy: str = Field(min_length=8)
    composition: str
    camera: str
    lighting: str
    environment: str
    authorship_cues: list[str] = Field(min_length=2, max_length=7)
    must_keep: list[str] = Field(min_length=3, max_length=10)
    must_avoid: list[str] = Field(min_length=5, max_length=18)


class VisualDirectorError(RuntimeError):
    pass


def load_visual_director_prompt() -> str:
    return load_prompt_file("render_director.md")


def select_render_mode(future: ReviewedFuture) -> RenderMode:
    override = os.getenv("RUINFORM_RENDER_MODE", "").strip().lower()
    if override in {"art_object", "design_product", "realistic_prototype"}:
        return override  # type: ignore[return-value]

    category = future.candidate.category
    if category in {"sculpture", "functional_art", "lighting"}:
        return "art_object"
    if category == "utility":
        return "realistic_prototype"
    return "design_product"


def _background_contract(state: ProjectState) -> str:
    if state.creative_intent.background_mode == "ruinform_world":
        return (
            "RUINFORM WORLD: keep the designed object as the undisputed hero, but place it in a restrained post-apocalyptic "
            "salvage-luxury environment: reclaimed workshop, recovery gallery, weathered architecture, honest dust/wear and cinematic light. "
            "No generic cyberpunk RGB, costume props, fake warning signs, random weapons, or scenery that carries the idea instead of the object."
        )
    return (
        "CLEAN STUDIO: neutral contemporary studio/gallery presentation with minimal visual noise. The object itself must carry the idea. "
        "No post-apocalyptic scenery, decorative storytelling props, ruins, smoke, warning signage or environmental spectacle."
    )


def fallback_visual_direction(
    *,
    state: ProjectState,
    future: ReviewedFuture,
    render_mode: RenderMode,
) -> VisualDirection:
    uses = future.candidate.material_uses
    material_by_id = {item.item_id: item for item in state.materials}
    hero_id = uses[0].material_item_id if uses else (state.materials[0].item_id if state.materials else "unknown")
    hero_label = material_by_id.get(hero_id).display_name if hero_id in material_by_id else hero_id
    secondary = [use.material_item_id for use in uses[1:]]
    environment = (
        "Restrained RUINFORM post-apocalyptic salvage-luxury workshop/gallery; object remains dominant, no generic cyberpunk props."
        if state.creative_intent.background_mode == "ruinform_world"
        else "Minimal neutral contemporary studio/gallery with no decorative storytelling props."
    )
    return VisualDirection(
        render_mode=render_mode,
        hero_material_id=hero_id,
        hero_object=hero_label,
        secondary_material_ids=secondary,
        accent_material_ids=[],
        object_type=future.candidate.name,
        visual_thesis=future.candidate.artistic_thesis,
        conceptual_tension="Create a clear visual tension between the rigid hero and transformed supporting matter.",
        material_relationship="Secondary materials should actively transform, frame or interrupt the hero rather than merely sit beside it.",
        signature_gesture=future.candidate.transformation_logic,
        ordinary_solution_to_reject="Reject the obvious stacked, evenly wrapped or merely decorated version of this concept.",
        silhouette="One immediately readable finished object with a distinctive non-generic silhouette.",
        negative_space="Use deliberate openings and breathing room so the hero remains legible.",
        color_strategy="Preserve source colors and use accents as controlled contrast rather than equal visual noise.",
        composition="Single hero object, isolated from clutter, centered or deliberately asymmetric.",
        camera="Three-quarter editorial object view at object height, no wide-angle distortion.",
        lighting="Sculptural editorial lighting that reveals material contrast, depth, folds, glass and surface transitions.",
        environment=environment,
        authorship_cues=[
            "One surprising but coherent material gesture.",
            "A silhouette that could be recognized from across the room.",
        ],
        must_keep=[
            "Keep the hero source object clearly recognizable.",
            "Keep source colors and material texture recognizable.",
            "Keep the result as one coherent designed object.",
        ],
        must_avoid=[
            "Do not invent unrelated major objects.",
            "Do not create visual clutter or several competing concepts.",
            "Do not add text, labels, logos, plaques, or branding.",
            "Do not hide the hero object behind the secondary material.",
            "Do not fall back to an evenly wrapped LED spiral, stacked ring base, or simple decorative sleeve unless the candidate absolutely requires it.",
        ],
    )


def _validate_direction(
    *,
    direction: VisualDirection,
    state: ProjectState,
    future: ReviewedFuture,
) -> None:
    candidate_ids = {use.material_item_id for use in future.candidate.material_uses}
    known_ids = {item.item_id for item in state.materials}
    allowed = candidate_ids or known_ids
    if direction.hero_material_id not in allowed:
        raise VisualDirectorError("Visual Director selected an unknown hero material")
    invalid = (set(direction.secondary_material_ids) | set(direction.accent_material_ids)) - allowed
    if invalid:
        raise VisualDirectorError("Visual Director referenced unknown source materials")
    if direction.hero_material_id in set(direction.secondary_material_ids) | set(direction.accent_material_ids):
        raise VisualDirectorError("Hero material cannot also be secondary/accent")


async def generate_visual_direction(
    *,
    state: ProjectState,
    future: ReviewedFuture,
    render_mode: RenderMode | None = None,
    client: AsyncOpenAI | None = None,
    model: str | None = None,
) -> VisualDirection:
    render_mode = render_mode or select_render_mode(future)
    model = model or os.getenv("RUINFORM_VISUAL_DIRECTOR_MODEL", DEFAULT_MODEL)
    client = client or AsyncOpenAI()

    candidate_ids = {use.material_item_id for use in future.candidate.material_uses}
    role_by_id = {use.material_item_id: use.role for use in future.candidate.material_uses}
    material_lines = []
    for item in state.materials:
        if candidate_ids and item.item_id not in candidate_ids:
            continue
        observations = [obs.label for obs in item.observations[:6]]
        material_lines.append(
            f"- {item.item_id}: {item.display_name}; candidate role: {role_by_id.get(item.item_id, 'source')}; "
            f"observed: {'; '.join(observations) or 'no extra observations'}"
        )

    intent = state.creative_intent
    content: list[dict[str, object]] = [
        {
            "type": "input_text",
            "text": (
                "Direct the next RUINFORM image generation at HIGH TASTE.\n\n"
                f"RENDER MODE: {render_mode}\n\n"
                f"PERSISTENT CREATIVE DIRECTION: {intent.direction or 'open exploration'}\n"
                f"DIFFICULTY MODE: {intent.difficulty_mode}\n"
                f"BACKGROUND CONTRACT: {_background_contract(state)}\n\n"
                "Creative Direction guides authorship and constraints, but must not erase source identity or turn this into generic text-to-image. "
                "Background Mode controls presentation only: do not redesign the object to fit scenery.\n\n"
                f"SOURCE MATERIALS:\n{chr(10).join(material_lines)}\n\n"
                f"PROJECT STATE: {compact_state_json(state)}\n\n"
                f"SELECTED CANDIDATE: {future.candidate.model_dump_json()}\n\n"
                f"FEASIBILITY REVIEW: {future.review.model_dump_json()}\n\n"
                "The previous failure mode to fight is a clean but generic render: source objects stacked, sleeved, "
                "or evenly wrapped with light. Choose one hero, one conceptual tension and one authored signature gesture. "
                "Reject the most obvious decorative solution even if it is technically valid. "
                "Also fight the opposite failure: do not bury a simple source-driven idea under a large inventory of invented hardware. "
                "Supporting parts should earn their place and remain visually subordinate to the user's source objects."
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

    response = await client.responses.create(
        model=model,
        reasoning={"effort": "medium"},
        instructions=load_visual_director_prompt(),
        input=[{"role": "user", "content": content}],
        text={
            "format": {
                "type": "json_schema",
                "name": "ruinform_visual_direction",
                "strict": True,
                "schema": VisualDirection.model_json_schema(),
            }
        },
    )

    if not response.output_text:
        raise VisualDirectorError("Visual Director returned no direction")
    try:
        direction = VisualDirection.model_validate(json.loads(response.output_text))
    except (json.JSONDecodeError, ValueError) as exc:
        raise VisualDirectorError("Visual Director returned invalid structured output") from exc

    _validate_direction(direction=direction, state=state, future=future)
    return direction
