from ruinform_intelligence.future_models import CandidateForm, MaterialUse
from ruinform_intelligence.live_render import _contract_repair_instructions
from ruinform_intelligence.render_models import RenderCritique
from ruinform_intelligence.semantic_contract import freeze_semantic_contract


def _candidate() -> CandidateForm:
    return CandidateForm(
        candidate_id="preview_01",
        name="Gold Link Gradient",
        one_line=(
            "The spoon's narrow silver chain enlarges link by link into a cascade of gold "
            "concentric rings before returning to the terminal key hook."
        ),
        category="functional_art",
        artistic_thesis="A material transition turns captivity into a visible gradient.",
        transformation_logic="Silver chain transitions into gold ring-like links and returns toward the hook.",
        material_uses=[
            MaterialUse(
                material_item_id="gold_disc",
                role="re-form into gold ring-like chain links",
                estimated_fraction=0.7,
                note="may be cut or bent; do not preserve the stock disc silhouette",
            )
        ],
        added_materials=[],
        required_tools=["metal snips"],
        key_operations=["re-form gold disc material into ring-like links"],
        unresolved_dependencies=[],
    )


def test_semantic_contract_is_frozen_from_future_only() -> None:
    contract = freeze_semantic_contract(_candidate())

    assert contract.candidate_id == "preview_01"
    assert contract.version == "v1"
    ids = [item.requirement_id for item in contract.requirements]
    assert "future.one_line" in ids
    assert "future.logic" in ids
    assert "operation.01" in ids
    assert "material.01" in ids

    text = " ".join(item.text for item in contract.requirements).lower()
    assert "six-step" not in text
    assert "palindrome" not in text
    assert "two co-largest" not in text


def test_automatic_repair_cannot_promote_critic_prose_into_contract() -> None:
    contract = freeze_semantic_contract(_candidate())
    review = RenderCritique(
        status="regenerate",
        brief_fidelity_score=72,
        source_material_fidelity_score=86,
        provenance_visibility_score=80,
        geometry_consistency_score=73,
        invention_risk_score=16,
        violations=[],
        failed_contract_requirement_ids=["future.one_line", "invented.palindrome"],
        regeneration_instructions=[
            "Use exactly six links with two co-largest crossing rings in a perfect palindrome."
        ],
        summary="Repairable semantic geometry miss.",
    )

    instructions = _contract_repair_instructions(review, contract)
    joined = " ".join(instructions).lower()

    assert "future.one_line" in joined
    assert "exactly six" not in joined
    assert "co-largest" not in joined
    assert "palindrome" not in joined
    assert "invented.palindrome" not in joined
    assert "do not add an exact count" in joined
