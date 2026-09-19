from __future__ import annotations

import os
import sqlite3
from pathlib import Path


def prepare_review_store_schema() -> None:
    """Repair the Wave 3 review index before the normal store initializes.

    GPT Image renders may be stored as data URLs. Indexing render_url directly can
    exceed PostgreSQL's btree row limit, so the matching index must cover only the
    small session/candidate keys. The review store may still compare render_url in
    the WHERE clause after that narrow lookup.
    """

    database_url = os.getenv("DATABASE_URL") or os.getenv("RUINFORM_DATABASE_URL")
    if database_url:
        _prepare_postgres(database_url)
        return
    _prepare_sqlite(os.getenv("RUINFORM_DB_PATH", ".ruinform/ruinform.db"))


def _prepare_sqlite(path: str) -> None:
    db_path = Path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
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
        conn.execute("DROP INDEX IF EXISTS idx_review_match")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_review_match ON review_queue_items(session_id, candidate_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_review_status ON review_queue_items(status, created_at_iso DESC)"
        )


def _prepare_postgres(database_url: str) -> None:
    try:
        import psycopg
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("psycopg is required to prepare the review store") from exc

    with psycopg.connect(database_url) as conn:
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
            cur.execute("DROP INDEX IF EXISTS idx_review_match")
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_review_match ON review_queue_items(session_id, candidate_id)"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_review_status ON review_queue_items(status, created_at_iso DESC)"
            )
        conn.commit()
