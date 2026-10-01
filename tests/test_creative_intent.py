from ruinform_intelligence.concept_preview import (
    _creative_direction,
    _difficulty_contract,
    _source_participation_contract,
)
from ruinform_intelligence.models import CreativeIntent, MaterialItem, ProjectState
from ruinform_intelligence.render_director import _supporting_parts_contract
from ruinform_intelligence.render_prompt import _background_render_instruction, _difficulty_render_instruction


def test_creative_intent_defaults_are_backwards_compatible() -> None:
    state = ProjectState()
    assert state.creative_intent.direction is None
    assert state.creative_intent.difficulty_mode == "medium"
    assert state.creative_intent.background_mode == "clean_studio"


def test_creative_direction_persists_and_session_adjustment_is_additive() -> None:
    state = ProjectState(
        creative_intent=CreativeIntent(
            direction="wall object, no electronics",
            difficulty_mode="easy",
            background_mode="clean_studio",
        )
    )
    text = _creative_direction(state, "keep the cup intact")
    assert "wall object, no electronics" in text
    assert "keep the cup intact" in text
    assert "PROJECT DIRECTION" in text
    assert "SESSION ADJUSTMENT" in text


def test_difficulty_contracts_are_materially_different() -> None:
    assert "0-2" in _difficulty_contract("easy")
    assert "0-4" in _difficulty_contract("medium")
    assert "radical geometry" in _difficulty_contract("wild")


def test_source_participation_contract_prefers_source_economy_for_small_sets() -> None:
    state = ProjectState(
        materials=[
            MaterialItem(display_name="bottle"),
            MaterialItem(display_name="pencil"),
            MaterialItem(display_name="LED strip"),
        ]
    )
    text = _source_participation_contract(state, candidate_count=4)
    assert "SMALLEST coherent subset" in text
    assert "No concept is required to use all source items" in text
    assert "Intentional omission is valid" in text
    assert "Every used source must carry a necessary" in text


def test_visual_director_support_budget_tracks_difficulty() -> None:
    easy = ProjectState(creative_intent=CreativeIntent(difficulty_mode="easy"))
    medium = ProjectState(creative_intent=CreativeIntent(difficulty_mode="medium"))
    wild = ProjectState(creative_intent=CreativeIntent(difficulty_mode="wild"))
    assert "0-2" in _supporting_parts_contract(easy)
    assert "0-4" in _supporting_parts_contract(medium)
    assert "specialist structure" in _supporting_parts_contract(wild)


def test_clean_studio_background_contract_keeps_environment_neutral() -> None:
    state = ProjectState(
        creative_intent=CreativeIntent(background_mode="clean_studio")
    )
    text = _background_render_instruction(state)
    assert "CLEAN STUDIO" in text
    assert "No ruins" in text
    assert "object alone" in text


def test_ruinform_world_background_contract_is_post_apocalyptic_but_object_first() -> None:
    state = ProjectState(
        creative_intent=CreativeIntent(background_mode="ruinform_world")
    )
    text = _background_render_instruction(state)
    assert "RUINFORM WORLD" in text
    assert "POST-APOCALYPTIC" in text
    assert "70%" in text
    assert "No generic cyberpunk" in text


def test_render_difficulty_contract_tracks_project_mode() -> None:
    easy = ProjectState(creative_intent=CreativeIntent(difficulty_mode="easy"))
    wild = ProjectState(creative_intent=CreativeIntent(difficulty_mode="wild"))
    assert "EASY BUILD LANGUAGE" in _difficulty_render_instruction(easy)
    assert "WILD BUILD LANGUAGE" in _difficulty_render_instruction(wild)
