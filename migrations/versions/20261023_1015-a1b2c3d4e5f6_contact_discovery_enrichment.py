"""contact_discovery_enrichment

Revision ID: a1b2c3d4e5f6
Revises: 2033895bcbc7
Create Date: 2026-10-23 10:15:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: str | None = "2033895bcbc7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("people", sa.Column("normalized_name", sa.String(length=255), nullable=True))
    op.add_column("people", sa.Column("department", sa.String(length=255), nullable=True))
    op.add_column("people", sa.Column("seniority", sa.String(length=64), nullable=True))
    op.add_column("people", sa.Column("public_phone", sa.String(length=64), nullable=True))
    op.add_column(
        "people",
        sa.Column(
            "discovery_status",
            sa.String(length=32),
            nullable=False,
            server_default="discovered",
        ),
    )
    op.add_column(
        "people",
        sa.Column(
            "email_status",
            sa.String(length=32),
            nullable=False,
            server_default="unknown",
        ),
    )
    op.add_column(
        "people",
        sa.Column(
            "profile_status",
            sa.String(length=32),
            nullable=False,
            server_default="unknown",
        ),
    )
    op.add_column("people", sa.Column("quality_score", sa.Float(), nullable=True))
    op.add_column(
        "people",
        sa.Column(
            "fields_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column("people", sa.Column("notes", sa.Text(), nullable=True))
    op.add_column(
        "people",
        sa.Column("last_researched_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "people", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.execute(
        "UPDATE people SET normalized_name = lower(regexp_replace(name, '[^a-zA-Z0-9]+', ' ', 'g'))"
    )
    op.execute("UPDATE people SET normalized_name = lower(name) WHERE normalized_name IS NULL OR normalized_name = ''")
    op.alter_column("people", "normalized_name", nullable=False)
    op.create_index(op.f("ix_people_normalized_name"), "people", ["normalized_name"], unique=False)
    op.create_index(op.f("ix_people_discovery_status"), "people", ["discovery_status"], unique=False)

    op.create_table(
        "company_contact_channels",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("company_id", sa.UUID(), nullable=False),
        sa.Column("channel_type", sa.String(length=32), nullable=False),
        sa.Column("value", sa.String(length=320), nullable=False),
        sa.Column("label", sa.String(length=64), nullable=True),
        sa.Column("source_url", sa.String(length=2048), nullable=True),
        sa.Column("source_snapshot_id", sa.UUID(), nullable=True),
        sa.Column("is_generic", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            name=op.f("fk_company_contact_channels_company_id_companies"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_snapshot_id"],
            ["source_snapshots.id"],
            name=op.f("fk_company_contact_channels_source_snapshot_id_source_snapshots"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_company_contact_channels")),
    )
    op.create_index(
        op.f("ix_company_contact_channels_company_id"),
        "company_contact_channels",
        ["company_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_company_contact_channels_source_snapshot_id"),
        "company_contact_channels",
        ["source_snapshot_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_company_contact_channels_source_snapshot_id"),
        table_name="company_contact_channels",
    )
    op.drop_index(
        op.f("ix_company_contact_channels_company_id"),
        table_name="company_contact_channels",
    )
    op.drop_table("company_contact_channels")
    op.drop_index(op.f("ix_people_discovery_status"), table_name="people")
    op.drop_index(op.f("ix_people_normalized_name"), table_name="people")
    op.drop_column("people", "archived_at")
    op.drop_column("people", "last_researched_at")
    op.drop_column("people", "notes")
    op.drop_column("people", "fields_json")
    op.drop_column("people", "quality_score")
    op.drop_column("people", "profile_status")
    op.drop_column("people", "email_status")
    op.drop_column("people", "discovery_status")
    op.drop_column("people", "public_phone")
    op.drop_column("people", "seniority")
    op.drop_column("people", "department")
    op.drop_column("people", "normalized_name")
