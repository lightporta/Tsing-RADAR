"""通用 LLM 与向量服务。

开发环境可配置 GLM_API_KEY；生产环境只接受 GLM provider 的
LLM_PROVIDER + LLM_API_KEY_FILE，并在 Settings 构造时一次性解析。
A3 访谈题序、画像状态与确认门不由 LLM 决定。
"""

import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Any, Optional

import httpx

from app.core.config import settings
from app.schemas.advisor import LLMMessage
from app.services.prompts import load_prompt_template

logger = logging.getLogger(__name__)

# v4.0.0 任务1 A-3：提示词版本化。内嵌 v1 文本为兜底常量，运行期从
# app/services/prompts/system_prompt_v1.txt 加载（版本清单不一致/文件缺失
# → 回退本常量，行为与 v3.1.x 完全一致）。
_SYSTEM_PROMPT_FALLBACK_V1 = (
    "你是 Tsing-RADAR 文本助手。动态访谈的题序、画像状态和确认门由服务端状态机控制。"
    "不得输出控制标记，不得自行宣布画像已确认或触发导师匹配。"
)
LLM_SYSTEM_PROMPT = load_prompt_template(
    "system_prompt", fallback=_SYSTEM_PROMPT_FALLBACK_V1
)


def _build_payload_messages(messages: list[LLMMessage]) -> list[dict[str, str]]:
    return [{"role": "system", "content": LLM_SYSTEM_PROMPT}] + [
        {"role": m.role, "content": m.content} for m in messages
    ]


@dataclass(frozen=True)
class LLMCompletionResult:
    text: str
    provider: str
    model: str


@dataclass(frozen=True)
class InterviewEnhancement:
    text: str | None
    provider: str | None
    status: str


async def _llm_complete_result(
    messages: list[LLMMessage],
    *,
    timeout_seconds: float | None = None,
) -> LLMCompletionResult | None:
    if not settings.llm_credentials:
        return None
    provider, api_key = settings.llm_credentials[0]
    # Settings guarantees this invariant.  Keep the service fail-closed if a
    # test or future refactor attempts to inject another provider directly.
    if provider != "glm":
        logger.error("llm_completion status=rejected_unsupported_provider")
        return None
    payload_messages = _build_payload_messages(messages)
    model = settings.GLM_CHAT_MODEL
    started = time.monotonic()
    try:
        async with httpx.AsyncClient(
            timeout=timeout_seconds or settings.LLM_TIMEOUT
        ) as client:
            resp = await client.post(
                f"{settings.GLM_BASE_URL}/chat/completions",
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
            text = str(resp.json()["choices"][0]["message"]["content"])
            logger.info(
                "llm_completion provider=glm model=%s status=success latency_ms=%d",
                model,
                round((time.monotonic() - started) * 1000),
            )
            return LLMCompletionResult(text=text, provider="glm", model=model)
    except Exception as exc:
        status_code = getattr(getattr(exc, "response", None), "status_code", None)
        logger.warning(
            "llm_completion provider=glm model=%s status=failed error_type=%s http_status=%s latency_ms=%d",
            model,
            type(exc).__name__,
            status_code if status_code is not None else "none",
            round((time.monotonic() - started) * 1000),
        )
        return None


async def llm_complete(messages: list[LLMMessage]) -> Optional[str]:
    """调用唯一支持的 GLM；失败时返回 None，由客户端明确提示并重试。"""
    result = await _llm_complete_result(messages)
    return result.text if result else None


async def enhance_interview_reply(
    *,
    user_message: str,
    fixed_reply: str,
) -> InterviewEnhancement:
    """Add a short acknowledgement without changing the fixed state machine."""
    if not settings.llm_credentials:
        return InterviewEnhancement(text=None, provider=None, status="disabled")
    result = await _llm_complete_result(
        [
            LLMMessage(
                role="user",
                content=(
                    "请只写一句自然、温暖的中文承接语（最多50个汉字），回应用户刚才的表达。"
                    "不要提问，不要给建议，不要引入新事实，不要宣布画像已确认或匹配完成。\n"
                    f"用户表达：{user_message[:800]}\n"
                    f"服务端接下来固定展示：{fixed_reply[:1200]}"
                ),
            )
        ],
        timeout_seconds=settings.LLM_INTERVIEW_ENHANCEMENT_TIMEOUT_SECONDS,
    )
    if result is None:
        provider = settings.configured_llm_providers[0]
        return InterviewEnhancement(
            text=None,
            provider=provider,
            status="unavailable",
        )
    candidate = re.sub(r"\s+", " ", result.text).strip(" \"'“”")
    forbidden = ("?", "？", "画像已确认", "匹配完成", "确认画像")
    if (
        not candidate
        or len(candidate) > 60
        or any(token in candidate for token in forbidden)
    ):
        logger.warning(
            "llm_interview_enhancement provider=%s model=%s status=rejected_output",
            result.provider,
            result.model,
        )
        return InterviewEnhancement(
            text=None,
            provider=result.provider,
            status="unavailable",
        )
    return InterviewEnhancement(
        text=candidate,
        provider=result.provider,
        status="available",
    )


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
        except Exception as exc:
            logger.warning(
                "llm_embedding provider=glm model=%s status=failed error_type=%s",
                settings.GLM_EMBED_MODEL,
                type(exc).__name__,
            )
    from app.services.matching import hash_embedding

    return hash_embedding(text, 128)


async def embed_texts(texts: list[str]) -> list[list[float]]:
    """批量向量化。"""
    return [await embed_text(t) for t in texts]


def portrait_to_text(portrait: dict[str, Any]) -> str:
    """把画像 dict 序列化为文本，用于向量化。"""
    return json.dumps(portrait, ensure_ascii=False)
