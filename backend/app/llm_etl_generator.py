import os
import re

from google import genai

MODEL_NAME = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")

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
- For dim_date, look up the existing date_sk for the snapshot/import date (today) rather than
  inserting new rows.
- For dim_platform, look up the existing platform_sk matching the game's OS support flags
  rather than inserting new rows.
- Do NOT call conn.commit() or conn.close() — the caller manages the transaction.
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


def generate_etl_code(
    file_format: str,
    ddl: str,
    sample: str,
    previous_code: str | None = None,
    previous_error: str | None = None,
) -> str:
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    prompt = _build_prompt(file_format, ddl, sample, previous_code, previous_error)
    response = client.models.generate_content(model=MODEL_NAME, contents=prompt)
    return _extract_code(response.text)
