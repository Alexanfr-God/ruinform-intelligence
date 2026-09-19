from __future__ import annotations

import html


def saved_output_panel(session) -> str:
    """Expose durable links back to the approved render/build from FUTURES.

    Concept pages are intentionally reusable, but that previously meant BACK TO FUTURES
    stranded users away from an already-approved render. Keep the render/build state
    reachable without rerendering or regenerating anything.
    """
    result = getattr(session, "render_result", None)
    if (
        result is None
        or getattr(result, "status", None) != "pass"
        or getattr(result, "accepted_image_url", None) is None
    ):
        return ""

    session_id = html.escape(session.session_id)
    links = [
        f"<a class='resume-link' href='/studio/{session_id}/render'>OPEN APPROVED RENDER</a>"
    ]
    if getattr(session, "build_plan", None) is not None:
        links.append(
            f"<a class='resume-link primary' href='/studio/{session_id}/build'>OPEN MAKE IT REAL</a>"
        )

    return (
        "<div class='panel saved-output-panel'>"
        "<div class='k'>SAVED OUTPUT / RESUME</div>"
        "<p class='muted'>This project already has an approved render. Resume it without spending image tokens again.</p>"
        "<div class='resume-links'>"
        + "".join(links)
        + "</div></div>"
        "<style>.resume-links{display:flex;gap:10px;flex-wrap:wrap}.resume-link{display:inline-block;text-decoration:none;border:1px solid #5c5448;padding:11px 13px;color:#eee8dd;background:#12110f;font-weight:700}.resume-link.primary{background:#e8e0d1;color:#111;border-color:#e8e0d1}</style>"
    )


def inject_saved_output_panel(body: str, session) -> str:
    panel = saved_output_panel(session)
    if not panel:
        return body
    anchor = "<div class='rule'></div><p><a href='/studio/"
    index = body.find(anchor)
    if index >= 0:
        return body[:index] + panel + body[index:]
    return body + panel


def inject_build_back_links(body: str, session) -> str:
    result = getattr(session, "render_result", None)
    if (
        result is None
        or getattr(result, "status", None) != "pass"
        or getattr(result, "accepted_image_url", None) is None
    ):
        return body

    session_id = html.escape(session.session_id)
    old = f"<p><a href='/studio/{session_id}/concepts'>BACK TO FUTURES</a></p>"
    new = (
        f"<p><a href='/studio/{session_id}/render'>BACK TO APPROVED RENDER</a>"
        f" &nbsp;·&nbsp; <a href='/studio/{session_id}/concepts'>BACK TO FUTURES</a></p>"
    )
    if old in body:
        return body.replace(old, new, 1)
    return body + new
