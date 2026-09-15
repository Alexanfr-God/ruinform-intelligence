from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from .future_models import FutureFormsResult
from .models import ProjectState
from .render_models import RenderResult


SessionStage = Literal[
    "evidence_required",
    "ready_for_futures",
    "futures_ready",
    "rendering",
    "completed",
    "failed",
]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class TransformationSession(BaseModel):
    session_id: str = Field(default_factory=lambda: str(uuid4()))
    project_id: str
    stage: SessionStage
    project_state: ProjectState
    futures: FutureFormsResult | None = None
    selected_candidate_id: str | None = None
    render_result: RenderResult | None = None
    created_at_iso: str = Field(default_factory=utc_now_iso)
    updated_at_iso: str = Field(default_factory=utc_now_iso)


class SessionNotFound(KeyError):
    pass


class SqliteRunStore:
    def __init__(self, path: str | None = None) -> None:
        self.path = Path(path or os.getenv("RUINFORM_DB_PATH", ".ruinform/ruinform.db"))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS transformation_sessions (
                    session_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    updated_at_iso TEXT NOT NULL
                )
                """
            )

    def save(self, session: TransformationSession) -> TransformationSession:
        saved = session.model_copy(update={"updated_at_iso": utc_now_iso()})
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO transformation_sessions(session_id, project_id, stage, payload_json, updated_at_iso)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    project_id=excluded.project_id,
                    stage=excluded.stage,
                    payload_json=excluded.payload_json,
                    updated_at_iso=excluded.updated_at_iso
                """,
                (
                    saved.session_id,
                    saved.project_id,
                    saved.stage,
                    saved.model_dump_json(),
                    saved.updated_at_iso,
                ),
            )
        return saved

    def get(self, session_id: str) -> TransformationSession:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload_json FROM transformation_sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        if row is None:
            raise SessionNotFound(session_id)
        return TransformationSession.model_validate_json(row[0])
