from ruinform_intelligence.models import ProjectState
from ruinform_intelligence.run_store import SqliteRunStore, TransformationSession


def test_sqlite_store_round_trip(tmp_path) -> None:
    store = SqliteRunStore(str(tmp_path / "ruinform.db"))
    state = ProjectState()
    session = TransformationSession(
        project_id=state.project_id,
        stage="evidence_required",
        project_state=state,
    )

    saved = store.save(session)
    loaded = store.get(saved.session_id)

    assert loaded.session_id == saved.session_id
    assert loaded.project_id == state.project_id
    assert loaded.stage == "evidence_required"
