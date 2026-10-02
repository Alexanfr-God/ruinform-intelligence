import pytest

from ruinform_intelligence.future_models import CandidateForm, MaterialOmission, MaterialUse


def _candidate(**updates) -> CandidateForm:
    payload = {
        "candidate_id": "preview_01",
        "name": "Role Test",
        "one_line": "A role-aware future.",
        "category": "functional_art",
        "artistic_thesis": "Each source earns its place.",
        "transformation_logic": "Recompose the selected sources into one authored object.",
        "material_uses": [
            MaterialUse(
                material_item_id="material_1",
                role="hero",
                estimated_fraction=None,
                note="Carries the signature gesture.",
            )
        ],
        "omitted_materials": [
            MaterialOmission(
                material_item_id="material_2",
                reason="It weakens the silhouette without adding a necessary role.",
            )
        ],
        "added_materials": [],
        "required_tools": [],
        "key_operations": ["recompose"],
        "unresolved_dependencies": [],
    }
    payload.update(updates)
    return CandidateForm(**payload)


def test_new_schema_requires_explicit_omission_accounting() -> None:
    schema = CandidateForm.model_json_schema()
    assert "omitted_materials" in schema["required"]
    role_schema = schema["$defs"]["MaterialUse"]["properties"]["role"]
    assert role_schema["enum"] == ["hero", "structure", "connector", "surface", "symbolic"]


def test_legacy_candidate_without_omissions_still_loads() -> None:
    candidate = CandidateForm(
        candidate_id="legacy_01",
        name="Legacy",
        one_line="Old stored candidate.",
        category="other",
        artistic_thesis="Archive compatibility.",
        transformation_logic="Keep old data readable.",
        material_uses=[
            MaterialUse(
                material_item_id="material_1",
                role="body",
                estimated_fraction=None,
                note=None,
            )
        ],
        added_materials=[],
        required_tools=[],
        key_operations=[],
        unresolved_dependencies=[],
    )
    assert candidate.omitted_materials == []
    assert candidate.material_uses[0].role == "hero"


def test_material_cannot_be_used_and_omitted() -> None:
    with pytest.raises(ValueError, match="both used and omitted"):
        _candidate(
            omitted_materials=[
                MaterialOmission(material_item_id="material_1", reason="Conflicting decision")
            ]
        )


def test_common_legacy_roles_normalize_to_canonical_roles() -> None:
    assert MaterialUse(material_item_id="a", role="base support", estimated_fraction=None, note=None).role == "structure"
    assert MaterialUse(material_item_id="b", role="linking joint", estimated_fraction=None, note=None).role == "connector"
    assert MaterialUse(material_item_id="c", role="textile skin", estimated_fraction=None, note=None).role == "surface"
    assert MaterialUse(material_item_id="d", role="narrative cue", estimated_fraction=None, note=None).role == "symbolic"
