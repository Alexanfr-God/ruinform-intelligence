from __future__ import annotations

import io
import os

import httpx
from openai import AsyncOpenAI, OpenAIError
from PIL import Image, ImageOps, UnidentifiedImageError

from .render_models import ProviderRender, RenderRequest
from .render_provider import RenderProviderError


DEFAULT_MODEL = "gpt-image-2.5-sunburst"
DEFAULT_QUALITY = "high"
SUPPORTED_QUALITY = {"low", "medium", "high", "auto"}
MAX_REFERENCE_SIDE = 4096


def effective_size(aspect_ratio: str) -> str:
    """Return a Sunburst-compatible resolution while keeping MVP output economical."""
    sizes = {
        "1:1": "1024x1024",
        "4:5": "1024x1280",
        "5:4": "1280x1024",
        "3:4": "1024x1360",
        "4:3": "1360x1024",
        "2:3": "1024x1536",
        "3:2": "1536x1024",
        "9:16": "864x1536",
        "16:9": "1536x864",
    }
    return sizes.get(aspect_ratio, "1024x1280")


def _full_prompt(request: RenderRequest) -> str:
    constraints = "\n".join(f"- {item}" for item in request.negative_constraints)
    if not constraints:
        return request.prompt
    return (
        request.prompt
        + "\n\nNON-NEGOTIABLE FAIL CONDITIONS:\n"
        + constraints
        + "\n\nUse the supplied source photographs as real material evidence. Preserve recognizable "
        "source identity while creating a single authored post-apocalyptic design object."
    )


def _normalize_reference_image(raw: bytes, *, evidence_id: str) -> bytes:
    """Decode arbitrary browser-uploaded image bytes and emit a plain RGB JPEG for GPT Image."""
    try:
        with Image.open(io.BytesIO(raw)) as source:
            source.seek(0)
            source.load()
            image = ImageOps.exif_transpose(source)
            if image.width < 1 or image.height < 1:
                raise ValueError("image has invalid dimensions")
            if image.mode != "RGB":
                image = image.convert("RGB")
            if max(image.size) > MAX_REFERENCE_SIDE:
                image.thumbnail(
                    (MAX_REFERENCE_SIDE, MAX_REFERENCE_SIDE),
                    Image.Resampling.LANCZOS,
                )
            output = io.BytesIO()
            image.save(
                output,
                format="JPEG",
                quality=95,
                optimize=True,
                progressive=False,
            )
            return output.getvalue()
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise RenderProviderError(
            f"Source image {evidence_id} could not be normalized for GPT Image: {exc}"
        ) from exc


class OpenAIImageProvider:
    """Primary RUINFORM image renderer using GPT Image with the real source photos."""

    def __init__(
        self,
        client: AsyncOpenAI | None = None,
        *,
        model: str = DEFAULT_MODEL,
        quality: str = DEFAULT_QUALITY,
        timeout_seconds: float = 180.0,
    ) -> None:
        if quality not in SUPPORTED_QUALITY:
            raise RenderProviderError(
                "RUINFORM_OPENAI_IMAGE_QUALITY must be one of low, medium, high, auto"
            )
        self.client = client or AsyncOpenAI()
        self.model = model
        self.quality = quality
        self.timeout_seconds = timeout_seconds

    async def _reference_files(self, request: RenderRequest) -> list[tuple[str, bytes, str]]:
        files: list[tuple[str, bytes, str]] = []
        if len(request.references) > 16:
            raise RenderProviderError("GPT Image accepts at most 16 source images")

        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as downloader:
            for index, reference in enumerate(request.references, start=1):
                try:
                    response = await downloader.get(str(reference.image_url))
                    response.raise_for_status()
                except httpx.HTTPError as exc:
                    raise RenderProviderError(
                        f"Could not load source image {reference.evidence_id}: {exc}"
                    ) from exc

                normalized = _normalize_reference_image(
                    response.content,
                    evidence_id=reference.evidence_id,
                )
                files.append((f"source_{index:02d}.jpg", normalized, "image/jpeg"))
        return files

    async def render(self, request: RenderRequest) -> ProviderRender:
        prompt = _full_prompt(request)
        size = effective_size(request.aspect_ratio)
        try:
            references = await self._reference_files(request)
            if references:
                response = await self.client.images.edit(
                    model=self.model,
                    image=references,
                    prompt=prompt,
                    quality=self.quality,
                    size=size,
                    output_format="jpeg",
                    output_compression=92,
                    background="opaque",
                    n=1,
                    timeout=self.timeout_seconds,
                )
            else:
                response = await self.client.images.generate(
                    model=self.model,
                    prompt=prompt,
                    quality=self.quality,
                    size=size,
                    output_format="jpeg",
                    output_compression=92,
                    background="opaque",
                    n=1,
                    timeout=self.timeout_seconds,
                )
        except (OpenAIError, httpx.HTTPError, ValueError) as exc:
            raise RenderProviderError(f"OpenAI image generation failed: {exc}") from exc

        if not response.data or not response.data[0].b64_json:
            raise RenderProviderError("OpenAI image generation completed without image data")

        data_url = f"data:image/jpeg;base64,{response.data[0].b64_json}"
        return ProviderRender(
            provider="openai",
            image_url=data_url,
            provider_job_id=None,
            provider_metadata={
                "model": self.model,
                "quality": self.quality,
                "size": size,
                "reference_count": len(request.references),
            },
        )
