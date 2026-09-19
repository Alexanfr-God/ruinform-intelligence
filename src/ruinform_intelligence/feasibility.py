from __future__ import annotations

import json
import os
from typing import Any

from openai import AsyncOpenAI

from .future_models import CandidatePool, FeasibilityReview, ReviewBatch
from .models import ProjectState
from .prompt_loader import load_prompt_file
from .reasoning_state import compact_state_json


DEFAULT_MODEL = "gpt-5.6"
_SCORE_FIELDS = (
    "feasibility_score",
    "material_fit_score",
    "buildability_score",
    "originality_score",
    "artistic_impact_score",
    "usefulness_score",
    "value_potential_score",
)


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


def _normalize_review_score_scale(review: FeasibilityReview) -> FeasibilityReview:
    """Repair obvious model drift to a 1–5 or 1–10 scale.

    The public contract is always 0–100. A whole review whose seven scores all sit
    at <=10 is almost certainly scale drift, not an intentional 3/100 across every
    dimension. Keep zero as zero and record the repair for auditability.
    """
    values = [int(getattr(review, field)) for field in _SCORE_FIELDS]
    maximum = max(values, default=0)
    if maximum <= 0 or maximum > 10:
        return review

    factor = 20 if maximum <= 5 else 10
    updates = {
        field: min(100, int(getattr(review, field)) * factor)
        for field in _SCORE_FIELDS
    }
    reasons = list(review.reasons)
    reasons.append(
        f"SYSTEM: normalized critic score drift from an apparent 0–{5 if factor == 20 else 10} scale to 0–100."
    )
    updates["reasons"] = reasons
    return review.model_copy(update=updates)


def _normalize_review_batch(batch: ReviewBatch) -> ReviewBatch:
    return batch.model_copy(
        update={"reviews": [_normalize_review_score_scale(review) for review in batch.reviews]}
    )


def _mode_policy(concept_mode: bool) -> str:
    if not concept_mode:
        return "VERIFIED PATH: score physical feasibility using established evidence and preserve any remaining unknowns."
    return (
        "CONCEPT MODE: the user intentionally continued with incomplete evidence. PASS means 'credible direction for "
        "exploratory visualization', not approval to fabricate or use. Distinguish missing precision from dangerous missing facts. "
        "Unknown ordinary dimensions may be treated as scale-to-fit variables when the candidate can be trimmed, wrapped, folded, "
        "positioned, nested, or adjusted during making; keep them in unresolved_dependencies but do not automatically punish the "
        "concept into rejection. Reward simple, physically legible transformations and quick prototypes made with common hand tools "
        "and cheap declared consumables. Penalize passive arrangements that avoid actual transformation unless the user requested an "
        "installation. High-consequence unknowns such as electrical rating, heat/flame behavior, pressure, load capacity, structural "
        "strength, or chemical safety remain real blockers before fabrication/use and must remain explicit."
    )


def _compact_retrieval_trace(trace: dict[str, Any] | None) -> str:
    if not trace:
        return "none"
    compact = {
        "version": trace.get("version"),
        "strategy": trace.get("strategy"),
        "taste_cards": trace.get("taste_cards", []),
        "evals": trace.get("evals", []),
        "lessons": trace.get("lessons", []),
        "shortlisted_ideas": trace.get("shortlisted_ideas", []),
        "preview_metadata": trace.get("preview_metadata", []),
    }
    return json.dumps(compact, ensure_ascii=False)[:10000]


async def review_candidate_pool(
    *,
    state: ProjectState,
    pool: CandidatePool,
    concept_mode: bool = False,
    client: AsyncOpenAI | None = None,
    model: str | None = None,
    reasoning_effort: str | None = None,
    retrieval_trace: dict[str, Any] | None = None,
) -> ReviewBatch:
    model = model or os.getenv("RUINFORM_FEASIBILITY_MODEL", DEFAULT_MODEL)
    client = client or AsyncOpenAI()
    effort = reasoning_effort or os.getenv("RUINFORM_FEASIBILITY_REASONING", "high")
    if effort not in {"low", "medium", "high"}:
        effort = "high"

    try:
        response = await client.responses.create(
            model=model,
            reasoning={"effort": effort},
            instructions=load_feasibility_prompt(),
            input=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": (
                                "Review every future form against the physical project state.\n\n"
                                f"MODE POLICY: {_mode_policy(concept_mode)}\n\n"
                                "SCORE CONTRACT: all seven numeric score fields are integers on a 0–100 scale. "
                                "Never answer on a 1–5 or 1–10 scale.\n\n"
                                f"Project state: {compact_state_json(state)}\n\n"
                                f"WAVE 3 RETRIEVAL + PREVIEW TRACE: {_compact_retrieval_trace(retrieval_trace)}\n\n"
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
    except Exception as exc:
        raise FeasibilityError(f"Feasibility Critic request failed: {exc}") from exc

    if not response.output_text:
        raise FeasibilityError("Feasibility Critic returned no reviews")
    try:
        batch = ReviewBatch.model_validate(json.loads(response.output_text))
    except (json.JSONDecodeError, ValueError) as exc:
        raise FeasibilityError("Feasibility Critic returned invalid structured output") from exc

    batch = _normalize_review_batch(batch)
    _validate_review_batch(pool=pool, batch=batch)
    return batch
