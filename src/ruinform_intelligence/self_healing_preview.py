from __future__ import annotations

import os

from openai import AsyncOpenAI

from .concept_preview import ConceptPreviewError, generate_concept_preview as generate_base_preview
from .feasibility import FeasibilityError, review_candidate_pool
from .future_models import (
    CandidatePool,
    FeasibilityReview,
    FutureFormsResult,
    ReviewedFuture,
    RevisionRecord,
)
from .models import ProjectState
from .preview_repair import (
    PreviewRepairError,
    build_repair_directives,
    repair_preview_candidates,
)


def _enabled() -> bool:
    return os.getenv("RUINFORM_PREVIEW_SELF_HEAL", "1").strip().lower() not in {"0", "false", "off", "no"}


def _rank_with_gate(review: FeasibilityReview) -> float:
    gate_score = {"pass": 100.0, "revise": 60.0, "reject": 20.0}[review.status]
    return round(
        0.15 * review.feasibility_score
        + 0.10 * review.material_fit_score
        + 0.10 * review.buildability_score
        + 0.20 * review.originality_score
        + 0.20 * review.artistic_impact_score
        + 0.05 * review.usefulness_score
        + 0.10 * review.value_potential_score
        + 0.10 * gate_score,
        2,
    )


def _critic_note(review: FeasibilityReview) -> str:
    if review.status == "pass":
        reason = review.reasons[0] if review.reasons else "credible direction worth visualizing"
        return f"PRE-RENDER CRITIC PASS — {reason}"
    changes = " · ".join(review.required_changes[:2])
    if not changes:
        changes = review.reasons[0] if review.reasons else "simplify or rethink before spending render tokens"
    return f"PRE-RENDER CRITIC {review.status.upper()} — {changes}"


def _clean_old_gate_notes(items: list[str]) -> list[str]:
    return [item for item in items if not item.startswith("PRE-RENDER CRITIC ")]


async def generate_concept_preview(
    *,
    state: ProjectState,
    mode: str = "hybrid",
    user_intent: str | None = None,
    client: AsyncOpenAI | None = None,
    model: str | None = None,
) -> FutureFormsResult:
    """Generate four futures, then repair flagged slots once before showing them.

    This deliberately wraps the stable preview pipeline instead of re-introducing an
    open-ended critic loop. PASS concepts are immutable. Every REVISE/REJECT slot may
    be touched once, the repaired subset is reviewed once, and the process stops.
    """

    client = client or AsyncOpenAI()
    base = await generate_base_preview(
        state=state,
        mode=mode,
        user_intent=user_intent,
        client=client,
        model=model,
    )

    trace = dict(base.retrieval_trace)
    if not _enabled():
        trace["self_healing"] = {
            "version": "wave3_self_healing_v1",
            "enabled": False,
            "attempted": False,
            "reason": "disabled_by_environment",
        }
        return base.model_copy(update={"retrieval_trace": trace})

    reviews_by_id = {item.candidate.candidate_id: item.review for item in base.selected_futures}
    candidates = [item.candidate for item in base.selected_futures]
    directives = build_repair_directives(candidates, reviews_by_id)
    if not directives:
        trace["self_healing"] = {
            "version": "wave3_self_healing_v1",
            "enabled": True,
            "attempted": False,
            "reason": "all_candidates_passed",
        }
        return base.model_copy(update={"retrieval_trace": trace})

    locked = [
        item.candidate
        for item in base.selected_futures
        if item.review.status == "pass"
    ]
    actions = {directive.candidate_id: directive.action for directive in directives}
    before_names = {
        directive.candidate_id: directive.original_candidate.name
        for directive in directives
    }
    initial_status = {
        directive.candidate_id: directive.critic_review.status
        for directive in directives
    }

    try:
        repaired = await repair_preview_candidates(
            state=state,
            directives=directives,
            locked_survivors=locked,
            memory_context=None,
            client=client,
        )
        repaired_pool = CandidatePool(candidates=[repaired[directive.candidate_id] for directive in directives])
        second_batch = await review_candidate_pool(
            state=state,
            pool=repaired_pool,
            concept_mode=True,
            client=client,
            reasoning_effort=os.getenv("RUINFORM_PRE_RENDER_CRITIC_REASONING", "low"),
            retrieval_trace=base.retrieval_trace,
        )
        second_reviews = {review.candidate_id: review for review in second_batch.reviews}
    except (PreviewRepairError, FeasibilityError, KeyError) as exc:
        trace["self_healing"] = {
            "version": "wave3_self_healing_v1",
            "enabled": True,
            "attempted": True,
            "error": str(exc),
            "targets": [
                {
                    "candidate_id": directive.candidate_id,
                    "action": directive.action,
                    "before_name": directive.original_candidate.name,
                    "before_status": directive.critic_review.status,
                }
                for directive in directives
            ],
            "fallback": "original_flagged_candidates_preserved",
        }
        return base.model_copy(update={"retrieval_trace": trace})

    original_by_id = {item.candidate.candidate_id: item for item in base.selected_futures}
    final_items: list[ReviewedFuture] = []
    healing_rows: list[dict[str, object]] = []

    for original in base.selected_futures:
        candidate_id = original.candidate.candidate_id
        if candidate_id not in repaired:
            final_items.append(original)
            continue

        candidate_after = repaired[candidate_id]
        review_after = second_reviews[candidate_id]
        gate_note = _critic_note(review_after)
        candidate_after = candidate_after.model_copy(
            update={
                "unresolved_dependencies": [gate_note]
                + _clean_old_gate_notes(list(candidate_after.unresolved_dependencies))
            }
        )
        history = list(original.revision_history)
        history.append(
            RevisionRecord(
                round_index=1,
                critique_status=original.review.status,
                requested_changes=list(original.review.required_changes),
                candidate_before=original.candidate,
                candidate_after=candidate_after,
            )
        )
        final_items.append(
            ReviewedFuture(
                candidate=candidate_after,
                review=review_after,
                rank_score=_rank_with_gate(review_after),
                revision_history=history,
                visual_brief=None,
            )
        )
        healing_rows.append(
            {
                "candidate_id": candidate_id,
                "action": actions[candidate_id],
                "before_name": before_names[candidate_id],
                "after_name": candidate_after.name,
                "before_status": initial_status[candidate_id],
                "after_status": review_after.status,
                "after_rank_score": _rank_with_gate(review_after),
                "remaining_required_changes": list(review_after.required_changes),
            }
        )

    final_items.sort(key=lambda item: item.rank_score, reverse=True)
    remaining_rejects = [
        item.candidate.candidate_id
        for item in final_items
        if item.review.status == "reject"
    ]

    trace["self_healing"] = {
        "version": "wave3_self_healing_v1",
        "enabled": True,
        "attempted": True,
        "pass_limit": 1,
        "targets": healing_rows,
        "remaining_rejects": remaining_rejects,
        "policy": "PASS locked; REVISE repaired once; REJECT replaced once; no recursive loop",
    }

    return FutureFormsResult(
        internal_candidate_count=base.internal_candidate_count + len(directives),
        reviewed_candidate_count=base.reviewed_candidate_count + len(second_reviews),
        revision_attempt_count=base.revision_attempt_count + len(directives),
        selected_futures=final_items,
        needs_regeneration=bool(remaining_rejects),
        regeneration_reason=(
            "One-pass self-healing completed, but one or more replacement/revision candidates still failed the pre-render gate."
            if remaining_rejects
            else None
        ),
        retrieval_trace=trace,
    )


__all__ = ["ConceptPreviewError", "generate_concept_preview"]
