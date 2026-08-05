"""核心匹配算法（文档第 3 章）。

- Synergy Score：极坐标六维多边形 + Shoelace 面积 + per-dim min 近似交集
- 关键词评分：field 命中 +10，tags 命中 +8
- 画像向量契合度：余弦相似度
- 训练权重加权：MODEL_WEIGHTS 系数调整
"""

import hashlib
import json
import math
import re
from typing import Any, Optional

from app.services.constants import TRAIT_KEYS


def mentor_traits_list(mentor: dict[str, Any]) -> list[float]:
    """取出导师六维雷达特质，按固定顺序返回 0-100 数值列表。"""
    rt = mentor.get("radar_traits", {}) or {}
    return [float(rt.get(k, 0)) for k in TRAIT_KEYS]


def compute_synergy(student_weights: list[float], mentor_traits: list[float]) -> float:
    """合伙人契合指数（Synergy Score）。

    极坐标六维多边形 + Shoelace 面积，交集用每维 min 近似。
    返回 0-100 的契合百分比。
    """
    angles = [i * 60 for i in range(6)]

    def to_cartesian(vals: list[float]) -> list[tuple[float, float]]:
        return [
            (v * math.cos(math.radians(a)), v * math.sin(math.radians(a)))
            for v, a in zip(vals, angles)
        ]

    def polygon_area(poly: list[tuple[float, float]]) -> float:
        n = len(poly)
        return abs(
            sum(
                poly[i][0] * poly[(i + 1) % n][1] - poly[(i + 1) % n][0] * poly[i][1]
                for i in range(n)
            )
        ) / 2

    student_area = polygon_area(to_cartesian(student_weights))
    if student_area <= 0:
        return 0.0
    inter_vals = [min(s, m) for s, m in zip(student_weights, mentor_traits)]
    inter_area = polygon_area(to_cartesian(inter_vals))
    return round(inter_area / student_area * 100, 1)


def keyword_score(mentor: dict[str, Any], keywords: list[str]) -> int:
    """关键词匹配得分：field 命中 +10，tags 命中 +8。"""
    field = mentor.get("field", "").lower()
    tags = [t.lower() for t in mentor.get("tags", [])]
    score = 0
    for k in keywords:
        if len(k) < 2:
            continue
        if k in field:
            score += 10
        if any(k in tag for tag in tags):
            score += 8
    return score


def hash_embedding(text: str, dim: int = 128) -> list[float]:
    """无 API Key 时基于文本 hash 生成 128 维伪向量（确定性，范围 -1~1）。"""
    vec = []
    for i in range(dim):
        chunk = hashlib.sha256(f"{text}#{i}".encode("utf-8")).digest()
        val = int.from_bytes(chunk[:4], "big") / 0xFFFFFFFF  # 0~1
        vec.append(round(val * 2 - 1, 4))
    return vec


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """余弦相似度。"""
    if not a or not b or len(a) != len(b):
        return 0.0
    num = sum(x * y for x, y in zip(a, b))
    da = math.sqrt(sum(x * x for x in a))
    db = math.sqrt(sum(y * y for y in b))
    return num / (da * db) if da and db else 0.0


def normalize_weights(weight: dict[str, float]) -> list[float]:
    """把六维权重 dict 归一为 0-100 顺序列表（缺失维度补 50）。"""
    vals = [float(weight.get(k, 50)) for k in TRAIT_KEYS]
    max_v = max(vals) if vals else 0
    # 若输入是 0~1 范围，则放大到 0~100
    if max_v <= 1.0:
        vals = [v * 100 for v in vals]
    return vals


def build_reason(mentor: dict[str, Any], kw_score: int, synergy: float) -> str:
    """生成一句话推荐理由。"""
    name = mentor.get("name", "")
    field = mentor.get("field", "")
    traits = mentor_traits_list(mentor)
    top_trait_idx = max(range(6), key=lambda i: traits[i])
    trait_cn = {
        "acumen": "学术洞察",
        "network": "学术网络",
        "mentorship": "指导用心",
        "tolerance": "氛围包容",
        "funding": "经费充足",
        "efficiency": "出成果快",
    }[TRAIT_KEYS[top_trait_idx]]
    if kw_score > 0:
        return f"{name}：研究方向「{field}」与你的兴趣高度契合，{trait_cn}突出。"
    return f"{name}：{trait_cn}突出，研究方向「{field}」，可作为潜在备选。"


def match_mentors(
    mentors: list[dict[str, Any]],
    interest: str,
    portrait: Optional[dict[str, Any]] = None,
    weight: Optional[dict[str, float]] = None,
    portrait_vec: Optional[list[float]] = None,
    mentor_vecs: Optional[dict[str, list[float]]] = None,
    model_weights: Optional[dict[str, float]] = None,
    top_n: int = 5,
) -> list[dict[str, Any]]:
    """综合匹配：关键词基础分 + 画像向量契合度 + 六维 Synergy Score。

    Args:
        mentors: 全量导师列表
        interest: 学生兴趣关键词字符串
        portrait: 学生画像 dict（用于向量契合）
        weight: 六维需求权重
        portrait_vec: 预计算的画像向量（避免重复 embed）
        mentor_vecs: 预计算的每名导师向量
        model_weights: 训练产出的加权系数
        top_n: 返回前 N 条
    """
    user_input = interest.lower().strip()
    keywords = [k for k in re.split(r"[\s,，、]+", user_input) if k]

    student_weights = normalize_weights(weight) if weight else None

    scored: list[dict[str, Any]] = []
    for m in mentors:
        kw = keyword_score(m, keywords)
        kw_base = min(60.0, kw * 3.0)

        cos_base = 0.0
        if portrait_vec is not None and mentor_vecs is not None:
            cos = cosine_similarity(portrait_vec, mentor_vecs.get(m.get("name", ""), []))
            cos_base = max(0.0, cos) * 40.0

        if model_weights is not None:
            kw_base *= model_weights.get("keyword_factor", 1.0)
            cos_base *= model_weights.get("portrait_factor", 1.0)

        base = kw_base + cos_base

        # 兜底：无任何信号时给 mentor 自身 score 一个比例
        if kw == 0 and portrait_vec is None and student_weights is None:
            base = max(base, m.get("score", 50) * 0.4)

        score = round(min(100.0, base), 1)

        synergy = 0.0
        if student_weights is not None:
            synergy = compute_synergy(student_weights, mentor_traits_list(m))

        scored.append({**m, "score": score, "reason": build_reason(m, kw, synergy), "synergy": synergy})

    scored.sort(key=lambda x: (x["score"], x["synergy"]), reverse=True)
    return scored[:top_n]
