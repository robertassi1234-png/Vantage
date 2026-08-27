import pytest

from app import db, engine
from app.config import settings


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    """Point every test at its own throwaway SQLite file.

    The engine is cached per process, so it has to be dropped on both sides of
    the test: once so this case builds an engine for its own file, and again so
    the next case isn't handed this one.
    """
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path / 'test.db'}")
    engine.reset_engine()
    db.init_db()
    yield
    engine.reset_engine()


@pytest.fixture(autouse=True)
def fake_api_keys(monkeypatch):
    """Keys must be non-empty or the clients short-circuit before the code under test."""
    monkeypatch.setattr(settings, "fmp_api_key", "test-key")
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
