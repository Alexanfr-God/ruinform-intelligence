from __future__ import annotations

import time

from ruinform_intelligence.studio import _cookie_is_valid, _cookie_token, _safe_next


def test_studio_cookie_round_trip() -> None:
    expires = int(time.time()) + 300
    token = _cookie_token("alex", expires, "secret")
    assert _cookie_is_valid(token, username="alex", password="secret")
    assert not _cookie_is_valid(token, username="alex", password="wrong")
    assert not _cookie_is_valid(token, username="other", password="secret")


def test_studio_cookie_expiry() -> None:
    token = _cookie_token("alex", int(time.time()) - 1, "secret")
    assert not _cookie_is_valid(token, username="alex", password="secret")


def test_safe_next_allows_only_internal_studio_paths() -> None:
    assert _safe_next("/studio/session-123") == "/studio/session-123"
    assert _safe_next("/studio/session-123/render") == "/studio/session-123/render"
    assert _safe_next("https://evil.example/") == "/lab"
    assert _safe_next("//evil.example/studio/x") == "/lab"
    assert _safe_next("/lab") == "/lab"
