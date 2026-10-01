from ruinform_intelligence.build_master import load_build_master_prompt
from ruinform_intelligence.engineering_critic import load_engineering_critic_prompt


def test_build_master_treats_branch_parent_as_design_ancestry_not_inventory() -> None:
    prompt = load_build_master_prompt()
    assert "design ancestry only" in prompt
    assert "Never require the locked parent render or parent assembly itself to physically exist" in prompt
    assert "Do not reactivate unrelated historical source matter" in prompt
    assert "reconstruct the inherited parent subassembly" in prompt


def test_engineering_critic_does_not_block_on_unbuilt_parent_artwork() -> None:
    prompt = load_engineering_critic_prompt()
    assert "design ancestor ≠ physical inventory" in prompt
    assert "Do NOT block merely because the archived parent assembly has not been physically built" in prompt
    assert "unrelated historical matter remains provenance only" in prompt
    assert "missing ordinary dimensions" in prompt
    assert "measurements_required" in prompt
