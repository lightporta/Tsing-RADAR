"""学生评价体系 M1 聚合服务：贝叶斯平均 + 物化表重算 + 提交约束。

设计要点（实施计划 §2.3）：
- 聚合公式 (m·C + Σwi·xi) / (m + Σwi)，先验 C=3.0（量表中点）、m=5，
  单人评分最多贡献一半权重，天然压恶意打分；
- 物化表 advisor_rating_summary 审核通过时重算，读取零计算；
- M1 纯分数「先发后抽审」：提交即 approved 并刷新聚合；
  evidence 非空（M2 预留）转 pending_review 且不参与聚合。
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.advisor_rating import AdvisorRating, AdvisorRatingSummary
from app.services.constants import TRAIT_KEYS

# 贝叶斯先验：m 张「虚拟中位票」+ 先验均值 C
_PRIOR_WEIGHT = 5.0
_PRIOR_MEAN = 3.0

REVIEW_APPROVED = "approved"
REVIEW_PENDING = "pending_review"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _bayesian_aggregate(
    scores: list[tuple[int, bool]],
    *,
    half_life_months: int = 12,
) -> tuple[float, int]:
    """(value, n) 贝叶斯平均；half_life 为时间衰减预留参数（M1 暂不启用）。

    单条评分向 3.0 收缩；多条评分收敛到真实均值。value 保留 3 位小数。
    """
    n = len(scores)
    total_weight = sum(1.0 for _ in scores)
    weighted_sum = sum(value * 1.0 for value, _ in scores)
    value = (_PRIOR_WEIGHT * _PRIOR_MEAN + weighted_sum) / (
        _PRIOR_WEIGHT + total_weight
    )
    return round(value, 3), n


def refresh_summary(db: Session, advisor_id: str) -> AdvisorRatingSummary:
    """全量重算该导师的 approved 评分并 upsert 物化表。"""
    approved = (
        db.query(AdvisorRating)
        .filter(
            AdvisorRating.advisor_id == advisor_id,
            AdvisorRating.review_status == REVIEW_APPROVED,
        )
        .all()
    )
    row = db.get(AdvisorRatingSummary, advisor_id)
    if row is None:
        row = AdvisorRatingSummary(advisor_id=advisor_id)
        db.add(row)
    latest: datetime | None = None
    for key in TRAIT_KEYS:
        pairs = [
            (int(rating.scores[key]), bool(rating.rater_verified))
            for rating in approved
            if isinstance(rating.scores, dict) and key in rating.scores
        ]
        value, n = _bayesian_aggregate(pairs)
        # 无样本维度保持 None（诚实空态），绝不伪造 0 分或中位分
        setattr(row, f"{key}_value", value if n else None)
        setattr(row, f"{key}_n", n)
    for rating in approved:
        if rating.created_at is None:
            continue
        created = _as_utc(rating.created_at)
        latest = created if latest is None else max(latest, created)
    row.last_collected_at = latest
    db.flush()
    return row


def get_summary(db: Session, advisor_id: str) -> dict | None:
    """读取物化聚合结果；无记录返回 None（由路由层转成诚实空态结构）。"""
    row = db.get(AdvisorRatingSummary, advisor_id)
    if row is None:
        return None
    return {
        "advisor_id": advisor_id,
        "dimensions": {
            key: {
                "value": getattr(row, f"{key}_value"),
                "n": getattr(row, f"{key}_n"),
            }
            for key in TRAIT_KEYS
        },
        "total_n": max(getattr(row, f"{key}_n") for key in TRAIT_KEYS),
        "last_collected_at": (
            row.last_collected_at.isoformat() if row.last_collected_at else None
        ),
    }


def submit_rating(
    db: Session,
    *,
    advisor_id: str,
    rater_principal: str,
    scores: dict[str, int],
    period_in_group: str | None,
    evidence: str | None = None,
) -> AdvisorRating:
    """创建评分：每日上限 → 一人一导师唯一约束 → 审核状态 → 刷新聚合。

    - 同一 rater_principal 每日 ≤ ADVISOR_RATING_DAILY_LIMIT 条，超限 429；
    - 同一导师同一主体重复提交 409（唯一约束兜底并发）；
    - M1 纯分数即发即审（approved）并立即刷新聚合；
      evidence 非空（M2 预留）转 pending_review，不参与聚合。
    """
    day_start = _now().replace(hour=0, minute=0, second=0, microsecond=0)
    submitted_today = (
        db.query(AdvisorRating)
        .filter(
            AdvisorRating.rater_principal == rater_principal,
            AdvisorRating.created_at >= day_start.replace(tzinfo=None),
        )
        .count()
    )
    if submitted_today >= settings.ADVISOR_RATING_DAILY_LIMIT:
        raise HTTPException(status_code=429, detail="今日评分提交次数已达上限")
    existing = (
        db.query(AdvisorRating)
        .filter(
            AdvisorRating.advisor_id == advisor_id,
            AdvisorRating.rater_principal == rater_principal,
        )
        .one_or_none()
    )
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail="您已评价过该导师，不可重复提交",
        )
    review_status = REVIEW_PENDING if evidence else REVIEW_APPROVED
    record = AdvisorRating(
        advisor_id=advisor_id,
        rater_principal=rater_principal,
        rater_verified=False,
        period_in_group=period_in_group,
        scores=scores,
        evidence=evidence,
        review_status=review_status,
    )
    db.add(record)
    try:
        db.flush()
    except IntegrityError as exc:
        # 并发下同人同导师唯一约束兜底
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="您已评价过该导师，不可重复提交",
        ) from exc
    if review_status == REVIEW_APPROVED:
        refresh_summary(db, advisor_id)
    return record
