"""discovery_leads

Revision ID: c3d4e5f6a7b8
Revises: a1b2c3d4e5f6
Create Date: 2026-10-23 10:45:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "c3d4e5f6a7b8"
down_revision: str | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "discovery_leads",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("source_kind", sa.String(length=64), nullable=False),
        sa.Column("source_name", sa.String(length=128), nullable=False),
        sa.Column("source_category", sa.String(length=32), nullable=False),
        sa.Column("listing_id", sa.String(length=512), nullable=False),
        sa.Column("canonical_url", sa.String(length=2048), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("excerpt", sa.Text(), nullable=True),
        sa.Column("lead_kind", sa.String(length=32), nullable=False),
        sa.Column("intent_class", sa.String(length=32), nullable=False),
        sa.Column("relevance_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column(
            "score_reasons_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "matched_filters_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "detected_requirements_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "buying_intent_indicators_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("location_text", sa.String(length=255), nullable=True),
        sa.Column("budget_text", sa.String(length=128), nullable=True),
        sa.Column("contract_type", sa.String(length=64), nullable=True),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="new",
        ),
        sa.Column("operator_notes", sa.Text(), nullable=True),
        sa.Column("discovered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("company_id", sa.UUID(), nullable=True),
        sa.Column("opportunity_id", sa.UUID(), nullable=True),
        sa.Column(
            "raw_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            name=op.f("fk_discovery_leads_company_id_companies"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["opportunity_id"],
            ["opportunities.id"],
            name=op.f("fk_discovery_leads_opportunity_id_opportunities"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_discovery_leads")),
        sa.UniqueConstraint(
            "source_kind",
            "listing_id",
            name="uq_discovery_leads_source_listing",
        ),
    )
    op.create_index(
        op.f("ix_discovery_leads_source_kind"), "discovery_leads", ["source_kind"]
    )
    op.create_index(
        op.f("ix_discovery_leads_source_category"),
        "discovery_leads",
        ["source_category"],
    )
    op.create_index(
        op.f("ix_discovery_leads_canonical_url"),
        "discovery_leads",
        ["canonical_url"],
    )
    op.create_index(op.f("ix_discovery_leads_lead_kind"), "discovery_leads", ["lead_kind"])
    op.create_index(
        op.f("ix_discovery_leads_intent_class"), "discovery_leads", ["intent_class"]
    )
    op.create_index(op.f("ix_discovery_leads_status"), "discovery_leads", ["status"])
    op.create_index(
        op.f("ix_discovery_leads_company_id"), "discovery_leads", ["company_id"]
    )
    op.create_index(
        op.f("ix_discovery_leads_opportunity_id"),
        "discovery_leads",
        ["opportunity_id"],
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_discovery_leads_opportunity_id"), table_name="discovery_leads")
    op.drop_index(op.f("ix_discovery_leads_company_id"), table_name="discovery_leads")
    op.drop_index(op.f("ix_discovery_leads_status"), table_name="discovery_leads")
    op.drop_index(op.f("ix_discovery_leads_intent_class"), table_name="discovery_leads")
    op.drop_index(op.f("ix_discovery_leads_lead_kind"), table_name="discovery_leads")
    op.drop_index(op.f("ix_discovery_leads_canonical_url"), table_name="discovery_leads")
    op.drop_index(op.f("ix_discovery_leads_source_category"), table_name="discovery_leads")
    op.drop_index(op.f("ix_discovery_leads_source_kind"), table_name="discovery_leads")
    op.drop_table("discovery_leads")
