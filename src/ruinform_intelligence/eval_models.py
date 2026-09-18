from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


EvalOutcome = Literal["success", "mixed", "fail"]
KeepIntent = Literal["yes", "maybe", "no"]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class EvalRecord(BaseModel):
    """A durable human evaluation of one concrete RUINFORM render.

    The record intentionally snapshots the project/concept/render state that existed
    at evaluation time. Later control edits or re-renders must never rewrite history.
    """

    eval_id: str = Field(default_factory=lambda: str(uuid4()))
    session_id: str
    project_id: str
    candidate_id: str
    candidate_name: str
    background_mode: str
    difficulty_mode: str
    creative_direction: str | None = None
    render_url: str

    outcome: EvalOutcome
    idea_score: int = Field(ge=1, le=5)
    wow_score: int = Field(ge=1, le=5)
    physical_credibility_score: int = Field(ge=1, le=5)
    source_participation_score: int = Field(ge=1, le=5)
    collectible_quality_score: int = Field(ge=1, le=5)
    would_keep_or_build: KeepIntent

    failure_tags: list[str] = Field(default_factory=list)
    good_notes: str | None = None
    bad_notes: str | None = None
    next_hypothesis: str | None = None

    source_items: list[str] = Field(default_factory=list)
    source_material_ids: list[str] = Field(default_factory=list)
    concept_snapshot: dict[str, Any] = Field(default_factory=dict)
    review_snapshot: dict[str, Any] = Field(default_factory=dict)
    render_snapshot: dict[str, Any] = Field(default_factory=dict)
    created_at_iso: str = Field(default_factory=utc_now_iso)
