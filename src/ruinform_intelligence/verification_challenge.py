from __future__ import annotations

import os
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel


_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_DEFAULT_TTL_SECONDS = 10 * 60


class VerificationChallenge(BaseModel):
    challenge_id: str
    source_session_id: str
    candidate_id: str
    code: str
    created_at_iso: str
    expires_at_iso: str
    consumed_at_iso: str | None = None


class VerificationChallengeError(RuntimeError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.isoformat()


def _parse(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _ttl_seconds() -> int:
    raw = os.getenv("RUINFORM_VERIFICATION_CHALLENGE_TTL_SECONDS", "").strip()
    if not raw:
        return _DEFAULT_TTL_SECONDS
    try:
        return max(60, min(3600, int(raw)))
    except ValueError:
        return _DEFAULT_TTL_SECONDS


def _new_challenge(*, source_session_id: str, candidate_id: str) -> VerificationChallenge:
    created = _now()
    return VerificationChallenge(
        challenge_id=str(uuid4()),
        source_session_id=source_session_id,
        candidate_id=candidate_id,
        code="".join(secrets.choice(_ALPHABET) for _ in range(4)),
        created_at_iso=_iso(created),
        expires_at_iso=_iso(created + timedelta(seconds=_ttl_seconds())),
    )


class SqliteVerificationChallengeStore:
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
                CREATE TABLE IF NOT EXISTS ruinform_verification_challenges (
                    challenge_id TEXT PRIMARY KEY,
                    source_session_id TEXT NOT NULL,
                    candidate_id TEXT NOT NULL,
                    code TEXT NOT NULL,
                    created_at_iso TEXT NOT NULL,
                    expires_at_iso TEXT NOT NULL,
                    consumed_at_iso TEXT
                )
                """
            )

    def issue(self, *, source_session_id: str, candidate_id: str) -> VerificationChallenge:
        challenge = _new_challenge(
            source_session_id=source_session_id,
            candidate_id=candidate_id,
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO ruinform_verification_challenges(
                    challenge_id, source_session_id, candidate_id, code,
                    created_at_iso, expires_at_iso, consumed_at_iso
                ) VALUES (?, ?, ?, ?, ?, ?, NULL)
                """,
                (
                    challenge.challenge_id,
                    challenge.source_session_id,
                    challenge.candidate_id,
                    challenge.code,
                    challenge.created_at_iso,
                    challenge.expires_at_iso,
                ),
            )
        return challenge

    def consume(
        self,
        *,
        challenge_id: str,
        source_session_id: str,
        candidate_id: str,
    ) -> VerificationChallenge:
        now = _now()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT challenge_id, source_session_id, candidate_id, code,
                       created_at_iso, expires_at_iso, consumed_at_iso
                FROM ruinform_verification_challenges
                WHERE challenge_id = ?
                """,
                (challenge_id,),
            ).fetchone()
            if row is None:
                raise VerificationChallengeError("Verification challenge was not found. Start a new live camera challenge.")
            challenge = VerificationChallenge(
                challenge_id=row[0],
                source_session_id=row[1],
                candidate_id=row[2],
                code=row[3],
                created_at_iso=row[4],
                expires_at_iso=row[5],
                consumed_at_iso=row[6],
            )
            if challenge.source_session_id != source_session_id or challenge.candidate_id != candidate_id:
                raise VerificationChallengeError("Verification challenge does not belong to this object session.")
            if challenge.consumed_at_iso:
                raise VerificationChallengeError("Verification challenge was already used. Start a new live camera challenge.")
            if _parse(challenge.expires_at_iso) <= now:
                raise VerificationChallengeError("Verification challenge expired. Start a new live camera challenge.")
            consumed_at = _iso(now)
            conn.execute(
                "UPDATE ruinform_verification_challenges SET consumed_at_iso = ? WHERE challenge_id = ? AND consumed_at_iso IS NULL",
                (consumed_at, challenge_id),
            )
        return challenge.model_copy(update={"consumed_at_iso": consumed_at})


class PostgresVerificationChallengeStore:
    def __init__(self, database_url: str | None = None) -> None:
        self.database_url = database_url or os.getenv("DATABASE_URL") or os.getenv("RUINFORM_DATABASE_URL")
        if not self.database_url:
            raise RuntimeError("DATABASE_URL is required for PostgresVerificationChallengeStore")
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
                    CREATE TABLE IF NOT EXISTS ruinform_verification_challenges (
                        challenge_id TEXT PRIMARY KEY,
                        source_session_id TEXT NOT NULL,
                        candidate_id TEXT NOT NULL,
                        code TEXT NOT NULL,
                        created_at_iso TEXT NOT NULL,
                        expires_at_iso TEXT NOT NULL,
                        consumed_at_iso TEXT
                    )
                    """
                )
            conn.commit()
        self._initialized = True

    def issue(self, *, source_session_id: str, candidate_id: str) -> VerificationChallenge:
        self._ensure_initialized()
        challenge = _new_challenge(
            source_session_id=source_session_id,
            candidate_id=candidate_id,
        )
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO ruinform_verification_challenges(
                        challenge_id, source_session_id, candidate_id, code,
                        created_at_iso, expires_at_iso, consumed_at_iso
                    ) VALUES (%s, %s, %s, %s, %s, %s, NULL)
                    """,
                    (
                        challenge.challenge_id,
                        challenge.source_session_id,
                        challenge.candidate_id,
                        challenge.code,
                        challenge.created_at_iso,
                        challenge.expires_at_iso,
                    ),
                )
            conn.commit()
        return challenge

    def consume(
        self,
        *,
        challenge_id: str,
        source_session_id: str,
        candidate_id: str,
    ) -> VerificationChallenge:
        self._ensure_initialized()
        now = _now()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT challenge_id, source_session_id, candidate_id, code,
                           created_at_iso, expires_at_iso, consumed_at_iso
                    FROM ruinform_verification_challenges
                    WHERE challenge_id = %s
                    FOR UPDATE
                    """,
                    (challenge_id,),
                )
                row = cur.fetchone()
                if row is None:
                    raise VerificationChallengeError("Verification challenge was not found. Start a new live camera challenge.")
                challenge = VerificationChallenge(
                    challenge_id=row[0],
                    source_session_id=row[1],
                    candidate_id=row[2],
                    code=row[3],
                    created_at_iso=row[4],
                    expires_at_iso=row[5],
                    consumed_at_iso=row[6],
                )
                if challenge.source_session_id != source_session_id or challenge.candidate_id != candidate_id:
                    raise VerificationChallengeError("Verification challenge does not belong to this object session.")
                if challenge.consumed_at_iso:
                    raise VerificationChallengeError("Verification challenge was already used. Start a new live camera challenge.")
                if _parse(challenge.expires_at_iso) <= now:
                    raise VerificationChallengeError("Verification challenge expired. Start a new live camera challenge.")
                consumed_at = _iso(now)
                cur.execute(
                    "UPDATE ruinform_verification_challenges SET consumed_at_iso = %s WHERE challenge_id = %s AND consumed_at_iso IS NULL",
                    (consumed_at, challenge_id),
                )
            conn.commit()
        return challenge.model_copy(update={"consumed_at_iso": consumed_at})


def challenge_store() -> SqliteVerificationChallengeStore | PostgresVerificationChallengeStore:
    if os.getenv("DATABASE_URL") or os.getenv("RUINFORM_DATABASE_URL"):
        return PostgresVerificationChallengeStore()
    return SqliteVerificationChallengeStore()
