from ruinform_intelligence.render_director import load_visual_director_prompt
from ruinform_intelligence.render_review_agent import load_prompt as load_render_critic_prompt


def test_visual_director_requires_visible_transformation_sequence() -> None:
    prompt = load_visual_director_prompt()
    assert "Semantic transformation fidelity" in prompt
    assert "start → transition → result" in prompt
    assert "Sequence / relationship" in prompt or "SEQUENCE / RELATIONSHIP" in prompt
    assert "do not collapse a progression into a cluster of equal repeated parts" in prompt


def test_render_critic_rejects_semantically_weak_but_pretty_render() -> None:
    prompt = load_render_critic_prompt()
    assert "Semantic geometry fidelity" in prompt
    assert "Presence of the correct objects/colors is not enough" in prompt or "correct objects/materials" in prompt
    assert "brief_fidelity_score` below 78" in prompt
    assert "link by link" in prompt
    assert "generic approximation" in prompt
    assert "SEQUENCE / RELATIONSHIP FIDELITY" in prompt
