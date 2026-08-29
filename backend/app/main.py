import json
import logging
import os
import threading
import uuid
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from fastapi import APIRouter, FastAPI, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("steam_etl.main")

from . import analytics_queries, db, etl_runner, quota_guard  # noqa: E402  (needs load_dotenv() first)
from .format_detector import detect_format  # noqa: E402
from .models import ETLJobStatus, UploadResponse  # noqa: E402

APP_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = APP_ROOT.parent
LANDING_DIR = APP_ROOT / "landing"
GENERATED_ETL_DIR = APP_ROOT / "generated_etl"
# In Docker the built frontend is copied to /app/frontend_dist (see Dockerfile); locally
# (no env var set) it defaults to the sibling frontend/dist produced by `npm run build`.
FRONTEND_DIST = Path(os.getenv("FRONTEND_DIST_PATH", str(REPO_ROOT / "frontend" / "dist")))
LANDING_DIR.mkdir(parents=True, exist_ok=True)
GENERATED_ETL_DIR.mkdir(parents=True, exist_ok=True)

db.init_db()

JOBS_FILE = APP_ROOT / "data" / "jobs.json"
_jobs_lock = threading.Lock()


def _persist_jobs() -> None:
    """Job state otherwise lives only in this process's memory, so it's lost on
    every container restart and can look "erased" if you navigate away and the
    server happened to restart (e.g. during active development) before you check
    back. Persisting to disk means a page revisit always gets the real last state."""
    try:
        JOBS_FILE.parent.mkdir(parents=True, exist_ok=True)
        JOBS_FILE.write_text(
            json.dumps({jid: job.model_dump() for jid, job in _jobs.items()}),
            encoding="utf-8",
        )
    except OSError:
        logger.warning("Failed to persist job state", exc_info=True)


def _load_jobs() -> None:
    if not JOBS_FILE.exists():
        return
    try:
        raw = json.loads(JOBS_FILE.read_text(encoding="utf-8"))
        for jid, data in raw.items():
            _jobs[jid] = ETLJobStatus(**data)
        logger.info("Loaded %d persisted job(s) from disk", len(raw))
    except (json.JSONDecodeError, OSError, ValueError):
        logger.warning("Failed to load persisted job state", exc_info=True)


def _set_job(job_id: str, job: ETLJobStatus) -> None:
    with _jobs_lock:
        _jobs[job_id] = job
        _persist_jobs()


app = FastAPI(title="Steam Scraper")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

api = APIRouter(prefix="/api")

# In-memory registries (jobs are also persisted to disk, see _persist_jobs/_load_jobs
# above). Fine for a single-process demo/research app; would move to the database or a
# task queue for anything long-lived or multi-worker.
_files: dict[str, dict] = {}
_jobs: dict[str, ETLJobStatus] = {}
_load_jobs()


@api.post("/upload", response_model=UploadResponse)
async def upload(file: UploadFile):
    content = await file.read()
    fmt = detect_format(file.filename, content)
    file_id = str(uuid.uuid4())
    dest = LANDING_DIR / f"{file_id}_{file.filename}"
    dest.write_bytes(content)
    _files[file_id] = {"path": dest, "format": fmt, "filename": file.filename}
    logger.info("Uploaded %s (%d bytes) -> file_id=%s, detected format=%s", file.filename, len(content), file_id, fmt)
    return UploadResponse(file_id=file_id, filename=file.filename, detected_format=fmt)


def _load_json_dataframe(path: Path) -> pd.DataFrame:
    with open(path, "r", encoding="utf-8") as f:
        peek = f.read(256).lstrip()

    if peek[:1] == "{":
        # Top-level JSON object keyed by id, e.g. {"<app_id>": {...fields...}, ...}.
        # pandas' default read_json orientation treats each top-level key as a COLUMN
        # (games as columns, fields as rows) instead of a row - for a file with tens
        # of thousands of games that turns a "10 row sample" into a 60M-character
        # prompt (10 attribute-rows x every game as its own column). orient="index"
        # makes each top-level key a row instead, which is what we actually want.
        df = pd.read_json(path, orient="index")
        df.index.name = "app_id"
        return df.reset_index()

    return pd.read_json(path)


def _load_dataframe(path: Path, fmt: str) -> pd.DataFrame:
    if fmt == "csv":
        return pd.read_csv(path)
    if fmt == "json":
        return _load_json_dataframe(path)
    if fmt == "xlsx":
        return pd.read_excel(path)
    # Reached only from _run_etl_job (a background thread, not a request handler) -
    # HTTPException has no HTTP response to attach to there, so a plain exception
    # with a clear message is what actually surfaces to the job's error field.
    raise ValueError(
        f"'{fmt}' isn't a supported tabular format - the ETL pipeline loads data into "
        "a pandas DataFrame (rows/columns), which csv, json, and xlsx have and this "
        "doesn't. Upload one of those instead."
    )


MAX_CELL_CHARS = 100
TARGET_SAMPLE_CHARS = 6000
MIN_SAMPLE_ROWS = 3
MAX_SAMPLE_ROWS = 30


def _truncate_cell(value: object) -> object:
    if isinstance(value, str) and len(value) > MAX_CELL_CHARS:
        return value[:MAX_CELL_CHARS] + "…"
    if isinstance(value, (list, dict)):
        text = str(value)
        if len(text) > MAX_CELL_CHARS:
            return text[:MAX_CELL_CHARS] + "…"
    return value


def _build_sample(df: pd.DataFrame) -> str:
    """Row count adapts to the table's actual width so the sample stays within a
    roughly constant character budget (TARGET_SAMPLE_CHARS) regardless of column
    count: a narrow table (few columns) gets more example rows, a wide one gets
    fewer, since a fixed row count would otherwise make wide tables' samples grow
    linearly with column count for no benefit to the LLM. Every cell is still
    individually capped at MAX_CELL_CHARS first (free-text fields, URL arrays)."""
    capped = df.head(MAX_SAMPLE_ROWS).copy()
    for col in capped.columns:
        capped[col] = capped[col].apply(_truncate_cell)

    total_available = len(capped)
    if total_available == 0:
        return capped.to_csv(index=False)

    rows = min(MIN_SAMPLE_ROWS, total_available)
    best = capped.head(rows).to_csv(index=False)
    while rows < total_available:
        rows += 1
        candidate = capped.head(rows).to_csv(index=False)
        if len(candidate) > TARGET_SAMPLE_CHARS:
            break
        best = candidate
    return best


def _run_etl_job(job_id: str, file_id: str, meta: dict) -> None:
    def report_progress(logs: list) -> None:
        current = _jobs[job_id]
        _set_job(job_id, current.model_copy(update={"logs": logs}))

    def report_step(msg: str) -> None:
        current = _jobs[job_id]
        _set_job(job_id, current.model_copy(update={"current_step": msg}))

    try:
        report_step("Loading and parsing the uploaded file...")
        df = _load_dataframe(meta["path"], meta["format"])
        sample = _build_sample(df)

        conn = db.get_connection()
        try:
            outcome = etl_runner.run_etl_with_retries(
                file_format=meta["format"],
                df=df,
                conn=conn,
                ddl=db.get_ddl_text(),
                sample=sample,
                on_progress=report_progress,
                on_step=report_step,
            )
            if outcome["status"] == "success":
                conn.commit()
                report_step("Removing games with any missing field...")
                removed = db.remove_incomplete_games(conn)
                if any(removed.values()):
                    logger.info("Removed incomplete games after job %s: %s", job_id, removed)
                    if outcome.get("result"):
                        outcome["result"]["removed_incomplete"] = removed["dim_game"]
            else:
                conn.rollback()
        finally:
            conn.close()

        if outcome.get("code"):
            artifact_path = GENERATED_ETL_DIR / f"{meta['format']}_{job_id}.py"
            artifact_path.write_text(outcome["code"], encoding="utf-8")

        _set_job(job_id, ETLJobStatus(
            job_id=job_id,
            file_id=file_id,
            status=outcome["status"],
            generated_code=outcome.get("code"),
            logs=outcome.get("logs", []),
            result=outcome.get("result"),
            error=outcome.get("error"),
        ))
    except Exception as exc:  # keeps a crash in the background thread from vanishing silently
        logger.exception("ETL job %s crashed", job_id)
        _set_job(job_id, ETLJobStatus(
            job_id=job_id,
            file_id=file_id,
            status="failed",
            error=f"{exc.__class__.__name__}: {exc}",
        ))


@api.post("/etl/run/{file_id}", response_model=ETLJobStatus)
def run_etl(file_id: str):
    meta = _files.get(file_id)
    if meta is None:
        raise HTTPException(404, "Unknown file_id")

    job_id = str(uuid.uuid4())
    initial_status = ETLJobStatus(job_id=job_id, file_id=file_id, status="running", logs=[])
    _set_job(job_id, initial_status)

    logger.info("Starting ETL job %s for file_id=%s (format=%s)", job_id, file_id, meta["format"])
    threading.Thread(target=_run_etl_job, args=(job_id, file_id, meta), daemon=True).start()

    return initial_status


@api.get("/etl/status/{job_id}", response_model=ETLJobStatus)
def etl_status(job_id: str):
    job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "Unknown job_id")
    return job


@api.get("/games")
def list_games(
    q: str | None = None,
    sort: str = "snapshot_date",
    dir: str = "desc",
    limit: int = 50,
    offset: int = 0,
):
    limit = max(1, min(limit, 1000))
    offset = max(0, offset)
    conn = db.get_connection()
    try:
        rows, total = analytics_queries.list_games(
            conn, search=q, sort_key=sort, sort_dir=dir, limit=limit, offset=offset
        )
        return {"rows": rows, "total": total}
    finally:
        conn.close()


@api.get("/games/{app_id}/history")
def game_price_history(app_id: str):
    conn = db.get_connection()
    try:
        return analytics_queries.price_history_for_game(conn, app_id)
    finally:
        conn.close()


@api.get("/analytics/price-by-year")
def analytics_price_by_year():
    conn = db.get_connection()
    try:
        return analytics_queries.price_by_release_year(conn)
    finally:
        conn.close()


@api.get("/analytics/summary")
def analytics_summary():
    conn = db.get_connection()
    try:
        return analytics_queries.summary_stats(conn)
    finally:
        conn.close()


@api.delete("/warehouse")
def clear_warehouse():
    logger.info("Clearing warehouse data (dim_game, dim_genre, bridge_game_genre, fact_game)")
    db.clear_data()
    return {"status": "cleared"}


@api.get("/gemini-usage")
def gemini_usage():
    return quota_guard.get_usage()


app.include_router(api)

# Serve the built frontend (npm run build -> frontend/dist) as static files, so the
# whole app is reachable from a single origin/port. Only active when a build exists;
# in local dev without a build, only the /api/* routes above are served (run the
# Vite dev server separately on :5173, which proxies /api to this backend).
if FRONTEND_DIST.is_dir():
    assets_dir = FRONTEND_DIST / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="frontend-assets")

    @app.get("/{full_path:path}")
    def serve_spa(full_path: str):
        # Without this, an unmatched /api/* path (typo, removed endpoint) would fall
        # through to here and silently return the SPA's index.html with a 200 instead
        # of a proper 404 - masking a real bug as an empty page.
        if full_path.startswith("api/"):
            raise HTTPException(404, "Not Found")
        candidate = FRONTEND_DIST / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(FRONTEND_DIST / "index.html")
