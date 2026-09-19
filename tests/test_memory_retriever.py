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
    assert 2 <= len(trace["taste_cards"]) <= 4
    assert "009_heartwood" in {row["id"] for row in trace["taste_cards"]}
    assert {row["outcome"] for row in trace["evals"]} == {"success", "mixed", "fail"}
    assert trace["shortlisted_ideas"][0]["name"] == "Hidden Ember"
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
