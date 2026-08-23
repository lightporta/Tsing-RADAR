"""投递与删除共享的文档锁序协议。"""

from __future__ import annotations

from sqlalchemy import select, text
from sqlalchemy.orm import Session
from sqlalchemy.sql import Select

from app.models.private_document import PrivateDocument


def private_document_lock_statement(document_id: str) -> Select:
    """Single row-lock statement shared by application creation and deletion."""

    return (
        select(PrivateDocument)
        .where(PrivateDocument.document_id == document_id)
        .with_for_update()
    )


def lock_private_document(
    db: Session,
    document_id: str,
) -> PrivateDocument | None:
    """先锁文档行，再由调用方在新语句中检查引用或业务状态。

    PostgreSQL 的 ``FOR UPDATE`` 在等待完成后锁定最新行版本；调用方随后
    发出的 Application 查询使用 READ COMMITTED 的新语句快照。SQLite 没有
    行锁，因此在任何业务读取前使用 ``BEGIN IMMEDIATE`` 获取写锁，从而让
    投递和删除在同一协议下串行化。
    """

    if db.get_bind().dialect.name == "sqlite":
        if db.in_transaction():
            db.rollback()
        db.execute(text("BEGIN IMMEDIATE"))
        return db.get(PrivateDocument, document_id)
    return db.execute(
        private_document_lock_statement(document_id)
    ).scalar_one_or_none()
