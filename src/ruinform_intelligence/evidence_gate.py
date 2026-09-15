from __future__ import annotations

from .models import ProjectState


HIGH_CONSEQUENCE = "high"


def refresh_critical_unknowns(state: ProjectState) -> ProjectState:
    """Populate project-level critical unknown IDs from material-level unknowns."""
    critical = []
    for material in state.materials:
        for unknown in material.unknowns:
            if unknown.consequence_if_unresolved == HIGH_CONSEQUENCE:
                critical.append(unknown.unknown_id)
    state.unresolved_critical_unknowns = critical
    return state


def can_advance_to_ideation(state: ProjectState) -> bool:
    """Ideation is blocked while consequential physical uncertainty remains."""
    refresh_critical_unknowns(state)
    return len(state.unresolved_critical_unknowns) == 0
