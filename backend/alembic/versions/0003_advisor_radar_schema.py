"""导师数据库 9 表规范扩展（entities/claims/sources 等）。

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-04

兼容 MySQL 8.x（本地开发与生产同方言）：
- UUID 统一用 String(36)，避免原生 UUID 类型方言差异
- 时间戳用 DateTime(timezone=True)，MySQL 会映射为 DATETIME
- server_default 用 sa.func.now() / sa.false() 等方言无关表达式
- 视图 advisors_public_view 用 ANSI SQL，MySQL 8.x 完全支持
- 全程 ORM 优先，仅视图创建用标准 SQL（无 MySQL 专属语法）
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    # ── 1. sources（来源元数据，最先创建，其他表外键依赖）────────────────
    op.create_table(
        "sources",
        sa.Column("source_id", sa.String(36), primary_key=True),
        sa.Column("source_class", sa.String(1), nullable=False),  # A/B/C/D/E
        sa.Column("source_type", sa.String(50)),
        sa.Column("source_title", sa.Text),
        sa.Column("public_url", sa.Text),
        sa.Column("publisher", sa.String(200)),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("page_content_sha256", sa.String(64)),
        sa.Column("snapshot_id", sa.String(100)),
        sa.Column("access_status", sa.String(30)),
        sa.Column("visibility", sa.String(20), server_default="public"),
    )
    op.create_index("ix_sources_class", "sources", ["source_class"])
    op.create_index("ix_sources_visibility", "sources", ["visibility"])

    # ── 2. entities（导师/实验室/院系/导师组实体）────────────────────────
    op.create_table(
        "entities",
        sa.Column("entity_id", sa.String(36), primary_key=True),
        sa.Column("entity_type", sa.String(20), nullable=False),  # person/advisor_group/lab/organization
        sa.Column("display_name", sa.String(200), nullable=False),
        sa.Column("name_zh", sa.String(100)),
        sa.Column("name_en", sa.String(200)),
        sa.Column("identity_status", sa.String(20), server_default="unresolved"),  # unresolved/pending_review/verified/conflicted
        sa.Column("review_status", sa.String(20), server_default="pending_review"),
        sa.Column("publication_status", sa.String(20), server_default="withheld"),  # withheld/published/rejected/withdrawn
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("verified_at", sa.DateTime(timezone=True)),
        sa.Column("next_review_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_entities_type", "entities", ["entity_type"])
    op.create_index("ix_entities_name", "entities", ["display_name"])
    op.create_index("ix_entities_status", "entities", ["identity_status", "publication_status"])

    # ── 3. entity_names（名称别名）────────────────────────────────────────
    op.create_table(
        "entity_names",
        sa.Column("name_id", sa.String(36), primary_key=True),
        sa.Column("entity_id", sa.String(36), sa.ForeignKey("entities.entity_id", ondelete="CASCADE")),
        sa.Column("name_type", sa.String(20)),  # official_zh/official_en/pinyin/abbreviation/historical
        sa.Column("name_value", sa.String(200)),
        sa.Column("claim_id", sa.String(36)),  # 引用 claims（后建，用 FK 约束时用延迟执行）
        sa.Column("is_primary", sa.Boolean, server_default=sa.false()),
    )
    op.create_index("ix_entity_names_entity", "entity_names", ["entity_id"])
    op.create_index("ix_entity_names_value", "entity_names", ["name_value"])

    # ── 4. directions（研究方向三层结构）──────────────────────────────────
    op.create_table(
        "directions",
        sa.Column("direction_id", sa.String(36), primary_key=True),
        sa.Column("level_1", sa.String(100), nullable=False),
        sa.Column("level_2", sa.String(100)),
        sa.Column("specific_topic", sa.String(500), nullable=False),
        sa.Column("application_context", sa.Text),
        sa.Column("method_or_technology", sa.Text),
        sa.Column("normalization_version", sa.String(20)),
    )
    op.create_index("ix_directions_level1", "directions", ["level_1"])
    op.create_index("ix_directions_level2", "directions", ["level_2"])
    op.create_index("ix_directions_topic", "directions", ["specific_topic"])

    # ── 5. relations（实体关系：隶属/领导/跨院系/联合）────────────────────
    op.create_table(
        "relations",
        sa.Column("relation_id", sa.String(36), primary_key=True),
        sa.Column("subject_entity_id", sa.String(36), sa.ForeignKey("entities.entity_id", ondelete="CASCADE")),
        sa.Column("relation_type", sa.String(50), nullable=False),  # affiliated_with/member_of/leads/part_of/joint_appointment_with
        sa.Column("object_entity_id", sa.String(36), sa.ForeignKey("entities.entity_id", ondelete="CASCADE")),
        sa.Column("valid_from", sa.DateTime(timezone=True)),
        sa.Column("valid_until", sa.DateTime(timezone=True)),
        sa.Column("claim_id", sa.String(36)),
        sa.Column("relation_status", sa.String(20), server_default="active"),  # active/historical/unknown
    )
    op.create_index("ix_relations_subject", "relations", ["subject_entity_id"])
    op.create_index("ix_relations_object", "relations", ["object_entity_id"])
    op.create_index("ix_relations_type", "relations", ["relation_type"])

    # ── 6. entity_directions（实体-方向关系）─────────────────────────────
    op.create_table(
        "entity_directions",
        sa.Column("entity_direction_id", sa.String(36), primary_key=True),
        sa.Column("entity_id", sa.String(36), sa.ForeignKey("entities.entity_id", ondelete="CASCADE")),
        sa.Column("direction_id", sa.String(36), sa.ForeignKey("directions.direction_id", ondelete="CASCADE")),
        sa.Column("direction_scope", sa.String(30)),  # current_official/catalog_only/historical/publication_signal_only
        sa.Column("valid_from", sa.DateTime(timezone=True)),
        sa.Column("valid_until", sa.DateTime(timezone=True)),
        sa.Column("claim_id", sa.String(36)),
    )
    op.create_index("ix_entity_directions_entity", "entity_directions", ["entity_id"])
    op.create_index("ix_entity_directions_direction", "entity_directions", ["direction_id"])
    op.create_index("ix_entity_directions_scope", "entity_directions", ["direction_scope"])

    # ── 7. catalog_links（招生目录事实关联）───────────────────────────────
    op.create_table(
        "catalog_links",
        sa.Column("catalog_link_id", sa.String(36), primary_key=True),
        sa.Column("catalog_snapshot_id", sa.String(100)),
        sa.Column("academic_year", sa.String(4)),
        sa.Column("catalog_type", sa.String(50)),  # doctoral_regular/doctoral_recommendation_exempt/master/etc.
        sa.Column("department_id", sa.String(36)),  # entities.entity_id (organization)
        sa.Column("program_id", sa.String(36)),
        sa.Column("direction_id", sa.String(36), sa.ForeignKey("directions.direction_id")),
        sa.Column("advisor_or_group_id", sa.String(36)),  # 目录标签实体
        sa.Column("resolved_entity_id", sa.String(36), sa.ForeignKey("entities.entity_id")),
        sa.Column("identity_resolution_status", sa.String(20), server_default="unresolved"),  # verified/conflicted/unresolved
        sa.Column("relation_claim_id", sa.String(36)),
    )
    op.create_index("ix_catalog_links_year", "catalog_links", ["academic_year"])
    op.create_index("ix_catalog_links_resolved", "catalog_links", ["resolved_entity_id"])
    op.create_index("ix_catalog_links_status", "catalog_links", ["identity_resolution_status"])

    # ── 8. opportunities（招聘/实习/招生机会，带时效）────────────────────
    op.create_table(
        "opportunities",
        sa.Column("opportunity_id", sa.String(36), primary_key=True),
        sa.Column("entity_id", sa.String(36), sa.ForeignKey("entities.entity_id", ondelete="CASCADE")),
        sa.Column("opportunity_type", sa.String(30)),  # phd/master/postdoc/research_assistant/internship/visiting_student/summer_research
        sa.Column("title", sa.Text),
        sa.Column("target_stage", sa.String(50)),
        sa.Column("direction_id", sa.String(36), sa.ForeignKey("directions.direction_id")),
        sa.Column("location", sa.String(200)),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("deadline_at", sa.DateTime(timezone=True)),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=False),  # 动态事实必须有
        sa.Column("opportunity_status", sa.String(30), server_default="unknown"),  # open/closed/unknown/needs_reverification/withdrawn
        sa.Column("application_channel", sa.Text),
        sa.Column("claim_id", sa.String(36)),
        sa.Column("review_status", sa.String(20), server_default="pending_review"),
        sa.Column("publication_status", sa.String(20), server_default="withheld"),
    )
    op.create_index("ix_opportunities_entity", "opportunities", ["entity_id"])
    op.create_index("ix_opportunities_status", "opportunities", ["opportunity_status", "publication_status"])
    op.create_index("ix_opportunities_valid", "opportunities", ["valid_until"])

    # ── 9. claims（字段级证据声明）────────────────────────────────────────
    op.create_table(
        "claims",
        sa.Column("claim_id", sa.String(36), primary_key=True),
        sa.Column("evidence_id", sa.String(36)),
        sa.Column("subject_type", sa.String(30)),  # entity/relation/direction/catalog_link/opportunity/entity_name
        sa.Column("subject_id", sa.String(36)),
        sa.Column("field_name", sa.String(100)),
        sa.Column("normalized_value", sa.Text),
        sa.Column("raw_text", sa.Text),
        sa.Column("source_id", sa.String(36), sa.ForeignKey("sources.source_id")),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True)),
        sa.Column("valid_until", sa.DateTime(timezone=True)),
        sa.Column("page_content_sha256", sa.String(64)),
        sa.Column("fragment_sha256", sa.String(64), nullable=False),
        sa.Column("snapshot_id", sa.String(100)),
        sa.Column("capture_method", sa.String(30)),  # crawler/manual
        sa.Column("method_version", sa.String(20)),
        sa.Column("normalization_version", sa.String(20)),
        sa.Column("verification_status", sa.String(20), server_default="unverified"),  # unverified/pending/verified/rejected
        sa.Column("conflict_status", sa.String(20), server_default="none"),  # none/open/superseded
        sa.Column("confidence", sa.Float),
        sa.Column("review_status", sa.String(20), server_default="pending_review"),
        sa.Column("publication_status", sa.String(20), server_default="withheld"),
        sa.Column("collector_role_id", sa.String(100)),
        sa.Column("batch_id", sa.String(36)),
    )
    op.create_index("ix_claims_subject", "claims", ["subject_type", "subject_id"])
    op.create_index("ix_claims_field", "claims", ["field_name"])
    op.create_index("ix_claims_source", "claims", ["source_id"])
    op.create_index("ix_claims_status", "claims", ["verification_status", "conflict_status", "publication_status"])
    op.create_index("ix_claims_batch", "claims", ["batch_id"])

    # ── 视图：advisors_public_view（只投影 publication_status='published' 的 person 实体）
    # 使用 ANSI SQL 标准语法（CREATE VIEW ... AS SELECT ...），MySQL 8.x 与其他主流方言通用
    # 视图是「发布门禁」的物化体现：任何 publication_status != 'published' 的记录都不进入此视图
    create_view_sql = """
    CREATE VIEW advisors_public_view AS
    SELECT
        e.entity_id AS advisor_id,
        e.display_name AS name,
        e.name_zh,
        e.name_en,
        e.entity_type,
        e.identity_status,
        e.publication_status,
        e.created_at,
        e.verified_at
    FROM entities e
    WHERE e.entity_type = 'person'
      AND e.publication_status = 'published';
    """
    op.execute(create_view_sql)


def downgrade() -> None:
    # 删除视图（方言兼容写法）
    op.execute("DROP VIEW IF EXISTS advisors_public_view")

    # 按外键依赖的逆序删除表
    op.drop_index("ix_claims_batch", table_name="claims")
    op.drop_index("ix_claims_status", table_name="claims")
    op.drop_index("ix_claims_source", table_name="claims")
    op.drop_index("ix_claims_field", table_name="claims")
    op.drop_index("ix_claims_subject", table_name="claims")
    op.drop_table("claims")

    op.drop_index("ix_opportunities_valid", table_name="opportunities")
    op.drop_index("ix_opportunities_status", table_name="opportunities")
    op.drop_index("ix_opportunities_entity", table_name="opportunities")
    op.drop_table("opportunities")

    op.drop_index("ix_catalog_links_status", table_name="catalog_links")
    op.drop_index("ix_catalog_links_resolved", table_name="catalog_links")
    op.drop_index("ix_catalog_links_year", table_name="catalog_links")
    op.drop_table("catalog_links")

    op.drop_index("ix_entity_directions_scope", table_name="entity_directions")
    op.drop_index("ix_entity_directions_direction", table_name="entity_directions")
    op.drop_index("ix_entity_directions_entity", table_name="entity_directions")
    op.drop_table("entity_directions")

    op.drop_index("ix_relations_type", table_name="relations")
    op.drop_index("ix_relations_object", table_name="relations")
    op.drop_index("ix_relations_subject", table_name="relations")
    op.drop_table("relations")

    op.drop_index("ix_directions_topic", table_name="directions")
    op.drop_index("ix_directions_level2", table_name="directions")
    op.drop_index("ix_directions_level1", table_name="directions")
    op.drop_table("directions")

    op.drop_index("ix_entity_names_value", table_name="entity_names")
    op.drop_index("ix_entity_names_entity", table_name="entity_names")
    op.drop_table("entity_names")

    op.drop_index("ix_entities_status", table_name="entities")
    op.drop_index("ix_entities_name", table_name="entities")
    op.drop_index("ix_entities_type", table_name="entities")
    op.drop_table("entities")

    op.drop_index("ix_sources_visibility", table_name="sources")
    op.drop_index("ix_sources_class", table_name="sources")
    op.drop_table("sources")
