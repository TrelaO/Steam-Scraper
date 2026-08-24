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

from . import analytics_queries, db, etl_runner  # noqa: E402  (needs load_dotenv() first)
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

app = FastAPI(title="Steam Scraper")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

api = APIRouter(prefix="/api")

# In-memory registries. Fine for a single-process demo/research app; would move to the
# database or a task queue for anything long-lived or multi-worker.
_files: dict[str, dict] = {}
_jobs: dict[str, ETLJobStatus] = {}


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


def _load_dataframe(path: Path, fmt: str) -> pd.DataFrame:
    if fmt == "csv":
        return pd.read_csv(path)
    if fmt == "json":
        return pd.read_json(path)
    if fmt == "xlsx":
        return pd.read_excel(path)
    raise HTTPException(400, f"Unsupported format: {fmt}")


def _run_etl_job(job_id: str, file_id: str, meta: dict) -> None:
    def report_progress(logs: list) -> None:
        current = _jobs[job_id]
        _jobs[job_id] = current.model_copy(update={"logs": logs})

    try:
        df = _load_dataframe(meta["path"], meta["format"])
        sample = df.head(10).to_csv(index=False)

        conn = db.get_connection()
        try:
            outcome = etl_runner.run_etl_with_retries(
                file_format=meta["format"],
                df=df,
                conn=conn,
                ddl=db.get_ddl_text(),
                sample=sample,
                on_progress=report_progress,
            )
            if outcome["status"] == "success":
                conn.commit()
            else:
                conn.rollback()
        finally:
            conn.close()

        if outcome.get("code"):
            artifact_path = GENERATED_ETL_DIR / f"{meta['format']}_{job_id}.py"
            artifact_path.write_text(outcome["code"], encoding="utf-8")

        _jobs[job_id] = ETLJobStatus(
            job_id=job_id,
            file_id=file_id,
            status=outcome["status"],
            generated_code=outcome.get("code"),
            logs=outcome.get("logs", []),
            result=outcome.get("result"),
            error=outcome.get("error"),
        )
    except Exception as exc:  # keeps a crash in the background thread from vanishing silently
        logger.exception("ETL job %s crashed", job_id)
        _jobs[job_id] = ETLJobStatus(
            job_id=job_id,
            file_id=file_id,
            status="failed",
            error=f"{exc.__class__.__name__}: {exc}",
        )


@api.post("/etl/run/{file_id}", response_model=ETLJobStatus)
def run_etl(file_id: str):
    meta = _files.get(file_id)
    if meta is None:
        raise HTTPException(404, "Unknown file_id")

    job_id = str(uuid.uuid4())
    initial_status = ETLJobStatus(job_id=job_id, file_id=file_id, status="running", logs=[])
    _jobs[job_id] = initial_status

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
def list_games():
    conn = db.get_connection()
    try:
        return analytics_queries.list_games(conn)
    finally:
        conn.close()


@api.delete("/warehouse")
def clear_warehouse():
    logger.info("Clearing warehouse data (dim_game, dim_genre, bridge_game_genre, fact_game)")
    db.clear_data()
    return {"status": "cleared"}


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
