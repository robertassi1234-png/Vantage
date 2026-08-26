import pytest

from app import db
from app.config import settings


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    """Point every test at its own throwaway SQLite file.

    `db.get_conn` reads the path from settings on each call, so overriding the
    attribute is enough to redirect the whole module.
    """
    monkeypatch.setattr(settings, "vantage_db_path", str(tmp_path / "test.db"))
    db.init_db()
    yield


@pytest.fixture(autouse=True)
def fake_api_keys(monkeypatch):
    """Keys must be non-empty or the clients short-circuit before the code under test."""
    monkeypatch.setattr(settings, "fmp_api_key", "test-key")
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
