from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Iterable

from .eval_models import EvalRecord
from .eval_store import create_eval_store
from .idea_store import IdeaBatch, create_idea_store
from .models import ProjectState
from .taste_library import TasteLibraryError, _read_json, load_design_brain_runtime_context, load_taste_card_catalog


_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "but", "by", "for", "from", "in", "into",
    "is", "it", "of", "on", "or", "the", "to", "use", "using", "with", "without", "object",
    "source", "material", "create", "make", "keep", "real", "simple", "new", "one", "this", "that",
    "more", "less", "very", "main", "visual", "art", "artwork", "thing", "parts", "part",
}

# Small material/action synonym graph. This is intentionally transparent and deterministic.
# When the library grows beyond a few dozen cards this layer can be supplemented by embeddings
# without changing the public retrieval contract.
_SYNONYM_GROUPS = [
    {"wood", "wooden", "timber", "board", "boards", "plank", "planks", "log", "branch", "branches", "bark", "tree"},
    {"metal", "steel", "iron", "wire", "rod", "rods", "bolt", "bolts", "nut", "nuts", "washer", "washers", "fastener", "fasteners", "screw", "screws"},
    {"light", "lighting", "lamp", "bulb", "led", "flashlight", "illuminated", "glow", "luminous", "shadow"},
    {"glass", "bottle", "jar", "vessel", "transparent", "translucent", "diffuser", "acrylic"},
    {"fabric", "textile", "plush", "cord", "rope", "thread", "line", "string", "soft"},
    {"frame", "picture", "print", "poster", "panel", "canvas", "wall"},
    {"move", "moving", "kinetic", "pivot", "rotate", "rotation", "hinge", "lever", "slider", "slide", "pull", "control", "balance"},
    {"cut", "cutting", "remove", "carve", "open", "split", "reveal", "void", "negative", "space"},
    {"repeat", "repetition", "array", "stack", "stacked", "sequence", "rhythm", "multiple"},
    {"bend", "bending", "curve", "curved", "coil", "spring", "loop", "wrap", "wrapped", "flexible"},
    {"functional", "utility", "useful", "function", "holder", "stand", "support", "shelf"},
    {"sculpture", "sculptural", "figure", "figurative", "character", "portrait", "silhouette"},
]


@dataclass(frozen=True)
class RetrievalPack:
    prompt_context: str
    trace: dict[str, Any]


def _tokenize(value: str | None) -> set[str]:
    if not value:
        return set()
    words = set(re.findall(r"[a-zA-Z0-9_]+", value.lower().replace("-", " ")))
    words = {word for word in words if len(word) > 2 and word not in _STOPWORDS}
    expanded = set(words)
    for group in _SYNONYM_GROUPS:
        if words & group:
            expanded.update(group)
    return expanded


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


def _project_query(state: ProjectState, user_intent: str | None, mode: str) -> tuple[str, set[str]]:
    pieces: list[str] = [mode, state.creative_intent.difficulty_mode, state.creative_intent.direction or "", user_intent or ""]
    for material in state.materials:
        pieces.append(material.display_name)
        for observation in material.observations:
            pieces.append(observation.label)
    pieces.extend(state.constraints.tools_available)
    pieces.extend(state.constraints.skills)
    text = " | ".join(piece for piece in pieces if piece)
    return text, _tokenize(text)


def _overlap_score(query_tokens: set[str], text: str, weight: float = 1.0) -> float:
    if not query_tokens:
        return 0.0
    return weight * len(query_tokens & _tokenize(text))


def _select_taste_cards(query_tokens: set[str], difficulty: str, *, limit: int = 3) -> list[dict[str, Any]]:
    catalog = list(load_taste_card_catalog())
    light_query = bool(query_tokens & _tokenize("light lamp led bulb flashlight shadow illuminated"))
    scored: list[tuple[float, str, dict[str, Any]]] = []
    for card in catalog:
        score = 0.0
        score += _overlap_score(query_tokens, _flatten_text(card.get("tags")), 3.0)
        score += _overlap_score(query_tokens, _flatten_text(card.get("materials")), 2.5)
        score += _overlap_score(query_tokens, _flatten_text(card.get("summary")), 1.7)
        score += _overlap_score(query_tokens, _flatten_text(card.get("learn")), 1.2)
        score += _overlap_score(query_tokens, _flatten_text(card.get("operator")), 1.5)
        score += _overlap_score(query_tokens, _flatten_text(card.get("core_formula")), 1.0)
        card_difficulty = str(card.get("difficulty", "")).lower()
        if difficulty in card_difficulty:
            score += 1.25
        card_text = _flatten_text(card)
        if not light_query and _tokenize(card_text) & _tokenize("lamp light lighting bulb led"):
            score -= 1.0
        # Stable tie-break by card id keeps tests deterministic.
        scored.append((score, str(card.get("id", "")), card))

    scored.sort(key=lambda row: (-row[0], row[1]))
    # Even when lexical overlap is weak, three different operators are still more useful
    # than dumping the entire library into Design Brain.
    return [row[2] for row in scored[: max(2, min(4, limit))]]


def _eval_text(record: EvalRecord) -> str:
    candidate = record.concept_snapshot or {}
    return " | ".join(
        [
            " ".join(record.source_items),
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


def _select_evals(query_tokens: set[str], difficulty: str, records: Iterable[EvalRecord]) -> list[tuple[float, EvalRecord]]:
    buckets: dict[str, list[tuple[float, EvalRecord]]] = {"success": [], "mixed": [], "fail": []}
    for record in records:
        source_score = _overlap_score(query_tokens, " ".join(record.source_items), 4.0)
        concept_score = _overlap_score(query_tokens, _eval_text(record), 1.25)
        difficulty_bonus = 0.75 if record.difficulty_mode == difficulty else 0.0
        score = source_score + concept_score + difficulty_bonus
        if score <= 0:
            continue
        buckets[record.outcome].append((score, record))

    selected: list[tuple[float, EvalRecord]] = []
    # Human labels are not a leaderboard. Retrieve the strongest relevant example from
    # each outcome so Design Brain sees positive patterns, boundaries and warnings.
    for outcome in ("success", "mixed", "fail"):
        rows = sorted(buckets[outcome], key=lambda row: (-row[0], row[1].created_at_iso))
        if rows:
            selected.append(rows[0])
    return sorted(selected, key=lambda row: -row[0])[:3]


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


def _select_shortlisted(query_tokens: set[str], batches: Iterable[IdeaBatch]) -> list[tuple[float, IdeaBatch, dict[str, Any]]]:
    scored: list[tuple[float, IdeaBatch, dict[str, Any]]] = []
    for batch in batches:
        source_score = _overlap_score(query_tokens, " ".join(batch.source_items), 3.0)
        for row in _shortlisted_rows(batch):
            candidate = row.get("candidate", {})
            candidate_text = _flatten_text(candidate)
            score = source_score + _overlap_score(query_tokens, candidate_text, 1.0)
            if score > 0:
                scored.append((score, batch, row))
    scored.sort(key=lambda row: (-row[0], row[1].created_at_iso))
    return scored[:2]


def _load_lessons() -> list[dict[str, Any]]:
    data = _read_json("docs/WAVE3_RETRIEVAL_RULES.json")
    lessons = data.get("lessons") if isinstance(data, dict) else None
    return [lesson for lesson in lessons or [] if isinstance(lesson, dict)]


def _select_lessons(query_tokens: set[str]) -> list[dict[str, Any]]:
    scored: list[tuple[int, dict[str, Any]]] = []
    for lesson in _load_lessons():
        cue_tokens = _tokenize(_flatten_text(lesson.get("cues")))
        overlap = len(query_tokens & cue_tokens)
        if overlap:
            scored.append((overlap, lesson))
    scored.sort(key=lambda row: (-row[0], str(row[1].get("id", ""))))
    return [row[1] for row in scored[:2]]


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


def build_wave3_retrieval_context(
    *,
    state: ProjectState,
    mode: str,
    user_intent: str | None = None,
    eval_records: Iterable[EvalRecord] | None = None,
    idea_batches: Iterable[IdeaBatch] | None = None,
) -> RetrievalPack:
    """Retrieve a small, inspectable memory pack for one concept-generation request.

    Design Brain receives only 2-4 Taste cards plus the most relevant human-rated
    examples, conditional lessons and shortlisted hypotheses. Retrieval is intentionally
    deterministic in v1 so we can audit why a memory was selected before adding semantic
    embeddings at larger library scale.
    """

    query_text, query_tokens = _project_query(state, user_intent, mode)
    taste_cards = _select_taste_cards(query_tokens, state.creative_intent.difficulty_mode, limit=3)
    taste_ids = tuple(str(card.get("id")) for card in taste_cards)
    design_context = load_design_brain_runtime_context(taste_ids)

    try:
        records = list(eval_records) if eval_records is not None else create_eval_store().list_recent(limit=40)
    except Exception:
        records = []
    evals = _select_evals(query_tokens, state.creative_intent.difficulty_mode, records)

    try:
        batches = list(idea_batches) if idea_batches is not None else create_idea_store().list_recent(limit=80)
    except Exception:
        batches = []
    shortlisted = _select_shortlisted(query_tokens, batches)
    lessons = _select_lessons(query_tokens)

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
        "- If a retrieved memory conflicts with the current source matter, ignore the memory.\n"
        "- Do not mention retrieved examples to the user; produce fresh concepts from the current source."
    )

    trace = {
        "version": "wave3_retriever_v1",
        "strategy": "deterministic_hybrid_lexical",
        "query_preview": query_text[:500],
        "taste_cards": [
            {"id": card.get("id"), "title": card.get("title"), "operator": card.get("operator")}
            for card in taste_cards
        ],
        "evals": [
            {"eval_id": record.eval_id, "outcome": record.outcome, "candidate_name": record.candidate_name, "score": round(score, 2)}
            for score, record in evals
        ],
        "lessons": [{"id": lesson.get("id"), "title": lesson.get("title")} for lesson in lessons],
        "shortlisted_ideas": [
            {
                "batch_id": batch.batch_id,
                "candidate_id": (row.get("candidate") or {}).get("candidate_id") if isinstance(row.get("candidate"), dict) else None,
                "name": (row.get("candidate") or {}).get("name") if isinstance(row.get("candidate"), dict) else None,
                "score": round(score, 2),
            }
            for score, batch, row in shortlisted
        ],
    }
    return RetrievalPack(prompt_context="\n\n".join(memory_sections), trace=trace)
