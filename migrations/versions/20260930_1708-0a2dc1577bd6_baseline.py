"""baseline

Intentionally empty. This revision exists only to anchor the migration chain and create
the alembic_version table, proving the migration pipeline works before any schema depends
on it.

Extensions and tables are added by the phase that needs them, per the spec's rule of
adding infrastructure only once a concrete feature requires it (section 12.1). Phase 2
brings the first real tables, Company and SourceSnapshot.

Revision ID: 0a2dc1577bd6
Revises:
Create Date: 2026-09-30 17:08:37.514506
"""

revision: str = "0a2dc1577bd6"
down_revision: str | None = None
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
