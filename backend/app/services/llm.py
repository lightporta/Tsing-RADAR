"""通用 LLM 与向量服务。

开发环境可配置 GLM_API_KEY 或 DEEPSEEK_API_KEY；生产环境只接受
LLM_PROVIDER + LLM_API_KEY_FILE，并在 Settings 构造时一次性解析。
A3 访谈题序、画像状态与确认门不由 LLM 决定。
"""

import json
from typing import Any, Optional

import httpx

from app.core.config import settings
from app.schemas.advisor import LLMMessage

# 通用文本提示词；严禁模型自行发出访谈控制标记。
LLM_SYSTEM_PROMPT = (
    "你是 Tsing-RADAR 文本助手。动态访谈的题序、画像状态和确认门由服务端状态机控制。"
    "不得输出控制标记，不得自行宣布画像已确认或触发导师匹配。"
)


def _build_payload_messages(messages: list[LLMMessage]) -> list[dict[str, str]]:
    return [{"role": "system", "content": LLM_SYSTEM_PROMPT}] + [
        {"role": m.role, "content": m.content} for m in messages
    ]


async def llm_complete(messages: list[LLMMessage]) -> Optional[str]:
    """调用 LLM 获取完整回复文本。

    开发环境保持 GLM 优先、失败后回退 DeepSeek；生产只有显式 provider。
    """
    payload_messages = _build_payload_messages(messages)
    provider_config = {
        "glm": (settings.GLM_BASE_URL, settings.GLM_CHAT_MODEL),
        "deepseek": (
            settings.DEEPSEEK_BASE_URL,
            settings.DEEPSEEK_CHAT_MODEL,
        ),
    }
    for provider, api_key in settings.llm_credentials:
        base_url, model = provider_config[provider]
        try:
            async with httpx.AsyncClient(timeout=settings.LLM_TIMEOUT) as client:
                resp = await client.post(
                    f"{base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": model,
                        "messages": payload_messages,
                        "stream": False,
                    },
                )
                resp.raise_for_status()
                return resp.json()["choices"][0]["message"]["content"]
        except Exception:
            pass

    return None


async def embed_text(text: str) -> list[float]:
    """文本向量化。

    优先 GLM embedding，失败/无 key 时使用确定性的词项特征哈希。
    A4 匹配默认不调用本函数，而使用明确标注的词法/概念召回回退。
    """
    glm_key = next(
        (
            api_key
            for provider, api_key in settings.llm_credentials
            if provider == "glm"
        ),
        None,
    )
    if glm_key:
        try:
            async with httpx.AsyncClient(timeout=settings.LLM_TIMEOUT) as client:
                resp = await client.post(
                    f"{settings.GLM_BASE_URL}/embeddings",
                    headers={
                        "Authorization": f"Bearer {glm_key}",
                        "Content-Type": "application/json",
                    },
                    json={"model": settings.GLM_EMBED_MODEL, "input": text},
                )
                resp.raise_for_status()
                return resp.json()["data"][0]["embedding"]
        except Exception:
            pass
    from app.services.matching import hash_embedding

    return hash_embedding(text, 128)


async def embed_texts(texts: list[str]) -> list[list[float]]:
    """批量向量化。"""
    return [await embed_text(t) for t in texts]


def portrait_to_text(portrait: dict[str, Any]) -> str:
    """把画像 dict 序列化为文本，用于向量化。"""
    return json.dumps(portrait, ensure_ascii=False)
