from ruinform_intelligence.verification import VerificationOutput
from ruinform_intelligence.verification_state import verification_state_for


def test_invalid_live_proof_has_no_object_scores() -> None:
    result = VerificationOutput(
        proof_status="invalid",
        object_match_evaluated=False,
        overall_match=None,
        silhouette_match=None,
        material_match=None,
        construction_match=None,
        detail_match=None,
        confidence=None,
        challenge_code_visible_in_all=False,
        challenge_code_match_confidence=10,
        challenge_observations=["Expected code missing from both required views."],
        verdict="invalid_proof",
        summary="Fresh live proof failed; object similarity was not evaluated.",
        matching_features=[],
        deviations=[],
        next_capture_request="Retake two live-camera views with the current code physically visible.",
    )

    assert verification_state_for(result) == ("IDEA", "UNVERIFIED")
    assert result.overall_match is None
    assert result.object_match_evaluated is False


def test_valid_strong_match_can_verify_existing_passport() -> None:
    result = VerificationOutput(
        proof_status="valid",
        object_match_evaluated=True,
        overall_match=91,
        silhouette_match=93,
        material_match=88,
        construction_match=92,
        detail_match=89,
        confidence=90,
        challenge_code_visible_in_all=True,
        challenge_code_match_confidence=96,
        challenge_observations=[
            "Exact code is legible on a physical note in view one.",
            "Exact code is legible on the same physical note in view two.",
        ],
        verdict="strong_match",
        summary="Valid fresh proof and strong preservation of the selected Future.",
        matching_features=["Major silhouette", "Distinctive transformed element"],
        deviations=["Minor hand-built finish variation"],
        next_capture_request=None,
    )

    assert verification_state_for(result) == ("VERIFIED", "VERIFIED")
