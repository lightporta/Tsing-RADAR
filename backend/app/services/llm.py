"""LLM 服务：GLM 优先 → DeepSeek 兜底 → 本地 stub（三级降级）。

用户要求接真模型，需在 .env 配置 GLM_API_KEY 或 DEEPSEEK_API_KEY。
"""

import json
from typing import Any, Optional

import httpx

from app.core.config import settings
from app.schemas.advisor import LLMMessage

# 问卷系统提示词（与旧 app.py 一致）
LLM_SYSTEM_PROMPT = (
    "你是 Tsing-RADAR 智能问卷助手，通过多轮对话挖掘学生对研究方向、科研风格、行业偏好的需求。"
    "每轮提出一个聚焦追问，参考高考志愿测评形式深入挖掘。"
    "当你认为已收集足够信息（通常 3-5 轮）可做导师推荐时，"
    "在回复末尾追加 \"RECOMMEND_READY\" 标记。"
)


def _build_payload_messages(messages: list[LLMMessage]) -> list[dict[str, str]]:
    return [{"role": "system", "content": LLM_SYSTEM_PROMPT}] + [
        {"role": m.role, "content": m.content} for m in messages
    ]


async def llm_complete(messages: list[LLMMessage]) -> Optional[str]:
    """调用 LLM 获取完整回复文本。

    GLM 优先，失败 fallback DeepSeek，均失败返回 None（由调用方走 stub）。
    """
    payload_messages = _build_payload_messages(messages)

    if settings.GLM_API_KEY:
        try:
            async with httpx.AsyncClient(timeout=settings.LLM_TIMEOUT) as client:
                resp = await client.post(
                    f"{settings.GLM_BASE_URL}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {settings.GLM_API_KEY}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": settings.GLM_CHAT_MODEL,
                        "messages": payload_messages,
                        "stream": False,
                    },
                )
                resp.raise_for_status()
                return resp.json()["choices"][0]["message"]["content"]
        except Exception:
            pass  # 降级到 DeepSeek

    if settings.DEEPSEEK_API_KEY:
        try:
            async with httpx.AsyncClient(timeout=settings.LLM_TIMEOUT) as client:
                resp = await client.post(
                    f"{settings.DEEPSEEK_BASE_URL}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {settings.DEEPSEEK_API_KEY}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": settings.DEEPSEEK_CHAT_MODEL,
                        "messages": payload_messages,
                        "stream": False,
                    },
                )
                resp.raise_for_status()
                return resp.json()["choices"][0]["message"]["content"]
        except Exception:
            pass  # 降级到本地 stub

    return None


async def embed_text(text: str) -> list[float]:
    """文本向量化。

    优先 GLM embedding，失败/无 key 时调用 vectorstore 的 hash 伪向量兜底。
    """
    if settings.GLM_API_KEY:
        try:
            async with httpx.AsyncClient(timeout=settings.LLM_TIMEOUT) as client:
                resp = await client.post(
                    f"{settings.GLM_BASE_URL}/embeddings",
                    headers={
                        "Authorization": f"Bearer {settings.GLM_API_KEY}",
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


# ===== 本地 stub 问卷追问（与旧 app.py 一致）=====

_STUB_RULES: list[tuple[tuple[str, ...], str]] = [
    (("nlp", "自然语言", "文本", "对话系统", "语言模型", "llm"),
     "你提到对 NLP 感兴趣，能说说你具体对哪个子方向更感兴趣吗？比如机器翻译、对话系统还是知识图谱？"),
    (("cv", "计算机视觉", "图像", "视觉", "目标检测", "分割"),
     "关于计算机视觉，你更偏向基础研究（如检测、分割、生成）还是应用落地（如自动驾驶、工业质检）？"),
    (("机器人", "robot", "控制", "机械臂", "运动"),
     "机器人方向上，你更想做运动控制与感知融合，还是强化学习/仿真训练？"),
    (("机器学习", "深度学习", "ml", "dl", "模型", "算法"),
     "在机器学习里，你更看重理论（优化、泛化）还是工程（系统、大模型训练）？"),
    (("系统", "分布式", "数据库", "编译", "操作系统", "体系结构"),
     "系统方向你的偏好是偏底层（编译/体系结构）还是偏上层（分布式/数据库）？"),
    (("信号", "通信", "射频", "雷达", "电磁", "天线"),
     "通信与信号方向，你更想做硬件（射频/天线）还是算法（估计/检测/信号处理）？"),
    (("芯片", "eda", "集成电路", "半导体", "verilog"),
     "芯片方向你倾向数字前端/后端，还是模拟/射频电路设计？"),
    (("科研", "论文", "学术", "phd", "读博"),
     "你更看重导师的学术指导（手把手带）还是给资源让你自由探索？"),
    (("实习", "工业", "企业", "就业", "工作"),
     "你希望导师项目偏校企合作（便于实习就业）还是偏国家级科研（便于发论文/读博）？"),
]

_COMPLETION_SIGNALS = ["推荐", "够了", "完了", "可以了", "结束", "match", "recommend", "开始匹配", "好了", "差不多了"]
_FALLBACKS = [
    "除了你提到的方向，你对导师的指导风格（手把手 vs 自由探索）有什么偏好吗？",
    "你更看重科研氛围包容度，还是出成果的效率？",
    "你希望导师的项目经费/资源充足，还是更在意学术网络与人脉？",
    "你对国有机构方向（航天/军工/国家实验室）和私营方向（互联网/初创）有偏好吗？",
    "能具体说说你最看重的科研特质吗？比如学术洞察、学术网络、指导用心、氛围包容、经费、效率。",
]


def stub_reply(messages: list[LLMMessage]) -> str:
    """本地关键词规则模拟追问；判定完成时追加 RECOMMEND_READY。"""
    last = messages[-1].content if messages else ""
    last_lower = last.lower()
    user_turns = sum(1 for m in messages if m.role == "user")

    if any(s in last_lower for s in _COMPLETION_SIGNALS) and user_turns >= 2:
        return (
            "感谢你的回答！我已经对你的画像有了清晰认识，"
            "正在为你匹配最合适的导师，请稍候查看推荐结果。RECOMMEND_READY"
        )

    for keys, reply in _STUB_RULES:
        if any(k in last_lower for k in keys):
            return reply

    return _FALLBACKS[user_turns % len(_FALLBACKS)]


def portrait_to_text(portrait: dict[str, Any]) -> str:
    """把画像 dict 序列化为文本，用于向量化。"""
    return json.dumps(portrait, ensure_ascii=False)
