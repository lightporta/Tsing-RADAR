"""导师数据加载。

提供两种加载来源：
1. JSON 兜底（开发期）：从 backend/data/mentors.json 读取旧格式数据
2. 数据库主源（生产期）：从 entities 表读 publication_status='published' 的导师

并对外提供 entity_to_legacy_dict()，把新表实体投影成旧 mentors.json 格式，
保证 GET /api/mentors 等旧接口在不改前端的前提下平滑切换。
"""

import json
import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

# data_loader.py → services/ → app/ → backend/
# Path 对象定位更直观，避免数 dirname 层数出错
_DATA_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "mentors.json"

logger = logging.getLogger(__name__)


# ────────────────────────── JSON 兜底 ──────────────────────────

@lru_cache(maxsize=1)
def load_mentors() -> list[dict[str, Any]]:
    """启动时加载旧导师库（开发期兜底，生产期由数据库覆盖）。"""
    with open(_DATA_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def reload_mentors() -> list[dict[str, Any]]:
    """强制重新加载（数据更新后调用）。"""
    load_mentors.cache_clear()
    return load_mentors()


# ────────────────────────── 数据库主源 ──────────────────────────

def _safe_query_entities(db) -> list[Any]:
    """只读 publication_status='published' 的 person 实体。"""
    from app.models.entity import Entity  # 延迟导入，避免循环依赖
    from sqlalchemy import select

    stmt = (
        select(Entity)
        .where(Entity.entity_type == "person")
        .where(Entity.publication_status == "published")
        .order_by(Entity.display_name)
    )
    return list(db.scalars(stmt))


def _entity_field_claim(db, entity_id: str, field_name: str) -> Optional[Any]:
    """取某实体某字段的公开 claim（publication_status='published'）。"""
    from app.models.claim import Claim
    from sqlalchemy import select

    stmt = (
        select(Claim)
        .where(Claim.subject_type == "entity")
        .where(Claim.subject_id == entity_id)
        .where(Claim.field_name == field_name)
        .where(Claim.publication_status == "published")
        .order_by(Claim.captured_at.desc())
        .limit(1)
    )
    return db.scalars(stmt).first()


def _entity_department(db, entity_id: str) -> Optional[str]:
    """通过 relations 取实体所属院系名（affiliated_with → organization）。"""
    from app.models.entity import Entity, Relation
    from sqlalchemy import select

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


def _entity_directions(db, entity_id: str) -> list[dict[str, Any]]:
    """取实体已发布的研究方向。"""
    from app.models.direction import Direction, EntityDirection
    from sqlalchemy import select

    stmt = (
        select(Direction, EntityDirection.direction_scope)
        .join(EntityDirection, EntityDirection.direction_id == Direction.direction_id)
        .where(EntityDirection.entity_id == entity_id)
    )
    rows = db.execute(stmt).all()
    return [
        {
            "level_1": d.level_1,
            "level_2": d.level_2,
            "specific_topic": d.specific_topic,
            "direction_scope": scope,
        }
        for d, scope in rows
    ]


def entity_to_legacy_dict(db, entity) -> dict[str, Any]:
    """把新表实体投影成旧 mentors.json 格式，保持前端兼容。

    派生字段（radar_traits/popularity/sector/score/reason）保持默认值，
    实际值由推荐算法在 /api/match 中计算。
    """
    directions = _entity_directions(db, entity.entity_id)
    dept = _entity_department(db, entity.entity_id)

    def _field(field_name: str) -> Optional[str]:
        c = _entity_field_claim(db, entity.entity_id, field_name)
        return c.normalized_value if c else None

    tags = list({d["level_1"] for d in directions if d.get("level_1")})
    field_text = " / ".join(d["specific_topic"] for d in directions) or (
        _field("field") or ""
    )

    return {
        "name": entity.display_name,
        "dept": dept or _field("department") or "",
        "field": field_text,
        "tags": tags,
        "profile_text": _field("profile_text") or "",
        "recent_papers": [],  # 派生/可选，留空
        "contact_email": _field("public_work_email") or "",
        "office_loc": _field("office_location") or "",
        "score": 0,            # 派生字段，由推荐层计算
        "reason": "",
        "radar_traits": {},    # 派生字段
        "popularity": 0,
        "sector": 0,
        "projects": [],
        "recruitments": [],
        "entity_id": entity.entity_id,  # 新增：前端可用来调用 v2 接口
    }


@lru_cache(maxsize=1)
def load_advisors_from_db() -> list[dict[str, Any]]:
    """加载所有已发布导师，按旧格式返回。

    返回前会清缓存后再调一次，因此适合启动期或显式 reload 使用。
    请求期请直接用 get_db() 在路由内查询，避免长事务。
    """
    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        entities = _safe_query_entities(db)
        return [entity_to_legacy_dict(db, e) for e in entities]
    finally:
        db.close()


def reload_advisors_from_db() -> list[dict[str, Any]]:
    """强制重新加载已发布导师。"""
    load_advisors_from_db.cache_clear()
    return load_advisors_from_db()


def load_mentors_with_fallback() -> list[dict[str, Any]]:
    """优先数据库，失败降级到 JSON。

    Agent-3 改造清单中所有「数据源改 DB」的接口都应使用本函数，
    保证数据库不可用时不影响前端基础展示。
    """
    try:
        advisors = load_advisors_from_db()
        if advisors:
            return advisors
        # 数据库可用但无已发布记录 → 降级 JSON（开发期典型场景）
        return load_mentors()
    except Exception as e:  # noqa: BLE001
        logger.warning("数据库加载失败，降级到 JSON: %s", e)
        return load_mentors()
