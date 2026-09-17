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


def compile_preview_render_request(
    *,
    state: ProjectState,
    future: ReviewedFuture,
    aspect_ratio: str = "4:5",
) -> RenderRequest:
    """Compile the fast concept-stage render without another LLM round-trip.

    Concept Preview is intentionally visual-first. The selected candidate already contains
    enough structured design intent for a strong image prompt, so we avoid generating a
    separate VisualBrief and avoid blocking on a render critic before the user has even
    decided whether the visual direction is worth pursuing.
    """

    candidate = future.candidate
    material_by_id = {item.item_id: item for item in state.materials}
    material_lines: list[str] = []
    for use in candidate.material_uses:
        material = material_by_id.get(use.material_item_id)
        label = material.display_name if material is not None else use.material_item_id
        material_lines.append(
            f"- {label}: use as {use.role}. Preserve recognizable source color, texture, wear, and identity."
        )

    operations = "; ".join(candidate.key_operations) or "Use simple physically legible assembly operations."
    additions = "; ".join(candidate.added_materials) or "No significant added materials."
    unresolved = "; ".join(candidate.unresolved_dependencies) or "Ordinary scale-to-fit assumptions only."

    prompt = (
        f"RUINFORM CONCEPT VISUALIZATION — {candidate.name}\n\n"
        f"Design intent: {candidate.one_line}\n"
        f"Artistic thesis: {candidate.artistic_thesis}\n"
        f"Transformation: {candidate.transformation_logic}\n\n"
        "SOURCE MATTER — preserve these supplied references faithfully:\n"
        + "\n".join(material_lines)
        + "\n\n"
        f"Physical operations: {operations}\n"
        f"Allowed simple additions: {additions}\n"
        f"Keep unresolved rather than pretending verified: {unresolved}\n\n"
        "Create ONE finished, photorealistic object that is immediately understandable from a single hero image. "
        "The result must look like a real object assembled from the supplied matter, not a collage, not loose items placed next to one another, and not an impossible seamless morph. "
        "Use visible, believable joins, folds, clips, stitching, wraps, fasteners, bases, or cable routing when relevant. "
        "Preserve obvious provenance: viewers should still recognize where the source materials came from. "
        "Aim for a strong contemporary collectible-design / maker-art result while keeping the construction visually plausible. "
        "Use a clean dark or warm workshop/gallery environment, cinematic product lighting, realistic material texture, and a confident centered composition. "
        "Do not add labels, captions, logos, plaques, or generated text. "
        "Exact dimensions may be visually approximated for concept exploration only."
    )

    negative_constraints = [
        "Do not invent additional major source objects that were not supplied.",
        "Do not hide the source materials behind a completely unrelated shell.",
        "Do not use magical seamless fusion, floating unsupported parts, or impossible geometry.",
        "Do not imply tested electrical, heat, load, structural, or safety certification.",
        "Do not generate text, logos, labels, plaques, watermarks, or product copy inside the image.",
    ]

    return RenderRequest(
        candidate_id=candidate.candidate_id,
        prompt=prompt,
        negative_constraints=negative_constraints,
        references=_source_references(state, future),
        aspect_ratio=aspect_ratio,
    )


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
