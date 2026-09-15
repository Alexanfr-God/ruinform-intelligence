from __future__ import annotations

import json
import os

from openai import AsyncOpenAI

from .form_architect import FormArchitectError, validate_candidate_against_state
from .future_models import CandidateForm, FeasibilityReview, FuturePreferences
from .models import ProjectState
from .prompt_loader import load_prompt_file
from .reasoning_state import compact_state_json


DEFAULT_MODEL = "gpt-5.6"


class RevisionArchitectError(RuntimeError):
    pass


def load_revision_prompt() -> str:
    return load_prompt_file("revision_architect.md")


async def revise_candidate(
    *,
    state: ProjectState,
    candidate: CandidateForm,
    review: FeasibilityReview,
    preferences: FuturePreferences,
    client: AsyncOpenAI | None = None,
    model: str | None = None,
) -> CandidateForm:
    if review.candidate_id != candidate.candidate_id:
        raise RevisionArchitectError("Review candidate_id does not match candidate")
    if review.status != "revise":
        raise RevisionArchitectError("Only candidates with revise status may enter revision")

    model = model or os.getenv("RUINFORM_REVISION_ARCHITECT_MODEL", DEFAULT_MODEL)
    client = client or AsyncOpenAI()
    mode_policy = (
        "CONCEPT MODE: revise for exploratory ideation only; keep unverified assumptions in unresolved_dependencies and do not imply build approval."
        if preferences.concept_mode
        else "VERIFIED PATH: revise using established evidence and critic feedback."
    )

    response = await client.responses.create(
        model=model,
        reasoning={"effort": "high"},
        instructions=load_revision_prompt(),
        input=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": (
                            "Revise this candidate using the physical project state and critic feedback.\n\n"
                            f"MODE POLICY: {mode_policy}\n\n"
                            f"Project state: {compact_state_json(state)}\n\n"
                            f"Preferences: {preferences.model_dump_json()}\n\n"
                            f"Current candidate: {candidate.model_dump_json()}\n\n"
                            f"Critic review: {review.model_dump_json()}"
                        ),
                    }
                ],
            }
        ],
        text={
            "format": {
                "type": "json_schema",
                "name": "ruinform_revised_candidate",
                "strict": True,
                "schema": CandidateForm.model_json_schema(),
            }
        },
    )

    if not response.output_text:
        raise RevisionArchitectError("Revision Architect returned no candidate")
    try:
        revised = CandidateForm.model_validate(json.loads(response.output_text))
    except (json.JSONDecodeError, ValueError) as exc:
        raise RevisionArchitectError("Revision Architect returned invalid structured output") from exc

    if revised.candidate_id != candidate.candidate_id:
        raise RevisionArchitectError("Revision Architect changed candidate_id")

    try:
        validate_candidate_against_state(
            candidate=revised,
            state=state,
            preferences=preferences,
        )
    except FormArchitectError as exc:
        raise RevisionArchitectError(str(exc)) from exc

    return revised
