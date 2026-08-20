"""Stop retaining extracted text copies for private documents.

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-15
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 原文件仍在 owner 私有对象存储中；只删除关系库里的冗余正文副本。
    op.execute(
        sa.text(
            "UPDATE private_documents "
            "SET extracted_text = '' "
            "WHERE extracted_text != ''"
        )
    )


def downgrade() -> None:
    # 隐私清理不可逆，且不能从对象存储绕过 owner 校验回填数据库。
    pass
