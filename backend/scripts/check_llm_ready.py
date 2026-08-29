"""LLM 凭据存在性检查（不输出任何 key 材料）。

用法（backend 目录下）：
    python scripts/check_llm_ready.py

输出凭据是否已配置（configured/missing）、provider、chat model、base_url。
用于 GLM key 接入前后的快速判定；密钥值本身永远不会被打印。
"""

from __future__ import annotations

import sys
from pathlib import Path

# 允许从仓库根目录直接运行：把 backend 加入 sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import settings  # noqa: E402


def main() -> int:
    configured = bool(settings.llm_credentials)
    providers = ", ".join(settings.configured_llm_providers) or "(none)"
    print(f"llm_credentials: {'configured' if configured else 'missing'}")
    print(f"llm_enabled: {settings.LLM_ENABLED}")
    print(f"providers: {providers}")
    print(f"chat_model: {settings.GLM_CHAT_MODEL}")
    print(f"embed_model: {settings.GLM_EMBED_MODEL}")
    print(f"base_url: {settings.GLM_BASE_URL}")
    if not configured:
        print(
            "hint: 开发环境在 backend/.env 写入 GLM_API_KEY=<key>；"
            "生产环境通过 LLM_PROVIDER=glm + LLM_API_KEY_FILE 文件挂载。"
            "本脚本不读取也不显示密钥值。"
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
