from app import analytics_queries as aq

DATE_SK = 20200315  # known to exist, seeded by dim_date
PLATFORM_SK = 1  # first seeded platform combo


def _insert_game(conn, app_id, price, discount, positive, negative):
    conn.execute("INSERT INTO dim_game (app_id, game_name) VALUES (?, ?)", (app_id, app_id))
    game_sk = conn.execute("SELECT game_sk FROM dim_game WHERE app_id = ?", (app_id,)).fetchone()[0]
    conn.execute(
        """
        INSERT INTO fact_game (game_sk, date_sk, platform_sk, price_usd, discount_pct,
            peak_ccu, positive_reviews, negative_reviews, average_playtime_mins)
        VALUES (?, ?, ?, ?, ?, 0, ?, ?, 0)
        """,
        (game_sk, DATE_SK, PLATFORM_SK, price, discount, positive, negative),
    )
    return game_sk


def _seed_dss_scenario(conn):
    # avg(price) across these 5 rows is 82 - only the four priced at 100 clear the
    # "priced above average" bar the discount_opportunities/reprice_flags rules use.
    _insert_game(conn, "well-reviewed-undiscounted", 100, 0, 90, 10)  # -> discount candidate
    _insert_game(conn, "poorly-reviewed-undiscounted", 100, 0, 10, 90)  # -> reprice candidate
    _insert_game(conn, "cheap-well-reviewed", 10, 0, 90, 10)  # priced below avg, excluded
    _insert_game(conn, "well-reviewed-but-discounted", 100, 20, 90, 10)  # already discounted
    _insert_game(conn, "too-few-reviews", 100, 0, 10, 5)  # under the review-count floor
    conn.commit()


def test_discount_opportunities_flags_only_well_reviewed_undiscounted_above_average(conn):
    _seed_dss_scenario(conn)

    rows = aq.discount_opportunities(conn)

    assert [r["app_id"] for r in rows] == ["well-reviewed-undiscounted"]
    assert rows[0]["review_score"] == 90.0


def test_reprice_flags_only_poorly_reviewed_undiscounted_above_average(conn):
    _seed_dss_scenario(conn)

    rows = aq.reprice_flags(conn)

    assert [r["app_id"] for r in rows] == ["poorly-reviewed-undiscounted"]
    assert rows[0]["review_score"] == 10.0


def test_dss_lists_are_empty_on_an_empty_warehouse(conn):
    assert aq.discount_opportunities(conn) == []
    assert aq.reprice_flags(conn) == []


def test_summary_stats_on_empty_warehouse_returns_none_not_error(conn):
    stats = aq.summary_stats(conn)
    assert stats["total_games"] == 0
    assert stats["avg_price"] is None
    assert stats["positive_review_rate"] is None


def test_summary_stats_computes_review_rate_across_games(conn):
    _insert_game(conn, "a", 10, 0, 80, 20)
    _insert_game(conn, "b", 20, 0, 20, 80)
    conn.commit()

    stats = aq.summary_stats(conn)

    assert stats["total_games"] == 2
    assert stats["avg_price"] == 15.0
    assert stats["positive_review_rate"] == 50.0
