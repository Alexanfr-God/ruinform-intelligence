import sqlite3

import pytest

from ruinform_intelligence.verification_challenge import (
    SqliteVerificationChallengeStore,
    VerificationChallengeError,
)


def test_challenge_is_bound_and_one_time(tmp_path):
    store = SqliteVerificationChallengeStore(str(tmp_path / "challenge.db"))
    challenge = store.issue(source_session_id="session-1", candidate_id="preview_03")

    assert len(challenge.code) == 4
    assert challenge.consumed_at_iso is None

    consumed = store.consume(
        challenge_id=challenge.challenge_id,
        source_session_id="session-1",
        candidate_id="preview_03",
    )
    assert consumed.code == challenge.code
    assert consumed.consumed_at_iso

    with pytest.raises(VerificationChallengeError, match="already used"):
        store.consume(
            challenge_id=challenge.challenge_id,
            source_session_id="session-1",
            candidate_id="preview_03",
        )


def test_challenge_cannot_cross_object_session(tmp_path):
    store = SqliteVerificationChallengeStore(str(tmp_path / "challenge.db"))
    challenge = store.issue(source_session_id="session-1", candidate_id="preview_03")

    with pytest.raises(VerificationChallengeError, match="does not belong"):
        store.consume(
            challenge_id=challenge.challenge_id,
            source_session_id="session-2",
            candidate_id="preview_03",
        )

    with sqlite3.connect(tmp_path / "challenge.db") as conn:
        consumed = conn.execute(
            "SELECT consumed_at_iso FROM ruinform_verification_challenges WHERE challenge_id = ?",
            (challenge.challenge_id,),
        ).fetchone()[0]
    assert consumed is None
