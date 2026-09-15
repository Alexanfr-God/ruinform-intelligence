from __future__ import annotations

import json

from .models import ProjectState


def compact_state_json(state: ProjectState) -> str:
    """Serialize physical state for text reasoning without repeating base64 image payloads.

    Image evidence remains addressable by evidence_id and stays intact in ProjectState for
    multimodal review/rendering. Text-only specialist agents need the provenance reference,
    not hundreds of kilobytes of duplicated image bytes on every call.
    """
    payload = state.model_dump(mode="json")
    for evidence in payload.get("evidence", []):
        if evidence.get("source_type") == "image" and evidence.get("uri"):
            evidence["uri"] = f"<image evidence retained: {evidence.get('evidence_id', 'unknown')}>"
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
