import sqlite3

from app import db


def test_init_db_creates_all_tables(conn):
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    for expected in ("dim_date", "dim_platform", "dim_game", "dim_genre", "bridge_game_genre", "fact_game"):
        assert expected in tables


def test_seeds_dim_platform_with_all_os_combinations(conn):
    # 2^3 windows/mac/linux flag combinations, seeded once at init.
    assert conn.execute("SELECT COUNT(*) FROM dim_platform").fetchone()[0] == 8


def test_seeds_dim_date_covers_a_known_date(conn):
    row = conn.execute("SELECT year, month, quarter FROM dim_date WHERE date_sk = 20200315").fetchone()
    assert row == (2020, 3, 1)


def test_get_schema_info_reflects_live_row_counts(conn):
    before = next(t for t in db.get_schema_info(conn) if t["name"] == "dim_genre")
    assert before["row_count"] == 0

    conn.execute("INSERT OR IGNORE INTO dim_genre (genre_name) VALUES ('Action')")
    conn.commit()

    after = next(t for t in db.get_schema_info(conn) if t["name"] == "dim_genre")
    assert after["row_count"] == 1
    assert after["kind"] == "dimension"


def _insert_complete_game(conn, app_id: str) -> int:
    conn.execute(
        """
        INSERT INTO dim_game (app_id, game_name, required_age, release_date,
            estimated_owners, owners_min, owners_max)
        VALUES (?, 'Game', 0, '2020-01-01', '0-20000', 0, 20000)
        """,
        (app_id,),
    )
    game_sk = conn.execute("SELECT game_sk FROM dim_game WHERE app_id = ?", (app_id,)).fetchone()[0]
    conn.execute("INSERT OR IGNORE INTO dim_genre (genre_name) VALUES ('Action')")
    genre_sk = conn.execute("SELECT genre_sk FROM dim_genre WHERE genre_name = 'Action'").fetchone()[0]
    conn.execute("INSERT OR IGNORE INTO bridge_game_genre (game_sk, genre_sk) VALUES (?, ?)", (game_sk, genre_sk))
    conn.execute(
        """
        INSERT INTO fact_game (game_sk, date_sk, platform_sk, price_usd, discount_pct,
            peak_ccu, positive_reviews, negative_reviews, average_playtime_mins)
        VALUES (?, 20200315, 1, 9.99, 0, 100, 10, 1, 60)
        """,
        (game_sk,),
    )
    return game_sk


def test_remove_incomplete_games_keeps_fully_populated_rows(conn):
    _insert_complete_game(conn, "complete-1")
    conn.commit()

    removed = db.remove_incomplete_games(conn)

    assert removed == {"fact_game": 0, "bridge_game_genre": 0, "dim_game": 0}
    assert conn.execute("SELECT COUNT(*) FROM dim_game").fetchone()[0] == 1


def test_remove_incomplete_games_removes_rows_with_a_null_field(conn):
    # A companion fully-complete game keeps this batch from being "100% would be
    # deleted" (which now short-circuits the cleanup entirely - see the dedicated
    # skip-guard tests below), so this isolates the per-row removal behavior itself.
    _insert_complete_game(conn, "companion-good")

    # Same shape as _insert_complete_game but price_usd left NULL - the ETL mapped
    # every OTHER field but this one, so the whole snapshot/game should be dropped.
    conn.execute(
        """
        INSERT INTO dim_game (app_id, game_name, required_age, release_date,
            estimated_owners, owners_min, owners_max)
        VALUES ('incomplete-1', 'Game', 0, '2020-01-01', '0-20000', 0, 20000)
        """
    )
    game_sk = conn.execute("SELECT game_sk FROM dim_game WHERE app_id = 'incomplete-1'").fetchone()[0]
    conn.execute("INSERT OR IGNORE INTO dim_genre (genre_name) VALUES ('Action')")
    genre_sk = conn.execute("SELECT genre_sk FROM dim_genre WHERE genre_name = 'Action'").fetchone()[0]
    conn.execute("INSERT INTO bridge_game_genre (game_sk, genre_sk) VALUES (?, ?)", (game_sk, genre_sk))
    conn.execute(
        """
        INSERT INTO fact_game (game_sk, date_sk, platform_sk, price_usd, discount_pct,
            peak_ccu, positive_reviews, negative_reviews, average_playtime_mins)
        VALUES (?, 20200315, 1, NULL, 0, 100, 10, 1, 60)
        """,
        (game_sk,),
    )
    conn.commit()

    removed = db.remove_incomplete_games(conn)

    assert removed["fact_game"] == 1
    assert removed["dim_game"] == 1
    assert conn.execute("SELECT COUNT(*) FROM dim_game").fetchone()[0] == 1  # only the companion survives


def test_remove_incomplete_games_removes_games_with_no_genre(conn):
    _insert_complete_game(conn, "companion-good")

    conn.execute(
        """
        INSERT INTO dim_game (app_id, game_name, required_age, release_date,
            estimated_owners, owners_min, owners_max)
        VALUES ('no-genre-1', 'Game', 0, '2020-01-01', '0-20000', 0, 20000)
        """
    )
    game_sk = conn.execute("SELECT game_sk FROM dim_game WHERE app_id = 'no-genre-1'").fetchone()[0]
    conn.execute(
        """
        INSERT INTO fact_game (game_sk, date_sk, platform_sk, price_usd, discount_pct,
            peak_ccu, positive_reviews, negative_reviews, average_playtime_mins)
        VALUES (?, 20200315, 1, 9.99, 0, 100, 10, 1, 60)
        """,
        (game_sk,),
    )
    conn.commit()

    removed = db.remove_incomplete_games(conn)

    assert removed["dim_game"] == 1


def test_remove_incomplete_games_does_not_require_discount_pct_or_peak_ccu(conn):
    # Regression test for the real bug this was built to fix: a source format that
    # never carries live-service fields (discount %, peak concurrent users) - e.g.
    # a static Kaggle "steam.csv" export - used to have every single row treated as
    # incomplete and deleted, even though every OTHER field was correctly mapped.
    _insert_complete_game(conn, "companion-good")

    conn.execute(
        """
        INSERT INTO dim_game (app_id, game_name, required_age, release_date,
            estimated_owners, owners_min, owners_max)
        VALUES ('no-live-fields', 'Game', 0, '2020-01-01', '0-20000', 0, 20000)
        """
    )
    game_sk = conn.execute("SELECT game_sk FROM dim_game WHERE app_id = 'no-live-fields'").fetchone()[0]
    conn.execute("INSERT OR IGNORE INTO dim_genre (genre_name) VALUES ('Action')")
    genre_sk = conn.execute("SELECT genre_sk FROM dim_genre WHERE genre_name = 'Action'").fetchone()[0]
    conn.execute("INSERT INTO bridge_game_genre (game_sk, genre_sk) VALUES (?, ?)", (game_sk, genre_sk))
    conn.execute(
        """
        INSERT INTO fact_game (game_sk, date_sk, platform_sk, price_usd, discount_pct,
            peak_ccu, positive_reviews, negative_reviews, average_playtime_mins)
        VALUES (?, 20200315, 1, 9.99, NULL, NULL, 10, 1, 60)
        """,
        (game_sk,),
    )
    conn.commit()

    removed = db.remove_incomplete_games(conn)

    assert removed == {"fact_game": 0, "bridge_game_genre": 0, "dim_game": 0}
    assert conn.execute("SELECT COUNT(*) FROM dim_game").fetchone()[0] == 2


def test_remove_incomplete_games_skips_cleanup_if_it_would_delete_everything(conn):
    # No companion good row this time - every fact_game row in the warehouse is
    # missing price_usd, so a naive cleanup would wipe the entire (otherwise
    # successful) import. The skip-guard should refuse to do that.
    for app_id in ("bad-1", "bad-2"):
        conn.execute(
            """
            INSERT INTO dim_game (app_id, game_name, required_age, release_date,
                estimated_owners, owners_min, owners_max)
            VALUES (?, 'Game', 0, '2020-01-01', '0-20000', 0, 20000)
            """,
            (app_id,),
        )
        game_sk = conn.execute("SELECT game_sk FROM dim_game WHERE app_id = ?", (app_id,)).fetchone()[0]
        conn.execute(
            """
            INSERT INTO fact_game (game_sk, date_sk, platform_sk, price_usd, discount_pct,
                peak_ccu, positive_reviews, negative_reviews, average_playtime_mins)
            VALUES (?, 20200315, 1, NULL, 0, 100, 10, 1, 60)
            """,
            (game_sk,),
        )
    conn.commit()

    removed = db.remove_incomplete_games(conn)

    assert removed["skipped_all_incomplete"] is True
    assert removed["fact_game"] == 0
    # Nothing was actually deleted - the whole point of the guard.
    assert conn.execute("SELECT COUNT(*) FROM fact_game").fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM dim_game").fetchone()[0] == 2


def test_remove_incomplete_games_guard_does_not_trigger_on_an_empty_warehouse(conn):
    # total_before == 0 must not be treated as "100% would be deleted" - there's
    # nothing to skip cleaning up.
    removed = db.remove_incomplete_games(conn)
    assert "skipped_all_incomplete" not in removed


def test_clear_data_wipes_user_tables_but_keeps_seeded_dimensions(conn):
    _insert_complete_game(conn, "to-be-cleared")
    conn.commit()

    db.clear_data()

    assert conn.execute("SELECT COUNT(*) FROM dim_game").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM fact_game").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM dim_genre").fetchone()[0] == 0
    # Reference dimensions are not user data and must survive a clear.
    assert conn.execute("SELECT COUNT(*) FROM dim_platform").fetchone()[0] == 8
    assert conn.execute("SELECT COUNT(*) FROM dim_date").fetchone()[0] > 0


def test_migration_adds_unique_constraint_and_dedupes_old_rows(tmp_path):
    # Deliberately NOT using the `conn` fixture (which already runs init_db, i.e.
    # the post-migration schema) - builds the OLD fact_game shape (no UNIQUE
    # constraint) by hand to prove the migration path itself, including dedup.
    path = tmp_path / "old_shape.db"
    raw = sqlite3.connect(path)
    raw.execute("""
        CREATE TABLE fact_game (
            fact_sk INTEGER PRIMARY KEY AUTOINCREMENT,
            game_sk INT, date_sk INT, platform_sk INT,
            price_usd DECIMAL(10,2), discount_pct INT, peak_ccu INT,
            positive_reviews INT, negative_reviews INT, average_playtime_mins INT
        )
    """)
    # Two rows for the same (game_sk, date_sk, platform_sk) - simulates the
    # duplicate-accumulation bug the UNIQUE constraint was added to prevent.
    # The later-inserted row (price 14.99) should be the one that survives.
    raw.executemany(
        """
        INSERT INTO fact_game (game_sk, date_sk, platform_sk, price_usd, discount_pct,
            peak_ccu, positive_reviews, negative_reviews, average_playtime_mins)
        VALUES (?, ?, ?, ?, 0, 0, 0, 0, 0)
        """,
        [(1, 20200101, 1, 19.99), (1, 20200101, 1, 14.99), (2, 20200101, 1, 5.0)],
    )
    raw.commit()

    db._migrate_fact_game_unique_constraint(raw)
    raw.commit()

    rows = raw.execute(
        "SELECT game_sk, date_sk, platform_sk, price_usd FROM fact_game ORDER BY game_sk"
    ).fetchall()
    assert rows == [(1, 20200101, 1, 14.99), (2, 20200101, 1, 5.0)]

    # The constraint itself must actually be in place post-migration.
    ddl = raw.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='fact_game'"
    ).fetchone()[0]
    assert "UNIQUE" in ddl.upper()
    raw.close()


def test_migration_is_a_noop_on_a_fresh_database(conn):
    # init_db() (via the `conn` fixture) already ran the migration once - calling
    # it again must not error or change anything (idempotency, since it also runs
    # on every ordinary startup, not just genuinely-old databases).
    before = conn.execute("SELECT COUNT(*) FROM fact_game").fetchone()[0]
    db._migrate_fact_game_unique_constraint(conn)
    after = conn.execute("SELECT COUNT(*) FROM fact_game").fetchone()[0]
    assert before == after == 0
