from __future__ import annotations

import asyncio

import httpx

from .render_provider import RenderProviderError

BASE_URL = "https://api.higgsfield.ai"
TERMINAL = {"completed", "failed", "nsfw", "canceled"}


class HiggsfieldApi:
    def __init__(self, client: httpx.AsyncClient, *, poll_seconds: float = 2.0, timeout_seconds: float = 180.0) -> None:
        self.client = client
        self.poll_seconds = poll_seconds
        self.timeout_seconds = timeout_seconds

    async def _json(self, method: str, url: str, body: dict | None = None) -> dict:
        try:
            response = await self.client.request(method, url, json=body)
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise RenderProviderError(f"Higgsfield API request failed: {exc}") from exc
        if not isinstance(data, dict):
            raise RenderProviderError("Higgsfield returned a non-object response")
        return data

    async def submit_and_wait(self, endpoint: str, payload: dict) -> dict:
        data = await self._json("POST", BASE_URL + endpoint, payload)
        request_id = data.get("request_id")
        if not request_id:
            raise RenderProviderError("Higgsfield did not return request_id")
        if data.get("status") == "completed":
            return data
        if data.get("status") in TERMINAL:
            raise RenderProviderError(f"Higgsfield generation ended with status={data.get('status')}")

        status_url = str(data.get("status_url") or f"{BASE_URL}/requests/{request_id}/status")
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.timeout_seconds
        while loop.time() < deadline:
            await asyncio.sleep(self.poll_seconds)
            current = await self._json("GET", status_url)
            if current.get("status") == "completed":
                return current
            if current.get("status") in TERMINAL:
                raise RenderProviderError(
                    f"Higgsfield generation ended with status={current.get('status')}: {current.get('error') or 'no detail'}"
                )
        raise RenderProviderError(f"Higgsfield generation timed out; request_id={request_id}")
