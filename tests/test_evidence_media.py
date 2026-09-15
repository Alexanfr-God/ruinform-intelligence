from ruinform_intelligence.evidence_media import evidence_signature, externalize_state_for_render
from ruinform_intelligence.models import EvidenceItem, ProjectState


def test_externalize_state_replaces_only_data_image_urls(monkeypatch) -> None:
    monkeypatch.setenv("RUINFORM_API_TOKEN", "test-secret")
    monkeypatch.setenv("RUINFORM_PUBLIC_BASE_URL", "https://example.test")
    state = ProjectState(
        evidence=[
            EvidenceItem(
                evidence_id="image_001",
                source_type="image",
                uri="data:image/jpeg;base64,ZmFrZQ==",
            ),
            EvidenceItem(
                evidence_id="measurement_001",
                source_type="measurement",
                property_key="height",
                value=31,
                unit="cm",
            ),
        ]
    )

    externalized = externalize_state_for_render(state, session_id="session-1")

    image_uri = externalized.evidence[0].uri
    assert image_uri is not None
    assert image_uri.startswith("https://example.test/public/evidence/session-1/image_001?sig=")
    assert externalized.evidence[1].uri is None
    assert state.evidence[0].uri.startswith("data:image/jpeg")


def test_evidence_signature_is_stable_and_scoped(monkeypatch) -> None:
    monkeypatch.setenv("RUINFORM_API_TOKEN", "test-secret")

    first = evidence_signature("session-1", "image_001")
    again = evidence_signature("session-1", "image_001")
    other = evidence_signature("session-1", "image_002")

    assert first == again
    assert first != other
    assert len(first) == 64
