import concurrent.futures
import re
import sqlite3
import time

RESULT_ROW_CAP = 500
QUERY_TIMEOUT_SECONDS = 20

# Allowlist, not a denylist: this runs arbitrary text typed into a web form against
# a live database with no auth in front of it. Only statements that can't modify
# data or schema are permitted - everything else (INSERT/UPDATE/DELETE/DROP/ALTER/
# PRAGMA/ATTACH/...) is rejected by simply not being on this list, rather than
# trying to enumerate and block every dangerous keyword.
_ALLOWED_LEADING_KEYWORDS = ("SELECT", "WITH", "EXPLAIN")


class QueryError(ValueError):
    """A submitted query was rejected (not read-only, multi-statement, or timed out)."""


def _strip_leading_comments(sql: str) -> str:
    sql = sql.strip()
    while True:
        if sql.startswith("--"):
            newline = sql.find("\n")
            sql = sql[newline + 1 :] if newline != -1 else ""
        elif sql.startswith("/*"):
            end = sql.find("*/")
            sql = sql[end + 2 :] if end != -1 else ""
        else:
            break
        sql = sql.strip()
    return sql


def _validate_readonly(sql: str) -> str:
    stripped = sql.strip().rstrip(";").strip()
    if not stripped:
        raise QueryError("Query is empty.")
    if ";" in stripped:
        # Rejects a query with ';' anywhere, including inside a string literal - a
        # false positive there is an acceptable cost for not having to actually
        # parse the SQL to tell a literal from a second stacked statement.
        raise QueryError("Only a single statement is allowed - remove the ';'.")

    checked = _strip_leading_comments(stripped)
    first_word_match = re.match(r"[A-Za-z]+", checked)
    first_word = first_word_match.group(0).upper() if first_word_match else ""
    if first_word not in _ALLOWED_LEADING_KEYWORDS:
        raise QueryError(
            "Only read-only queries are allowed here (SELECT, WITH ... SELECT, or "
            "EXPLAIN) - this console can't modify the warehouse."
        )
    return stripped


def run_readonly_query(conn: sqlite3.Connection, sql: str) -> dict:
    stripped = _validate_readonly(sql)

    def run():
        cursor = conn.execute(stripped)
        columns = [d[0] for d in cursor.description] if cursor.description else []
        rows = cursor.fetchmany(RESULT_ROW_CAP + 1)
        return columns, rows

    started = time.monotonic()
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        future = executor.submit(run)
        try:
            columns, rows = future.result(timeout=QUERY_TIMEOUT_SECONDS)
        except concurrent.futures.TimeoutError:
            # future.result() timing out does NOT stop the query - it keeps running
            # in the worker thread, and a plain `with ThreadPoolExecutor(...)` here
            # would block on shutdown waiting for that same runaway thread, defeating
            # the timeout entirely (confirmed with a deliberately slow recursive CTE:
            # the "timeout" didn't return for 30+ seconds). conn.interrupt() is
            # SQLite's real cross-thread cancellation call; wait briefly for the
            # worker to unwind from it before returning, so the caller's conn.close()
            # right after this can't race with the worker thread still touching conn.
            conn.interrupt()
            try:
                future.result(timeout=5)
            except Exception:
                pass
            raise QueryError(
                f"Query did not finish within {QUERY_TIMEOUT_SECONDS}s and was "
                "cancelled - add a WHERE clause or LIMIT to narrow it down."
            )
    finally:
        executor.shutdown(wait=False)
    elapsed_ms = (time.monotonic() - started) * 1000

    truncated = len(rows) > RESULT_ROW_CAP
    rows = rows[:RESULT_ROW_CAP]

    return {
        "columns": columns,
        "rows": [list(r) for r in rows],
        "row_count": len(rows),
        "truncated": truncated,
        "elapsed_ms": round(elapsed_ms, 1),
    }
