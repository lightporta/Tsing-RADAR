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


# —— v4.1.0 自然度增强：v2 模板合同 ——
# —— v4.2.0 多轮自然度：rewrite_template 升级 v3 ——
# —— v4.3.0 RADAR娘人设 + 三明治：双模板升级 v4 ——


def test_active_versions_are_current():
    assert _CURRENT_VERSIONS["system_prompt"] == "v4"
    assert _CURRENT_VERSIONS["rewrite_template"] == "v4"


def test_rewrite_template_carries_naturalness_contract():
    text = _real_text("rewrite_template")
    # 六条自然度要求的关键指令齐全
    for directive in (
        "承接方式要换着来",       # C：不每轮同一开场
        "融进句子里",             # D：选项不编号复述
        "禁止机器腔",             # E：客服腔/AI 自称禁令
        "自然停在问题上",         # F：不挂"请回答"尾巴
        "语气词",                 # F：松弛但不堆砌
        "像真人对话，不像模板播报",
    ):
        assert directive in text, directive
    # v4.2.0 多轮自然度要求（G/H，v4.3.0 顺延为 H/I）
    for directive in (
        "多轮要连贯",             # G：参考最近对话自然呼应
        "不要照搬其措辞",         # G：系统底稿仅作上下文
        "本轮开场必须与「上一轮话术」明显不同",  # C/G：防重复承接
        "篇幅贴合用户与阶段",     # H：镜像用户长度 + 阶段语气
    ):
        assert directive in text, directive
    # v4.3.0 三明治法则与四类钩子（B）
    for directive in (
        "三明治法则",
        "共情承接",
        "回忆钩子",
        "类比钩子",
        "延迟钩子",
        "反向钩子",
        "至少选一个",
    ):
        assert directive in text, directive
    # v4.3.0 上下文黏性与纯文本输出（I / 硬性要求 7）
    assert "首句必须承接上轮内容" in text
    assert "隐性提及一次" in text
    assert "不使用任何 Markdown 标记" in text
    # v1 事实红线全部保留
    for redline in (
        "必须完整保留服务端题目要传达的信息",
        "不得添加题目之外的新事实",
        "不得宣布画像已确认或匹配完成",
        "400 字",
        "原样保留其中的招募名称、截止日期",
        "原样保留其中的用户事实",
    ):
        assert redline in text, redline
    # v1 的全部 format 占位符保留（调用方 .format 不变）
    for placeholder in (
        "{user_message}",
        "{completed}",
        "{missing}",
        "{constraints}",
        "{question_prompt}",
        "{options}",
        "{recruitment_summary}",
        "{memory_summary}",
        "{recent_dialogue}",
        "{previous_reply}",
        "{turn_phase}",
        "{user_style_hint}",
    ):
        assert placeholder in text, placeholder


def test_system_prompt_v4_radar_girl_persona_keeps_control_rules():
    text = _real_text("system_prompt")
    # v1 控制规则保留（test_load_versioned_template_matches_file 也断言
    # "Tsing-RADAR" 在文本中）
    assert "服务端状态机控制" in text
    assert "不得输出控制标记" in text
    assert "不得自行宣布画像已确认或触发导师匹配" in text
    # v4.3.0 RADAR娘人设要素
    assert "RADAR娘" in text
    assert "选师经验" in text
    assert "避坑经验" in text
    assert "网络语气" in text
    assert "3~5 句" in text
    assert "emoji" in text
    # v2 机器腔禁令保留
    assert "客服" in text
    assert "语言模型" in text
