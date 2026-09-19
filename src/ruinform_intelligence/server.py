from __future__ import annotations

import logging

from .api import app
from .build_evidence import count_candidate_evidence_rounds, state_for_build_candidate
from .evidence_api import router as evidence_loop_router
from .evidence_media import router as evidence_media_router
from .future_api import router as future_forms_router
from .idea_store import capture_session_ideas, mark_session_candidate_rendered
from .lab import router as lab_router
from .lab_postproduction import router as lab_postproduction_router
from .live_api import router as live_transformations_router
from .mvp_entry import router as mvp_entry_router
from .render_api import router as render_router
from .review_schema import prepare_review_store_schema
from .review_store import capture_session_render
from .self_healing_preview import generate_concept_preview as generate_self_healing_preview
from . import studio as studio_module
from .studio_build_evidence import router as studio_build_evidence_router
from .studio_controls import router as studio_controls_router
from .studio_evals import router as studio_evals_router
from .studio_ideas import router as studio_ideas_router
from .studio_resume_nav import inject_build_back_links, inject_saved_output_panel
from .studio_reviews import router as studio_reviews_router
from .workshop_evidence_ux import build_workshop_evidence_panel


logger = logging.getLogger(__name__)
studio_router = studio_module.router
_review_schema_prepared = False


def _ensure_review_schema() -> None:
    global _review_schema_prepared
    if _review_schema_prepared:
        return
    prepare_review_store_schema()
    _review_schema_prepared = True


# RFM-INT-0021 keeps the stable Studio route surface but swaps the concept-stage
# callable for a bounded one-pass self-healing wrapper. PASS ideas remain locked;
# REVISE/REJECT slots may be repaired/replaced once before the user sees them.
studio_module.generate_concept_preview = generate_self_healing_preview


# RFM-INT-0024.1 fixes a navigation trap: BACK TO FUTURES used to strand users away
# from an already-approved render/build even though the durable session still had both.
_original_concepts_page = studio_module._concepts_page


def _concepts_page_with_resume_links(session) -> str:
    return inject_saved_output_panel(_original_concepts_page(session), session)


studio_module._concepts_page = _concepts_page_with_resume_links


# RFM-INT-0024 keeps build evidence scoped to the approved candidate. Evidence from an
# earlier candidate may remain in the project audit trail, but it must never influence a
# different future merely because the user rendered another idea in the same session.
_original_reviewed_build_package = studio_module.generate_reviewed_build_package


async def _candidate_scoped_reviewed_build_package(**kwargs):
    future = kwargs["future"]
    kwargs["state"] = state_for_build_candidate(
        kwargs["state"],
        future.candidate.candidate_id,
    )
    return await _original_reviewed_build_package(**kwargs)


studio_module.generate_reviewed_build_package = _candidate_scoped_reviewed_build_package


# RFM-INT-0024.2 replaces the raw critic dump with a phase-aware workshop contract:
# the maker supplies simple measurements/observations/photos; RUINFORM derives engineering.
_original_build_page = studio_module._build_page


def _build_page_with_evidence_request(session) -> str:
    body = _original_build_page(session)
    if (
        session.build_plan is None
        or session.build_review is None
        or session.build_review.status == "pass"
        or not session.selected_candidate_id
    ):
        return body
    panel = build_workshop_evidence_panel(
        session_id=session.session_id,
        plan=session.build_plan,
        review=session.build_review,
        candidate_id=session.selected_candidate_id,
        evidence_round_count=count_candidate_evidence_rounds(
            session.project_state,
            session.selected_candidate_id,
        ),
    )
    if not panel:
        return body
    anchor = "<div class='grid'><div class='panel'><div class='k'>WHAT WE KNOW</div>"
    if anchor in body:
        return body.replace(anchor, panel + anchor, 1)
    return panel + body


studio_module._build_page = _build_page_with_evidence_request


# Keep a direct route back to the approved visual from MAKE IT REAL. This is deliberately
# a UI-only wrapper: no session state is changed and no model/image call is triggered.
_evidence_build_page = studio_module._build_page


def _build_page_with_resume_nav(session) -> str:
    return inject_build_back_links(_evidence_build_page(session), session)


studio_module._build_page = _build_page_with_resume_nav


# Keep the most-used Studio destinations visible on every Studio page.
# This wrapper is intentionally UI-only: it does not touch session state or the
# render/concept pipelines, so a user can always start fresh without hunting
# for /studio/new in chat history.
_original_studio_page = studio_module._page


def _studio_page_with_global_nav(body: str, *, title: str = "RUINFORM STUDIO") -> str:
    nav = """
<style>
.ruinform-global-nav{position:sticky;top:0;z-index:15;display:flex;justify-content:flex-end;gap:10px;padding:10px 0 16px;background:linear-gradient(#080807 72%,rgba(8,8,7,0));}
.ruinform-global-nav a{display:inline-block;text-decoration:none;border:1px solid #5c5448;background:#12110f;color:#eee8dd;padding:10px 13px;font-size:12px;font-weight:700;letter-spacing:.08em;}
.ruinform-global-nav a.primary{background:#e8e0d1;color:#111;border-color:#e8e0d1;}
@media(max-width:760px){.ruinform-global-nav{justify-content:stretch;flex-wrap:wrap}.ruinform-global-nav a{flex:1;text-align:center}}
</style>
<nav class='ruinform-global-nav' aria-label='Studio navigation'>
<a href='/studio/ideas'>IDEA ROOM</a>
<a href='/studio/reviews'>REVIEW INBOX</a>
<a href='/studio/evals'>EVAL LIBRARY</a>
<a class='primary' href='/studio/new'>+ NEW PROJECT</a>
</nav>
"""
    return _original_studio_page(nav + body, title=title)


_studio_page_with_global_nav._ruinform_nav_wrapped = True
studio_module._page = _studio_page_with_global_nav


@app.middleware("http")
async def _capture_wave3_memory(request, call_next):
    """Freeze generated thinking and approved visuals without slowing the hot path.

    Concept batches are captured after concept generation. Approved renders are
    captured after render generation. GET variants also backfill the current Studio
    state, which lets an already-generated project recover into the new rooms after
    deployment. Queue failures are isolated from the user's successful request.
    """

    response = await call_next(request)
    parts = request.url.path.strip("/").split("/")
    if not parts or parts[0] != "studio":
        return response

    try:
        # POST /studio/{session}/concepts and GET /studio/{session}/concepts
        if len(parts) == 3 and parts[2] == "concepts" and request.method in {"POST", "GET"}:
            session = studio_module._session(parts[1])
            capture_session_ideas(session)

        # POST /studio/{session}/render/{candidate}
        if len(parts) == 4 and parts[2] == "render" and request.method == "POST":
            _ensure_review_schema()
            session = studio_module._session(parts[1])
            capture_session_ideas(session)
            mark_session_candidate_rendered(session)
            capture_session_render(session)

        # GET /studio/{session}/render acts as a backfill path for existing approved renders.
        if len(parts) == 3 and parts[2] == "render" and request.method == "GET":
            _ensure_review_schema()
            session = studio_module._session(parts[1])
            capture_session_ideas(session)
            mark_session_candidate_rendered(session)
            capture_session_render(session)
    except Exception:  # pragma: no cover - memory capture must never break Studio
        logger.exception("Could not capture Wave 3 Studio memory")

    return response


app.include_router(evidence_loop_router)
app.include_router(evidence_media_router)
app.include_router(future_forms_router)
app.include_router(render_router)
app.include_router(live_transformations_router)
# Static Studio entry routes must be registered before the dynamic
# /studio/{session_id} routes, otherwise FastAPI treats names as session IDs.
app.include_router(mvp_entry_router)
app.include_router(studio_controls_router)
app.include_router(studio_evals_router)
app.include_router(studio_ideas_router)
app.include_router(studio_reviews_router)
# Evidence resume is a deeper Studio route. Register it before the main Studio router so
# it remains explicit and inspectable rather than becoming part of the legacy route surface.
app.include_router(studio_build_evidence_router)
app.include_router(studio_router)
# Register post-production before the legacy lab router so the enhanced
# render endpoint owns POST /lab/{session_id}/render/{candidate_id}.
app.include_router(lab_postproduction_router)
app.include_router(lab_router)
