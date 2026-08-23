"""导师隐私控制：字段可见性（即时生效）与下线/隐藏申请（审批流）。

- visibility：false=对导师端/管理端隐藏；本期仅影响导师端+管理端展示层，低风险即时生效；
- takedown：full 整档下线 / field 单字段隐藏，审批通过后写入 mentor_profiles。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.mentor_account import MentorAccount
from app.models.mentor_profile import SELF_CLAIM_FIELDS
from app.models.takedown_request import (
    SCOPE_FIELD,
    SCOPE_FULL,
    TK_APPROVED,
    TK_PENDING,
    TK_REJECTED,
    TakedownRequest,
)
from app.services.mentor_profile import ensure_mentor_profile, require_claimed

# 可见性策略可覆盖的字段：自述字段 + 公开档案中的联系方式类字段。
VISIBILITY_FIELDS = (
    *SELF_CLAIM_FIELDS,
    "contact_email",
    "office_loc",
    "official_homepage",
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def get_privacy_status(db: Session, *, account: MentorAccount) -> dict:
    advisor_id = require_claimed(account)
    profile = ensure_mentor_profile(db, account=account, advisor_id=advisor_id)
    return {
        "visibility": dict(profile.visibility or {}),
        "takedown": {
            "active": profile.takedown_at is not None,
            "effective_at": (
                profile.takedown_at.isoformat() if profile.takedown_at else None
            ),
        },
    }


def update_visibility(
    db: Session, *, account: MentorAccount, visibility: dict
) -> dict:
    """按字段设置展示策略；立即生效（仅导师端/管理端展示层）。"""
    advisor_id = require_claimed(account)
    invalid = set(visibility) - set(VISIBILITY_FIELDS)
    if invalid:
        raise HTTPException(
            status_code=422,
            detail=f"不支持的可见性字段：{', '.join(sorted(invalid))}",
        )
    profile = ensure_mentor_profile(db, account=account, advisor_id=advisor_id)
    merged = dict(profile.visibility or {})
    merged.update({field: bool(value) for field, value in visibility.items()})
    profile.visibility = merged
    profile.updated_at = _now()
    db.commit()
    db.refresh(profile)
    return {"visibility": merged}


def submit_takedown(
    db: Session,
    *,
    account: MentorAccount,
    reason: str,
    scope: str,
    field_name: str | None,
) -> TakedownRequest:
    """提交下线/隐藏申请；pending 期间仍按原策略展示。"""
    advisor_id = require_claimed(account)
    if scope not in {SCOPE_FULL, SCOPE_FIELD}:
        raise HTTPException(status_code=422, detail="scope 必须为 full 或 field")
    if scope == SCOPE_FIELD:
        if not field_name or field_name not in VISIBILITY_FIELDS:
            raise HTTPException(
                status_code=422,
                detail="field 模式必须指定受支持的字段",
            )
    pending = (
        db.query(TakedownRequest)
        .filter(
            TakedownRequest.account_id == account.account_id,
            TakedownRequest.status == TK_PENDING,
        )
        .one_or_none()
    )
    if pending is not None:
        raise HTTPException(status_code=409, detail="已有待审批的下线/隐藏申请")
    request = TakedownRequest(
        req_id=str(uuid.uuid4()),
        account_id=account.account_id,
        advisor_id=advisor_id,
        reason=reason.strip() or None,
        scope=scope,
        field_name=field_name if scope == SCOPE_FIELD else None,
        status=TK_PENDING,
    )
    db.add(request)
    db.commit()
    db.refresh(request)
    return request


def get_takedown(db: Session, *, req_id: str) -> TakedownRequest:
    request = db.get(TakedownRequest, req_id)
    if request is None:
        raise HTTPException(status_code=404, detail="下线/隐藏申请不存在")
    return request


def decide_takedown(
    db: Session,
    *,
    req_id: str,
    reviewer: str,
    approve: bool,
    note: str | None,
) -> TakedownRequest:
    """审批下线/隐藏：通过后 full 写 takedown_at，field 写 visibility=false。"""
    request = get_takedown(db, req_id=req_id)
    if request.status != TK_PENDING:
        raise HTTPException(status_code=409, detail="该申请已处理")
    now = _now()
    if approve:
        account = db.get(MentorAccount, request.account_id)
        profile = ensure_mentor_profile(
            db, account=account, advisor_id=request.advisor_id
        )
        if request.scope == SCOPE_FULL:
            profile.takedown_at = now
        else:
            merged = dict(profile.visibility or {})
            merged[request.field_name] = False
            profile.visibility = merged
        profile.updated_at = now
        request.status = TK_APPROVED
    else:
        request.status = TK_REJECTED
    request.decided_by = reviewer
    request.decided_at = now
    request.admin_note = note
    db.commit()
    db.refresh(request)
    return request
