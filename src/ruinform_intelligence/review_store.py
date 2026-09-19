from __future__ import annotations

import hashlib
import os
import sqlite3
from pathlib import Path
from typing import Literal, Protocol

from .review_models import ReviewItem, utc_now_iso


ReviewStatus = Literal["pending", "evaluated"]


class ReviewItemNotFound(KeyError):
    pass


class ReviewStore(Protocol):
    backend_name: str

    def save(self, item: ReviewItem) -> ReviewItem: ...

    def get(self, review_id: str) -> ReviewItem: ...

    def list_recent(self, *, status: ReviewStatus | None = None, limit: int = 100) -> list[ReviewItem]: ...

    def mark_evaluated(self, review_id: str, eval_id: str) -> ReviewItem: ...

    def mark_matching_evaluated(self, *, session_id: str, candidate_id: str, render_url: str, eval_id: str) -> ReviewItem | None: ...


def _review_id(*, session_id: str, candidate_id: str, render_url: str) -> str:
    raw = f"{session_id}|{candidate_id}|{render_url}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


class SqliteReviewStore:
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
                CREATE TABLE IF NOT EXISTS review_queue_items (
                    review_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    candidate_id TEXT NOT NULL,
                    render_url TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at_iso TEXT NOT NULL,
                    evaluated_at_iso TEXT
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_review_status ON review_queue_items(status, created_at_iso DESC)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_review_match ON review_queue_items(session_id, candidate_id, render_url)"
            )

    def save(self, item: ReviewItem) -> ReviewItem:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO review_queue_items(
                    review_id, session_id, project_id, candidate_id, render_url,
                    status, payload_json, created_at_iso, evaluated_at_iso
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(review_id) DO UPDATE SET
                    status=excluded.status,
                    payload_json=excluded.payload_json,
                    evaluated_at_iso=excluded.evaluated_at_iso
                """,
                (
                    item.review_id,
                    item.session_id,
                    item.project_id,
                    item.candidate_id,
                    item.render_url,
                    item.status,
                    item.model_dump_json(),
                    item.created_at_iso,
                    item.evaluated_at_iso,
                ),
            )
        return item

    def get(self, review_id: str) -> ReviewItem:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload_json FROM review_queue_items WHERE review_id = ?",
                (review_id,),
            ).fetchone()
        if row is None:
            raise ReviewItemNotFound(review_id)
        return ReviewItem.model_validate_json(row[0])

    def list_recent(self, *, status: ReviewStatus | None = None, limit: int = 100) -> list[ReviewItem]:
        with self._connect() as conn:
            if status:
                rows = conn.execute(
                    """
                    SELECT payload_json FROM review_queue_items
                    WHERE status = ?
                    ORDER BY created_at_iso DESC
                    LIMIT ?
                    """,
                    (status, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT payload_json FROM review_queue_items
                    ORDER BY created_at_iso DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
        return [ReviewItem.model_validate_json(row[0]) for row in rows]

    def mark_evaluated(self, review_id: str, eval_id: str) -> ReviewItem:
        current = self.get(review_id)
        updated = current.model_copy(
            update={"status": "evaluated", "eval_id": eval_id, "evaluated_at_iso": utc_now_iso()}
        )
        return self.save(updated)

    def mark_matching_evaluated(self, *, session_id: str, candidate_id: str, render_url: str, eval_id: str) -> ReviewItem | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT payload_json FROM review_queue_items
                WHERE session_id = ? AND candidate_id = ? AND render_url = ? AND status = 'pending'
                ORDER BY created_at_iso DESC
                LIMIT 1
                """,
                (session_id, candidate_id, render_url),
            ).fetchone()
        if row is None:
            return None
        current = ReviewItem.model_validate_json(row[0])
        return self.mark_evaluated(current.review_id, eval_id)


class PostgresReviewStore:
    backend_name = "postgres"

    def __init__(self, database_url: str | None = None) -> None:
        self.database_url = database_url or os.getenv("DATABASE_URL") or os.getenv("RUINFORM_DATABASE_URL")
        if not self.database_url:
            raise RuntimeError("DATABASE_URL is required for PostgresReviewStore")
        self._initialized = False

    def _connect(self):
        try:
            import psycopg
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("psycopg is required for PostgresReviewStore") from exc
        return psycopg.connect(self.database_url)

    def _ensure_initialized(self) -> None:
        if self._initialized:
            return
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS review_queue_items (
                        review_id TEXT PRIMARY KEY,
                        session_id TEXT NOT NULL,
                        project_id TEXT NOT NULL,
                        candidate_id TEXT NOT NULL,
                        render_url TEXT NOT NULL,
                        status TEXT NOT NULL,
                        payload_json TEXT NOT NULL,
                        created_at_iso TEXT NOT NULL,
                        evaluated_at_iso TEXT
                    )
                    """
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_review_status ON review_queue_items(status, created_at_iso DESC)"
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_review_match ON review_queue_items(session_id, candidate_id, render_url)"
                )
            conn.commit()
        self._initialized = True

    def save(self, item: ReviewItem) -> ReviewItem:
        self._ensure_initialized()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO review_queue_items(
                        review_id, session_id, project_id, candidate_id, render_url,
                        status, payload_json, created_at_iso, evaluated_at_iso
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT(review_id) DO UPDATE SET
                        status=EXCLUDED.status,
                        payload_json=EXCLUDED.payload_json,
                        evaluated_at_iso=EXCLUDED.evaluated_at_iso
                    """,
                    (
                        item.review_id,
                        item.session_id,
                        item.project_id,
                        item.candidate_id,
                        item.render_url,
                        item.status,
                        item.model_dump_json(),
                        item.created_at_iso,
                        item.evaluated_at_iso,
                    ),
                )
            conn.commit()
        return item

    def get(self, review_id: str) -> ReviewItem:
        self._ensure_initialized()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT payload_json FROM review_queue_items WHERE review_id = %s", (review_id,))
                row = cur.fetchone()
        if row is None:
            raise ReviewItemNotFound(review_id)
        return ReviewItem.model_validate_json(row[0])

    def list_recent(self, *, status: ReviewStatus | None = None, limit: int = 100) -> list[ReviewItem]:
        self._ensure_initialized()
        with self._connect() as conn:
            with conn.cursor() as cur:
                if status:
                    cur.execute(
                        """
                        SELECT payload_json FROM review_queue_items
                        WHERE status = %s
                        ORDER BY created_at_iso DESC
                        LIMIT %s
                        """,
                        (status, limit),
                    )
                else:
                    cur.execute(
                        """
                        SELECT payload_json FROM review_queue_items
                        ORDER BY created_at_iso DESC
                        LIMIT %s
                        """,
                        (limit,),
                    )
                rows = cur.fetchall()
        return [ReviewItem.model_validate_json(row[0]) for row in rows]

    def mark_evaluated(self, review_id: str, eval_id: str) -> ReviewItem:
        current = self.get(review_id)
        updated = current.model_copy(
            update={"status": "evaluated", "eval_id": eval_id, "evaluated_at_iso": utc_now_iso()}
        )
        return self.save(updated)

    def mark_matching_evaluated(self, *, session_id: str, candidate_id: str, render_url: str, eval_id: str) -> ReviewItem | None:
        self._ensure_initialized()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT payload_json FROM review_queue_items
                    WHERE session_id = %s AND candidate_id = %s AND render_url = %s AND status = 'pending'
                    ORDER BY created_at_iso DESC
                    LIMIT 1
                    """,
                    (session_id, candidate_id, render_url),
                )
                row = cur.fetchone()
        if row is None:
            return None
        current = ReviewItem.model_validate_json(row[0])
        return self.mark_evaluated(current.review_id, eval_id)


def create_review_store() -> ReviewStore:
    if os.getenv("DATABASE_URL") or os.getenv("RUINFORM_DATABASE_URL"):
        return PostgresReviewStore()
    return SqliteReviewStore()


def capture_session_render(session) -> ReviewItem | None:
    """Freeze the session's current approved render into the pending review inbox.

    The deterministic ID makes capture idempotent, which matters because the capture
    hook runs after HTTP responses and may see the same approved session more than once.
    """

    result = session.render_result
    if result is None or result.status != "pass" or result.accepted_image_url is None:
        return None
    if not session.selected_candidate_id or result.candidate_id != session.selected_candidate_id:
        return None
    if session.futures is None:
        return None
    future = next(
        (
            item
            for item in session.futures.selected_futures
            if item.candidate.candidate_id == session.selected_candidate_id
        ),
        None,
    )
    if future is None:
        return None

    render_url = str(result.accepted_image_url)
    intent = session.project_state.creative_intent
    item = ReviewItem(
        review_id=_review_id(
            session_id=session.session_id,
            candidate_id=future.candidate.candidate_id,
            render_url=render_url,
        ),
        session_id=session.session_id,
        project_id=session.project_id,
        candidate_id=future.candidate.candidate_id,
        candidate_name=future.candidate.name,
        render_url=render_url,
        background_mode=intent.background_mode,
        difficulty_mode=intent.difficulty_mode,
        creative_direction=intent.direction,
        source_items=[material.display_name for material in session.project_state.materials],
        source_material_ids=[material.item_id for material in session.project_state.materials],
        concept_snapshot=future.candidate.model_dump(mode="json"),
        review_snapshot=future.review.model_dump(mode="json"),
        render_snapshot=result.model_dump(mode="json"),
    )
    return create_review_store().save(item)
