from ruinform_intelligence.higgsfield_provider import HiggsfieldProvider, effective_aspect_ratio
from ruinform_intelligence.render_models import RenderReference, RenderRequest


class DummyApi:
    pass


def test_aspect_ratio_falls_back_for_popcorn() -> None:
    assert effective_aspect_ratio("4:5") == "3:4"
    assert effective_aspect_ratio("16:9") == "16:9"


def test_payload_preserves_references_and_constraints() -> None:
    provider = HiggsfieldProvider(DummyApi())
    request = RenderRequest(
        candidate_id="candidate_01",
        prompt="Create the approved future form.",
        negative_constraints=["Do not invent extra hardware."],
        references=[
            RenderReference(
                evidence_id="image_001",
                image_url="https://example.com/source.jpg",
                material_item_id="material_01",
                note=None,
            )
        ],
        aspect_ratio="4:5",
    )
    payload = provider.payload(request)
    assert payload["image_urls"] == ["https://example.com/source.jpg"]
    assert payload["aspect_ratio"] == "3:4"
    assert "Do not invent extra hardware." in payload["prompt"]
