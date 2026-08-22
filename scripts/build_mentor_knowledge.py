"""v4.0.0 任务1 A-1：导师公开评价知识库构建（综述级确定性等价物）。

解析《清华导师评价综述_20260816.md》的 340 个导师章节，只提取综述级
聚合事实（评价统计 / 判档 / 四维结构化均分 / 综述摘要），**剔除全部
`> 代表性…` 原始引文块**，输出：

- backend/data/knowledge/mentors.knowledge.json   （知识本体，随仓库分发）
- backend/data/knowledge/knowledge_manifest.json  （溯源：来源文件 SHA256 + 口径声明）

治理红线（逐字）：
- 语料只入综述级、无原始引文、可溯源（SHA256 清单）；
- 回复带「匿名主观评价聚合，仅作参考」声明；
- 绝不混入雷达/匹配客观管线。

用法：
    python scripts/build_mentor_knowledge.py [--source 清华导师评价综述_20260816.md]
    python scripts/build_mentor_knowledge.py --rebuild-vectors
默认按「仓库上一级目录」（AIProject/，与综述源文件同目录）寻找源文件；
--rebuild-vectors 从既有知识本体构建向量索引（人工触发，月度重建），
需 GLM 凭据（GLM_API_KEY 或 LLM_API_KEY_FILE）——无 key / 嵌入失败 /
维度不一致均诚实退出，绝不产出半成品或无语义的 hash 兜底向量。
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SOURCE = REPO_ROOT.parent / "清华导师评价综述_20260816.md"
OUT_DIR = REPO_ROOT / "backend" / "data" / "knowledge"
KNOWLEDGE_OUT = OUT_DIR / "mentors.knowledge.json"
MANIFEST_OUT = OUT_DIR / "knowledge_manifest.json"
VECTORS_OUT = OUT_DIR / "mentors.knowledge.vectors.json"

_HEADER_RE = re.compile(r"^### (\d+)\.\s*(.+?)[|｜](\d+) 条评价\s*$")
_NAME_RE = re.compile(r"^(?P<name>[^（(]+)[（(](?P<inner>.*)[)）]$")

# 概况行：正面 X / 中性 Y / 负面 Z｜推荐率 R%｜情感均值 E｜tolerance **T**（方法）·判档 D·置信 C[｜来源：SRC （日期段）]
_GENERAL_RE = re.compile(
    r"正面 (\d+) / 中性 (\d+) / 负面 (\d+)｜"
    r"推荐率 (\d+)%｜"
    r"情感均值 ([\d.]+)｜"
    r"tolerance \*\*(\d+)\*\*（([^）]+)）·"
    r"判档 ([0-9C][^\s·｜]*)·"
    r"置信 ([^\s｜]+)｜"
    r"来源：(.+?)（([^）]+)）"
)
# 极少数章节无来源字段（如单条低置信评价）：拆解主体 + 可选来源
_GENERAL_CORE_RE = re.compile(
    r"正面 (\d+) / 中性 (\d+) / 负面 (\d+)｜"
    r"推荐率 (\d+)%｜"
    r"情感均值 ([\d.]+)｜"
    r"tolerance \*\*(\d+)\*\*（([^）]+)）·"
    r"判档 ([0-9C][^\s·｜]*)·"
    r"置信 ([^\s｜]+)"
)
# 四维评分行：学术 A｜经费 F｜师生关系 R｜学生前途 P（N 条带评分）；缺失维度用 — 占位
_FOUR_DIM_RE = re.compile(
    r"学术 ([\d.]+|—)｜经费 ([\d.]+|—)｜师生关系 ([\d.]+|—)｜学生前途 ([\d.]+|—)（(\d+) 条带评分）"
)

# 引文块行首（逐字剔除）
_QUOTE_PREFIXES = ("> 代表性", ">代表性")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _split_dept_title(inner: str) -> tuple[str | None, str | None]:
    """括号内 `院系 · 职称` → (院系, 职称)；无 `·` 时职称缺省。"""
    if "·" in inner:
        left, _, right = inner.rpartition("·")
        return left.strip(), right.strip()
    return inner.strip(), None


def _parse_general(line: str) -> dict:
    match = _GENERAL_RE.search(line) or _GENERAL_CORE_RE.search(line)
    if not match:
        raise ValueError(f"概况行无法解析：{line[:80]}")
    groups = match.groups()
    pos, neu, neg, rate, sentiment, tol, tol_method, band, conf = groups[:9]
    result = {
        "positive": int(pos),
        "neutral": int(neu),
        "negative": int(neg),
        "recommend_rate": int(rate),
        "sentiment_mean": float(sentiment),
        "tolerance": int(tol),
        "tolerance_method": tol_method.strip(),
        "band": band.strip(),
        "confidence": conf.strip(),
        "sources": "",
        "date_range": "",
    }
    if len(groups) >= 11:
        result["sources"] = groups[9].strip()
        result["date_range"] = groups[10].strip()
    return result


def _parse_authority(line: str, dept_header: str) -> dict:
    """权威行：在库（院系·职称｜2027 招生｜官方主页）或库外（字段缺省）。"""
    body = line.split("：", 1)[1].strip()
    if body.startswith("不在当前导师库"):
        return {
            "in_current_db": False,
            "authority": None,
            "recruitment_2027": [],
            "homepage": None,
        }
    segments = body.split("｜")
    authority = segments[0].strip()
    recruitment: list[str] = []
    homepage: str | None = None
    for segment in segments[1:]:
        if segment.startswith("2027 招生："):
            recruitment = [
                item.strip()
                for item in segment.split("：", 1)[1].split("、")
                if item.strip()
            ]
        elif segment.startswith("官方主页："):
            homepage = segment.split("：", 1)[1].strip() or None
    if not authority:
        authority = dept_header or None
    return {
        "in_current_db": True,
        "authority": authority,
        "recruitment_2027": recruitment,
        "homepage": homepage,
    }


def _parse_four_dim(line: str) -> dict | None:
    match = _FOUR_DIM_RE.search(line)
    if not match:
        return None
    academic, funding, relationship, prospects, sample = match.groups()

    def _num(value: str) -> float | None:
        return float(value) if value != "—" else None

    return {
        "academic": _num(academic),
        "funding": _num(funding),
        "relationship": _num(relationship),
        "prospects": _num(prospects),
        "sample": int(sample),
    }


def parse_sections(lines: list[str]) -> tuple[list[dict], int]:
    mentors: list[dict] = []
    quote_blocks = 0
    current: dict | None = None
    section_lines: list[str] = []

    def flush() -> None:
        nonlocal section_lines, quote_blocks
        if current is None:
            return
        current["summary"] = ""
        for raw in section_lines:
            stripped = raw.strip()
            if not stripped:
                continue
            if stripped.startswith(_QUOTE_PREFIXES):
                quote_blocks += 1
                continue
            if stripped.startswith("**综述**"):
                current["summary"] = stripped.split("：", 1)[1].strip()
            elif stripped.startswith("**四维评分"):
                four = _parse_four_dim(stripped)
                if four is not None:
                    current["four_dim"] = four
        if not current["summary"]:
            raise ValueError(f"章节缺失综述行：{current.get('name')}")
        # 综述级校验：summary/stats 不得残留引文引号
        if '"' in current["summary"] or "”" in current["summary"] or "“" in current["summary"]:
            raise ValueError(f"综述行疑似残留引文：{current.get('name')}")
        mentors.append(current)
        section_lines = []

    for line in lines:
        header = _HEADER_RE.match(line)
        if header:
            flush()
            raw_name = header.group(2).strip()
            name_match = _NAME_RE.match(raw_name)
            if not name_match:
                raise ValueError(f"章节头无法解析：{raw_name}")
            name = name_match.group("name").strip()
            dept_header, title_header = _split_dept_title(name_match.group("inner"))
            current = {
                "name": name,
                "department_header": dept_header,
                "title_header": title_header,
                "in_current_db": True,
                "authority": None,
                "recruitment_2027": [],
                "homepage": None,
                "review_count": int(header.group(3)),
                "stats": {},
                "four_dim": None,
                "summary": "",
            }
            section_lines = []
            continue
        if current is not None:
            stripped = line.strip()
            if stripped.startswith("**概况**"):
                current["stats"] = _parse_general(stripped)
            elif stripped.startswith("**权威**"):
                current.update(_parse_authority(stripped, current["department_header"]))
            section_lines.append(line)
    flush()
    return mentors, quote_blocks


def build(source: Path) -> None:
    if not source.exists():
        sys.exit(f"源文件不存在：{source}")
    lines = source.read_text(encoding="utf-8").splitlines()
    mentors, quote_blocks = parse_sections(lines)
    if len(mentors) != 340:
        sys.exit(f"章节数异常：期望 340，实际 {len(mentors)}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    knowledge = {
        "schema_version": "1.0",
        "notice": (
            "综述级聚合：仅存评价统计、判档、四维结构化均分与综述摘要；"
            "不含任何原始引文（代表性引文块已全部剔除）。"
            "匿名主观评价聚合仅作参考，不构成对导师能力的客观评判，"
            "不混入雷达/匹配客观管线。"
        ),
        "mentors": mentors,
    }
    KNOWLEDGE_OUT.write_text(
        json.dumps(knowledge, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    manifest = {
        "artifact": KNOWLEDGE_OUT.name,
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "build_script": "scripts/build_mentor_knowledge.py",
        "source_file": source.name,
        "source_sha256": _sha256(source),
        "source_mentor_count": len(mentors),
        "quote_blocks_removed": quote_blocks,
        "scope_notice": knowledge["notice"],
    }
    MANIFEST_OUT.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    in_db = sum(1 for m in mentors if m["in_current_db"])
    with_four = sum(1 for m in mentors if m["four_dim"])
    print(
        f"OK：{len(mentors)} 位导师（在库 {in_db} / 库外 {len(mentors) - in_db}），"
        f"剔除引文块 {quote_blocks} 个，四维 {with_four} 位"
    )
    print(f"   → {KNOWLEDGE_OUT.relative_to(REPO_ROOT)}")
    print(f"   → {MANIFEST_OUT.relative_to(REPO_ROOT)}")


def _block_text(mentor: dict) -> str:
    """导师块的嵌入文本单元（确定性）：姓名（院系）：综述摘要。"""
    name = str(mentor.get("name") or "").strip()
    dept = str(mentor.get("department_header") or "").strip()
    summary = str(mentor.get("summary") or "").strip()
    return f"{name}（{dept}）：{summary}"


def build_vectors() -> None:
    """从既有知识本体构建向量索引（--rebuild-vectors，人工触发）。

    诚实退出条件（均不写任何文件）：无 GLM 凭据 / 知识本体缺失 /
    manifest 缺失 / 任一导师嵌入失败 / 嵌入维度不一致。
    """
    if str(REPO_ROOT / "backend") not in sys.path:
        sys.path.insert(0, str(REPO_ROOT / "backend"))
    from app.core.config import settings
    from app.services.llm import embed_text_strict

    if not any(
        provider == "glm" for provider, _ in settings.llm_credentials
    ):
        sys.exit(
            "未配置 GLM 凭据（GLM_API_KEY / LLM_API_KEY_FILE）：向量索引"
            "需要真实 embedding，拒绝生成无语义的 hash 兜底向量。"
        )
    if not KNOWLEDGE_OUT.exists():
        sys.exit(f"知识本体不存在，先运行基础构建：{KNOWLEDGE_OUT}")
    if not MANIFEST_OUT.exists():
        sys.exit(f"manifest 不存在，先运行基础构建：{MANIFEST_OUT}")

    payload = json.loads(KNOWLEDGE_OUT.read_text(encoding="utf-8"))
    mentors = payload.get("mentors") or []
    # 与服务端 _read_index 同一去重口径：首个同名优先（块 id 对齐词法索引）
    blocks: dict[str, str] = {}
    for mentor in mentors:
        name = str(mentor.get("name") or "").strip()
        if name and name not in blocks:
            blocks[name] = _block_text(mentor)
    if not blocks:
        sys.exit("知识本体为空，无可嵌入块")

    async def _embed_all() -> dict[str, list[float] | None]:
        results: dict[str, list[float] | None] = {}
        for name, text in blocks.items():
            results[name] = await embed_text_strict(text)
        return results

    print(f"嵌入 {len(blocks)} 个导师块（{settings.GLM_EMBED_MODEL}）…")
    embedded = asyncio.run(_embed_all())

    dim: int | None = None
    vectors: dict[str, list[float]] = {}
    for name, vector in embedded.items():
        if not vector:
            sys.exit(f"嵌入失败（{name}）：诚实退出，不写半成品索引")
        if dim is None:
            dim = len(vector)
        elif len(vector) != dim:
            sys.exit(
                f"嵌入维度不一致（{name}：{len(vector)} != {dim}）：诚实退出"
            )
        vectors[name] = vector

    vectors_payload = {
        "schema_version": "1.0",
        "notice": (
            "向量索引仅用于词法未命中后的语义补充召回（阈值门控）；"
            "只作咨询参考，绝不混入雷达/匹配客观管线。"
        ),
        "model": settings.GLM_EMBED_MODEL,
        "dim": dim,
        "count": len(vectors),
        "knowledge_sha256": _sha256(KNOWLEDGE_OUT),
        "generated_at": datetime.now(timezone.utc).isoformat(
            timespec="seconds"
        ),
        "vectors": vectors,
    }
    VECTORS_OUT.write_text(
        json.dumps(vectors_payload, ensure_ascii=False), encoding="utf-8"
    )

    manifest = json.loads(MANIFEST_OUT.read_text(encoding="utf-8"))
    manifest.update(
        {
            "vectors_artifact": VECTORS_OUT.name,
            "vectors_sha256": _sha256(VECTORS_OUT),
            "vectors_model": settings.GLM_EMBED_MODEL,
            "vectors_dim": dim,
            "vectors_count": len(vectors),
            "vectors_knowledge_sha256": _sha256(KNOWLEDGE_OUT),
        }
    )
    MANIFEST_OUT.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        f"OK：向量索引 {len(vectors)} 块 × {dim} 维"
        f"（model={settings.GLM_EMBED_MODEL}）"
    )
    print(f"   → {VECTORS_OUT.relative_to(REPO_ROOT)}")
    print(f"   → manifest 已增补 vectors_sha256")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source", default=str(DEFAULT_SOURCE), help="综述源文件路径"
    )
    parser.add_argument(
        "--rebuild-vectors",
        action="store_true",
        help="从既有知识本体构建向量索引（需 GLM 凭据）",
    )
    args = parser.parse_args()
    if args.rebuild_vectors:
        build_vectors()
    else:
        build(Path(args.source))


if __name__ == "__main__":
    main()
