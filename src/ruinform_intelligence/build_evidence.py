from __future__ import annotations

import base64
import html
import re
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict

from .build_models import BuildCriticReview, BuildPlan
from .models import EvidenceItem, ProjectState


EvidenceInputKind = Literal["measurement", "inspection", "photo", "statement"]
_ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
_MAX_IMAGE_BYTES = 8 * 1024 * 1024
_MAX_TASKS = 5
_BUILD_PREFIX = "build:"
_WORD_RE = re.compile(r"[a-z0-9_]+", re.IGNORECASE)
_TAG_RE = re.compile(r"^\[([A-Z0-9_]+)\]\s*(.*)$", re.DOTALL)
_PHYSICAL_VALUE_RE = re.compile(
    r"(?<![A-Za-z0-9_])(\d+(?:[\.,]\d+)?)\s*(mm|cm|m|inches|inch|in|ft|feet|kg|g|lbs|lb|N|Nm|V|A|W|degrees|degree|deg|°C|°F)(?![A-Za-z0-9_])",
    re.IGNORECASE,
)
_STOP_WORDS = {
    "the", "and", "or", "a", "an", "to", "of", "for", "with", "from", "is", "are",
    "be", "before", "after", "that", "this", "its", "into", "using", "use", "used", "real",
    "actual", "plan", "build", "step", "steps", "required", "verify", "verified", "selected",
}
_EVIDENCE_TAGS: dict[str, EvidenceInputKind] = {
    "INVENTED_DIMENSION": "measurement",
    "MISSING_MEASUREMENT": "measurement",
    "UNVERIFIED_LOAD": "measurement",
    "HIDDEN_ASSUMPTION": "inspection",
    "LOW_PHYSICAL_CREDIBILITY": "inspection",
    "SAFETY_GATE_MISSING": "inspection",
    "UNSUPPORTED_MATERIAL_PROPERTY": "inspection",
}


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BuildEvidenceTask(StrictModel):
    task_id: str
    title: str
    input_kind: EvidenceInputKind
    instruction: str
    why_needed: str
    property_key: str
    required: bool = True


class BuildEvidenceRequest(StrictModel):
    version: str
    candidate_id: str
    critic_status: Literal["revise", "block"]
    tasks: list[BuildEvidenceTask]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _tokens(text: str) -> set[str]:
    return {
        token.lower()
        for token in _WORD_RE.findall(text or "")
        if len(token) >= 3 and token.lower() not in _STOP_WORDS
    }


def _clean_task_id(value: str) -> str:
    clean = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return clean[:54] or "evidence"


def _measurement_score(measurement, critic_tokens: set[str]) -> int:
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


def derive_build_evidence_request(
    *,
    plan: BuildPlan,
    review: BuildCriticReview,
    candidate_id: str,
) -> BuildEvidenceRequest | None:
    if review.status == "pass":
        return None

    tasks: list[BuildEvidenceTask] = []
    seen_keys: set[str] = set()

    def add(task: BuildEvidenceTask) -> None:
        if len(tasks) >= _MAX_TASKS or task.property_key in seen_keys:
            return
        seen_keys.add(task.property_key)
        tasks.append(task)

    # Genuine blockers should be visible to the user even when the Build Master did not
    # phrase them as a formal measurement requirement.
    for index, blocker in enumerate(review.blocking_unknowns[:2], start=1):
        add(
            BuildEvidenceTask(
                task_id=f"blocker_{index}",
                title="Resolve blocking unknown",
                input_kind="inspection",
                instruction=blocker,
                why_needed="Engineering Critic marked this fact as blocking the build handoff.",
                property_key=f"blocking_unknown_{index}",
            )
        )

    # Some critic tags are specifically asking for physical evidence rather than another
    # prose rewrite. Surface those as concrete workshop missions.
    for index, change in enumerate(review.required_changes, start=1):
        match = _TAG_RE.match(change.strip())
        if not match:
            continue
        tag, body = match.groups()
        kind = _EVIDENCE_TAGS.get(tag)
        if kind is None:
            continue
        body = body.strip() or change.strip()
        add(
            BuildEvidenceTask(
                task_id=f"critic_{_clean_task_id(tag)}_{index}",
                title=tag.replace("_", " ").title(),
                input_kind=kind,
                instruction=body,
                why_needed=f"Engineering Critic requested evidence for {tag}.",
                property_key=f"critic_{tag.lower()}_{index}",
            )
        )

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

    # Prefer measurements that relate to the final critic. If lexical matching is weak,
    # still surface the highest-impact blocked measurements so the user has a path forward.
    for measurement in ranked:
        score = _measurement_score(measurement, critic_tokens)
        if score <= 0 and tasks:
            continue
        add(
            BuildEvidenceTask(
                task_id=f"measure_{_clean_task_id(measurement.measurement_id)}",
                title=f"Measure {measurement.measurement_id}",
                input_kind="measurement",
                instruction=f"{measurement.what_to_measure} {measurement.how_to_measure}",
                why_needed=measurement.used_for,
                property_key=f"measurement_{_clean_task_id(measurement.measurement_id)}",
            )
        )
        if len(tasks) >= 4:
            break

    if len(tasks) < 4:
        for measurement in ranked:
            add(
                BuildEvidenceTask(
                    task_id=f"measure_{_clean_task_id(measurement.measurement_id)}",
                    title=f"Measure {measurement.measurement_id}",
                    input_kind="measurement",
                    instruction=f"{measurement.what_to_measure} {measurement.how_to_measure}",
                    why_needed=measurement.used_for,
                    property_key=f"measurement_{_clean_task_id(measurement.measurement_id)}",
                )
            )
            if len(tasks) >= 4:
                break

    mounting_words = {"wall", "mount", "anchor", "standoff", "substrate", "drill", "support"}
    if mounting_words & critic_tokens and len(tasks) < _MAX_TASKS:
        add(
            BuildEvidenceTask(
                task_id="mounting_location_photo",
                title="Photograph the intended mounting location",
                input_kind="photo",
                instruction=(
                    "Upload a clear wide photo and, if useful, a close-up of the intended mounting area. "
                    "In the note, identify the wall/substrate if you actually know it; do not guess from appearance."
                ),
                why_needed="The approved build depends on real wall clearance, substrate and anchoring conditions.",
                property_key="mounting_location_photo",
            )
        )

    if not tasks:
        # Non-pass with no extractable evidence task means the remaining problem is mostly a
        # plan defect. Keep the workflow honest rather than inventing a fake measurement.
        add(
            BuildEvidenceTask(
                task_id="workshop_finding",
                title="Add a real workshop finding",
                input_kind="statement",
                instruction=(
                    "Add only a measured, inspected, tested, or manufacturer-documented fact that directly addresses "
                    "the Engineering Critic. Do not estimate dimensions from the render."
                ),
                why_needed="A new evidence round must add physical information, not another guess.",
                property_key="workshop_finding",
            )
        )

    return BuildEvidenceRequest(
        version="build_evidence_request_v1",
        candidate_id=candidate_id,
        critic_status=review.status,
        tasks=tasks,
    )


def build_evidence_prefix(candidate_id: str) -> str:
    return f"{_BUILD_PREFIX}{candidate_id}:"


def evidence_property_key(candidate_id: str, task: BuildEvidenceTask) -> str:
    return f"{build_evidence_prefix(candidate_id)}{task.property_key}"


def state_for_build_candidate(state: ProjectState, candidate_id: str) -> ProjectState:
    prefix = build_evidence_prefix(candidate_id)
    evidence = [
        item
        for item in state.evidence
        if not (item.property_key or "").startswith(_BUILD_PREFIX)
        or (item.property_key or "").startswith(prefix)
    ]
    return state.model_copy(update={"evidence": evidence})


def build_evidence_image_urls(state: ProjectState, candidate_id: str) -> list[str]:
    prefix = build_evidence_prefix(candidate_id)
    return [
        item.uri
        for item in state.evidence
        if item.source_type == "image"
        and item.uri
        and (item.property_key or "").startswith(prefix)
    ]


def parse_physical_value(text: str) -> tuple[float | None, str | None]:
    match = _PHYSICAL_VALUE_RE.search(text or "")
    if not match:
        return None, None
    value_raw, unit = match.groups()
    try:
        value = float(value_raw.replace(",", "."))
    except ValueError:
        return None, None
    return value, unit


async def upload_to_data_url(upload, *, max_bytes: int = _MAX_IMAGE_BYTES) -> str:
    media_type = getattr(upload, "content_type", None) or ""
    if media_type not in _ALLOWED_IMAGE_TYPES:
        raise ValueError(f"Unsupported evidence image type: {media_type or 'unknown'}")
    raw = await upload.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise ValueError("Evidence image exceeds 8 MB")
    if not raw:
        raise ValueError("Evidence image is empty")
    return f"data:{media_type};base64,{base64.b64encode(raw).decode('ascii')}"


def build_evidence_panel(
    *,
    session_id: str,
    plan: BuildPlan,
    review: BuildCriticReview | None,
    candidate_id: str | None,
    evidence_round_count: int,
) -> str:
    if review is None or review.status == "pass" or not candidate_id:
        return ""
    request = derive_build_evidence_request(plan=plan, review=review, candidate_id=candidate_id)
    if request is None:
        return ""

    cards: list[str] = []
    for index, task in enumerate(request.tasks, start=1):
        answer_name = f"answer__{task.task_id}"
        photo_name = f"photo__{task.task_id}"
        if task.input_kind == "photo":
            control = (
                f"<label>EVIDENCE PHOTO</label><input type='file' name='{html.escape(photo_name, quote=True)}' "
                "accept='image/jpeg,image/png,image/webp'/>"
                f"<label>WHAT DO YOU KNOW? — optional</label><textarea name='{html.escape(answer_name, quote=True)}' rows='3' "
                "placeholder='Known wall type, location, clearance, inspection finding...'></textarea>"
            )
        else:
            placeholder = (
                "Example: 2.4 kg, measured with a scale."
                if task.input_kind == "measurement"
                else "State only what you inspected, tested, measured, or documented."
            )
            control = (
                f"<label>YOUR EVIDENCE</label><textarea name='{html.escape(answer_name, quote=True)}' rows='4' "
                f"placeholder='{html.escape(placeholder, quote=True)}'></textarea>"
                f"<label>OPTIONAL PHOTO</label><input type='file' name='{html.escape(photo_name, quote=True)}' "
                "accept='image/jpeg,image/png,image/webp'/>"
            )
        cards.append(
            "<div class='card'>"
            f"<div class='k'>NEED {index:02d} / {html.escape(task.input_kind.upper())}</div>"
            f"<h2>{html.escape(task.title)}</h2>"
            f"<p>{html.escape(task.instruction)}</p>"
            f"<p class='muted'><strong>Why:</strong> {html.escape(task.why_needed)}</p>"
            f"{control}</div>"
        )

    return f"""
<div class='panel critic-revise'>
<div class='k'>RFM-INT-0024 / EVIDENCE REQUEST / ROUND {evidence_round_count + 1}</div>
<h2>RUINFORM NEEDS REAL-WORLD EVIDENCE.</h2>
<p>Do not restart the project and do not regenerate the image. Add measurements, inspection findings or photos from the real object/workshop. RUINFORM will resume the same approved render and run one fresh bounded Build Master → Engineering Critic round.</p>
<form method='post' action='/studio/{html.escape(session_id)}/build/evidence' enctype='multipart/form-data' data-busy data-busy-title='ADDING EVIDENCE → RESUMING BUILD.'>
<div class='grid'>{''.join(cards)}</div>
<button type='submit'>ADD EVIDENCE → RESUME BUILD</button>
</form>
<p class='muted'>At least one task must contain a real answer or photo. A new evidence round is not a recursive repair loop: each round still gets at most one automatic plan repair.</p>
</div>
"""


def count_candidate_evidence_rounds(state: ProjectState, candidate_id: str) -> int:
    prefix = f"{build_evidence_prefix(candidate_id)}round_"
    return sum(1 for item in state.evidence if (item.property_key or "").startswith(prefix))


def round_marker(candidate_id: str, round_number: int, evidence_ids: list[str], before: str, after: str) -> EvidenceItem:
    return EvidenceItem(
        evidence_id=f"build_round_{candidate_id}_{round_number}",
        source_type="tool_result",
        property_key=f"{build_evidence_prefix(candidate_id)}round_{round_number}",
        text=(
            f"Build evidence round {round_number}: added {len(evidence_ids)} evidence item(s); "
            f"Engineering Critic {before.upper()} → {after.upper()}."
        ),
        created_at_iso=utc_now_iso(),
    )
