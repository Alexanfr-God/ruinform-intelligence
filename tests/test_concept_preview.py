from ruinform_intelligence.concept_preview import (
    PreviewBatch,
    PreviewCandidate,
    _instructions,
    _preview_schema,
)
from ruinform_intelligence.future_models import CandidateForm, MaterialUse


def _preview(candidate_id: str) -> PreviewCandidate:
    return PreviewCandidate(
        candidate=CandidateForm(
            candidate_id=candidate_id,
            name=f"Concept {candidate_id}",
            one_line="A quick transformed object.",
            category="functional_art",
            artistic_thesis="Keep source traces visible.",
            transformation_logic="Fold, wrap, and join the source matter into a new object.",
            material_uses=[
                MaterialUse(
                    material_item_id="material_1",
                    role="body",
                    estimated_fraction=None,
                    note=None,
                )
            ],
            added_materials=["zip ties"],
            required_tools=["scissors"],
            key_operations=["trim-to-fit", "wrap", "join"],
            unresolved_dependencies=["exact dimensions"],
        ),
        buildability_hint=80,
        originality_hint=85,
        artistic_impact_hint=90,
        usefulness_hint=60,
        value_hint=70,
        confidence_note="Preview only.",
    )


def test_preview_batch_requires_exactly_four_candidates() -> None:
    batch = PreviewBatch(candidates=[_preview(f"preview_{index:02d}") for index in range(1, 5)])
    assert len(batch.candidates) == 4


def test_preview_prompt_defers_engineering_until_after_selection() -> None:
    prompt = _instructions("hybrid")
    assert "PREVIEW stage" in prompt
    assert "not engineering approval" in prompt
    assert "scale-to-fit" in prompt
    assert "exactly four" in prompt


def test_preview_schema_locks_material_ids_to_project_state() -> None:
    schema = _preview_schema(["real_a", "real_b"])
    material_id_schema = schema["$defs"]["MaterialUse"]["properties"]["material_item_id"]
    candidate_id_schema = schema["$defs"]["CandidateForm"]["properties"]["candidate_id"]
    assert material_id_schema["enum"] == ["real_a", "real_b"]
    assert candidate_id_schema["enum"] == ["preview_01", "preview_02", "preview_03", "preview_04"]
