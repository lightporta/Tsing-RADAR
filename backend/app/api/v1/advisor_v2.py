"""导师 v2 接口（基于 RADAR 9 表规范，按 Agent-4 统一标准）。

新增 5 个接口：
  GET /api/advisors                    已发布导师列表（含 evidence）
  GET /api/advisors/{entity_id}        单个导师详情（事实类）
  GET /api/advisors/{entity_id}/directions   研究方向
  GET /api/advisors/{entity_id}/opportunities 公开机会（带时效过滤）
  GET /api/advisors/{entity_id}/evidence      某字段的公开证据

设计要点（与 Agent-4 一致）：
  - 统一响应格式 {code, message, data, evidence, derived_signal, disclaimer}
  - 只返回 publication_status='published'
  - 不返回私域字段（consent_id / 私人手机/邮箱 / 反馈原文）
  - 派生字段（score/radar_traits/popularity）不在事实接口暴露
  - 动态机会校验 valid_until，过期不返回 open
"""

from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.entity import Entity, Relation
from app.models.direction import Direction, EntityDirection
from app.models.opportunity import Opportunity
from app.models.claim import Claim, Source
from app.models.catalog import CatalogLink

router = APIRouter()


# ─────────────────────── 工具函数 ───────────────────────

def _pub_claims_for(db: Session, subject_id: str, field_name: Optional[str] = None) -> list[Claim]:
    """取某主体的已发布 claims，按 captured_at 倒序。"""
    stmt = (
        select(Claim)
        .where(Claim.subject_type == "entity")
        .where(Claim.subject_id == subject_id)
        .where(Claim.publication_status == "published")
    )
    if field_name:
        stmt = stmt.where(Claim.field_name == field_name)
    stmt = stmt.order_by(Claim.captured_at.desc())
    return list(db.scalars(stmt))


def _latest_claim_value(db: Session, subject_id: str, field_name: str) -> Optional[str]:
    claims = _pub_claims_for(db, subject_id, field_name)
    return claims[0].normalized_value if claims else None


def _entity_department(db: Session, entity_id: str) -> Optional[str]:
    """通过 relations 取所属院系 display_name。"""
    stmt = (
        select(Entity)
        .join(Relation, Relation.object_entity_id == Entity.entity_id)
        .where(Relation.subject_entity_id == entity_id)
        .where(Relation.relation_type == "affiliated_with")
        .where(Relation.relation_status == "active")
        .limit(1)
    )
    org = db.scalars(stmt).first()
    return org.display_name if org else None


def _entity_evidence(db: Session, subject_id: str) -> Optional[dict]:
    """取主体最近一条已发布 claim 的 evidence（用于响应外层）。"""
    c = _pub_claims_for(db, subject_id)
    if not c:
        return None
    c = c[0]
    s = db.get(Source, c.source_id)
    return {
        "source_url": s.public_url if s else None,
        "source_class": s.source_class if s else None,
        "captured_at": c.captured_at.isoformat() if c.captured_at else None,
        "evidence_id": c.evidence_id or c.claim_id,
        "raw_text_excerpt": (c.raw_text or "")[:500],
    }


def _get_published_entity(db: Session, entity_id: str) -> Entity:
    """取已发布的 person 实体；不存在或未发布统一 404。"""
    ent = db.get(Entity, entity_id)
    if not ent or ent.entity_type != "person" or ent.publication_status != "published":
        raise HTTPException(status_code=404, detail={
            "code": 2001, "message": "导师不存在或未发布"
        })
    return ent


# ─────────────────────── 接口 ───────────────────────

@router.get("/advisors")
def list_advisors(
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    department: Optional[str] = Query(None, description="按院系过滤，逗号分隔多值"),
    db: Session = Depends(get_db),
):
    """已发布导师列表（事实类，derived_signal=false）。

    不含派生字段；每个导师附最近一条证据的 source_url。
    """
    stmt = (
        select(Entity)
        .where(Entity.entity_type == "person")
        .where(Entity.publication_status == "published")
        .order_by(Entity.display_name)
    )
    entities = list(db.scalars(stmt))

    # 院系过滤
    if department:
        wanted = {d.strip() for d in department.split(",") if d.strip()}
        entities = [e for e in entities if _entity_department(db, e.entity_id) in wanted]

    total = len(entities)
    start = (page - 1) * size
    page_entities = entities[start:start + size]

    data = []
    for e in page_entities:
        data.append({
            "entity_id": e.entity_id,
            "display_name": e.display_name,
            "name_zh": e.name_zh,
            "name_en": e.name_en,
            "department": _entity_department(db, e.entity_id),
            "title": _latest_claim_value(db, e.entity_id, "title"),
            "official_homepage": _latest_claim_value(db, e.entity_id, "official_homepage"),
        })

    return {
        "code": 0,
        "message": "ok",
        "data": data,
        "pagination": {"page": page, "size": size, "total": total},
        "derived_signal": False,
        "disclaimer": None,
    }


@router.get("/advisors/{entity_id}")
def get_advisor(entity_id: str, db: Session = Depends(get_db)):
    """单个导师详情（事实类，附完整证据）。"""
    e = _get_published_entity(db, entity_id)
    dept = _entity_department(db, e.entity_id)

    # 研究方向
    dir_stmt = (
        select(Direction, EntityDirection.direction_scope)
        .join(EntityDirection, EntityDirection.direction_id == Direction.direction_id)
        .where(EntityDirection.entity_id == e.entity_id)
    )
    directions = [
        {
            "level_1": d.level_1,
            "level_2": d.level_2,
            "specific_topic": d.specific_topic,
            "direction_scope": scope,
        }
        for d, scope in db.execute(dir_stmt).all()
    ]

    # 字段事实
    def _val(field: str) -> Optional[str]:
        return _latest_claim_value(db, e.entity_id, field)

    data = {
        "entity_id": e.entity_id,
        "entity_type": e.entity_type,
        "display_name": e.display_name,
        "name_zh": e.name_zh,
        "name_en": e.name_en,
        "department": dept,
        "title": _val("title"),
        "official_homepage": _val("official_homepage"),
        "public_work_email": _val("public_work_email"),
        "office_location": _val("office_location"),
        "institute": _val("institute"),
        "directions": directions,
    }

    return {
        "code": 0,
        "message": "ok",
        "data": data,
        "evidence": _entity_evidence(db, e.entity_id),
        "derived_signal": False,
        "disclaimer": None,
    }


@router.get("/advisors/{entity_id}/directions")
def get_advisor_directions(entity_id: str, db: Session = Depends(get_db)):
    """导师研究方向（含 direction_scope，区分证据强度）。"""
    e = _get_published_entity(db, entity_id)
    stmt = (
        select(Direction, EntityDirection.direction_scope)
        .join(EntityDirection, EntityDirection.direction_id == Direction.direction_id)
        .where(EntityDirection.entity_id == e.entity_id)
    )
    directions = [
        {
            "level_1": d.level_1,
            "level_2": d.level_2,
            "specific_topic": d.specific_topic,
            "direction_scope": scope,
            "application_context": d.application_context,
            "method_or_technology": d.method_or_technology,
        }
        for d, scope in db.execute(stmt).all()
    ]
    return {
        "code": 0,
        "message": "ok",
        "data": directions,
        "evidence": _entity_evidence(db, e.entity_id),
        "derived_signal": False,
        "disclaimer": None,
    }


@router.get("/advisors/{entity_id}/opportunities")
def get_advisor_opportunities(entity_id: str, db: Session = Depends(get_db)):
    """导师公开机会（仅 open/unknown 且未过期）。"""
    e = _get_published_entity(db, entity_id)
    now = datetime.utcnow()
    stmt = (
        select(Opportunity)
        .where(Opportunity.entity_id == e.entity_id)
        .where(Opportunity.publication_status == "published")
        .where(Opportunity.opportunity_status.in_(["open", "unknown"]))
        .where(Opportunity.valid_until >= now)
        .order_by(Opportunity.valid_until.asc())
    )
    ops = list(db.scalars(stmt))

    data = []
    for op in ops:
        # 取该机会对应的 claim/source 作为证据
        claim = db.get(Claim, op.claim_id) if op.claim_id else None
        source = db.get(Source, claim.source_id) if claim and claim.source_id else None
        data.append({
            "opportunity_id": op.opportunity_id,
            "opportunity_type": op.opportunity_type,
            "title": op.title,
            "target_stage": op.target_stage,
            "published_at": op.published_at.isoformat() if op.published_at else None,
            "deadline_at": op.deadline_at.isoformat() if op.deadline_at else None,
            "valid_until": op.valid_until.isoformat() if op.valid_until else None,
            "opportunity_status": op.opportunity_status,
            "application_channel": op.application_channel,
            "evidence": {
                "source_url": source.public_url if source else None,
                "source_class": source.source_class if source else None,
                "captured_at": claim.captured_at.isoformat() if claim and claim.captured_at else None,
                "evidence_id": (claim.evidence_id or claim.claim_id) if claim else None,
            } if claim else None,
        })

    return {
        "code": 0,
        "message": "ok",
        "data": data,
        "derived_signal": False,
        "disclaimer": None,
    }


@router.get("/advisors/{entity_id}/evidence")
def get_advisor_evidence(
    entity_id: str,
    field_name: Optional[str] = Query(None, description="可选：只看某字段的证据"),
    db: Session = Depends(get_db),
):
    """导师字段级公开证据（可追溯）。"""
    e = _get_published_entity(db, entity_id)
    claims = _pub_claims_for(db, e.entity_id, field_name)

    data = []
    for c in claims:
        s = db.get(Source, c.source_id)
        data.append({
            "field_name": c.field_name,
            "normalized_value": c.normalized_value,
            "raw_text_excerpt": (c.raw_text or "")[:500],
            "source_url": s.public_url if s else None,
            "source_class": s.source_class if s else None,
            "captured_at": c.captured_at.isoformat() if c.captured_at else None,
            "evidence_id": c.evidence_id or c.claim_id,
            "verification_status": c.verification_status,
        })

    return {
        "code": 0,
        "message": "ok",
        "data": data,
        "derived_signal": False,
        "disclaimer": None,
    }


@router.get("/catalog/{academic_year}")
def get_catalog(academic_year: str, db: Session = Depends(get_db)):
    """年度招生目录（只表述「出现在目录」，不推断招生）。

    禁止返回「当前一定招生」「有名额」相关表述。
    """
    stmt = (
        select(CatalogLink)
        .where(CatalogLink.academic_year == academic_year)
        .order_by(CatalogLink.department_id)
    )
    links = list(db.scalars(stmt))

    # 按院系聚合
    by_dept: dict[str, dict] = {}
    for link in links:
        dept_org = db.get(Entity, link.department_id) if link.department_id else None
        dept_name = dept_org.display_name if dept_org else "未知院系"
        direction = db.get(Direction, link.direction_id) if link.direction_id else None

        bucket = by_dept.setdefault(dept_name, {
            "department": dept_name,
            "academic_year": academic_year,
            "entries": [],
        })
        # 解析的导师姓名
        resolved_name = None
        if link.resolved_entity_id:
            ent = db.get(Entity, link.resolved_entity_id)
            if ent:
                resolved_name = ent.display_name
        bucket["entries"].append({
            "major": direction.level_1 if direction else None,
            "direction": direction.specific_topic if direction else None,
            "degree_type": direction.level_2 if direction else None,
            "resolved_advisor": resolved_name,
            "identity_resolution_status": link.identity_resolution_status,
        })

    # 取一条来源作为证据
    sample_link = links[0] if links else None
    evidence = None
    if sample_link and sample_link.catalog_snapshot_id:
        # 从 sources 找该 snapshot
        s = db.scalars(
            select(Source).where(Source.snapshot_id == sample_link.catalog_snapshot_id).limit(1)
        ).first()
        if s:
            evidence = {
                "source_url": s.public_url,
                "source_class": s.source_class,
                "captured_at": s.captured_at.isoformat() if s.captured_at else None,
                "evidence_id": s.source_id,
            }

    return {
        "code": 0,
        "message": "ok",
        "data": list(by_dept.values()),
        "evidence": evidence,
        "derived_signal": False,
        "disclaimer": "目录信息仅证明导师出现在该年度官方目录中，不代表当前一定招生或有名额。",
    }
