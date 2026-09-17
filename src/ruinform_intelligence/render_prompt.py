from __future__ import annotations

from .future_models import ReviewedFuture, VisualBrief
from .models import ProjectState
from .render_director import VisualDirection, fallback_visual_direction, select_render_mode
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
    direction: VisualDirection | None = None,
    aspect_ratio: str = "4:5",
) -> RenderRequest:
    """Compile the concept-stage render from candidate + Visual Director hierarchy."""

    candidate = future.candidate
    direction = direction or fallback_visual_direction(
        state=state,
        future=future,
        render_mode=select_render_mode(future),
    )
    material_by_id = {item.item_id: item for item in state.materials}

    role_by_id: dict[str, str] = {}
    for use in candidate.material_uses:
        role_by_id[use.material_item_id] = use.role

    def label(material_id: str) -> str:
        item = material_by_id.get(material_id)
        return item.display_name if item is not None else material_id

    hero_label = label(direction.hero_material_id)
    hierarchy_lines = [f"HERO — {hero_label}: dominant visual anchor; {direction.hero_object}."]
    for material_id in direction.secondary_material_ids:
        hierarchy_lines.append(
            f"SECONDARY — {label(material_id)}: support the hero; never dominate or hide it; candidate role: {role_by_id.get(material_id, 'support')}."
        )
    for material_id in direction.accent_material_ids:
        hierarchy_lines.append(
            f"ACCENT — {label(material_id)}: use sparingly as rhythm/detail/illumination; candidate role: {role_by_id.get(material_id, 'accent')}."
        )

    source_lines: list[str] = []
    for use in candidate.material_uses:
        material = material_by_id.get(use.material_item_id)
        material_label = material.display_name if material is not None else use.material_item_id
        source_lines.append(
            f"- {material_label} ({use.material_item_id}): use as {use.role}. Preserve recognizable color, texture, wear, major geometry and source identity."
        )

    operations = "; ".join(candidate.key_operations) or "Use simple physically legible assembly operations."
    additions = "; ".join(candidate.added_materials) or "No significant added materials."
    unresolved = "; ".join(candidate.unresolved_dependencies) or "Ordinary scale-to-fit assumptions only."
    keep = "\n".join(f"- {item}" for item in direction.must_keep)

    mode_instruction = {
        "art_object": (
            "Present it as gallery-grade contemporary design art: one authored sculptural gesture, strong negative space, "
            "clean silhouette, restrained drama, no craft clutter."
        ),
        "design_product": (
            "Present it as a premium limited-edition collectible design object: resolved, desirable, visually disciplined, "
            "design-fair quality, polished product-art photography."
        ),
        "realistic_prototype": (
            "Present it as a beautiful but believable maker prototype: physically legible assembly, minimal additions, "
            "honest joins, workshop plausibility without looking crude."
        ),
    }[direction.render_mode]

    prompt = (
        f"RUINFORM VISUAL DIRECTOR / {direction.render_mode.upper()}\n\n"
        f"OBJECT TYPE: {direction.object_type}\n"
        f"VISUAL THESIS: {direction.visual_thesis}\n"
        f"SIGNATURE GESTURE: {direction.signature_gesture}\n"
        f"SILHOUETTE: {direction.silhouette}\n\n"
        "VISUAL HIERARCHY — non-negotiable:\n"
        + "\n".join(hierarchy_lines)
        + "\n\nSOURCE MATTER — preserve these supplied references faithfully:\n"
        + "\n".join(source_lines)
        + "\n\n"
        f"CANDIDATE INTENT: {candidate.one_line}\n"
        f"ARTISTIC THESIS: {candidate.artistic_thesis}\n"
        f"TRANSFORMATION LOGIC: {candidate.transformation_logic}\n"
        f"PHYSICAL OPERATIONS: {operations}\n"
        f"ALLOWED SIMPLE ADDITIONS: {additions}\n"
        f"KEEP UNRESOLVED RATHER THAN FAKING: {unresolved}\n\n"
        f"COMPOSITION: {direction.composition}\n"
        f"CAMERA: {direction.camera}\n"
        f"LIGHTING: {direction.lighting}\n"
        f"ENVIRONMENT: {direction.environment}\n\n"
        f"MODE DIRECTION: {mode_instruction}\n\n"
        "MUST KEEP:\n"
        f"{keep}\n\n"
        "Create ONE finished photorealistic object. The result must be understandable in one second. "
        "It must feel intentionally designed, not like a list of source objects pasted together. "
        "Protect the hero object from being swallowed by secondary material. "
        "Use secondary matter to frame, support, wrap, cradle, punctuate or structurally transform the hero according to the thesis. "
        "Use accents with restraint. Every visible part must strengthen the same central idea. "
        "Preserve provenance so the real source matter remains recognizable. "
        "Use material-specific reflections, folds, seams, thickness, translucency and wear. "
        "Do not add labels, captions, logos, plaques, generated text or decorative storytelling props. "
        "Exact dimensions may be visually approximated for concept exploration only."
    )

    negative_constraints = [
        *direction.must_avoid,
        "Do not invent additional major source objects that were not supplied.",
        "Do not turn one coherent object into several competing objects or accessories.",
        "Do not hide the hero material behind a completely unrelated shell or oversized secondary element.",
        "Do not use magical seamless fusion, floating unsupported parts, or impossible geometry.",
        "Do not add random straps, pouches, bags, devices, cables, stands, handles, mannequins, or hardware unless explicitly required by the visual direction or candidate.",
        "Do not imply tested electrical, heat, load, structural, or safety certification.",
        "Do not generate text, logos, labels, plaques, watermarks, or product copy inside the image.",
        "Do not use a generic craft-collage aesthetic; make one authored design statement.",
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
