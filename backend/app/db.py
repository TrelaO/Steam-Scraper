import logging
import sqlite3
from datetime import date, timedelta
from pathlib import Path

logger = logging.getLogger("steam_etl.db")

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "warehouse.db"

DDL_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS dim_date (
        date_sk INT PRIMARY KEY,
        full_date DATE,
        year INT,
        month INT,
        quarter INT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS dim_platform (
        platform_sk INTEGER PRIMARY KEY AUTOINCREMENT,
        supports_windows BOOLEAN,
        supports_mac BOOLEAN,
        supports_linux BOOLEAN,
        platform_combo VARCHAR(50)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS dim_game (
        game_sk INTEGER PRIMARY KEY AUTOINCREMENT,
        app_id VARCHAR(50) UNIQUE NOT NULL,
        game_name VARCHAR(255),
        required_age INT,
        release_date DATE,
        estimated_owners VARCHAR(50),
        owners_min INT,
        owners_max INT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS dim_genre (
        genre_sk INTEGER PRIMARY KEY AUTOINCREMENT,
        genre_name VARCHAR(100) UNIQUE NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS bridge_game_genre (
        game_sk INT REFERENCES dim_game(game_sk),
        genre_sk INT REFERENCES dim_genre(genre_sk),
        PRIMARY KEY (game_sk, genre_sk)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS fact_game (
        fact_sk INTEGER PRIMARY KEY AUTOINCREMENT,
        game_sk INT REFERENCES dim_game(game_sk),
        date_sk INT REFERENCES dim_date(date_sk),
        platform_sk INT REFERENCES dim_platform(platform_sk),
        price_usd DECIMAL(10,2),
        discount_pct INT,
        peak_ccu INT,
        positive_reviews INT,
        negative_reviews INT,
        average_playtime_mins INT,
        UNIQUE (game_sk, date_sk, platform_sk)
    )
    """,
    # Re-running the same file on the same day previously kept appending a fresh
    # fact_game row per game with no way to tell it apart from the last run's -
    # the UNIQUE constraint above lets generated code use INSERT OR REPLACE instead,
    # so a same-day re-import updates that snapshot rather than duplicating it.
    "CREATE INDEX IF NOT EXISTS idx_dim_game_name ON dim_game(game_name)",
    "CREATE INDEX IF NOT EXISTS idx_fact_game_game_sk ON fact_game(game_sk)",
]


def get_ddl_text() -> str:
    """DDL as a single string, used to prime the LLM prompt with the target schema."""
    return "\n".join(stmt.strip() + ";" for stmt in DDL_STATEMENTS)


def get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    # check_same_thread=False: the connection is opened on the request thread but the
    # generated ETL code runs it from a worker thread (etl_runner's timeout executor).
    # Access is still strictly sequential (never concurrent), so this is safe here.
    # timeout= (Python driver) and PRAGMA busy_timeout (SQLite itself) both needed:
    # without either, a second connection hitting the DB while another is mid-write -
    # a long-running ETL job, a migration, anything - gets "database is locked"
    # immediately instead of waiting a moment for the lock to clear. 30s covers even
    # a slow ETL write against a large dataset.
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30.0)
    conn.execute("PRAGMA busy_timeout = 30000;")
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def _migrate_fact_game_unique_constraint(conn: sqlite3.Connection) -> None:
    """fact_game gained a UNIQUE(game_sk, date_sk, platform_sk) constraint after the
    table may already have existed without it - CREATE TABLE IF NOT EXISTS never
    retrofits an existing table, and clearing data (DELETE FROM) doesn't touch the
    schema either. Detect the old shape and migrate in place, deduplicating any
    existing rows by keeping the most-recently-inserted one per (game_sk, date_sk,
    platform_sk) - the same "later snapshot wins" semantics INSERT OR REPLACE gives
    going forward.
    """
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='fact_game'"
    ).fetchone()
    if row is None or row[0] is None or "UNIQUE" in row[0].upper():
        return  # doesn't exist yet (fresh DB) or already migrated

    logger.info("Migrating fact_game to add UNIQUE(game_sk, date_sk, platform_sk)...")
    conn.execute("ALTER TABLE fact_game RENAME TO fact_game_old")
    conn.execute("""
        CREATE TABLE fact_game (
            fact_sk INTEGER PRIMARY KEY AUTOINCREMENT,
            game_sk INT REFERENCES dim_game(game_sk),
            date_sk INT REFERENCES dim_date(date_sk),
            platform_sk INT REFERENCES dim_platform(platform_sk),
            price_usd DECIMAL(10,2),
            discount_pct INT,
            peak_ccu INT,
            positive_reviews INT,
            negative_reviews INT,
            average_playtime_mins INT,
            UNIQUE (game_sk, date_sk, platform_sk)
        )
    """)
    conn.execute("""
        INSERT OR REPLACE INTO fact_game
            (fact_sk, game_sk, date_sk, platform_sk, price_usd, discount_pct,
             peak_ccu, positive_reviews, negative_reviews, average_playtime_mins)
        SELECT fact_sk, game_sk, date_sk, platform_sk, price_usd, discount_pct,
               peak_ccu, positive_reviews, negative_reviews, average_playtime_mins
        FROM fact_game_old
        ORDER BY fact_sk
    """)
    before = conn.execute("SELECT COUNT(*) FROM fact_game_old").fetchone()[0]
    after = conn.execute("SELECT COUNT(*) FROM fact_game").fetchone()[0]
    conn.execute("DROP TABLE fact_game_old")
    logger.info("Migration done: %d rows -> %d rows (%d duplicates removed)", before, after, before - after)


def init_db() -> None:
    conn = get_connection()
    try:
        with conn:
            _migrate_fact_game_unique_constraint(conn)
            for statement in DDL_STATEMENTS:
                conn.execute(statement)
            _seed_dim_platform(conn)
            _seed_dim_date(conn)
    finally:
        conn.close()


def _seed_dim_platform(conn: sqlite3.Connection) -> None:
    if conn.execute("SELECT COUNT(*) FROM dim_platform").fetchone()[0] > 0:
        return
    combos = []
    for windows in (0, 1):
        for mac in (0, 1):
            for linux in (0, 1):
                label = "+".join(
                    name
                    for name, flag in (("Windows", windows), ("Mac", mac), ("Linux", linux))
                    if flag
                ) or "None"
                combos.append((windows, mac, linux, label))
    conn.executemany(
        """
        INSERT INTO dim_platform (supports_windows, supports_mac, supports_linux, platform_combo)
        VALUES (?, ?, ?, ?)
        """,
        combos,
    )


def clear_data() -> None:
    """Wipes everything the ETL writes (dim_game, dim_genre, bridge_game_genre,
    fact_game) but leaves the seeded reference dimensions (dim_date, dim_platform)
    in place - those aren't user data, they're static lookup tables."""
    conn = get_connection()
    try:
        with conn:
            conn.execute("DELETE FROM fact_game")
            conn.execute("DELETE FROM bridge_game_genre")
            conn.execute("DELETE FROM dim_genre")
            conn.execute("DELETE FROM dim_game")
            conn.execute(
                "DELETE FROM sqlite_sequence WHERE name IN "
                "('fact_game', 'dim_genre', 'dim_game')"
            )
    finally:
        conn.close()


def _seed_dim_date(conn: sqlite3.Connection, start_year: int = 2015, end_year: int = 2030) -> None:
    if conn.execute("SELECT COUNT(*) FROM dim_date").fetchone()[0] > 0:
        return
    rows = []
    current = date(start_year, 1, 1)
    end = date(end_year, 12, 31)
    while current <= end:
        date_sk = int(current.strftime("%Y%m%d"))
        quarter = (current.month - 1) // 3 + 1
        rows.append((date_sk, current.isoformat(), current.year, current.month, quarter))
        current += timedelta(days=1)
    conn.executemany(
        "INSERT INTO dim_date (date_sk, full_date, year, month, quarter) VALUES (?, ?, ?, ?, ?)",
        rows,
    )
