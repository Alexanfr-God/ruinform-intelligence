import io

from PIL import Image

from ruinform_intelligence.openai_image_provider import _normalize_reference_image


def test_reference_normalization_converts_cmyk_to_rgb_jpeg() -> None:
    source_buffer = io.BytesIO()
    Image.new("CMYK", (32, 24), (0, 120, 120, 10)).save(source_buffer, format="JPEG")

    normalized = _normalize_reference_image(source_buffer.getvalue(), evidence_id="image_001")

    with Image.open(io.BytesIO(normalized)) as image:
        assert image.format == "JPEG"
        assert image.mode == "RGB"
        assert image.size == (32, 24)
