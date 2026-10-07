"""Test fixtures.

Tests run against a separate database (TEST_POSTGRES_DB) created and dropped per session,
so a test run can never touch real prospect data. Schema comes from Base.metadata rather
than by replaying migrations: that keeps the suite fast, and migration correctness is
verified separately by applying them to the real database.
"""

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.db.base import Base
from app.db.session import get_session
from app.main import app

settings = get_settings()


@pytest.fixture(autouse=True)
def _disable_llm_unless_injected(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    """Phase 2 tests create snapshots without a gateway; keep them offline by default.

    Phase 3 tests that need extraction pass an explicit FakeGateway, which bypasses the
    llm_enabled gate when provided.
    """
    monkeypatch.setenv("LLM_ENABLED", "false")
    monkeypatch.setenv("SCHEDULER_ENABLED", "false")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(scope="session")
def test_engine() -> Generator[Engine, None, None]:
    # CREATE DATABASE cannot run inside a transaction, hence the autocommit connection.
    admin = create_engine(settings.database_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{settings.test_postgres_db}"'))
        conn.execute(text(f'CREATE DATABASE "{settings.test_postgres_db}"'))
    admin.dispose()

    engine = create_engine(settings.test_database_url)
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()

    admin = create_engine(settings.database_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{settings.test_postgres_db}"'))
    admin.dispose()


@pytest.fixture
def session(test_engine: Engine) -> Generator[Session, None, None]:
    """A session wrapped in a transaction that is always rolled back, so tests cannot
    leak state into each other regardless of what they commit."""
    connection = test_engine.connect()
    transaction = connection.begin()
    factory = sessionmaker(bind=connection, autoflush=False, expire_on_commit=False)
    db = factory()
    try:
        yield db
    finally:
        db.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def client(session: Session) -> Generator[TestClient, None, None]:
    def override() -> Generator[Session, None, None]:
        yield session

    app.dependency_overrides[get_session] = override
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
