from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any

from openai import AsyncOpenAI

from .build_models import BuildCriticReview, BuildPlan, BuildRevisionTrace
from .engineering_critic import EngineeringCriticError, review_build_plan
from .future_models import ReviewedFuture
from .models import ProjectState
from .prompt_loader import load_prompt_file
from .reasoning_state import compact_state_json


DEFAULT_MODEL = "gpt-5.6"

# Physical numbers are not allowed to appear from nowhere. Counts and time estimates are
# intentionally excluded; this targets dimensions/ratings/loads that masquerade as facts.
_PHYSICAL_NUMBER_RE = re.compile(
    r"(?<![A-Za-z0-9_])(\d+(?:\.\d+)?)\s*(mm|cm|m|inches|inch|in|ft|feet|kg|g|lbs|lb|N|Nm|V|A|W|degrees|degree|deg|°C|°F)(?![A-Za-z0-9_])",
    re.IGNORECASE,
)
_UNIT_ALIASES = {
    "inches": "in",
    "inch": "in",
    "feet": "ft",
    "lbs": "lb",
    "degree": "deg",
    "degrees": "deg",
    "°c": "c",
    "°f": "f",
}


class BuildMasterError(RuntimeError):
    pass


@dataclass(frozen=True)
class ReviewedBuildPackage:
    plan: BuildPlan
    review: BuildCriticReview
    revision_trace: BuildRevisionTrace


def load_build_master_prompt() -> str:
    return load_prompt_file("build_master.md")


def _measurement_token(number: str | int | float, unit: str) -> str:
    try:
        normalized_number = f"{float(number):g}"
    except (TypeError, ValueError):
        normalized_number = str(number).strip().lower()
    normalized_unit = unit.strip().lower()
    normalized_unit = _UNIT_ALIASES.get(normalized_unit, normalized_unit)
    return f"{normalized_number}{normalized_unit}"


def _physical_numbers(text: str) -> set[str]:
    return {_measurement_token(number, unit) for number, unit in _PHYSICAL_NUMBER_RE.findall(text or "")}


def _flatten_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return " ".join(_flatten_text(item) for item in value.values())
    if isinstance(value, (list, tuple, set)):
        return " ".join(_flatten_text(item) for item in value)
    return str(value)


def _verified_physical_numbers(state: ProjectState) -> set[str]:
    # Textual evidence/user statements may already contain a legitimate requested or measured
    # physical value. Structured EvidenceItem(value, unit) needs an explicit bridge because
    # JSON serialization separates the two fields.
    verified = _physical_numbers(_flatten_text(state.model_dump(mode="python")))
    for evidence in state.evidence:
        if isinstance(evidence.value, (int, float)) and evidence.unit:
            verified.add(_measurement_token(evidence.value, evidence.unit))
    return verified


def _plan_physical_text(plan: BuildPlan) -> str:
    payload = plan.model_dump(mode="python")
    payload.pop("estimated_time_minutes", None)
    # Step numbers and measurement IDs are metadata, not claimed physical values. The regex
    # only catches values coupled to physical units, so flattening the rest is safe.
    return _flatten_text(payload)


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

    expected_steps = list(range(1, len(plan.steps) + 1))
    actual_steps = [step.step_number for step in plan.steps]
    if actual_steps != expected_steps:
        raise BuildMasterError("Build plan steps must be sequential and start at 1")

    valid_steps = set(actual_steps)
    invalid_measurement_refs = {
        step_number
        for measurement in plan.measurements_required
        for step_number in measurement.blocks_step_numbers
        if step_number not in valid_steps
    }
    if invalid_measurement_refs:
        raise BuildMasterError(
            "Measurement requirements reference unknown build steps: "
            + ", ".join(str(value) for value in sorted(invalid_measurement_refs))
        )

    claimed_numbers = _physical_numbers(_plan_physical_text(plan))
    verified_numbers = _verified_physical_numbers(state)
    invented = claimed_numbers - verified_numbers
    if invented:
        raise BuildMasterError(
            "Build plan invented physical numbers not present in project evidence: "
            + ", ".join(sorted(invented))
            + ". Convert them to measure-to-fit instructions."
        )


def _build_request_text(
    *,
    state: ProjectState,
    future: ReviewedFuture,
    plan_mode: str,
    draft: BuildPlan | None = None,
    review: BuildCriticReview | None = None,
) -> str:
    base = (
        "Create a practical post-production build plan for this approved RUINFORM future.\n\n"
        "IMPORTANT: the image attached to this message is the exact render the user approved. "
        "Treat its visible form, arrangement, proportions, surface treatment and assembly intent as the visual target. "
        "Do not silently redesign it. If the image conflicts with verified physical facts, keep the facts and state the mismatch as a gate.\n\n"
        "Never invent a numeric physical dimension or rating. Unknown geometry belongs in measurements_required and measure-to-fit language.\n\n"
        f"PLAN MODE: {plan_mode}\n\n"
        f"Project state: {compact_state_json(state)}\n\n"
        f"Approved future: {future.candidate.model_dump_json()}\n\n"
        f"Feasibility review: {future.review.model_dump_json()}"
    )
    if draft is not None and review is not None:
        base += (
            "\n\nTHIS IS THE ONE ALLOWED ENGINEERING REPAIR PASS. Return a complete corrected plan, not a patch. "
            "Preserve the approved visual and concept identity. Fix only the engineering handoff defects identified by the critic. "
            "Do not solve missing evidence by guessing.\n\n"
            f"Previous build plan: {draft.model_dump_json()}\n\n"
            f"Engineering Critic review: {review.model_dump_json()}"
        )
    return base


async def _request_plan(
    *,
    state: ProjectState,
    future: ReviewedFuture,
    accepted_image_url: str,
    plan_mode: str,
    client: AsyncOpenAI,
    model: str,
    draft: BuildPlan | None = None,
    review: BuildCriticReview | None = None,
) -> BuildPlan:
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
                        "text": _build_request_text(
                            state=state,
                            future=future,
                            plan_mode=plan_mode,
                            draft=draft,
                            review=review,
                        ),
                    },
                    {"type": "input_image", "image_url": accepted_image_url},
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


async def generate_build_plan(
    *,
    state: ProjectState,
    future: ReviewedFuture,
    accepted_image_url: str,
    concept_mode: bool,
    client: AsyncOpenAI | None = None,
    model: str | None = None,
) -> BuildPlan:
    if future.review.status != "pass":
        raise BuildMasterError("Build plan may be generated only for a passed future")
    if not accepted_image_url.strip():
        raise BuildMasterError("Build Master requires the approved render image")

    model = model or os.getenv("RUINFORM_BUILD_MASTER_MODEL", DEFAULT_MODEL)
    client = client or AsyncOpenAI()
    plan_mode = "concept_prototype" if concept_mode else "verified"
    return await _request_plan(
        state=state,
        future=future,
        accepted_image_url=accepted_image_url,
        plan_mode=plan_mode,
        client=client,
        model=model,
    )


async def revise_build_plan(
    *,
    state: ProjectState,
    future: ReviewedFuture,
    accepted_image_url: str,
    concept_mode: bool,
    draft: BuildPlan,
    review: BuildCriticReview,
    client: AsyncOpenAI | None = None,
    model: str | None = None,
) -> BuildPlan:
    if review.status != "revise":
        raise BuildMasterError("Build repair may run only for a REVISE engineering review")
    model = model or os.getenv("RUINFORM_BUILD_MASTER_MODEL", DEFAULT_MODEL)
    client = client or AsyncOpenAI()
    plan_mode = "concept_prototype" if concept_mode else "verified"
    return await _request_plan(
        state=state,
        future=future,
        accepted_image_url=accepted_image_url,
        plan_mode=plan_mode,
        client=client,
        model=model,
        draft=draft,
        review=review,
    )


async def generate_reviewed_build_package(
    *,
    state: ProjectState,
    future: ReviewedFuture,
    accepted_image_url: str,
    concept_mode: bool,
    client: AsyncOpenAI | None = None,
    model: str | None = None,
) -> ReviewedBuildPackage:
    """Draft -> Engineering Critic -> at most one repair -> final critic.

    BLOCK never auto-repairs because it represents missing evidence or a fundamental
    contradiction. REVISE gets exactly one text-only repair pass. There is no recursive loop.
    """

    shared_client = client or AsyncOpenAI()
    draft = await generate_build_plan(
        state=state,
        future=future,
        accepted_image_url=accepted_image_url,
        concept_mode=concept_mode,
        client=shared_client,
        model=model,
    )
    try:
        first_review = await review_build_plan(
            state=state,
            future=future,
            plan=draft,
            accepted_image_url=accepted_image_url,
            client=shared_client,
        )
    except EngineeringCriticError as exc:
        raise BuildMasterError(str(exc)) from exc

    policy = "PASS locked; REVISE repaired once; BLOCK waits for new evidence; no recursive engineering loop"
    if first_review.status != "revise":
        trace = BuildRevisionTrace(
            version="build_master_v1_engineering_loop",
            attempted=False,
            before_status=first_review.status,
            after_status=None,
            changes_requested=list(first_review.required_changes),
            policy=policy,
        )
        return ReviewedBuildPackage(plan=draft, review=first_review, revision_trace=trace)

    repaired = await revise_build_plan(
        state=state,
        future=future,
        accepted_image_url=accepted_image_url,
        concept_mode=concept_mode,
        draft=draft,
        review=first_review,
        client=shared_client,
        model=model,
    )
    try:
        final_review = await review_build_plan(
            state=state,
            future=future,
            plan=repaired,
            accepted_image_url=accepted_image_url,
            client=shared_client,
        )
    except EngineeringCriticError as exc:
        raise BuildMasterError(str(exc)) from exc

    trace = BuildRevisionTrace(
        version="build_master_v1_engineering_loop",
        attempted=True,
        before_status=first_review.status,
        after_status=final_review.status,
        changes_requested=list(first_review.required_changes),
        policy=policy,
    )
    return ReviewedBuildPackage(plan=repaired, review=final_review, revision_trace=trace)
