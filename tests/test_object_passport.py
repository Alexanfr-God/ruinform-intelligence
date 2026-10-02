from ruinform_intelligence.future_models import (
    CandidateForm,
    FeasibilityReview,
    FutureFormsResult,
    MaterialOmission,
    MaterialUse,
    ReviewedFuture,
)
from ruinform_intelligence.models import EvidenceItem, MaterialItem, ProjectState
from ruinform_intelligence.object_passport import SqliteObjectPassportStore, _passport_page
from ruinform_intelligence.run_store import TransformationSession


def _session() -> TransformationSession:
    bottle = MaterialItem(item_id="matter_bottle", display_name="Aqua bottle")
    pen = MaterialItem(item_id="matter_pen", display_name="Blue retractable pen")
    candidate = CandidateForm(
        candidate_id="preview_03",
        name="Orbit Scribe",
        one_line="The bottle becomes the stationary center of a radial drawing arm.",
        category="utility",
        artistic_thesis="A discarded vessel becomes the fixed memory of repeated motion.",
        transformation_logic="The pen pivots around the bottle and draws a circular trace.",
        material_uses=[
            MaterialUse(
                material_item_id="matter_bottle",
                role="hero",
                estimated_fraction=1.0,
                note="Stationary center.",
            ),
            MaterialUse(
                material_item_id="matter_pen",
                role="connector",
                estimated_fraction=1.0,
                note="Radial drawing arm.",
            ),
        ],
        omitted_materials=[],
        added_materials=[],
        required_tools=[],
        key_operations=["pivot"],
        unresolved_dependencies=[],
    )
    review = FeasibilityReview(
        candidate_id="preview_03",
        status="pass",
        feasibility_score=80,
        material_fit_score=86,
        buildability_score=69,
        originality_score=84,
        artistic_impact_score=80,
        usefulness_score=80,
        value_potential_score=75,
        reasons=[],
        required_changes=[],
        unresolved_dependencies=[],
    )
    future = ReviewedFuture(candidate=candidate, review=review, rank_score=80)
    state = ProjectState(
        materials=[bottle, pen],
        evidence=[EvidenceItem(evidence_id="image_001", source_type="image", uri="https://example.com/a.jpg")],
    )
    return TransformationSession(
        project_id=state.project_id,
        stage="completed",
        project_state=state,
        futures=FutureFormsResult(
            internal_candidate_count=2,
            reviewed_candidate_count=2,
            selected_futures=[future],
        ),
        selected_candidate_id="preview_03",
    )


def test_object_passport_creation_is_idempotent(tmp_path) -> None:
    session = _session()
    future = session.futures.selected_futures[0]
    store = SqliteObjectPassportStore(str(tmp_path / "passport.db"))

    first = store.create(session=session, future=future)
    second = store.create(session=session, future=future)

    assert first.object_id == "RF-0001"
    assert second.object_id == first.object_id
    assert first.title == "Orbit Scribe"
    assert first.verification_status == "UNVERIFIED"
    assert first.owner_wallet is None
    assert [item.decision for item in first.materials] == ["used", "used"]
    assert [item.role for item in first.materials] == ["hero", "connector"]
    assert store.get("RF-0001").candidate_id == "preview_03"


def test_public_passport_page_exposes_identity_and_status(tmp_path) -> None:
    session = _session()
    future = session.futures.selected_futures[0]
    store = SqliteObjectPassportStore(str(tmp_path / "passport.db"))
    passport = store.create(session=session, future=future)

    page = _passport_page(passport)

    assert "RF-0001" in page
    assert "Orbit Scribe" in page
    assert "UNVERIFIED" in page
    assert "NO OWNER LOCKED" in page
    assert "ARTIST MEANING" in page
