import sqlite3
import time

import pytest

from app.sql_console import QueryError, RESULT_ROW_CAP, run_readonly_query


@pytest.fixture()
def memdb():
    # check_same_thread=False, matching db.get_connection(): run_readonly_query
    # actually executes on a worker thread (see sql_console.py's timeout handling),
    # same as every real connection this module is ever called with in production.
    connection = sqlite3.connect(":memory:", check_same_thread=False)
    connection.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT)")
    connection.executemany("INSERT INTO t (name) VALUES (?)", [(f"row{i}",) for i in range(5)])
    connection.commit()
    yield connection
    connection.close()


@pytest.mark.parametrize("sql", ["SELECT * FROM t", "select * from t", "  SELECT 1  "])
def test_select_variants_allowed(memdb, sql):
    result = run_readonly_query(memdb, sql)
    assert "columns" in result and "rows" in result


def test_with_cte_allowed(memdb):
    result = run_readonly_query(memdb, "WITH x AS (SELECT 1 AS n) SELECT n FROM x")
    assert result["rows"] == [[1]]


def test_explain_allowed(memdb):
    result = run_readonly_query(memdb, "EXPLAIN SELECT * FROM t")
    assert result["row_count"] >= 1


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM t",
        "UPDATE t SET name = 'x'",
        "INSERT INTO t (name) VALUES ('x')",
        "DROP TABLE t",
        "ALTER TABLE t ADD COLUMN x TEXT",
        "PRAGMA table_info(t)",
        "ATTACH DATABASE ':memory:' AS other",
        "",
        "   ",
    ],
)
def test_non_select_statements_rejected(memdb, sql):
    with pytest.raises(QueryError):
        run_readonly_query(memdb, sql)


def test_stacked_statements_rejected(memdb):
    with pytest.raises(QueryError, match="single statement"):
        run_readonly_query(memdb, "SELECT 1; DROP TABLE t")


def test_leading_comment_before_select_is_still_allowed(memdb):
    result = run_readonly_query(memdb, "-- a comment\nSELECT 1")
    assert result["rows"] == [[1]]


def test_leading_comment_before_forbidden_statement_still_rejected(memdb):
    with pytest.raises(QueryError):
        run_readonly_query(memdb, "-- sneaky\nDELETE FROM t")


def test_row_cap_truncates_and_flags(memdb):
    memdb.executemany(
        "INSERT INTO t (name) VALUES (?)", [(f"extra{i}",) for i in range(RESULT_ROW_CAP + 50)]
    )
    memdb.commit()
    result = run_readonly_query(memdb, "SELECT * FROM t")
    assert result["row_count"] == RESULT_ROW_CAP
    assert result["truncated"] is True


def test_under_cap_not_flagged_truncated(memdb):
    result = run_readonly_query(memdb, "SELECT * FROM t")
    assert result["row_count"] == 5
    assert result["truncated"] is False


def test_timeout_actually_cancels_and_connection_stays_usable(memdb, monkeypatch):
    from app import sql_console

    monkeypatch.setattr(sql_console, "QUERY_TIMEOUT_SECONDS", 1)

    slow_query = """
        WITH RECURSIVE spin(x) AS (
            SELECT 1 UNION ALL SELECT x + 1 FROM spin WHERE x < 100000000
        )
        SELECT COUNT(*) FROM spin
    """
    start = time.monotonic()
    with pytest.raises(QueryError, match="did not finish"):
        run_readonly_query(memdb, slow_query)
    elapsed = time.monotonic() - start
    # Generous upper bound (not tied to the 1s limit itself) - this is the
    # regression test for the original bug: a naive future.result(timeout=...)
    # never actually stopped the query and this used to hang for the query's
    # full runtime instead of returning near the configured timeout.
    assert elapsed < 10

    # The connection must still be usable afterward - proves conn.interrupt()
    # cancelled the query without leaving the connection/worker thread in a bad
    # state (this is exactly what the old thread+shutdown(wait=True) approach broke).
    result = run_readonly_query(memdb, "SELECT COUNT(*) FROM t")
    assert result["rows"] == [[5]]
