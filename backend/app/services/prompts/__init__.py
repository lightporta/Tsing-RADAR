"""v4.0.0 任务1 A-3：提示词版本化加载。

模板文件位于本目录（system_prompt_v1.txt / rewrite_template_v1.txt），
prompt_versions.json 登记各模板当前版本与变更说明。约定：
- 模板变更必须新增版本文件并在 prompt_versions.json 登记，不得原地覆盖；
- 运行期任何加载失败（文件缺失/损坏/版本清单不一致）→ 返回代码内嵌的
  v1 兜底文本，保证与 v3.1.x 行为完全一致（fail-closed 降级）。
"""

from __future__ import annotations

import json
from pathlib import Path

_PROMPTS_DIR = Path(__file__).resolve().parent
_VERSIONS_PATH = _PROMPTS_DIR / "prompt_versions.json"

# 各模板当前支持/期望的版本（与 prompt_versions.json 对照，不一致即兜底）
# v4.1.0：升级 v2（自然度增强：人设 + 机器腔禁令 + 承接方式轮换）。
_CURRENT_VERSIONS: dict[str, str] = {
    "system_prompt": "v2",
    "rewrite_template": "v2",
}


def _read_versions() -> dict:
    try:
        payload = json.loads(_VERSIONS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def load_prompt_template(name: str, *, fallback: str) -> str:
    """加载版本化模板文本；任何失败返回内嵌兜底（不抛异常）。"""
    expected = _CURRENT_VERSIONS.get(name)
    if expected is None:
        return fallback
    versions = _read_versions()
    declared = (versions.get("versions") or {}).get(name, {}).get("current")
    if declared != expected:
        return fallback
    try:
        text = (_PROMPTS_DIR / f"{name}_{expected}.txt").read_text(
            encoding="utf-8"
        )
    except OSError:
        return fallback
    text = text.strip()
    if not text:
        return fallback
    return text
