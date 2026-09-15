import asyncio

import httpx

from ruinform_intelligence.higgsfield_api import HiggsfieldApi


def test_submit_and_poll_to_completion() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(f"{request.method} {request.url.path}")
        if request.method == "POST":
            return httpx.Response(
                200,
                json={
                    "status": "queued",
                    "request_id": "11111111-1111-4111-8111-111111111111",
                    "status_url": "https://api.higgsfield.ai/requests/test/status",
                },
            )
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "request_id": "11111111-1111-4111-8111-111111111111",
                "images": [{"url": "https://example.com/result.jpg"}],
            },
        )

    async def run() -> dict:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            api = HiggsfieldApi(client, poll_seconds=0, timeout_seconds=1)
            return await api.submit_and_wait("/higgsfield-ai/popcorn/auto", {"prompt": "test"})

    result = asyncio.run(run())
    assert result["status"] == "completed"
    assert calls == [
        "POST /higgsfield-ai/popcorn/auto",
        "GET /requests/test/status",
    ]
