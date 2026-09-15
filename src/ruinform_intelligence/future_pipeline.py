from __future__ import annotations

from openai import AsyncOpenAI

from .feasibility import FeasibilityError, review_candidate_pool
from .form_architect import FormArchitectError, generate_candidate_pool
from .future_models import (
    CandidatePool,
    FeasibilityReview,
    FutureFormsResult,
    FuturePreferences,
    ReviewedFuture,
)
from .models import ProjectState


class FuturePipelineError(RuntimeError):
    pass


def rank_score(review: FeasibilityReview, preferences: FuturePreferences) -> float:
    core = 0.25 * review.feasibility_score + 0.20 * review.material_fit_score

    weighted_metrics = [
        (preferences.originality, review.originality_score),
        (preferences.artistic_impact, review.artistic_impact_score),
        (preferences.usefulness, review.usefulness_score),
        (preferences.ease, review.buildability_score),
        (preferences.value, review.value_potential_score),
    ]
    total_weight = sum(weight for weight, _ in weighted_metrics)
    if total_weight > 0:
        preference_average = sum(weight * score for weight, score in weighted_metrics) / total_weight
    else:
        preference_average = 0.0

    return round(core + 0.55 * preference_average, 2)


def select_top_futures(
    *,
    pool: CandidatePool,
    reviews_by_id: dict[str, FeasibilityReview],
    preferences: FuturePreferences,
    limit: int = 3,
) -> list[ReviewedFuture]:
    reviewed: list[ReviewedFuture] = []
    for candidate in pool.candidates:
        review = reviews_by_id[candidate.candidate_id]
        if review.status != "pass":
            continue
        reviewed.append(
            ReviewedFuture(
                candidate=candidate,
                review=review,
                rank_score=rank_score(review, preferences),
            )
        )
    reviewed.sort(key=lambda item: item.rank_score, reverse=True)
    return reviewed[:limit]


async def discover_future_forms(
    *,
    state: ProjectState,
    preferences: FuturePreferences | None = None,
    user_intent: str | None = None,
    client: AsyncOpenAI | None = None,
    architect_model: str | None = None,
    critic_model: str | None = None,
) -> FutureFormsResult:
    preferences = preferences or FuturePreferences()
    try:
        pool = await generate_candidate_pool(
            state=state,
            preferences=preferences,
            user_intent=user_intent,
            client=client,
            model=architect_model,
        )
        batch = await review_candidate_pool(
            state=state,
            pool=pool,
            client=client,
            model=critic_model,
        )
    except (FormArchitectError, FeasibilityError) as exc:
        raise FuturePipelineError(str(exc)) from exc

    reviews_by_id = {review.candidate_id: review for review in batch.reviews}
    selected = select_top_futures(
        pool=pool,
        reviews_by_id=reviews_by_id,
        preferences=preferences,
        limit=3,
    )

    needs_regeneration = len(selected) < 3
    return FutureFormsResult(
        internal_candidate_count=len(pool.candidates),
        reviewed_candidate_count=len(batch.reviews),
        selected_futures=selected,
        needs_regeneration=needs_regeneration,
        regeneration_reason=(
            "Fewer than three candidates passed feasibility review. Generate a revised pool before showing a full set."
            if needs_regeneration
            else None
        ),
    )
