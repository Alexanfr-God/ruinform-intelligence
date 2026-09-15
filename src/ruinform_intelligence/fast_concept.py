from __future__ import annotations

import logging

from .feasibility import FeasibilityError, review_candidate_pool
from .form_architect import FormArchitectError, generate_candidate_pool
from .future_models import FutureFormsResult, FuturePreferences
from .future_pipeline import select_top_futures
from .models import ProjectState


logger = logging.getLogger("ruinform.fast_concept")


class FastConceptError(RuntimeError):
    pass


async def discover_concept_futures_fast(
    *,
    state: ProjectState,
    preferences: FuturePreferences,
    user_intent: str | None = None,
) -> FutureFormsResult:
    """Low-latency Concept Mode discovery.

    Concept Mode is exploratory by definition. The Live Lab therefore performs only the
    two decisions required before showing ideas: one broad generation call and one batched
    critic call. Visual briefs are intentionally deferred until the user chooses a future.
    This keeps the first WOW loop responsive without weakening the render trust gate.
    """

    effective = preferences.model_copy(update={"concept_mode": True})
    try:
        logger.info("concept.fast architect:start project=%s", state.project_id)
        pool = await generate_candidate_pool(
            state=state,
            preferences=effective,
            user_intent=user_intent,
        )
        logger.info(
            "concept.fast architect:done project=%s candidates=%s",
            state.project_id,
            len(pool.candidates),
        )

        logger.info("concept.fast critic:start project=%s", state.project_id)
        batch = await review_candidate_pool(
            state=state,
            pool=pool,
            concept_mode=True,
        )
        logger.info(
            "concept.fast critic:done project=%s reviews=%s",
            state.project_id,
            len(batch.reviews),
        )
    except (FormArchitectError, FeasibilityError) as exc:
        raise FastConceptError(str(exc)) from exc

    reviews_by_id = {review.candidate_id: review for review in batch.reviews}
    selected = select_top_futures(
        pool=pool,
        reviews_by_id=reviews_by_id,
        preferences=effective,
        limit=3,
    )

    needs_regeneration = len(selected) < 3
    return FutureFormsResult(
        internal_candidate_count=len(pool.candidates),
        reviewed_candidate_count=len(batch.reviews),
        revision_attempt_count=0,
        selected_futures=selected,
        needs_regeneration=needs_regeneration,
        regeneration_reason=(
            "Fast Concept Mode found fewer than three critic-approved futures. "
            "The visible concepts are still exploratory; regenerate or add evidence for a broader result."
            if needs_regeneration
            else None
        ),
    )
