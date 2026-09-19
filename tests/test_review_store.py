from ruinform_intelligence.review_models import ReviewItem
from ruinform_intelligence.review_store import SqliteReviewStore


def _item(review_id: str = "review-1") -> ReviewItem:
    return ReviewItem(
        review_id=review_id,
        session_id="session-1",
        project_id="project-1",
        candidate_id="candidate-1",
        candidate_name="Test Future",
        render_url="https://example.com/render.png",
        background_mode="clean_studio",
        difficulty_mode="medium",
        creative_direction="Keep it simple",
        source_items=["Bottle", "Wire"],
        source_material_ids=["m1", "m2"],
        concept_snapshot={"name": "Test Future"},
        review_snapshot={"artistic_impact_score": 9},
        render_snapshot={"status": "pass"},
    )


def test_review_store_pending_to_evaluated(tmp_path):
    store = SqliteReviewStore(str(tmp_path / "review.db"))
    item = store.save(_item())

    assert store.get(item.review_id).status == "pending"
    assert [row.review_id for row in store.list_recent(status="pending")] == [item.review_id]

    updated = store.mark_evaluated(item.review_id, "eval-1")
    assert updated.status == "evaluated"
    assert updated.eval_id == "eval-1"
    assert updated.evaluated_at_iso is not None
    assert store.list_recent(status="pending") == []
    assert store.list_recent(status="evaluated")[0].review_id == item.review_id


def test_mark_matching_evaluated(tmp_path):
    store = SqliteReviewStore(str(tmp_path / "review.db"))
    item = store.save(_item())

    matched = store.mark_matching_evaluated(
        session_id="session-1",
        candidate_id="candidate-1",
        render_url="https://example.com/render.png",
        eval_id="eval-2",
    )

    assert matched is not None
    assert matched.review_id == item.review_id
    assert matched.status == "evaluated"
    assert matched.eval_id == "eval-2"


def test_review_store_save_is_idempotent(tmp_path):
    store = SqliteReviewStore(str(tmp_path / "review.db"))
    item = _item()
    store.save(item)
    store.save(item)

    rows = store.list_recent()
    assert len(rows) == 1
    assert rows[0].review_id == item.review_id
