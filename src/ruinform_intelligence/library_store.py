from __future__ import annotations

import hashlib
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class LibraryEntry(BaseModel):
    generation_id: str
    owner_id: str
    review_id: str
    session_id: str
    candidate_id: str
    is_public: bool = False
    parent_generation_id: str | None = None
    created_at_iso: str = ""
    updated_at_iso: str = ""


class LibraryEntryNotFound(KeyError):
    pass


def generation_id_for(*, owner_id: str, review_id: str) -> str:
    return hashlib.sha256(f"{owner_id}|{review_id}".encode("utf-8")).hexdigest()


class LibraryStore(Protocol):
    backend_name: str

    def save(self, item: LibraryEntry) -> LibraryEntry: ...
    def get(self, generation_id: str) -> LibraryEntry: ...
    def list_mine(self, owner_id: str, *, limit: int = 60) -> list[LibraryEntry]: ...
    def list_public(self, *, limit: int = 60) -> list[LibraryEntry]: ...
    def set_public(self, generation_id: str, *, owner_id: str, is_public: bool) -> LibraryEntry: ...


def _normalize_times(item: LibraryEntry) -> LibraryEntry:
    now = utc_now_iso()
    return item.model_copy(
        update={
            "created_at_iso": item.created_at_iso or now,
            "updated_at_iso": now,
        }
    )


class SqliteLibraryStore:
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
                CREATE TABLE IF NOT EXISTS generation_library (
                    generation_id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL,
                    review_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    candidate_id TEXT NOT NULL,
                    is_public INTEGER NOT NULL DEFAULT 0,
                    parent_generation_id TEXT,
                    created_at_iso TEXT NOT NULL,
                    updated_at_iso TEXT NOT NULL,
                    UNIQUE(owner_id, review_id)
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_generation_owner ON generation_library(owner_id, created_at_iso DESC)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_generation_public ON generation_library(is_public, created_at_iso DESC)")

    @staticmethod
    def _row(row) -> LibraryEntry:
        if row is None:
            raise LibraryEntryNotFound()
        return LibraryEntry(
            generation_id=row[0], owner_id=row[1], review_id=row[2], session_id=row[3],
            candidate_id=row[4], is_public=bool(row[5]), parent_generation_id=row[6],
            created_at_iso=row[7], updated_at_iso=row[8],
        )

    def save(self, item: LibraryEntry) -> LibraryEntry:
        saved = _normalize_times(item)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO generation_library(
                    generation_id, owner_id, review_id, session_id, candidate_id,
                    is_public, parent_generation_id, created_at_iso, updated_at_iso
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(generation_id) DO UPDATE SET
                    is_public=excluded.is_public,
                    parent_generation_id=COALESCE(excluded.parent_generation_id, generation_library.parent_generation_id),
                    updated_at_iso=excluded.updated_at_iso
                """,
                (
                    saved.generation_id, saved.owner_id, saved.review_id, saved.session_id,
                    saved.candidate_id, int(saved.is_public), saved.parent_generation_id,
                    saved.created_at_iso, saved.updated_at_iso,
                ),
            )
        return saved

    def get(self, generation_id: str) -> LibraryEntry:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT generation_id,owner_id,review_id,session_id,candidate_id,is_public,parent_generation_id,created_at_iso,updated_at_iso FROM generation_library WHERE generation_id=?",
                (generation_id,),
            ).fetchone()
        if row is None:
            raise LibraryEntryNotFound(generation_id)
        return self._row(row)

    def list_mine(self, owner_id: str, *, limit: int = 60) -> list[LibraryEntry]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT generation_id,owner_id,review_id,session_id,candidate_id,is_public,parent_generation_id,created_at_iso,updated_at_iso FROM generation_library WHERE owner_id=? ORDER BY created_at_iso DESC LIMIT ?",
                (owner_id, limit),
            ).fetchall()
        return [self._row(row) for row in rows]

    def list_public(self, *, limit: int = 60) -> list[LibraryEntry]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT generation_id,owner_id,review_id,session_id,candidate_id,is_public,parent_generation_id,created_at_iso,updated_at_iso FROM generation_library WHERE is_public=1 ORDER BY created_at_iso DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._row(row) for row in rows]

    def set_public(self, generation_id: str, *, owner_id: str, is_public: bool) -> LibraryEntry:
        item = self.get(generation_id)
        if item.owner_id != owner_id:
            raise PermissionError(generation_id)
        return self.save(item.model_copy(update={"is_public": is_public}))


class PostgresLibraryStore:
    backend_name = "postgres"

    def __init__(self, database_url: str | None = None) -> None:
        self.database_url = database_url or os.getenv("DATABASE_URL") or os.getenv("RUINFORM_DATABASE_URL")
        if not self.database_url:
            raise RuntimeError("DATABASE_URL is required for PostgresLibraryStore")
        self._initialized = False

    def _connect(self):
        import psycopg
        return psycopg.connect(self.database_url)

    def _ensure_initialized(self) -> None:
        if self._initialized:
            return
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS generation_library (
                        generation_id TEXT PRIMARY KEY,
                        owner_id TEXT NOT NULL,
                        review_id TEXT NOT NULL,
                        session_id TEXT NOT NULL,
                        candidate_id TEXT NOT NULL,
                        is_public BOOLEAN NOT NULL DEFAULT FALSE,
                        parent_generation_id TEXT,
                        created_at_iso TEXT NOT NULL,
                        updated_at_iso TEXT NOT NULL,
                        UNIQUE(owner_id, review_id)
                    )
                    """
                )
                cur.execute("CREATE INDEX IF NOT EXISTS idx_generation_owner ON generation_library(owner_id, created_at_iso DESC)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_generation_public ON generation_library(is_public, created_at_iso DESC)")
            conn.commit()
        self._initialized = True

    @staticmethod
    def _row(row) -> LibraryEntry:
        return LibraryEntry(
            generation_id=row[0], owner_id=row[1], review_id=row[2], session_id=row[3],
            candidate_id=row[4], is_public=bool(row[5]), parent_generation_id=row[6],
            created_at_iso=row[7], updated_at_iso=row[8],
        )

    def save(self, item: LibraryEntry) -> LibraryEntry:
        self._ensure_initialized()
        saved = _normalize_times(item)
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO generation_library(
                        generation_id, owner_id, review_id, session_id, candidate_id,
                        is_public, parent_generation_id, created_at_iso, updated_at_iso
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT(generation_id) DO UPDATE SET
                        is_public=EXCLUDED.is_public,
                        parent_generation_id=COALESCE(EXCLUDED.parent_generation_id, generation_library.parent_generation_id),
                        updated_at_iso=EXCLUDED.updated_at_iso
                    """,
                    (
                        saved.generation_id, saved.owner_id, saved.review_id, saved.session_id,
                        saved.candidate_id, saved.is_public, saved.parent_generation_id,
                        saved.created_at_iso, saved.updated_at_iso,
                    ),
                )
            conn.commit()
        return saved

    def get(self, generation_id: str) -> LibraryEntry:
        self._ensure_initialized()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT generation_id,owner_id,review_id,session_id,candidate_id,is_public,parent_generation_id,created_at_iso,updated_at_iso FROM generation_library WHERE generation_id=%s",
                    (generation_id,),
                )
                row = cur.fetchone()
        if row is None:
            raise LibraryEntryNotFound(generation_id)
        return self._row(row)

    def list_mine(self, owner_id: str, *, limit: int = 60) -> list[LibraryEntry]:
        self._ensure_initialized()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT generation_id,owner_id,review_id,session_id,candidate_id,is_public,parent_generation_id,created_at_iso,updated_at_iso FROM generation_library WHERE owner_id=%s ORDER BY created_at_iso DESC LIMIT %s",
                    (owner_id, limit),
                )
                rows = cur.fetchall()
        return [self._row(row) for row in rows]

    def list_public(self, *, limit: int = 60) -> list[LibraryEntry]:
        self._ensure_initialized()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT generation_id,owner_id,review_id,session_id,candidate_id,is_public,parent_generation_id,created_at_iso,updated_at_iso FROM generation_library WHERE is_public=TRUE ORDER BY created_at_iso DESC LIMIT %s",
                    (limit,),
                )
                rows = cur.fetchall()
        return [self._row(row) for row in rows]

    def set_public(self, generation_id: str, *, owner_id: str, is_public: bool) -> LibraryEntry:
        item = self.get(generation_id)
        if item.owner_id != owner_id:
            raise PermissionError(generation_id)
        return self.save(item.model_copy(update={"is_public": is_public}))


def create_library_store() -> LibraryStore:
    if os.getenv("DATABASE_URL") or os.getenv("RUINFORM_DATABASE_URL"):
        return PostgresLibraryStore()
    return SqliteLibraryStore()
