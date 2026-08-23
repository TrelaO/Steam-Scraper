import sqlite3
from datetime import date, timedelta
from pathlib import Path

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
        average_playtime_mins INT
    )
    """,
]


def get_ddl_text() -> str:
    """DDL as a single string, used to prime the LLM prompt with the target schema."""
    return "\n".join(stmt.strip() + ";" for stmt in DDL_STATEMENTS)


def get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def init_db() -> None:
    conn = get_connection()
    try:
        with conn:
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
