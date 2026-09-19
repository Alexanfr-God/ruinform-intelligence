from ruinform_intelligence.future_models import CandidateForm, FeasibilityReview, MaterialUse, RevisionRecord
from ruinform_intelligence.preview_repair import RepairBatch, build_repair_directives, _repair_schema


def _candidate(candidate_id: str, name: str) -> CandidateForm:
    return CandidateForm(
        candidate_id=candidate_id,
        name=name,
        one_line="test",
        category="sculpture",
        artistic_thesis="test",
        transformation_logic="test",
        material_uses=[MaterialUse(material_item_id="m1", role="hero", estimated_fraction=1.0, note=None)],
        added_materials=[],
        required_tools=[],
        key_operations=["test"],
        unresolved_dependencies=[],
    )


def _review(candidate_id: str, status: str) -> FeasibilityReview:
    return FeasibilityReview(
        candidate_id=candidate_id,
        status=status,
        feasibility_score=70,
        material_fit_score=70,
        buildability_score=70,
        originality_score=70,
        artistic_impact_score=70,
        usefulness_score=70,
        value_potential_score=70,
        reasons=["test"],
        required_changes=["simplify"],
        unresolved_dependencies=[],
    )


def test_build_repair_directives_skips_pass_and_maps_actions() -> None:
    candidates = [
        _candidate("preview_01", "pass"),
        _candidate("preview_02", "revise"),
        _candidate("preview_03", "reject"),
    ]
    reviews = {
        "preview_01": _review("preview_01", "pass"),
        "preview_02": _review("preview_02", "revise"),
        "preview_03": _review("preview_03", "reject"),
    }

    directives = build_repair_directives(candidates, reviews)

    assert [(item.candidate_id, item.action) for item in directives] == [
        ("preview_02", "revise"),
        ("preview_03", "replace"),
    ]


def test_repair_schema_locks_target_count_and_ids() -> None:
    schema = _repair_schema(["m1", "m2"], ["preview_02", "preview_04"])
    assert schema["properties"]["candidates"]["minItems"] == 2
    assert schema["properties"]["candidates"]["maxItems"] == 2
    assert schema["$defs"]["CandidateForm"]["properties"]["candidate_id"]["enum"] == [
        "preview_02",
        "preview_04",
    ]
    assert schema["$defs"]["MaterialUse"]["properties"]["material_item_id"]["enum"] == ["m1", "m2"]


def test_revision_record_can_preserve_reject_replacement_history() -> None:
    before = _candidate("preview_03", "before")
    after = _candidate("preview_03", "after")
    record = RevisionRecord(
        round_index=1,
        critique_status="reject",
        requested_changes=["replace mechanism"],
        candidate_before=before,
        candidate_after=after,
    )
    assert record.critique_status == "reject"
    assert record.candidate_before.name == "before"
    assert record.candidate_after.name == "after"
