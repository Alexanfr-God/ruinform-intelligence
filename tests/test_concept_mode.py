from ruinform_intelligence.future_models import FuturePreferences
from ruinform_intelligence.lab import _evidence_form, _futures_page
from ruinform_intelligence.models import MaterialItem, ProjectState, Unknown
from ruinform_intelligence.run_store import TransformationSession


def _blocked_session() -> TransformationSession:
    unknowns = [
        Unknown(
            property_key=f"unknown_{index}",
            question=f"Question {index}?",
            reason="Needed for exact physical verification.",
            consequence_if_unresolved="high" if index < 3 else "medium",
        )
        for index in range(7)
    ]
    state = ProjectState(
        project_id="project_concept",
        materials=[MaterialItem(item_id="material_1", display_name="test matter", unknowns=unknowns)],
    )
    return TransformationSession(
        session_id="session_concept",
        project_id=state.project_id,
        stage="evidence_required",
        project_state=state,
    )


def test_concept_mode_is_opt_in() -> None:
    preferences = FuturePreferences()
    assert preferences.concept_mode is False
    assert preferences.model_copy(update={"concept_mode": True}).concept_mode is True


def test_evidence_form_offers_concept_mode_and_limits_primary_questions() -> None:
    rendered = _evidence_form(_blocked_session())
    assert "CONTINUE IN CONCEPT MODE" in rendered
    assert "UNVERIFIED AI ASSUMPTIONS" in rendered
    assert "SHOW 2 MORE QUESTIONS" in rendered
    assert rendered.count('class="question"') == 7


def test_concept_mode_persists_on_session() -> None:
    session = _blocked_session().model_copy(
        update={
            "reasoning_mode": "concept",
            "concept_mode_acknowledged": True,
            "concept_notice_version": "2026-09-15-v1",
            "stage": "ready_for_futures",
        }
    )
    restored = TransformationSession.model_validate_json(session.model_dump_json())
    assert restored.reasoning_mode == "concept"
    assert restored.concept_mode_acknowledged is True
    assert restored.concept_notice_version == "2026-09-15-v1"
