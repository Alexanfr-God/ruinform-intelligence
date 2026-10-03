from __future__ import annotations

import json

from ruinform_intelligence import passport_provenance_patch as _passport_provenance_patch  # noqa: F401
from ruinform_intelligence.object_passport import ObjectPassport


def test_object_passport_round_trip_preserves_new_provenance_fields() -> None:
    raw = {
        "version": "object-passport-v0.1",
        "object_id": "RF-9999",
        "source_session_id": "session-1",
        "project_id": "project-1",
        "candidate_id": "future-1",
        "title": "Test Object",
        "one_line": "A test object.",
        "transformation_logic": "Keep the provenance intact.",
        "artist_meaning": "Persistence matters.",
        "materials": [],
        "source_image_count": 2,
        "render_image_url": None,
        "build_status": "IDEA",
        "verification_status": "UNVERIFIED",
        "owner_wallet": None,
        "created_at_iso": "2026-10-03T00:00:00Z",
        "verification_proof_status": "valid",
        "verification_score": 14,
        "verification_verdict": "weak_match",
        "verification_confidence": 91,
        "future_unknown_provenance_field": {"keep": True},
    }

    passport = ObjectPassport.model_validate(raw)
    dumped = json.loads(passport.model_dump_json())

    assert dumped["verification_proof_status"] == "valid"
    assert dumped["verification_score"] == 14
    assert dumped["verification_verdict"] == "weak_match"
    assert dumped["verification_confidence"] == 91
    assert dumped["future_unknown_provenance_field"] == {"keep": True}
