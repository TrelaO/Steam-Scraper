import logging
import os
import re
import time

from google import genai
from google.genai import errors as genai_errors

from . import quota_guard

logger = logging.getLogger("steam_etl.llm_etl_generator")

MODEL_NAME = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")

# Google's 429 responses can include a RetryInfo.retryDelay hint (a few seconds to
# ~1min for a short-window rate limit). If it's under this, wait it out and retry the
# SAME call once automatically - a rate limit isn't a code bug, so unlike the normal
# attempt loop, retrying with "corrected" code would be pointless; just retrying the
# identical request after the suggested delay is the correct move. A longer delay
# (e.g. a daily quota reset reported in hours) isn't worth blocking the request for.
MAX_AUTO_RETRY_DELAY_SECONDS = 90


class QuotaExceededError(RuntimeError):
    """Raised when the Gemini API rejects a call for exceeding a rate/quota limit.
    Distinct from other failures because retrying with corrected code can't fix it."""

SYSTEM_PROMPT = """You are a data engineer writing a Python ETL transformation.

You will be given:
1. The format of a source file (csv, json, or xlsx).
2. The DDL of a target SQLite star-schema warehouse.
3. A sample of the source data (a few rows), already loaded into a pandas DataFrame `df`.

Write ONE Python function with this exact signature:

    def run_etl(df, conn):
        ...

Rules:
- `df` is a pandas.DataFrame containing the FULL source dataset (not just the sample shown).
- `conn` is an open sqlite3.Connection to the warehouse. The schema already exists; do NOT
  create, drop, or alter tables.
- Map the source columns onto the target schema, handling missing/malformed values sensibly
  (e.g. skip rows without a usable app id, coerce types, split delimited genre lists).
- Use INSERT OR IGNORE / INSERT OR REPLACE as appropriate to avoid unique-constraint failures
  on re-runs (e.g. dim_game.app_id, dim_genre.genre_name).
- fact_game has a UNIQUE constraint on (game_sk, date_sk, platform_sk). Use
  INSERT OR REPLACE INTO fact_game (not plain INSERT) so re-running the same file on
  the same day updates that snapshot instead of accumulating duplicate rows.
- For dim_date, look up the existing date_sk for the snapshot/import date (today) rather than
  inserting new rows.
- For dim_platform, look up the existing platform_sk matching the game's OS support flags
  rather than inserting new rows.
- Do NOT call conn.commit() or conn.close() — the caller manages the transaction.
- A cell's value may itself be a list/array or dict, not just a scalar (e.g. a JSON
  source's "genres" column holds actual Python lists, not strings to parse). NEVER
  write `pd.isna(x)` or `x is None or pd.isna(x)` as your first check on a value that
  might be list/array-like - calling pd.isna() on an array raises "the truth value of
  an array is ambiguous". Always check `isinstance(x, (list, tuple, np.ndarray, dict))`
  BEFORE any pd.isna() call, not after, so the array/list/dict branch is reached first.
- Return a dict mapping table name to number of rows inserted, e.g.
  {"dim_game": 100, "fact_game": 100}.
- Output ONLY the Python code for this one function (plus any needed imports at the top).
  No markdown fences, no explanation text.
"""


def _build_prompt(
    file_format: str,
    ddl: str,
    sample: str,
    previous_code: str | None = None,
    previous_error: str | None = None,
) -> str:
    parts = [
        SYSTEM_PROMPT,
        f"\nSource file format: {file_format}\n",
        f"\nTarget schema DDL:\n{ddl}\n",
        f"\nSample of the source data (CSV-rendered, first rows):\n{sample}\n",
    ]
    if previous_code and previous_error:
        parts.append(
            "\nA previous attempt raised an error. Fix the bug and return the corrected "
            "full function.\n\nPrevious code:\n"
            f"{previous_code}\n\nError raised:\n{previous_error}\n"
        )
    return "\n".join(parts)


def _extract_code(text: str) -> str:
    match = re.search(r"```(?:python)?\s*(.*?)```", text, re.DOTALL)
    return match.group(1).strip() if match else text.strip()


def _extract_retry_delay_seconds(exc: genai_errors.APIError) -> float | None:
    """Pulls the RetryInfo.retryDelay hint (e.g. "30.6s") out of a 429's error
    body, if present. Defensive: the exact shape isn't a stable contract, so any
    parsing failure just means "no hint found" rather than raising."""
    try:
        details = exc.details.get("error", {}).get("details", [])
        for item in details:
            if str(item.get("@type", "")).endswith("RetryInfo"):
                delay = item.get("retryDelay", "")
                if isinstance(delay, str) and delay.endswith("s"):
                    return float(delay[:-1])
    except Exception:
        pass
    return None


def generate_etl_code(
    file_format: str,
    ddl: str,
    sample: str,
    previous_code: str | None = None,
    previous_error: str | None = None,
) -> str:
    quota_guard.check_and_reserve()

    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    prompt = _build_prompt(file_format, ddl, sample, previous_code, previous_error)
    logger.info("Calling Gemini model=%s (prompt=%d chars)...", MODEL_NAME, len(prompt))
    started = time.monotonic()
    try:
        response = client.models.generate_content(model=MODEL_NAME, contents=prompt)
    except genai_errors.APIError as exc:
        if exc.code == 429 or exc.status == "RESOURCE_EXHAUSTED":
            retry_delay = _extract_retry_delay_seconds(exc)
            if retry_delay is not None and retry_delay <= MAX_AUTO_RETRY_DELAY_SECONDS:
                logger.warning(
                    "Gemini rate limit hit, waiting %.0fs and retrying once: %s",
                    retry_delay, exc.message,
                )
                time.sleep(retry_delay + 1)
                try:
                    response = client.models.generate_content(model=MODEL_NAME, contents=prompt)
                    logger.info(
                        "Gemini responded in %.1fs after rate-limit retry (%d chars)",
                        time.monotonic() - started, len(response.text),
                    )
                    return _extract_code(response.text)
                except genai_errors.APIError as retry_exc:
                    exc = retry_exc
            logger.warning("Gemini quota/rate limit hit: %s", exc.message)
            raise QuotaExceededError(
                f"Gemini API quota exceeded for model '{MODEL_NAME}': {exc.message} "
                "This is a plan/billing limit, not a code bug - retrying with corrected "
                "code won't help. Wait for the quota to reset or upgrade your Google AI "
                "Studio plan, then try again."
            ) from exc
        raise
    logger.info("Gemini responded in %.1fs (%d chars)", time.monotonic() - started, len(response.text))
    return _extract_code(response.text)
