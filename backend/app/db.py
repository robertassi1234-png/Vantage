import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from app.config import settings

SCHEMA = """
-- Watchlists are per browser ("space"); everything else stays global on
-- purpose. Prices and fundamentals are the same numbers for everyone, so a
-- shared cache means a second visitor costs no extra API calls.
CREATE TABLE IF NOT EXISTS watchlist (
    space_id TEXT NOT NULL DEFAULT 'default',
    list_name TEXT NOT NULL DEFAULT 'watch',
    ticker TEXT NOT NULL,
    added_at TEXT NOT NULL,
    note TEXT,
    PRIMARY KEY (space_id, list_name, ticker)
);

CREATE TABLE IF NOT EXISTS fundamentals_cache (
    ticker TEXT PRIMARY KEY,
    data_json TEXT NOT NULL,
    fetched_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS market_cache (
    cache_key TEXT PRIMARY KEY,
    data_json TEXT NOT NULL,
    fetched_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS fed_statements (
    id TEXT PRIMARY KEY,
    date TEXT NOT NULL,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    raw_text TEXT NOT NULL,
    summary TEXT,
    sentiment TEXT,
    key_takeaways TEXT,
    fetched_at TEXT NOT NULL
);
"""


@contextmanager
def get_conn():
    conn = sqlite3.connect(settings.vantage_db_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


DEFAULT_SPACE = "default"

# The watchlist is for following prices; the comparison list is for studying
# fundamentals side by side. Keeping them apart means adding something to
# glance at doesn't clutter the table you're analysing.
WATCH_LIST = "watch"
COMPARE_LIST = "compare"
LIST_NAMES = (WATCH_LIST, COMPARE_LIST)


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        _migrate_watchlist_to_spaces(conn)


def _migrate_watchlist_to_spaces(conn) -> None:
    """Bring a pre-spaces watchlist table up to the current shape.

    CREATE TABLE IF NOT EXISTS leaves an existing table untouched, so a
    database created before watchlists were scoped keeps the old columns.
    Existing rows belong to whoever was using the app, so they land in the
    default space rather than being dropped.
    """
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(watchlist)")}
    if not columns:
        return

    if "space_id" not in columns:
        conn.execute(
            f"ALTER TABLE watchlist ADD COLUMN space_id TEXT NOT NULL DEFAULT '{DEFAULT_SPACE}'"
        )
    if "note" not in columns:
        conn.execute("ALTER TABLE watchlist ADD COLUMN note TEXT")

    if "list_name" not in columns:
        # The table has to be rebuilt rather than altered: the primary key was
        # (space_id, ticker), and ALTER TABLE ADD COLUMN cannot widen a primary
        # key in SQLite. Adding the column alone would leave the old key in
        # place and silently refuse to let a ticker exist in both lists.
        conn.execute("ALTER TABLE watchlist RENAME TO watchlist_pre_lists")
        conn.execute(
            """
            CREATE TABLE watchlist (
                space_id TEXT NOT NULL DEFAULT 'default',
                list_name TEXT NOT NULL DEFAULT 'watch',
                ticker TEXT NOT NULL,
                added_at TEXT NOT NULL,
                note TEXT,
                PRIMARY KEY (space_id, list_name, ticker)
            )
            """
        )
        # Whatever was saved before the split was serving both purposes.
        for list_name in LIST_NAMES:
            conn.execute(
                """
                INSERT OR IGNORE INTO watchlist (space_id, list_name, ticker, added_at, note)
                SELECT space_id, ?, ticker, added_at, note FROM watchlist_pre_lists
                """,
                (list_name,),
            )
        conn.execute("DROP TABLE watchlist_pre_lists")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# --- watchlist ---

def get_watchlist(space_id: str = DEFAULT_SPACE, list_name: str = WATCH_LIST) -> list[str]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT ticker FROM watchlist WHERE space_id = ? AND list_name = ? ORDER BY added_at",
            (space_id, list_name),
        ).fetchall()
        return [r["ticker"] for r in rows]


def get_watchlist_entries(
    space_id: str = DEFAULT_SPACE, list_name: str = WATCH_LIST
) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT ticker, added_at, note FROM watchlist "
            "WHERE space_id = ? AND list_name = ? ORDER BY added_at",
            (space_id, list_name),
        ).fetchall()
        return [dict(r) for r in rows]


def add_to_watchlist(
    ticker: str, space_id: str = DEFAULT_SPACE, list_name: str = WATCH_LIST
) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO watchlist (space_id, list_name, ticker, added_at) "
            "VALUES (?, ?, ?, ?)",
            (space_id, list_name, ticker, now_iso()),
        )


def set_watchlist_note(
    ticker: str,
    note: str | None,
    space_id: str = DEFAULT_SPACE,
    list_name: str = WATCH_LIST,
) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE watchlist SET note = ? WHERE space_id = ? AND list_name = ? AND ticker = ?",
            (note or None, space_id, list_name, ticker),
        )


def remove_from_watchlist(
    ticker: str, space_id: str = DEFAULT_SPACE, list_name: str = WATCH_LIST
) -> None:
    with get_conn() as conn:
        conn.execute(
            "DELETE FROM watchlist WHERE space_id = ? AND list_name = ? AND ticker = ?",
            (space_id, list_name, ticker),
        )
        # The fundamentals cache is deliberately global: the numbers are the
        # same for everyone, so one person removing a ticker must not throw
        # away a cached copy another space is still using.


# --- fundamentals cache ---

def get_cached_fundamentals(ticker: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT data_json, fetched_at FROM fundamentals_cache WHERE ticker = ?",
            (ticker,),
        ).fetchone()
        if not row:
            return None
        return {"data": json.loads(row["data_json"]), "fetched_at": row["fetched_at"]}


def set_cached_fundamentals(ticker: str, data: dict) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO fundamentals_cache (ticker, data_json, fetched_at)
            VALUES (?, ?, ?)
            ON CONFLICT(ticker) DO UPDATE SET data_json = excluded.data_json, fetched_at = excluded.fetched_at
            """,
            (ticker, json.dumps(data), now_iso()),
        )


# --- generic market cache ---

def get_market_cache(key: str, max_age_seconds: int):
    """Return cached payload for `key`, or None if missing or older than the TTL.

    The FMP free tier allows 250 calls/day, so quotes and price history are
    served from here unless they've gone stale.
    """
    with get_conn() as conn:
        row = conn.execute(
            "SELECT data_json, fetched_at FROM market_cache WHERE cache_key = ?", (key,)
        ).fetchone()
        if not row:
            return None
        fetched = datetime.fromisoformat(row["fetched_at"])
        if (datetime.now(timezone.utc) - fetched).total_seconds() > max_age_seconds:
            return None
        return json.loads(row["data_json"])


def set_market_cache(key: str, data) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO market_cache (cache_key, data_json, fetched_at)
            VALUES (?, ?, ?)
            ON CONFLICT(cache_key) DO UPDATE SET
                data_json = excluded.data_json,
                fetched_at = excluded.fetched_at
            """,
            (key, json.dumps(data), now_iso()),
        )


# --- fed statements ---

def get_fed_timeline(limit: int = 20) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, date, title, url, summary, sentiment, key_takeaways, fetched_at "
            "FROM fed_statements ORDER BY date DESC LIMIT ?",
            (limit,),
        ).fetchall()
        results = []
        for r in rows:
            d = dict(r)
            d["key_takeaways"] = json.loads(d["key_takeaways"]) if d["key_takeaways"] else []
            results.append(d)
        return results


def get_latest_fed_statement_id() -> str | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id FROM fed_statements ORDER BY date DESC LIMIT 1"
        ).fetchone()
        return row["id"] if row else None


def statement_exists(statement_id: str) -> bool:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM fed_statements WHERE id = ?", (statement_id,)
        ).fetchone()
        return row is not None


def save_fed_statement(
    statement_id: str,
    date: str,
    title: str,
    url: str,
    raw_text: str,
    summary: str,
    sentiment: str,
    key_takeaways: list[str],
) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO fed_statements (id, date, title, url, raw_text, summary, sentiment, key_takeaways, fetched_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                summary = excluded.summary,
                sentiment = excluded.sentiment,
                key_takeaways = excluded.key_takeaways,
                fetched_at = excluded.fetched_at
            """,
            (
                statement_id,
                date,
                title,
                url,
                raw_text,
                summary,
                sentiment,
                json.dumps(key_takeaways),
                now_iso(),
            ),
        )
