from __future__ import annotations

import os

import httpx
from openai import AsyncOpenAI, OpenAIError

from .render_models import ProviderRender, RenderRequest
from .render_provider import RenderProviderError


DEFAULT_MODEL = "gpt-image-2.5-sunburst"
DEFAULT_QUALITY = "high"
SUPPORTED_QUALITY = {"low", "medium", "high", "auto"}


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

                media_type = response.headers.get("content-type", "image/jpeg").split(";", 1)[0].lower()
                if media_type == "image/jpg":
                    media_type = "image/jpeg"
                if media_type not in {"image/jpeg", "image/png", "image/webp"}:
                    raise RenderProviderError(
                        f"Unsupported source image type for {reference.evidence_id}: {media_type}"
                    )
                extension = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}[media_type]
                files.append((f"source_{index:02d}.{extension}", response.content, media_type))
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
