"""D1 清华 2027 博士招生目录的限速缓存、离线解析和审计。

目录中的 offering 只表示官方页面列出的方向—导师/导师组关系，不表示名额或招生承诺。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable
from zoneinfo import ZoneInfo

from lxml import html

from app.schemas.catalog import (
    ALLOWED_SOURCE_HOSTS,
    AdmissionRemark,
    AdvisorEntityType,
    AdvisorOrGroup,
    CatalogCoverage,
    CatalogDataset,
    CatalogFieldEvidence,
    CatalogSnapshot,
    CatalogType,
    Department,
    Offering,
    Program,
    RemarkScope,
    ResearchDirection,
)


OFFICIAL_ENTRY_URL = "https://yz.tsinghua.edu.cn/zsxx/bszs/jzml.htm"
MAX_PAGE_BYTES = 5 * 1024 * 1024
DEFAULT_MIN_INTERVAL_SECONDS = 1.0
USER_AGENT = "Tsing-RADAR-D1/1.0 local official catalog audit"
SHANGHAI = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True)
class CatalogSpec:
    catalog_type: CatalogType
    snapshot_id: str
    expected_path: str


CATALOG_SPECS = (
    CatalogSpec(
        catalog_type=CatalogType.DOCTORAL_REGULAR,
        snapshot_id="ab3ae191-f6b5-4a83-bd4d-02a279904861",
        expected_path=(
            "/publish/s03/s0303/detail/"
            "ab3ae191-f6b5-4a83-bd4d-02a279904861"
        ),
    ),
    CatalogSpec(
        catalog_type=CatalogType.DOCTORAL_RECOMMENDATION_EXEMPT,
        snapshot_id="2ede1fca-d9a0-407a-9d68-3475494848b7",
        expected_path=(
            "/publish/s01/s0103/detail/"
            "2ede1fca-d9a0-407a-9d68-3475494848b7/2"
        ),
    ),
)


class CatalogIngestionError(RuntimeError):
    pass


class CatalogFetchError(CatalogIngestionError):
    pass


class CatalogParseError(CatalogIngestionError):
    pass


class CatalogAuditError(CatalogIngestionError):
    pass


@dataclass(frozen=True)
class FetchResponse:
    status: int
    final_url: str
    headers: dict[str, str]
    body: bytes = b""


@dataclass(frozen=True)
class CachedPage:
    request_url: str
    final_url: str
    captured_at: datetime
    last_checked_at: datetime
    content_sha256: str
    content_type: str
    body: bytes

    @property
    def text(self) -> str:
        try:
            return self.body.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise CatalogParseError(
                f"官方页面不是有效 UTF-8: {self.final_url}"
            ) from exc


@dataclass(frozen=True)
class ResolvedCatalog:
    spec: CatalogSpec
    title: str
    catalog_url: str
    raw_link_text: str


@dataclass(frozen=True)
class DiscoveredDepartment:
    code: str
    name: str
    page_url: str
    raw_link_text: str


@dataclass
class ParsedDepartmentBundle:
    department: Department
    programs: list[Program]
    research_directions: list[ResearchDirection]
    advisors_or_groups: list[AdvisorOrGroup]
    offerings: list[Offering]
    remarks: list[AdmissionRemark]


class _TransientFetchError(CatalogFetchError):
    pass


def _now() -> datetime:
    return datetime.now(SHANGHAI)


def _normalize_text(value: str) -> str:
    return " ".join(value.replace("\xa0", " ").split())


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_text(value: str) -> str:
    return _sha256_bytes(value.encode("utf-8"))


def _json_default(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="python")
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "value"):
        return str(value.value)
    raise TypeError(f"不可序列化类型: {type(value)!r}")


def _canonical_json(value: Any) -> str:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="python")
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=_json_default,
    )


def _content_hash(payload: dict[str, Any]) -> str:
    clean = {key: value for key, value in payload.items() if key != "content_sha256"}
    return _sha256_text(_canonical_json(clean))


def _entity_id(kind: str, *parts: str) -> str:
    digest = _sha256_text(
        _canonical_json({"kind": kind, "parts": list(parts)})
    )[:24]
    return f"{kind}_{digest}"


def _official_url(value: str) -> str:
    parsed = urllib.parse.urlsplit(value)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in ALLOWED_SOURCE_HOSTS
        or parsed.username
        or parsed.password
    ):
        raise CatalogFetchError(f"拒绝非官方 URL: {value}")
    return urllib.parse.urlunsplit(parsed._replace(fragment=""))


def _atomic_write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_bytes(payload)
    os.replace(temporary, path)


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    serialized = (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")
    _atomic_write_bytes(path, serialized)


class RateLimiter:
    def __init__(self, min_interval_seconds: float) -> None:
        if min_interval_seconds < DEFAULT_MIN_INTERVAL_SECONDS:
            raise ValueError(
                f"D1 请求间隔不得小于 {DEFAULT_MIN_INTERVAL_SECONDS} 秒"
            )
        self.min_interval_seconds = min_interval_seconds
        self._last_request_at: float | None = None

    def wait(self) -> None:
        if self._last_request_at is not None:
            remaining = (
                self.min_interval_seconds
                - (time.monotonic() - self._last_request_at)
            )
            if remaining > 0:
                time.sleep(remaining)
        self._last_request_at = time.monotonic()


class _OfficialRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _official_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _network_fetch(url: str, headers: dict[str, str]) -> FetchResponse:
    request = urllib.request.Request(url, headers=headers, method="GET")
    opener = urllib.request.build_opener(_OfficialRedirectHandler())
    try:
        with opener.open(request, timeout=30) as response:
            final_url = _official_url(response.geturl())
            body = response.read(MAX_PAGE_BYTES + 1)
            if len(body) > MAX_PAGE_BYTES:
                raise CatalogFetchError(f"官方页面超过 5 MiB: {url}")
            return FetchResponse(
                status=int(response.status),
                final_url=final_url,
                headers={key.lower(): value for key, value in response.headers.items()},
                body=body,
            )
    except urllib.error.HTTPError as exc:
        if exc.code == 304:
            return FetchResponse(
                status=304,
                final_url=_official_url(exc.geturl()),
                headers={key.lower(): value for key, value in exc.headers.items()},
            )
        if exc.code == 429 or 500 <= exc.code <= 599:
            raise _TransientFetchError(
                f"官方页面临时错误 HTTP {exc.code}: {url}"
            ) from exc
        raise CatalogFetchError(f"官方页面 HTTP {exc.code}: {url}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise _TransientFetchError(f"官方页面网络错误: {url}: {exc}") from exc


class CatalogCache:
    """缓存公开 HTML；离线读取时严格验证元数据和内容哈希。"""

    def __init__(
        self,
        root: Path,
        *,
        min_interval_seconds: float = DEFAULT_MIN_INTERVAL_SECONDS,
        transport: Callable[[str, dict[str, str]], FetchResponse] | None = None,
    ) -> None:
        self.root = root
        self.rate_limiter = RateLimiter(min_interval_seconds)
        self.transport = transport or _network_fetch

    def _paths(self, key: str) -> tuple[Path, Path]:
        if not re.fullmatch(r"[a-zA-Z0-9_/-]+", key) or ".." in key.split("/"):
            raise CatalogFetchError(f"非法缓存键: {key}")
        html_path = self.root.joinpath(*key.split("/")).with_suffix(".html")
        meta_path = html_path.with_suffix(".meta.json")
        return html_path, meta_path

    def load(self, key: str, expected_url: str) -> CachedPage:
        expected_url = _official_url(expected_url)
        html_path, meta_path = self._paths(key)
        if not html_path.is_file() or not meta_path.is_file():
            raise CatalogFetchError(
                f"缺少本地缓存 {key}；首次运行请显式使用 --refresh"
            )
        try:
            metadata = json.loads(meta_path.read_text(encoding="utf-8"))
            body = html_path.read_bytes()
            if metadata["request_url"] != expected_url:
                raise CatalogFetchError(
                    f"缓存 URL 不匹配: {metadata['request_url']} != {expected_url}"
                )
            final_url = _official_url(metadata["final_url"])
            actual_hash = _sha256_bytes(body)
            if actual_hash != metadata["content_sha256"]:
                raise CatalogFetchError(f"缓存内容哈希不匹配: {key}")
            captured_at = datetime.fromisoformat(metadata["captured_at"])
            last_checked_at = datetime.fromisoformat(metadata["last_checked_at"])
            if (
                captured_at.tzinfo is None
                or last_checked_at.tzinfo is None
                or captured_at.utcoffset() is None
                or last_checked_at.utcoffset() is None
            ):
                raise CatalogFetchError(f"缓存时间缺少时区: {key}")
            return CachedPage(
                request_url=expected_url,
                final_url=final_url,
                captured_at=captured_at,
                last_checked_at=last_checked_at,
                content_sha256=actual_hash,
                content_type=metadata["content_type"],
                body=body,
            )
        except (KeyError, ValueError, json.JSONDecodeError, OSError) as exc:
            if isinstance(exc, CatalogFetchError):
                raise
            raise CatalogFetchError(f"缓存元数据损坏: {key}: {exc}") from exc

    def fetch(self, key: str, url: str) -> CachedPage:
        """条件刷新单页；最多重试两次临时错误。"""
        url = _official_url(url)
        existing: CachedPage | None = None
        existing_meta: dict[str, Any] = {}
        html_path, meta_path = self._paths(key)
        if html_path.is_file() and meta_path.is_file():
            existing = self.load(key, url)
            existing_meta = json.loads(meta_path.read_text(encoding="utf-8"))

        headers = {"User-Agent": USER_AGENT, "Accept": "text/html"}
        if existing_meta.get("etag"):
            headers["If-None-Match"] = existing_meta["etag"]
        if existing_meta.get("last_modified"):
            headers["If-Modified-Since"] = existing_meta["last_modified"]

        response: FetchResponse | None = None
        for attempt in range(3):
            self.rate_limiter.wait()
            try:
                response = self.transport(url, headers)
                break
            except _TransientFetchError:
                if attempt == 2:
                    raise
                time.sleep(2**attempt)
        if response is None:
            raise CatalogFetchError(f"未取得官方页面响应: {url}")

        checked_at = _now()
        if response.status == 304:
            if existing is None:
                raise CatalogFetchError(f"无本地正文却收到 304: {url}")
            existing_meta["last_checked_at"] = checked_at.isoformat()
            _atomic_write_json(meta_path, existing_meta)
            return self.load(key, url)
        if response.status != 200:
            raise CatalogFetchError(f"官方页面非 200 响应: {response.status}: {url}")

        content_type = response.headers.get("content-type", "").lower()
        if not (
            content_type.startswith("text/html")
            or content_type.startswith("application/xhtml+xml")
        ):
            raise CatalogFetchError(
                f"官方页面 Content-Type 非 HTML: {content_type or '<missing>'}: {url}"
            )
        if len(response.body) > MAX_PAGE_BYTES:
            raise CatalogFetchError(f"官方页面超过 5 MiB: {url}")
        try:
            decoded = response.body.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise CatalogFetchError(f"官方页面不是 UTF-8: {url}") from exc
        if "<html" not in decoded.lower() or "</html>" not in decoded.lower():
            raise CatalogFetchError(f"官方响应不是完整 HTML: {url}")

        digest = _sha256_bytes(response.body)
        captured_at = (
            existing.captured_at
            if existing is not None and existing.content_sha256 == digest
            else checked_at
        )
        if existing is None or existing.content_sha256 != digest:
            _atomic_write_bytes(html_path, response.body)
        metadata = {
            "request_url": url,
            "final_url": _official_url(response.final_url),
            "captured_at": captured_at.isoformat(),
            "last_checked_at": checked_at.isoformat(),
            "content_sha256": digest,
            "content_type": content_type,
            "byte_count": len(response.body),
            "etag": response.headers.get("etag"),
            "last_modified": response.headers.get("last-modified"),
        }
        _atomic_write_json(meta_path, metadata)
        return self.load(key, url)


def _document(page: CachedPage):
    try:
        return html.fromstring(page.text)
    except (ValueError, TypeError) as exc:
        raise CatalogParseError(f"无法解析 HTML: {page.final_url}") from exc


def _cell_segments(cell) -> list[str]:
    return [
        normalized
        for text_value in cell.xpath(".//text()")
        if (normalized := _normalize_text(text_value))
    ]


def _cell_raw(cell) -> str:
    return "\n".join(_cell_segments(cell))


def _row_raw(cells: Iterable[Any]) -> str:
    return " | ".join(_cell_raw(cell) for cell in cells)


def _evidence(
    page: CachedPage,
    raw_text: str,
    normalized_value: str | list[str],
) -> CatalogFieldEvidence:
    raw_text = raw_text.strip()
    if not raw_text:
        raise CatalogParseError("证据原始片段不得为空")
    return CatalogFieldEvidence(
        source_url=page.final_url,
        captured_at=page.captured_at,
        page_content_sha256=page.content_sha256,
        fragment_sha256=_sha256_text(raw_text),
        raw_text=raw_text,
        normalized_value=normalized_value,
    )


def _with_hash(model_type, payload: dict[str, Any]):
    provisional_payload = dict(payload)
    provisional_payload["content_sha256"] = "0" * 64
    provisional = model_type.model_validate(provisional_payload)
    normalized = provisional.model_dump(mode="python")
    normalized["content_sha256"] = _content_hash(normalized)
    return model_type.model_validate(normalized)


def resolve_catalogs(entry_page: CachedPage) -> list[ResolvedCatalog]:
    document = _document(entry_page)
    resolved: list[ResolvedCatalog] = []
    anchors = document.xpath("//a[@href]")
    for spec in CATALOG_SPECS:
        matches: list[tuple[str, str]] = []
        for anchor in anchors:
            href = anchor.get("href") or ""
            url = urllib.parse.urljoin(entry_page.final_url, href)
            if spec.snapshot_id not in url:
                continue
            title = _normalize_text(anchor.text_content())
            matches.append((title, _official_url(url)))
        if len(matches) != 1:
            raise CatalogParseError(
                f"官方入口中快照 {spec.snapshot_id} 链接数量为 {len(matches)}"
            )
        title, url = matches[0]
        parsed = urllib.parse.urlsplit(url)
        if parsed.hostname != "yzbm.tsinghua.edu.cn" or parsed.path != spec.expected_path:
            raise CatalogParseError(
                f"官方入口快照路径改变: {spec.snapshot_id}: {url}"
            )
        if "2027年博士研究生招生专业目录" not in title:
            raise CatalogParseError(f"官方入口标题不符合 2027 博士目录: {title}")
        is_recommendation = "推荐免试" in title
        if is_recommendation != (
            spec.catalog_type
            == CatalogType.DOCTORAL_RECOMMENDATION_EXEMPT
        ):
            raise CatalogParseError(f"目录类型与入口标题不一致: {title}")
        resolved.append(
            ResolvedCatalog(
                spec=spec,
                title=title,
                catalog_url=url,
                raw_link_text=f"{title}\n{url}",
            )
        )
    return resolved


def discover_departments(
    resolved: ResolvedCatalog,
    index_page: CachedPage,
) -> list[DiscoveredDepartment]:
    if resolved.spec.snapshot_id not in index_page.final_url:
        raise CatalogParseError(
            f"目录首页 URL 不包含预期快照: {index_page.final_url}"
        )
    document = _document(index_page)
    discovered: dict[str, DiscoveredDepartment] = {}
    for anchor in document.xpath("//a[contains(@href, 'yxsdm=')]"):
        raw_text = _normalize_text(anchor.text_content())
        match = re.fullmatch(r"(?P<code>\d{3})\s+(?P<name>.+)", raw_text)
        if not match:
            raise CatalogParseError(f"无法解析院系入口标签: {raw_text!r}")
        code = match.group("code")
        name = match.group("name")
        url = _official_url(
            urllib.parse.urljoin(resolved.catalog_url, anchor.get("href"))
        )
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
        if query.get("yxsdm") != [code] or resolved.spec.snapshot_id not in url:
            raise CatalogParseError(f"院系链接与标签不一致: {raw_text}: {url}")
        item = DiscoveredDepartment(
            code=code,
            name=name,
            page_url=url,
            raw_link_text=f"{raw_text}\n{url}",
        )
        if code in discovered and discovered[code] != item:
            raise CatalogParseError(f"院系代码出现冲突入口: {code}")
        discovered[code] = item
    if not discovered:
        raise CatalogParseError(f"目录首页未发现院系: {resolved.catalog_url}")
    return [discovered[code] for code in sorted(discovered)]


PROGRAM_PATTERN = re.compile(
    r"^(?P<code>[0-9A-Z]{6})\s*[（(]"
    r"(?P<category>学术学位|专业学位)[）)]\s*(?P<name>.+)$"
)
DIRECTION_PATTERN = re.compile(
    r"^(?P<code>\d{2})[（(](?P<mode>[^）)]+)[）)](?P<name>.+)$"
)
DEPARTMENT_PATTERN = re.compile(r"^(?P<code>\d{3})\s+(?P<name>.+)$")


def _explicit_tags(text: str) -> list[str]:
    tags: list[str] = []
    if re.search(r"仅\s*推免", text):
        tags.append("recommendation_exempt_only")
    if "不招收直博生" in text or "不招直博" in text:
        tags.append("no_direct_phd")
    return tags


def _make_remark(
    *,
    snapshot_id: str,
    scope: RemarkScope,
    target_id: str,
    text: str,
    page: CachedPage,
    raw_text: str,
) -> AdmissionRemark:
    text = _normalize_text(text)
    tags = _explicit_tags(text)
    remark_id = _entity_id("remark", snapshot_id, scope.value, target_id, text)
    evidence_text = _evidence(page, raw_text, text)
    evidence_tags = _evidence(page, raw_text, tags)
    return _with_hash(
        AdmissionRemark,
        {
            "remark_id": remark_id,
            "snapshot_id": snapshot_id,
            "scope": scope,
            "target_id": target_id,
            "text": text,
            "explicit_tags": tags,
            "provenance": {
                "text": evidence_text,
                "explicit_tags": evidence_tags,
            },
        },
    )


def parse_department_page(
    resolved: ResolvedCatalog,
    discovered: DiscoveredDepartment,
    index_page: CachedPage,
    page: CachedPage,
) -> ParsedDepartmentBundle:
    if resolved.spec.snapshot_id not in page.final_url:
        raise CatalogParseError(f"院系页快照错误: {page.final_url}")
    document = _document(page)
    rows = document.xpath("//table//tr")
    if not rows:
        raise CatalogParseError(f"院系页缺少目录表格: {page.final_url}")
    header = [_normalize_text(cell.text_content()) for cell in rows[0].xpath("./th|./td")]
    expected_header = ["院系、专业、研究方向", "导师姓名", "招生说明"]
    if header != expected_header:
        raise CatalogParseError(
            f"目录表头改变: {page.final_url}: {header!r}"
        )

    department_id = _entity_id(
        "department", resolved.spec.snapshot_id, discovered.code
    )
    programs: list[Program] = []
    directions: list[ResearchDirection] = []
    advisors: dict[tuple[str, str], AdvisorOrGroup] = {}
    offerings: list[Offering] = []
    remarks: list[AdmissionRemark] = []
    seen_program_codes: set[str] = set()
    seen_direction_keys: set[tuple[str, str]] = set()
    seen_offering_keys: set[tuple[str, str | None]] = set()
    current_program: Program | None = None
    current_direction: ResearchDirection | None = None
    department_row_raw: str | None = None
    found_department = False
    official_empty = False

    for row_index, row in enumerate(rows[1:], start=1):
        cells = row.xpath("./th|./td")
        normalized_cells = [_normalize_text(cell.text_content()) for cell in cells]
        if not any(normalized_cells):
            continue
        if len(cells) == 1 and normalized_cells[0] == "暂无数据":
            official_empty = True
            continue
        if (
            len(cells) == 1
            and normalized_cells[0].startswith("注：")
            and "专业目录所列导师" in normalized_cells[0]
        ):
            # 官方全局免责声明有时位于 table 内且 colspan=4；
            # extract_snapshot_disclaimers() 会在快照层单独保存。
            continue

        first_segments = _cell_segments(cells[0])
        first_text = first_segments[0] if first_segments else ""
        department_match = DEPARTMENT_PATTERN.fullmatch(first_text)
        if (
            department_match
            and cells[0].get("colspan") == "2"
            and len(cells) == 2
        ):
            if found_department:
                raise CatalogParseError(f"院系页出现重复院系行: {page.final_url}")
            if (
                department_match.group("code") != discovered.code
                or department_match.group("name") != discovered.name
            ):
                raise CatalogParseError(
                    f"院系页与入口不一致: {first_text} != "
                    f"{discovered.code} {discovered.name}"
                )
            found_department = True
            department_row_raw = _row_raw(cells)
            current_program = None
            current_direction = None
            continue

        program_match = PROGRAM_PATTERN.fullmatch(first_text)
        if (
            program_match
            and cells[0].get("colspan") == "2"
            and len(cells) == 2
        ):
            if not found_department:
                raise CatalogParseError(f"专业行早于院系行: {page.final_url}")
            code = program_match.group("code")
            if code in seen_program_codes:
                raise CatalogParseError(
                    f"同一院系专业代码重复: {discovered.code}/{code}"
                )
            seen_program_codes.add(code)
            category_raw = program_match.group("category")
            category = "academic" if category_raw == "学术学位" else "professional"
            name = _normalize_text(program_match.group("name"))
            program_id = _entity_id("program", department_id, code)
            raw_program = _cell_raw(cells[0])
            common = _evidence(page, raw_program, code)
            current_program = _with_hash(
                Program,
                {
                    "program_id": program_id,
                    "snapshot_id": resolved.spec.snapshot_id,
                    "department_id": department_id,
                    "code": code,
                    "degree_category": category,
                    "name": name,
                    "provenance": {
                        "code": common,
                        "degree_category": _evidence(
                            page, raw_program, category
                        ),
                        "name": _evidence(page, raw_program, name),
                    },
                },
            )
            programs.append(current_program)
            current_direction = None
            program_remark = _cell_raw(cells[1])
            if program_remark:
                remarks.append(
                    _make_remark(
                        snapshot_id=resolved.spec.snapshot_id,
                        scope=RemarkScope.PROGRAM,
                        target_id=program_id,
                        text=program_remark,
                        page=page,
                        raw_text=_row_raw(cells),
                    )
                )
            continue

        direction_match = DIRECTION_PATTERN.fullmatch(first_text)
        if direction_match:
            if current_program is None:
                raise CatalogParseError(f"方向行早于专业行: {page.final_url}")
            if len(cells) not in {2, 3}:
                raise CatalogParseError(
                    f"方向首行列数异常: {page.final_url} row={row_index}"
                )
            code = direction_match.group("code")
            direction_key = (current_program.program_id, code)
            if direction_key in seen_direction_keys:
                raise CatalogParseError(
                    f"同一专业方向代码重复: {current_program.code}/{code}"
                )
            seen_direction_keys.add(direction_key)
            study_mode = _normalize_text(direction_match.group("mode"))
            name = _normalize_text(direction_match.group("name"))
            direction_id = _entity_id(
                "direction", current_program.program_id, code
            )
            raw_direction = _cell_raw(cells[0])
            current_direction = _with_hash(
                ResearchDirection,
                {
                    "direction_id": direction_id,
                    "snapshot_id": resolved.spec.snapshot_id,
                    "program_id": current_program.program_id,
                    "code": code,
                    "study_mode": study_mode,
                    "name": name,
                    "provenance": {
                        "code": _evidence(page, raw_direction, code),
                        "study_mode": _evidence(
                            page, raw_direction, study_mode
                        ),
                        "name": _evidence(page, raw_direction, name),
                    },
                },
            )
            directions.append(current_direction)
            direction_remark_segments = first_segments[1:]
            if direction_remark_segments:
                direction_remark = " ".join(direction_remark_segments)
                remarks.append(
                    _make_remark(
                        snapshot_id=resolved.spec.snapshot_id,
                        scope=RemarkScope.RESEARCH_DIRECTION,
                        target_id=direction_id,
                        text=direction_remark,
                        page=page,
                        raw_text=raw_direction,
                    )
                )
            advisor_cell = cells[1]
            remark_cell = cells[2] if len(cells) == 3 else None
        else:
            if current_direction is None:
                raise CatalogParseError(
                    f"未知目录行形态: {page.final_url} row={row_index}: "
                    f"{_row_raw(cells)!r}"
                )
            if len(cells) != 2:
                raise CatalogParseError(
                    f"方向后续行列数异常: {page.final_url} row={row_index}"
                )
            advisor_cell = cells[0]
            remark_cell = cells[1]

        advisor_label = _normalize_text(advisor_cell.text_content())
        offering_remark = (
            _normalize_text(remark_cell.text_content()) if remark_cell is not None else ""
        )
        advisor_id: str | None = None
        row_raw = _row_raw(cells)
        if advisor_label:
            entity_type = (
                AdvisorEntityType.ADVISOR_GROUP
                if "导师组" in advisor_label
                else AdvisorEntityType.PERSON
            )
            advisor_key = (entity_type.value, advisor_label)
            if advisor_key not in advisors:
                advisor_id = _entity_id(
                    "advisor_or_group",
                    resolved.spec.snapshot_id,
                    department_id,
                    entity_type.value,
                    advisor_label,
                )
                raw_advisor = _cell_raw(advisor_cell)
                advisors[advisor_key] = _with_hash(
                    AdvisorOrGroup,
                    {
                        "advisor_or_group_id": advisor_id,
                        "snapshot_id": resolved.spec.snapshot_id,
                        "department_id": department_id,
                        "entity_type": entity_type,
                        "source_label": advisor_label,
                        "provenance": {
                            "entity_type": _evidence(
                                page, raw_advisor, entity_type.value
                            ),
                            "source_label": _evidence(
                                page, raw_advisor, advisor_label
                            ),
                        },
                    },
                )
            advisor_id = advisors[advisor_key].advisor_or_group_id

        offering_key = (current_direction.direction_id, advisor_id)
        if offering_key in seen_offering_keys:
            raise CatalogParseError(
                f"方向—导师关系重复: {current_direction.direction_id}/{advisor_label}"
            )
        seen_offering_keys.add(offering_key)
        offering_id = _entity_id(
            "offering",
            current_direction.direction_id,
            advisor_id or "no_advisor",
        )
        relation_value = (
            f"{current_direction.direction_id}->{advisor_id}"
            if advisor_id
            else f"{current_direction.direction_id}-><none>"
        )
        offering = _with_hash(
            Offering,
            {
                "offering_id": offering_id,
                "snapshot_id": resolved.spec.snapshot_id,
                "direction_id": current_direction.direction_id,
                "advisor_or_group_id": advisor_id,
                "provenance": {
                    "relation": _evidence(page, row_raw, relation_value)
                },
            },
        )
        offerings.append(offering)
        if offering_remark:
            remarks.append(
                _make_remark(
                    snapshot_id=resolved.spec.snapshot_id,
                    scope=RemarkScope.OFFERING,
                    target_id=offering_id,
                    text=offering_remark,
                    page=page,
                    raw_text=row_raw,
                )
            )

    if official_empty and (found_department or programs or directions or offerings):
        raise CatalogParseError(f"“暂无数据”与目录实体同时出现: {page.final_url}")
    if not official_empty and not found_department:
        raise CatalogParseError(f"院系页未出现院系行: {page.final_url}")

    raw_department = department_row_raw or discovered.raw_link_text
    department_source_page = page if department_row_raw else index_page
    department = _with_hash(
        Department,
        {
            "department_id": department_id,
            "snapshot_id": resolved.spec.snapshot_id,
            "code": discovered.code,
            "name": discovered.name,
            "source_url": page.final_url,
            "provenance": {
                "code": _evidence(
                    department_source_page, raw_department, discovered.code
                ),
                "name": _evidence(
                    department_source_page, raw_department, discovered.name
                ),
            },
        },
    )
    return ParsedDepartmentBundle(
        department=department,
        programs=programs,
        research_directions=directions,
        advisors_or_groups=list(advisors.values()),
        offerings=offerings,
        remarks=remarks,
    )


def extract_snapshot_disclaimers(
    resolved: ResolvedCatalog,
    page: CachedPage,
) -> list[AdmissionRemark]:
    document = _document(page)
    candidates = {
        _normalize_text(text_value)
        for text_value in document.xpath("//text()")
        if "专业目录所列导师" in text_value
    }
    return [
        _make_remark(
            snapshot_id=resolved.spec.snapshot_id,
            scope=RemarkScope.SNAPSHOT,
            target_id=resolved.spec.snapshot_id,
            text=text,
            page=page,
            raw_text=text,
        )
        for text in sorted(candidates)
        if text
    ]


def refresh_official_cache(
    cache: CatalogCache,
) -> dict[str, int]:
    """低频刷新入口、两个目录首页和全部发现的院系页。"""
    entry_page = cache.fetch("official_entry", OFFICIAL_ENTRY_URL)
    resolved_catalogs = resolve_catalogs(entry_page)
    counts: dict[str, int] = {}
    for resolved in resolved_catalogs:
        prefix = resolved.spec.snapshot_id
        index_page = cache.fetch(f"{prefix}/index", resolved.catalog_url)
        departments = discover_departments(resolved, index_page)
        counts[resolved.spec.catalog_type.value] = len(departments)
        for department in departments:
            cache.fetch(
                f"{prefix}/department_{department.code}",
                department.page_url,
            )
    return counts


def build_dataset_from_cache(cache: CatalogCache) -> CatalogDataset:
    entry_page = cache.load("official_entry", OFFICIAL_ENTRY_URL)
    resolved_catalogs = resolve_catalogs(entry_page)

    snapshots: list[CatalogSnapshot] = []
    departments_all: list[Department] = []
    programs_all: list[Program] = []
    directions_all: list[ResearchDirection] = []
    advisors_all: list[AdvisorOrGroup] = []
    offerings_all: list[Offering] = []
    remarks_all: list[AdmissionRemark] = []
    discovered_counts: dict[str, int] = {}
    parsed_counts: dict[str, int] = {}
    empty_counts: dict[str, int] = {}
    programs_without_directions: dict[str, int] = {}
    directions_without_advisors: dict[str, int] = {}
    offerings_without_advisor: dict[str, int] = {}

    for resolved in resolved_catalogs:
        snapshot_id = resolved.spec.snapshot_id
        catalog_key = resolved.spec.catalog_type.value
        index_page = cache.load(f"{snapshot_id}/index", resolved.catalog_url)
        discovered = discover_departments(resolved, index_page)
        discovered_counts[catalog_key] = len(discovered)
        snapshot_departments: list[Department] = []
        snapshot_programs: list[Program] = []
        snapshot_directions: list[ResearchDirection] = []
        snapshot_advisors: list[AdvisorOrGroup] = []
        snapshot_offerings: list[Offering] = []
        snapshot_remarks = extract_snapshot_disclaimers(resolved, index_page)
        page_hashes = {
            entry_page.final_url: entry_page.content_sha256,
            index_page.final_url: index_page.content_sha256,
        }
        capture_times = [entry_page.captured_at, index_page.captured_at]

        for item in discovered:
            page = cache.load(
                f"{snapshot_id}/department_{item.code}",
                item.page_url,
            )
            bundle = parse_department_page(
                resolved,
                item,
                index_page,
                page,
            )
            snapshot_departments.append(bundle.department)
            snapshot_programs.extend(bundle.programs)
            snapshot_directions.extend(bundle.research_directions)
            snapshot_advisors.extend(bundle.advisors_or_groups)
            snapshot_offerings.extend(bundle.offerings)
            snapshot_remarks.extend(bundle.remarks)
            page_hashes[page.final_url] = page.content_sha256
            capture_times.append(page.captured_at)

        parsed_counts[catalog_key] = len(snapshot_departments)
        programs_by_department: dict[str, int] = {}
        for program in snapshot_programs:
            programs_by_department[program.department_id] = (
                programs_by_department.get(program.department_id, 0) + 1
            )
        empty_counts[catalog_key] = sum(
            programs_by_department.get(department.department_id, 0) == 0
            for department in snapshot_departments
        )
        direction_program_ids = {
            direction.program_id for direction in snapshot_directions
        }
        programs_without_directions[catalog_key] = sum(
            program.program_id not in direction_program_ids
            for program in snapshot_programs
        )
        offering_advisor_by_direction = {
            offering.direction_id
            for offering in snapshot_offerings
            if offering.advisor_or_group_id is not None
        }
        directions_without_advisors[catalog_key] = sum(
            direction.direction_id not in offering_advisor_by_direction
            for direction in snapshot_directions
        )
        offerings_without_advisor[catalog_key] = sum(
            offering.advisor_or_group_id is None
            for offering in snapshot_offerings
        )

        disclaimer_ids = [
            remark.remark_id
            for remark in snapshot_remarks
            if remark.scope == RemarkScope.SNAPSHOT
        ]
        captured_at = max(capture_times)
        entry_raw = resolved.raw_link_text
        snapshot_payload = {
            "snapshot_id": snapshot_id,
            "catalog_type": resolved.spec.catalog_type,
            "academic_year": 2027,
            "source_entry_url": entry_page.final_url,
            "catalog_url": resolved.catalog_url,
            "source_link_title": resolved.title,
            "captured_at": captured_at,
            "page_content_sha256": dict(sorted(page_hashes.items())),
            "department_ids": [
                department.department_id
                for department in sorted(
                    snapshot_departments, key=lambda value: value.code
                )
            ],
            "disclaimer_remark_ids": sorted(disclaimer_ids),
            "provenance": {
                "snapshot_id": _evidence(
                    entry_page, entry_raw, snapshot_id
                ),
                "catalog_type": _evidence(
                    entry_page,
                    entry_raw,
                    resolved.spec.catalog_type.value,
                ),
                "academic_year": _evidence(entry_page, entry_raw, "2027"),
                "catalog_url": _evidence(
                    entry_page, entry_raw, resolved.catalog_url
                ),
                "source_link_title": _evidence(
                    entry_page, entry_raw, resolved.title
                ),
            },
        }
        snapshots.append(_with_hash(CatalogSnapshot, snapshot_payload))
        departments_all.extend(snapshot_departments)
        programs_all.extend(snapshot_programs)
        directions_all.extend(snapshot_directions)
        advisors_all.extend(snapshot_advisors)
        offerings_all.extend(snapshot_offerings)
        remarks_all.extend(snapshot_remarks)

    coverage = CatalogCoverage(
        discovered_departments=discovered_counts,
        parsed_departments=parsed_counts,
        empty_departments=empty_counts,
        programs_without_directions=programs_without_directions,
        directions_without_advisors=directions_without_advisors,
        offerings_without_advisor=offerings_without_advisor,
    )
    generated_at = max(snapshot.captured_at for snapshot in snapshots)
    payload = {
        "schema_version": "1.0",
        "generated_at": generated_at,
        "source_entry_url": entry_page.final_url,
        "snapshots": sorted(snapshots, key=lambda value: value.catalog_type.value),
        "departments": sorted(
            departments_all,
            key=lambda value: (value.snapshot_id, value.code),
        ),
        "programs": sorted(
            programs_all,
            key=lambda value: (
                value.snapshot_id,
                value.department_id,
                value.code,
            ),
        ),
        "research_directions": sorted(
            directions_all,
            key=lambda value: (
                value.snapshot_id,
                value.program_id,
                value.code,
            ),
        ),
        "advisors_or_groups": sorted(
            advisors_all,
            key=lambda value: (
                value.snapshot_id,
                value.department_id,
                value.entity_type.value,
                value.source_label,
            ),
        ),
        "offerings": sorted(
            offerings_all,
            key=lambda value: (
                value.snapshot_id,
                value.direction_id,
                value.advisor_or_group_id or "",
            ),
        ),
        "remarks": sorted(
            remarks_all,
            key=lambda value: (
                value.snapshot_id,
                value.scope.value,
                value.target_id,
                value.text,
            ),
        ),
        "coverage": coverage,
    }
    payload["content_sha256"] = _content_hash(payload)
    dataset = CatalogDataset.model_validate(payload)
    errors = audit_catalog_dataset(dataset)
    if errors:
        raise CatalogAuditError("; ".join(errors))
    return dataset


def serialize_dataset(dataset: CatalogDataset) -> bytes:
    return (
        json.dumps(
            dataset.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
        + "\n"
    ).encode("utf-8")


def write_dataset_atomic(dataset: CatalogDataset, output_path: Path) -> None:
    errors = audit_catalog_dataset(dataset)
    if errors:
        raise CatalogAuditError("; ".join(errors))
    _atomic_write_bytes(output_path, serialize_dataset(dataset))


def _hash_matches(model: Any) -> bool:
    payload = model.model_dump(mode="python")
    expected = payload.pop("content_sha256")
    return expected == _sha256_text(_canonical_json(payload))


def _audit_evidence_map(
    *,
    context: str,
    snapshot: CatalogSnapshot,
    provenance: dict[str, CatalogFieldEvidence],
    expected_values: dict[str, str | list[str]],
) -> list[str]:
    errors: list[str] = []
    if set(provenance) != set(expected_values):
        errors.append(
            f"{context}: provenance 字段集合错误 "
            f"actual={sorted(provenance)} expected={sorted(expected_values)}"
        )
    for field_name, expected_value in expected_values.items():
        evidence = provenance.get(field_name)
        if evidence is None:
            continue
        if evidence.fragment_sha256 != _sha256_text(evidence.raw_text):
            errors.append(f"{context}.{field_name}: fragment_sha256 与 raw_text 不一致")
        if evidence.normalized_value != expected_value:
            errors.append(
                f"{context}.{field_name}: normalized_value 与实际字段不一致"
            )
        expected_page_hash = snapshot.page_content_sha256.get(evidence.source_url)
        if expected_page_hash is None:
            errors.append(
                f"{context}.{field_name}: 来源页不属于该 snapshot"
            )
        elif evidence.page_content_sha256 != expected_page_hash:
            errors.append(
                f"{context}.{field_name}: evidence 页面哈希与 snapshot 不一致"
            )
        if evidence.captured_at > snapshot.captured_at:
            errors.append(
                f"{context}.{field_name}: evidence 捕获时间晚于 snapshot"
            )
    return errors


def audit_catalog_dataset(dataset: CatalogDataset) -> list[str]:
    errors: list[str] = []
    expected_snapshots = {
        spec.snapshot_id: spec.catalog_type for spec in CATALOG_SPECS
    }
    snapshot_map = {snapshot.snapshot_id: snapshot for snapshot in dataset.snapshots}
    if len(snapshot_map) != len(dataset.snapshots):
        errors.append("snapshot_id 重复")
    if set(snapshot_map) != set(expected_snapshots):
        errors.append("快照 UUID 集合不等于批准的两个 2027 目录")
    for snapshot_id, expected_type in expected_snapshots.items():
        snapshot = snapshot_map.get(snapshot_id)
        if snapshot and snapshot.catalog_type != expected_type:
            errors.append(f"{snapshot_id}: catalog_type 错误")

    for snapshot in dataset.snapshots:
        if snapshot.source_entry_url != dataset.source_entry_url:
            errors.append(f"{snapshot.snapshot_id}: source_entry_url 不一致")
        for source_url in snapshot.page_content_sha256:
            try:
                _official_url(source_url)
            except CatalogFetchError:
                errors.append(f"{snapshot.snapshot_id}: 页面 URL 非官方来源")
                continue
            if (
                source_url != snapshot.source_entry_url
                and snapshot.snapshot_id not in source_url
            ):
                errors.append(
                    f"{snapshot.snapshot_id}: 页面 URL 不属于该 snapshot"
                )
        errors.extend(
            _audit_evidence_map(
                context=f"snapshot:{snapshot.snapshot_id}",
                snapshot=snapshot,
                provenance=snapshot.provenance,
                expected_values={
                    "snapshot_id": snapshot.snapshot_id,
                    "catalog_type": snapshot.catalog_type.value,
                    "academic_year": str(snapshot.academic_year),
                    "catalog_url": snapshot.catalog_url,
                    "source_link_title": snapshot.source_link_title,
                },
            )
        )

    entity_groups = {
        "department": dataset.departments,
        "program": dataset.programs,
        "direction": dataset.research_directions,
        "advisor_or_group": dataset.advisors_or_groups,
        "offering": dataset.offerings,
        "remark": dataset.remarks,
    }
    for label, entities in entity_groups.items():
        ids: set[str] = set()
        for entity in entities:
            id_field = {
                "department": "department_id",
                "program": "program_id",
                "direction": "direction_id",
                "advisor_or_group": "advisor_or_group_id",
                "offering": "offering_id",
                "remark": "remark_id",
            }[label]
            entity_id = getattr(entity, id_field)
            if entity_id in ids:
                errors.append(f"{label} ID 重复: {entity_id}")
            ids.add(entity_id)
            if entity.snapshot_id not in snapshot_map:
                errors.append(f"{label} 引用未知 snapshot: {entity_id}")
            if not _hash_matches(entity):
                errors.append(f"{label} 内容哈希错误: {entity_id}")

    for snapshot in dataset.snapshots:
        if not _hash_matches(snapshot):
            errors.append(f"snapshot 内容哈希错误: {snapshot.snapshot_id}")
    dataset_payload = dataset.model_dump(mode="python")
    dataset_hash = dataset_payload.pop("content_sha256")
    if dataset_hash != _sha256_text(_canonical_json(dataset_payload)):
        errors.append("dataset 内容哈希错误")

    department_map = {
        value.department_id: value for value in dataset.departments
    }
    program_map = {value.program_id: value for value in dataset.programs}
    direction_map = {
        value.direction_id: value for value in dataset.research_directions
    }
    advisor_map = {
        value.advisor_or_group_id: value
        for value in dataset.advisors_or_groups
    }
    offering_map = {
        value.offering_id: value for value in dataset.offerings
    }
    department_ids = set(department_map)
    program_ids = set(program_map)
    direction_ids = set(direction_map)
    advisor_ids = set(advisor_map)
    offering_ids = set(offering_map)

    for snapshot in dataset.snapshots:
        actual = {
            department.department_id
            for department in dataset.departments
            if department.snapshot_id == snapshot.snapshot_id
        }
        if set(snapshot.department_ids) != actual:
            errors.append(f"{snapshot.snapshot_id}: department_ids 不完整")
        for remark_id in snapshot.disclaimer_remark_ids:
            remark = next(
                (
                    value
                    for value in dataset.remarks
                    if value.remark_id == remark_id
                ),
                None,
            )
            if remark is None:
                errors.append(
                    f"{snapshot.snapshot_id}: disclaimer_remark_id 不存在"
                )
            elif (
                remark.snapshot_id != snapshot.snapshot_id
                or remark.scope != RemarkScope.SNAPSHOT
                or remark.target_id != snapshot.snapshot_id
            ):
                errors.append(
                    f"{snapshot.snapshot_id}: disclaimer_remark_id 作用域不一致"
                )

    for department in dataset.departments:
        snapshot = snapshot_map.get(department.snapshot_id)
        if snapshot:
            errors.extend(
                _audit_evidence_map(
                    context=f"department:{department.department_id}",
                    snapshot=snapshot,
                    provenance=department.provenance,
                    expected_values={
                        "code": department.code,
                        "name": department.name,
                    },
                )
            )
    for program in dataset.programs:
        department = department_map.get(program.department_id)
        if department is None:
            errors.append(f"program 外键缺失: {program.program_id}")
        elif program.snapshot_id != department.snapshot_id:
            errors.append(
                f"program→department 跨 snapshot: {program.program_id}"
            )
        snapshot = snapshot_map.get(program.snapshot_id)
        if snapshot:
            errors.extend(
                _audit_evidence_map(
                    context=f"program:{program.program_id}",
                    snapshot=snapshot,
                    provenance=program.provenance,
                    expected_values={
                        "code": program.code,
                        "degree_category": program.degree_category,
                        "name": program.name,
                    },
                )
            )
    for direction in dataset.research_directions:
        program = program_map.get(direction.program_id)
        if program is None:
            errors.append(f"direction 外键缺失: {direction.direction_id}")
        elif direction.snapshot_id != program.snapshot_id:
            errors.append(
                f"direction→program 跨 snapshot: {direction.direction_id}"
            )
        snapshot = snapshot_map.get(direction.snapshot_id)
        if snapshot:
            errors.extend(
                _audit_evidence_map(
                    context=f"direction:{direction.direction_id}",
                    snapshot=snapshot,
                    provenance=direction.provenance,
                    expected_values={
                        "code": direction.code,
                        "study_mode": direction.study_mode,
                        "name": direction.name,
                    },
                )
            )
    for advisor in dataset.advisors_or_groups:
        department = department_map.get(advisor.department_id)
        if department is None:
            errors.append(
                f"advisor_or_group 外键缺失: {advisor.advisor_or_group_id}"
            )
        elif advisor.snapshot_id != department.snapshot_id:
            errors.append(
                "advisor_or_group→department 跨 snapshot: "
                f"{advisor.advisor_or_group_id}"
            )
        contains_group = "导师组" in advisor.source_label
        if contains_group != (
            advisor.entity_type == AdvisorEntityType.ADVISOR_GROUP
        ):
            errors.append(
                f"导师组类型不一致: {advisor.advisor_or_group_id}"
            )
        snapshot = snapshot_map.get(advisor.snapshot_id)
        if snapshot:
            errors.extend(
                _audit_evidence_map(
                    context=f"advisor_or_group:{advisor.advisor_or_group_id}",
                    snapshot=snapshot,
                    provenance=advisor.provenance,
                    expected_values={
                        "entity_type": advisor.entity_type.value,
                        "source_label": advisor.source_label,
                    },
                )
            )
    for offering in dataset.offerings:
        direction = direction_map.get(offering.direction_id)
        if direction is None:
            errors.append(f"offering direction 外键缺失: {offering.offering_id}")
        elif offering.snapshot_id != direction.snapshot_id:
            errors.append(
                f"offering→direction 跨 snapshot: {offering.offering_id}"
            )
        advisor = (
            advisor_map.get(offering.advisor_or_group_id)
            if offering.advisor_or_group_id is not None
            else None
        )
        if offering.advisor_or_group_id is not None and advisor is None:
            errors.append(f"offering advisor 外键缺失: {offering.offering_id}")
        elif advisor is not None and offering.snapshot_id != advisor.snapshot_id:
            errors.append(
                f"offering→advisor 跨 snapshot: {offering.offering_id}"
            )
        snapshot = snapshot_map.get(offering.snapshot_id)
        if snapshot:
            relation_value = (
                f"{offering.direction_id}->{offering.advisor_or_group_id}"
                if offering.advisor_or_group_id
                else f"{offering.direction_id}-><none>"
            )
            errors.extend(
                _audit_evidence_map(
                    context=f"offering:{offering.offering_id}",
                    snapshot=snapshot,
                    provenance=offering.provenance,
                    expected_values={"relation": relation_value},
                )
            )

    valid_remark_targets: dict[RemarkScope, dict[str, Any]] = {
        RemarkScope.SNAPSHOT: snapshot_map,
        RemarkScope.PROGRAM: program_map,
        RemarkScope.RESEARCH_DIRECTION: direction_map,
        RemarkScope.OFFERING: offering_map,
    }
    for remark in dataset.remarks:
        target = valid_remark_targets[remark.scope].get(remark.target_id)
        if target is None:
            errors.append(f"remark 目标缺失: {remark.remark_id}")
        elif remark.snapshot_id != target.snapshot_id:
            errors.append(f"remark→target 跨 snapshot: {remark.remark_id}")
        snapshot = snapshot_map.get(remark.snapshot_id)
        if snapshot:
            errors.extend(
                _audit_evidence_map(
                    context=f"remark:{remark.remark_id}",
                    snapshot=snapshot,
                    provenance=remark.provenance,
                    expected_values={
                        "text": remark.text,
                        "explicit_tags": list(remark.explicit_tags),
                    },
                )
            )

    scoped_labels: dict[tuple[str, str, str, str], str] = {}
    for advisor in dataset.advisors_or_groups:
        key = (
            advisor.snapshot_id,
            advisor.department_id,
            advisor.entity_type.value,
            advisor.source_label,
        )
        prior = scoped_labels.get(key)
        if prior and prior != advisor.advisor_or_group_id:
            errors.append(f"同一来源标签产生多个实体: {key}")
        scoped_labels[key] = advisor.advisor_or_group_id

    forbidden_keys = {
        "quota",
        "actual_slots",
        "currently_recruiting",
        "mentor_style",
        "funding",
        "lab_atmosphere",
        "popularity",
        "subjective_score",
    }
    serialized = dataset.model_dump(mode="python")

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            leaked = forbidden_keys & set(value)
            if leaked:
                errors.append(f"出现 D1 禁止字段: {sorted(leaked)}")
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(serialized)

    expected_catalog_keys = {
        snapshot.catalog_type.value for snapshot in dataset.snapshots
    }
    coverage_maps = {
        "discovered_departments": dataset.coverage.discovered_departments,
        "parsed_departments": dataset.coverage.parsed_departments,
        "empty_departments": dataset.coverage.empty_departments,
        "programs_without_directions": (
            dataset.coverage.programs_without_directions
        ),
        "directions_without_advisors": (
            dataset.coverage.directions_without_advisors
        ),
        "offerings_without_advisor": (
            dataset.coverage.offerings_without_advisor
        ),
    }
    for label, values in coverage_maps.items():
        if set(values) != expected_catalog_keys:
            errors.append(f"coverage.{label} 键集合错误")
        if any(
            not isinstance(value, int)
            or isinstance(value, bool)
            or value < 0
            for value in values.values()
        ):
            errors.append(f"coverage.{label} 必须是非负整数")

    directions_by_program = {
        direction.program_id for direction in dataset.research_directions
    }
    directions_with_advisor = {
        offering.direction_id
        for offering in dataset.offerings
        if offering.advisor_or_group_id is not None
    }
    for snapshot in dataset.snapshots:
        key = snapshot.catalog_type.value
        snapshot_departments = [
            value
            for value in dataset.departments
            if value.snapshot_id == snapshot.snapshot_id
        ]
        snapshot_department_ids = {
            value.department_id for value in snapshot_departments
        }
        snapshot_programs = [
            value
            for value in dataset.programs
            if value.snapshot_id == snapshot.snapshot_id
        ]
        snapshot_directions = [
            value
            for value in dataset.research_directions
            if value.snapshot_id == snapshot.snapshot_id
        ]
        snapshot_offerings = [
            value
            for value in dataset.offerings
            if value.snapshot_id == snapshot.snapshot_id
        ]
        expected_coverage = {
            "discovered_departments": len(snapshot_departments),
            "parsed_departments": len(snapshot_departments),
            "empty_departments": sum(
                not any(
                    program.department_id == department_id
                    for program in snapshot_programs
                )
                for department_id in snapshot_department_ids
            ),
            "programs_without_directions": sum(
                program.program_id not in directions_by_program
                for program in snapshot_programs
            ),
            "directions_without_advisors": sum(
                direction.direction_id not in directions_with_advisor
                for direction in snapshot_directions
            ),
            "offerings_without_advisor": sum(
                offering.advisor_or_group_id is None
                for offering in snapshot_offerings
            ),
        }
        for label, expected_value in expected_coverage.items():
            actual = coverage_maps[label].get(key)
            if actual != expected_value:
                errors.append(
                    f"coverage.{label}[{key}] 与实体重算不一致: "
                    f"{actual} != {expected_value}"
                )
    return errors
