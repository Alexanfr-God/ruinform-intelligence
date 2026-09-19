from types import SimpleNamespace

from ruinform_intelligence.studio_resume_nav import (
    inject_build_back_links,
    inject_saved_output_panel,
    saved_output_panel,
)


def _session(*, with_render: bool = True, with_build: bool = False):
    render = None
    if with_render:
        render = SimpleNamespace(
            status="pass",
            accepted_image_url="data:image/png;base64,abc",
        )
    return SimpleNamespace(
        session_id="session-1",
        render_result=render,
        build_plan=object() if with_build else None,
    )


def test_saved_output_panel_links_back_to_render_and_build() -> None:
    panel = saved_output_panel(_session(with_build=True))
    assert "OPEN APPROVED RENDER" in panel
    assert "/studio/session-1/render" in panel
    assert "OPEN MAKE IT REAL" in panel
    assert "/studio/session-1/build" in panel


def test_saved_output_panel_absent_without_approved_render() -> None:
    assert saved_output_panel(_session(with_render=False)) == ""


def test_inject_saved_output_before_regenerate_link() -> None:
    body = "cards<div class='rule'></div><p><a href='/studio/session-1'>GENERATE A DIFFERENT SET</a></p>"
    enhanced = inject_saved_output_panel(body, _session(with_build=True))
    assert enhanced.index("SAVED OUTPUT / RESUME") < enhanced.index("GENERATE A DIFFERENT SET")


def test_build_page_gets_back_to_approved_render_link() -> None:
    body = "<p><a href='/studio/session-1/concepts'>BACK TO FUTURES</a></p>"
    enhanced = inject_build_back_links(body, _session(with_build=True))
    assert "BACK TO APPROVED RENDER" in enhanced
    assert "/studio/session-1/render" in enhanced
    assert "BACK TO FUTURES" in enhanced
