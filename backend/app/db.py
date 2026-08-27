"""Storage layer.

SQL here is deliberately portable between SQLite and Postgres: no AUTOINCREMENT,
no RETURNING, and upserts written as ON CONFLICT ... DO UPDATE, which both
understand. `owner_id` identifies whoever the rows belong to -- a signed-in
user's id, or an anonymous browser's space id -- so one set of queries serves
both without a second code path.
"""

import json
from datetime import datetime, timezone

from app.engine import connect, is_postgres, q

DEFAULT_SPACE = "default"

# The watchlist is for following prices; the comparison list is for studying
# fundamentals side by side. Keeping them apart means adding something to
# glance at doesn't clutter the table you're analysing.
WATCH_LIST = "watch"
COMPARE_LIST = "compare"
LIST_NAMES = (WATCH_LIST, COMPARE_LIST)

# Rows belong to an owner: "user:<id>" once signed in, "space:<id>" while
# anonymous. Signing in rewrites the owner rather than copying rows. Named
# because the migration rebuilds this table and needs the same definition.
WATCHLIST_SCHEMA = """
    CREATE TABLE IF NOT EXISTS watchlist (
        owner_id TEXT NOT NULL,
        list_name TEXT NOT NULL,
        ticker TEXT NOT NULL,
        added_at TEXT NOT NULL,
        note TEXT,
        PRIMARY KEY (owner_id, list_name, ticker)
    )
"""

TABLES = [
    WATCHLIST_SCHEMA,
    """
    CREATE TABLE IF NOT EXISTS alerts (
        id TEXT PRIMARY KEY,
        owner_id TEXT NOT NULL,
        ticker TEXT NOT NULL,
        direction TEXT NOT NULL,
        threshold DOUBLE PRECISION NOT NULL,
        note TEXT,
        created_at TEXT NOT NULL,
        triggered_at TEXT,
        triggered_price DOUBLE PRECISION,
        acknowledged INTEGER NOT NULL DEFAULT 0,
        notified_at TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS users (
        id TEXT PRIMARY KEY,
        email TEXT NOT NULL UNIQUE,
        created_at TEXT NOT NULL,
        last_login_at TEXT
    )
    """,
    # Only the hash is stored: a leaked database must not yield working
    # sign-in links.
    """
    CREATE TABLE IF NOT EXISTS login_tokens (
        token_hash TEXT PRIMARY KEY,
        email TEXT NOT NULL,
        created_at TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        used_at TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sessions (
        token_hash TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        created_at TEXT NOT NULL,
        expires_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS fundamentals_cache (
        ticker TEXT PRIMARY KEY,
        data_json TEXT NOT NULL,
        fetched_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS market_cache (
        cache_key TEXT PRIMARY KEY,
        data_json TEXT NOT NULL,
        fetched_at TEXT NOT NULL
    )
    """,
    """
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
    )
    """,
]

INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_watchlist_owner ON watchlist (owner_id, list_name)",
    "CREATE INDEX IF NOT EXISTS idx_alerts_owner ON alerts (owner_id)",
    "CREATE INDEX IF NOT EXISTS idx_alerts_pending ON alerts (triggered_at)",
    "CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions (user_id)",
]


def space_owner(space_id: str) -> str:
    """Owner key for an anonymous browser."""
    return f"space:{space_id}"


#: The owner a browser that has never been given a space id resolves to.
DEFAULT_OWNER = f"space:{DEFAULT_SPACE}"


def user_owner(user_id: str) -> str:
    """Owner key for a signed-in account."""
    return f"user:{user_id}"


def init_db() -> None:
    with connect() as conn:
        for statement in TABLES:
            conn.execute(q(statement))
        # Migrate before indexing: the indexes name owner_id, which a table
        # written by an older version does not have until it is rewritten.
        _migrate_legacy_columns(conn)
        for statement in INDEXES:
            conn.execute(q(statement))


def _migrate_legacy_columns(conn) -> None:
    """Carry a database written by an earlier version forward.

    `CREATE TABLE IF NOT EXISTS` above is a no-op on a table that already
    exists, so an upgraded deployment still has the old columns and every
    query on `owner_id` would fail. Three shapes have shipped:

      1. `watchlist(ticker, added_at)`             -- one global list
      2. `... (space_id, ticker, ...)`             -- per browser
      3. `... (space_id, list_name, ticker, ...)`  -- watch and compare split

    Each is rewritten into the owner form rather than dropped, so nobody
    upgrades into an empty watchlist.
    """
    _migrate_watchlist(conn)
    _migrate_alerts(conn)


def _migrate_watchlist(conn) -> None:
    columns = _table_columns(conn, "watchlist")
    if not columns or "owner_id" in columns:
        return

    # The primary key changes, and SQLite cannot widen one in place, so the
    # table is rebuilt and copied rather than altered.
    owner = "'space:' || space_id" if "space_id" in columns else f"'{DEFAULT_OWNER}'"
    note = "note" if "note" in columns else "NULL"

    conn.execute(q("ALTER TABLE watchlist RENAME TO watchlist_legacy"))
    conn.execute(q(WATCHLIST_SCHEMA))

    if "list_name" in columns:
        conn.execute(
            q(
                f"INSERT INTO watchlist (owner_id, list_name, ticker, added_at, note) "
                f"SELECT {owner}, list_name, ticker, added_at, {note} FROM watchlist_legacy"
            )
        )
    else:
        # Before the split there was one list doing both jobs, so it becomes
        # both -- dropping it from either would look like data loss.
        for list_name in LIST_NAMES:
            conn.execute(
                q(
                    f"INSERT INTO watchlist (owner_id, list_name, ticker, added_at, note) "
                    f"SELECT {owner}, :l, ticker, added_at, {note} FROM watchlist_legacy"
                ),
                {"l": list_name},
            )

    conn.execute(q("DROP TABLE watchlist_legacy"))


def _migrate_alerts(conn) -> None:
    columns = _table_columns(conn, "alerts")
    if not columns:
        return

    # Alerts key on their own id, so the owner column can be added in place.
    if "owner_id" not in columns:
        conn.execute(q("ALTER TABLE alerts ADD COLUMN owner_id TEXT"))
        source = "'space:' || space_id" if "space_id" in columns else f"'{DEFAULT_OWNER}'"
        conn.execute(q(f"UPDATE alerts SET owner_id = {source}"))

    if "notified_at" not in columns:
        conn.execute(q("ALTER TABLE alerts ADD COLUMN notified_at TEXT"))


def _table_columns(conn, table: str) -> set[str]:
    if is_postgres():
        rows = conn.execute(
            q(
                "SELECT column_name AS name FROM information_schema.columns "
                "WHERE table_name = :t AND table_schema = current_schema()"
            ),
            {"t": table},
        ).mappings()
    else:
        rows = conn.execute(q(f"PRAGMA table_info({table})")).mappings()
    return {r["name"] for r in rows}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# --- watchlists ---

def get_watchlist(owner_id: str, list_name: str = WATCH_LIST) -> list[str]:
    with connect() as conn:
        rows = conn.execute(
            q(
                "SELECT ticker FROM watchlist WHERE owner_id = :o AND list_name = :l "
                "ORDER BY added_at"
            ),
            {"o": owner_id, "l": list_name},
        ).mappings()
        return [r["ticker"] for r in rows]


def get_watchlist_entries(owner_id: str, list_name: str = WATCH_LIST) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            q(
                "SELECT ticker, added_at, note FROM watchlist "
                "WHERE owner_id = :o AND list_name = :l ORDER BY added_at"
            ),
            {"o": owner_id, "l": list_name},
        ).mappings()
        return [dict(r) for r in rows]


def add_to_watchlist(ticker: str, owner_id: str, list_name: str = WATCH_LIST) -> None:
    with connect() as conn:
        conn.execute(
            q(
                "INSERT INTO watchlist (owner_id, list_name, ticker, added_at) "
                "VALUES (:o, :l, :t, :a) ON CONFLICT DO NOTHING"
            ),
            {"o": owner_id, "l": list_name, "t": ticker, "a": now_iso()},
        )


def set_watchlist_note(
    ticker: str, note: str | None, owner_id: str, list_name: str = WATCH_LIST
) -> None:
    with connect() as conn:
        conn.execute(
            q(
                "UPDATE watchlist SET note = :n "
                "WHERE owner_id = :o AND list_name = :l AND ticker = :t"
            ),
            {"n": note or None, "o": owner_id, "l": list_name, "t": ticker},
        )


def remove_from_watchlist(ticker: str, owner_id: str, list_name: str = WATCH_LIST) -> None:
    with connect() as conn:
        conn.execute(
            q(
                "DELETE FROM watchlist WHERE owner_id = :o AND list_name = :l AND ticker = :t"
            ),
            {"o": owner_id, "l": list_name, "t": ticker},
        )
        # The fundamentals cache stays global on purpose: the numbers are the
        # same for everyone, so one person removing a ticker must not throw
        # away a copy another account is still using.


def transfer_owner(from_owner: str, to_owner: str) -> dict[str, int]:
    """Move an anonymous browser's rows onto a signed-in account.

    Rows the account already has win, so signing in on a second device can't
    clobber the list that is already there.
    """
    moved = {"watchlist": 0, "alerts": 0}
    with connect() as conn:
        existing = {
            (r["list_name"], r["ticker"])
            for r in conn.execute(
                q("SELECT list_name, ticker FROM watchlist WHERE owner_id = :o"),
                {"o": to_owner},
            ).mappings()
        }

        incoming = conn.execute(
            q("SELECT list_name, ticker FROM watchlist WHERE owner_id = :o"),
            {"o": from_owner},
        ).mappings().all()

        for row in incoming:
            key = (row["list_name"], row["ticker"])
            if key in existing:
                conn.execute(
                    q(
                        "DELETE FROM watchlist WHERE owner_id = :o AND list_name = :l "
                        "AND ticker = :t"
                    ),
                    {"o": from_owner, "l": row["list_name"], "t": row["ticker"]},
                )
            else:
                conn.execute(
                    q(
                        "UPDATE watchlist SET owner_id = :to WHERE owner_id = :from "
                        "AND list_name = :l AND ticker = :t"
                    ),
                    {"to": to_owner, "from": from_owner, "l": row["list_name"], "t": row["ticker"]},
                )
                moved["watchlist"] += 1

        result = conn.execute(
            q("UPDATE alerts SET owner_id = :to WHERE owner_id = :from"),
            {"to": to_owner, "from": from_owner},
        )
        moved["alerts"] = result.rowcount or 0

    return moved


# --- fundamentals cache ---

def get_cached_fundamentals(ticker: str) -> dict | None:
    with connect() as conn:
        row = conn.execute(
            q("SELECT data_json, fetched_at FROM fundamentals_cache WHERE ticker = :t"),
            {"t": ticker},
        ).mappings().first()
        if not row:
            return None
        return {"data": json.loads(row["data_json"]), "fetched_at": row["fetched_at"]}


def set_cached_fundamentals(ticker: str, data: dict) -> None:
    with connect() as conn:
        conn.execute(
            q(
                "INSERT INTO fundamentals_cache (ticker, data_json, fetched_at) "
                "VALUES (:t, :d, :f) ON CONFLICT (ticker) DO UPDATE "
                "SET data_json = excluded.data_json, fetched_at = excluded.fetched_at"
            ),
            {"t": ticker, "d": json.dumps(data), "f": now_iso()},
        )


# --- generic market cache ---

def get_market_cache(key: str, max_age_seconds: int):
    """Cached payload for `key`, or None if missing or past the TTL."""
    with connect() as conn:
        row = conn.execute(
            q("SELECT data_json, fetched_at FROM market_cache WHERE cache_key = :k"),
            {"k": key},
        ).mappings().first()
        if not row:
            return None
        fetched = datetime.fromisoformat(row["fetched_at"])
        if (datetime.now(timezone.utc) - fetched).total_seconds() > max_age_seconds:
            return None
        return json.loads(row["data_json"])


def set_market_cache(key: str, data) -> None:
    with connect() as conn:
        conn.execute(
            q(
                "INSERT INTO market_cache (cache_key, data_json, fetched_at) "
                "VALUES (:k, :d, :f) ON CONFLICT (cache_key) DO UPDATE "
                "SET data_json = excluded.data_json, fetched_at = excluded.fetched_at"
            ),
            {"k": key, "d": json.dumps(data), "f": now_iso()},
        )


# --- fed statements ---

def get_fed_timeline(limit: int = 20) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            q(
                "SELECT id, date, title, url, summary, sentiment, key_takeaways, fetched_at "
                "FROM fed_statements ORDER BY date DESC LIMIT :n"
            ),
            {"n": limit},
        ).mappings()

        results = []
        for row in rows:
            item = dict(row)
            item["key_takeaways"] = (
                json.loads(item["key_takeaways"]) if item["key_takeaways"] else []
            )
            results.append(item)
        return results


def statement_exists(statement_id: str) -> bool:
    with connect() as conn:
        row = conn.execute(
            q("SELECT 1 AS present FROM fed_statements WHERE id = :i"), {"i": statement_id}
        ).mappings().first()
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
    with connect() as conn:
        conn.execute(
            q(
                "INSERT INTO fed_statements "
                "(id, date, title, url, raw_text, summary, sentiment, key_takeaways, fetched_at) "
                "VALUES (:i, :d, :ti, :u, :r, :s, :se, :k, :f) "
                "ON CONFLICT (id) DO UPDATE SET summary = excluded.summary, "
                "sentiment = excluded.sentiment, key_takeaways = excluded.key_takeaways, "
                "fetched_at = excluded.fetched_at"
            ),
            {
                "i": statement_id,
                "d": date,
                "ti": title,
                "u": url,
                "r": raw_text,
                "s": summary,
                "se": sentiment,
                "k": json.dumps(key_takeaways),
                "f": now_iso(),
            },
        )
