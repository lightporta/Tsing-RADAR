"""多源爬取框架：为每位导师采集实时项目 + 学术成果（A/B/C 级来源）。

数据来源分级（按规范第六节）：
  - A 级：导师官方主页、实验室官网、研招网、ORCID（公开事实主要来源）
  - B 级：DOI、CrossRef、OpenAlex、政府公示（成果、合作核验）
  - C 级：媒体报道、新闻公示（项目活动信号，需更多核验）
  - D 级：学生反馈、评价网 —— **本脚本仅入库到 private_feedback_raw**，
          永不进入公开层（entities/claims），永不进入 GitHub

执行策略：
  1. 从 entities 表读已发布的 person 实体（带 official_homepage claim）
  2. 对每位导师并发调用 fetcher 抓取多源信息
  3. 每条信息生成 Claim + Source，按来源等级分类
  4. 学生评价单独走 private 层，仅聚合成 PrivateSignal（≥3 份样本）

CLI：
  # 全量（运行时长 ∝ 导师数 × 源数，建议在另一台机器跑）
  python -m scripts.crawl_live --target all

  # 样本验证（建议先用这个跑 10-20 人验证 pipeline）
  python -m scripts.crawl_live --limit 10 --departments 电子工程系

  # 只补充项目（不重抓主页）
  python -m scripts.crawl_live --source-types project,publication

注意：
  - 默认 polite_delay=2s，每个请求间停顿，避免被反爬
  - 失败重试 3 次，仍失败则记 issue 不中断
  - 所有抓取结果默认 publication_status=withheld，需审核才发布
  - 采集的学生反馈 consent_id 必须留空（除非走受控授权流程）
"""

import argparse
import asyncio
import hashlib
import json
import logging
import re
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
_PROJECT_ROOT = _BACKEND.parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

try:
    import httpx
except ImportError:  # pragma: no cover
    httpx = None  # type: ignore

logger = logging.getLogger("crawl_live")

OUT_DIR = _PROJECT_ROOT / "data_collection" / "batches"
OUT_DIR.mkdir(parents=True, exist_ok=True)

PHONE_RE = re.compile(r"1[3-9]\d{9}")
WECHAT_RE = re.compile(r"(微信|wechat|wx)[：:\s]*[a-zA-Z0-9_-]{5,}", re.IGNORECASE)

# 各来源的等级与默认抓取配置
SOURCE_SPECS = {
    "official_homepage": {
        "source_class": "A",
        "source_type": "official_personal_homepage",
        "description": "导师官方主页（研究方向、项目、论文列表）",
    },
    "lab_page": {
        "source_class": "A",
        "source_type": "official_lab_page",
        "description": "实验室官网",
    },
    "orcid": {
        "source_class": "A",
        "source_type": "orcid_public",
        "description": "ORCID 公开履历",
    },
    "openalex": {
        "source_class": "B",
        "source_type": "openalex_works",
        "description": "OpenAlex 论文（出版信号）",
    },
    "crossref": {
        "source_class": "B",
        "source_type": "crossref_works",
        "description": "CrossRef DOI（出版信号）",
    },
    "nsfc": {
        "source_class": "B",
        "source_type": "nsfc_project",
        "description": "NSFC 项目公示",
    },
    "news_media": {
        "source_class": "C",
        "source_type": "news_media_report",
        "description": "媒体报道、新闻公示（项目活动信号）",
    },
    "student_review": {
        "source_class": "D",
        "source_type": "private_student_review",
        "description": "学生评价（**仅入库 private_feedback_raw，永不公开**）",
    },
}


def new_uuid() -> str:
    return str(uuid.uuid4())


def sha256_text(t: str) -> str:
    return hashlib.sha256(t.encode("utf-8")).hexdigest()


def sanitize(text: str) -> str:
    """去除私域信息（手机/微信）。命中即整段丢弃，宁缺毋滥。"""
    if not text:
        return ""
    if PHONE_RE.search(text) or WECHAT_RE.search(text):
        return ""
    return text.strip()


def is_tsinghua_official(url: str) -> bool:
    """官方主页只接受 tsinghua.edu.cn 域，避免误爬第三方页面。"""
    if not url:
        return False
    try:
        host = urlparse(url).netloc.lower()
        return "tsinghua.edu.cn" in host
    except Exception:
        return False


# ─────────────────────── 抓取器 ───────────────────────

async def fetch_page(client, url: str, *, retries: int = 3) -> Optional[str]:
    """抓取单个 URL，返回 HTML 文本。失败返回 None。"""
    if httpx is None:
        logger.warning("httpx 未安装，跳过实际抓取")
        return None
    last_err: Optional[Exception] = None
    for attempt in range(retries):
        try:
            r = await client.get(url, follow_redirects=True)
            if r.status_code == 200:
                return r.text
            logger.warning("HTTP %s: %s", r.status_code, url)
        except Exception as e:  # noqa: BLE001
            last_err = e
            await asyncio.sleep(2 ** attempt)
    logger.warning("抓取失败 %s: %s", url, last_err)
    return None


def parse_homepage(html: str, base_url: str) -> dict:
    """从导师主页 HTML 提取研究方向、论文标题、项目信息。

    通用启发式抽取（不同院系页面结构差异大，这里只做粗抽取，
    精确字段需要后续接 LLM 解析，本框架只做 pipeline 证明）。
    """
    import re as _re
    text = _re.sub(r"<script[^>]*>.*?</script>", "", html, flags=_re.S | _re.I)
    text = _re.sub(r"<style[^>]*>.*?</style>", "", text, flags=_re.S | _re.I)
    plain = _re.sub(r"<[^>]+>", " ", text)
    plain = _re.sub(r"\s+", " ", plain).strip()

    # 简单启发式：找「研究方向」「论文」「项目」段后的内容
    def _section_after(keyword: str, max_len: int = 500) -> str:
        m = _re.search(rf"{keyword}[^<>]{{0,5}}[:：]?(.{{0,{max_len}}})", plain)
        return m.group(1).strip() if m else ""

    return {
        "research_summary": sanitize(_section_after("研究方向")),
        "recent_papers_raw": sanitize(_section_after("代表性论文", 1000)),
        "projects_raw": sanitize(_section_after("科研项目", 1000)),
        "page_text_excerpt": sanitize(plain[:2000]),
    }


async def fetch_openalex_works(client, query: str, *, limit: int = 10) -> list[dict]:
    """从 OpenAlex 查询论文（B 级，免费 API）。"""
    if httpx is None:
        return []
    try:
        r = await client.get(
            "https://api.openalex.org/works",
            params={"search": query, "per-page": limit},
            timeout=15,
        )
        if r.status_code != 200:
            return []
        data = r.json()
        return [
            {
                "title": w.get("title"),
                "doi": w.get("doi"),
                "year": (w.get("publication_year")),
                "cited_by_count": w.get("cited_by_count", 0),
            }
            for w in data.get("results", [])
            if w.get("title")
        ]
    except Exception as e:  # noqa: BLE001
        logger.warning("OpenAlex 失败：%s", e)
        return []


# ─────────────────────── 数据库读取 ───────────────────────

def load_target_entities(
    *,
    limit: Optional[int],
    departments: Optional[list[str]],
    only_published: bool,
) -> list[dict]:
    """从 entities 表加载待抓取的导师实体（带 official_homepage）。"""
    from sqlalchemy import select
    from app.db.session import SessionLocal
    from app.models.entity import Entity, Relation
    from app.models.claim import Claim

    db = SessionLocal()
    try:
        stmt = select(Entity).where(Entity.entity_type == "person")
        if only_published:
            stmt = stmt.where(Entity.publication_status == "published")
        entities = list(db.scalars(stmt))
        result = []
        for e in entities:
            # 院系
            dept_stmt = (
                select(Entity)
                .join(Relation, Relation.object_entity_id == Entity.entity_id)
                .where(Relation.subject_entity_id == e.entity_id)
                .where(Relation.relation_type == "affiliated_with")
                .limit(1)
            )
            dept = db.scalars(dept_stmt).first()
            dept_name = dept.display_name if dept else None
            # 过滤院系
            if departments and dept_name not in departments:
                continue
            # 官方主页
            hp_stmt = (
                select(Claim)
                .where(Claim.subject_type == "entity")
                .where(Claim.subject_id == e.entity_id)
                .where(Claim.field_name == "official_homepage")
                .order_by(Claim.captured_at.desc())
                .limit(1)
            )
            hp = db.scalars(hp_stmt).first()
            result.append({
                "entity_id": e.entity_id,
                "name": e.display_name,
                "department": dept_name,
                "homepage": hp.normalized_value if hp else None,
            })
            if limit and len(result) >= limit:
                break
        return result
    finally:
        db.close()


# ─────────────────────── 主流程 ───────────────────────

async def crawl_one(
    client,
    person: dict,
    *,
    source_types: list[str],
    polite_delay: float,
    batch_id: str,
) -> dict:
    """抓取一位导师的多源信息，返回符合规范的批次片段。"""
    name = person["name"]
    dept = person.get("department") or ""
    homepage = person.get("homepage") or ""
    entity_id = person["entity_id"]

    fragment: dict[str, list] = {
        "sources": [],
        "claims": [],
        "directions": [],         # 三层方向（current_official / publication_signal_only）
        "entity_directions": [],
        "private_feedback_raw": [],  # 私域，单独收集
        "issues": [],
    }

    captured_at = datetime.utcnow().isoformat()

    # ── A 级：官方主页 ──
    if "official_homepage" in source_types and homepage:
        await asyncio.sleep(polite_delay)
        if is_tsinghua_official(homepage):
            html = await fetch_page(client, homepage)
            if html:
                page_sha = sha256_text(html)
                source_id = new_uuid()
                fragment["sources"].append({
                    "source_id": source_id,
                    "source_class": "A",
                    "source_type": "official_personal_homepage",
                    "source_title": f"{name} 官方主页",
                    "public_url": homepage,
                    "publisher": "清华大学",
                    "captured_at": captured_at,
                    "page_content_sha256": page_sha,
                    "snapshot_id": new_uuid(),
                    "access_status": "ok",
                    "visibility": "public",
                })
                parsed = parse_homepage(html, homepage)
                # 研究方向 → current_official scope
                if parsed["research_summary"]:
                    raw = parsed["research_summary"][:500]
                    fragment["claims"].append({
                        "claim_id": new_uuid(),
                        "evidence_id": new_uuid(),
                        "subject_type": "entity",
                        "subject_id": entity_id,
                        "field_name": "research_directions_text",
                        "normalized_value": None,
                        "raw_text": raw,
                        "source_id": source_id,
                        "captured_at": captured_at,
                        "page_content_sha256": page_sha,
                        "fragment_sha256": sha256_text(raw),
                        "snapshot_id": source_id,
                        "capture_method": "crawler",
                        "method_version": "v1",
                        "publication_status": "withheld",
                        "review_status": "pending_review",
                        "batch_id": batch_id,
                    })
                # 论文/项目摘要（publication_signal_only）
                for field, txt in [
                    ("recent_papers_text", parsed["recent_papers_raw"]),
                    ("recent_projects_text", parsed["projects_raw"]),
                ]:
                    if txt:
                        raw = txt[:500]
                        fragment["claims"].append({
                            "claim_id": new_uuid(),
                            "evidence_id": new_uuid(),
                            "subject_type": "entity",
                            "subject_id": entity_id,
                            "field_name": field,
                            "raw_text": raw,
                            "source_id": source_id,
                            "captured_at": captured_at,
                            "page_content_sha256": page_sha,
                            "fragment_sha256": sha256_text(raw),
                            "snapshot_id": source_id,
                            "capture_method": "crawler",
                            "publication_status": "withheld",
                            "review_status": "pending_review",
                            "batch_id": batch_id,
                        })
            else:
                fragment["issues"].append({
                    "issue_type": "source_unavailable",
                    "entity_id": entity_id,
                    "url": homepage,
                })
        else:
            fragment["issues"].append({
                "issue_type": "non_official_homepage",
                "entity_id": entity_id,
                "url": homepage,
            })

    # ── B 级：OpenAlex 论文 ──
    if "openalex" in source_types:
        await asyncio.sleep(polite_delay)
        works = await fetch_openalex_works(client, f"Tsinghua {name}")
        if works:
            source_id = new_uuid()
            fragment["sources"].append({
                "source_id": source_id,
                "source_class": "B",
                "source_type": "openalex_works",
                "source_title": f"{name} 在 OpenAlex 的论文",
                "public_url": "https://api.openalex.org/works",
                "publisher": "OpenAlex",
                "captured_at": captured_at,
                "visibility": "public",
                "access_status": "ok",
            })
            for w in works:
                title = (w.get("title") or "").strip()
                if not title:
                    continue
                raw = f"{title} ({w.get('year','')}) cited={w.get('cited_by_count',0)}"
                raw = sanitize(raw)
                if not raw:
                    continue
                fragment["claims"].append({
                    "claim_id": new_uuid(),
                    "evidence_id": new_uuid(),
                    "subject_type": "entity",
                    "subject_id": entity_id,
                    "field_name": "publication_signal",
                    "normalized_value": title,
                    "raw_text": raw[:500],
                    "source_id": source_id,
                    "captured_at": captured_at,
                    "fragment_sha256": sha256_text(raw),
                    "capture_method": "crawler",
                    "publication_status": "withheld",
                    "review_status": "pending_review",
                    "batch_id": batch_id,
                })

    # ── D 级：学生评价（不爬，仅占位，强调私域隔离）──
    if "student_review" in source_types:
        # ⚠️ 学生评价采集需走受控授权流程（consent_id + 问卷），不在自动爬虫范围。
        # 这里仅记录「未采集」状态，由独立、带授权的流程写入 private_feedback_raw。
        fragment["issues"].append({
            "issue_type": "student_review_skipped",
            "reason": "学生评价属 D 级私域数据，需走受控授权问卷流程，不参与自动爬取。",
            "entity_id": entity_id,
        })

    return fragment


async def crawl_all(
    targets: list[dict],
    *,
    source_types: list[str],
    polite_delay: float,
    concurrency: int,
) -> dict:
    """并发抓取所有目标导师。"""
    batch_id = new_uuid()
    sem = asyncio.Semaphore(concurrency)
    all_sources: list[dict] = []
    all_claims: list[dict] = []
    all_issues: list[dict] = []

    limits = httpx.Limits(max_connections=concurrency) if httpx else None
    headers = {"User-Agent": "Tsing-RADAR-Research-Bot/1.0 (academic research)"}
    timeout = httpx.Timeout(30) if httpx else None

    async with (httpx.AsyncClient(limits=limits, headers=headers, timeout=timeout) if httpx else _NullCtx()) as client:
        async def _one(p):
            async with sem:
                frag = await crawl_one(
                    client, p,
                    source_types=source_types,
                    polite_delay=polite_delay,
                    batch_id=batch_id,
                )
                all_sources.extend(frag["sources"])
                all_claims.extend(frag["claims"])
                all_issues.extend(frag["issues"])
                return len(frag["claims"])

        results = await asyncio.gather(*[_one(p) for p in targets], return_exceptions=True)
        ok = sum(1 for r in results if not isinstance(r, Exception))

    return {
        "batch_id": batch_id,
        "generated_at": datetime.utcnow().isoformat(),
        "schema_version": "live-crawl-v1",
        "source_types": source_types,
        "stats": {
            "targets": len(targets),
            "succeeded": ok,
            "sources": len(all_sources),
            "claims": len(all_claims),
            "issues": len(all_issues),
        },
        "sources": all_sources,
        "entities": [],  # 实体已在主库，不重建
        "claims": all_claims,
        "issues": all_issues,
    }


class _NullCtx:
    """httpx 未安装时的占位 async context manager。"""
    async def __aenter__(self):
        return None
    async def __aexit__(self, *exc):
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description="多源爬取导师实时信息（项目/论文/评价）")
    parser.add_argument("--limit", type=int, default=None, help="限制抓取导师数（建议先用 10 试跑）")
    parser.add_argument("--departments", default=None, help="逗号分隔院系过滤")
    parser.add_argument("--source-types", default="official_homepage,openalex",
                        help="逗号分隔，可选：" + ",".join(SOURCE_SPECS.keys()))
    parser.add_argument("--include-withheld", action="store_true",
                        help="同时抓 withheld 实体（默认只抓 published）")
    parser.add_argument("--polite-delay", type=float, default=2.0,
                        help="每个请求间停顿秒数（避免反爬）")
    parser.add_argument("--concurrency", type=int, default=3, help="并发数")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    source_types = [s.strip() for s in args.source_types.split(",") if s.strip()]
    invalid = [s for s in source_types if s not in SOURCE_SPECS]
    if invalid:
        parser.error(f"未知 source-types: {invalid}，可选: {list(SOURCE_SPECS.keys())}")

    departments = (
        [d.strip() for d in args.departments.split(",") if d.strip()]
        if args.departments else None
    )

    targets = load_target_entities(
        limit=args.limit,
        departments=departments,
        only_published=not args.include_withheld,
    )
    if not targets:
        logger.warning("无目标导师，退出")
        return
    logger.info("目标导师：%d 位，来源类型：%s", len(targets), source_types)

    batch = asyncio.run(crawl_all(
        targets,
        source_types=source_types,
        polite_delay=args.polite_delay,
        concurrency=args.concurrency,
    ))

    out_path = OUT_DIR / f"batch_crawl_live_{datetime.utcnow().strftime('%Y%m%d')}_{batch['batch_id'][:8]}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(batch, f, ensure_ascii=False, indent=2)

    logger.info("✅ 已生成 %s", out_path)
    print(json.dumps({"path": str(out_path), "stats": batch["stats"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
