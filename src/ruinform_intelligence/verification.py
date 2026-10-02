from __future__ import annotations

import json
import os
from typing import Literal

from openai import AsyncOpenAI
from pydantic import BaseModel, ConfigDict, Field


DEFAULT_MODEL = "gpt-5.6"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class VerificationOutput(StrictModel):
    proof_status: Literal["valid", "invalid"]
    object_match_evaluated: bool
    overall_match: int | None = Field(ge=0, le=100)
    silhouette_match: int | None = Field(ge=0, le=100)
    material_match: int | None = Field(ge=0, le=100)
    construction_match: int | None = Field(ge=0, le=100)
    detail_match: int | None = Field(ge=0, le=100)
    confidence: int | None = Field(ge=0, le=100)
    challenge_code_visible_in_all: bool
    challenge_code_match_confidence: int = Field(ge=0, le=100)
    challenge_observations: list[str]
    verdict: Literal["invalid_proof", "strong_match", "partial_match", "weak_match"]
    summary: str
    matching_features: list[str]
    deviations: list[str]
    next_capture_request: str | None


class VerificationError(RuntimeError):
    pass


def _schema() -> dict:
    return VerificationOutput.model_json_schema()


def _input(
    *,
    reference_image_url: str,
    build_image_urls: list[str],
    concept_name: str | None,
    concept_description: str | None,
    expected_challenge_code: str,
) -> list[dict]:
    content: list[dict] = [
        {
            "type": "input_text",
            "text": (
                "You are RUINFORM Verify. Verification has TWO SEPARATE GATES and they must never be blended.\n\n"
                "GATE 1 — LIVE PROOF VALIDITY:\n"
                "First decide whether the submitted photographs are credible fresh live-camera evidence. Do not score the object yet.\n"
                f"- Expected one-time code: {expected_challenge_code}\n"
                "- The exact code must be visibly legible in EVERY submitted physical-build photo on a real paper/card or other physical marker in the photographed scene.\n"
                "- A digital overlay, app UI text, screenshot annotation, edited caption, or code visible only in the generated reference does NOT satisfy the challenge.\n"
                "- For challenge_observations, report one concise observation per submitted physical photo, including whether the expected code is legible and physically present.\n"
                "- challenge_code_match_confidence measures only confidence in the physical code-presence judgment.\n"
                "- Repeated/near-duplicate views or copied reference imagery are not credible independent proof.\n"
                "- If the expected code is missing, wrong, obscured, digitally overlaid, or absent from ANY required photo, proof_status MUST be invalid.\n"
                "- If proof_status is invalid: object_match_evaluated=false; verdict=invalid_proof; overall_match, silhouette_match, material_match, construction_match, detail_match and confidence MUST ALL be null. Do not award a 0-10 object score. matching_features and deviations should be empty because object similarity was not evaluated. Explain only why proof failed and request a new live capture.\n\n"
                "GATE 2 — OBJECT MATCH:\n"
                "Run this gate ONLY when proof_status=valid. Compare the generated design reference against the valid photographs of the physical object. Score visual design fidelity, not photographic similarity. Camera angle, lighting, crop, lens, background and normal hand-made imperfections must not be penalized by themselves. Focus on silhouette/proportion, material identity and placement, construction logic/major joins, and distinctive details.\n"
                "- When proof_status=valid: object_match_evaluated=true and every object-match score must be an integer 0-100.\n"
                "- strong_match: major form and distinctive design language are clearly preserved with strong evidence.\n"
                "- partial_match: the concept is recognizable but meaningful geometry/material/detail differences exist or coverage is limited.\n"
                "- weak_match: valid live proof shows an object that does not sufficiently preserve the target concept.\n"
                "- A different object from the same broad category (for example another black remote) must score based on the defining transformation, construction and details, not category/color resemblance alone.\n"
                "- If all views repeat substantially the same angle, lower confidence and request a meaningfully different side/rear/detail view.\n\n"
                "Never claim structural safety, authenticity, material chemistry, ownership, or engineering certification.\n\n"
                f"Concept name: {concept_name or 'selected RUINFORM future'}\n"
                f"Concept description: {concept_description or 'no additional description supplied'}\n"
                f"Physical photo count: {len(build_image_urls)}"
            ),
        },
        {"type": "input_text", "text": "GENERATED DESIGN REFERENCE — target visual direction, never physical proof:"},
        {"type": "input_image", "image_url": reference_image_url, "detail": "high"},
    ]
    for index, image_url in enumerate(build_image_urls, start=1):
        content.append({"type": "input_text", "text": f"SUBMITTED LIVE-CAMERA PHOTO {index}:"})
        content.append({"type": "input_image", "image_url": image_url, "detail": "high"})
    content.append(
        {
            "type": "input_text",
            "text": (
                "Return the structured two-gate assessment. Gate 1 is binary proof validity. "
                "Never expose an object similarity score when Gate 1 fails. Only after Gate 1 passes may Gate 2 produce object-match scores. "
                "Keep observations, matching_features and deviations concise, concrete and visible in the supplied evidence."
            ),
        }
    )
    return [{"role": "user", "content": content}]


async def verify_physical_build(
    *,
    reference_image_url: str,
    build_image_urls: list[str],
    expected_challenge_code: str,
    concept_name: str | None = None,
    concept_description: str | None = None,
    client: AsyncOpenAI | None = None,
    model: str | None = None,
) -> VerificationOutput:
    if not reference_image_url:
        raise ValueError("A rendered design reference is required")
    if not 2 <= len(build_image_urls) <= 3:
        raise ValueError("Upload 2 or 3 physical build photos for verification")
    expected_challenge_code = expected_challenge_code.strip().upper()
    if len(expected_challenge_code) != 4:
        raise ValueError("A valid 4-character live verification challenge is required")

    client = client or AsyncOpenAI()
    model = model or os.getenv("RUINFORM_VERIFICATION_MODEL", DEFAULT_MODEL)
    try:
        response = await client.responses.create(
            model=model,
            instructions=(
                "Be conservative, visual, and evidence-bound. Verification is sequential: first validate fresh live proof, then — only if valid — evaluate object match. "
                "Never turn an invalid challenge into a low object score. Never reward a result just because it is aesthetically pleasing. "
                "Never infer unseen sides. Do not let copied reference imagery, digital overlays, or repeated near-identical views inflate confidence. "
                "An object match is a design-comparison aid, not a safety, ownership, material, or authenticity certificate."
            ),
            input=_input(
                reference_image_url=reference_image_url,
                build_image_urls=build_image_urls,
                concept_name=concept_name,
                concept_description=concept_description,
                expected_challenge_code=expected_challenge_code,
            ),
            text={
                "format": {
                    "type": "json_schema",
                    "name": "ruinform_build_verification",
                    "strict": True,
                    "schema": _schema(),
                }
            },
        )
    except Exception as exc:
        raise VerificationError(f"Verification model failed: {exc}") from exc

    if not response.output_text:
        raise VerificationError("Verification model returned no structured output")
    try:
        result = VerificationOutput.model_validate(json.loads(response.output_text))
    except (json.JSONDecodeError, ValueError) as exc:
        raise VerificationError("Verification model returned invalid structured output") from exc

    score_fields = (
        result.overall_match,
        result.silhouette_match,
        result.material_match,
        result.construction_match,
        result.detail_match,
        result.confidence,
    )
    if result.proof_status == "invalid":
        if result.object_match_evaluated or result.verdict != "invalid_proof" or any(value is not None for value in score_fields):
            raise VerificationError("Verification model mixed invalid proof with object-match scoring")
    else:
        if (
            not result.challenge_code_visible_in_all
            or not result.object_match_evaluated
            or result.verdict == "invalid_proof"
            or any(value is None for value in score_fields)
        ):
            raise VerificationError("Verification model returned an inconsistent valid-proof assessment")
    return result
