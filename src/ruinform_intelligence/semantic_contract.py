from __future__ import annotations

from .future_models import CandidateForm, FutureSemanticContract, SemanticRequirement


def _normalized(value: str) -> str:
    return " ".join(value.strip().split())


def freeze_semantic_contract(candidate: CandidateForm) -> FutureSemanticContract:
    """Create a stable, renderer-facing contract from the selected Future itself.

    The contract is deliberately derived only from the accepted Future. Render notes,
    critic feedback, retry directives, and presentation prompts are excluded so later
    repair passes cannot silently mutate the design specification.
    """

    requirements: list[SemanticRequirement] = []
    seen: set[str] = set()

    def add(requirement_id: str, kind: str, text: str) -> None:
        clean = _normalized(text)
        if not clean:
            return
        key = clean.casefold()
        if key in seen:
            return
        seen.add(key)
        requirements.append(
            SemanticRequirement(
                requirement_id=requirement_id,
                kind=kind,
                text=clean,
            )
        )

    add("future.one_line", "transformation", candidate.one_line)
    add("future.logic", "transformation", candidate.transformation_logic)

    for index, operation in enumerate(candidate.key_operations[:6], start=1):
        add(f"operation.{index:02d}", "operation", operation)

    for index, use in enumerate(candidate.material_uses[:8], start=1):
        note = f" — {use.note}" if use.note else ""
        add(
            f"material.{index:02d}",
            "material_role",
            f"{use.material_item_id}: {use.role}{note}",
        )

    return FutureSemanticContract(
        candidate_id=candidate.candidate_id,
        requirements=requirements,
    )
