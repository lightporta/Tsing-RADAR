"""一次性历史数据导入脚本（旧 SQLite → 当前 MySQL）。

用途：把上一阶段用 SQLite 暂存的 tsing_radar.db 数据迁移到当前 MySQL 数据库。
**只做一次性数据迁移，运行时不走 SQLite 连接**——业务运行统一使用 MySQL。

前置条件：
  1. 当前 .env 已配置好 MySQL DATABASE_URL
  2. 已执行 alembic upgrade head，新表已在 MySQL 中创建
  3. 旧 SQLite 文件（默认 backend/tsing_radar.db）仍然存在

CLI：
  python -m scripts.import_sqlite_data --sqlite-path ./tsing_radar.db
  python -m scripts.import_sqlite_data --sqlite-path ./tsing_radar.db --dry-run

幂等：导入用 merge（基于主键），重复运行不会重复插入。
"""

import argparse
import logging
import sys
from pathlib import Path
from typing import Any, Optional

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from sqlalchemy import create_engine, select, text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

# 当前 MySQL 目标库（从 .env 读，绝不在运行时连 SQLite）
from app.db.session import SessionLocal, init_db  # noqa: E402
from app.models.entity import Entity, EntityName, Relation  # noqa: E402
from app.models.direction import Direction, EntityDirection  # noqa: E402
from app.models.catalog import CatalogLink  # noqa: E402
from app.models.opportunity import Opportunity  # noqa: E402
from app.models.claim import Claim, Source  # noqa: E402

logger = logging.getLogger("import_sqlite")


# ── 需要迁移的表与对应 ORM 类（按依赖顺序）──
TABLES_IN_ORDER: list[tuple[str, type]] = [
    ("sources", Source),
    ("entities", Entity),
    ("entity_names", EntityName),
    ("relations", Relation),
    ("directions", Direction),
    ("entity_directions", EntityDirection),
    ("catalog_links", CatalogLink),
    ("opportunities", Opportunity),
    ("claims", Claim),
]


def _open_sqlite(sqlite_path: Path):
    """只读打开旧 SQLite 文件。"""
    if not sqlite_path.exists():
        raise FileNotFoundError(f"SQLite 文件不存在: {sqlite_path}")
    return create_engine(f"sqlite:///{sqlite_path}", echo=False)


def _table_columns(src_engine, table_name: str) -> list[str]:
    """获取旧表所有列名（按列定义顺序）。"""
    with src_engine.connect() as conn:
        cols = list(conn.execute(text(f"SELECT * FROM {table_name} LIMIT 0")).keys())
    return cols


def _iter_rows(src_engine, table_name: str, columns: list[str]):
    """流式读取旧表所有行，每行作为 dict 返回。"""
    with src_engine.connect() as conn:
        result = conn.execution_options(stream_results=True).execute(
            text(f"SELECT {', '.join(columns)} FROM {table_name}")
        )
        for row in result:
            yield dict(zip(columns, row))


def _get_pk(model_cls) -> str:
    """取 ORM 主键字段名。"""
    for col in model_cls.__table__.columns:
        if col.primary_key:
            return col.name
    raise RuntimeError(f"{model_cls.__name__} 无主键")


def import_one_table(
    src_engine,
    dst_session: Session,
    table_name: str,
    model_cls: type,
    *,
    dry_run: bool,
) -> int:
    """把一张旧表的数据导入对应 ORM 模型。返回成功导入行数。"""
    columns = _table_columns(src_engine, table_name)
    orm_columns = {c.name for c in model_cls.__table__.columns}
    pk = _get_pk(model_cls)

    # 只导入 ORM 中存在的列（多余列丢弃），保护向后兼容
    use_cols = [c for c in columns if c in orm_columns]
    skipped_cols = [c for c in columns if c not in orm_columns]
    if skipped_cols:
        logger.info("  跳过旧表 %s 多余列：%s", table_name, skipped_cols)

    count = 0
    for row in _iter_rows(src_engine, table_name, use_cols):
        pk_value = row.get(pk)
        if not pk_value:
            continue
        if dry_run:
            count += 1
            continue
        # merge = upsert（按 PK）
        existing = dst_session.get(model_cls, pk_value)
        if existing:
            for k, v in row.items():
                if v is not None:
                    setattr(existing, k, v)
        else:
            obj = model_cls(**row)
            dst_session.add(obj)
        count += 1
        if count % 1000 == 0:
            dst_session.flush()
            logger.info("  %s 已处理 %d 行", table_name, count)
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description="一次性导入旧 SQLite 数据到 MySQL")
    parser.add_argument(
        "--sqlite-path",
        default=str(_BACKEND / "tsing_radar.db"),
        help="旧 SQLite 文件路径（默认 backend/tsing_radar.db）",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="只统计不写入"
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    sqlite_path = Path(args.sqlite_path)
    src_engine = _open_sqlite(sqlite_path)

    # 检查目标 MySQL 是否已迁移
    init_db()
    dst_session = SessionLocal()

    total = 0
    try:
        for table_name, model_cls in TABLES_IN_ORDER:
            # 检查旧 SQLite 是否有此表
            with src_engine.connect() as conn:
                has = conn.execute(
                    text(
                        "SELECT name FROM sqlite_master WHERE type='table' AND name=:n"
                    ),
                    {"n": table_name},
                ).fetchone()
            if not has:
                logger.info("跳过 %s（旧库无此表）", table_name)
                continue

            logger.info("→ 导入 %s ...", table_name)
            n = import_one_table(
                src_engine, dst_session, table_name, model_cls, dry_run=args.dry_run
            )
            logger.info("  %s 完成：%d 行", table_name, n)
            total += n

        if not args.dry_run:
            dst_session.commit()
            logger.info("✅ 全部提交完成，总计 %d 行", total)
        else:
            logger.info("✅ Dry-run 完成，总计 %d 行（未写入）", total)
    except Exception:
        dst_session.rollback()
        raise
    finally:
        dst_session.close()
        src_engine.dispose()


if __name__ == "__main__":
    main()
