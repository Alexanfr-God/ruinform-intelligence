from __future__ import annotations

import json
import os

from openai import AsyncOpenAI

from .build_models import BuildPlan
from .future_models import ReviewedFuture
from .models import ProjectState
from .prompt_loader import load_prompt_file
from .reasoning_state import compact_state_json


DEFAULT_MODEL = "gpt-5.6"


class BuildMasterError(RuntimeError):
    pass


def load_build_master_prompt() -> str:
    return load_prompt_file("build_master.md")


def _validate_plan(*, plan: BuildPlan, state: ProjectState, future: ReviewedFuture) -> None:
    if plan.candidate_id != future.candidate.candidate_id:
        raise BuildMasterError("Build plan candidate_id does not match selected future")

    known_material_ids = {item.item_id for item in state.materials}
    used_ids = {
        material_id
        for step in plan.steps
        for material_id in step.source_material_ids
    }
    unknown_ids = used_ids - known_material_ids
    if unknown_ids:
        raise BuildMasterError(
            "Build plan references unknown source material IDs: "
            + ", ".join(sorted(unknown_ids))
        )

    if future.review.status != "pass":
        raise BuildMasterError("Build plan may be generated only for a passed future")


async def generate_build_plan(
    *,
    state: ProjectState,
    future: ReviewedFuture,
    concept_mode: bool,
    client: AsyncOpenAI | None = None,
    model: str | None = None,
) -> BuildPlan:
    if future.review.status != "pass":
        raise BuildMasterError("Build plan may be generated only for a passed future")

    model = model or os.getenv("RUINFORM_BUILD_MASTER_MODEL", DEFAULT_MODEL)
    client = client or AsyncOpenAI()
    plan_mode = "concept_prototype" if concept_mode else "verified"

    response = await client.responses.create(
        model=model,
        reasoning={"effort": "medium"},
        instructions=load_build_master_prompt(),
        input=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": (
                            "Create a practical post-production build plan for this approved RUINFORM future.\n\n"
                            f"PLAN MODE: {plan_mode}\n\n"
                            f"Project state: {compact_state_json(state)}\n\n"
                            f"Approved future: {future.candidate.model_dump_json()}\n\n"
                            f"Feasibility review: {future.review.model_dump_json()}"
                        ),
                    }
                ],
            }
        ],
        text={
            "format": {
                "type": "json_schema",
                "name": "ruinform_build_plan",
                "strict": True,
                "schema": BuildPlan.model_json_schema(),
            }
        },
    )

    if not response.output_text:
        raise BuildMasterError("Build Master returned no plan")

    try:
        plan = BuildPlan.model_validate(json.loads(response.output_text))
    except (json.JSONDecodeError, ValueError) as exc:
        raise BuildMasterError("Build Master returned invalid structured output") from exc

    _validate_plan(plan=plan, state=state, future=future)
    return plan
