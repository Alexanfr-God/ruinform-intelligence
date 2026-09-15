from __future__ import annotations

from openai import AsyncOpenAI

from .future_models import ReviewedFuture
from .models import ProjectState
from .render_models import RenderAttempt, RenderRequest, RenderResult
from .render_prompt import compile_render_request
from .render_provider import RenderProvider, RenderProviderError
from .render_review import enforce_render_gate
from .render_review_agent import RenderReviewAgentError, evaluate_render


MAX_RENDER_ATTEMPTS = 3


class RenderGatewayError(RuntimeError):
    pass


def _next_request(request: RenderRequest, instructions: list[str]) -> RenderRequest:
    if not instructions:
        instructions = ["Regenerate more faithfully to the approved Visual Brief and source matter."]
    directive = "\n\nREGENERATION DIRECTIVES:\n" + "\n".join(f"- {item}" for item in instructions)
    return request.model_copy(update={"prompt": request.prompt + directive})


async def render_future(
    *,
    state: ProjectState,
    future: ReviewedFuture,
    provider: RenderProvider,
    client: AsyncOpenAI | None = None,
    review_model: str | None = None,
    aspect_ratio: str = "4:5",
    max_attempts: int = MAX_RENDER_ATTEMPTS,
) -> RenderResult:
    if not 1 <= max_attempts <= 5:
        raise RenderGatewayError("max_attempts must be between 1 and 5")

    request = compile_render_request(state=state, future=future, aspect_ratio=aspect_ratio)
    attempts: list[RenderAttempt] = []

    for attempt_index in range(1, max_attempts + 1):
        try:
            render = await provider.render(request)
            raw_review = await evaluate_render(
                future=future,
                request=request,
                render=render,
                client=client,
                model=review_model,
            )
        except (RenderProviderError, RenderReviewAgentError, ValueError) as exc:
            raise RenderGatewayError(str(exc)) from exc

        review = enforce_render_gate(raw_review)
        attempts.append(
            RenderAttempt(
                attempt_index=attempt_index,
                request=request,
                render=render,
                critique=review,
            )
        )

        if review.status == "pass":
            return RenderResult(
                candidate_id=future.candidate.candidate_id,
                status="pass",
                accepted_image_url=render.image_url,
                attempts=attempts,
            )
        if review.status == "reject":
            break
        request = _next_request(request, review.regeneration_instructions)

    return RenderResult(
        candidate_id=future.candidate.candidate_id,
        status="failed",
        attempts=attempts,
        failure_reason="No render passed the visual trust gate within the allowed attempts.",
    )
