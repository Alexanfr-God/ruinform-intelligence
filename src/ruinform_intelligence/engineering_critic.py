from __future__ import annotations

import json
import os

from openai import AsyncOpenAI

from .build_evidence import build_evidence_image_urls
from .build_models import BuildCriticReview, BuildPlan
from .future_models import ReviewedFuture
from .models import ProjectState
from .prompt_loader import load_prompt_file
from .reasoning_state import compact_state_json


DEFAULT_MODEL = "gpt-5.6"


class EngineeringCriticError(RuntimeError):
    pass


def load_engineering_critic_prompt() -> str:
    return load_prompt_file("engineering_critic.md")


def _normalize_review(review: BuildCriticReview) -> BuildCriticReview:
    # A PASS with required changes is internally contradictory. Keep the critic bounded and
    # deterministic by upgrading that result to REVISE instead of silently ignoring changes.
    if review.status == "pass" and review.required_changes:
        return review.model_copy(update={"status": "revise"})
    return review


async def review_build_plan(
    *,
    state: ProjectState,
    future: ReviewedFuture,
    plan: BuildPlan,
    accepted_image_url: str,
    client: AsyncOpenAI | None = None,
    model: str | None = None,
) -> BuildCriticReview:
    if not accepted_image_url.strip():
        raise EngineeringCriticError("Engineering Critic requires the approved render image")

    model = model or os.getenv("RUINFORM_ENGINEERING_CRITIC_MODEL", DEFAULT_MODEL)
    client = client or AsyncOpenAI()
    evidence_images = build_evidence_image_urls(state, future.candidate.candidate_id)
    content: list[dict[str, str]] = [
        {
            "type": "input_text",
            "text": (
                "Audit this Build Master plan before RUINFORM presents it as a practical handoff.\n\n"
                "The first attached image is the exact render approved by the user. Verify that the plan reproduces that visual without inventing physical facts.\n\n"
                f"ADDITIONAL WORKSHOP EVIDENCE PHOTOS: {len(evidence_images)}. If present, they follow the approved render. "
                "Use them only for visible evidence; do not infer hidden structure, ratings, material grade, or dimensions from appearance.\n\n"
                f"Project state: {compact_state_json(state)}\n\n"
                f"Approved future: {future.candidate.model_dump_json()}\n\n"
                f"Pre-render feasibility review: {future.review.model_dump_json()}\n\n"
                f"Build plan: {plan.model_dump_json()}"
            ),
        },
        {"type": "input_image", "image_url": accepted_image_url},
    ]
    content.extend({"type": "input_image", "image_url": image_url} for image_url in evidence_images)

    response = await client.responses.create(
        model=model,
        reasoning={"effort": "medium"},
        instructions=load_engineering_critic_prompt(),
        input=[{"role": "user", "content": content}],
        text={
            "format": {
                "type": "json_schema",
                "name": "ruinform_engineering_critic",
                "strict": True,
                "schema": BuildCriticReview.model_json_schema(),
            }
        },
    )

    if not response.output_text:
        raise EngineeringCriticError("Engineering Critic returned no review")

    try:
        review = BuildCriticReview.model_validate(json.loads(response.output_text))
    except (json.JSONDecodeError, ValueError) as exc:
        raise EngineeringCriticError("Engineering Critic returned invalid structured output") from exc

    if review.candidate_id != future.candidate.candidate_id:
        raise EngineeringCriticError("Engineering Critic candidate_id does not match selected future")
    return _normalize_review(review)
