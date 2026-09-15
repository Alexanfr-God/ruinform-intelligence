from __future__ import annotations

from pydantic import BaseModel, Field

from .models import ClaimKind, ProjectState


class EvidenceContractIssue(BaseModel):
    code: str
    message: str
    observation_id: str | None = None
    evidence_id: str | None = None


class EvidenceContractReport(BaseModel):
    passed: bool
    issues: list[EvidenceContractIssue] = Field(default_factory=list)


class EvidenceContractError(ValueError):
    def __init__(self, report: EvidenceContractReport):
        self.report = report
        super().__init__("Evidence contract failed")


def validate_state_contract(state: ProjectState) -> EvidenceContractReport:
    issues: list[EvidenceContractIssue] = []

    evidence_by_id = {}
    for item in state.evidence:
        if item.evidence_id in evidence_by_id:
            issues.append(
                EvidenceContractIssue(
                    code="duplicate_evidence_id",
                    message=f"Duplicate evidence id: {item.evidence_id}",
                    evidence_id=item.evidence_id,
                )
            )
        evidence_by_id[item.evidence_id] = item

    observations_by_id = {}
    for material in state.materials:
        for observation in material.observations:
            if observation.observation_id in observations_by_id:
                issues.append(
                    EvidenceContractIssue(
                        code="duplicate_observation_id",
                        message=f"Duplicate observation id: {observation.observation_id}",
                        observation_id=observation.observation_id,
                    )
                )
            observations_by_id[observation.observation_id] = observation

    for material in state.materials:
        for observation in material.observations:
            if not observation.property_key:
                issues.append(
                    EvidenceContractIssue(
                        code="missing_property_key",
                        message="Every observation must have a stable property_key.",
                        observation_id=observation.observation_id,
                    )
                )

            if observation.claim_kind in {ClaimKind.FACT, ClaimKind.HYPOTHESIS} and not observation.evidence:
                issues.append(
                    EvidenceContractIssue(
                        code="ungrounded_claim",
                        message="Facts and hypotheses must cite at least one evidence item.",
                        observation_id=observation.observation_id,
                    )
                )

            for ref in observation.evidence:
                item = evidence_by_id.get(ref.evidence_id)
                if item is None:
                    issues.append(
                        EvidenceContractIssue(
                            code="unknown_evidence_ref",
                            message=f"Observation references missing evidence: {ref.evidence_id}",
                            observation_id=observation.observation_id,
                            evidence_id=ref.evidence_id,
                        )
                    )
                    continue
                if item.source_type != ref.source_type:
                    issues.append(
                        EvidenceContractIssue(
                            code="evidence_source_mismatch",
                            message=(
                                f"Evidence {ref.evidence_id} is {item.source_type}, "
                                f"but the observation cites it as {ref.source_type}."
                            ),
                            observation_id=observation.observation_id,
                            evidence_id=ref.evidence_id,
                        )
                    )

            if observation.change_type == "new" and observation.prior_observation_ids:
                issues.append(
                    EvidenceContractIssue(
                        code="new_claim_has_prior",
                        message="A new claim cannot point to prior observations.",
                        observation_id=observation.observation_id,
                    )
                )

            if observation.change_type != "new" and not observation.prior_observation_ids:
                issues.append(
                    EvidenceContractIssue(
                        code="claim_change_missing_prior",
                        message="Confirmed, revised, or contradicted claims must cite prior observation ids.",
                        observation_id=observation.observation_id,
                    )
                )

            for prior_id in observation.prior_observation_ids:
                prior = observations_by_id.get(prior_id)
                if prior is None:
                    issues.append(
                        EvidenceContractIssue(
                            code="unknown_prior_observation",
                            message=f"Unknown prior observation id: {prior_id}",
                            observation_id=observation.observation_id,
                        )
                    )
                    continue
                if (
                    observation.property_key
                    and prior.property_key
                    and observation.property_key != prior.property_key
                ):
                    issues.append(
                        EvidenceContractIssue(
                            code="prior_property_mismatch",
                            message=(
                                f"Prior observation {prior_id} belongs to {prior.property_key}, "
                                f"not {observation.property_key}."
                            ),
                            observation_id=observation.observation_id,
                        )
                    )

        for unknown in material.unknowns:
            if unknown.consequence_if_unresolved in {"medium", "high"} and not unknown.property_key:
                issues.append(
                    EvidenceContractIssue(
                        code="important_unknown_missing_property_key",
                        message="Medium/high consequence unknowns require a stable property_key.",
                    )
                )

    return EvidenceContractReport(passed=not issues, issues=issues)


def assert_state_contract(state: ProjectState) -> EvidenceContractReport:
    report = validate_state_contract(state)
    if not report.passed:
        raise EvidenceContractError(report)
    return report
