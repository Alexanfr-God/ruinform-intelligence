import asyncio

from ruinform_intelligence.future_models import (
    CandidateForm,
    FeasibilityReview,
    MaterialUse,
    ReviewedFuture,
    VisualBrief,
    VisualMaterialTrace,
)
from ruinform_intelligence.models import (
    ClaimKind,
    EvidenceItem,
    EvidenceRef,
    MaterialItem,
    MaterialObservation,
    ProjectState,
)
from ruinform_intelligence.render_gateway import render_future
from ruinform_intelligence.render_models import ProviderRender, RenderCritique, RenderViolation
from ruinform_intelligence.render_prompt import compile_render_request
from ruinform_intelligence.render_review import enforce_render_gate


def _state() -> ProjectState:
    evidence = EvidenceItem(
        evidence_id="image_001",
        source_type="image",
        uri="https://example.com/source.jpg",
    )
    material = MaterialItem(
        item_id="material_1",
        display_name="worn denim",
        observations=[
            MaterialObservation(
                observation_id="obs_1",
                property_key="material_family",
                label="appears to be denim",
                claim_kind=ClaimKind.HYPOTHESIS,
                confidence=0.9,
                evidence=[EvidenceRef(evidence_id="image_001", source_type="image")],
            )
        ],
    )
    return ProjectState(stage="ideation", evidence=[evidence], materials=[material])


def _future() -> ReviewedFuture:
    candidate = CandidateForm(
        candidate_id="candidate_01",
        name="Scarred Vessel",
        one_line="A sculptural utility vessel preserving worn denim traces.",
        category="functional_art",
        artistic_thesis="Wear becomes visible history.",
        transformation_logic="Fold and tension existing denim around a simple reusable structure.",
        material_uses=[
            MaterialUse(
                material_item_id="material_1",
                role="visible outer skin",
                estimated_fraction=None,
                note=None,
            )
        ],
        added_materials=[],
        required_tools=[],
        key_operations=["fold", "join"],
        unresolved_dependencies=[],
    )
    review = FeasibilityReview(
        candidate_id="candidate_01",
        status="pass",
        feasibility_score=86,
        material_fit_score=94,
        buildability_score=80,
        originality_score=88,
        artistic_impact_score=91,
        usefulness_score=72,
        value_potential_score=76,
        reasons=["Material identity remains visible."],
        required_changes=[],
        unresolved_dependencies=[],
    )
    brief = VisualBrief(
        candidate_id="candidate_01",
        title="Scarred Vessel",
        object_summary="A compact sculptural utility object with visibly worn denim skin.",
        silhouette="Asymmetrical upright vessel.",
        geometry_notes=["Keep the outer form simple and materially legible."],
        material_traces=[
            VisualMaterialTrace(
                material_item_id="material_1",
                intended_location="outer skin",
                source_character_to_preserve="fades, abrasion, original weave",
                appearance_constraints=["do not replace with pristine generic denim"],
            )
        ],
        visible_connections=["simple visible joining line"],
        composition="single object, isolated",
        camera="three-quarter view",
        lighting="directional workshop light",
        environment="dark neutral studio-workshop",
        provenance_cues=["source wear remains visible"],
        unknowns_to_keep_ambiguous=[],
        forbidden_inventions=["Do not invent exact dimensions."],
    )
    return ReviewedFuture(candidate=candidate, review=review, rank_score=89.0, visual_brief=brief)


def _review(status: str, *, source_score: int = 90, invention_risk: int = 10) -> RenderCritique:
    return RenderCritique(
        status=status,
        brief_fidelity_score=90,
        source_material_fidelity_score=source_score,
        provenance_visibility_score=86,
        geometry_consistency_score=88,
        invention_risk_score=invention_risk,
        violations=[],
        failed_contract_requirement_ids=[],
        regeneration_instructions=["Preserve more of the original worn surface."],
        summary="Review complete.",
    )


def test_compile_render_request_carries_source_evidence() -> None:
    request = compile_render_request(state=_state(), future=_future())
    assert request.candidate_id == "candidate_01"
    assert [ref.evidence_id for ref in request.references] == ["image_001"]
    assert request.references[0].material_item_id == "material_1"
    assert "RUINFORM FUTURE FORM" in request.prompt


def test_render_gate_overrides_unsafe_pass() -> None:
    review = _review("pass", source_score=50, invention_risk=40)
    gated = enforce_render_gate(review)
    assert gated.status == "regenerate"


def test_render_gate_blocks_explicit_blocker() -> None:
    review = _review("pass")
    review = review.model_copy(
        update={
            "violations": [
                RenderViolation(
                    code="invented_part",
                    severity="critical",
                    message="The image adds an undeclared structural part.",
                )
            ]
        }
    )
    assert enforce_render_gate(review).status == "regenerate"


def test_gateway_regenerates_until_render_passes(monkeypatch) -> None:
    class FakeProvider:
        def __init__(self) -> None:
            self.calls = 0

        async def render(self, request):
            self.calls += 1
            return ProviderRender(
                provider="fake",
                image_url=f"https://example.com/render-{self.calls}.jpg",
                provider_job_id=f"job-{self.calls}",
            )

    calls = {"count": 0}

    async def fake_evaluate_render(**kwargs):
        calls["count"] += 1
        return _review("regenerate" if calls["count"] == 1 else "pass")

    monkeypatch.setattr("ruinform_intelligence.render_gateway.evaluate_render", fake_evaluate_render)
    provider = FakeProvider()
    result = asyncio.run(
        render_future(
            state=_state(),
            future=_future(),
            provider=provider,
            max_attempts=3,
        )
    )

    assert result.status == "pass"
    assert len(result.attempts) == 2
    assert provider.calls == 2
    assert "REGENERATION DIRECTIVES" in result.attempts[1].request.prompt
