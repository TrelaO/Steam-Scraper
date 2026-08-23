import sqlite3


def _rows_as_dicts(conn: sqlite3.Connection, query: str, params: tuple = ()) -> list[dict]:
    previous_factory = conn.row_factory
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.row_factory = previous_factory


def avg_price_discount_by_genre_year(conn: sqlite3.Connection) -> list[dict]:
    query = """
        SELECT g.genre_name,
               CAST(strftime('%Y', dg.release_date) AS INT) AS release_year,
               AVG(f.price_usd) AS avg_price,
               AVG(f.discount_pct) AS avg_discount
        FROM fact_game f
        JOIN dim_game dg ON dg.game_sk = f.game_sk
        JOIN bridge_game_genre bg ON bg.game_sk = dg.game_sk
        JOIN dim_genre g ON g.genre_sk = bg.genre_sk
        GROUP BY g.genre_name, release_year
        ORDER BY release_year, g.genre_name
    """
    return _rows_as_dicts(conn, query)


def price_review_correlation(conn: sqlite3.Connection) -> list[dict]:
    query = """
        SELECT dg.game_name,
               f.price_usd,
               f.positive_reviews,
               f.negative_reviews
        FROM fact_game f
        JOIN dim_game dg ON dg.game_sk = f.game_sk
    """
    return _rows_as_dicts(conn, query)


def price_variance_by_platform(conn: sqlite3.Connection) -> list[dict]:
    query = """
        SELECT p.platform_combo,
               AVG(f.price_usd) AS avg_price,
               MIN(f.price_usd) AS min_price,
               MAX(f.price_usd) AS max_price
        FROM fact_game f
        JOIN dim_platform p ON p.platform_sk = f.platform_sk
        GROUP BY p.platform_combo
    """
    return _rows_as_dicts(conn, query)
