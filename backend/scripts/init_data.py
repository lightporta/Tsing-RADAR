"""数据初始化脚本。

两种用途：
1. 旧格式导入：把 backend/data/mentors.json 导入旧 advisors 表（开发期）
2. 新规范导入：把 data_collection/batches/batch_crawl_*.json 导入 9 张新表

CLI：
  # 旧格式
  python -m scripts.init_data --legacy

  # 新规范（默认全部 withheld，需审核后才改 published）
  python -m scripts.init_data --import-batch /path/to/batch_crawl_xxx.json

  # 把通过审核的 withheld 记录批量发布（需管理员 token）
  python -m scripts.init_data --publish-batch <batch_id> --admin-token xxx
"""

import argparse
import json
import logging
import os
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

# 允许 `python -m scripts.init_data` 与 `python scripts/init_data.py` 两种调用
_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.db.session import SessionLocal, init_db  # noqa: E402
from app.models.advisor import Advisor  # noqa: E402
from app.models.entity import Entity, EntityName, Relation  # noqa: E402
from app.models.direction import Direction, EntityDirection  # noqa: E402
from app.models.catalog import CatalogLink  # noqa: E402
from app.models.opportunity import Opportunity  # noqa: E402
from app.models.claim import Claim, Source  # noqa: E402

logger = logging.getLogger("init_data")
logger.setLevel(logging.INFO)
if not logger.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

_UTC_NOW = datetime.utcnow  # 仅用于默认时间戳；批次导入用源数据 captured_at


# ─────────────────────── 旧格式：mentors.json → advisors ───────────────────────

def import_legacy() -> int:
    """把旧 mentors.json 导入 advisors 表（开发期兼容）。"""
    init_db()
    data_path = _BACKEND / "data" / "mentors.json"
    with open(data_path, "r", encoding="utf-8") as f:
        mentors = json.load(f)

    db = SessionLocal()
    try:
        for i, m in enumerate(mentors):
            advisor = Advisor(
                advisor_id=f"T{1000 + i}",
                name=m.get("name", ""),
                department=m.get("dept", ""),
                field=m.get("field", ""),
                tags=m.get("tags", []),
                contact_email=m.get("contact_email"),
                office_loc=m.get("office_loc"),
                radar_traits=m.get("radar_traits", {}),
                popularity=m.get("popularity", 0),
                sector=0 if m.get("sector", "国") == "国" else 1,
            )
            db.merge(advisor)
        db.commit()
        print(f"✅ 已导入 {len(mentors)} 位导师到 advisors 表")
        return len(mentors)
    finally:
        db.close()


# ─────────────────────── 新规范：batch JSON → 9 张表 ───────────────────────

def _parse_dt(v: Any) -> Optional[datetime]:
    if not v:
        return None
    if isinstance(v, datetime):
        return v
    try:
        # 支持 "2026-08-04T10:00:00+08:00" 与 "2026-08-04T10:00:00"
        s = str(v).replace("Z", "+00:00")
        return datetime.fromisoformat(s)
    except Exception:  # noqa: BLE001
        return None


def _merge_model(db, model_cls, pk_name: str, pk_value: str, **fields):
    """upsert：按主键存在则更新，否则插入。"""
    existing = db.get(model_cls, pk_value)
    if existing:
        for k, v in fields.items():
            if v is not None:
                setattr(existing, k, v)
        return existing
    obj = model_cls(**{pk_name: pk_value}, **fields)
    db.add(obj)
    return obj


def import_radar_batch(batch_path: str, *, default_publication_status: str = "withheld") -> dict:
    """导入一个符合规范的批次 JSON 到 9 张新表。

    幂等：相同 ID 再次导入会更新而非报错。
    安全：所有记录 publication_status=withheld，需经审核才置为 published。
    """
    init_db()
    batch_path = Path(batch_path)
    with open(batch_path, "r", encoding="utf-8") as f:
        batch = json.load(f)

    # 规范允许顶层包装 {batch_id, generated_at, entities, ...} 或裸数组
    if isinstance(batch, dict):
        batch_id = batch.get("batch_id") or str(uuid.uuid4())
        sources = batch.get("sources", []) or []
        entities = batch.get("entities", []) or []
        entity_names = batch.get("entity_names", []) or []
        relations = batch.get("relations", []) or []
        directions = batch.get("directions", []) or []
        entity_directions = batch.get("entity_directions", []) or []
        catalog_links = batch.get("catalog_links", []) or []
        opportunities = batch.get("opportunities", []) or []
        claims = batch.get("claims", []) or []
    else:
        raise ValueError("批次 JSON 必须为对象形式，包含 entities/claims/sources 等键")

    counters = {
        "sources": 0, "entities": 0, "entity_names": 0, "relations": 0,
        "directions": 0, "entity_directions": 0, "catalog_links": 0,
        "opportunities": 0, "claims": 0,
    }

    db = SessionLocal()
    try:
        # sources
        for s in sources:
            _merge_model(
                db, Source, "source_id", s["source_id"],
                source_class=s.get("source_class") or "A",
                source_type=s.get("source_type"),
                source_title=s.get("source_title"),
                public_url=s.get("public_url"),
                publisher=s.get("publisher"),
                published_at=_parse_dt(s.get("published_at")),
                captured_at=_parse_dt(s.get("captured_at")) or datetime.utcnow(),
                page_content_sha256=s.get("page_content_sha256"),
                snapshot_id=s.get("snapshot_id"),
                access_status=s.get("access_status"),
                visibility=s.get("visibility", "public"),
            )
            counters["sources"] += 1

        # entities
        for e in entities:
            _merge_model(
                db, Entity, "entity_id", e["entity_id"],
                entity_type=e.get("entity_type") or "person",
                display_name=e.get("display_name") or e.get("name_zh") or "",
                name_zh=e.get("name_zh"),
                name_en=e.get("name_en"),
                identity_status=e.get("identity_status", "unresolved"),
                review_status=e.get("review_status", "pending_review"),
                publication_status=e.get("publication_status", default_publication_status),
                created_at=_parse_dt(e.get("created_at")) or datetime.utcnow(),
                updated_at=_parse_dt(e.get("updated_at")) or datetime.utcnow(),
                verified_at=_parse_dt(e.get("verified_at")),
                next_review_at=_parse_dt(e.get("next_review_at")),
            )
            counters["entities"] += 1

        # entity_names
        for n in entity_names:
            _merge_model(
                db, EntityName, "name_id", n["name_id"],
                entity_id=n.get("entity_id"),
                name_type=n.get("name_type"),
                name_value=n.get("name_value"),
                claim_id=n.get("claim_id"),
                is_primary=bool(n.get("is_primary", False)),
            )
            counters["entity_names"] += 1

        # relations
        for r in relations:
            _merge_model(
                db, Relation, "relation_id", r["relation_id"],
                subject_entity_id=r.get("subject_entity_id"),
                relation_type=r.get("relation_type") or "affiliated_with",
                object_entity_id=r.get("object_entity_id"),
                valid_from=_parse_dt(r.get("valid_from")),
                valid_until=_parse_dt(r.get("valid_until")),
                claim_id=r.get("claim_id"),
                relation_status=r.get("relation_status", "active"),
            )
            counters["relations"] += 1

        # directions
        for d in directions:
            _merge_model(
                db, Direction, "direction_id", d["direction_id"],
                level_1=d.get("level_1") or "",
                level_2=d.get("level_2"),
                specific_topic=d.get("specific_topic") or "",
                application_context=d.get("application_context"),
                method_or_technology=d.get("method_or_technology"),
                normalization_version=d.get("normalization_version"),
            )
            counters["directions"] += 1

        # entity_directions
        for ed in entity_directions:
            _merge_model(
                db, EntityDirection, "entity_direction_id", ed["entity_direction_id"],
                entity_id=ed.get("entity_id"),
                direction_id=ed.get("direction_id"),
                direction_scope=ed.get("direction_scope", "current_official"),
                valid_from=_parse_dt(ed.get("valid_from")),
                valid_until=_parse_dt(ed.get("valid_until")),
                claim_id=ed.get("claim_id"),
            )
            counters["entity_directions"] += 1

        # catalog_links
        for cl in catalog_links:
            _merge_model(
                db, CatalogLink, "catalog_link_id", cl["catalog_link_id"],
                catalog_snapshot_id=cl.get("catalog_snapshot_id"),
                academic_year=cl.get("academic_year"),
                catalog_type=cl.get("catalog_type"),
                department_id=cl.get("department_id"),
                program_id=cl.get("program_id"),
                direction_id=cl.get("direction_id"),
                advisor_or_group_id=cl.get("advisor_or_group_id"),
                resolved_entity_id=cl.get("resolved_entity_id"),
                identity_resolution_status=cl.get("identity_resolution_status", "unresolved"),
                relation_claim_id=cl.get("relation_claim_id"),
            )
            counters["catalog_links"] += 1

        # opportunities（默认 withheld）
        for op in opportunities:
            valid_until = _parse_dt(op.get("valid_until"))
            if not valid_until:
                # 没有 valid_until 不允许入库（动态事实必须有）
                logger.warning("opportunity %s 缺 valid_until，跳过", op.get("opportunity_id"))
                continue
            _merge_model(
                db, Opportunity, "opportunity_id", op["opportunity_id"],
                entity_id=op.get("entity_id"),
                opportunity_type=op.get("opportunity_type"),
                title=op.get("title"),
                target_stage=op.get("target_stage"),
                direction_id=op.get("direction_id"),
                location=op.get("location"),
                published_at=_parse_dt(op.get("published_at")),
                deadline_at=_parse_dt(op.get("deadline_at")),
                valid_until=valid_until,
                opportunity_status=op.get("opportunity_status", "unknown"),
                application_channel=op.get("application_channel"),
                claim_id=op.get("claim_id"),
                review_status=op.get("review_status", "pending_review"),
                publication_status=op.get("publication_status", default_publication_status),
            )
            counters["opportunities"] += 1

        # claims（默认 withheld）
        for c in claims:
            fragment_sha = c.get("fragment_sha256")
            if not fragment_sha:
                logger.warning("claim %s 缺 fragment_sha256，跳过", c.get("claim_id"))
                continue
            _merge_model(
                db, Claim, "claim_id", c["claim_id"],
                evidence_id=c.get("evidence_id"),
                subject_type=c.get("subject_type"),
                subject_id=c.get("subject_id"),
                field_name=c.get("field_name"),
                normalized_value=c.get("normalized_value"),
                raw_text=c.get("raw_text"),
                source_id=c.get("source_id"),
                captured_at=_parse_dt(c.get("captured_at")) or datetime.utcnow(),
                valid_from=_parse_dt(c.get("valid_from")),
                valid_until=_parse_dt(c.get("valid_until")),
                page_content_sha256=c.get("page_content_sha256"),
                fragment_sha256=fragment_sha,
                snapshot_id=c.get("snapshot_id"),
                capture_method=c.get("capture_method", "crawler"),
                method_version=c.get("method_version"),
                normalization_version=c.get("normalization_version"),
                verification_status=c.get("verification_status", "unverified"),
                conflict_status=c.get("conflict_status", "none"),
                confidence=c.get("confidence"),
                review_status=c.get("review_status", "pending_review"),
                publication_status=c.get("publication_status", default_publication_status),
                collector_role_id=c.get("collector_role_id"),
                batch_id=c.get("batch_id") or batch_id,
            )
            counters["claims"] += 1

        db.commit()
        logger.info("✅ 批次 %s 导入完成：%s", batch_id, counters)
        return {"batch_id": batch_id, "counters": counters}
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# ─────────────────────── 发布门禁 ───────────────────────

def publish_batch(batch_id: str, *, admin_token: str) -> dict:
    """把一个批次内通过审核的 withheld 记录批量置为 published。

    要求：
    - 任何 review_status != 'approved' 的记录不发布
    - 任何 verification_status == 'rejected' 的 claim 不发布
    - 仅管理员调用，需 admin_token
    """
    from app.core.config import settings

    if admin_token != settings.ADMIN_TOKEN:
        raise PermissionError("admin_token 不匹配，禁止发布")

    init_db()
    db = SessionLocal()
    published = {"claims": 0, "entities": 0, "opportunities": 0}
    try:
        # claims
        for c in db.query(Claim).filter(Claim.batch_id == batch_id):
            if c.review_status == "approved" and c.verification_status != "rejected":
                c.publication_status = "published"
                published["claims"] += 1
        # entities（按 batch 内 claim 关联的 subject 释放）
        ent_ids = {
            c.subject_id for c in db.query(Claim).filter(
                Claim.batch_id == batch_id,
                Claim.subject_type == "entity",
                Claim.review_status == "approved",
            )
        }
        for eid in ent_ids:
            ent = db.get(Entity, eid)
            if ent and ent.review_status == "approved":
                ent.publication_status = "published"
                published["entities"] += 1
        # opportunities
        for op in db.query(Opportunity).filter(Opportunity.claim_id.in_(
            [c.claim_id for c in db.query(Claim).filter(
                Claim.batch_id == batch_id, Claim.subject_type == "opportunity"
            )]
        )):
            if op.review_status == "approved":
                op.publication_status = "published"
                published["opportunities"] += 1
        db.commit()
        return {"batch_id": batch_id, "published": published}
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# ─────────────────────── CLI ───────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Tsing-RADAR 数据初始化")
    parser.add_argument("--legacy", action="store_true", help="导入旧 mentors.json 到 advisors 表")
    parser.add_argument("--import-batch", metavar="PATH", help="导入新规范批次 JSON")
    parser.add_argument("--publish-batch", metavar="BATCH_ID", help="发布批次")
    parser.add_argument("--admin-token", default=os.environ.get("ADMIN_TOKEN", "admin"))
    args = parser.parse_args()

    if args.import_batch:
        result = import_radar_batch(args.import_batch)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.publish_batch:
        result = publish_batch(args.publish_batch, admin_token=args.admin_token)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        # 默认旧格式
        import_legacy()


if __name__ == "__main__":
    main()
