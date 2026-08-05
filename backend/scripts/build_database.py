"""构建导师数据库批次 JSON（Agent-1 输出 / Agent-2 输入）。

读取：
  professors_info/official_*.json      各院系教师名录（A 级来源）
  professors_info/sources_meta.json    页面快照元数据（含 SHA-256 + snapshot_id + captured_at）
  professors_info/招生目录_完整.json    2027 招生目录（catalog_only 来源）

输出：
  data_collection/batches/batch_crawl_<YYYYMMDD>_<batch_id前8位>.json

设计原则（遵守 Agent-1 规范）：
  - 所有 ID 为随机 UUIDv4
  - 每条事实附 source_id + captured_at + page_content_sha256 + fragment_sha256
  - 私人手机号/微信不采集（仅采集官方工作邮箱，且只入公开层）
  - 不从招生目录推断「当前招生」「有名额」，catalog 只表述「出现在该年度目录」
  - 所有记录 publication_status=withheld，需审核才置 published

跨设备部署：本脚本不依赖任何数据库或外部服务，只读写本地 JSON。
另一台机器只需把 professors_info/ 与本脚本一起拷贝即可重新生成同样的批次（ID 用 UUID，
每次运行会重新生成；如需稳定 ID，在另一台机用 --import-batch 直接消费本机产出的 JSON）。
"""

import argparse
import hashlib
import json
import logging
import os
import re
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

logger = logging.getLogger("build_database")

# 项目根（Tsing-RADAR_Project/），位于 backend/ 上两级
_PROJECT_ROOT = _BACKEND.parent.parent

PROFESSORS_DIR = _PROJECT_ROOT / "professors_info"
SOURCES_META_PATH = PROFESSORS_DIR / "sources_meta.json"
CATALOG_PATH = PROFESSORS_DIR / "招生目录_完整.json"

OUT_DIR = _PROJECT_ROOT / "data_collection" / "batches"

# 私域检测正则：手机号、微信号
_PHONE_RE = re.compile(r"1[3-9]\d{9}")
_WECHAT_RE = re.compile(r"(微信|wechat|wx)[：:\s]*[a-zA-Z0-9_-]{5,}", re.IGNORECASE)


# ─────────────────────── 工具 ───────────────────────

def new_uuid() -> str:
    return str(uuid.uuid4())


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def is_official_email(email: str) -> bool:
    """只接收清华校内官方邮箱，避免私域或个人邮箱入公开层。"""
    if not email:
        return False
    e = email.strip().lower()
    return e.endswith("@tsinghua.edu.cn") or e.endswith("@mail.tsinghua.edu.cn")


def sanitize(raw: str) -> str:
    """去除明显私域信息（手机/微信）。命中即整段丢弃。"""
    if not raw:
        return ""
    if _PHONE_RE.search(raw) or _WECHAT_RE.search(raw):
        return ""
    return raw.strip()


def normalize_dept(name: str) -> str:
    """院系名归一化：去括号/前后缀/空格，便于跨数据源匹配。"""
    if not name:
        return ""
    s = name.strip()
    # 去「清华大学」前缀
    s = re.sub(r"^清华大学", "", s)
    # 去「深圳国际研究生院」等括号
    s = re.sub(r"[（）()]", "", s)
    return s.strip().lower()


def parse_dt(v: Any) -> str | None:
    if not v:
        return None
    if isinstance(v, str):
        return v
    if isinstance(v, datetime):
        return v.isoformat()
    return str(v)


# ─────────────────────── 构建器 ───────────────────────

class DatabaseBuilder:
    def __init__(self) -> None:
        self.entities: list[dict] = []
        self.entity_names: list[dict] = []
        self.relations: list[dict] = []
        self.directions: list[dict] = []
        self.entity_directions: list[dict] = []
        self.catalog_links: list[dict] = []
        self.opportunities: list[dict] = []
        self.claims: list[dict] = []
        self.sources: list[dict] = []

        # dept_name(规范化) → entity_id (organization)
        self._dept_org_id: dict[str, str] = {}
        # dept_name(规范化) → source_id (官方院系页 A 级来源)
        self._dept_source_id: dict[str, str] = {}
        # (name, normalized_dept) → entity_id (person)
        self._person_index: dict[tuple[str, str], str] = {}
        # direction key → direction_id（dedup）
        self._direction_index: dict[tuple[str, str, str], str] = {}

        self._sources_meta = self._load_sources_meta()

    def _load_sources_meta(self) -> dict:
        if SOURCES_META_PATH.exists():
            with open(SOURCES_META_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        logger.warning("sources_meta.json 不存在，快照/SHA-256 字段将为空")
        return {}

    # ── 来源 ──
    def _find_source_meta(self, *, dept_key: str | None = None, url: str | None = None) -> dict:
        """从 sources_meta 找匹配的快照信息。"""
        if dept_key and dept_key in self._sources_meta:
            return self._sources_meta[dept_key]
        if url:
            for v in self._sources_meta.values():
                if v.get("request_url") == url or v.get("final_url") == url:
                    return v
        return {}

    def _ensure_dept_source(self, dept_name: str, source_url: str) -> str:
        """为院系创建/复用 Source 记录，返回 source_id。"""
        norm = normalize_dept(dept_name)
        if norm in self._dept_source_id:
            return self._dept_source_id[norm]

        meta = self._find_source_meta(url=source_url)
        source_id = new_uuid()
        self.sources.append({
            "source_id": source_id,
            "source_class": "A",
            "source_type": "official_department_page",
            "source_title": f"清华大学{dept_name}师资队伍页",
            "public_url": source_url or meta.get("request_url"),
            "publisher": "清华大学",
            "published_at": None,
            "captured_at": meta.get("captured_at") or datetime.utcnow().isoformat(),
            "page_content_sha256": meta.get("page_content_sha256"),
            "snapshot_id": meta.get("snapshot_id"),
            "access_status": meta.get("access_status") or "ok",
            "visibility": "public",
        })
        self._dept_source_id[norm] = source_id
        return source_id

    def _ensure_catalog_source(self, snapshot_meta: dict) -> str:
        """为招生目录创建/复用 Source（A 级官方研招网）。"""
        url = snapshot_meta.get("request_url") or snapshot_meta.get("final_url")
        existing = next((s for s in self.sources if s["public_url"] == url), None)
        if existing:
            return existing["source_id"]
        source_id = new_uuid()
        self.sources.append({
            "source_id": source_id,
            "source_class": "A",
            "source_type": "official_admission_catalog",
            "source_title": "清华大学研究生招生目录",
            "public_url": url,
            "publisher": "清华大学",
            "published_at": None,
            "captured_at": snapshot_meta.get("captured_at") or datetime.utcnow().isoformat(),
            "page_content_sha256": snapshot_meta.get("page_content_sha256"),
            "snapshot_id": snapshot_meta.get("snapshot_id"),
            "access_status": snapshot_meta.get("access_status") or "ok",
            "visibility": "public",
        })
        return source_id

    def _ensure_dept_org(self, dept_name: str) -> str:
        norm = normalize_dept(dept_name)
        if norm in self._dept_org_id:
            return self._dept_org_id[norm]
        org_id = new_uuid()
        self.entities.append({
            "entity_id": org_id,
            "entity_type": "organization",
            "display_name": dept_name,
            "name_zh": dept_name,
            "name_en": None,
            "identity_status": "verified",
            "review_status": "pending_review",
            "publication_status": "withheld",
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat(),
        })
        self._dept_org_id[norm] = org_id
        return org_id

    def _ensure_direction(self, level_1: str, level_2: str, topic: str) -> str:
        key = (level_1, level_2 or "", topic)
        if key in self._direction_index:
            return self._direction_index[key]
        d_id = new_uuid()
        self.directions.append({
            "direction_id": d_id,
            "level_1": level_1,
            "level_2": level_2 or None,
            "specific_topic": topic,
            "application_context": None,
            "method_or_technology": None,
            "normalization_version": "v1",
        })
        self._direction_index[key] = d_id
        return d_id

    def _add_claim(
        self,
        *,
        subject_type: str,
        subject_id: str,
        field_name: str,
        normalized_value: str | None,
        raw_text: str,
        source_id: str,
        captured_at: str,
        page_content_sha256: str | None,
        snapshot_id: str | None,
        batch_id: str,
    ) -> str:
        claim_id = new_uuid()
        clean_raw = sanitize(raw_text)
        self.claims.append({
            "claim_id": claim_id,
            "evidence_id": new_uuid(),
            "subject_type": subject_type,
            "subject_id": subject_id,
            "field_name": field_name,
            "normalized_value": normalized_value,
            "raw_text": clean_raw[:500],  # ≤500 字
            "source_id": source_id,
            "captured_at": captured_at,
            "valid_from": None,
            "valid_until": None,
            "page_content_sha256": page_content_sha256,
            "fragment_sha256": sha256_text(clean_raw),
            "snapshot_id": snapshot_id,
            "capture_method": "crawler",
            "method_version": "v1",
            "normalization_version": "v1",
            "verification_status": "unverified",
            "conflict_status": "none",
            "confidence": None,
            "review_status": "pending_review",
            "publication_status": "withheld",
            "collector_role_id": "auto-builder",
            "batch_id": batch_id,
        })
        return claim_id

    # ── 主流程 ──
    def build_from_official(self, batch_id: str) -> None:
        """从 professors_info/official_*.json 构建导师实体与字段级证据。"""
        files = sorted(PROFESSORS_DIR.glob("official_*.json"))
        if not files:
            raise FileNotFoundError(f"未在 {PROFESSORS_DIR} 找到 official_*.json")

        for fp in files:
            dept_name = fp.stem.replace("official_", "")
            with open(fp, "r", encoding="utf-8") as f:
                people = json.load(f)
            if not people:
                continue

            # 用第一条的 source_url 作为该院系来源页（同一院系共享一个 source）
            source_url = people[0].get("source_url", "")
            source_id = self._ensure_dept_source(dept_name, source_url)
            meta = self._find_source_meta(url=source_url)
            page_sha = meta.get("page_content_sha256")
            snapshot_id = meta.get("snapshot_id")
            captured_at = meta.get("captured_at") or datetime.utcnow().isoformat()

            org_id = self._ensure_dept_org(dept_name)

            for p in people:
                name = sanitize(p.get("name", ""))
                if not name:
                    continue
                norm_dept = normalize_dept(dept_name)
                key = (name, norm_dept)
                if key in self._person_index:
                    entity_id = self._person_index[key]
                else:
                    entity_id = new_uuid()
                    self.entities.append({
                        "entity_id": entity_id,
                        "entity_type": "person",
                        "display_name": name,
                        "name_zh": name,
                        "name_en": None,
                        "identity_status": "pending_review",
                        "review_status": "pending_review",
                        "publication_status": "withheld",
                        "created_at": datetime.utcnow().isoformat(),
                        "updated_at": datetime.utcnow().isoformat(),
                    })
                    # 中文姓名别名
                    self.entity_names.append({
                        "name_id": new_uuid(),
                        "entity_id": entity_id,
                        "name_type": "official_zh",
                        "name_value": name,
                        "claim_id": None,
                        "is_primary": True,
                    })
                    # affiliated_with → 院系组织
                    rel_claim_id = self._add_claim(
                        subject_type="relation",
                        subject_id="",  # 先占位，relation 表创建后回填
                        field_name="affiliated_with",
                        normalized_value=dept_name,
                        raw_text=f"{name} 隶属 {dept_name}",
                        source_id=source_id,
                        captured_at=captured_at,
                        page_content_sha256=page_sha,
                        snapshot_id=snapshot_id,
                        batch_id=batch_id,
                    )
                    relation_id = new_uuid()
                    self.relations.append({
                        "relation_id": relation_id,
                        "subject_entity_id": entity_id,
                        "relation_type": "affiliated_with",
                        "object_entity_id": org_id,
                        "valid_from": None,
                        "valid_until": None,
                        "claim_id": rel_claim_id,
                        "relation_status": "active",
                    })
                    # 回填 claim.subject_id
                    for c in self.claims:
                        if c["claim_id"] == rel_claim_id:
                            c["subject_id"] = relation_id
                            break

                    self._person_index[key] = entity_id

                # ── 字段级证据（每个字段一个 claim） ──
                def _add(field: str, value: str | None, raw_template: str) -> None:
                    v = sanitize(value or "")
                    if not v:
                        return
                    self._add_claim(
                        subject_type="entity",
                        subject_id=entity_id,
                        field_name=field,
                        normalized_value=v,
                        raw_text=raw_template.format(name=name, value=v, dept=dept_name),
                        source_id=source_id,
                        captured_at=captured_at,
                        page_content_sha256=page_sha,
                        snapshot_id=snapshot_id,
                        batch_id=batch_id,
                    )

                _add("name_zh", p.get("name"), "{name}（姓名，{dept}）")
                _add("title", p.get("title"), "{name} {value}")
                _add("official_homepage", p.get("homepage"), "{name} 主页：{value}")
                _add("institute", p.get("institute"), "{name} 所属研究所：{value}")
                # 邮箱仅采集校内官方邮箱
                email = p.get("email", "")
                if is_official_email(email):
                    _add("public_work_email", email, "{name} 工作邮箱：{value}")
                # 研究所可衍生为研究方向（catalog_only 弱信号，暂不创建）

    def build_from_catalog(self, batch_id: str) -> None:
        """从招生目录构建 catalog_links（不推断当前招生）。"""
        if not CATALOG_PATH.exists():
            logger.warning("招生目录 %s 不存在，跳过", CATALOG_PATH)
            return

        with open(CATALOG_PATH, "r", encoding="utf-8") as f:
            catalog = json.load(f)

        # 一年一个目录源
        # 优先用 catalog_000（综合）的 meta；找不到则用任一
        catalog_meta = self._find_source_meta(dept_key="catalog_000")
        if not catalog_meta:
            # 取第一个 catalog_* 项作为目录源代表
            for k, v in self._sources_meta.items():
                if k.startswith("catalog_"):
                    catalog_meta = v
                    break
        source_id = self._ensure_catalog_source(catalog_meta)

        for entry in catalog:
            dept_name = entry.get("dept_name") or ""
            major_name = entry.get("major_name") or ""
            direction_text = entry.get("direction") or ""
            degree_type = entry.get("degree_type") or ""

            # 创建一条 catalog 专属 direction（catalog_only）
            d_id = self._ensure_direction(
                level_1=major_name or "未分类",
                level_2=degree_type,
                topic=direction_text or major_name,
            )

            # 部门组织实体（如果之前没出现过，也建一个）
            norm_dept = normalize_dept(dept_name)
            if norm_dept and norm_dept not in self._dept_org_id:
                self._ensure_dept_org(dept_name)
            dept_org_id = self._dept_org_id.get(norm_dept)

            for advisor_name in entry.get("advisors", []):
                name = sanitize(advisor_name)
                if not name:
                    continue
                # 尝试匹配已建实体
                resolved_entity_id = None
                status = "unresolved"
                if norm_dept:
                    ent = self._person_index.get((name, norm_dept))
                    if ent:
                        resolved_entity_id = ent
                        status = "verified"
                # 跨院系回退：仅按姓名匹配（同名歧义时降级 unresolved）
                if not resolved_entity_id:
                    candidates = [
                        (n, d) for (n, d) in self._person_index if n == name
                    ]
                    if len(candidates) == 1:
                        resolved_entity_id = self._person_index[candidates[0]]
                        status = "verified"

                self.catalog_links.append({
                    "catalog_link_id": new_uuid(),
                    "catalog_snapshot_id": catalog_meta.get("snapshot_id"),
                    "academic_year": "2027",
                    "catalog_type": "doctoral_regular" if "博士" in degree_type or "学术" in degree_type else "master",
                    "department_id": dept_org_id,
                    "program_id": None,
                    "direction_id": d_id,
                    "advisor_or_group_id": None,  # 目录标签实体，留空
                    "resolved_entity_id": resolved_entity_id,
                    "identity_resolution_status": status,
                    "relation_claim_id": None,
                })

    def build(self) -> dict:
        batch_id = new_uuid()
        self.build_from_official(batch_id)
        self.build_from_catalog(batch_id)

        return {
            "batch_id": batch_id,
            "generated_at": datetime.utcnow().isoformat(),
            "schema_version": "v1",
            "stats": {
                "entities": len(self.entities),
                "entity_names": len(self.entity_names),
                "relations": len(self.relations),
                "directions": len(self.directions),
                "entity_directions": len(self.entity_directions),
                "catalog_links": len(self.catalog_links),
                "opportunities": len(self.opportunities),
                "claims": len(self.claims),
                "sources": len(self.sources),
            },
            "sources": self.sources,
            "entities": self.entities,
            "entity_names": self.entity_names,
            "relations": self.relations,
            "directions": self.directions,
            "entity_directions": self.entity_directions,
            "catalog_links": self.catalog_links,
            "opportunities": self.opportunities,
            "claims": self.claims,
        }


def main() -> None:
    parser = argparse.ArgumentParser(description="构建导师数据库批次 JSON")
    parser.add_argument("--out-dir", default=str(OUT_DIR), help="输出目录")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.WARNING if args.quiet else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    builder = DatabaseBuilder()
    batch = builder.build()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    date_str = datetime.utcnow().strftime("%Y%m%d")
    fname = f"batch_crawl_{date_str}_{batch['batch_id'][:8]}.json"
    out_path = out_dir / fname

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(batch, f, ensure_ascii=False, indent=2)

    logger.info("✅ 已生成 %s", out_path)
    logger.info("统计：%s", json.dumps(batch["stats"], ensure_ascii=False))
    print(json.dumps({"path": str(out_path), "stats": batch["stats"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
