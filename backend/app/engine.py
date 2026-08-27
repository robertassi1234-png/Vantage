"""Database engine, shared by SQLite (local) and Postgres (deployed).

One `DATABASE_URL` decides which. Everything above this module writes portable
SQL and never has to care, which is what lets the app run with no signups
locally and on managed Postgres in production.
"""

from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from app.config import settings

_engine: Engine | None = None


def normalise_url(url: str) -> str:
    """Accept the connection strings hosting providers actually hand out.

    Neon, Supabase and Render all print `postgres://...`, which SQLAlchemy 2
    no longer recognises, and several append options psycopg rejects. Fixing
    it here means a copy-pasted string works rather than erroring on boot.
    """
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg://", 1)
    elif url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        url = normalise_url(settings.database_url)
        if url.startswith("sqlite"):
            # check_same_thread is a SQLite-only guard that FastAPI's
            # threadpool trips over.
            _engine = create_engine(url, connect_args={"check_same_thread": False})
        else:
            # Managed Postgres closes idle connections; pre-ping avoids handing
            # out a dead one after the app has been asleep.
            _engine = create_engine(url, pool_pre_ping=True, pool_recycle=300)
    return _engine


def reset_engine() -> None:
    """Drop the cached engine. Tests point at a fresh database per case."""
    global _engine
    if _engine is not None:
        _engine.dispose()
    _engine = None


def is_postgres() -> bool:
    return not normalise_url(settings.database_url).startswith("sqlite")


@contextmanager
def connect():
    """A transactional connection. Commits on success, rolls back on error."""
    with get_engine().begin() as conn:
        yield conn


def q(sql: str):
    return text(sql)
