from __future__ import annotations

from .higgsfield_api import HiggsfieldApi
from .render_models import ProviderRender, RenderRequest
from .render_provider import RenderProviderError

DEFAULT_ENDPOINT = "/higgsfield-ai/popcorn/auto"
SUPPORTED_RATIOS = {"1:1", "4:3", "3:4", "3:2", "2:3", "16:9", "9:16"}
RATIO_FALLBACKS = {"4:5": "3:4", "5:4": "4:3", "21:9": "16:9"}


def effective_aspect_ratio(value: str) -> str:
    if value in SUPPORTED_RATIOS:
        return value
    return RATIO_FALLBACKS.get(value, "3:4")


class HiggsfieldProvider:
    def __init__(self, api: HiggsfieldApi, *, endpoint: str = DEFAULT_ENDPOINT, resolution: str = "1600p") -> None:
        self.api = api
        self.endpoint = endpoint if endpoint.startswith("/") else f"/{endpoint}"
        self.resolution = resolution

    def payload(self, request: RenderRequest) -> dict[str, object]:
        references = [str(reference.image_url) for reference in request.references]
        if len(references) > 8:
            raise RenderProviderError("Higgsfield Popcorn accepts at most 8 image references")
        constraints = "\n".join(f"- {item}" for item in request.negative_constraints)
        prompt = request.prompt
        if constraints:
            prompt += "\n\nSTRICT VISUAL CONSTRAINTS:\n" + constraints
        return {
            "prompt": prompt,
            "image_urls": references,
            "num_images": 1,
            "resolution": self.resolution,
            "aspect_ratio": effective_aspect_ratio(request.aspect_ratio),
        }

    async def render(self, request: RenderRequest) -> ProviderRender:
        payload = self.payload(request)
        data = await self.api.submit_and_wait(self.endpoint, payload)
        images = data.get("images") or []
        if not images or not isinstance(images[0], dict) or not images[0].get("url"):
            raise RenderProviderError("Higgsfield completed without an image URL")
        return ProviderRender(
            provider="higgsfield",
            image_url=images[0]["url"],
            provider_job_id=data.get("request_id"),
            provider_metadata={
                "endpoint": self.endpoint,
                "resolution": self.resolution,
                "effective_aspect_ratio": str(payload["aspect_ratio"]),
            },
        )
