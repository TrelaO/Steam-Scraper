import uuid
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

from . import analytics_queries, db, etl_runner  # noqa: E402  (needs load_dotenv() first)
from .format_detector import detect_format  # noqa: E402
from .models import ETLJobStatus, UploadResponse  # noqa: E402

APP_ROOT = Path(__file__).resolve().parent.parent
LANDING_DIR = APP_ROOT / "landing"
GENERATED_ETL_DIR = APP_ROOT / "generated_etl"
LANDING_DIR.mkdir(parents=True, exist_ok=True)
GENERATED_ETL_DIR.mkdir(parents=True, exist_ok=True)

db.init_db()

app = FastAPI(title="Steam AI-ETL")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory registries. Fine for a single-process demo/research app; would move to the
# database or a task queue for anything long-lived or multi-worker.
_files: dict[str, dict] = {}
_jobs: dict[str, ETLJobStatus] = {}


@app.post("/upload", response_model=UploadResponse)
async def upload(file: UploadFile):
    content = await file.read()
    fmt = detect_format(file.filename, content)
    file_id = str(uuid.uuid4())
    dest = LANDING_DIR / f"{file_id}_{file.filename}"
    dest.write_bytes(content)
    _files[file_id] = {"path": dest, "format": fmt, "filename": file.filename}
    return UploadResponse(file_id=file_id, filename=file.filename, detected_format=fmt)


def _load_dataframe(path: Path, fmt: str) -> pd.DataFrame:
    if fmt == "csv":
        return pd.read_csv(path)
    if fmt == "json":
        return pd.read_json(path)
    if fmt == "xlsx":
        return pd.read_excel(path)
    raise HTTPException(400, f"Unsupported format: {fmt}")


@app.post("/etl/run/{file_id}", response_model=ETLJobStatus)
def run_etl(file_id: str):
    meta = _files.get(file_id)
    if meta is None:
        raise HTTPException(404, "Unknown file_id")

    df = _load_dataframe(meta["path"], meta["format"])
    sample = df.head(10).to_csv(index=False)
    job_id = str(uuid.uuid4())

    conn = db.get_connection()
    try:
        outcome = etl_runner.run_etl_with_retries(
            file_format=meta["format"],
            df=df,
            conn=conn,
            ddl=db.get_ddl_text(),
            sample=sample,
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

    status = ETLJobStatus(
        job_id=job_id,
        file_id=file_id,
        status=outcome["status"],
        generated_code=outcome.get("code"),
        logs=outcome.get("logs", []),
        result=outcome.get("result"),
        error=outcome.get("error"),
    )
    _jobs[job_id] = status
    return status


@app.get("/etl/status/{job_id}", response_model=ETLJobStatus)
def etl_status(job_id: str):
    job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "Unknown job_id")
    return job


@app.get("/analytics/price-discount-by-genre-year")
def analytics_price_discount_by_genre_year():
    conn = db.get_connection()
    try:
        return analytics_queries.avg_price_discount_by_genre_year(conn)
    finally:
        conn.close()


@app.get("/analytics/price-review-correlation")
def analytics_price_review_correlation():
    conn = db.get_connection()
    try:
        return analytics_queries.price_review_correlation(conn)
    finally:
        conn.close()


@app.get("/analytics/price-variance-by-platform")
def analytics_price_variance_by_platform():
    conn = db.get_connection()
    try:
        return analytics_queries.price_variance_by_platform(conn)
    finally:
        conn.close()
