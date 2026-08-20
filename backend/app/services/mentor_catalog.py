"""进程内导师目录缓存。

`GET /mentors` 与 `GET /scatter` 共用同一条
`load_mentors -> grouped_mentor_resources -> score_enriched_resources`
重管线；本模块在其外加一层缓存，避免每次请求全量重算。

缓存命中条件（与 `grouped_mentor_resources` 的 identity-cache 同思路）：
- 传入的 raw records 与缓存来源是同一对象（生产路径上 `load_mentors()`
  的 lru_cache 保证这一点；测试注入的新列表会自然绕开缓存）；
- 且底层文件键未变：(导师数据文件 mtime+size, 评分发布文件 mtime+size)。
  评分文件未配置/不可 stat 时该分量取 None，不解析发布文件内部版本。
文件被替换而 lru_cache 仍返回旧列表时，先清底层缓存再重载重算。
"""

from __future__ import annotations

import os
import threading
from typing import Any

from app.core.config import settings
from app.services import data_loader
from app.services.data_loader import load_mentors
from app.services.mentor_resources import grouped_mentor_resources
from app.services.mentor_score_governance import (
    clear_score_cache,
    score_enriched_resources,
)

_lock = threading.Lock()
_cache_key: tuple[tuple[int, int], tuple[int, int] | None] | None = None
_cache_source: list[dict[str, Any]] | None = None
_cache_result: tuple[list[dict[str, Any]], dict[str, Any]] | None = None


def _file_marker(path: str | None) -> tuple[int, int] | None:
    """返回 (mtime_ns, size)；路径为空或 stat 失败返回 None。"""
    if not path:
        return None
    try:
        stat_result = os.stat(path)
    except OSError:
        return None
    return (stat_result.st_mtime_ns, stat_result.st_size)


def enriched_mentor_resources(
    raw_records: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """等价于 score_enriched_resources(grouped_mentor_resources(load_mentors()))。

    调用方传入的 raw_records 保持路由模块的可替换接缝；缺省取 load_mentors()。
    命中进程内缓存时零重算；导师数据文件 stat 不可用时退化为实时计算。
    """
    global _cache_key, _cache_source, _cache_result
    if raw_records is None:
        raw_records = load_mentors()
    mentor_marker = _file_marker(data_loader._DATA_PATH)
    if mentor_marker is None:
        # 无法确认数据文件状态：不信任缓存，按原行为实时计算。
        return score_enriched_resources(grouped_mentor_resources(raw_records))
    key = (mentor_marker, _file_marker(settings.MENTOR_SCORE_DATA_FILE))
    with _lock:
        if (
            _cache_result is not None
            and _cache_key == key
            and _cache_source is raw_records
        ):
            return _cache_result
        if (
            _cache_key is not None
            and _cache_key != key
            and _cache_source is raw_records
        ):
            # 同一来源对象但文件已替换：底层 lru_cache 仍是旧数据，
            # 先清缓存重载，保证不基于过期文件内容计算。
            data_loader.load_mentors.cache_clear()
            data_loader.load_match_candidates.cache_clear()
            data_loader.load_mentor_dataset.cache_clear()
            clear_score_cache()
            raw_records = load_mentors()
        result = score_enriched_resources(grouped_mentor_resources(raw_records))
        _cache_key = key
        _cache_source = raw_records
        _cache_result = result
        return result


def _reset_cache_for_tests() -> None:
    """仅供测试隔离使用。"""
    global _cache_key, _cache_source, _cache_result
    with _lock:
        _cache_key = None
        _cache_source = None
        _cache_result = None
