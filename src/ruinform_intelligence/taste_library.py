from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any


class TasteLibraryError(RuntimeError):
    pass


def _project_roots() -> list[Path]:
    roots: list[Path] = []
    override = os.getenv("RUINFORM_PROJECT_ROOT")
    if override:
        roots.append(Path(override))
    roots.extend(
        [
            Path.cwd(),
            Path(__file__).resolve().parents[2],
        ]
    )
    unique: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        resolved = root.expanduser().resolve()
        key = str(resolved)
        if key not in seen:
            seen.add(key)
            unique.append(resolved)
    return unique


def _resolve(relative_path: str) -> Path:
    checked: list[str] = []
    for root in _project_roots():
        path = (root / relative_path).resolve()
        checked.append(str(path))
        if path.is_file():
            return path
    raise TasteLibraryError(
        f"RUINFORM knowledge file {relative_path!r} was not found. Checked: "
        + ", ".join(checked)
    )


def _read_text(relative_path: str) -> str:
    return _resolve(relative_path).read_text(encoding="utf-8")


def _read_json(relative_path: str) -> Any:
    try:
        return json.loads(_read_text(relative_path))
    except json.JSONDecodeError as exc:
        raise TasteLibraryError(f"Invalid JSON in {relative_path}") from exc


def _compact_card(card: dict[str, Any]) -> str:
    learn = card.get("learn") or []
    avoid = card.get("avoid") or []
    tags = card.get("tags") or []
    parts = [
        f"CARD {card.get('id', 'unknown')}: {card.get('title', '')}",
        f"operator={card.get('operator_label') or card.get('operator', '')}",
        f"core_lesson={card.get('core_lesson', '')}",
    ]
    secondary = card.get("secondary_lesson")
    if secondary:
        parts.append(f"secondary_lesson={secondary}")
    summary = card.get("summary")
    if summary:
        parts.append(f"summary={summary}")
    if learn:
        parts.append("learn=" + " | ".join(str(value) for value in learn[:3]))
    if avoid:
        parts.append("do_not_copy=" + " | ".join(str(value) for value in avoid[:3]))
    if tags:
        parts.append("tags=" + ", ".join(str(value) for value in tags[:8]))
    return "\n".join(parts)


@lru_cache(maxsize=1)
def load_taste_card_catalog() -> tuple[dict[str, Any], ...]:
    """Load the canonical Taste Library as structured cards for the Wave 3 retriever."""

    index = _read_json("docs/TASTE_LIBRARY/index.json")
    entries = index.get("cards") if isinstance(index, dict) else None
    if not isinstance(entries, list) or not entries:
        raise TasteLibraryError("Taste Library index contains no cards")

    cards: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict) or not entry.get("path"):
            continue
        card = _read_json("docs/TASTE_LIBRARY/" + str(entry["path"]))
        if isinstance(card, dict):
            cards.append(card)
    if not cards:
        raise TasteLibraryError("Taste Library could not load any concept cards")
    return tuple(cards)


@lru_cache(maxsize=32)
def load_design_brain_runtime_context(card_ids: tuple[str, ...] | None = None) -> str:
    """Return compact live RUINFORM knowledge for concept generation.

    ``card_ids=None`` preserves the legacy behavior and loads all cards. Wave 3 passes a
    small retrieved set, normally 2-4 cards, so Design Brain never needs to see the whole
    growing library at once.
    """

    if os.getenv("RUINFORM_TASTE_LIBRARY_ENABLED", "1").strip().lower() in {
        "0",
        "false",
        "no",
        "off",
    }:
        return "TASTE LIBRARY: disabled by RUINFORM_TASTE_LIBRARY_ENABLED."

    skill = _read_text("skills/ruinform-design-brain/SKILL.md")
    style = _read_text("docs/RUINFORM_STYLE_BIBLE.md")
    grammar = _read_text("docs/TASTE_LIBRARY/DESIGN_GRAMMAR.md")
    catalog = load_taste_card_catalog()

    if card_ids is None:
        selected = list(catalog)
        selection_label = f"ALL {len(selected)} CARDS / LEGACY MODE"
    else:
        by_id = {str(card.get("id")): card for card in catalog}
        selected = [by_id[card_id] for card_id in card_ids if card_id in by_id]
        selection_label = f"RETRIEVED {len(selected)} OF {len(catalog)} CARDS"

    cards = [_compact_card(card) for card in selected]
    if not cards:
        raise TasteLibraryError("Taste Library retrieval selected no valid concept cards")

    return (
        "RUINFORM LIVE KNOWLEDGE PACK\n"
        "============================\n\n"
        "REUSABLE DESIGN-BRAIN SKILL:\n"
        + skill
        + "\n\nRUINFORM STYLE BIBLE:\n"
        + style
        + "\n\nDESIGN GRAMMAR:\n"
        + grammar
        + f"\n\nTASTE CARD SELECTION: {selection_label}\n"
        + "TASTE CARDS — TRANSFER OPERATORS, NEVER COPY OBJECTS:\n\n"
        + "\n\n---\n\n".join(cards)
        + "\n\nTASTE LIBRARY USAGE POLICY:\n"
        "- Source photographs and user intent outrank all examples.\n"
        "- Taste cards teach ways of thinking, not silhouettes, materials, categories, or styling recipes.\n"
        "- Never reproduce a card's exact object unless the source matter independently demands it.\n"
        "- Do not default to lighting just because several cards happen to be lamps.\n"
        "- Across the four concepts, use genuinely different operator families or combinations.\n"
        "- Unless the user explicitly requests lighting, normally return at least two non-lighting concepts.\n"
        "- The goal is transfer: apply an operator to the user's matter in a way not present in the library.\n"
    )
