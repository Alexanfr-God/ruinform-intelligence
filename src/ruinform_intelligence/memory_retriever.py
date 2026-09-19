from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Iterable

from .eval_models import EvalRecord
from .eval_store import create_eval_store
from .idea_store import IdeaBatch, create_idea_store
from .models import ProjectState
from .taste_library import _read_json, load_design_brain_runtime_context, load_taste_card_catalog


_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "but", "by", "for", "from", "in", "into",
    "is", "it", "of", "on", "or", "the", "to", "use", "using", "with", "without", "object",
    "source", "material", "create", "make", "keep", "real", "simple", "new", "one", "this", "that",
    "more", "less", "very", "main", "visual", "art", "artwork", "thing", "parts", "part",
}

# Retriever v2 deliberately does NOT expand one token into every synonym in a group.
# A semantic family can contribute at most once to a field score. This prevents a single
# generic word such as "metal" from becoming nine synthetic overlaps like
# steel/wire/rod/bolt/nut/washer/fastener/screw.
_SOURCE_FAMILIES: dict[str, set[str]] = {
    "wheeled_frame": {"tricycle", "bicycle", "bike", "cycle", "wheeled", "wheel", "wheels", "rideon", "ride", "pedal", "pedals"},
    "linked_chain": {"chain", "chains", "link", "links", "linked"},
    "flexible_sheet": {"leather", "hide", "offcut", "offcuts", "sheet", "sheets", "scrap", "scraps", "fabric", "textile", "cloth"},
    "radial_canopy": {"umbrella", "umbrellas", "canopy", "parasol", "rib", "ribs"},
    "wood_mass": {"wood", "wooden", "timber", "plank", "planks", "board", "boards", "log", "branch", "branches", "bark"},
    "transparent_vessel": {"glass", "bottle", "bottles", "jar", "jars", "vessel", "acrylic"},
    "light_source": {"light", "lighting", "lamp", "lamps", "bulb", "bulbs", "led", "leds", "flashlight"},
    "frame_panel": {"frame", "frames", "picture", "print", "poster", "panel", "panels", "canvas"},
}

_BEHAVIOR_GROUPS: dict[str, set[str]] = {
    "articulated": {"chain", "link", "links", "hinge", "joint", "joints", "articulated"},
    "flexible": {"flexible", "soft", "bend", "bending", "curve", "curved", "coil", "coiled", "loop", "wrap", "wrapped", "fold", "folded"},
    "rigid_frame": {"frame", "rod", "rods", "bar", "bars", "shaft", "axle", "bracket", "support", "spine"},
    "radial": {"radial", "wheel", "wheels", "umbrella", "canopy", "rib", "ribs", "spoke", "spokes"},
    "translucent": {"transparent", "translucent", "glass", "acrylic", "diffuser"},
    "surface_sheet": {"sheet", "sheets", "panel", "panels", "fabric", "leather", "hide", "canopy"},
}

_OPERATOR_GROUPS: dict[str, set[str]] = {
    "subtractive_reveal": {"cut", "cutting", "remove", "removed", "carve", "open", "split", "reveal", "revealed", "void", "negative"},
    "kinetic_rotation": {"move", "moving", "kinetic", "pivot", "rotate", "rotation", "turn", "turning", "spin", "hinge", "slider", "slide"},
    "tension_balance": {"tension", "tensioned", "balance", "balanced", "suspend", "suspended", "hang", "hanging", "counterweight", "pull"},
    "repetition": {"repeat", "repeated", "repetition", "array", "stack", "stacked", "sequence", "rhythm", "multiple"},
    "illumination": {"light", "lighting", "lamp", "bulb", "led", "glow", "luminous", "shadow", "project", "projection"},
    "functional_support": {"functional", "utility", "useful", "holder", "stand", "support", "shelf", "bookend", "book", "storage", "valet"},
    "fold_wrap_lace": {"fold", "folded", "wrap", "wrapped", "lace", "laced", "stitch", "stitched", "sew", "sewn"},
    "compression_capture": {"compress", "compressed", "clamp", "clamped", "capture", "captured", "pin", "pinned", "cradle"},
}

_GENERIC_TOKENS = {
    "black", "brown", "pink", "silver", "metal", "steel", "iron", "small", "large", "medium", "open",
    "dark", "lightweight", "piece", "pieces", "item", "items", "section", "assembly",
}

_EVAL_MIN_MATCH = 30.0
_SHORTLIST_MIN_MATCH = 35.0


@dataclass(frozen=True)
class RetrievalPack:
    prompt_context: str
    trace: dict[str, Any]


@dataclass(frozen=True)
class QuerySignature:
    text: str
    source_tokens: frozenset[str]
    context_tokens: frozenset[str]
    all_tokens: frozenset[str]
    source_families: frozenset[str]
    behaviors: frozenset[str]
    operators: frozenset[str]


@dataclass(frozen=True)
class MatchResult:
    score: float
    reasons: tuple[str, ...]
    components: dict[str, float]
    strong_signal: bool


def _tokenize(value: str | None) -> set[str]:
    """Return exact normalized tokens only; never synonym-expand them."""
    if not value:
        return set()
    words = set(re.findall(r"[a-zA-Z0-9_]+", value.lower().replace("-", " ")))
    return {word for word in words if len(word) > 2 and word not in _STOPWORDS}


def _flatten_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return " ".join(_flatten_text(item) for item in value.values())
    if isinstance(value, (list, tuple, set)):
        return " ".join(_flatten_text(item) for item in value)
    return str(value)


def _group_hits(tokens: set[str] | frozenset[str], groups: dict[str, set[str]]) -> set[str]:
    return {name for name, members in groups.items() if tokens & members}


def _non_generic(tokens: set[str] | frozenset[str]) -> set[str]:
    return set(tokens) - _GENERIC_TOKENS


def _ratio_hits(left: set[str] | frozenset[str], right: set[str] | frozenset[str], *, cap: int = 3) -> tuple[float, set[str]]:
    hits = _non_generic(left) & _non_generic(right)
    if not hits:
        return 0.0, set()
    return min(1.0, len(hits) / max(1, cap)), hits


def _group_ratio(query_groups: set[str] | frozenset[str], candidate_groups: set[str] | frozenset[str], *, cap: int = 2) -> tuple[float, set[str]]:
    hits = set(query_groups) & set(candidate_groups)
    if not hits:
        return 0.0, set()
    return min(1.0, len(hits) / max(1, min(cap, len(query_groups) or 1))), hits


def _project_query(state: ProjectState, user_intent: str | None, mode: str) -> QuerySignature:
    source_parts: list[str] = []
    context_parts: list[str] = [
        mode,
        state.creative_intent.difficulty_mode,
        state.creative_intent.direction or "",
        user_intent or "",
    ]
    for material in state.materials:
        source_parts.append(material.display_name)
        for observation in material.observations:
            source_parts.append(observation.label)
    context_parts.extend(state.constraints.tools_available)
    context_parts.extend(state.constraints.skills)

    source_text = " | ".join(piece for piece in source_parts if piece)
    context_text = " | ".join(piece for piece in context_parts if piece)
    source_tokens = frozenset(_tokenize(source_text))
    context_tokens = frozenset(_tokenize(context_text))
    all_tokens = frozenset(set(source_tokens) | set(context_tokens))
    return QuerySignature(
        text=" | ".join(piece for piece in [source_text, context_text] if piece),
        source_tokens=source_tokens,
        context_tokens=context_tokens,
        all_tokens=all_tokens,
        source_families=frozenset(_group_hits(source_tokens, _SOURCE_FAMILIES)),
        behaviors=frozenset(_group_hits(all_tokens, _BEHAVIOR_GROUPS)),
        operators=frozenset(_group_hits(context_tokens, _OPERATOR_GROUPS)),
    )


def _memory_match(
    query: QuerySignature,
    *,
    source_text: str,
    concept_text: str,
    difficulty_match: bool = False,
) -> MatchResult:
    source_tokens = frozenset(_tokenize(source_text))
    concept_tokens = frozenset(_tokenize(concept_text))
    all_candidate_tokens = frozenset(set(source_tokens) | set(concept_tokens))

    exact_source_ratio, exact_source_hits = _ratio_hits(query.source_tokens, source_tokens, cap=3)
    context_ratio, context_hits = _ratio_hits(query.context_tokens, concept_tokens, cap=3)

    source_family_ratio, source_family_hits = _group_ratio(
        query.source_families,
        _group_hits(source_tokens, _SOURCE_FAMILIES),
        cap=2,
    )
    behavior_ratio, behavior_hits = _group_ratio(
        query.behaviors,
        _group_hits(all_candidate_tokens, _BEHAVIOR_GROUPS),
        cap=2,
    )
    operator_ratio, operator_hits = _group_ratio(
        query.operators,
        _group_hits(concept_tokens, _OPERATOR_GROUPS),
        cap=2,
    )

    components = {
        "exact_source": round(30.0 * exact_source_ratio, 2),
        "source_family": round(30.0 * source_family_ratio, 2),
        "behavior": round(15.0 * behavior_ratio, 2),
        "operator": round(15.0 * operator_ratio, 2),
        "direction": round(5.0 * context_ratio, 2),
        "difficulty": 5.0 if difficulty_match else 0.0,
    }
    score = min(100.0, round(sum(components.values()), 2))

    reasons: list[str] = []
    if exact_source_hits:
        reasons.append("exact source: " + ", ".join(sorted(exact_source_hits)[:4]))
    if source_family_hits:
        reasons.append("source family: " + ", ".join(sorted(source_family_hits)))
    if behavior_hits:
        reasons.append("behavior: " + ", ".join(sorted(behavior_hits)))
    if operator_hits:
        reasons.append("operator: " + ", ".join(sorted(operator_hits)))
    if context_hits:
        reasons.append("direction: " + ", ".join(sorted(context_hits)[:4]))
    if difficulty_match:
        reasons.append("same difficulty")

    strong_signal = bool(exact_source_hits or source_family_hits or operator_hits)
    return MatchResult(score=score, reasons=tuple(reasons), components=components, strong_signal=strong_signal)


def _taste_match(query: QuerySignature, card: dict[str, Any], difficulty: str) -> MatchResult:
    materials = _flatten_text(card.get("materials"))
    concept = " | ".join(
        [
            _flatten_text(card.get("tags")),
            _flatten_text(card.get("summary")),
            _flatten_text(card.get("learn")),
            _flatten_text(card.get("operator")),
            _flatten_text(card.get("core_formula")),
        ]
    )
    card_difficulty = str(card.get("difficulty", "")).lower()
    return _memory_match(
        query,
        source_text=materials,
        concept_text=concept,
        difficulty_match=difficulty in card_difficulty,
    )


def _select_taste_cards(query: QuerySignature, difficulty: str, *, limit: int = 3) -> list[tuple[MatchResult, dict[str, Any]]]:
    scored: list[tuple[MatchResult, str, dict[str, Any]]] = []
    for card in load_taste_card_catalog():
        match = _taste_match(query, card, difficulty)
        scored.append((match, str(card.get("id", "")), card))
    scored.sort(key=lambda row: (-row[0].score, row[1]))
    count = max(2, min(4, limit))
    return [(match, card) for match, _, card in scored[:count]]


def _eval_text(record: EvalRecord) -> str:
    candidate = record.concept_snapshot or {}
    return " | ".join(
        [
            record.creative_direction or "",
            record.candidate_name,
            _flatten_text(candidate.get("category")),
            _flatten_text(candidate.get("one_line")),
            _flatten_text(candidate.get("artistic_thesis")),
            _flatten_text(candidate.get("transformation_logic")),
            " ".join(record.failure_tags),
            record.good_notes or "",
            record.bad_notes or "",
            record.next_hypothesis or "",
        ]
    )


def _select_evals(query: QuerySignature, difficulty: str, records: Iterable[EvalRecord]) -> list[tuple[MatchResult, EvalRecord]]:
    buckets: dict[str, list[tuple[MatchResult, EvalRecord]]] = {"success": [], "mixed": [], "fail": []}
    for record in records:
        match = _memory_match(
            query,
            source_text=" ".join(record.source_items),
            concept_text=_eval_text(record),
            difficulty_match=record.difficulty_mode == difficulty,
        )
        if match.score < _EVAL_MIN_MATCH or not match.strong_signal:
            continue
        buckets[record.outcome].append((match, record))

    selected: list[tuple[MatchResult, EvalRecord]] = []
    # One example per human outcome keeps the memory balanced: positive relationship,
    # boundary case, warning. Scores are normalized match confidence, not quality scores.
    for outcome in ("success", "mixed", "fail"):
        rows = sorted(buckets[outcome], key=lambda row: (-row[0].score, row[1].created_at_iso))
        if rows:
            selected.append(rows[0])
    return sorted(selected, key=lambda row: -row[0].score)[:3]


def _shortlisted_rows(batch: IdeaBatch) -> list[dict[str, Any]]:
    if batch.status == "archived" or not batch.shortlisted_candidate_ids:
        return []
    selected = set(batch.shortlisted_candidate_ids)
    rows = batch.futures_snapshot.get("selected_futures", [])
    result: list[dict[str, Any]] = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        candidate = row.get("candidate", {})
        if isinstance(candidate, dict) and candidate.get("candidate_id") in selected:
            result.append(row)
    return result


def _select_shortlisted(query: QuerySignature, batches: Iterable[IdeaBatch]) -> list[tuple[MatchResult, IdeaBatch, dict[str, Any]]]:
    scored: list[tuple[MatchResult, IdeaBatch, dict[str, Any]]] = []
    for batch in batches:
        for row in _shortlisted_rows(batch):
            candidate = row.get("candidate", {}) if isinstance(row.get("candidate"), dict) else {}
            match = _memory_match(
                query,
                source_text=" ".join(batch.source_items),
                concept_text=_flatten_text(candidate),
                difficulty_match=batch.difficulty_mode == "medium" if not batch.difficulty_mode else False,
            )
            # Shortlists are unjudged and therefore need a stronger relevance floor than
            # human-rated examples. Generic material-family coincidence is not enough.
            if match.score >= _SHORTLIST_MIN_MATCH and match.strong_signal:
                scored.append((match, batch, row))
    scored.sort(key=lambda row: (-row[0].score, row[1].created_at_iso))
    return scored[:2]


def _load_lessons() -> list[dict[str, Any]]:
    data = _read_json("docs/WAVE3_RETRIEVAL_RULES.json")
    lessons = data.get("lessons") if isinstance(data, dict) else None
    return [lesson for lesson in lessons or [] if isinstance(lesson, dict)]


def _select_lessons(query: QuerySignature) -> list[dict[str, Any]]:
    """Lessons are conditional on stated intent, not merely on owning a suggestive object.

    A bicycle or umbrella must not trigger an interaction lesson just because it can move.
    The user direction/context needs to contain the relevant operator signal.
    """
    context_tokens = set(query.context_tokens)
    context_operators = _group_hits(context_tokens, _OPERATOR_GROUPS)
    scored: list[tuple[int, str, dict[str, Any]]] = []
    for lesson in _load_lessons():
        cue_tokens = _tokenize(_flatten_text(lesson.get("cues")))
        exact = len(context_tokens & cue_tokens)
        cue_operators = _group_hits(cue_tokens, _OPERATOR_GROUPS)
        semantic = len(context_operators & cue_operators)
        score = exact * 2 + semantic
        if score > 0:
            scored.append((score, str(lesson.get("id", "")), lesson))
    scored.sort(key=lambda row: (-row[0], row[1]))
    return [row[2] for row in scored[:2]]


def _compact_eval(record: EvalRecord) -> str:
    candidate = record.concept_snapshot or {}
    transformation = str(candidate.get("transformation_logic", ""))[:700]
    return (
        f"HUMAN EVAL {record.outcome.upper()}: {record.candidate_name}\n"
        f"source={' · '.join(record.source_items)}\n"
        f"scores=idea {record.idea_score}/5, wow {record.wow_score}/5, physical {record.physical_credibility_score}/5, "
        f"source {record.source_participation_score}/5, collectible {record.collectible_quality_score}/5; keep={record.would_keep_or_build}\n"
        f"transformation={transformation}\n"
        f"good={record.good_notes or 'none recorded'}\n"
        f"bad={record.bad_notes or 'none recorded'}\n"
        f"failure_tags={', '.join(record.failure_tags) or 'none'}\n"
        f"next_hypothesis={record.next_hypothesis or 'none recorded'}"
    )


def _compact_shortlist(batch: IdeaBatch, row: dict[str, Any]) -> str:
    candidate = row.get("candidate", {}) if isinstance(row.get("candidate"), dict) else {}
    return (
        f"SHORTLISTED / UNJUDGED IDEA: {candidate.get('name', 'Unnamed future')}\n"
        f"source={' · '.join(batch.source_items)}\n"
        f"one_line={candidate.get('one_line', '')}\n"
        f"transformation={str(candidate.get('transformation_logic', ''))[:700]}\n"
        "status=human-shortlisted hypothesis only; do not treat as a proven success"
    )


def _trace_match(match: MatchResult) -> dict[str, Any]:
    return {
        "score": round(match.score, 1),
        "reasons": list(match.reasons),
        "components": match.components,
    }


def build_wave3_retrieval_context(
    *,
    state: ProjectState,
    mode: str,
    user_intent: str | None = None,
    eval_records: Iterable[EvalRecord] | None = None,
    idea_batches: Iterable[IdeaBatch] | None = None,
) -> RetrievalPack:
    """Retrieve a small, inspectable Wave 3 memory pack using Retriever v2.

    V2 keeps retrieval deterministic but separates exact source evidence, semantic source
    families, material behavior and transformation operators. Every semantic family can
    score at most once per field, scores are normalized to 0-100, and weak generic matches
    are filtered before they can steer Design Brain.
    """

    query = _project_query(state, user_intent, mode)
    taste_matches = _select_taste_cards(query, state.creative_intent.difficulty_mode, limit=3)
    taste_cards = [card for _, card in taste_matches]
    taste_ids = tuple(str(card.get("id")) for card in taste_cards)
    design_context = load_design_brain_runtime_context(taste_ids)

    try:
        records = list(eval_records) if eval_records is not None else create_eval_store().list_recent(limit=40)
    except Exception:
        records = []
    evals = _select_evals(query, state.creative_intent.difficulty_mode, records)

    try:
        batches = list(idea_batches) if idea_batches is not None else create_idea_store().list_recent(limit=80)
    except Exception:
        batches = []
    shortlisted = _select_shortlisted(query, batches)
    lessons = _select_lessons(query)

    memory_sections: list[str] = [design_context]
    if evals:
        memory_sections.append(
            "WAVE 3 / HUMAN-RATED MEMORY — USE AS EVIDENCE, NOT AS OBJECT TEMPLATES:\n\n"
            + "\n\n---\n\n".join(_compact_eval(record) for _, record in evals)
        )
    if lessons:
        lesson_text = []
        for lesson in lessons:
            lesson_text.append(
                f"LESSON {lesson.get('id')}: {lesson.get('title')}\n"
                f"rule={lesson.get('rule')}\n"
                f"avoid={lesson.get('avoid')}"
            )
        memory_sections.append("WAVE 3 / CONDITIONAL LESSONS:\n\n" + "\n\n---\n\n".join(lesson_text))
    if shortlisted:
        memory_sections.append(
            "WAVE 3 / SHORTLISTED GENERATED MEMORY — INSPIRATION ONLY, NOT GROUND TRUTH:\n\n"
            + "\n\n---\n\n".join(_compact_shortlist(batch, row) for _, batch, row in shortlisted)
        )

    memory_sections.append(
        "WAVE 3 MEMORY POLICY:\n"
        "- Current source photographs and explicit user direction always outrank memory.\n"
        "- SUCCESS examples teach transferable positive relationships, not silhouettes to copy.\n"
        "- MIXED examples teach boundary conditions. FAIL examples teach warnings.\n"
        "- Shortlisted ideas are unjudged hypotheses; they may inspire but must never become training truth.\n"
        "- Match scores measure retrieval relevance only; they are never quality scores.\n"
        "- If a retrieved memory conflicts with the current source matter, ignore the memory.\n"
        "- Do not mention retrieved examples to the user; produce fresh concepts from the current source."
    )

    trace = {
        "version": "wave3_retriever_v2",
        "strategy": "deterministic_field_aware_normalized",
        "query_preview": query.text[:500],
        "query_signature": {
            "source_families": sorted(query.source_families),
            "behaviors": sorted(query.behaviors),
            "operators": sorted(query.operators),
        },
        "taste_cards": [
            {
                "id": card.get("id"),
                "title": card.get("title"),
                "operator": card.get("operator"),
                **_trace_match(match),
            }
            for match, card in taste_matches
        ],
        "evals": [
            {
                "eval_id": record.eval_id,
                "outcome": record.outcome,
                "candidate_name": record.candidate_name,
                **_trace_match(match),
            }
            for match, record in evals
        ],
        "lessons": [{"id": lesson.get("id"), "title": lesson.get("title")} for lesson in lessons],
        "shortlisted_ideas": [
            {
                "batch_id": batch.batch_id,
                "candidate_id": (row.get("candidate") or {}).get("candidate_id") if isinstance(row.get("candidate"), dict) else None,
                "name": (row.get("candidate") or {}).get("name") if isinstance(row.get("candidate"), dict) else None,
                **_trace_match(match),
            }
            for match, batch, row in shortlisted
        ],
    }
    return RetrievalPack(prompt_context="\n\n".join(memory_sections), trace=trace)
