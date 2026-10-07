from __future__ import annotations

import base64
import json
import os

import httpx
from openai import AsyncOpenAI, OpenAIError

from .future_models import FutureSemanticContract, ReviewedFuture
from .prompt_loader import load_prompt_file
from .render_models import ProviderRender, RenderCritique, RenderRequest

DEFAULT_MODEL = "gpt-5.6"


class RenderReviewAgentError(RuntimeError):
    pass


def load_prompt() -> str:
    return load_prompt_file("render_critic.md")


async def evaluate_render(
    *,
    future: ReviewedFuture,
    semantic_contract: FutureSemanticContract,
    request: RenderRequest,
    render: ProviderRender,
    client: AsyncOpenAI | None = None,
    model: str | None = None,
    source_image_urls: list[str] | None = None,
) -> RenderCritique:
    if future.review.status == "reject":
        raise RenderReviewAgentError("Rejected futures may not be render-reviewed")
    if request.candidate_id != future.candidate.candidate_id:
        raise RenderReviewAgentError("Candidate mismatch")
    if semantic_contract.candidate_id != future.candidate.candidate_id:
        raise RenderReviewAgentError("Semantic contract candidate mismatch")

    stage_note = (
        "A renderer-safe VisualBrief is attached to the future."
        if future.visual_brief is not None
        else (
            "This is a concept-stage render without a separate VisualBrief. Source/reference images still define provenance and ancestry."
        )
    )
    contract_lines = "\n".join(
        f"- [{item.requirement_id}] ({item.kind}) {item.text}"
        for item in semantic_contract.requirements
    ) or "- No explicit transformation requirements were captured."
    allowed_ids = [item.requirement_id for item in semantic_contract.requirements]

    content: list[dict] = [
        {
            "type": "input_text",
            "text": (
                "Evaluate the generated concept image against the IMMUTABLE FUTURE CONTRACT below. "
                "This contract was frozen from the selected Future before rendering. It is the only source of hard semantic transformation requirements. "
                "The compiled render request, user render note, Visual Director text, and any CRITIC-GUIDED REGENERATION DIRECTIVES are implementation guidance only: they MUST NOT create new hard requirements, counts, topology, ordering, symmetry, or geometry that are absent from the immutable contract. "
                "You may still judge source/provenance honesty and generic physical plausibility independently.\n\n"
                f"Review stage: {stage_note}\n\n"
                f"IMMUTABLE FUTURE CONTRACT v1:\n{contract_lines}\n\n"
                f"VALID REQUIREMENT IDS: {json.dumps(allowed_ids)}\n\n"
                "For every semantic contract failure, put ONLY the corresponding IDs from VALID REQUIREMENT IDS into failed_contract_requirement_ids. "
                "Never invent an ID. Never add a requirement because a previous retry instruction suggested one. "
                "Regeneration instructions may explain how to better satisfy failed contract items, but must not narrow or expand the contract with new exact counts, new mandatory parts, or new topology.\n\n"
                f"Selected future context (informative, not permission to expand the contract): {future.model_dump_json()}\n\n"
                f"Current render request (implementation guidance, mutable across retries): {request.model_dump_json()}"
            ),
        },
    ]

    async def inline_image(value: str, downloader: httpx.AsyncClient) -> str:
        if value.startswith("data:image/"):
            return value
        if not value.startswith("https://"):
            raise RenderReviewAgentError("Unsupported render review image source")
        try:
            response = await downloader.get(value)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise RenderReviewAgentError(f"Could not load render review image: {exc}") from exc
        media_type = (response.headers.get("content-type") or "image/jpeg").split(";", 1)[0]
        return f"data:{media_type};base64,{base64.b64encode(response.content).decode('ascii')}"

    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as downloader:
        generated_image = await inline_image(str(render.image_url), downloader)
        content.append({"type": "input_image", "image_url": generated_image, "detail": "high"})

        reference_values = source_image_urls if source_image_urls is not None else [
            str(reference.image_url) for reference in request.references[:8]
        ]
        for value in reference_values[:8]:
            try:
                image_value = await inline_image(value, downloader)
            except RenderReviewAgentError:
                # One unavailable source reference must not destroy an otherwise valid
                # render. The immutable contract and remaining evidence still allow a
                # conservative review; missing provenance will naturally lower fidelity.
                continue
            content.append({"type": "input_image", "image_url": image_value, "detail": "high"})

    model = model or os.getenv("RUINFORM_RENDER_CRITIC_MODEL", DEFAULT_MODEL)
    client = client or AsyncOpenAI()
    try:
        response = await client.responses.create(
            model=model,
            reasoning={"effort": "high"},
            instructions=load_prompt(),
            input=[{"role": "user", "content": content}],
            text={
                "format": {
                    "type": "json_schema",
                    "name": "ruinform_render_review",
                    "strict": True,
                    "schema": RenderCritique.model_json_schema(),
                }
            },
        )
    except OpenAIError as exc:
        raise RenderReviewAgentError(f"Render review request failed: {exc}") from exc
    if not response.output_text:
        raise RenderReviewAgentError("Render review returned no structured output")
    try:
        review = RenderCritique.model_validate(json.loads(response.output_text))
    except (json.JSONDecodeError, ValueError) as exc:
        raise RenderReviewAgentError("Render review returned invalid structured output") from exc

    allowed = set(allowed_ids)
    filtered_ids = [
        requirement_id
        for requirement_id in review.failed_contract_requirement_ids
        if requirement_id in allowed
    ]
    if filtered_ids != review.failed_contract_requirement_ids:
        review = review.model_copy(update={"failed_contract_requirement_ids": filtered_ids})
    return review
