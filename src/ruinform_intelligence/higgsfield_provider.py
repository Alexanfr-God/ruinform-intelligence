from __future__ import annotations

SUPPORTED_RATIOS = {"1:1", "4:3", "3:4", "3:2", "2:3", "16:9", "9:16"}
RATIO_FALLBACKS = {"4:5": "3:4", "5:4": "4:3", "21:9": "16:9"}


def effective_aspect_ratio(value: str) -> str:
    if value in SUPPORTED_RATIOS:
        return value
    return RATIO_FALLBACKS.get(value, "3:4")
