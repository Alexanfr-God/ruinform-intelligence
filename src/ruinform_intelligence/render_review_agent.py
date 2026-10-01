from __future__ import annotations

import json
import os

from openai import AsyncOpenAI

from .future_models import ReviewedFuture
from .prompt_loader import load_prompt_file
from .render_models import ProviderRender, RenderCritique, RenderRequest

DEFAULT_MODEL = "gpt-5.6"


class RenderReviewAgentError(RuntimeError):
    pass


def load_prompt() -> str:
    return load_prompt_file("render_critic.md")


async def evaluate_render(
    *,
    future: ReviewedFuture,
    request: RenderRequest,
    render: ProviderRender,
    client: AsyncOpenAI | None = None,
    model: str | None = None,
) -> RenderCritique:
    if future.review.status == "reject":
        raise RenderReviewAgentError("Rejected futures may not be render-reviewed")
    if request.candidate_id != future.candidate.candidate_id:
        raise RenderReviewAgentError("Candidate mismatch")

    stage_note = (
        "A renderer-safe VisualBrief is attached to the future."
        if future.visual_brief is not None
        else (
            "This is a concept-stage render without a separate VisualBrief. Treat the selected future, "
            "the compiled render request, and the supplied source photographs together as the binding visual contract."
        )
    )
    candidate = future.candidate
    semantic_contract = (
        f"NAME: {candidate.name}\n"
        f"ONE-LINE TRANSFORMATION: {candidate.one_line}\n"
        f"TRANSFORMATION LOGIC: {candidate.transformation_logic}\n"
        f"KEY OPERATIONS: {'; '.join(candidate.key_operations) or 'none declared'}\n"
        f"MATERIAL ROLES: "
        + "; ".join(
            f"{use.material_item_id} => {use.role}"
            + (f" ({use.note})" if use.note else "")
            for use in candidate.material_uses
        )
    )
    content: list[dict] = [
        {
            "type": "input_text",
            "text": (
                "Evaluate the generated concept image against this selected future and render request. "
                "The transformation itself is the primary contract: check whether the image visibly performs the Future's stated path, sequence, progression, spatial relationship, and material operation. "
                "Presence of the correct objects/colors is not enough. Do not reward atmosphere or polish when the semantic geometry is weak. "
                "If the Future says that something changes gradually, link-by-link, through, around, into, before/after, or returns to another element, verify that relationship directly in the pixels. "
                "Return only the structured review.\n\n"
                f"Review stage: {stage_note}\n\n"
                f"BINDING SEMANTIC TRANSFORMATION CONTRACT:\n{semantic_contract}\n\n"
                f"Selected future: {future.model_dump_json()}\n\n"
                f"Render request: {request.model_dump_json()}"
            ),
        },
        {"type": "input_image", "image_url": str(render.image_url), "detail": "high"},
    ]
    for reference in request.references[:8]:
        content.append({"type": "input_image", "image_url": str(reference.image_url), "detail": "high"})

    model = model or os.getenv("RUINFORM_RENDER_CRITIC_MODEL", DEFAULT_MODEL)
    client = client or AsyncOpenAI()
    response = await client.responses.create(
        model=model,
        reasoning={"effort": "high"},
        instructions=load_prompt(),
        input=[{"role": "user", "content": content}],
        text={
            "format": {
                "type": "json_schema",
                "name": "ruinform_render_review",
                "strict": True,
                "schema": RenderCritique.model_json_schema(),
            }
        },
    )
    if not response.output_text:
        raise RenderReviewAgentError("Render review returned no structured output")
    try:
        return RenderCritique.model_validate(json.loads(response.output_text))
    except (json.JSONDecodeError, ValueError) as exc:
        raise RenderReviewAgentError("Render review returned invalid structured output") from exc
