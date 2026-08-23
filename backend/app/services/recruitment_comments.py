"""招募评论区服务：两级评论 + 分级审核 + 举报即隐藏 + 点赞幂等 + 软删保楼层。

设计要点（实施计划 §2.1/§2.2）：
- 公开列表只返回 approved 评论；含链接/联系方式/敏感词的先审后发
  （pending_review，公开不可见），楼主回复与普通评论先发后审（approved）；
- 举报立即隐藏（approved → pending_review）并进审核队列；
- 软删保楼层：deleted_at 非空后公开树中显示「已删除」占位，回复仍可见；
- 点赞每主体一次去重（recruitment_comment_likes 唯一约束兜底并发）；
- 隐私红线：公开输出不含 author_principal；审计事件不写评论正文。
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.recruitment import Recruitment
from app.models.recruitment_comment import (
    RecruitmentComment,
    RecruitmentCommentLike,
)
from app.services.content_moderation import PRE_REVIEW, classify_content
from app.services.recruitment_public import (
    PROJECT_TIMEZONE,
    _deadline_is_past,
)

REVIEW_APPROVED = "approved"
REVIEW_PENDING = "pending_review"
REVIEW_REJECTED = "rejected"

DELETED_PLACEHOLDER = "该评论已删除"

# 匿名徽章只由服务端根据 author_label / is_op 计算，客户端不得自报
_AUTHOR_BADGES = {
    "student": "清华学生",
    "verified_student": "清华学生·已验证",
    "senior": "学长学姐",
    "advisor": "认证导师",
}


class CommentReviewError(ValueError):
    """评论审核动作的参数/状态错误（与 RecruitmentReviewError 同构）。"""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _public_recruitment(db: Session, recruit_id: str) -> Recruitment:
    """仅 verified + published + 未下架 + 未过期 的帖可挂公开评论。"""
    record = db.get(Recruitment, recruit_id)
    today = _now().astimezone(PROJECT_TIMEZONE).date()
    if (
        record is None
        or record.review_status != "verified"
        or record.publication_status != "published"
        or record.takedown_at is not None
        or _deadline_is_past(record.deadline, today=today)
    ):
        raise HTTPException(status_code=404, detail="招募不存在或未公开")
    return record


def _assert_rate_limits(db: Session, *, principal: str, recruit_id: str) -> None:
    """服务内确定性限频：每日总量 + 单帖限量，超限 429。"""
    day_start = _now().replace(hour=0, minute=0, second=0, microsecond=0)
    submitted_today = (
        db.query(RecruitmentComment)
        .filter(
            RecruitmentComment.author_principal == principal,
            RecruitmentComment.created_at >= day_start.replace(tzinfo=None),
        )
        .count()
    )
    if submitted_today >= settings.COMMENT_DAILY_LIMIT:
        raise HTTPException(status_code=429, detail="今日评论次数已达上限")
    in_post = (
        db.query(RecruitmentComment)
        .filter(
            RecruitmentComment.author_principal == principal,
            RecruitmentComment.recruit_id == recruit_id,
        )
        .count()
    )
    if in_post >= settings.COMMENT_PER_POST_LIMIT:
        raise HTTPException(status_code=429, detail="该招募下的评论次数已达上限")


def create_comment(
    db: Session,
    *,
    recruit_id: str,
    parent_id: str | None,
    principal: str,
    author_label: str,
    content: str,
) -> RecruitmentComment:
    """写入评论；按 is_op + classify_content 决定 review_status 初值。

    - 仅公开口径内的招募可评论（未过审帖下不能有公开评论）；
    - 楼主（发布者本人）回复即时 approved；
    - 含链接/联系方式/敏感词 → pending_review（公开不可见，先审后发）；
    - 其余 approved（先发后审 + 抽检）；
    - parent_id 只允许一级回复：对回复再回复 → 422。
    """
    recruitment = _public_recruitment(db, recruit_id)
    _assert_rate_limits(db, principal=principal, recruit_id=recruit_id)
    parent: RecruitmentComment | None = None
    if parent_id is not None:
        parent = db.get(RecruitmentComment, parent_id)
        if parent is None or parent.recruit_id != recruit_id:
            raise HTTPException(status_code=404, detail="被回复的评论不存在")
        if parent.parent_id is not None:
            raise HTTPException(
                status_code=422, detail="仅支持一级回复，请直接回复顶层评论"
            )
    is_op = principal == recruitment.publisher_id
    if is_op:
        review_status = REVIEW_APPROVED
    elif classify_content(content) == PRE_REVIEW:
        review_status = REVIEW_PENDING
    else:
        review_status = REVIEW_APPROVED
    record = RecruitmentComment(
        recruit_id=recruit_id,
        parent_id=parent_id,
        author_principal=principal,
        author_label=("advisor" if is_op and recruitment.publisher_type == "advisor" else author_label),
        is_op=is_op,
        content=content,
        review_status=review_status,
        like_count=0,
        governance={"review_history": []},
    )
    db.add(record)
    db.flush()
    return record


def _public_comment_dict(
    comment: RecruitmentComment,
    *,
    replies: list[dict] | None,
    reply_total: int | None,
    viewer: str | None,
) -> dict:
    """公开序列化：不含 author_principal；软删评论显示占位、保留楼层。

    own 仅表示「当前请求主体是否作者」（用于作者自删入口），不暴露身份。
    """
    deleted = comment.deleted_at is not None
    item = {
        "comment_id": comment.comment_id,
        "badge": ("楼主" if comment.is_op else None) or _AUTHOR_BADGES.get(
            comment.author_label, "清华学生"
        ),
        "is_op": bool(comment.is_op),
        "own": viewer is not None and comment.author_principal == viewer,
        "content": DELETED_PLACEHOLDER if deleted else comment.content,
        "deleted": deleted,
        "like_count": comment.like_count if not deleted else 0,
        "created_at": (
            comment.created_at.isoformat() if comment.created_at else None
        ),
    }
    if replies is not None:
        item["replies"] = replies
        item["reply_total"] = reply_total if reply_total is not None else len(replies)
    return item


def list_comment_tree(
    db: Session,
    *,
    recruit_id: str,
    page: int = 1,
    page_size: int = 10,
    viewer: str | None = None,
) -> dict:
    """两级嵌套树：父评论分页 + 每父内嵌前 N 条回复。

    仅返回 approved 评论（软删的保留为占位）；输出不含 author_principal。
    """
    base_filter = (
        RecruitmentComment.recruit_id == recruit_id,
        RecruitmentComment.review_status == REVIEW_APPROVED,
    )
    total = (
        db.query(RecruitmentComment)
        .filter(*base_filter, RecruitmentComment.parent_id.is_(None))
        .count()
    )
    parents = (
        db.query(RecruitmentComment)
        .filter(*base_filter, RecruitmentComment.parent_id.is_(None))
        .order_by(RecruitmentComment.created_at.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    preview_limit = settings.COMMENT_REPLY_PREVIEW_LIMIT
    items: list[dict] = []
    for parent in parents:
        reply_query = db.query(RecruitmentComment).filter(
            *base_filter,
            RecruitmentComment.parent_id == parent.comment_id,
        )
        reply_total = reply_query.count()
        replies = (
            reply_query.order_by(RecruitmentComment.created_at.asc())
            .limit(preview_limit)
            .all()
        )
        items.append(
            _public_comment_dict(
                parent,
                replies=[
                    _public_comment_dict(
                        reply, replies=None, reply_total=None, viewer=viewer
                    )
                    for reply in replies
                ],
                reply_total=reply_total,
                viewer=viewer,
            )
        )
    return {"data": items, "meta": {"total": total, "page": page, "page_size": page_size}}


def _visible_comment(db: Session, comment_id: str) -> RecruitmentComment:
    comment = db.get(RecruitmentComment, comment_id)
    if comment is None or comment.review_status != REVIEW_APPROVED:
        raise HTTPException(status_code=404, detail="评论不存在")
    return comment


def like_comment(db: Session, *, comment_id: str, principal: str) -> int:
    """点赞：每主体一次去重（唯一约束兜底并发），返回最新 like_count。"""
    comment = _visible_comment(db, comment_id)
    if comment.deleted_at is not None:
        raise HTTPException(status_code=404, detail="评论不存在")
    existing = (
        db.query(RecruitmentCommentLike)
        .filter(
            RecruitmentCommentLike.comment_id == comment_id,
            RecruitmentCommentLike.principal == principal,
        )
        .one_or_none()
    )
    if existing is not None:
        return comment.like_count
    db.add(RecruitmentCommentLike(comment_id=comment_id, principal=principal))
    try:
        comment.like_count = (comment.like_count or 0) + 1
        db.flush()
    except IntegrityError:
        # 并发重复点赞：唯一约束兜底，计数不变
        db.rollback()
        refreshed = db.get(RecruitmentComment, comment_id)
        return refreshed.like_count if refreshed else 0
    return comment.like_count


def report_comment(
    db: Session, *, comment_id: str, principal: str, reason: str
) -> None:
    """举报：立即从公开列表隐藏（approved → pending_review）并进审核队列。"""
    comment = _visible_comment(db, comment_id)
    if comment.deleted_at is not None:
        raise HTTPException(status_code=404, detail="评论不存在")
    now = _now()
    governance = dict(comment.governance or {})
    reports = list(governance.get("reports") or [])
    reports.append({"reason": reason.strip(), "reported_at": now.isoformat()})
    governance["reports"] = reports
    comment.review_status = REVIEW_PENDING
    comment.governance = governance
    db.flush()


def soft_delete_comment(db: Session, *, comment_id: str, principal: str) -> None:
    """作者自删（软删保楼层）：公开树显示占位，回复仍可见；重复删除幂等。"""
    comment = db.get(RecruitmentComment, comment_id)
    if comment is None:
        raise HTTPException(status_code=404, detail="评论不存在")
    if comment.author_principal != principal:
        raise HTTPException(status_code=403, detail="只能删除自己的评论")
    if comment.deleted_at is not None:
        return
    comment.deleted_at = _now()
    db.flush()


def list_review_queue(db: Session, *, status_filter: str | None = None) -> list[dict]:
    """管理端审核队列：默认待审；输出含正文供审核员判断（不公开路由）。"""
    query = db.query(RecruitmentComment)
    if status_filter:
        query = query.filter(RecruitmentComment.review_status == status_filter)
    else:
        query = query.filter(
            RecruitmentComment.review_status == REVIEW_PENDING
        )
    rows = query.order_by(RecruitmentComment.created_at.asc()).all()
    return [
        {
            "comment_id": row.comment_id,
            "recruit_id": row.recruit_id,
            "parent_id": row.parent_id,
            "is_op": bool(row.is_op),
            "content": row.content,
            "review_status": row.review_status,
            "reports": (row.governance or {}).get("reports", []),
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        for row in rows
    ]


def review_comment(
    db: Session,
    *,
    comment_id: str,
    action: str,
    reviewer: str,
    reason: str,
) -> RecruitmentComment:
    """评论审核：approve/reject，治理历史写入评论行 governance.review_history。

    字段名与 recruitment_review.py 的 review_history 对齐
    （action/reviewer/reason/reviewed_at），不改既有招募审核语义。
    """
    if action not in {"approve", "reject"}:
        raise CommentReviewError("action must be approve or reject")
    if not reviewer.strip() or not reason.strip():
        raise CommentReviewError("reviewer and reason are required")
    record = db.get(RecruitmentComment, comment_id)
    if record is None:
        raise CommentReviewError("comment not found")
    now = _now()
    governance = dict(record.governance or {})
    history = list(governance.get("review_history") or [])
    history.append(
        {
            "action": action,
            "reviewer": reviewer.strip(),
            "reason": reason.strip(),
            "reviewed_at": now.isoformat(),
        }
    )
    governance["review_history"] = history
    record.review_status = (
        REVIEW_APPROVED if action == "approve" else REVIEW_REJECTED
    )
    record.governance = governance
    db.commit()
    db.refresh(record)
    return record
