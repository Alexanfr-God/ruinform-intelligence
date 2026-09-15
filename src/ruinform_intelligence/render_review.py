from __future__ import annotations

from .render_models import RenderCritique

MIN_BRIEF_FIDELITY = 78
MIN_SOURCE_FIDELITY = 72
MAX_INVENTION_RISK = 25


class RenderReviewError(RuntimeError):
    pass


def enforce_render_gate(review: RenderCritique) -> RenderCritique:
    has_blocker = any(item.severity == "critical" for item in review.violations)
    misses_floor = (
        review.brief_fidelity_score < MIN_BRIEF_FIDELITY
        or review.source_material_fidelity_score < MIN_SOURCE_FIDELITY
        or review.invention_risk_score > MAX_INVENTION_RISK
    )
    if (has_blocker or misses_floor) and review.status == "pass":
        return review.model_copy(update={"status": "regenerate"})
    return review
