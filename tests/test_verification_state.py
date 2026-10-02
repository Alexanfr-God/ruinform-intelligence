from ruinform_intelligence.verification import VerificationOutput
from ruinform_intelligence.verification_state import verification_state_for


def _result(*, verdict: str, overall: int, confidence: int, next_capture_request=None):
    return VerificationOutput(
        overall_match=overall,
        silhouette_match=overall,
        material_match=overall,
        construction_match=overall,
        detail_match=overall,
        confidence=confidence,
        verdict=verdict,
        summary="test",
        matching_features=[],
        deviations=[],
        next_capture_request=next_capture_request,
    )


def test_strong_confident_match_verifies_passport():
    assert verification_state_for(_result(verdict="strong_match", overall=91, confidence=88)) == (
        "VERIFIED",
        "VERIFIED",
    )


def test_strong_match_with_missing_view_needs_review():
    assert verification_state_for(
        _result(
            verdict="strong_match",
            overall=90,
            confidence=85,
            next_capture_request="Show the rear joint",
        )
    ) == ("PHYSICAL", "NEEDS_REVIEW")


def test_partial_match_needs_review():
    assert verification_state_for(_result(verdict="partial_match", overall=72, confidence=74)) == (
        "PHYSICAL",
        "NEEDS_REVIEW",
    )


def test_weak_or_low_confidence_evidence_does_not_upgrade():
    assert verification_state_for(_result(verdict="weak_match", overall=35, confidence=60)) == (
        "IDEA",
        "UNVERIFIED",
    )
    assert verification_state_for(_result(verdict="partial_match", overall=70, confidence=30)) == (
        "IDEA",
        "UNVERIFIED",
    )
