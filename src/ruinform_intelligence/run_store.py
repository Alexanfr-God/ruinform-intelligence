from __future__ import annotations

import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Protocol
from uuid import uuid4

from pydantic import BaseModel, Field

from .build_models import BuildCriticReview, BuildPlan, BuildRevisionTrace
from .future_models import FutureFormsResult
from .models import ProjectState
from .render_models import RenderResult


SessionStage = Literal[
    "evidence_required",
    "ready_for_futures",
    "futures_ready",
    "rendering",
    "completed",
    "build_plan_ready",
    "failed",
]
ReasoningMode = Literal["verified", "concept"]


class RenderJobState(BaseModel):
    candidate_id: str
    aspect_ratio: str = "4:5"
    max_attempts: int = 3
    user_prompt: str | None = None
    presentation_mode: Literal["standard", "post_apocalyptic"] = "post_apocalyptic"
    status: Literal["queued", "running", "completed", "failed"] = "queued"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class TransformationSession(BaseModel):
    session_id: str = Field(default_factory=lambda: str(uuid4()))
    project_id: str
    stage: SessionStage
    project_state: ProjectState
    reasoning_mode: ReasoningMode = "verified"
    concept_mode_acknowledged: bool = False
    concept_notice_version: str | None = None
    futures: FutureFormsResult | None = None
    selected_candidate_id: str | None = None
    render_result: RenderResult | None = None
    render_job: RenderJobState | None = None
    build_plan: BuildPlan | None = None
    build_review: BuildCriticReview | None = None
    build_revision_trace: BuildRevisionTrace | None = None
    last_error: str | None = None
    last_error_stage: str | None = None
    created_at_iso: str = Field(default_factory=utc_now_iso)
    updated_at_iso: str = Field(default_factory=utc_now_iso)


class SessionNotFound(KeyError):
    pass


class RunStore(Protocol):
    backend_name: str

    def save(self, session: TransformationSession) -> TransformationSession: ...

    def get(self, session_id: str) -> TransformationSession: ...


class SqliteRunStore:
    """Local/dev store with a production compatibility bridge.

    Existing callers historically instantiate ``SqliteRunStore`` directly. To avoid a
    risky cross-cutting migration, when DATABASE_URL/RUINFORM_DATABASE_URL is configured
    this constructor transparently returns a ``PostgresRunStore`` instead. Local tests and
    development without a database URL continue to use SQLite.

    SQLite must never be treated as durable storage on hosts with an ephemeral filesystem.
    """

    backend_name = "sqlite"

    def __new__(cls, path: str | None = None):
        if cls is SqliteRunStore and (
            os.getenv("DATABASE_URL") or os.getenv("RUINFORM_DATABASE_URL")
        ):
            return PostgresRunStore()
        return super().__new__(cls)

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


class PostgresRunStore:
    """Durable production store backed by PostgreSQL.

    Connection and schema initialization are intentionally lazy. A temporary database
    issue must not prevent the web process from booting and exposing health information.
    The first real store operation initializes the table and still fails loudly if the
    database is unreachable; there is no silent fallback to SQLite in production.
    """

    backend_name = "postgres"

    def __init__(self, database_url: str | None = None) -> None:
        self.database_url = database_url or os.getenv("DATABASE_URL") or os.getenv("RUINFORM_DATABASE_URL")
        if not self.database_url:
            raise RuntimeError("DATABASE_URL is required for PostgresRunStore")
        self._initialized = False

    def _connect(self):
        try:
            import psycopg
        except ImportError as exc:  # pragma: no cover - packaging guard
            raise RuntimeError("psycopg is required for PostgresRunStore") from exc
        return psycopg.connect(self.database_url, connect_timeout=5)

    def _run_with_retry(self, operation, *, attempts: int = 3):
        """Retry short-lived PostgreSQL transport failures with a fresh connection.

        Every attempt opens a new connection. Session writes are UPSERTs, so replaying a
        write after an EOF around commit is safe and prevents a transient SSL disconnect
        from killing an otherwise healthy render/background job.
        """
        try:
            import psycopg
        except ImportError as exc:  # pragma: no cover - packaging guard
            raise RuntimeError("psycopg is required for PostgresRunStore") from exc

        for attempt in range(attempts):
            try:
                return operation()
            except (psycopg.OperationalError, psycopg.InterfaceError):
                if attempt + 1 >= attempts:
                    raise
                time.sleep(0.2 * (2 ** attempt))

    def _ensure_initialized(self) -> None:
        if self._initialized:
            return

        def initialize() -> None:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
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
                conn.commit()

        self._run_with_retry(initialize)
        self._initialized = True

    def save(self, session: TransformationSession) -> TransformationSession:
        self._ensure_initialized()
        saved = session.model_copy(update={"updated_at_iso": utc_now_iso()})

        def write() -> None:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO transformation_sessions(session_id, project_id, stage, payload_json, updated_at_iso)
                        VALUES (%s, %s, %s, %s, %s)
                        ON CONFLICT(session_id) DO UPDATE SET
                            project_id=EXCLUDED.project_id,
                            stage=EXCLUDED.stage,
                            payload_json=EXCLUDED.payload_json,
                            updated_at_iso=EXCLUDED.updated_at_iso
                        """,
                        (
                            saved.session_id,
                            saved.project_id,
                            saved.stage,
                            saved.model_dump_json(),
                            saved.updated_at_iso,
                        ),
                    )
                conn.commit()

        self._run_with_retry(write)
        return saved

    def get(self, session_id: str) -> TransformationSession:
        self._ensure_initialized()

        def read():
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT payload_json FROM transformation_sessions WHERE session_id = %s",
                        (session_id,),
                    )
                    return cur.fetchone()

        row = self._run_with_retry(read)
        if row is None:
            raise SessionNotFound(session_id)
        return TransformationSession.model_validate_json(row[0])


def create_run_store() -> RunStore:
    """Choose durable Postgres when configured; otherwise use SQLite for local/dev."""
    if os.getenv("DATABASE_URL") or os.getenv("RUINFORM_DATABASE_URL"):
        return PostgresRunStore()
    return SqliteRunStore()
