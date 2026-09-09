import re
from pathlib import Path

from .models import ETLJobStatus

# generated_etl/ artifact filenames are "<format>_<job_id>.py" (see main.py's
# _run_etl_job) - the job_id is the only reliable link back to that run's attempt
# log, since the in-memory _files registry (which also knows the format) doesn't
# survive a restart the way the persisted jobs.json / generated_etl/ archive does.
_ARTIFACT_RE = re.compile(r"^(csv|json|xlsx)_([0-9a-f-]+)\.py$")


def _error_type(error_text: str) -> str:
    """Pulls the exception class name off a formatted traceback's last line (see
    etl_runner._format_generated_code_traceback), e.g. "KeyError: 'app_id'" ->
    "KeyError". Falls back to "Unknown" for anything that doesn't match that shape."""
    lines = [line for line in error_text.strip().splitlines() if line.strip()]
    if not lines:
        return "Unknown"
    match = re.match(r"([A-Za-z_][\w.]*):", lines[-1])
    return match.group(1) if match else "Unknown"


def format_comparison(generated_etl_dir: Path, jobs: dict[str, ETLJobStatus]) -> dict:
    """Aggregates, per source format, how the LLM's ETL-generation attempts actually
    went: how many runs, what fraction succeeded, how many attempts it typically took,
    and the most common failure types - the actual research question this project is
    built around (autogenerating ETL code for the same data in different formats).

    Matches each generated_etl/<format>_<job_id>.py artifact back to that job's
    attempt log via job_id; an artifact whose job is no longer in `jobs` (e.g. the
    persisted state was cleared) still counts as a run, just without attempt/error
    detail.
    """
    buckets: dict[str, dict] = {}
    for path in sorted(generated_etl_dir.glob("*.py")):
        match = _ARTIFACT_RE.match(path.name)
        if not match:
            continue
        fmt, job_id = match.group(1), match.group(2)
        bucket = buckets.setdefault(
            fmt,
            {"runs": 0, "known_runs": 0, "successes": 0, "total_attempts": 0, "error_counts": {}},
        )
        bucket["runs"] += 1

        job = jobs.get(job_id)
        if job is None:
            # Artifact outlived the job history (e.g. jobs.json was cleared) - still
            # a real run, just with no attempt/outcome detail to aggregate.
            continue
        bucket["known_runs"] += 1
        if job.status == "success":
            bucket["successes"] += 1
        bucket["total_attempts"] += len(job.logs) or 1
        for entry in job.logs:
            if entry.status == "error" and entry.error:
                err_type = _error_type(entry.error)
                bucket["error_counts"][err_type] = bucket["error_counts"].get(err_type, 0) + 1

    result: dict[str, dict] = {}
    for fmt, bucket in buckets.items():
        known_runs = bucket["known_runs"]
        top_errors = sorted(bucket["error_counts"].items(), key=lambda kv: -kv[1])[:5]
        result[fmt] = {
            "runs": bucket["runs"],
            "successes": bucket["successes"],
            "success_rate": (100.0 * bucket["successes"] / known_runs) if known_runs else None,
            "avg_attempts": (bucket["total_attempts"] / known_runs) if known_runs else None,
            "top_errors": [{"type": t, "count": c} for t, c in top_errors],
        }
    return result
