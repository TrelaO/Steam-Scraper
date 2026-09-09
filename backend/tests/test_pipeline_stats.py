from app.models import ETLAttemptLog, ETLJobStatus
from app.pipeline_stats import _error_type, format_comparison


def _artifact(tmp_path, fmt, job_id):
    (tmp_path / f"{fmt}_{job_id}.py").write_text("def run_etl(df, conn): ...", encoding="utf-8")


def _job(job_id, file_id, status, logs):
    return ETLJobStatus(job_id=job_id, file_id=file_id, status=status, logs=logs)


def test_error_type_extracts_exception_class_name():
    assert _error_type("Traceback (most recent call last):\nKeyError: 'app_id'") == "KeyError"


def test_error_type_falls_back_to_unknown_for_unparseable_text():
    assert _error_type("") == "Unknown"
    assert _error_type("something with no colon at all") == "Unknown"


def test_format_comparison_aggregates_success_and_attempts(tmp_path):
    # job_id must look like a real uuid.uuid4() (hex digits + hyphens only) - that's
    # what pipeline_stats' filename regex expects, matching how main.py actually
    # names generated_etl/ artifacts.
    _artifact(tmp_path, "csv", "1111aaaa-0000-0000-0000-000000000001")
    _artifact(tmp_path, "csv", "2222bbbb-0000-0000-0000-000000000002")
    _artifact(tmp_path, "json", "3333cccc-0000-0000-0000-000000000003")

    jobs = {
        "1111aaaa-0000-0000-0000-000000000001": _job(
            "1111aaaa-0000-0000-0000-000000000001", "file-1", "success",
            [
                ETLAttemptLog(attempt=1, status="error", error="Traceback...\nKeyError: 'x'"),
                ETLAttemptLog(attempt=2, status="success"),
            ],
        ),
        "2222bbbb-0000-0000-0000-000000000002": _job(
            "2222bbbb-0000-0000-0000-000000000002", "file-2", "failed",
            [ETLAttemptLog(attempt=1, status="error", error="Traceback...\nValueError: bad")],
        ),
        "3333cccc-0000-0000-0000-000000000003": _job(
            "3333cccc-0000-0000-0000-000000000003", "file-3", "success",
            [ETLAttemptLog(attempt=1, status="success")],
        ),
    }

    result = format_comparison(tmp_path, jobs)

    assert result["csv"]["runs"] == 2
    assert result["csv"]["successes"] == 1
    assert result["csv"]["success_rate"] == 50.0
    assert result["csv"]["avg_attempts"] == 1.5  # (2 attempts + 1 attempt) / 2 runs
    assert {"type": "KeyError", "count": 1} in result["csv"]["top_errors"]
    assert {"type": "ValueError", "count": 1} in result["csv"]["top_errors"]

    assert result["json"]["runs"] == 1
    assert result["json"]["successes"] == 1
    assert result["json"]["success_rate"] == 100.0
    assert result["json"]["top_errors"] == []

    assert "xlsx" not in result


def test_format_comparison_counts_run_even_if_job_missing_from_history(tmp_path):
    # Simulates an artifact surviving longer than jobs.json (e.g. persisted state
    # was cleared) - it should still count as a run, just without attempt detail.
    _artifact(tmp_path, "xlsx", "deadbeef-0000-0000-0000-000000000009")

    result = format_comparison(tmp_path, {})

    assert result["xlsx"]["runs"] == 1
    assert result["xlsx"]["successes"] == 0
    assert result["xlsx"]["success_rate"] is None
    assert result["xlsx"]["avg_attempts"] is None


def test_format_comparison_ignores_files_not_matching_the_naming_convention(tmp_path):
    (tmp_path / "not-an-artifact.txt").write_text("x", encoding="utf-8")
    (tmp_path / "weird_name.py").write_text("x", encoding="utf-8")

    result = format_comparison(tmp_path, {})

    assert result == {}


def test_format_comparison_on_empty_directory(tmp_path):
    assert format_comparison(tmp_path, {}) == {}
