import os

import pytest

from app import db, engine, provider_health
from app.config import settings

# Everything here has to run on Postgres too, and SQLite quietly accepts SQL
# that Postgres rejects. Point this at a database and the whole suite runs
# against it:
#
#   VANTAGE_TEST_DATABASE_URL=postgresql://user@localhost/vantage_test pytest
#
# Unset, tests use a throwaway SQLite file and need no server.
POSTGRES_URL = os.environ.get("VANTAGE_TEST_DATABASE_URL")


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    """Give every test its own empty database.

    The engine is cached per process, so it is dropped on both sides: once so
    this case builds an engine for its own database, and again so the next
    case is not handed this one.
    """
    monkeypatch.setattr(
        settings,
        "database_url",
        POSTGRES_URL or f"sqlite:///{tmp_path / 'test.db'}",
    )
    engine.reset_engine()

    if POSTGRES_URL:
        # A shared server has no per-test file to throw away, so the schema is
        # rebuilt instead. Dropping it also clears tables a migration test left
        # in an older shape.
        with engine.connect() as conn:
            conn.execute(engine.q("DROP SCHEMA public CASCADE"))
            conn.execute(engine.q("CREATE SCHEMA public"))

    db.init_db()
    yield
    engine.reset_engine()


@pytest.fixture(autouse=True)
def fresh_provider_health():
    """Forget provider cooldowns between tests.

    A rate-limit recorded by one case would otherwise bench that provider for
    every case after it, producing failures nowhere near their cause.
    """
    provider_health.reset()
    yield
    provider_health.reset()


@pytest.fixture(autouse=True)
def fake_api_keys(monkeypatch):
    """Keys must be non-empty or the clients short-circuit before the code under test."""
    monkeypatch.setattr(settings, "fmp_api_key", "test-key")
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
