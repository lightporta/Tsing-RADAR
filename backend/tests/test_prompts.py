"""v4.0.0 任务1 A-3：提示词版本化加载测试（fail-closed 兜底）。"""

from __future__ import annotations

from pathlib import Path

from app.services.prompts import _CURRENT_VERSIONS, load_prompt_template


def _real_text(name: str) -> str:
    path = Path(__file__).resolve().parents[1] / "app" / "services" / "prompts"
    version = _CURRENT_VERSIONS[name]
    return (path / f"{name}_{version}.txt").read_text(encoding="utf-8").strip()


def test_load_versioned_template_matches_file():
    fallback = "fallback-system"
    loaded = load_prompt_template("system_prompt", fallback=fallback)
    assert loaded == _real_text("system_prompt")
    assert loaded != fallback
    assert "Tsing-RADAR" in loaded


def test_load_rewrite_template_matches_file():
    fallback = "fallback-rewrite"
    loaded = load_prompt_template("rewrite_template", fallback=fallback)
    assert loaded == _real_text("rewrite_template")
    assert loaded != fallback
    assert "记忆摘要" in loaded


def test_unknown_name_returns_fallback():
    assert load_prompt_template("no_such_template", fallback="fb") == "fb"


def test_version_mismatch_returns_fallback(monkeypatch):
    # 版本清单与代码期望不一致 → fail-closed 回退内嵌兜底
    monkeypatch.setitem(_CURRENT_VERSIONS, "system_prompt", "v999")
    assert load_prompt_template("system_prompt", fallback="fb") == "fb"


def test_missing_file_returns_fallback(monkeypatch, tmp_path):
    import app.services.prompts as prompts_mod

    monkeypatch.setattr(prompts_mod, "_PROMPTS_DIR", tmp_path)
    monkeypatch.setattr(
        prompts_mod,
        "_VERSIONS_PATH",
        tmp_path / "prompt_versions.json",
    )
    (tmp_path / "prompt_versions.json").write_text(
        '{"versions": {"system_prompt": {"current": "v1"}}}', encoding="utf-8"
    )
    assert load_prompt_template("system_prompt", fallback="fb") == "fb"


def test_corrupt_versions_json_returns_fallback(monkeypatch, tmp_path):
    import app.services.prompts as prompts_mod

    monkeypatch.setattr(
        prompts_mod, "_VERSIONS_PATH", tmp_path / "bad_versions.json"
    )
    (tmp_path / "bad_versions.json").write_text("{not json", encoding="utf-8")
    assert load_prompt_template("system_prompt", fallback="fb") == "fb"


def test_empty_template_file_returns_fallback(monkeypatch, tmp_path):
    import app.services.prompts as prompts_mod

    monkeypatch.setattr(prompts_mod, "_PROMPTS_DIR", tmp_path)
    monkeypatch.setattr(
        prompts_mod,
        "_VERSIONS_PATH",
        tmp_path / "prompt_versions.json",
    )
    (tmp_path / "prompt_versions.json").write_text(
        '{"versions": {"system_prompt": {"current": "v1"}}}', encoding="utf-8"
    )
    (tmp_path / "system_prompt_v1.txt").write_text("   \n", encoding="utf-8")
    assert load_prompt_template("system_prompt", fallback="fb") == "fb"
