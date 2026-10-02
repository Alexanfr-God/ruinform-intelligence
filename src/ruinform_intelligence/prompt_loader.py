from __future__ import annotations

import os
from pathlib import Path


class PromptNotFoundError(RuntimeError):
    pass


_PROMPT_OVERLAYS: dict[str, tuple[str, ...]] = {
    "design_brain.md": ("future_intelligence_v1.md",),
}


def _candidate_paths(filename: str) -> list[Path]:
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
    return candidates


def _read_first_prompt(filename: str) -> tuple[str, Path]:
    checked: list[str] = []
    for path in _candidate_paths(filename):
        resolved = path.expanduser().resolve()
        checked.append(str(resolved))
        if resolved.is_file():
            return resolved.read_text(encoding="utf-8"), resolved

    raise PromptNotFoundError(
        f"RUINFORM prompt {filename!r} was not found. Checked: " + ", ".join(checked)
    )


def load_prompt_file(filename: str) -> str:
    """Load a versioned RUINFORM prompt from a source checkout or explicit directory.

    Production installs may execute from site-packages, so prompt paths must not be
    derived only from ``__file__``. Render starts the app from the repository root;
    this resolver therefore prefers an explicit override and then the process cwd.

    Some core prompts have small versioned overlays. Keeping overlays separate lets us
    evolve one product capability without rewriting the full base prompt or coupling
    unrelated agents to the same experiment.
    """
    base_text, base_path = _read_first_prompt(filename)
    overlays = _PROMPT_OVERLAYS.get(filename, ())
    if not overlays:
        return base_text

    parts = [base_text.rstrip()]
    for overlay_name in overlays:
        overlay_path = base_path.parent / overlay_name
        if not overlay_path.is_file():
            try:
                overlay_text, _ = _read_first_prompt(overlay_name)
            except PromptNotFoundError:
                continue
        else:
            overlay_text = overlay_path.read_text(encoding="utf-8")
        if overlay_text.strip():
            parts.append(overlay_text.strip())

    return "\n\n".join(parts) + "\n"
