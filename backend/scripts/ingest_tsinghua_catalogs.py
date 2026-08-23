#!/usr/bin/env python3
"""低频缓存并离线生成 D1 清华 2027 博士目录数据集。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.services.catalog_ingestion import (  # noqa: E402
    DEFAULT_MIN_INTERVAL_SECONDS,
    CatalogCache,
    CatalogIngestionError,
    build_dataset_from_cache,
    refresh_official_cache,
    write_dataset_atomic,
)


DEFAULT_CACHE = BACKEND_ROOT / "data" / "catalog_d1" / "cache"
DEFAULT_OUTPUT = (
    BACKEND_ROOT / "data" / "catalog_d1" / "generated" / "catalogs.json"
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "D1 只摄取清华官方 2027 普通博士与推免博士目录；"
            "默认纯离线，首次运行需显式 --refresh。"
        )
    )
    parser.add_argument("--refresh", action="store_true", help="低频刷新官方缓存")
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--min-interval",
        type=float,
        default=DEFAULT_MIN_INTERVAL_SECONDS,
        help="网络请求最小间隔秒数，不得小于 1.0",
    )
    args = parser.parse_args()

    try:
        cache = CatalogCache(
            args.cache_dir,
            min_interval_seconds=args.min_interval,
        )
        if args.refresh:
            refreshed = refresh_official_cache(cache)
            print(
                "cache_refreshed "
                + " ".join(
                    f"{catalog_type}={count}"
                    for catalog_type, count in sorted(refreshed.items())
                )
            )
        dataset = build_dataset_from_cache(cache)
        write_dataset_atomic(dataset, args.output)
        print(
            "PASS "
            f"snapshots={len(dataset.snapshots)} "
            f"departments={len(dataset.departments)} "
            f"programs={len(dataset.programs)} "
            f"directions={len(dataset.research_directions)} "
            f"advisor_or_groups={len(dataset.advisors_or_groups)} "
            f"offerings={len(dataset.offerings)} "
            f"remarks={len(dataset.remarks)} "
            f"content_sha256={dataset.content_sha256} "
            f"output={args.output}"
        )
        return 0
    except (CatalogIngestionError, OSError, ValueError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
