"""D1 官方目录解析合同；所有 HTML 均为合成夹具，不代表真实目录覆盖。"""

from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from app.schemas.catalog import AdvisorEntityType, CatalogType, RemarkScope
from app.services import catalog_ingestion
from app.services.catalog_ingestion import (
    OFFICIAL_ENTRY_URL,
    CachedPage,
    CatalogCache,
    CatalogFetchError,
    CatalogParseError,
    FetchResponse,
    audit_catalog_dataset,
    build_dataset_from_cache,
    discover_departments,
    parse_department_page,
    refresh_official_cache,
    resolve_catalogs,
    serialize_dataset,
    write_dataset_atomic,
)


CAPTURED_AT = datetime(2026, 7, 30, 12, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
REGULAR_URL = (
    "https://yzbm.tsinghua.edu.cn/publish/s03/s0303/detail/"
    "ab3ae191-f6b5-4a83-bd4d-02a279904861"
)
RECOMMENDATION_URL = (
    "https://yzbm.tsinghua.edu.cn/publish/s01/s0103/detail/"
    "2ede1fca-d9a0-407a-9d68-3475494848b7/2"
)


def page(text: str, url: str) -> CachedPage:
    body = text.encode("utf-8")
    return CachedPage(
        request_url=url,
        final_url=url,
        captured_at=CAPTURED_AT,
        last_checked_at=CAPTURED_AT,
        content_sha256=hashlib.sha256(body).hexdigest(),
        content_type="text/html;charset=UTF-8",
        body=body,
    )


def entry_html() -> str:
    return f"""
    <html><body>
      <a href="{REGULAR_URL}">清华大学2027年博士研究生招生专业目录</a>
      <a href="{RECOMMENDATION_URL}">
        清华大学2027年博士研究生招生专业目录_推荐免试
      </a>
    </body></html>
    """


def index_html(base_url: str, departments: list[tuple[str, str]]) -> str:
    links = "".join(
        f'<a href="?yxsdm={code}">{code}&nbsp;{name}</a>'
        for code, name in departments
    )
    return f"""
    <html><body>{links}
      <div>注：专业目录所列导师均具有博士生招生资格，与招生人数不完全对应。</div>
      <span data-base="{base_url}"></span>
    </body></html>
    """


def department_html(
    code: str = "003",
    name: str = "土木工程系",
    *,
    advisor: str = "王强",
) -> str:
    return f"""
    <html><body><table>
      <tr><th>院系、专业、研究方向</th><th>导师姓名</th><th>招生说明</th></tr>
      <tr><td colspan="2">{code}&nbsp;{name}</td><td>官方咨询信息</td></tr>
      <tr><td colspan="2">081400 （学术学位） 土木工程</td><td>授工学学位</td></tr>
      <tr>
        <td rowspan="2">01（全日制）结构工程</td>
        <td>DE GEUS MARTIJN</td><td></td>
      </tr>
      <tr><td>{advisor}</td><td>不招收直博生</td></tr>
      <tr>
        <td rowspan="2"><div>02（全日制）工程专项</div><div>仅推免</div></td>
        <td>{advisor}</td><td></td>
      </tr>
      <tr><td>车辆国重导师组</td><td></td></tr>
      <tr><td colspan="4">注：专业目录所列导师均具有博士生招生资格，与招生人数不完全对应。</td></tr>
    </table></body></html>
    """


def empty_department_html() -> str:
    return """
    <html><body><table>
      <tr><th>院系、专业、研究方向</th><th>导师姓名</th><th>招生说明</th></tr>
      <tr><td colspan="3">暂无数据</td></tr>
    </table></body></html>
    """


def resolved_regular():
    resolved = resolve_catalogs(page(entry_html(), OFFICIAL_ENTRY_URL))
    return next(
        value
        for value in resolved
        if value.catalog_url == REGULAR_URL
    )


def test_rowspan_blank_inheritance_english_group_and_explicit_remarks() -> None:
    resolved = resolved_regular()
    index = page(index_html(REGULAR_URL, [("003", "土木工程系")]), REGULAR_URL)
    discovered = discover_departments(resolved, index)[0]
    bundle = parse_department_page(
        resolved,
        discovered,
        index,
        page(department_html(), discovered.page_url),
    )

    assert len(bundle.programs) == 1
    assert len(bundle.research_directions) == 2
    assert len(bundle.advisors_or_groups) == 3
    assert len(bundle.offerings) == 4
    by_label = {
        entity.source_label: entity for entity in bundle.advisors_or_groups
    }
    assert by_label["DE GEUS MARTIJN"].entity_type == AdvisorEntityType.PERSON
    assert (
        by_label["车辆国重导师组"].entity_type
        == AdvisorEntityType.ADVISOR_GROUP
    )
    wang_id = by_label["王强"].advisor_or_group_id
    assert sum(
        offering.advisor_or_group_id == wang_id
        for offering in bundle.offerings
    ) == 2
    tags = {tag for remark in bundle.remarks for tag in remark.explicit_tags}
    assert tags == {"recommendation_exempt_only", "no_direct_phd"}


def test_same_source_label_in_different_departments_is_not_global_identity() -> None:
    resolved = resolved_regular()
    index = page(
        index_html(
            REGULAR_URL,
            [("003", "土木工程系"), ("004", "水利水电工程系")],
        ),
        REGULAR_URL,
    )
    discovered = discover_departments(resolved, index)
    bundles = [
        parse_department_page(
            resolved,
            item,
            index,
            page(
                department_html(item.code, item.name, advisor="王强"),
                item.page_url,
            ),
        )
        for item in discovered
    ]
    ids = {
        entity.advisor_or_group_id
        for bundle in bundles
        for entity in bundle.advisors_or_groups
        if entity.source_label == "王强"
    }
    assert len(ids) == 2


def test_official_empty_department_is_preserved_without_inventing_entities() -> None:
    resolved = resolved_regular()
    index = page(index_html(REGULAR_URL, [("601", "全球创新学院")]), REGULAR_URL)
    discovered = discover_departments(resolved, index)[0]
    bundle = parse_department_page(
        resolved,
        discovered,
        index,
        page(empty_department_html(), discovered.page_url),
    )
    assert bundle.department.code == "601"
    assert bundle.programs == []
    assert bundle.offerings == []


@pytest.mark.parametrize(
    "mutated",
    [
        department_html().replace("导师姓名", "导师"),
        department_html().replace(
            '<tr><td>王强</td><td>不招收直博生</td></tr>',
            "<tr><td>未知</td><td>多余</td><td>结构</td><td>变化</td></tr>",
        ),
    ],
)
def test_page_structure_change_fails_closed(mutated: str) -> None:
    resolved = resolved_regular()
    index = page(index_html(REGULAR_URL, [("003", "土木工程系")]), REGULAR_URL)
    discovered = discover_departments(resolved, index)[0]
    with pytest.raises(CatalogParseError):
        parse_department_page(
            resolved,
            discovered,
            index,
            page(mutated, discovered.page_url),
        )


class FakeOfficialTransport:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, str]]] = []

    def __call__(self, url: str, headers: dict[str, str]) -> FetchResponse:
        self.calls.append((url, dict(headers)))
        if url == OFFICIAL_ENTRY_URL:
            body = entry_html()
        elif "ab3ae191-f6b5-4a83-bd4d-02a279904861" in url:
            body = (
                department_html()
                if "yxsdm=003" in url
                else index_html(REGULAR_URL, [("003", "土木工程系")])
            )
        elif "2ede1fca-d9a0-407a-9d68-3475494848b7" in url:
            body = (
                department_html()
                if "yxsdm=003" in url
                else index_html(
                    RECOMMENDATION_URL,
                    [("003", "土木工程系")],
                )
            )
        else:
            raise AssertionError(f"unexpected URL: {url}")
        return FetchResponse(
            status=200,
            final_url=url,
            headers={"content-type": "text/html;charset=UTF-8"},
            body=body.encode("utf-8"),
        )


def prepared_cache(tmp_path: Path) -> tuple[CatalogCache, FakeOfficialTransport]:
    transport = FakeOfficialTransport()
    cache = CatalogCache(tmp_path / "cache", transport=transport)
    cache.rate_limiter.wait = lambda: None
    refresh_official_cache(cache)
    return cache, transport


def test_same_cache_and_unchanged_refresh_are_byte_idempotent(
    tmp_path: Path,
) -> None:
    cache, _ = prepared_cache(tmp_path)
    first = build_dataset_from_cache(cache)
    first_bytes = serialize_dataset(first)
    second = build_dataset_from_cache(cache)
    assert serialize_dataset(second) == first_bytes

    refresh_official_cache(cache)
    third = build_dataset_from_cache(cache)
    assert serialize_dataset(third) == first_bytes
    assert audit_catalog_dataset(third) == []

    output = tmp_path / "catalogs.json"
    write_dataset_atomic(third, output)
    assert output.read_bytes() == first_bytes


def test_cache_hash_corruption_and_parse_failure_preserve_old_output(
    tmp_path: Path,
) -> None:
    cache, _ = prepared_cache(tmp_path)
    output = tmp_path / "catalogs.json"
    output.write_bytes(b"previous-valid-output")
    department_cache = (
        tmp_path
        / "cache"
        / "ab3ae191-f6b5-4a83-bd4d-02a279904861"
        / "department_003.html"
    )
    department_cache.write_text("<html>changed</html>", encoding="utf-8")
    with pytest.raises(CatalogFetchError, match="哈希不匹配"):
        build_dataset_from_cache(cache)
    assert output.read_bytes() == b"previous-valid-output"


def test_transient_failure_retries_twice_and_writes_no_cache(
    tmp_path: Path,
    monkeypatch,
) -> None:
    attempts = 0
    backoffs: list[int] = []
    monkeypatch.setattr(
        catalog_ingestion.time,
        "sleep",
        lambda seconds: backoffs.append(seconds),
    )

    def failing_transport(
        url: str, headers: dict[str, str]
    ) -> FetchResponse:
        nonlocal attempts
        attempts += 1
        raise catalog_ingestion._TransientFetchError("temporary")

    cache = CatalogCache(tmp_path / "cache", transport=failing_transport)
    cache.rate_limiter.wait = lambda: None
    with pytest.raises(CatalogFetchError):
        cache.fetch("official_entry", OFFICIAL_ENTRY_URL)
    assert attempts == 3
    assert backoffs == [1, 2]
    assert not (tmp_path / "cache" / "official_entry.html").exists()


def test_tampered_entity_hash_is_detected(tmp_path: Path) -> None:
    cache, _ = prepared_cache(tmp_path)
    dataset = build_dataset_from_cache(cache)
    dataset.departments[0].content_sha256 = "0" * 64
    errors = audit_catalog_dataset(dataset)
    assert any("department 内容哈希错误" in error for error in errors)


def rehash(value) -> None:
    value.content_sha256 = catalog_ingestion._content_hash(
        value.model_dump(mode="python")
    )


def rehash_dataset(dataset) -> None:
    dataset.content_sha256 = catalog_ingestion._content_hash(
        dataset.model_dump(mode="python")
    )


def regular_and_recommendation(dataset, values):
    regular_snapshot = next(
        snapshot
        for snapshot in dataset.snapshots
        if snapshot.catalog_type == CatalogType.DOCTORAL_REGULAR
    )
    recommendation_snapshot = next(
        snapshot
        for snapshot in dataset.snapshots
        if snapshot.catalog_type
        == CatalogType.DOCTORAL_RECOMMENDATION_EXEMPT
    )
    regular = next(
        value
        for value in values
        if value.snapshot_id == regular_snapshot.snapshot_id
    )
    recommendation = next(
        value
        for value in values
        if value.snapshot_id == recommendation_snapshot.snapshot_id
    )
    return regular, recommendation


@pytest.mark.parametrize(
    ("edge", "expected_error"),
    [
        ("program_department", "program→department 跨 snapshot"),
        ("direction_program", "direction→program 跨 snapshot"),
        (
            "advisor_department",
            "advisor_or_group→department 跨 snapshot",
        ),
        ("offering_direction", "offering→direction 跨 snapshot"),
        ("offering_advisor", "offering→advisor 跨 snapshot"),
        ("remark_target", "remark→target 跨 snapshot"),
    ],
)
def test_every_relation_rejects_cross_snapshot_links(
    tmp_path: Path,
    edge: str,
    expected_error: str,
) -> None:
    cache, _ = prepared_cache(tmp_path)
    dataset = build_dataset_from_cache(cache)
    if edge == "program_department":
        regular, recommendation = regular_and_recommendation(
            dataset, dataset.programs
        )
        _, recommendation_department = regular_and_recommendation(
            dataset, dataset.departments
        )
        regular.department_id = recommendation_department.department_id
        rehash(regular)
    elif edge == "direction_program":
        regular, _ = regular_and_recommendation(
            dataset, dataset.research_directions
        )
        _, recommendation_program = regular_and_recommendation(
            dataset, dataset.programs
        )
        regular.program_id = recommendation_program.program_id
        rehash(regular)
    elif edge == "advisor_department":
        regular, _ = regular_and_recommendation(
            dataset, dataset.advisors_or_groups
        )
        _, recommendation_department = regular_and_recommendation(
            dataset, dataset.departments
        )
        regular.department_id = recommendation_department.department_id
        rehash(regular)
    elif edge == "offering_direction":
        regular, _ = regular_and_recommendation(
            dataset, dataset.offerings
        )
        _, recommendation_direction = regular_and_recommendation(
            dataset, dataset.research_directions
        )
        regular.direction_id = recommendation_direction.direction_id
        regular.provenance["relation"].normalized_value = (
            f"{regular.direction_id}->{regular.advisor_or_group_id}"
        )
        rehash(regular)
    elif edge == "offering_advisor":
        regular, _ = regular_and_recommendation(
            dataset, dataset.offerings
        )
        _, recommendation_advisor = regular_and_recommendation(
            dataset, dataset.advisors_or_groups
        )
        regular.advisor_or_group_id = (
            recommendation_advisor.advisor_or_group_id
        )
        regular.provenance["relation"].normalized_value = (
            f"{regular.direction_id}->{regular.advisor_or_group_id}"
        )
        rehash(regular)
    else:
        regular = next(
            remark
            for remark in dataset.remarks
            if remark.scope == RemarkScope.PROGRAM
            and remark.snapshot_id
            == next(
                snapshot.snapshot_id
                for snapshot in dataset.snapshots
                if snapshot.catalog_type == CatalogType.DOCTORAL_REGULAR
            )
        )
        _, recommendation_program = regular_and_recommendation(
            dataset, dataset.programs
        )
        regular.target_id = recommendation_program.program_id
        rehash(regular)
    rehash_dataset(dataset)
    errors = audit_catalog_dataset(dataset)
    assert any(expected_error in error for error in errors)


@pytest.mark.parametrize(
    ("tampering", "expected_error"),
    [
        ("raw_text", "fragment_sha256 与 raw_text 不一致"),
        ("normalized_value", "normalized_value 与实际字段不一致"),
        ("page_hash", "evidence 页面哈希与 snapshot 不一致"),
        ("foreign_source_page", "页面 URL 不属于该 snapshot"),
    ],
)
def test_field_provenance_tampering_is_detected_after_rehash(
    tmp_path: Path,
    tampering: str,
    expected_error: str,
) -> None:
    cache, _ = prepared_cache(tmp_path)
    dataset = build_dataset_from_cache(cache)
    department, _ = regular_and_recommendation(
        dataset, dataset.departments
    )
    evidence = department.provenance["name"]
    if tampering == "raw_text":
        evidence.raw_text += " 篡改"
    elif tampering == "normalized_value":
        evidence.normalized_value = "篡改名称"
    elif tampering == "page_hash":
        evidence.page_content_sha256 = "0" * 64
    else:
        regular_snapshot, recommendation_snapshot = regular_and_recommendation(
            dataset, dataset.snapshots
        )
        foreign_url, foreign_hash = next(
            (url, digest)
            for url, digest in recommendation_snapshot.page_content_sha256.items()
            if recommendation_snapshot.snapshot_id in url
        )
        regular_snapshot.page_content_sha256[foreign_url] = foreign_hash
        evidence.source_url = foreign_url
        evidence.page_content_sha256 = foreign_hash
        rehash(regular_snapshot)
    rehash(department)
    rehash_dataset(dataset)
    errors = audit_catalog_dataset(dataset)
    assert any(expected_error in error for error in errors)


@pytest.mark.parametrize("mode", ["missing", "cross_snapshot"])
def test_disclaimer_references_are_scoped_to_the_snapshot(
    tmp_path: Path,
    mode: str,
) -> None:
    cache, _ = prepared_cache(tmp_path)
    dataset = build_dataset_from_cache(cache)
    regular_snapshot, recommendation_snapshot = regular_and_recommendation(
        dataset, dataset.snapshots
    )
    if mode == "missing":
        regular_snapshot.disclaimer_remark_ids = ["remark_deadbeef"]
        expected_error = "disclaimer_remark_id 不存在"
    else:
        regular_snapshot.disclaimer_remark_ids = list(
            recommendation_snapshot.disclaimer_remark_ids
        )
        expected_error = "disclaimer_remark_id 作用域不一致"
    rehash(regular_snapshot)
    rehash_dataset(dataset)
    errors = audit_catalog_dataset(dataset)
    assert any(expected_error in error for error in errors)


@pytest.mark.parametrize(
    ("mode", "expected_error"),
    [
        ("missing_key", "coverage.empty_departments 键集合错误"),
        ("negative", "coverage.offerings_without_advisor 必须是非负整数"),
        ("wrong_count", "与实体重算不一致"),
    ],
)
def test_coverage_is_recomputed_and_rejects_tampering(
    tmp_path: Path,
    mode: str,
    expected_error: str,
) -> None:
    cache, _ = prepared_cache(tmp_path)
    dataset = build_dataset_from_cache(cache)
    key = CatalogType.DOCTORAL_REGULAR.value
    if mode == "missing_key":
        dataset.coverage.empty_departments.pop(key)
    elif mode == "negative":
        dataset.coverage.offerings_without_advisor[key] = -1
    else:
        dataset.coverage.parsed_departments[key] += 1
    rehash_dataset(dataset)
    errors = audit_catalog_dataset(dataset)
    assert any(expected_error in error for error in errors)
