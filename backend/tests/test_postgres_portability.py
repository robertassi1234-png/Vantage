"""The SQL has to run on Postgres, which nothing here can reach.

These do not need a server: SQLAlchemy will compile a statement against the
Postgres dialect, and psycopg will parse a connection string, which is enough
to catch the SQLite-only syntax and the URL formats that would otherwise only
fail on deploy.
"""

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.dialects import postgresql

from app import db
from app.config import settings
from app.engine import get_engine, is_postgres, normalise_url, reset_engine


class TestConnectionStrings:
    @pytest.mark.parametrize(
        "given",
        [
            # What Neon, Supabase and Render actually print.
            "postgres://user:pw@host/dbname",
            "postgresql://user:pw@host/dbname",
        ],
    )
    def test_a_pasted_url_is_rewritten_to_a_driver_sqlalchemy_2_accepts(self, given):
        assert normalise_url(given) == "postgresql+psycopg://user:pw@host/dbname"

    def test_an_explicit_driver_is_left_alone(self):
        url = "postgresql+psycopg://user:pw@host/db"
        assert normalise_url(url) == url

    def test_sqlite_is_left_alone(self):
        assert normalise_url("sqlite:///vantage.db") == "sqlite:///vantage.db"

    def test_a_password_with_a_colon_survives_rewriting(self):
        """Only the scheme is replaced, so credentials are never mangled."""
        assert normalise_url("postgres://u:p:w@host/db").endswith("//u:p:w@host/db")

    def test_postgres_is_detected_from_the_url(self, monkeypatch):
        monkeypatch.setattr(settings, "database_url", "postgres://u:p@h/d")
        assert is_postgres() is True

    def test_an_engine_is_built_without_the_sqlite_only_flag(self, monkeypatch):
        """check_same_thread is SQLite-only; passing it to psycopg would fail."""
        monkeypatch.setattr(settings, "database_url", "postgresql://u:p@localhost/d")
        reset_engine()
        try:
            engine = get_engine()  # does not connect
            assert engine.dialect.name == "postgresql"
            assert engine.pool._pre_ping is True
        finally:
            reset_engine()


class TestSchemaCompiles:
    """SQLite tolerates syntax Postgres rejects; compiling catches it here."""

    @pytest.mark.parametrize("statement", db.TABLES + db.INDEXES)
    def test_every_schema_statement_compiles_for_postgres(self, statement):
        compiled = str(text(statement).compile(dialect=postgresql.dialect()))
        assert "AUTOINCREMENT" not in compiled.upper()

    @pytest.mark.parametrize(
        "statement",
        [
            "INSERT INTO watchlist (owner_id, list_name, ticker, added_at) "
            "VALUES (:o, :l, :t, :a) ON CONFLICT DO NOTHING",
            "INSERT INTO fundamentals_cache (ticker, data_json, fetched_at) "
            "VALUES (:t, :d, :f) ON CONFLICT (ticker) DO UPDATE "
            "SET data_json = excluded.data_json",
            "UPDATE watchlist SET owner_id = 'space:' || space_id",
            "SELECT DISTINCT u.id, u.email FROM users u "
            "JOIN alerts a ON a.owner_id = 'user:' || u.id WHERE a.triggered_at IS NULL",
        ],
    )
    def test_the_queries_that_differ_between_engines_compile(self, statement):
        assert str(text(statement).compile(dialect=postgresql.dialect()))

    def test_no_sqlite_only_syntax_anywhere_in_the_schema(self):
        combined = " ".join(db.TABLES + db.INDEXES).upper()
        for sqlite_only in ("AUTOINCREMENT", "PRAGMA", "WITHOUT ROWID"):
            assert sqlite_only not in combined


class TestDialectBranches:
    def test_column_lookup_uses_information_schema_on_postgres(self, monkeypatch):
        """PRAGMA does not exist on Postgres, so the branch has to flip."""
        monkeypatch.setattr("app.db.is_postgres", lambda: True)
        seen = []

        class FakeConn:
            def execute(self, statement, params=None):
                seen.append(str(statement))
                return _Empty()

        class _Empty:
            def mappings(self):
                return []

        db._table_columns(FakeConn(), "watchlist")
        assert "information_schema" in seen[0]
        assert "PRAGMA" not in seen[0]


class TestPsycopgIsInstalled:
    def test_the_driver_is_available(self):
        """Deploying without it fails at boot, long after the tests passed."""
        import psycopg  # noqa: F401

    def test_the_dialect_can_be_loaded(self):
        engine = create_engine("postgresql+psycopg://u:p@localhost/d")
        assert engine.dialect.driver == "psycopg"
