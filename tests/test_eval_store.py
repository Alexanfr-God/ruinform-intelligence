from ruinform_intelligence.eval_models import EvalRecord
from ruinform_intelligence.eval_store import SqliteEvalStore


def _record(*, outcome: str = "mixed", name: str = "Almost Impact") -> EvalRecord:
    return EvalRecord(
        session_id="session-1",
        project_id="project-1",
        candidate_id=f"candidate-{name}",
        candidate_name=name,
        background_mode="clean_studio",
        difficulty_mode="wild",
        creative_direction="one unforgettable visual gesture",
        render_url="https://example.com/render.png",
        outcome=outcome,
        idea_score=5,
        wow_score=5,
        physical_credibility_score=4,
        source_participation_score=4,
        collectible_quality_score=5,
        would_keep_or_build="yes",
        failure_tags=["low_physical_credibility"] if outcome != "success" else [],
        good_notes="Strong signature gesture",
        source_items=["Aqua bottle", "Bear"],
        source_material_ids=["bottle-1", "bear-1"],
        concept_snapshot={"name": name},
        review_snapshot={"artistic_impact_score": 9},
        render_snapshot={"status": "pass"},
    )


def test_eval_store_saves_and_lists_session(tmp_path):
    store = SqliteEvalStore(str(tmp_path / "evals.db"))
    record = _record()
    store.save(record)

    rows = store.list_for_session("session-1")

    assert len(rows) == 1
    assert rows[0].eval_id == record.eval_id
    assert rows[0].candidate_name == "Almost Impact"
    assert rows[0].wow_score == 5


def test_eval_store_filters_success_mixed_fail(tmp_path):
    store = SqliteEvalStore(str(tmp_path / "evals.db"))
    store.save(_record(outcome="success", name="Almost Impact"))
    store.save(_record(outcome="mixed", name="Through The Throat"))
    store.save(_record(outcome="fail", name="Overbuilt Prototype"))

    success = store.list_recent(outcome="success")
    mixed = store.list_recent(outcome="mixed")
    failed = store.list_recent(outcome="fail")

    assert [row.candidate_name for row in success] == ["Almost Impact"]
    assert [row.candidate_name for row in mixed] == ["Through The Throat"]
    assert [row.candidate_name for row in failed] == ["Overbuilt Prototype"]
