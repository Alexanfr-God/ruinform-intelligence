from __future__ import annotations

from .future_models import ReviewedFuture, VisualBrief
from .models import ProjectState
from .render_director import VisualDirection, fallback_visual_direction, select_render_mode
from .render_models import RenderReference, RenderRequest


_BRANCH_PARENT_EVIDENCE_ID = "branch_parent_future"


def _has_locked_parent(state: ProjectState) -> bool:
    return any(
        evidence.evidence_id == _BRANCH_PARENT_EVIDENCE_ID
        and evidence.source_type == "image"
        and bool(evidence.uri)
        for evidence in state.evidence
    )


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
        is_locked_parent = evidence.evidence_id == _BRANCH_PARENT_EVIDENCE_ID
        if is_locked_parent or linked or not evidence_to_materials:
            refs.append(
                RenderReference(
                    evidence_id=evidence.evidence_id,
                    image_url=evidence.uri,
                    material_item_id=linked[0] if len(linked) == 1 else None,
                    note=(
                        "locked parent future design reference; preserve form ancestry, not a newly supplied material"
                        if is_locked_parent
                        else "source material evidence"
                    ),
                )
            )
            seen.add(evidence.evidence_id)
    return refs


def _background_render_instruction(state: ProjectState) -> str:
    if state.creative_intent.background_mode == "ruinform_world":
        return (
            "RUINFORM WORLD / POST-APOCALYPTIC PRESENTATION: Keep the finished art object as at least 70% of the visual attention. "
            "Place it in a restrained salvage-luxury post-consumer setting: reclaimed workshop, recovery gallery, weathered concrete/metal/wood, "
            "honest wear, subtle dust and cinematic directional light. The environment must support the object's story, never supply the missing idea. "
            "No generic cyberpunk RGB, fantasy ruins, random weapons, gas masks, warning signs, mannequins, or excessive apocalypse props."
        )
    return (
        "CLEAN STUDIO PRESENTATION: Use a neutral contemporary studio/gallery background, simple surface, controlled editorial light and minimal visual noise. "
        "No ruins, workshop clutter, smoke, post-apocalyptic props, fake signage or scenic storytelling. The object alone must earn the WOW."
    )


def _difficulty_render_instruction(state: ProjectState) -> str:
    mode = state.creative_intent.difficulty_mode
    if mode == "easy":
        return (
            "EASY BUILD LANGUAGE: keep supporting hardware extremely restrained and visually obvious in function. Prefer 0-2 simple additions, household/basic hand-tool logic, "
            "reversible clamps/ties/simple joins where possible, and no unnecessary specialist mechanism."
        )
    if mode == "wild":
        return (
            "WILD BUILD LANGUAGE: more radical geometry and specialist fabrication may appear if the selected concept genuinely requires it, but every added component must have a clear structural or functional role. "
            "Do not let invented hardware overwhelm the supplied objects."
        )
    return (
        "MEDIUM BUILD LANGUAGE: allow workshop-level drilling/cutting/bending/clamping and roughly 0-4 supporting parts when needed. Keep the assembly legible and source-driven rather than turning it into a dense prop."
    )


def compile_preview_render_request(
    *,
    state: ProjectState,
    future: ReviewedFuture,
    direction: VisualDirection | None = None,
    aspect_ratio: str = "4:5",
) -> RenderRequest:
    """Compile the concept-stage render from candidate + high-taste Visual Director."""

    candidate = future.candidate
    direction = direction or fallback_visual_direction(
        state=state,
        future=future,
        render_mode=select_render_mode(future),
    )
    branch_mode = _has_locked_parent(state)
    material_by_id = {item.item_id: item for item in state.materials}
    role_by_id = {use.material_item_id: use.role for use in candidate.material_uses}

    def label(material_id: str) -> str:
        item = material_by_id.get(material_id)
        return item.display_name if item is not None else material_id

    if branch_mode:
        hierarchy_lines = [
            "HERO / DESIGN ANCESTOR — LOCKED PARENT FUTURE: this existing authored object remains the visual hero. "
            "Preserve at least two recognizable identity anchors while allowing local geometry, path, topology and attachment logic to evolve."
        ]
        for use in candidate.material_uses:
            hierarchy_lines.append(
                f"ACTIVE BRANCH MATTER — {label(use.material_item_id)}: transform and use it to CAUSE the descendant's evolution; "
                f"candidate role: {role_by_id.get(use.material_item_id, use.role)}. Its provenance should remain legible, but its intact stock silhouette is NOT sacred."
            )
        priority_hero = (
            "LOCKED PARENT FUTURE / DESIGN ANCESTOR — keep the inherited object recognizable; "
            "the active branch matter changes what it does or how its geometry/path reads"
        )
    else:
        hierarchy_lines = [
            f"HERO — {label(direction.hero_material_id)}: {direction.hero_object}. Keep it visually dominant and unmistakable."
        ]
        for material_id in direction.secondary_material_ids:
            hierarchy_lines.append(
                f"SECONDARY — {label(material_id)}: actively transform/support the hero; never become a generic base or hide it; "
                f"candidate role: {role_by_id.get(material_id, 'support')}."
            )
        for material_id in direction.accent_material_ids:
            hierarchy_lines.append(
                f"ACCENT — {label(material_id)}: use sparingly to reinforce the signature gesture; candidate role: {role_by_id.get(material_id, 'accent')}."
            )
        priority_hero = direction.hero_object

    source_lines: list[str] = []
    for use in candidate.material_uses:
        material = material_by_id.get(use.material_item_id)
        material_label = material.display_name if material is not None else use.material_item_id
        if branch_mode:
            source_lines.append(
                f"- {material_label} ({use.material_item_id}): preserve recognizable material provenance — color, texture, wear, thickness and characteristic surface/edge cues — "
                "but ALLOW believable cutting, bending, slitting, drilling, folding, splitting, flattening, re-forming or sub-part reuse when the candidate operations call for it. "
                "Do not default to showing this item as an untouched stock object."
            )
        else:
            source_lines.append(
                f"- {material_label} ({use.material_item_id}): preserve recognizable color, texture, seams, wear, thickness, geometry and source identity."
            )

    operations = "; ".join(candidate.key_operations) or "Use simple physically legible assembly operations."
    operation_contract = "\n".join(
        f"- OPERATION {index:02d}: {operation}"
        for index, operation in enumerate(candidate.key_operations, start=1)
    ) or "- Use simple physically legible assembly operations."
    additions = "; ".join(candidate.added_materials) or "No significant added materials."
    unresolved = "; ".join(candidate.unresolved_dependencies) or "Ordinary scale-to-fit assumptions only."
    keep = "\n".join(f"- {item}" for item in direction.must_keep)
    authorship = "\n".join(f"- {item}" for item in direction.authorship_cues)

    branch_contract = ""
    if branch_mode:
        branch_contract = (
            "BRANCH EVOLUTION CONTRACT — HARD PRIORITY:\n"
            "- The locked parent-future reference is the EXISTING authored object and visual ancestor, not raw material inventory.\n"
            "- Preserve at least TWO strong parent identity anchors: signature gesture, function, conceptual tension, silhouette cue, negative space or distinctive part relationship.\n"
            "- Current candidate materials are NEW ACTIVE MATTER only. Historical objects visible inside the parent reference are unavailable unless they also exist as current material IDs.\n"
            "- New matter may be cut, bent, slit, drilled, opened, split, folded, flattened, re-formed or used by evidenced sub-part when physically plausible.\n"
            "- New matter must CAUSE a visible evolution in structure, path/force, function, silhouette, negative space, interaction, material tension or meaning.\n"
            "- REMOVAL TEST: if deleting the new matter would leave essentially the same parent object, the render has FAILED.\n"
            "- GENERIC SUBSTITUTE TEST: if any generic plate/ring/patch could replace the new matter without changing the idea, the render has FAILED.\n"
            "- Do not solve the branch by placing the new item intact behind, beside, under, on top of, or as a badge/backing plate on the parent.\n"
            "- Preserve material provenance, NOT necessarily the new object's original intact silhouette.\n\n"
        )

    mode_instruction = {
        "art_object": (
            "Gallery-grade contemporary collectible art. Prefer one bold sculptural move, material tension, negative space and a silhouette "
            "that is memorable without relying on a pedestal, fog or generic RGB decoration."
        ),
        "design_product": (
            "Premium limited-edition design object with strong authorship and disciplined details. It should feel resolved and desirable, "
            "but not like a generic luxury product render."
        ),
        "realistic_prototype": (
            "Beautiful and physically believable maker prototype with one strong formal idea, honest joins and visible assembly logic. "
            "Buildable must not mean visually ordinary."
        ),
    }[direction.render_mode]

    prompt = (
        f"RUINFORM HIGH-TASTE VISUAL / {direction.render_mode.upper()}\n\n"
        "PERSISTENT PROJECT CONTROLS:\n"
        f"CREATIVE DIRECTION: {state.creative_intent.direction or 'open exploration'}\n"
        f"DIFFICULTY: {state.creative_intent.difficulty_mode.upper()}\n"
        f"{_difficulty_render_instruction(state)}\n"
        f"{_background_render_instruction(state)}\n\n"
        + branch_contract
        + "ABSOLUTE PRIORITY:\n"
        f"1. HERO: {priority_hero}\n"
        f"2. VISUAL THESIS: {direction.visual_thesis}\n"
        f"3. CONCEPTUAL TENSION: {direction.conceptual_tension}\n"
        f"4. MATERIAL RELATIONSHIP: {direction.material_relationship}\n"
        f"5. SIGNATURE GESTURE: {direction.signature_gesture}\n"
        f"6. REJECT THIS ORDINARY SOLUTION: {direction.ordinary_solution_to_reject}\n\n"
        "The final image must make the signature gesture obvious within one second. If the result can be described as merely stacked, sleeved, "
        "evenly wrapped, symmetrically decorated, or 'LED added to object', it has failed the brief.\n\n"
        "SOURCE HIERARCHY:\n"
        + "\n".join(hierarchy_lines)
        + "\n\nSOURCE IMAGE FIDELITY:\n"
        + "\n".join(source_lines)
        + "\n\n"
        "SELECTED FUTURE CONSTRUCTION CONTRACT — HIGH PRIORITY:\n"
        f"{operation_contract}\n"
        "Every listed operation that has a visible physical consequence must be legible in the finished object. "
        "Especially preserve the specified attachment method: do not replace a strap, clamp, collar, fastener or non-invasive mount with an invented bracket, hidden glue, drilling, fusion, or unrelated hardware. "
        "Styling and environment are subordinate to these construction cues.\n\n"
        f"SILHOUETTE: {direction.silhouette}\n"
        f"NEGATIVE SPACE: {direction.negative_space}\n"
        f"COLOR STRATEGY: {direction.color_strategy}\n\n"
        "AUTHORSHIP CUES:\n"
        f"{authorship}\n\n"
        f"COMPOSITION: {direction.composition}\n"
        f"CAMERA: {direction.camera}\n"
        f"LIGHTING: {direction.lighting}\n"
        f"VISUAL DIRECTOR ENVIRONMENT NOTE: {direction.environment}\n"
        f"MODE DIRECTION: {mode_instruction}\n\n"
        f"CANDIDATE INTENT: {candidate.one_line}\n"
        f"PHYSICAL OPERATIONS AVAILABLE: {operations}\n"
        f"ALLOWED SIMPLE ADDITIONS: {additions}\n"
        f"KEEP UNRESOLVED RATHER THAN FAKING: {unresolved}\n\n"
        "MUST KEEP:\n"
        f"{keep}\n\n"
        "Create ONE finished photorealistic authored object. Preserve provenance of the real source materials. "
        "If a locked parent-future reference is supplied, treat that image as the existing object to evolve: preserve its recognizable ancestry while integrating ONLY the active branch materials described by the candidate. Do not mine that reference image for unrelated historical source objects. "
        "In branch mode the locked parent, not the newly uploaded stock object, is the visual hero; the new matter should visibly influence or transform the inherited design. "
        "Secondary material must enter into a meaningful spatial/formal relationship with the hero, not merely form a base. "
        "Accent light must reveal or intensify the signature gesture, never substitute for the idea. "
        "Use realistic material-specific reflections, translucency, folds, seams, thickness and wear. "
        "Supporting hardware must be the minimum needed to make the selected idea believable; do not turn simple source matter into an overbuilt movie prop. "
        "Do not add labels, captions, logos, plaques, generated text or decorative storytelling props. "
        "Exact dimensions may be visually approximated for concept exploration only."
    )

    negative_constraints = [
        *direction.must_avoid,
        f"Do not produce the rejected ordinary solution: {direction.ordinary_solution_to_reject}",
        "Do not reduce the concept to an evenly spiraled LED strip around the hero.",
        "Do not reduce soft material to a stacked donut/ring base unless that exact base is essential to the selected signature gesture.",
        "Do not use generic cyberpunk RGB styling as a substitute for form or concept.",
        "Do not invent additional major source objects that were not supplied.",
        "Do not turn one coherent object into several competing objects or accessories.",
        "Do not hide the hero material behind a completely unrelated shell or oversized secondary element.",
        "Do not use magical seamless fusion, floating unsupported parts, or impossible geometry.",
        "Do not add random straps, pouches, bags, devices, cables, stands, handles, mannequins, or hardware unless explicitly required by the direction or candidate.",
        "Do not imply tested electrical, heat, load, structural, or safety certification.",
        "Do not generate text, logos, labels, plaques, watermarks, or product copy inside the image.",
        "Do not use a generic craft-collage aesthetic; make one authored design statement.",
    ]
    if branch_mode:
        negative_constraints.extend(
            [
                "Do not freeze the locked parent pixel-perfect when the selected evolution requires a local path, topology, silhouette or connection change.",
                "Do not let active branch matter replace or visually overwhelm the locked parent identity.",
                "Do not preserve active branch matter as an untouched stock object by default; transform it when the selected candidate calls for cutting, bending, slitting, drilling, folding, splitting or re-forming.",
                "Do not use the new matter as a decorative backing plate, badge, halo, trim piece or unrelated intact prop.",
                "Do not mine the locked parent reference for historical source objects that are not present as current branch material IDs.",
            ]
        )
    if state.creative_intent.background_mode == "clean_studio":
        negative_constraints.extend(
            [
                "Do not add post-apocalyptic scenery, ruins, workshop clutter, smoke, warning signage, survival props, or environmental storytelling.",
                "Do not let the background make the object seem more interesting than it is.",
            ]
        )
    else:
        negative_constraints.extend(
            [
                "Do not turn RUINFORM World into generic Fallout/cyberpunk cosplay.",
                "Do not add large unrelated machinery or environmental props that compete with the object.",
            ]
        )

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
