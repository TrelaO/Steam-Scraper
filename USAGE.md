# Steam Scraper — Usage Guide

A mini data warehouse for Steam game price/trend analysis, built around one idea: instead
of hand-writing ETL code for each source file format, an LLM (Google Gemini) generates the
mapping code on the fly, from the source format and the target star-schema DDL. The app
lets you upload the same Steam dataset as CSV, JSON, or XLSX, watch the LLM generate and
run the ETL for each, and compare how it does across formats — then explore the resulting
warehouse and get simple decision-support signals out of it.

This guide is about *using* the running app. For architecture/internals, see the (Polish)
[README.md](README.md) — most of it (code, comments, API paths) is in English regardless.

## Requirements

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) — the only thing you
  need installed. No local Python/Node setup required.
- A Gemini API key, free at [aistudio.google.com](https://aistudio.google.com/apikey).

## Starting the app

1. Copy `.env.example` to `.env` and paste your key into `GEMINI_API_KEY`.
2. Run it:
   - **Windows:** double-click [start.bat](start.bat).
   - **Mac/Linux:** `./start.sh` (or double-click it, if your file manager runs it).
   - **Manually, any OS:** `docker compose up --build`.
3. Wait for the build (a minute or two the first time), then open
   **http://localhost:8000** — the launcher scripts do this for you automatically.

Don't have a key yet, or want to change it later without editing `.env` and restarting?
Click the **⚙ gear icon** in the top navbar once the app is open — see [Settings](#settings-api-key)
below.

## The three pages

### 1. Upload

Drag a file onto the dropzone, or click it to browse. Any file is accepted; only CSV,
JSON, and XLSX are actually processable — anything else (a PDF, a screenshot, ...) is
detected honestly and the app tells you it can't be mapped, rather than pretending it can.

Once a file is accepted, click **Generate & run ETL**. This kicks off:

1. The file's format and a small representative sample of its rows are sent to Gemini
   along with the warehouse's schema (DDL).
2. Gemini writes a Python function that maps the source columns onto the warehouse's
   dimension/fact tables.
3. That code runs in an isolated subprocess against your *actual* uploaded file (not just
   the sample) — sandboxed (no filesystem/network access, only a fixed allowlist of
   data-munging libraries) and time-bounded (killed outright if it hangs).
4. If it errors, the error is fed back to Gemini for a corrected attempt (up to 3 tries
   total) before giving up.

You'll be redirected to a **Pipeline run** page to watch this happen live.

Below the upload box, a **"How the LLM has done, by format"** table shows aggregate stats
from every past run (success rate, average attempts, most common failure types) — the
actual research question this project is about.

### 2. Pipeline run

Shows the live status of one ETL run: which attempt it's on, a step-by-step status line,
and (once finished) the rows written per table, the generated Python code itself, a
**field mapping table** (Gemini's own explanation of which source column maps to which
warehouse column and why), and the full attempt log if there were retries.

### 3. Dashboard

The warehouse's contents, once something has been loaded:

- **KPI tiles** — games in warehouse, average price, % free-to-play, positive review
  rate, average playtime, most common genre.
- **Decision support** — two rule-based lists: games priced above average with no active
  discount and strong reviews (*discount candidates* — a sale is likely to convert), and
  the same price/discount situation but with weak reviews (*reprice candidates* — the
  price itself looks like the problem). Click a row to see that game's price history.
- **Price & discount by release-year cohort** — a bar chart, since a single-snapshot
  import can't show a real time series (see the note on that page).
- **The full table** — every game, filterable (name, prefix match) and sortable by any
  column. Click a row for its price history chart. A **🗑 Clear database** button wipes
  the loaded data (not the seeded reference tables) if you want to start over.

### 4. Warehouse

Two things:

- **Table relationships** — a diagram of the star schema (`fact_game` in the middle,
  its dimensions and the genre bridge table around it), with live row counts per table.
- **SQL console** — a **read-only** query box (`SELECT` / `WITH` / `EXPLAIN` only; capped
  at 500 rows and 20 seconds) for exploring the data directly. A few example queries are
  one click away, your last 10 queries are remembered (locally, in your browser), and
  results can be exported to CSV.

### Settings (API key)

Click **⚙** in the navbar. You can paste an API key here instead of (or in addition to)
the one in `.env` — a key set this way takes priority immediately, no restart needed.
Useful for trying a different key without touching the `.env` file, or for a shared/demo
deployment where editing `.env` isn't convenient. Clearing it reverts to `.env`. The key
is never shown back to you in full once saved — only a masked preview (e.g. `••••1234`)
and whether it's currently coming from your override or from `.env`.

## Getting a dataset to try

The project is built around the Kaggle
["Steam Games Dataset"](https://www.kaggle.com/datasets/fronkongames/steam-games-dataset):
download it, and upload the CSV and JSON versions separately through the Upload page to
compare how the LLM handles each. Any XLSX with similar tabular game data works too, to
cover all three formats.

**Large files:** the full dataset is large (hundreds of MB, 100k+ games) and the
LLM-generated code usually processes rows in a plain Python loop — at that scale a single
attempt can hit the execution time limit before finishing. For trying the pipeline out,
cut a smaller sample first (e.g. the first few hundred rows) and upload that instead.

## Troubleshooting

- **"Warehouse contents" / Dashboard looks empty right after a successful run.** Check the
  result on the Pipeline run page: if it shows `removed_incomplete`, the ETL wrote rows
  but a data-quality cleanup step then removed games missing a required field (this is
  usually a data issue, not a bug — one column your source doesn't actually have). If it
  shows `incomplete_cleanup_skipped: true`, the app detected that cleanup would have
  removed *everything* and skipped it instead, on purpose — refresh the Dashboard, your
  data should be there.
- **A run fails immediately with a quota/budget message.** Either Google's own free-tier
  rate limit was hit (wait for it to reset, shown in the error), or the app's own
  self-imposed daily call budget (`GEMINI_DAILY_CALL_BUDGET` in `.env`, default 200) is
  used up for the day — this is a safety net against a runaway loop burning your real
  quota, not Google's own limit. Check current usage via the badge in the navbar.
- **"No API key configured."** Set one in `.env` (`GEMINI_API_KEY`) or via ⚙ Settings.
- **The app won't start / port 8000 already in use.** Something else is using that port,
  or a previous container is still running — check with `docker compose logs` and
  `docker compose down` if needed, then start again.

## Running tests / without Docker

Both are optional and covered in the (Polish) [README.md](README.md#testy) — short
version: `cd backend && pip install -r ../requirements.txt && pytest` runs the backend
test suite (no API key or network needed), and the README's "Uruchomienie — bez Dockera"
section covers running the backend/frontend as two separate dev processes.
