from __future__ import annotations

import os
from pathlib import Path


class PromptNotFoundError(RuntimeError):
    pass


def load_prompt_file(filename: str) -> str:
    """Load a versioned RUINFORM prompt from a source checkout or explicit directory.

    Production installs may execute from site-packages, so prompt paths must not be
    derived only from ``__file__``. Render starts the app from the repository root;
    this resolver therefore prefers an explicit override and then the process cwd.
    """
    candidates: list[Path] = []

    override = os.getenv("RUINFORM_PROMPTS_DIR")
    if override:
        candidates.append(Path(override) / filename)

    candidates.extend(
        [
            Path.cwd() / "prompts" / filename,
            Path(__file__).resolve().parents[2] / "prompts" / filename,
        ]
    )

    checked: list[str] = []
    for path in candidates:
        resolved = path.expanduser().resolve()
        checked.append(str(resolved))
        if resolved.is_file():
            return resolved.read_text(encoding="utf-8")

    raise PromptNotFoundError(
        f"RUINFORM prompt {filename!r} was not found. Checked: " + ", ".join(checked)
    )
