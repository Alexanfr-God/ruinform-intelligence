from __future__ import annotations

import json
import os

from openai import AsyncOpenAI

from .future_models import CandidatePool, ReviewBatch
from .models import ProjectState
from .prompt_loader import load_prompt_file


DEFAULT_MODEL = "gpt-5.6"


class FeasibilityError(RuntimeError):
    pass


def load_feasibility_prompt() -> str:
    return load_prompt_file("feasibility_critic.md")


def _validate_review_batch(*, pool: CandidatePool, batch: ReviewBatch) -> None:
    expected_ids = {candidate.candidate_id for candidate in pool.candidates}
    review_ids = [review.candidate_id for review in batch.reviews]
    if len(review_ids) != len(set(review_ids)):
        raise FeasibilityError("Feasibility Critic returned duplicate candidate reviews")
    missing = expected_ids - set(review_ids)
    extra = set(review_ids) - expected_ids
    if missing or extra:
        details = []
        if missing:
            details.append("missing=" + ",".join(sorted(missing)))
        if extra:
            details.append("extra=" + ",".join(sorted(extra)))
        raise FeasibilityError("Review batch does not match candidate pool: " + " ".join(details))


async def review_candidate_pool(
    *,
    state: ProjectState,
    pool: CandidatePool,
    client: AsyncOpenAI | None = None,
    model: str | None = None,
) -> ReviewBatch:
    model = model or os.getenv("RUINFORM_FEASIBILITY_MODEL", DEFAULT_MODEL)
    client = client or AsyncOpenAI()

    response = await client.responses.create(
        model=model,
        reasoning={"effort": "high"},
        instructions=load_feasibility_prompt(),
        input=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": (
                            "Review every future form against the trusted project state.\n\n"
                            f"Project state: {state.model_dump_json()}\n\n"
                            f"Candidate pool: {pool.model_dump_json()}"
                        ),
                    }
                ],
            }
        ],
        text={
            "format": {
                "type": "json_schema",
                "name": "ruinform_feasibility_reviews",
                "strict": True,
                "schema": ReviewBatch.model_json_schema(),
            }
        },
    )

    if not response.output_text:
        raise FeasibilityError("Feasibility Critic returned no reviews")
    try:
        batch = ReviewBatch.model_validate(json.loads(response.output_text))
    except (json.JSONDecodeError, ValueError) as exc:
        raise FeasibilityError("Feasibility Critic returned invalid structured output") from exc

    _validate_review_batch(pool=pool, batch=batch)
    return batch
