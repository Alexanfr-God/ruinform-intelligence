from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Protocol

from .eval_models import EvalOutcome, EvalRecord


class EvalStore(Protocol):
    backend_name: str

    def save(self, record: EvalRecord) -> EvalRecord: ...

    def list_for_session(self, session_id: str, limit: int = 20) -> list[EvalRecord]: ...

    def list_recent(
        self,
        *,
        outcome: EvalOutcome | None = None,
        limit: int = 50,
    ) -> list[EvalRecord]: ...


class SqliteEvalStore:
    backend_name = "sqlite"

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
                CREATE TABLE IF NOT EXISTS evaluation_records (
                    eval_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    candidate_id TEXT NOT NULL,
                    candidate_name TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    wow_score INTEGER NOT NULL,
                    difficulty_mode TEXT NOT NULL,
                    background_mode TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at_iso TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_eval_session ON evaluation_records(session_id, created_at_iso DESC)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_eval_outcome ON evaluation_records(outcome, created_at_iso DESC)"
            )

    def save(self, record: EvalRecord) -> EvalRecord:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO evaluation_records(
                    eval_id, session_id, project_id, candidate_id, candidate_name,
                    outcome, wow_score, difficulty_mode, background_mode,
                    payload_json, created_at_iso
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(eval_id) DO UPDATE SET
                    outcome=excluded.outcome,
                    wow_score=excluded.wow_score,
                    payload_json=excluded.payload_json
                """,
                (
                    record.eval_id,
                    record.session_id,
                    record.project_id,
                    record.candidate_id,
                    record.candidate_name,
                    record.outcome,
                    record.wow_score,
                    record.difficulty_mode,
                    record.background_mode,
                    record.model_dump_json(),
                    record.created_at_iso,
                ),
            )
        return record

    def list_for_session(self, session_id: str, limit: int = 20) -> list[EvalRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT payload_json FROM evaluation_records
                WHERE session_id = ?
                ORDER BY created_at_iso DESC
                LIMIT ?
                """,
                (session_id, limit),
            ).fetchall()
        return [EvalRecord.model_validate_json(row[0]) for row in rows]

    def list_recent(
        self,
        *,
        outcome: EvalOutcome | None = None,
        limit: int = 50,
    ) -> list[EvalRecord]:
        with self._connect() as conn:
            if outcome:
                rows = conn.execute(
                    """
                    SELECT payload_json FROM evaluation_records
                    WHERE outcome = ?
                    ORDER BY created_at_iso DESC
                    LIMIT ?
                    """,
                    (outcome, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT payload_json FROM evaluation_records
                    ORDER BY created_at_iso DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
        return [EvalRecord.model_validate_json(row[0]) for row in rows]


class PostgresEvalStore:
    backend_name = "postgres"

    def __init__(self, database_url: str | None = None) -> None:
        self.database_url = database_url or os.getenv("DATABASE_URL") or os.getenv("RUINFORM_DATABASE_URL")
        if not self.database_url:
            raise RuntimeError("DATABASE_URL is required for PostgresEvalStore")
        self._initialized = False

    def _connect(self):
        try:
            import psycopg
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("psycopg is required for PostgresEvalStore") from exc
        return psycopg.connect(self.database_url)

    def _ensure_initialized(self) -> None:
        if self._initialized:
            return
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS evaluation_records (
                        eval_id TEXT PRIMARY KEY,
                        session_id TEXT NOT NULL,
                        project_id TEXT NOT NULL,
                        candidate_id TEXT NOT NULL,
                        candidate_name TEXT NOT NULL,
                        outcome TEXT NOT NULL,
                        wow_score INTEGER NOT NULL,
                        difficulty_mode TEXT NOT NULL,
                        background_mode TEXT NOT NULL,
                        payload_json TEXT NOT NULL,
                        created_at_iso TEXT NOT NULL
                    )
                    """
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_eval_session ON evaluation_records(session_id, created_at_iso DESC)"
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_eval_outcome ON evaluation_records(outcome, created_at_iso DESC)"
                )
            conn.commit()
        self._initialized = True

    def save(self, record: EvalRecord) -> EvalRecord:
        self._ensure_initialized()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO evaluation_records(
                        eval_id, session_id, project_id, candidate_id, candidate_name,
                        outcome, wow_score, difficulty_mode, background_mode,
                        payload_json, created_at_iso
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT(eval_id) DO UPDATE SET
                        outcome=EXCLUDED.outcome,
                        wow_score=EXCLUDED.wow_score,
                        payload_json=EXCLUDED.payload_json
                    """,
                    (
                        record.eval_id,
                        record.session_id,
                        record.project_id,
                        record.candidate_id,
                        record.candidate_name,
                        record.outcome,
                        record.wow_score,
                        record.difficulty_mode,
                        record.background_mode,
                        record.model_dump_json(),
                        record.created_at_iso,
                    ),
                )
            conn.commit()
        return record

    def list_for_session(self, session_id: str, limit: int = 20) -> list[EvalRecord]:
        self._ensure_initialized()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT payload_json FROM evaluation_records
                    WHERE session_id = %s
                    ORDER BY created_at_iso DESC
                    LIMIT %s
                    """,
                    (session_id, limit),
                )
                rows = cur.fetchall()
        return [EvalRecord.model_validate_json(row[0]) for row in rows]

    def list_recent(
        self,
        *,
        outcome: EvalOutcome | None = None,
        limit: int = 50,
    ) -> list[EvalRecord]:
        self._ensure_initialized()
        with self._connect() as conn:
            with conn.cursor() as cur:
                if outcome:
                    cur.execute(
                        """
                        SELECT payload_json FROM evaluation_records
                        WHERE outcome = %s
                        ORDER BY created_at_iso DESC
                        LIMIT %s
                        """,
                        (outcome, limit),
                    )
                else:
                    cur.execute(
                        """
                        SELECT payload_json FROM evaluation_records
                        ORDER BY created_at_iso DESC
                        LIMIT %s
                        """,
                        (limit,),
                    )
                rows = cur.fetchall()
        return [EvalRecord.model_validate_json(row[0]) for row in rows]


def create_eval_store() -> EvalStore:
    if os.getenv("DATABASE_URL") or os.getenv("RUINFORM_DATABASE_URL"):
        return PostgresEvalStore()
    return SqliteEvalStore()
