from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field


ReviewStatus = Literal["pending", "evaluated"]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ReviewItem(BaseModel):
    """Frozen approved render waiting for human evaluation.

    Review items are deliberately separate from mutable Studio sessions. A project may
    be re-rendered, switch background, or move on to another concept without erasing
    an earlier generated image from the human-learning queue.
    """

    review_id: str
    session_id: str
    project_id: str
    candidate_id: str
    candidate_name: str
    render_url: str
    background_mode: str
    difficulty_mode: str
    creative_direction: str | None = None
    source_items: list[str] = Field(default_factory=list)
    source_material_ids: list[str] = Field(default_factory=list)
    concept_snapshot: dict[str, Any] = Field(default_factory=dict)
    review_snapshot: dict[str, Any] = Field(default_factory=dict)
    render_snapshot: dict[str, Any] = Field(default_factory=dict)
    status: ReviewStatus = "pending"
    eval_id: str | None = None
    created_at_iso: str = Field(default_factory=utc_now_iso)
    evaluated_at_iso: str | None = None
