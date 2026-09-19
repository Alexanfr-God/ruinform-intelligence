from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field


IdeaBatchStatus = Literal["pending", "rendered", "archived"]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class IdeaBatch(BaseModel):
    batch_id: str
    session_id: str
    project_id: str
    status: IdeaBatchStatus = "pending"
    background_mode: str
    difficulty_mode: str
    creative_direction: str | None = None
    source_items: list[str] = Field(default_factory=list)
    source_material_ids: list[str] = Field(default_factory=list)
    futures_snapshot: dict[str, Any] = Field(default_factory=dict)
    shortlisted_candidate_ids: list[str] = Field(default_factory=list)
    rendered_candidate_ids: list[str] = Field(default_factory=list)
    created_at_iso: str = Field(default_factory=utc_now_iso)
    updated_at_iso: str = Field(default_factory=utc_now_iso)


class IdeaBatchNotFound(KeyError):
    pass


class IdeaStore(Protocol):
    backend_name: str

    def save(self, item: IdeaBatch) -> IdeaBatch: ...

    def get(self, batch_id: str) -> IdeaBatch: ...

    def list_recent(self, *, status: IdeaBatchStatus | None = None, limit: int = 100) -> list[IdeaBatch]: ...

    def list_for_session(self, session_id: str, limit: int = 40) -> list[IdeaBatch]: ...

    def shortlist(self, batch_id: str, candidate_id: str) -> IdeaBatch: ...

    def mark_rendered(self, *, session_id: str, candidate_id: str) -> IdeaBatch | None: ...

    def archive(self, batch_id: str) -> IdeaBatch: ...


def _batch_id(*, session_id: str, futures_snapshot: dict[str, Any]) -> str:
    canonical = json.dumps(futures_snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(f"{session_id}|{canonical}".encode("utf-8")).hexdigest()


def _candidate_ids(item: IdeaBatch) -> set[str]:
    rows = item.futures_snapshot.get("selected_futures", [])
    result: set[str] = set()
    for row in rows:
        candidate = row.get("candidate", {}) if isinstance(row, dict) else {}
        candidate_id = candidate.get("candidate_id") if isinstance(candidate, dict) else None
        if isinstance(candidate_id, str):
            result.add(candidate_id)
    return result


class SqliteIdeaStore:
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
                CREATE TABLE IF NOT EXISTS idea_batches (
                    batch_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at_iso TEXT NOT NULL,
                    updated_at_iso TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_idea_status ON idea_batches(status, created_at_iso DESC)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_idea_session ON idea_batches(session_id, created_at_iso DESC)"
            )

    def save(self, item: IdeaBatch) -> IdeaBatch:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO idea_batches(
                    batch_id, session_id, project_id, status, payload_json,
                    created_at_iso, updated_at_iso
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(batch_id) DO UPDATE SET
                    status=excluded.status,
                    payload_json=excluded.payload_json,
                    updated_at_iso=excluded.updated_at_iso
                """,
                (
                    item.batch_id,
                    item.session_id,
                    item.project_id,
                    item.status,
                    item.model_dump_json(),
                    item.created_at_iso,
                    item.updated_at_iso,
                ),
            )
        return item

    def get(self, batch_id: str) -> IdeaBatch:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload_json FROM idea_batches WHERE batch_id = ?",
                (batch_id,),
            ).fetchone()
        if row is None:
            raise IdeaBatchNotFound(batch_id)
        return IdeaBatch.model_validate_json(row[0])

    def list_recent(self, *, status: IdeaBatchStatus | None = None, limit: int = 100) -> list[IdeaBatch]:
        with self._connect() as conn:
            if status:
                rows = conn.execute(
                    """
                    SELECT payload_json FROM idea_batches
                    WHERE status = ?
                    ORDER BY created_at_iso DESC
                    LIMIT ?
                    """,
                    (status, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT payload_json FROM idea_batches
                    ORDER BY created_at_iso DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
        return [IdeaBatch.model_validate_json(row[0]) for row in rows]

    def list_for_session(self, session_id: str, limit: int = 40) -> list[IdeaBatch]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT payload_json FROM idea_batches
                WHERE session_id = ?
                ORDER BY created_at_iso DESC
                LIMIT ?
                """,
                (session_id, limit),
            ).fetchall()
        return [IdeaBatch.model_validate_json(row[0]) for row in rows]

    def shortlist(self, batch_id: str, candidate_id: str) -> IdeaBatch:
        item = self.get(batch_id)
        if candidate_id not in _candidate_ids(item):
            raise IdeaBatchNotFound(f"{batch_id}:{candidate_id}")
        ids = list(item.shortlisted_candidate_ids)
        if candidate_id not in ids:
            ids.append(candidate_id)
        return self.save(item.model_copy(update={"shortlisted_candidate_ids": ids, "updated_at_iso": utc_now_iso()}))

    def mark_rendered(self, *, session_id: str, candidate_id: str) -> IdeaBatch | None:
        for item in self.list_for_session(session_id):
            if candidate_id not in _candidate_ids(item):
                continue
            rendered = list(item.rendered_candidate_ids)
            if candidate_id not in rendered:
                rendered.append(candidate_id)
            return self.save(
                item.model_copy(
                    update={
                        "status": "rendered",
                        "rendered_candidate_ids": rendered,
                        "updated_at_iso": utc_now_iso(),
                    }
                )
            )
        return None

    def archive(self, batch_id: str) -> IdeaBatch:
        item = self.get(batch_id)
        return self.save(item.model_copy(update={"status": "archived", "updated_at_iso": utc_now_iso()}))


class PostgresIdeaStore:
    backend_name = "postgres"

    def __init__(self, database_url: str | None = None) -> None:
        self.database_url = database_url or os.getenv("DATABASE_URL") or os.getenv("RUINFORM_DATABASE_URL")
        if not self.database_url:
            raise RuntimeError("DATABASE_URL is required for PostgresIdeaStore")
        self._initialized = False

    def _connect(self):
        try:
            import psycopg
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("psycopg is required for PostgresIdeaStore") from exc
        return psycopg.connect(self.database_url)

    def _ensure_initialized(self) -> None:
        if self._initialized:
            return
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS idea_batches (
                        batch_id TEXT PRIMARY KEY,
                        session_id TEXT NOT NULL,
                        project_id TEXT NOT NULL,
                        status TEXT NOT NULL,
                        payload_json TEXT NOT NULL,
                        created_at_iso TEXT NOT NULL,
                        updated_at_iso TEXT NOT NULL
                    )
                    """
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_idea_status ON idea_batches(status, created_at_iso DESC)"
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_idea_session ON idea_batches(session_id, created_at_iso DESC)"
                )
            conn.commit()
        self._initialized = True

    def save(self, item: IdeaBatch) -> IdeaBatch:
        self._ensure_initialized()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO idea_batches(
                        batch_id, session_id, project_id, status, payload_json,
                        created_at_iso, updated_at_iso
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT(batch_id) DO UPDATE SET
                        status=EXCLUDED.status,
                        payload_json=EXCLUDED.payload_json,
                        updated_at_iso=EXCLUDED.updated_at_iso
                    """,
                    (
                        item.batch_id,
                        item.session_id,
                        item.project_id,
                        item.status,
                        item.model_dump_json(),
                        item.created_at_iso,
                        item.updated_at_iso,
                    ),
                )
            conn.commit()
        return item

    def get(self, batch_id: str) -> IdeaBatch:
        self._ensure_initialized()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT payload_json FROM idea_batches WHERE batch_id = %s", (batch_id,))
                row = cur.fetchone()
        if row is None:
            raise IdeaBatchNotFound(batch_id)
        return IdeaBatch.model_validate_json(row[0])

    def list_recent(self, *, status: IdeaBatchStatus | None = None, limit: int = 100) -> list[IdeaBatch]:
        self._ensure_initialized()
        with self._connect() as conn:
            with conn.cursor() as cur:
                if status:
                    cur.execute(
                        """
                        SELECT payload_json FROM idea_batches
                        WHERE status = %s
                        ORDER BY created_at_iso DESC
                        LIMIT %s
                        """,
                        (status, limit),
                    )
                else:
                    cur.execute(
                        """
                        SELECT payload_json FROM idea_batches
                        ORDER BY created_at_iso DESC
                        LIMIT %s
                        """,
                        (limit,),
                    )
                rows = cur.fetchall()
        return [IdeaBatch.model_validate_json(row[0]) for row in rows]

    def list_for_session(self, session_id: str, limit: int = 40) -> list[IdeaBatch]:
        self._ensure_initialized()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT payload_json FROM idea_batches
                    WHERE session_id = %s
                    ORDER BY created_at_iso DESC
                    LIMIT %s
                    """,
                    (session_id, limit),
                )
                rows = cur.fetchall()
        return [IdeaBatch.model_validate_json(row[0]) for row in rows]

    def shortlist(self, batch_id: str, candidate_id: str) -> IdeaBatch:
        item = self.get(batch_id)
        if candidate_id not in _candidate_ids(item):
            raise IdeaBatchNotFound(f"{batch_id}:{candidate_id}")
        ids = list(item.shortlisted_candidate_ids)
        if candidate_id not in ids:
            ids.append(candidate_id)
        return self.save(item.model_copy(update={"shortlisted_candidate_ids": ids, "updated_at_iso": utc_now_iso()}))

    def mark_rendered(self, *, session_id: str, candidate_id: str) -> IdeaBatch | None:
        for item in self.list_for_session(session_id):
            if candidate_id not in _candidate_ids(item):
                continue
            rendered = list(item.rendered_candidate_ids)
            if candidate_id not in rendered:
                rendered.append(candidate_id)
            return self.save(
                item.model_copy(
                    update={
                        "status": "rendered",
                        "rendered_candidate_ids": rendered,
                        "updated_at_iso": utc_now_iso(),
                    }
                )
            )
        return None

    def archive(self, batch_id: str) -> IdeaBatch:
        item = self.get(batch_id)
        return self.save(item.model_copy(update={"status": "archived", "updated_at_iso": utc_now_iso()}))


def create_idea_store() -> IdeaStore:
    if os.getenv("DATABASE_URL") or os.getenv("RUINFORM_DATABASE_URL"):
        return PostgresIdeaStore()
    return SqliteIdeaStore()


def capture_session_ideas(session) -> IdeaBatch | None:
    if session.futures is None or not session.futures.selected_futures:
        return None
    snapshot = session.futures.model_dump(mode="json")
    intent = session.project_state.creative_intent
    item = IdeaBatch(
        batch_id=_batch_id(session_id=session.session_id, futures_snapshot=snapshot),
        session_id=session.session_id,
        project_id=session.project_id,
        background_mode=intent.background_mode,
        difficulty_mode=intent.difficulty_mode,
        creative_direction=intent.direction,
        source_items=[material.display_name for material in session.project_state.materials],
        source_material_ids=[material.item_id for material in session.project_state.materials],
        futures_snapshot=snapshot,
    )
    return create_idea_store().save(item)


def mark_session_candidate_rendered(session) -> IdeaBatch | None:
    candidate_id = getattr(session, "selected_candidate_id", None)
    if not candidate_id:
        return None
    return create_idea_store().mark_rendered(session_id=session.session_id, candidate_id=candidate_id)
