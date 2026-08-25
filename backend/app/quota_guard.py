import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

USAGE_FILE = Path(__file__).resolve().parent.parent / "data" / "gemini_usage.json"

# Google's free tier caps gemini-3.6-flash at 20 requests/day (see the 429 error text:
# "limit: 20, model: gemini-3.6-flash"). Default a couple below that so our own count
# drifting slightly from Google's still fails safely before a real 429 mid-run.
DAILY_BUDGET = int(os.getenv("GEMINI_DAILY_CALL_BUDGET", "18"))

_lock = threading.Lock()


class BudgetExceededError(RuntimeError):
    """Raised when the local daily Gemini call budget is already used up. Distinct
    from QuotaExceededError (Google's own 429): this stops the call before it's even
    made, so a run that's doomed to fail doesn't also waste one of the real requests."""


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _load() -> dict:
    if not USAGE_FILE.exists():
        return {"date": _today(), "count": 0}
    try:
        data = json.loads(USAGE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"date": _today(), "count": 0}
    if data.get("date") != _today():
        return {"date": _today(), "count": 0}
    return data


def _save(data: dict) -> None:
    USAGE_FILE.parent.mkdir(parents=True, exist_ok=True)
    USAGE_FILE.write_text(json.dumps(data), encoding="utf-8")


def get_usage() -> dict:
    with _lock:
        data = _load()
        return {
            "date": data["date"],
            "count": data["count"],
            "budget": DAILY_BUDGET,
            "remaining": max(0, DAILY_BUDGET - data["count"]),
        }


def check_and_reserve() -> None:
    """Call immediately before making a Gemini API call. Raises BudgetExceededError
    if today's self-imposed budget is used up; otherwise reserves one call."""
    with _lock:
        data = _load()
        if data["count"] >= DAILY_BUDGET:
            raise BudgetExceededError(
                f"Local daily Gemini call budget ({DAILY_BUDGET} calls) is used up for "
                f"today ({data['date']} UTC). This is a self-imposed limit to avoid "
                "burning through Google's free-tier quota via repeated retries - raise "
                "GEMINI_DAILY_CALL_BUDGET or wait for tomorrow's reset."
            )
        data["count"] += 1
        _save(data)
