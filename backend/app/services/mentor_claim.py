"""导师档案认领：候选匹配（JSON 发行物 + advisors DB 并集）与审批。

- 唯一候选（归一化 name+dept 后仅 1 个）→ factor_used=auto_unique，直接绑定；
- 多候选/无匹配 → 人工审批（claim_pending）。
- 认领成功后立即创建 mentor_profiles 覆盖层（本期仅导师端+管理端可见）。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.advisor import Advisor
from app.models.mentor_account import (
    MentorAccount,
    STATUS_CLAIM_PENDING,
    STATUS_CLAIMED,
    STATUS_UNCLAIMED,
)
from app.models.mentor_claim import (
    CLAIM_APPROVED,
    CLAIM_PENDING,
    CLAIM_REJECTED,
    FACTOR_AUTO_UNIQUE,
    FACTOR_MANUAL,
    MentorClaim,
)
from app.models.mentor_profile import MentorProfile
from app.services.data_loader import load_mentors
from app.services.mentor_resources import (
    _normalized_identity,
    grouped_mentor_resources,
)
from app.services.mentor_verification import campus_card_approved


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _candidate_item(record: dict, *, in_db: bool) -> dict:
    return {
        "advisor_id": str(record.get("advisor_id")),
        "name": record.get("name"),
        "dept": record.get("dept"),
        "title": record.get("title"),
        "resource_types": record.get("resource_types"),
        "in_db": in_db,
    }


def find_candidates(
    db: Session, *, name: str, department: str
) -> list[dict]:
    """按归一化 name/dept 匹配公开候选（JSON 发行物 + advisors DB 并集）。"""
    target_name = _normalized_identity(name)
    target_dept = _normalized_identity(department)
    if not target_name:
        return []
    json_ids: set[str] = set()
    candidates: list[dict] = []
    for record in grouped_mentor_resources(load_mentors()):
        if _normalized_identity(record.get("name")) != target_name:
            continue
        if target_dept and _normalized_identity(record.get("dept")) != target_dept:
            continue
        json_ids.add(str(record.get("advisor_id")))
        candidates.append(_candidate_item(record, in_db=False))

    # advisors 表并集：JSON 中不存在的旧库记录也可被认领。
    db_rows = db.query(Advisor).all()
    db_ids: set[str] = set()
    for advisor in db_rows:
        if _normalized_identity(advisor.name) != target_name:
            continue
        if target_dept and _normalized_identity(advisor.department) != target_dept:
            continue
        db_ids.add(str(advisor.advisor_id))
        if str(advisor.advisor_id) not in json_ids:
            candidates.append(
                {
                    "advisor_id": str(advisor.advisor_id),
                    "name": advisor.name,
                    "dept": advisor.department,
                    "title": None,
                    "resource_types": None,
                    "in_db": True,
                }
            )
    for item in candidates:
        if item["advisor_id"] in db_ids:
            item["in_db"] = True
    candidates.sort(key=lambda item: (item["name"] or "", item["advisor_id"]))
    return candidates


def _candidate_matches(candidates: list[dict]) -> list[dict]:
    """按归一化 name+dept 聚合候选，返回独立的人（去重 advisor 记录）。"""
    seen: dict[tuple[str, str], list[dict]] = {}
    for candidate in candidates:
        key = (
            _normalized_identity(candidate.get("name")),
            _normalized_identity(candidate.get("dept")),
        )
        seen.setdefault(key, []).append(candidate)
    merged: list[dict] = []
    for members in seen.values():
        primary = dict(members[0])
        primary["in_db"] = any(item["in_db"] for item in members)
        merged.append(primary)
    return merged


def submit_claim(
    db: Session,
    *,
    account: MentorAccount,
    candidate_id: str,
    name: str,
    department: str,
) -> dict:
    """提交认领；姓名空间唯一候选自动绑定，多候选进入人工审批队列。"""
    if account.status == STATUS_CLAIMED:
        raise HTTPException(status_code=409, detail="该账号已绑定导师档案")
    if account.status == STATUS_CLAIM_PENDING:
        raise HTTPException(status_code=409, detail="已有待审批的认领申请")
    if not candidate_id:
        raise HTTPException(status_code=422, detail="必须指定认领的候选档案")

    # 校园卡人工审核是认领的前置条件：邮箱验证码只用于登录，
    # 不再视为导师身份认证（修改说明 §1）。
    if not campus_card_approved(db, account_id=account.account_id):
        raise HTTPException(
            status_code=403,
            detail="需先上传校园卡并通过管理员人工审核，才能认领导师档案",
        )

    # 按姓名全量匹配（跨院系），判定唯一候选；
    # 若院系非空则与所选候选校验一致，防止误选重名他人。
    candidates = find_candidates(db, name=name, department="")
    target = next(
        (item for item in candidates if item["advisor_id"] == candidate_id), None
    )
    if target is None:
        raise HTTPException(status_code=404, detail="未找到该候选导师档案")
    if department.strip() and _normalized_identity(department) != _normalized_identity(
        target.get("dept")
    ):
        raise HTTPException(status_code=404, detail="候选档案与院系不匹配")

    already_claimed = (
        db.query(MentorAccount)
        .filter(
            MentorAccount.status == STATUS_CLAIMED,
            MentorAccount.advisor_id == candidate_id,
            MentorAccount.account_id != account.account_id,
        )
        .one_or_none()
    )
    if already_claimed is not None:
        raise HTTPException(status_code=409, detail="该导师档案已被其他账号认领")

    people = _candidate_matches(candidates)
    now = _now()
    if len(people) == 1:
        claim = MentorClaim(
            claim_id=str(uuid.uuid4()),
            account_id=account.account_id,
            advisor_id=candidate_id,
            candidate_json=[target],
            factor_used=FACTOR_AUTO_UNIQUE,
            status=CLAIM_APPROVED,
            decided_by="auto",
            decided_at=now,
            admin_note="唯一候选，自动绑定",
        )
        account.status = STATUS_CLAIMED
        account.advisor_id = candidate_id
        ensure_mentor_profile(db, account=account, advisor_id=candidate_id, commit=False)
        db.add(claim)
        db.commit()
        return {"status": "claimed", "claim_id": claim.claim_id, "factor": FACTOR_AUTO_UNIQUE}

    claim = MentorClaim(
        claim_id=str(uuid.uuid4()),
        account_id=account.account_id,
        advisor_id=candidate_id,
        candidate_json=[target],
        factor_used=FACTOR_MANUAL,
        status=CLAIM_PENDING,
    )
    account.status = STATUS_CLAIM_PENDING
    db.add(claim)
    db.commit()
    return {"status": "pending_review", "claim_id": claim.claim_id, "factor": FACTOR_MANUAL}


def ensure_mentor_profile(
    db: Session,
    *,
    account: MentorAccount,
    advisor_id: str,
    commit: bool = True,
) -> MentorProfile:
    """创建（幂等）导师档案覆盖层；profile 与账号/档案一一对应。"""
    profile = (
        db.query(MentorProfile)
        .filter(MentorProfile.account_id == account.account_id)
        .one_or_none()
    )
    if profile is None:
        profile = MentorProfile(
            profile_id=str(uuid.uuid4()),
            account_id=account.account_id,
            advisor_id=advisor_id,
            self_claims={},
            visibility={},
        )
        db.add(profile)
        if commit:
            db.commit()
            db.refresh(profile)
    return profile


def get_claim(db: Session, *, claim_id: str) -> MentorClaim:
    claim = db.get(MentorClaim, claim_id)
    if claim is None:
        raise HTTPException(status_code=404, detail="认领申请不存在")
    return claim


def approve_claim(
    db: Session, *, claim_id: str, reviewer: str, note: str | None
) -> MentorClaim:
    claim = get_claim(db, claim_id=claim_id)
    if claim.status != CLAIM_PENDING:
        raise HTTPException(status_code=409, detail="该认领申请已处理")
    account = db.get(MentorAccount, claim.account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="关联导师账号不存在")
    taken = (
        db.query(MentorAccount)
        .filter(
            MentorAccount.status == STATUS_CLAIMED,
            MentorAccount.advisor_id == claim.advisor_id,
            MentorAccount.account_id != account.account_id,
        )
        .one_or_none()
    )
    if taken is not None:
        raise HTTPException(status_code=409, detail="该导师档案已被其他账号认领")
    now = _now()
    claim.status = CLAIM_APPROVED
    claim.decided_by = reviewer
    claim.decided_at = now
    claim.admin_note = note
    account.status = STATUS_CLAIMED
    account.advisor_id = claim.advisor_id
    account.updated_at = now
    ensure_mentor_profile(db, account=account, advisor_id=claim.advisor_id, commit=False)
    db.commit()
    db.refresh(claim)
    return claim


def reject_claim(
    db: Session, *, claim_id: str, reviewer: str, note: str | None
) -> MentorClaim:
    claim = get_claim(db, claim_id=claim_id)
    if claim.status != CLAIM_PENDING:
        raise HTTPException(status_code=409, detail="该认领申请已处理")
    now = _now()
    claim.status = CLAIM_REJECTED
    claim.decided_by = reviewer
    claim.decided_at = now
    claim.admin_note = note
    account = db.get(MentorAccount, claim.account_id)
    if account is not None and account.status == STATUS_CLAIM_PENDING:
        account.status = STATUS_UNCLAIMED
        account.updated_at = now
    db.commit()
    db.refresh(claim)
    return claim
