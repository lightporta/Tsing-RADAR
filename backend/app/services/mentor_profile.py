"""导师档案视图与字段级编辑申请（逐字段进审批流）。

- 公开档案来自 JSON 发行物（load_mentors），只读；
- 导师自述/编辑字段存 mentor_profiles.self_claims（provenance=mentor_edit），
  本期仅导师端+管理端可见；学生侧合并预留二期（data_loader 零改动）。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.mentor_account import MentorAccount, STATUS_CLAIMED
from app.models.mentor_profile import MentorProfile, SELF_CLAIM_FIELDS
from app.models.mentor_profile_edit import (
    EDIT_APPROVED,
    EDIT_PENDING,
    EDIT_REJECTED,
    MentorProfileEdit,
)
from app.services.data_loader import load_mentors
from app.services.mentor_claim import ensure_mentor_profile as _ensure_mentor_profile


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _json_record(advisor_id: str) -> dict | None:
    """JSON 发行物中该导师的公开记录（按 advisor_id 精确匹配）。"""
    for mentor in load_mentors():
        if str(mentor.get("advisor_id")) == advisor_id:
            return mentor
    return None


def require_claimed(account: MentorAccount) -> str:
    """未认领时拒绝；返回 advisor_id。"""
    if account.status != STATUS_CLAIMED or not account.advisor_id:
        raise HTTPException(status_code=409, detail="尚未完成档案认领")
    return account.advisor_id


def ensure_mentor_profile(
    db: Session, *, account: MentorAccount, advisor_id: str
) -> MentorProfile:
    """取回（必要时创建）导师档案覆盖层。"""
    return _ensure_mentor_profile(
        db, account=account, advisor_id=advisor_id, commit=False
    )


def get_mentor_profile(db: Session, *, account: MentorAccount) -> dict:
    """导师端/管理端可见的完整档案：JSON 公开字段 + 过审自述 + 可见性策略。"""
    advisor_id = require_claimed(account)
    profile = ensure_mentor_profile(db, account=account, advisor_id=advisor_id)
    record = _json_record(advisor_id) or {}
    visibility = dict(profile.visibility or {})
    hidden = {field for field, show in visibility.items() if show is False}

    public_fields: dict = {}
    for field, value in (record or {}).items():
        if field in ("advisor_id", "provenance") or field in hidden:
            continue
        public_fields[field] = value
    self_claims = {
        field: value
        for field, value in (profile.self_claims or {}).items()
        if field not in hidden
    }
    return {
        "advisor_id": advisor_id,
        "name": record.get("name"),
        "dept": record.get("dept"),
        "public_fields": public_fields,
        "self_claims": self_claims,
        "hidden_fields": sorted(hidden),
        "provenance": record.get("provenance", {}),
        "data_status": record.get("data_status"),
        "takedown": {
            "active": profile.takedown_at is not None,
            "effective_at": (
                profile.takedown_at.isoformat() if profile.takedown_at else None
            ),
        },
        "visibility": visibility,
    }


def submit_field_edit(
    db: Session,
    *,
    account: MentorAccount,
    field_name: str,
    new_value: str,
) -> MentorProfileEdit:
    """提交单个字段的编辑申请；同字段存在 pending 时拒绝。"""
    advisor_id = require_claimed(account)
    if field_name not in SELF_CLAIM_FIELDS:
        raise HTTPException(
            status_code=422,
            detail=f"该字段不支持导师自述（支持：{', '.join(SELF_CLAIM_FIELDS)}）",
        )
    pending = (
        db.query(MentorProfileEdit)
        .filter(
            MentorProfileEdit.account_id == account.account_id,
            MentorProfileEdit.status == EDIT_PENDING,
            MentorProfileEdit.field_name == field_name,
        )
        .one_or_none()
    )
    if pending is not None:
        raise HTTPException(status_code=409, detail="该字段已有待审批的编辑申请")
    profile = ensure_mentor_profile(db, account=account, advisor_id=advisor_id)
    old_value = (profile.self_claims or {}).get(field_name) or ""
    edit = MentorProfileEdit(
        edit_id=str(uuid.uuid4()),
        account_id=account.account_id,
        advisor_id=advisor_id,
        field_name=field_name,
        old_value=old_value,
        new_value=new_value.strip(),
        status=EDIT_PENDING,
    )
    db.add(edit)
    db.commit()
    db.refresh(edit)
    return edit


def list_my_edits(db: Session, *, account: MentorAccount) -> list[dict]:
    return [
        {
            "edit_id": item.edit_id,
            "field_name": item.field_name,
            "old_value": item.old_value,
            "new_value": item.new_value,
            "status": item.status,
            "admin_note": item.admin_note,
            "created_at": item.created_at.isoformat() if item.created_at else None,
            "decided_at": item.decided_at.isoformat() if item.decided_at else None,
        }
        for item in (
            db.query(MentorProfileEdit)
            .filter(MentorProfileEdit.account_id == account.account_id)
            .order_by(MentorProfileEdit.created_at.desc())
            .all()
        )
    ]


def get_edit(db: Session, *, edit_id: str) -> MentorProfileEdit:
    edit = db.get(MentorProfileEdit, edit_id)
    if edit is None:
        raise HTTPException(status_code=404, detail="编辑申请不存在")
    return edit


def apply_field_edit(
    db: Session,
    *,
    edit_id: str,
    reviewer: str,
    approve: bool,
    note: str | None,
) -> MentorProfileEdit:
    """审批编辑：通过则写入 self_claims（新值为空时删除该自述字段）。"""
    edit = get_edit(db, edit_id=edit_id)
    if edit.status != EDIT_PENDING:
        raise HTTPException(status_code=409, detail="该编辑申请已处理")
    now = _now()
    if approve:
        account = db.get(MentorAccount, edit.account_id)
        profile = ensure_mentor_profile(
            db, account=account, advisor_id=edit.advisor_id
        )
        claims = dict(profile.self_claims or {})
        if edit.new_value:
            claims[edit.field_name] = edit.new_value
        else:
            claims.pop(edit.field_name, None)
        profile.self_claims = claims
        profile.updated_at = now
        edit.status = EDIT_APPROVED
    else:
        edit.status = EDIT_REJECTED
    edit.decided_by = reviewer
    edit.decided_at = now
    edit.admin_note = note
    db.commit()
    db.refresh(edit)
    return edit
