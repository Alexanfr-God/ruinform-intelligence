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
    if future.visual_brief is None or future.review.status != "pass":
        raise RenderReviewAgentError("Only approved futures with a VisualBrief may be reviewed")
    if request.candidate_id != future.candidate.candidate_id:
        raise RenderReviewAgentError("Candidate mismatch")

    content: list[dict] = [
        {
            "type": "input_text",
            "text": (
                "Evaluate the generated concept image against this approved future and render request. "
                "Return only the structured review.\n\n"
                f"Approved future: {future.model_dump_json()}\n\n"
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
