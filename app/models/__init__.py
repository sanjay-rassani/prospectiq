"""Model registry.

Every model must be imported here. Alembic's autogenerate compares the live database
against Base.metadata, and a model that is never imported is invisible to it -- which
shows up as a migration that silently drops nothing and creates nothing.

Phase 2 adds Company and SourceSnapshot; the remaining entities from spec section 13
arrive with the phase that uses them.
"""

from app.db.base import Base, TimestampMixin

__all__ = ["Base", "TimestampMixin"]
