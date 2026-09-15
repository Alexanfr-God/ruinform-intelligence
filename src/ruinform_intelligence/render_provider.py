from __future__ import annotations

from typing import Protocol

from .render_models import ProviderRender, RenderRequest


class RenderProviderError(RuntimeError):
    pass


class RenderProvider(Protocol):
    """Vendor-neutral rendering boundary.

    A production adapter may call Higgsfield or another renderer, but the intelligence
    layer depends only on this small contract.
    """

    async def render(self, request: RenderRequest) -> ProviderRender: ...
