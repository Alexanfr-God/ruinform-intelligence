from __future__ import annotations

from openai import AsyncOpenAI

from .feasibility import FeasibilityError, review_candidate_pool
from .form_architect import FormArchitectError, generate_candidate_pool
from .future_models import (
    CandidateForm,
    CandidatePool,
    FeasibilityReview,
    FutureFormsResult,
    FuturePreferences,
    ReviewedFuture,
    RevisionRecord,
)
from .models import ProjectState
from .revision_architect import RevisionArchitectError, revise_candidate
from .visual_brief import VisualBriefError, generate_visual_brief


MAX_REVISION_ROUNDS = 2
MAX_REVISION_CANDIDATES = 5


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
    preference_average = (
        sum(weight * score for weight, score in weighted_metrics) / total_weight
        if total_weight > 0
        else 0.0
    )
    return round(core + 0.55 * preference_average, 2)


def prioritize_revision_candidates(
    *,
    pool: CandidatePool,
    reviews_by_id: dict[str, FeasibilityReview],
    preferences: FuturePreferences,
    limit: int = MAX_REVISION_CANDIDATES,
) -> list[CandidateForm]:
    revisable = [
        candidate
        for candidate in pool.candidates
        if reviews_by_id[candidate.candidate_id].status == "revise"
    ]
    revisable.sort(
        key=lambda candidate: rank_score(
            reviews_by_id[candidate.candidate_id],
            preferences,
        ),
        reverse=True,
    )
    return revisable[:limit]


def select_top_futures(
    *,
    pool: CandidatePool,
    reviews_by_id: dict[str, FeasibilityReview],
    preferences: FuturePreferences,
    revision_history_by_id: dict[str, list[RevisionRecord]] | None = None,
    limit: int = 3,
) -> list[ReviewedFuture]:
    revision_history_by_id = revision_history_by_id or {}
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
                revision_history=revision_history_by_id.get(candidate.candidate_id, []),
            )
        )
    reviewed.sort(key=lambda item: item.rank_score, reverse=True)
    return reviewed[:limit]


async def _review_single_candidate(
    *,
    state: ProjectState,
    candidate: CandidateForm,
    concept_mode: bool,
    client: AsyncOpenAI | None,
    critic_model: str | None,
) -> FeasibilityReview:
    batch = await review_candidate_pool(
        state=state,
        pool=CandidatePool(candidates=[candidate]),
        concept_mode=concept_mode,
        client=client,
        model=critic_model,
    )
    return batch.reviews[0]


async def _revise_until_decided(
    *,
    state: ProjectState,
    candidate: CandidateForm,
    initial_review: FeasibilityReview,
    preferences: FuturePreferences,
    client: AsyncOpenAI | None,
    revision_model: str | None,
    critic_model: str | None,
    max_rounds: int,
) -> tuple[CandidateForm, FeasibilityReview, list[RevisionRecord]]:
    current_candidate = candidate
    current_review = initial_review
    history: list[RevisionRecord] = []

    for round_index in range(1, max_rounds + 1):
        if current_review.status != "revise":
            break
        revised = await revise_candidate(
            state=state,
            candidate=current_candidate,
            review=current_review,
            preferences=preferences,
            client=client,
            model=revision_model,
        )
        history.append(
            RevisionRecord(
                round_index=round_index,
                critique_status="revise",
                requested_changes=list(current_review.required_changes),
                candidate_before=current_candidate,
                candidate_after=revised,
            )
        )
        current_candidate = revised
        current_review = await _review_single_candidate(
            state=state,
            candidate=current_candidate,
            concept_mode=preferences.concept_mode,
            client=client,
            critic_model=critic_model,
        )

    return current_candidate, current_review, history


async def discover_future_forms(
    *,
    state: ProjectState,
    preferences: FuturePreferences | None = None,
    user_intent: str | None = None,
    client: AsyncOpenAI | None = None,
    architect_model: str | None = None,
    critic_model: str | None = None,
    revision_model: str | None = None,
    visual_brief_model: str | None = None,
    max_revision_rounds: int = MAX_REVISION_ROUNDS,
) -> FutureFormsResult:
    preferences = preferences or FuturePreferences()
    if not 0 <= max_revision_rounds <= 5:
        raise FuturePipelineError("max_revision_rounds must be between 0 and 5")

    try:
        initial_pool = await generate_candidate_pool(
            state=state,
            preferences=preferences,
            user_intent=user_intent,
            client=client,
            model=architect_model,
        )
        initial_batch = await review_candidate_pool(
            state=state,
            pool=initial_pool,
            concept_mode=preferences.concept_mode,
            client=client,
            model=critic_model,
        )

        reviews_by_id = {review.candidate_id: review for review in initial_batch.reviews}
        candidates_by_id = {candidate.candidate_id: candidate for candidate in initial_pool.candidates}
        revision_history: dict[str, list[RevisionRecord]] = {
            candidate.candidate_id: [] for candidate in initial_pool.candidates
        }

        pass_count = sum(1 for review in initial_batch.reviews if review.status == "pass")
        if pass_count < 3 and max_revision_rounds > 0:
            revision_queue = prioritize_revision_candidates(
                pool=initial_pool,
                reviews_by_id=reviews_by_id,
                preferences=preferences,
            )
            for candidate in revision_queue:
                if pass_count >= 3:
                    break
                final_candidate, final_review, history = await _revise_until_decided(
                    state=state,
                    candidate=candidate,
                    initial_review=reviews_by_id[candidate.candidate_id],
                    preferences=preferences,
                    client=client,
                    revision_model=revision_model,
                    critic_model=critic_model,
                    max_rounds=max_revision_rounds,
                )
                candidates_by_id[candidate.candidate_id] = final_candidate
                reviews_by_id[candidate.candidate_id] = final_review
                revision_history[candidate.candidate_id] = history
                if final_review.status == "pass":
                    pass_count += 1

        final_pool = CandidatePool(
            candidates=[
                candidates_by_id[candidate.candidate_id]
                for candidate in initial_pool.candidates
            ]
        )
        selected = select_top_futures(
            pool=final_pool,
            reviews_by_id=reviews_by_id,
            preferences=preferences,
            revision_history_by_id=revision_history,
            limit=3,
        )

        with_visuals: list[ReviewedFuture] = []
        for item in selected:
            brief = await generate_visual_brief(
                state=state,
                candidate=item.candidate,
                review=item.review,
                concept_mode=preferences.concept_mode,
                client=client,
                model=visual_brief_model,
            )
            with_visuals.append(item.model_copy(update={"visual_brief": brief}))
    except (
        FormArchitectError,
        FeasibilityError,
        RevisionArchitectError,
        VisualBriefError,
    ) as exc:
        raise FuturePipelineError(str(exc)) from exc

    revision_attempt_count = sum(len(items) for items in revision_history.values())
    needs_regeneration = len(with_visuals) < 3
    return FutureFormsResult(
        internal_candidate_count=len(initial_pool.candidates),
        reviewed_candidate_count=len(initial_batch.reviews) + revision_attempt_count,
        revision_attempt_count=revision_attempt_count,
        selected_futures=with_visuals,
        needs_regeneration=needs_regeneration,
        regeneration_reason=(
            "Fewer than three candidates reached pass status after bounded revision. Generate a new candidate pool."
            if needs_regeneration
            else None
        ),
    )
