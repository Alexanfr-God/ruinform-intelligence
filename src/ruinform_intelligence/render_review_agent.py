from __future__ import annotations

import json
import os
from pathlib import Path

from openai import AsyncOpenAI

from .render_models import RenderCritique

DEFAULT_MODEL = "gpt-5.6"
PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "render_critic.md"


async def parse_render_review(*, response_text: str) -> RenderCritique:
    return RenderCritique.model_validate(json.loads(response_text))
