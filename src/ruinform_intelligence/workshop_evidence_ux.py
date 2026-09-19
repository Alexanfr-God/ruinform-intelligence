from __future__ import annotations

import html
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict

from .build_models import BuildCriticReview, BuildPlan, MeasurementRequirement


EvidenceInputKind = Literal["measurement", "inspection", "photo", "statement"]
EvidencePhase = Literal["now", "after_mockup", "after_assembly", "before_installation"]
_PHASE_ORDER: tuple[EvidencePhase, ...] = (
    "now",
    "after_mockup",
    "after_assembly",
    "before_installation",
)
_PHASE_LABELS = {
    "now": "NOW",
    "after_mockup": "AFTER MOCK-UP",
    "after_assembly": "AFTER ASSEMBLY",
    "before_installation": "BEFORE INSTALLATION",
}
_MAX_TASKS = 8
_TAG_RE = re.compile(r"^\[([A-Z0-9_]+)\]\s*(.*)$", re.DOTALL)
_WORD_RE = re.compile(r"[a-z0-9_]+", re.IGNORECASE)
_STOP_WORDS = {
    "the", "and", "or", "a", "an", "to", "of", "for", "with", "from", "is", "are",
    "be", "before", "after", "that", "this", "its", "into", "using", "use", "used", "real",
    "actual", "plan", "build", "step", "steps", "required", "verify", "verified", "selected",
}


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WorkshopEvidenceTask(StrictModel):
    task_id: str
    title: str
    input_kind: EvidenceInputKind
    phase: EvidencePhase
    instruction: str
    why_needed: str
    property_key: str
    required: bool = True


class WorkshopEvidenceRequest(StrictModel):
    version: str
    candidate_id: str
    critic_status: Literal["revise", "block"]
    tasks: list[WorkshopEvidenceTask]


def _clean(value: str) -> str:
    clean = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return clean[:54] or "evidence"


def _tokens(text: str) -> set[str]:
    return {
        token.lower()
        for token in _WORD_RE.findall(text or "")
        if len(token) >= 3 and token.lower() not in _STOP_WORDS
    }


def _measurement_phase(measurement: MeasurementRequirement) -> EvidencePhase:
    text = " ".join(
        [
            measurement.measurement_id,
            measurement.what_to_measure,
            measurement.how_to_measure,
            measurement.used_for,
        ]
    ).lower()
    if any(token in text for token in ("completed assembly mass", "after final fastening", "complete assembly", "finished assembly")):
        return "after_assembly"
    if any(token in text for token in ("full-scale", "mock-up", "mockup", "sag", "curl", "layout behavior", "layout_behavior")):
        return "after_mockup"
    if any(token in text for token in ("mounting interface", "standoff spacing", "connector selection", "mounting layout")):
        return "after_assembly"
    if any(token in text for token in ("wall substrate", "concealed service", "wall condition", "wall_conditions")):
        return "now"
    if any(token in text for token in ("anchor", "hardware rating", "manufacturer rating")):
        return "before_installation"
    return "now"


def _measurement_score(measurement: MeasurementRequirement, critic_tokens: set[str]) -> int:
    text = " ".join(
        [measurement.measurement_id, measurement.what_to_measure, measurement.used_for, measurement.how_to_measure]
    )
    overlap = _tokens(text) & critic_tokens
    score = len(overlap) * 3
    lowered = text.lower()
    for high_value in ("wall", "anchor", "mount", "mass", "weight", "load", "center", "clearance", "substrate", "material", "condition"):
        if high_value in critic_tokens and high_value in lowered:
            score += 4
    return score


def _critic_task(tag: str, body: str, index: int) -> WorkshopEvidenceTask | None:
    tag = tag.upper()
    if tag in {"INVENTED_DIMENSION", "MISSING_MEASUREMENT"}:
        return WorkshopEvidenceTask(
            task_id=f"critic_{_clean(tag)}_{index}",
            title="Measure the missing real geometry",
            input_kind="measurement",
            phase="now",
            instruction=(
                "Measure the named real dimension directly on the object. Report the raw number and unit only, plus how you measured it. "
                "Do not estimate from the generated render."
            ),
            why_needed=body or f"Engineering Critic requested evidence for {tag}.",
            property_key=f"critic_{tag.lower()}_{index}",
        )
    if tag == "UNVERIFIED_LOAD":
        return WorkshopEvidenceTask(
            task_id=f"critic_{_clean(tag)}_{index}",
            title="Record raw mounting facts you can measure now",
            input_kind="measurement",
            phase="now",
            instruction=(
                "Give only raw facts you can actually measure or confirm now: current object/partial-assembly mass if available, distance from the wall/support line to the farthest point, support spacing if known, and intended mounting orientation. "
                "Do NOT calculate reactions, moments, load eccentricity, or safety factors — RUINFORM must derive those later. Leave unavailable facts for a later phase."
            ),
            why_needed="Engineering Critic found an unverified load path. RUINFORM needs raw measurements, not engineering calculations from you.",
            property_key=f"critic_{tag.lower()}_{index}",
            required=False,
        )
    if tag == "HIDDEN_ASSUMPTION":
        return WorkshopEvidenceTask(
            task_id=f"critic_{_clean(tag)}_{index}",
            title="Inspect or test the assumed construction",
            input_kind="inspection",
            phase="now",
            instruction=(
                "State what is physically true or what you actually tested. If this concerns a joint/tab, say whether it is integral, separate, reinforced, or still untested. "
                "A close-up photo of the real sample is useful. Do not choose an answer just to satisfy the plan."
            ),
            why_needed=body or "Engineering Critic found an assumption that must be replaced by a workshop fact.",
            property_key=f"critic_{tag.lower()}_{index}",
        )
    if tag in {"LOW_PHYSICAL_CREDIBILITY", "UNSUPPORTED_MATERIAL_PROPERTY"}:
        return WorkshopEvidenceTask(
            task_id=f"critic_{_clean(tag)}_{index}",
            title="Test the real material or mechanism",
            input_kind="inspection",
            phase="now",
            instruction=(
                "Perform the smallest safe real-world test that answers the critic's question. Describe only what happened: flexed, cracked, slipped, held, sagged, rubbed, etc. "
                "Upload a photo if it helps document the result."
            ),
            why_needed=body or f"Engineering Critic requested evidence for {tag}.",
            property_key=f"critic_{tag.lower()}_{index}",
        )
    if tag == "SAFETY_GATE_MISSING":
        return WorkshopEvidenceTask(
            task_id=f"critic_{_clean(tag)}_{index}",
            title="Confirm installation constraints",
            input_kind="inspection",
            phase="before_installation",
            instruction=(
                "Record only verified installation facts: substrate, concealed-service check, hardware documentation, manufacturer limits, or other applicable constraints. "
                "Do not infer a load rating from appearance."
            ),
            why_needed=body or "Engineering Critic requires a verified safety gate before installation.",
            property_key=f"critic_{tag.lower()}_{index}",
        )
    return None


def derive_workshop_evidence_request(
    *,
    plan: BuildPlan,
    review: BuildCriticReview,
    candidate_id: str,
) -> WorkshopEvidenceRequest | None:
    if review.status == "pass":
        return None

    tasks: list[WorkshopEvidenceTask] = []
    seen: set[str] = set()

    def add(task: WorkshopEvidenceTask) -> None:
        if len(tasks) >= _MAX_TASKS or task.property_key in seen:
            return
        seen.add(task.property_key)
        tasks.append(task)

    for index, blocker in enumerate(review.blocking_unknowns[:2], start=1):
        add(
            WorkshopEvidenceTask(
                task_id=f"blocker_{index}",
                title="Resolve the blocking unknown with a real fact",
                input_kind="inspection",
                phase="now",
                instruction=(
                    "Inspect, measure, test, or obtain documentation for this unknown. Report the raw finding only. "
                    "If it cannot be known yet, say so instead of guessing."
                ),
                why_needed=blocker,
                property_key=f"blocking_unknown_{index}",
            )
        )

    for index, change in enumerate(review.required_changes, start=1):
        match = _TAG_RE.match(change.strip())
        if not match:
            continue
        tag, body = match.groups()
        task = _critic_task(tag, body.strip(), index)
        if task is not None:
            add(task)

    critic_text = " ".join(review.required_changes + review.blocking_unknowns + review.reasons)
    critic_tokens = _tokens(critic_text)
    ranked = sorted(
        plan.measurements_required,
        key=lambda measurement: (
            _measurement_score(measurement, critic_tokens),
            len(measurement.blocks_step_numbers),
        ),
        reverse=True,
    )

    # Include the most relevant measurements across phases. Later-stage facts stay visible
    # but do not block the active workshop phase.
    for measurement in ranked:
        phase = _measurement_phase(measurement)
        add(
            WorkshopEvidenceTask(
                task_id=f"measure_{_clean(measurement.measurement_id)}",
                title=f"Measure {measurement.measurement_id}",
                input_kind="measurement",
                phase=phase,
                instruction=f"{measurement.what_to_measure} {measurement.how_to_measure}",
                why_needed=measurement.used_for,
                property_key=f"measurement_{_clean(measurement.measurement_id)}",
            )
        )

    mounting_words = {"wall", "mount", "anchor", "standoff", "substrate", "drill", "support"}
    if mounting_words & critic_tokens:
        add(
            WorkshopEvidenceTask(
                task_id="mounting_location_photo",
                title="Photograph the intended mounting location",
                input_kind="photo",
                phase="now",
                instruction=(
                    "Take one wide photo of the intended mounting area and, if useful, one close-up. "
                    "In the note, state the wall/substrate only if you actually know it. Do not identify substrate from appearance alone."
                ),
                why_needed="The approved build depends on real wall clearance, substrate and anchoring conditions.",
                property_key="mounting_location_photo",
            )
        )

    if not tasks:
        add(
            WorkshopEvidenceTask(
                task_id="workshop_finding",
                title="Add one real workshop finding",
                input_kind="statement",
                phase="now",
                instruction=(
                    "Add one measured, inspected, tested, or manufacturer-documented fact that directly addresses the Engineering Critic. "
                    "Do not estimate dimensions from the render."
                ),
                why_needed="A new evidence round must add physical information, not another guess.",
                property_key="workshop_finding",
            )
        )

    tasks.sort(key=lambda task: (_PHASE_ORDER.index(task.phase), task.task_id))
    return WorkshopEvidenceRequest(
        version="build_evidence_request_v2",
        candidate_id=candidate_id,
        critic_status=review.status,
        tasks=tasks,
    )


def _control(task: WorkshopEvidenceTask) -> str:
    answer_name = f"answer__{task.task_id}"
    photo_name = f"photo__{task.task_id}"
    if task.input_kind == "photo":
        return (
            f"<label>EVIDENCE PHOTO</label><input type='file' name='{html.escape(photo_name, quote=True)}' "
            "accept='image/jpeg,image/png,image/webp'/>"
            f"<label>WHAT DO YOU KNOW? — optional</label><textarea name='{html.escape(answer_name, quote=True)}' rows='3' "
            "placeholder='Only facts you know: wall type, measured clearance, inspection finding...'></textarea>"
        )
    placeholder = (
        "Example: 2.4 kg, measured with a scale."
        if task.input_kind == "measurement"
        else "State only what you inspected, tested, measured, or documented."
    )
    return (
        f"<label>YOUR EVIDENCE</label><textarea name='{html.escape(answer_name, quote=True)}' rows='4' "
        f"placeholder='{html.escape(placeholder, quote=True)}'></textarea>"
        f"<label>OPTIONAL PHOTO</label><input type='file' name='{html.escape(photo_name, quote=True)}' "
        "accept='image/jpeg,image/png,image/webp'/>"
    )


def build_workshop_evidence_panel(
    *,
    session_id: str,
    plan: BuildPlan,
    review: BuildCriticReview | None,
    candidate_id: str | None,
    evidence_round_count: int,
) -> str:
    if review is None or review.status == "pass" or not candidate_id:
        return ""
    request = derive_workshop_evidence_request(plan=plan, review=review, candidate_id=candidate_id)
    if request is None or not request.tasks:
        return ""

    active_phase = next(phase for phase in _PHASE_ORDER if any(task.phase == phase for task in request.tasks))
    active_tasks = [task for task in request.tasks if task.phase == active_phase]
    later_tasks = [task for task in request.tasks if task.phase != active_phase]

    active_cards: list[str] = []
    for index, task in enumerate(active_tasks, start=1):
        active_cards.append(
            "<div class='card'>"
            f"<div class='k'>DO {index:02d} / {html.escape(task.input_kind.upper())}</div>"
            f"<h2>{html.escape(task.title)}</h2>"
            f"<p>{html.escape(task.instruction)}</p>"
            f"<p class='muted'><strong>Why:</strong> {html.escape(task.why_needed)}</p>"
            f"{_control(task)}</div>"
        )

    later_cards: list[str] = []
    for task in later_tasks:
        later_cards.append(
            "<div class='card'>"
            f"<div class='k'>LATER / {html.escape(_PHASE_LABELS[task.phase])}</div>"
            f"<h2>{html.escape(task.title)}</h2>"
            f"<p>{html.escape(task.instruction)}</p>"
            f"<p class='muted'><strong>Why:</strong> {html.escape(task.why_needed)}</p>"
            "<span class='badge'>LOCKED UNTIL THIS PHASE</span>"
            "</div>"
        )

    active_label = _PHASE_LABELS[active_phase]
    later_html = (
        f"<div class='rule'></div><div class='k'>WHAT COMES LATER</div><p class='muted'>These are future evidence gates. Do not fabricate them now; RUINFORM will ask again when that phase becomes physically possible.</p><div class='grid'>{''.join(later_cards)}</div>"
        if later_cards
        else ""
    )
    return f"""
<div class='panel critic-revise'>
<div class='k'>RFM-INT-0024.2 / WORKSHOP EVIDENCE / ROUND {evidence_round_count + 1}</div>
<h2>DO THIS {html.escape(active_label)}.</h2>
<p><strong>You provide raw facts. RUINFORM does the engineering.</strong> Measure, inspect, test, document, or photograph only what is physically available in this phase. You do not need to calculate moments, support reactions, safety factors, or hardware capacity.</p>
<p class='muted'>Partial evidence is normal. Submit any real fact or photo you can obtain now. Do not restart the project and do not regenerate the approved image.</p>
<form method='post' action='/studio/{html.escape(session_id)}/build/evidence' enctype='multipart/form-data' data-busy data-busy-title='ADDING EVIDENCE → RESUMING BUILD.'>
<div class='grid'>{''.join(active_cards)}</div>
<button type='submit'>ADD REAL EVIDENCE → RESUME BUILD</button>
</form>
{later_html}
<p class='muted'>Each evidence round remains bounded: one fresh Build Master draft, one Engineering Critic check, and at most one automatic repair. Later-phase tasks stay locked until they become physically possible.</p>
</div>
"""
