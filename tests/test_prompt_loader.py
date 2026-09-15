from pathlib import Path

from ruinform_intelligence.prompt_loader import load_prompt_file


def test_prompt_loader_resolves_explicit_prompt_directory(monkeypatch, tmp_path) -> None:
    prompt_dir = tmp_path / "prompts"
    prompt_dir.mkdir()
    (prompt_dir / "material_eye.md").write_text("# Material Eye test", encoding="utf-8")
    monkeypatch.setenv("RUINFORM_PROMPTS_DIR", str(prompt_dir))
    monkeypatch.chdir(tmp_path)

    assert load_prompt_file("material_eye.md") == "# Material Eye test"


def test_prompt_loader_resolves_repository_prompt(monkeypatch) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    monkeypatch.delenv("RUINFORM_PROMPTS_DIR", raising=False)
    monkeypatch.chdir(repo_root)

    prompt = load_prompt_file("material_eye.md")
    assert prompt.startswith("# Material Eye")
