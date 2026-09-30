from ruinform_intelligence.concept_preview import _preview_schema
from ruinform_intelligence.live_futures import _internal_candidate_count


def test_live_future_budget_keeps_extra_search_only_for_mix():
    assert _internal_candidate_count("hybrid") == 3
    assert _internal_candidate_count("art") == 2
    assert _internal_candidate_count("buildable") == 2
    assert _internal_candidate_count("functional") == 2


def test_preview_schema_locks_requested_candidate_count():
    schema = _preview_schema(["material_001"], 2)
    candidates = schema["properties"]["candidates"]
    assert candidates["minItems"] == 2
    assert candidates["maxItems"] == 2

    candidate_form = schema["$defs"]["CandidateForm"]
    assert candidate_form["properties"]["candidate_id"]["enum"] == [
        "preview_01",
        "preview_02",
    ]
