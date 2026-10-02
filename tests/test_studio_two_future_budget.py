import asyncio

from ruinform_intelligence import server


def test_studio_control_preview_forces_exactly_two_futures(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def fake_self_healing_preview(**kwargs):
        captured.update(kwargs)
        return "ok"

    monkeypatch.setattr(server, "generate_self_healing_preview", fake_self_healing_preview)

    result = asyncio.run(
        server._generate_two_future_preview(
            state=object(),
            mode="hybrid",
            candidate_count=99,
        )
    )

    assert result == "ok"
    assert captured["candidate_count"] == 2
    assert captured["mode"] == "hybrid"
