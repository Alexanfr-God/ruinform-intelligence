from __future__ import annotations

import logging
import re
from typing import Literal

from .evidence_gate import can_advance_to_ideation
from .future_models import FuturePreferences
from .future_pipeline import discover_future_forms
from .run_store import SqliteRunStore, TransformationSession
from .self_healing_preview import generate_concept_preview


logger = logging.getLogger("ruinform.live_futures")
ConceptMode = Literal["hybrid", "art", "buildable", "functional"]
DifficultyMode = Literal["easy", "medium", "wild"]
_VISIBLE_FUTURE_COUNT = 2


def _internal_candidate_count(mode: ConceptMode) -> int:
    """Spend search budget where it protects quality.

    MIX/HYBRID remains broad enough to benefit from one extra internal direction,
    while focused modes can go straight to two candidates. In every case the same
    pre-render critic and one-pass self-healing remain enabled.
    """
    return 3 if mode == "hybrid" else 2


def _source_ids(item) -> frozenset[str]:
    return frozenset(use.material_item_id for use in item.candidate.material_uses)


def _classify_family_text(text: str) -> str:
    families: tuple[tuple[str, str], ...] = (
        ("subtract_reveal", r"\b(cut|slit|notch|trim|perforat|open|remove|reveal|carve|hollow|crescent)\w*"),
        ("reform", r"\b(bend|fold|roll|flatten|twist|curve|flare|compress|stretch|reshape|re-form)\w*"),
        ("disassemble_recompose", r"\b(disassembl|separat|unfasten|recompos|reassembl|reverse|reorient|expose)\w*"),
        ("repeat_scale", r"\b(repeat|cascade|gradient|progressiv|concentric|array|rhythm|enlarge|shrink|scale)\w*"),
        ("tension_suspend", r"\b(tension|suspend|hang|counterbalance|balance|cantilever|brace|trap|float)\w*"),
        ("surface_skin", r"\b(laminat|weave|wrap|layer|stitch|skin|peel|upholster|surface)\w*"),
        ("kinetic_interaction", r"\b(rotate|pivot|slide|hinge|spring|kinetic|move|motion|respond|spin)\w*"),
        ("fusion_capture", r"\b(weld|rivet|clamp|bind|interlock|capture|bolt|join|link)\w*"),
        ("role_reassignment", r"\b(reassign|convert|repurpose|holder|hook|shelf|seat|valet|basin)\b"),
        ("arrangement", r"\b(arrange|place|position|register|cluster|field|beside|above|around|stack)\w*"),
    )
    for family, pattern in families:
        if re.search(pattern, text):
            return family
    return "other"


def _transformation_family(item) -> str:
    """Infer the dominant PHYSICAL operator, preferring explicit fabrication operations.

    V1.1 deliberately avoids reading poetic one-line copy first. Words such as "bend the
    horizon" or "fracture the field" may be metaphors rather than fabrication moves.
    `key_operations` therefore has first authority, followed by transformation_logic.
    """
    candidate = item.candidate
    operations = " ".join(candidate.key_operations).lower()
    family = _classify_family_text(operations)
    if family != "other":
        return family
    return _classify_family_text(candidate.transformation_logic.lower())


def _semantic_motif(item) -> str:
    """Coarsely detect Concept Seed siblings without pretending to do full semantics."""
    candidate = item.candidate
    text = " ".join(
        [candidate.name, candidate.one_line, candidate.artistic_thesis]
    ).lower()
    motifs: tuple[tuple[str, str], ...] = (
        ("fracture", r"\b(fault|faultline|fissure|fracture|broken|rupture|crack|split|interrupt)\w*"),
        ("reveal", r"\b(reveal|hidden|inside|expose|latent|uncover|discover)\w*"),
        ("absence", r"\b(absence|void|empty|missing|ghost|negative[ -]space)\w*"),
        ("balance_pressure", r"\b(balance|tension|pressure|weight|gravity|precarious|fall|suspend)\w*"),
        ("containment_protection", r"\b(contain|cage|hold|trap|enclose|protect|shelter|restrain)\w*"),
        ("memory_repair", r"\b(memory|scar|wear|trace|history|age|repair|mend|heal)\w*"),
        ("growth_repetition", r"\b(grow|growth|repeat|rhythm|cascade|multiply|accumulat|proliferat)\w*"),
        ("inversion_reassignment", r"\b(invert|reverse|inside[ -]out|reassign|repurpose|role reversal)\w*"),
        ("ritual_habit", r"\b(ritual|habit|routine|care|domestic|daily|ceremony)\w*"),
        ("motion_response", r"\b(motion|kinetic|rotate|pivot|move|respond|responsive|spin)\w*"),
    )
    for motif, pattern in motifs:
        if re.search(pattern, text):
            return motif
    return "other"


def _diversity_score(candidate, anchor) -> float:
    """Rank the second visible Future for quality plus physical and semantic distance."""
    score = float(candidate.rank_score)

    candidate_family = _transformation_family(candidate)
    anchor_family = _transformation_family(anchor)
    if candidate_family != anchor_family:
        score += 16.0

    candidate_motif = _semantic_motif(candidate)
    anchor_motif = _semantic_motif(anchor)
    if candidate_motif != anchor_motif:
        score += 12.0
    elif candidate_motif != "other":
        score -= 10.0

    if _source_ids(candidate) != _source_ids(anchor):
        score += 7.0
    if candidate.candidate.category != anchor.candidate.category:
        score += 3.0

    if candidate.candidate.artistic_thesis.strip().lower() != anchor.candidate.artistic_thesis.strip().lower():
        score += 1.0
    return score


def _visible_preview(futures):
    """Expose two strong directions while avoiding physical or semantic siblings.

    Quality is the hard boundary: when two or more candidates passed the critic, the
    visible pair is chosen only from PASS candidates. Diversity then decides which
    strong second direction complements the top-ranked anchor. REVISE is considered
    only when fewer than two PASS candidates exist, and REJECT remains last-resort
    fallback data rather than a diversity candidate.
    """
    ranked = list(futures.selected_futures)
    passed = [item for item in ranked if item.review.status == "pass"]
    non_rejected = [item for item in ranked if item.review.status != "reject"]

    if len(passed) >= _VISIBLE_FUTURE_COUNT:
        pool = passed
    elif passed:
        remaining = [
            item for item in non_rejected if item.candidate.candidate_id != passed[0].candidate.candidate_id
        ]
        pool = passed + remaining
    else:
        pool = non_rejected or ranked

    if not pool:
        return futures.model_copy(update={"selected_futures": []})

    chosen = [pool[0]]
    if len(pool) > 1:
        second = max(pool[1:], key=lambda item: _diversity_score(item, chosen[0]))
        chosen.append(second)

    if len(chosen) < _VISIBLE_FUTURE_COUNT:
        chosen_ids = {item.candidate.candidate_id for item in chosen}
        for item in ranked:
            if item.candidate.candidate_id in chosen_ids:
                continue
            chosen.append(item)
            if len(chosen) >= _VISIBLE_FUTURE_COUNT:
                break

    return futures.model_copy(update={"selected_futures": chosen[:_VISIBLE_FUTURE_COUNT]})


async def discover_session_futures(
    *,
    session: TransformationSession,
    preferences: FuturePreferences,
    user_intent: str | None,
    max_revision_rounds: int,
    store: SqliteRunStore,
    mode: ConceptMode = "hybrid",
    difficulty_mode: DifficultyMode | None = None,
) -> TransformationSession:
    verified_ready = can_advance_to_ideation(session.project_state)
    concept_ready = session.reasoning_mode == "concept" and session.concept_mode_acknowledged
    if not verified_ready and not concept_ready:
        raise ValueError("Project still needs more evidence before future discovery")

    effective_preferences = preferences.model_copy(
        update={"concept_mode": bool(concept_ready)}
    )

    working_state = session.project_state
    if difficulty_mode is not None:
        working_state = working_state.model_copy(
            update={
                "creative_intent": working_state.creative_intent.model_copy(
                    update={"difficulty_mode": difficulty_mode}
                )
            }
        )

    if concept_ready:
        candidate_count = _internal_candidate_count(mode)
        logger.info(
            "futures vision-preview:start session=%s mode=%s difficulty=%s internal_budget=%s exposed=%s",
            session.session_id,
            mode,
            working_state.creative_intent.difficulty_mode,
            candidate_count,
            _VISIBLE_FUTURE_COUNT,
        )
        futures = await generate_concept_preview(
            state=working_state,
            mode=mode,
            user_intent=user_intent,
            candidate_count=candidate_count,
        )
        internal_visible = len(futures.selected_futures)
        for item in futures.selected_futures:
            logger.info(
                "futures candidate session=%s id=%s status=%s rank=%.2f family=%s motif=%s sources=%s name=%s",
                session.session_id,
                item.candidate.candidate_id,
                item.review.status,
                item.rank_score,
                _transformation_family(item),
                _semantic_motif(item),
                ",".join(sorted(_source_ids(item))),
                item.candidate.name,
            )
        futures = _visible_preview(futures)
        logger.info(
            "futures vision-preview:done session=%s internal_visible=%s exposed=%s statuses=%s families=%s motifs=%s",
            session.session_id,
            internal_visible,
            len(futures.selected_futures),
            ",".join(item.review.status for item in futures.selected_futures),
            ",".join(_transformation_family(item) for item in futures.selected_futures),
            ",".join(_semantic_motif(item) for item in futures.selected_futures),
        )
    else:
        logger.info("futures verified:start session=%s", session.session_id)
        futures = await discover_future_forms(
            state=working_state,
            preferences=effective_preferences,
            user_intent=user_intent,
            max_revision_rounds=max_revision_rounds,
        )
        logger.info(
            "futures verified:done session=%s visible=%s",
            session.session_id,
            len(futures.selected_futures),
        )

    return store.save(
        session.model_copy(
            update={
                "stage": "futures_ready",
                "futures": futures,
                "project_state": working_state,
            }
        )
    )
