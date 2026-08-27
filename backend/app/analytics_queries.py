import sqlite3

# Maps API-facing sort keys to real SQL column expressions. Whitelisted rather than
# taking the column name straight from the request - this string gets interpolated
# into the query, so an unvalidated value would be a SQL injection vector.
_SORTABLE_COLUMNS = {
    "app_id": "dg.app_id",
    "game_name": "dg.game_name",
    "platform_combo": "p.platform_combo",
    "price_usd": "f.price_usd",
    "discount_pct": "f.discount_pct",
    "peak_ccu": "f.peak_ccu",
    "positive_reviews": "f.positive_reviews",
    "negative_reviews": "f.negative_reviews",
    "average_playtime_mins": "f.average_playtime_mins",
    "release_date": "dg.release_date",
    "snapshot_date": "d.full_date",
}

_BASE_FROM = """
    FROM fact_game f
    JOIN dim_game dg ON dg.game_sk = f.game_sk
    LEFT JOIN dim_platform p ON p.platform_sk = f.platform_sk
    LEFT JOIN dim_date d ON d.date_sk = f.date_sk
"""


def _rows_as_dicts(conn: sqlite3.Connection, query: str, params: tuple = ()) -> list[dict]:
    previous_factory = conn.row_factory
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.row_factory = previous_factory


def list_games(
    conn: sqlite3.Connection,
    search: str | None = None,
    sort_key: str = "snapshot_date",
    sort_dir: str = "desc",
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict], int]:
    """Paginated, filtered, sorted warehouse content. Returns (rows, total).

    Scale choices, both proven necessary against a real ~278k-row warehouse:
    - The total count is a SEPARATE, minimal query - just fact_game alone when there's
      no search (66ms at 130k rows), or fact_game+dim_game only (skipping the platform/
      date joins entirely) when there is (307ms) - not the COUNT(*) with the full
      4-way join the row query needs, which alone cost over a second regardless of
      LIMIT and made a naive "OFFSET deep into 278k rows" case take 15s+.
    - Genre lookup (a correlated subquery per game) runs only on the LIMIT'd result,
      not on every matching row before pagination - the dominant cost otherwise.

    OFFSET itself is still O(offset) - SQLite has to walk past every skipped row - so
    this only stays fast for sequential browsing, not jumping deep into an unfiltered
    list. Search (indexed prefix match) is the tool for narrowing down.
    """
    sort_col = _SORTABLE_COLUMNS.get(sort_key, _SORTABLE_COLUMNS["snapshot_date"])
    direction = "DESC" if sort_dir == "desc" else "ASC"

    # Prefix match only ("dragon%" not "%dragon%"): a leading wildcard can't use
    # idx_dim_game_name at all, which was the actual cost of a "contains" search -
    # 6.7s at ~278k rows (full scan + sort) vs. under 100ms for a prefix range scan.
    where_clause = ""
    where_params: list = []
    if search:
        where_clause = "WHERE dg.game_name LIKE ?"
        where_params = [f"{search}%"]

    if search:
        total = conn.execute(
            f"SELECT COUNT(*) FROM fact_game f JOIN dim_game dg ON dg.game_sk = f.game_sk {where_clause}",
            where_params,
        ).fetchone()[0]
    else:
        total = conn.execute("SELECT COUNT(*) FROM fact_game").fetchone()[0]

    query = f"""
        SELECT
            dg.app_id, dg.game_name, dg.release_date, dg.game_sk,
            p.platform_combo, f.price_usd, f.discount_pct, f.peak_ccu,
            f.positive_reviews, f.negative_reviews, f.average_playtime_mins,
            d.full_date AS snapshot_date
        {_BASE_FROM}
        {where_clause}
        ORDER BY {sort_col} {direction}
        LIMIT ? OFFSET ?
    """
    rows = _rows_as_dicts(conn, query, where_params + [limit, offset])

    # One extra query for all rows' genres together, instead of one correlated
    # subquery per row - at limit=1000 that was ~1000 separate lookups and roughly
    # doubled the total query time (1s -> 2.4s). IN() over the page's game_sks is a
    # single indexed pass instead.
    game_sks = [r["game_sk"] for r in rows]
    genres_by_sk: dict[int, list[str]] = {}
    if game_sks:
        placeholders = ",".join("?" for _ in game_sks)
        genre_rows = conn.execute(
            f"""
            SELECT bg.game_sk, g.genre_name
            FROM bridge_game_genre bg
            JOIN dim_genre g ON g.genre_sk = bg.genre_sk
            WHERE bg.game_sk IN ({placeholders})
            """,
            game_sks,
        ).fetchall()
        for game_sk, genre_name in genre_rows:
            genres_by_sk.setdefault(game_sk, []).append(genre_name)

    for r in rows:
        genre_list = genres_by_sk.get(r.pop("game_sk"))
        r["genres"] = ", ".join(genre_list) if genre_list else None

    return rows, total


def price_by_release_year(conn: sqlite3.Connection) -> list[dict]:
    """Aggregated server-side (not by fetching every row to the browser) so this
    stays cheap regardless of warehouse size."""
    query = """
        SELECT
            CAST(strftime('%Y', dg.release_date) AS INT) AS year,
            AVG(f.price_usd) AS avg_price,
            AVG(f.discount_pct) AS avg_discount,
            COUNT(*) AS count
        FROM fact_game f
        JOIN dim_game dg ON dg.game_sk = f.game_sk
        WHERE dg.release_date IS NOT NULL AND f.price_usd IS NOT NULL
        GROUP BY year
        HAVING year IS NOT NULL
        ORDER BY year
    """
    return _rows_as_dicts(conn, query)


def summary_stats(conn: sqlite3.Connection) -> dict:
    """Headline KPIs for the warehouse - two cheap aggregate queries (no per-row
    Python loop), each a single pass over fact_game / bridge_game_genre."""
    row = conn.execute("""
        SELECT
            COUNT(DISTINCT f.game_sk) AS total_games,
            AVG(f.price_usd) AS avg_price,
            100.0 * SUM(CASE WHEN f.price_usd = 0 THEN 1 ELSE 0 END) / COUNT(*) AS pct_free,
            SUM(f.positive_reviews) AS total_positive,
            SUM(f.negative_reviews) AS total_negative,
            AVG(f.average_playtime_mins) AS avg_playtime_mins
        FROM fact_game f
    """).fetchone()

    top_genre_row = conn.execute("""
        SELECT g.genre_name, COUNT(*) AS n
        FROM bridge_game_genre bg
        JOIN dim_genre g ON g.genre_sk = bg.genre_sk
        GROUP BY g.genre_name
        ORDER BY n DESC
        LIMIT 1
    """).fetchone()

    total_positive = row[3] or 0
    total_negative = row[4] or 0
    total_reviews = total_positive + total_negative

    return {
        "total_games": row[0] or 0,
        "avg_price": row[1],
        "pct_free": row[2],
        "positive_review_rate": (100.0 * total_positive / total_reviews) if total_reviews else None,
        "avg_playtime_mins": row[5],
        "top_genre": top_genre_row[0] if top_genre_row else None,
    }


def price_history_for_game(conn: sqlite3.Connection, app_id: str) -> list[dict]:
    query = f"""
        SELECT f.price_usd, f.discount_pct, p.platform_combo, d.full_date AS snapshot_date
        {_BASE_FROM}
        WHERE dg.app_id = ? AND f.price_usd IS NOT NULL
        ORDER BY d.full_date
    """
    return _rows_as_dicts(conn, query, (app_id,))
