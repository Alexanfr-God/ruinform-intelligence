from __future__ import annotations

from .future_models import ReviewedFuture, VisualBrief
from .models import ProjectState
from .render_models import RenderReference, RenderRequest


def _source_references(state: ProjectState, future: ReviewedFuture) -> list[RenderReference]:
    material_ids = {use.material_item_id for use in future.candidate.material_uses}
    evidence_to_materials: dict[str, set[str]] = {}
    for material in state.materials:
        if material.item_id not in material_ids:
            continue
        for observation in material.observations:
            for ref in observation.evidence:
                evidence_to_materials.setdefault(ref.evidence_id, set()).add(material.item_id)

    refs: list[RenderReference] = []
    seen: set[str] = set()
    for evidence in state.evidence:
        if evidence.source_type != "image" or not evidence.uri or evidence.evidence_id in seen:
            continue
        linked = sorted(evidence_to_materials.get(evidence.evidence_id, set()))
        if linked or not evidence_to_materials:
            refs.append(
                RenderReference(
                    evidence_id=evidence.evidence_id,
                    image_url=evidence.uri,
                    material_item_id=linked[0] if len(linked) == 1 else None,
                    note="source material evidence",
                )
            )
            seen.add(evidence.evidence_id)
    return refs


def compile_render_request(
    *,
    state: ProjectState,
    future: ReviewedFuture,
    aspect_ratio: str = "4:5",
) -> RenderRequest:
    brief = future.visual_brief
    if brief is None:
        raise ValueError("Reviewed future has no VisualBrief")
    if future.review.status != "pass":
        raise ValueError("Only passed futures may be rendered")

    prompt = _compile_visual_prompt(brief)
    return RenderRequest(
        candidate_id=future.candidate.candidate_id,
        prompt=prompt,
        negative_constraints=list(brief.forbidden_inventions),
        references=_source_references(state, future),
        aspect_ratio=aspect_ratio,
    )


def _compile_visual_prompt(brief: VisualBrief) -> str:
    material_lines = "\n".join(
        f"- {trace.material_item_id}: {trace.intended_location}; preserve {trace.source_character_to_preserve}; "
        f"constraints: {', '.join(trace.appearance_constraints) or 'none'}"
        for trace in brief.material_traces
    )
    return (
        f"RUINFORM FUTURE FORM — {brief.title}\n\n"
        f"Object: {brief.object_summary}\n"
        f"Silhouette: {brief.silhouette}\n"
        f"Geometry: {'; '.join(brief.geometry_notes)}\n"
        f"Source material mapping:\n{material_lines}\n"
        f"Visible connections: {'; '.join(brief.visible_connections)}\n"
        f"Composition: {brief.composition}\n"
        f"Camera: {brief.camera}\n"
        f"Lighting: {brief.lighting}\n"
        f"Environment: {brief.environment}\n"
        f"Provenance cues: {'; '.join(brief.provenance_cues)}\n"
        f"Keep ambiguous: {'; '.join(brief.unknowns_to_keep_ambiguous) or 'none'}\n\n"
        "Create a photorealistic concept visualization, not engineering proof. "
        "The object must visibly preserve the identity and surface character of the supplied source matter."
    )
