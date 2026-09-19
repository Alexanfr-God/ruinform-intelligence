from ruinform_intelligence.eval_models import EvalRecord
from ruinform_intelligence.idea_store import IdeaBatch
from ruinform_intelligence.memory_retriever import build_wave3_retrieval_context
from ruinform_intelligence.models import CreativeIntent, MaterialItem, ProjectState


def _state() -> ProjectState:
    return ProjectState(
        materials=[
            MaterialItem(item_id="wood", display_name="Bark-covered wood section"),
            MaterialItem(item_id="led", display_name="Illuminated LED strip assembly"),
            MaterialItem(item_id="bolts", display_name="Threaded rods and metal fasteners"),
        ],
        creative_intent=CreativeIntent(
            difficulty_mode="medium",
            background_mode="clean_studio",
            direction="Create a collectible light object by revealing a hidden void in the wood.",
        ),
    )


def _tricycle_state() -> ProjectState:
    return ProjectState(
        materials=[
            MaterialItem(item_id="ride", display_name="Three-wheeled ride-on object"),
            MaterialItem(item_id="chain", display_name="Chain segment"),
            MaterialItem(item_id="sheet", display_name="Brown sheet offcuts"),
            MaterialItem(item_id="umbrella", display_name="Open umbrella"),
        ],
        creative_intent=CreativeIntent(
            difficulty_mode="medium",
            background_mode="ruinform_world",
            direction=None,
        ),
    )


def _eval(outcome: str, name: str) -> EvalRecord:
    return EvalRecord(
        eval_id=f"eval-{outcome}",
        session_id=f"session-{outcome}",
        project_id=f"project-{outcome}",
        candidate_id=f"candidate-{outcome}",
        candidate_name=name,
        background_mode="clean_studio",
        difficulty_mode="medium",
        creative_direction="wood and warm light",
        render_url="https://example.test/render.png",
        outcome=outcome,
        idea_score=4,
        wow_score=4,
        physical_credibility_score=4,
        source_participation_score=5,
        collectible_quality_score=4,
        would_keep_or_build="yes" if outcome == "success" else "maybe",
        failure_tags=[] if outcome == "success" else ["too_complex"],
        good_notes="The bark and light remain recognizable.",
        bad_notes="Mechanism becomes too visible." if outcome != "success" else None,
        source_items=["bark wood", "LED light"],
        source_material_ids=["old-wood", "old-led"],
        concept_snapshot={
            "category": "lighting",
            "one_line": "Warm light revealed inside rough wood.",
            "transformation_logic": "Remove a controlled void and place light inside it.",
        },
    )


def _tricycle_eval(outcome: str, name: str, source_items: list[str], transformation: str) -> EvalRecord:
    return EvalRecord(
        eval_id=f"tri-{outcome}-{name.lower().replace(' ', '-')}",
        session_id=f"session-{outcome}-{name}",
        project_id=f"project-{outcome}-{name}",
        candidate_id=f"candidate-{outcome}-{name}",
        candidate_name=name,
        background_mode="ruinform_world",
        difficulty_mode="medium",
        creative_direction=None,
        render_url="https://example.test/render.png",
        outcome=outcome,
        idea_score=4,
        wow_score=4,
        physical_credibility_score=4,
        source_participation_score=4,
        collectible_quality_score=4,
        would_keep_or_build="maybe",
        failure_tags=[],
        good_notes=None,
        bad_notes=None,
        source_items=source_items,
        source_material_ids=[f"m-{index}" for index, _ in enumerate(source_items)],
        concept_snapshot={
            "category": "sculpture",
            "one_line": transformation,
            "transformation_logic": transformation,
        },
    )


def _idea(status: str = "pending") -> IdeaBatch:
    return IdeaBatch(
        batch_id=f"batch-{status}",
        session_id="old-session",
        project_id="old-project",
        status=status,
        background_mode="clean_studio",
        difficulty_mode="medium",
        creative_direction="wood light",
        source_items=["rough wood", "LED strip"],
        source_material_ids=["w", "l"],
        shortlisted_candidate_ids=["preview_02"],
        futures_snapshot={
            "selected_futures": [
                {
                    "candidate": {
                        "candidate_id": "preview_02",
                        "name": "Hidden Ember",
                        "one_line": "A restrained light appears from a cut void.",
                        "transformation_logic": "Open one cavity in the wood and hide the light source inside.",
                    }
                }
            ]
        },
    )


def test_wave3_retriever_limits_taste_cards_and_uses_human_memory() -> None:
    pack = build_wave3_retrieval_context(
        state=_state(),
        mode="hybrid",
        eval_records=[_eval("success", "Warm Fault"), _eval("mixed", "Busy Fault"), _eval("fail", "Impossible Fault")],
        idea_batches=[_idea()],
    )

    trace = pack.trace
    assert trace["version"] == "wave3_retriever_v2"
    assert trace["strategy"] == "deterministic_field_aware_normalized"
    assert 2 <= len(trace["taste_cards"]) <= 4
    assert "009_heartwood" in {row["id"] for row in trace["taste_cards"]}
    assert {row["outcome"] for row in trace["evals"]} == {"success", "mixed", "fail"}
    assert trace["shortlisted_ideas"][0]["name"] == "Hidden Ember"
    assert all(0 <= row["score"] <= 100 for row in trace["evals"])
    assert all(row["reasons"] for row in trace["evals"])
    assert "HUMAN-RATED MEMORY" in pack.prompt_context
    assert "SHORTLISTED GENERATED MEMORY" in pack.prompt_context
    assert "RETRIEVED 3 OF 10 CARDS" in pack.prompt_context


def test_archived_shortlist_is_not_retrieved() -> None:
    pack = build_wave3_retrieval_context(
        state=_state(),
        mode="hybrid",
        eval_records=[],
        idea_batches=[_idea(status="archived")],
    )
    assert pack.trace["shortlisted_ideas"] == []


def test_v2_generic_metal_words_do_not_create_huge_relevance() -> None:
    relevant = _tricycle_eval(
        "success",
        "Chain Wheel Study",
        ["bicycle wheel", "chain links"],
        "Capture chain links around a wheel as a rigid falling arc.",
    )
    generic = _tricycle_eval(
        "mixed",
        "Generic Metal Study",
        ["metal steel iron rods bolts nuts washers fasteners screws"],
        "A steel rod and wire support use bolts, nuts and washers.",
    )

    pack = build_wave3_retrieval_context(
        state=_tricycle_state(),
        mode="hybrid",
        eval_records=[relevant, generic],
        idea_batches=[],
    )

    assert pack.trace["version"] == "wave3_retriever_v2"
    assert all(0 <= row["score"] <= 100 for row in pack.trace["evals"])
    names = {row["candidate_name"] for row in pack.trace["evals"]}
    assert "Chain Wheel Study" in names
    assert "Generic Metal Study" not in names
    relevant_row = next(row for row in pack.trace["evals"] if row["candidate_name"] == "Chain Wheel Study")
    assert relevant_row["score"] < 100
    assert any("source family" in reason for reason in relevant_row["reasons"])


def test_source_motion_does_not_trigger_interaction_lesson_without_interaction_intent() -> None:
    pack = build_wave3_retrieval_context(
        state=_tricycle_state(),
        mode="hybrid",
        eval_records=[],
        idea_batches=[],
    )
    lesson_ids = {row["id"] for row in pack.trace["lessons"]}
    assert "interaction_must_read" not in lesson_ids
    assert set(pack.trace["query_signature"]["source_families"]) >= {
        "wheeled_frame",
        "linked_chain",
        "flexible_sheet",
        "radial_canopy",
    }
