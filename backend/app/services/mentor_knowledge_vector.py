"""v4.3.0 阶段三：知识库向量混合召回（零依赖，诚实降级）。

任务书《对话增强适配执行提示词_20260822》§三的确定性落地：
- 词法精确/子串命中**优先**（mentor_knowledge.query_mentor_knowledge，
  本模块不参与命中路径）；
- 词法未命中时，若向量索引存在且有 GLM key → 问题向量与候选块向量做
  余弦相似度（纯 Python：requirements 无 numpy，340 块 × 数百维毫秒级，
  不为此新增依赖），取 top-K（K=3）语义补充；阈值门控——全部低于
  KNOWLEDGE_VECTOR_MIN_SIMILARITY 时保持诚实拒答（拒答门红线不变）；
- 降级链（三层，逐层诚实）：无索引 / 无 key / 嵌入失败 / 维度不匹配
  → 空列表 → 调用方回落词法行为（与基线逐字一致）。

红线（逐字）：
- 只作咨询参考，绝不混入雷达/匹配客观管线；
- 召回的记录仍走 render_mentor_knowledge / render_semantic_supplement
  确定性渲染（不经 LLM 改写事实），来源口径声明不变；
- 向量文件缺失/损坏 → 降级为无索引（行为等同词法现状），不阻断服务。

索引文件 backend/data/knowledge/mentors.knowledge.vectors.json 由
scripts/build_mentor_knowledge.py --rebuild-vectors 人工构建（无 key
诚实退出，不产半成品）；块 id 与词法索引同名（首现优先去重口径一致）。
"""

from __future__ import annotations

import json
import logging
import math
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.services.llm import embed_text_strict
from app.services import mentor_knowledge

logger = logging.getLogger(__name__)

_VECTORS_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "data"
    / "knowledge"
    / "mentors.knowledge.vectors.json"
)

_TOP_K = 3

_vectors_payload: dict[str, Any] | None = None


def _read_vectors() -> dict[str, Any] | None:
    """读取向量索引；缺失/损坏/结构非法 → None（降级为无索引）。"""
    try:
        payload = json.loads(_VECTORS_PATH.read_text(encoding="utf-8"))
    except OSError:
        return None  # 文件不存在：最常见形态（未构建），不刷日志
    except ValueError:
        logger.warning(
            "向量索引文件损坏（JSON 解析失败）：%s（按无索引降级，不阻断服务）",
            _VECTORS_PATH,
        )
        return None
    if not isinstance(payload, dict):
        return None
    dim = payload.get("dim")
    vectors = payload.get("vectors")
    if not isinstance(dim, int) or dim <= 0 or not isinstance(vectors, dict):
        logger.warning(
            "向量索引结构非法（dim/vectors 缺失）：%s（按无索引降级）",
            _VECTORS_PATH,
        )
        return None
    return payload


def _load_vectors() -> dict[str, Any] | None:
    global _vectors_payload
    if _vectors_payload is None:
        _vectors_payload = _read_vectors()
    return _vectors_payload


def reset_vector_cache() -> None:
    """清空模块级向量索引缓存（测试用）。"""
    global _vectors_payload
    _vectors_payload = None


def _glm_key_present() -> bool:
    return any(
        provider == "glm" for provider, _ in settings.llm_credentials
    )


def vector_recall_ready() -> bool:
    """向量语义补充是否就绪（索引存在 + 有 GLM key）。"""
    return _load_vectors() is not None and _glm_key_present()


def _cosine(a: list[float], b: list[float]) -> float:
    """纯 Python 余弦相似度；零向量/长度不一致 → 0.0（确定性防御）。"""
    if len(a) != len(b) or not a:
        return 0.0
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for x, y in zip(a, b):
        dot += x * y
        norm_a += x * x
        norm_b += y * y
    if norm_a <= 0.0 or norm_b <= 0.0:
        return 0.0
    return dot / math.sqrt(norm_a * norm_b)


async def vector_recall(
    query_text: str, *, top_k: int = _TOP_K
) -> list[dict[str, Any]]:
    """词法未命中后的语义补充召回；任何降级路径返回空列表。

    返回按相似度降序（同分按姓名字典序，确定性）的 top-K 导师记录
    （来自词法索引，与知识本体同源）；调用方据此渲染或回落拒答。
    """
    payload = _load_vectors()
    if payload is None:
        return []
    if not _glm_key_present():
        return []
    query = (query_text or "").strip()
    if not query:
        return []
    query_vector = await embed_text_strict(query)
    if not query_vector:
        return []
    dim = payload["dim"]
    if len(query_vector) != dim:
        # 嵌入模型/维度与索引不一致（如索引换代未重建）→ 诚实降级
        logger.warning(
            "向量索引维度不匹配：query=%d index=%d（按词法现状降级）",
            len(query_vector),
            dim,
        )
        return []
    threshold = settings.KNOWLEDGE_VECTOR_MIN_SIMILARITY
    scored: list[tuple[float, str]] = []
    for name, vector in payload["vectors"].items():
        if not isinstance(vector, list) or len(vector) != dim:
            continue
        score = _cosine(query_vector, vector)
        if score >= threshold:
            scored.append((score, str(name)))
    scored.sort(key=lambda item: (-item[0], item[1]))
    records: list[dict[str, Any]] = []
    for _score, name in scored[:top_k]:
        record = mentor_knowledge.query_mentor_knowledge(name)
        if record is not None:
            records.append(record)
    return records
