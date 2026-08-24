import sqlite3


def _rows_as_dicts(conn: sqlite3.Connection, query: str, params: tuple = ()) -> list[dict]:
    previous_factory = conn.row_factory
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.row_factory = previous_factory


def list_games(conn: sqlite3.Connection) -> list[dict]:
    """Flattened view of the warehouse: one row per fact_game entry, joined against
    its dimensions so IDs (game_sk, platform_sk, date_sk) resolve to readable values."""
    query = """
        SELECT
            dg.app_id,
            dg.game_name,
            dg.release_date,
            p.platform_combo,
            f.price_usd,
            f.discount_pct,
            f.peak_ccu,
            f.positive_reviews,
            f.negative_reviews,
            f.average_playtime_mins,
            d.full_date AS snapshot_date,
            (
                SELECT GROUP_CONCAT(g2.genre_name, ', ')
                FROM bridge_game_genre bg2
                JOIN dim_genre g2 ON g2.genre_sk = bg2.genre_sk
                WHERE bg2.game_sk = dg.game_sk
            ) AS genres
        FROM fact_game f
        JOIN dim_game dg ON dg.game_sk = f.game_sk
        LEFT JOIN dim_platform p ON p.platform_sk = f.platform_sk
        LEFT JOIN dim_date d ON d.date_sk = f.date_sk
        ORDER BY dg.game_name, d.full_date DESC
    """
    return _rows_as_dicts(conn, query)
