"""Storage layer.

SQL here is deliberately portable between SQLite and Postgres: no AUTOINCREMENT,
no RETURNING, and upserts written as ON CONFLICT ... DO UPDATE, which both
understand. `owner_id` identifies whoever the rows belong to -- a signed-in
user's id, or an anonymous browser's space id -- so one set of queries serves
both without a second code path.
"""

import json
import uuid
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

# A lot is one purchase or sale, kept rather than collapsed into a single
# "shares held" number. Adding to a position over time is normal, and only the
# individual lots give a real weighted average cost -- one number would be
# overwritten by the next buy and the basis lost. Negative shares are a sale,
# with cost_per_share carrying the price sold at, which is what realised P/L
# needs later.
LOTS_SCHEMA = """
    CREATE TABLE IF NOT EXISTS lots (
        id TEXT PRIMARY KEY,
        owner_id TEXT NOT NULL,
        ticker TEXT NOT NULL,
        shares DOUBLE PRECISION NOT NULL,
        cost_per_share DOUBLE PRECISION NOT NULL,
        trade_date TEXT NOT NULL,
        note TEXT,
        created_at TEXT NOT NULL
    )
"""

# A split rewrites every lot's share count and cost, which is destructive: the
# original figures are gone once it is applied. Recording the event means a
# ratio entered wrongly can be reversed exactly instead of leaving a basis
# that is silently wrong forever.
SPLITS_SCHEMA = """
    CREATE TABLE IF NOT EXISTS splits (
        id TEXT PRIMARY KEY,
        owner_id TEXT NOT NULL,
        ticker TEXT NOT NULL,
        ratio DOUBLE PRECISION NOT NULL,
        applied_at TEXT NOT NULL
    )
"""

# What you were thinking when you bought, and what the stock cost when you
# thought it. The price is the point: an opinion recorded next to the price it
# was formed at can be checked later, and one without cannot. It is stamped
# once at write time and never recomputed -- recalculating it against today's
# price would erase the only thing the entry was for.
JOURNAL_SCHEMA = """
    CREATE TABLE IF NOT EXISTS journal (
        id TEXT PRIMARY KEY,
        owner_id TEXT NOT NULL,
        ticker TEXT NOT NULL,
        body TEXT NOT NULL,
        price_at_write DOUBLE PRECISION,
        date_written TEXT NOT NULL,
        tags TEXT NOT NULL,
        reviewed_at TEXT
    )
"""

TABLES = [
    WATCHLIST_SCHEMA,
    LOTS_SCHEMA,
    SPLITS_SCHEMA,
    JOURNAL_SCHEMA,
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
    "CREATE INDEX IF NOT EXISTS idx_lots_owner ON lots (owner_id, ticker)",
    "CREATE INDEX IF NOT EXISTS idx_splits_owner ON splits (owner_id, ticker)",
    "CREATE INDEX IF NOT EXISTS idx_journal_owner ON journal (owner_id, date_written)",
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
    moved = {"watchlist": 0, "alerts": 0, "lots": 0, "journal": 0}
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

        # Lots and their split adjustments move wholesale rather than being
        # merged. Each lot is a distinct trade, so two of the same ticker are
        # not duplicates the way two watchlist rows are -- de-duplicating here
        # would quietly delete a real purchase. They travel together because a
        # split left behind would restate lots it no longer applies to.
        result = conn.execute(
            q("UPDATE lots SET owner_id = :to WHERE owner_id = :from"),
            {"to": to_owner, "from": from_owner},
        )
        moved["lots"] = result.rowcount or 0
        conn.execute(
            q("UPDATE splits SET owner_id = :to WHERE owner_id = :from"),
            {"to": to_owner, "from": from_owner},
        )

        # Journal entries move for the same reason as lots: each is a distinct
        # thing written on a day, not a row that can be de-duplicated.
        result = conn.execute(
            q("UPDATE journal SET owner_id = :to WHERE owner_id = :from"),
            {"to": to_owner, "from": from_owner},
        )
        moved["journal"] = result.rowcount or 0

    return moved


# --- positions ---

def list_lots(owner_id: str, ticker: str | None = None) -> list[dict]:
    """Every lot the owner has recorded, oldest trade first.

    Order matters: average cost is computed by walking the lots in the order
    they happened, so a sale is priced against the basis as it stood then.
    """
    sql = "SELECT * FROM lots WHERE owner_id = :o"
    params: dict = {"o": owner_id}
    if ticker:
        sql += " AND ticker = :t"
        params["t"] = ticker
    sql += " ORDER BY trade_date, created_at"

    with connect() as conn:
        return [_row_to_lot(r) for r in conn.execute(q(sql), params).mappings()]


def add_lot(
    owner_id: str,
    ticker: str,
    shares: float,
    cost_per_share: float,
    trade_date: str,
    note: str | None = None,
) -> dict:
    lot_id = uuid.uuid4().hex
    with connect() as conn:
        conn.execute(
            q(
                "INSERT INTO lots "
                "(id, owner_id, ticker, shares, cost_per_share, trade_date, note, created_at) "
                "VALUES (:i, :o, :t, :s, :c, :d, :n, :ca)"
            ),
            {
                "i": lot_id,
                "o": owner_id,
                "t": ticker,
                "s": float(shares),
                "c": float(cost_per_share),
                "d": trade_date,
                "n": note or None,
                "ca": now_iso(),
            },
        )
    return get_lot(owner_id, lot_id)


def get_lot(owner_id: str, lot_id: str) -> dict | None:
    with connect() as conn:
        row = conn.execute(
            q("SELECT * FROM lots WHERE owner_id = :o AND id = :i"),
            {"o": owner_id, "i": lot_id},
        ).mappings().first()
        return _row_to_lot(row) if row else None


def delete_lot(owner_id: str, lot_id: str) -> None:
    with connect() as conn:
        conn.execute(
            q("DELETE FROM lots WHERE owner_id = :o AND id = :i"),
            {"o": owner_id, "i": lot_id},
        )


def apply_split(owner_id: str, ticker: str, ratio: float) -> dict:
    """Restate every lot of `ticker` for a share split.

    A 4-for-1 split is ratio 4: four times the shares at a quarter the cost
    each, leaving the money invested unchanged. Total cost is what must not
    move -- it is the only figure a split does not affect -- so shares are
    multiplied and cost per share divided by the same number.

    Applied to every lot including later ones, because the alternative is
    worse: the reader adds a lot, then remembers the split, and a
    date-filtered version would silently skip it.
    """
    ratio = float(ratio)
    split_id = uuid.uuid4().hex
    with connect() as conn:
        conn.execute(
            q(
                "UPDATE lots SET shares = shares * :r, cost_per_share = cost_per_share / :r "
                "WHERE owner_id = :o AND ticker = :t"
            ),
            {"r": ratio, "o": owner_id, "t": ticker},
        )
        conn.execute(
            q(
                "INSERT INTO splits (id, owner_id, ticker, ratio, applied_at) "
                "VALUES (:i, :o, :t, :r, :a)"
            ),
            {"i": split_id, "o": owner_id, "t": ticker, "r": ratio, "a": now_iso()},
        )
    return {"id": split_id, "ticker": ticker, "ratio": ratio, "applied_at": now_iso()}


def undo_split(owner_id: str, split_id: str) -> bool:
    """Reverse a split adjustment, exactly.

    The point of recording splits at all: a ratio typed as 10 instead of 0.1
    leaves every cost basis wrong by a hundredfold, and without this there is
    no way back short of re-entering every lot from memory.
    """
    with connect() as conn:
        row = conn.execute(
            q("SELECT ticker, ratio FROM splits WHERE owner_id = :o AND id = :i"),
            {"o": owner_id, "i": split_id},
        ).mappings().first()
        if not row:
            return False

        conn.execute(
            q(
                "UPDATE lots SET shares = shares / :r, cost_per_share = cost_per_share * :r "
                "WHERE owner_id = :o AND ticker = :t"
            ),
            {"r": float(row["ratio"]), "o": owner_id, "t": row["ticker"]},
        )
        conn.execute(
            q("DELETE FROM splits WHERE owner_id = :o AND id = :i"),
            {"o": owner_id, "i": split_id},
        )
    return True


def list_splits(owner_id: str) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            q("SELECT * FROM splits WHERE owner_id = :o ORDER BY applied_at DESC"),
            {"o": owner_id},
        ).mappings()
        return [
            {
                "id": r["id"],
                "ticker": r["ticker"],
                "ratio": r["ratio"],
                "applied_at": r["applied_at"],
            }
            for r in rows
        ]


def _row_to_lot(row) -> dict:
    return {
        "id": row["id"],
        "ticker": row["ticker"],
        "shares": row["shares"],
        "costPerShare": row["cost_per_share"],
        "tradeDate": row["trade_date"],
        "note": row["note"],
        "created_at": row["created_at"],
    }


# --- thesis journal ---

def list_journal(owner_id: str, ticker: str | None = None) -> list[dict]:
    """Entries newest first, which is how a journal is read."""
    sql = "SELECT * FROM journal WHERE owner_id = :o"
    params: dict = {"o": owner_id}
    if ticker:
        sql += " AND ticker = :t"
        params["t"] = ticker
    sql += " ORDER BY date_written DESC"

    with connect() as conn:
        return [_row_to_entry(r) for r in conn.execute(q(sql), params).mappings()]


def add_journal_entry(
    owner_id: str,
    ticker: str,
    body: str,
    price_at_write: float | None,
    tags: list[str],
) -> dict:
    entry_id = uuid.uuid4().hex
    with connect() as conn:
        conn.execute(
            q(
                "INSERT INTO journal "
                "(id, owner_id, ticker, body, price_at_write, date_written, tags) "
                "VALUES (:i, :o, :t, :b, :p, :d, :g)"
            ),
            {
                "i": entry_id,
                "o": owner_id,
                "t": ticker,
                "b": body,
                "p": price_at_write,
                "d": now_iso(),
                "g": json.dumps(tags),
            },
        )
    return get_journal_entry(owner_id, entry_id)


def get_journal_entry(owner_id: str, entry_id: str) -> dict | None:
    with connect() as conn:
        row = conn.execute(
            q("SELECT * FROM journal WHERE owner_id = :o AND id = :i"),
            {"o": owner_id, "i": entry_id},
        ).mappings().first()
        return _row_to_entry(row) if row else None


def delete_journal_entry(owner_id: str, entry_id: str) -> None:
    with connect() as conn:
        conn.execute(
            q("DELETE FROM journal WHERE owner_id = :o AND id = :i"),
            {"o": owner_id, "i": entry_id},
        )


def mark_journal_reviewed(owner_id: str, entry_id: str) -> bool:
    """Stamp an entry as revisited, so it stops being nudged about."""
    with connect() as conn:
        result = conn.execute(
            q("UPDATE journal SET reviewed_at = :r WHERE owner_id = :o AND id = :i"),
            {"r": now_iso(), "o": owner_id, "i": entry_id},
        )
        return bool(result.rowcount)


def _row_to_entry(row) -> dict:
    return {
        "id": row["id"],
        "ticker": row["ticker"],
        "body": row["body"],
        "priceAtWrite": row["price_at_write"],
        "dateWritten": row["date_written"],
        "tags": json.loads(row["tags"]) if row["tags"] else [],
        "reviewedAt": row["reviewed_at"],
    }


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
