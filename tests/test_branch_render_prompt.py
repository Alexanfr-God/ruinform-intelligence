from ruinform_intelligence.future_models import CandidateForm, FeasibilityReview, MaterialUse, ReviewedFuture
from ruinform_intelligence.models import ClaimKind, EvidenceItem, EvidenceRef, MaterialItem, MaterialObservation, ProjectState
from ruinform_intelligence.render_director import VisualDirection
from ruinform_intelligence.render_prompt import compile_preview_render_request


def _review(candidate_id: str) -> FeasibilityReview:
    return FeasibilityReview(
        candidate_id=candidate_id,
        status="pass",
        feasibility_score=82,
        material_fit_score=88,
        buildability_score=76,
        originality_score=90,
        artistic_impact_score=91,
        usefulness_score=78,
        value_potential_score=86,
        reasons=["Strong causal material relationship."],
        required_changes=[],
        unresolved_dependencies=[],
    )


def _candidate(candidate_id: str = "preview_01") -> CandidateForm:
    return CandidateForm(
        candidate_id=candidate_id,
        name="Gravity Orbit",
        one_line="A transformed gold disc becomes an orbital guide that redirects the inherited chain-pour before it returns to the hook.",
        category="functional_art",
        artistic_thesis="A domestic disc becomes a precise interruption in a frozen act of pouring.",
        transformation_logic="Slit and re-form the gold disc into a shallow orbital guide so the inherited chain path visibly bends through it.",
        material_uses=[
            MaterialUse(
                material_item_id="material_gold",
                role="transformed orbital guide that causally redirects the inherited chain path",
                estimated_fraction=None,
                note="Preserve gold metal provenance without preserving the intact lid silhouette.",
            )
        ],
        added_materials=["minimal concealed fastener if needed"],
        required_tools=["snips", "pliers", "drill"],
        key_operations=["slit", "bend", "re-form", "fasten"],
        unresolved_dependencies=["Confirm exact metal thickness before fabrication."],
    )


def _direction() -> VisualDirection:
    return VisualDirection(
        render_mode="art_object",
        hero_material_id="material_gold",
        hero_object="Frozen Pour Valet descendant with a transformed orbital guide",
        secondary_material_ids=[],
        accent_material_ids=[],
        object_type="functional art wall hook",
        visual_thesis="The inherited frozen pour is forced into a new orbit by transformed gold matter.",
        conceptual_tension="A soft circular orbit interrupts and redirects the hard descending chain path.",
        material_relationship="The gold stock is cut and re-formed into a guide that physically causes the chain trajectory to bend.",
        signature_gesture="The chain visibly enters a formed gold channel, arcs around it, and exits toward the inherited terminal hook.",
        ordinary_solution_to_reject="An intact gold lid simply mounted behind the original spoon-chain hook as decoration.",
        silhouette="The original spoon-chain-hook ancestry remains readable, with one controlled orbital swelling in the chain path.",
        negative_space="Keep a clear crescent void between the transformed gold guide and the returning chain.",
        color_strategy="Preserve silver chain and warm gold contrast without introducing unrelated colors.",
        composition="One wall-mounted descendant, isolated and immediately readable.",
        camera="Three-quarter frontal object view at eye level.",
        lighting="Directional editorial light revealing the gold guide profile and chain path.",
        environment="Restrained neutral gallery wall.",
        authorship_cues=[
            "One visibly transformed gold guide creates the new chain trajectory.",
            "The inherited spoon-to-chain-to-hook gesture remains legible at a glance.",
        ],
        must_keep=[
            "Keep the locked parent's spoon ancestry recognizable.",
            "Keep the frozen chain-pour relationship recognizable.",
            "Keep the terminal hook relationship recognizable.",
        ],
        must_avoid=[
            "Do not use an intact lid as a backing plate.",
            "Do not obscure the inherited spoon-chain-hook ancestry.",
            "Do not invent unrelated old source objects.",
            "Do not add decorative hardware unrelated to the orbit.",
            "Do not replace the chain with a generic new chain design.",
        ],
    )


def _branch_state() -> ProjectState:
    new_evidence = EvidenceItem(
        evidence_id="image_new_gold",
        source_type="image",
        uri="https://example.com/gold-disc.jpg",
    )
    parent_evidence = EvidenceItem(
        evidence_id="branch_parent_future",
        source_type="image",
        uri="https://example.com/frozen-pour-valet.jpg",
        note="Frozen Pour Valet locked parent",
    )
    material = MaterialItem(
        item_id="material_gold",
        display_name="gold-colored circular disc",
        observations=[
            MaterialObservation(
                observation_id="obs_gold",
                property_key="appearance",
                label="gold-colored circular metal-looking disc",
                claim_kind=ClaimKind.HYPOTHESIS,
                confidence=0.9,
                evidence=[EvidenceRef(evidence_id="image_new_gold", source_type="image")],
            )
        ],
    )
    return ProjectState(
        stage="ideation",
        evidence=[parent_evidence, new_evidence],
        materials=[material],
    )


def _ordinary_state() -> ProjectState:
    evidence = EvidenceItem(
        evidence_id="image_new_gold",
        source_type="image",
        uri="https://example.com/gold-disc.jpg",
    )
    material = MaterialItem(
        item_id="material_gold",
        display_name="gold-colored circular disc",
        observations=[
            MaterialObservation(
                observation_id="obs_gold",
                property_key="appearance",
                label="gold-colored circular metal-looking disc",
                claim_kind=ClaimKind.HYPOTHESIS,
                confidence=0.9,
                evidence=[EvidenceRef(evidence_id="image_new_gold", source_type="image")],
            )
        ],
    )
    return ProjectState(stage="ideation", evidence=[evidence], materials=[material])


def _future() -> ReviewedFuture:
    candidate = _candidate()
    return ReviewedFuture(candidate=candidate, review=_review(candidate.candidate_id), rank_score=88.0)


def test_branch_render_keeps_locked_parent_as_visual_hero() -> None:
    request = compile_preview_render_request(
        state=_branch_state(),
        future=_future(),
        direction=_direction(),
    )

    refs = {ref.evidence_id: ref for ref in request.references}
    assert set(refs) == {"branch_parent_future", "image_new_gold"}
    assert "locked parent future" in (refs["branch_parent_future"].note or "")
    assert "BRANCH EVOLUTION CONTRACT — HARD PRIORITY" in request.prompt
    assert "HERO / DESIGN ANCESTOR — LOCKED PARENT FUTURE" in request.prompt
    assert "ACTIVE BRANCH MATTER — gold-colored circular disc" in request.prompt
    assert "the locked parent, not the newly uploaded stock object, is the visual hero" in request.prompt
    assert "HERO — gold-colored circular disc" not in request.prompt
    assert "untouched stock object" in request.prompt
    assert any("decorative backing plate" in item for item in request.negative_constraints)
    assert any("historical source objects" in item for item in request.negative_constraints)


def test_non_branch_render_keeps_normal_material_hero_hierarchy() -> None:
    request = compile_preview_render_request(
        state=_ordinary_state(),
        future=_future(),
        direction=_direction(),
    )

    assert "BRANCH EVOLUTION CONTRACT — HARD PRIORITY" not in request.prompt
    assert "HERO — gold-colored circular disc" in request.prompt
    assert "HERO / DESIGN ANCESTOR — LOCKED PARENT FUTURE" not in request.prompt
