from ruinform_intelligence.idea_store import IdeaBatch, SqliteIdeaStore


def _batch(batch_id: str = "batch-1") -> IdeaBatch:
    return IdeaBatch(
        batch_id=batch_id,
        session_id="session-1",
        project_id="project-1",
        background_mode="clean_studio",
        difficulty_mode="medium",
        creative_direction="Make one strong gesture",
        source_items=["Bottle", "Wire"],
        source_material_ids=["m1", "m2"],
        futures_snapshot={
            "selected_futures": [
                {
                    "candidate": {
                        "candidate_id": "preview_01",
                        "name": "Future One",
                    },
                    "review": {"artistic_impact_score": 91},
                    "rank_score": 88.0,
                },
                {
                    "candidate": {
                        "candidate_id": "preview_02",
                        "name": "Future Two",
                    },
                    "review": {"artistic_impact_score": 84},
                    "rank_score": 81.0,
                },
            ]
        },
    )


def test_idea_store_lifecycle(tmp_path):
    store = SqliteIdeaStore(str(tmp_path / "ideas.db"))
    item = store.save(_batch())

    assert store.get(item.batch_id).status == "pending"
    assert store.list_recent(status="pending")[0].batch_id == item.batch_id

    shortlisted = store.shortlist(item.batch_id, "preview_01")
    assert shortlisted.shortlisted_candidate_ids == ["preview_01"]

    rendered = store.mark_rendered(session_id="session-1", candidate_id="preview_01")
    assert rendered is not None
    assert rendered.status == "rendered"
    assert rendered.rendered_candidate_ids == ["preview_01"]

    archived = store.archive(item.batch_id)
    assert archived.status == "archived"


def test_idea_store_save_is_idempotent(tmp_path):
    store = SqliteIdeaStore(str(tmp_path / "ideas.db"))
    item = _batch()
    store.save(item)
    store.save(item)

    rows = store.list_recent()
    assert len(rows) == 1
    assert rows[0].batch_id == item.batch_id
