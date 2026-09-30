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
    overall_match: int = Field(ge=0, le=100)
    silhouette_match: int = Field(ge=0, le=100)
    material_match: int = Field(ge=0, le=100)
    construction_match: int = Field(ge=0, le=100)
    detail_match: int = Field(ge=0, le=100)
    confidence: int = Field(ge=0, le=100)
    verdict: Literal["strong_match", "partial_match", "weak_match"]
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
) -> list[dict]:
    content: list[dict] = [
        {
            "type": "input_text",
            "text": (
                "You are RUINFORM Verify. Compare a generated design reference against photographs "
                "of the physical object that a person actually built. Score visual design fidelity, not "
                "photographic similarity. Camera angle, lighting, crop, lens, background and normal hand-made "
                "imperfections must not be penalized by themselves. Focus on silhouette/proportion, material "
                "identity and placement, construction logic/major joins, and distinctive details. Do not claim "
                "structural safety, authenticity, material chemistry, ownership, or engineering certification. "
                "If the photos do not show enough of the object, reduce confidence and explain what view is missing.\n\n"
                "EVIDENCE VALIDITY RULES:\n"
                "- Physical-build photos must be independent photographic evidence of a real object.\n"
                "- If a submitted physical photo appears to be the generated reference itself, a screenshot/export of it, "
                "or a near-identical digital copy with the same framing, background, lighting and image details, treat that "
                "photo as invalid evidence. If all submitted evidence is invalid this way, use weak_match, overall_match <= 10, "
                "confidence <= 20, and request real photographs of the physical object.\n"
                "- Repeated or near-duplicate physical photos count as one view, not multiple independent views. If all physical "
                "photos repeat substantially the same angle, confidence must be <= 65 and next_capture_request must ask for a "
                "meaningfully different side/rear/detail view. Do not award strong_match merely because the same view was repeated.\n"
                "- A very high score requires visible agreement in the actual object, not pixel-level similarity caused by reused digital imagery.\n\n"
                f"Concept name: {concept_name or 'selected RUINFORM future'}\n"
                f"Concept description: {concept_description or 'no additional description supplied'}\n"
                f"Physical photo count: {len(build_image_urls)}"
            ),
        },
        {"type": "input_text", "text": "GENERATED DESIGN REFERENCE — this is the target visual direction:"},
        {"type": "input_image", "image_url": reference_image_url, "detail": "high"},
    ]
    for index, image_url in enumerate(build_image_urls, start=1):
        content.append({"type": "input_text", "text": f"PHYSICAL BUILD PHOTO {index}:"})
        content.append({"type": "input_image", "image_url": image_url, "detail": "high"})
    content.append(
        {
            "type": "input_text",
            "text": (
                "Return a calibrated physical-build visual match assessment. overall_match is the headline verified-build "
                "fidelity score, so evidence quality matters: do not turn raw pixel/image similarity into a verification score. "
                "Use strong_match only when the major form and distinctive design language are clearly preserved by valid physical evidence; "
                "partial_match when the concept is recognizable but meaningful geometry/material/detail differences exist or coverage is limited; "
                "weak_match when the built object does not visually preserve the concept or when the supplied evidence is not credible physical evidence. "
                "Keep matching_features and deviations concise and observable."
            ),
        }
    )
    return [{"role": "user", "content": content}]


async def verify_physical_build(
    *,
    reference_image_url: str,
    build_image_urls: list[str],
    concept_name: str | None = None,
    concept_description: str | None = None,
    client: AsyncOpenAI | None = None,
    model: str | None = None,
) -> VerificationOutput:
    if not reference_image_url:
        raise ValueError("A rendered design reference is required")
    if not 2 <= len(build_image_urls) <= 3:
        raise ValueError("Upload 2 or 3 physical build photos for verification")

    client = client or AsyncOpenAI()
    model = model or os.getenv("RUINFORM_VERIFICATION_MODEL", DEFAULT_MODEL)
    try:
        response = await client.responses.create(
            model=model,
            instructions=(
                "Be conservative, visual, and evidence-bound. Never reward a result just because it is aesthetically pleasing. "
                "Never infer unseen sides. First judge whether the submitted physical photos are credible, independent views of a real build. "
                "Do not let copied reference imagery or repeated near-identical views inflate match or confidence. "
                "A match score is a design-comparison aid, not a safety or authenticity certificate."
            ),
            input=_input(
                reference_image_url=reference_image_url,
                build_image_urls=build_image_urls,
                concept_name=concept_name,
                concept_description=concept_description,
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
        return VerificationOutput.model_validate(json.loads(response.output_text))
    except (json.JSONDecodeError, ValueError) as exc:
        raise VerificationError("Verification model returned invalid structured output") from exc
