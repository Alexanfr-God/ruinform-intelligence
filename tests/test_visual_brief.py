import pytest

from ruinform_intelligence.future_models import (
    CandidateForm,
    MaterialUse,
    VisualBrief,
    VisualMaterialTrace,
)
from ruinform_intelligence.models import MaterialItem, ProjectState, Unknown
from ruinform_intelligence.visual_brief import VisualBriefError, _enforce_renderer_boundaries


def _candidate() -> CandidateForm:
    return CandidateForm(
        candidate_id="candidate_01",
        name="Artifact",
        one_line="A materially honest artifact.",
        category="functional_art",
        artistic_thesis="Keep the original matter visible.",
        transformation_logic="Reconfigure the source matter.",
        material_uses=[
            MaterialUse(
                material_item_id="material_1",
                role="primary body",
                estimated_fraction=None,
                note=None,
            )
        ],
        added_materials=[],
        required_tools=[],
        key_operations=["reconfigure"],
        unresolved_dependencies=[],
    )


def _brief(material_id: str = "material_1") -> VisualBrief:
    return VisualBrief(
        candidate_id="candidate_01",
        title="Artifact",
        object_summary="A restrained future form.",
        silhouette="Compact asymmetrical object.",
        geometry_notes=["Keep geometry visually plausible without exact dimensions."],
        material_traces=[
            VisualMaterialTrace(
                material_item_id=material_id,
                intended_location="main body",
                source_character_to_preserve="existing surface wear",
                appearance_constraints=[],
            )
        ],
        visible_connections=[],
        composition="Single object centered in frame.",
        camera="Three-quarter documentary view.",
        lighting="Directional workshop light.",
        environment="Neutral fabrication space.",
        provenance_cues=["Keep source wear visible."],
        unknowns_to_keep_ambiguous=[],
        forbidden_inventions=[],
    )


def test_visual_brief_inherits_unresolved_physical_unknowns() -> None:
    state = ProjectState(
        materials=[
            MaterialItem(
                item_id="material_1",
                display_name="metal tube",
                unknowns=[
                    Unknown(
                        property_key="wall_thickness",
                        question="What is the wall thickness?",
                        reason="Not established yet.",
                        consequence_if_unresolved="medium",
                    )
                ],
            )
        ]
    )

    result = _enforce_renderer_boundaries(
        state=state,
        candidate=_candidate(),
        brief=_brief(),
    )

    assert "wall_thickness" in result.unknowns_to_keep_ambiguous
    assert any("wall_thickness" in item for item in result.forbidden_inventions)
    assert any("engineering proof" in item for item in result.forbidden_inventions)


def test_visual_brief_cannot_swap_source_materials() -> None:
    state = ProjectState(materials=[MaterialItem(item_id="material_1", display_name="metal")])

    with pytest.raises(VisualBriefError, match="exactly match"):
        _enforce_renderer_boundaries(
            state=state,
            candidate=_candidate(),
            brief=_brief(material_id="material_999"),
        )
