import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { runEtl, uploadFile, UploadResponse } from "../api/client";

export default function Upload() {
  const [uploaded, setUploaded] = useState<UploadResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();

  async function handleFile(file: File) {
    setError(null);
    setBusy(true);
    setUploaded(null);
    try {
      const res = await uploadFile(file);
      setUploaded(res);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function handleRun() {
    if (!uploaded) return;
    setError(null);
    setBusy(true);
    try {
      const job = await runEtl(uploaded.file_id);
      navigate(`/pipeline/${job.job_id}`, { state: { job } });
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="page">
      <div className="page-header">
        <h1>Upload source data</h1>
        <p>Accepts the same Steam dataset in CSV, JSON, or XLSX form.</p>
      </div>

      <div className="card">
        <label className={`dropzone${busy ? " disabled" : ""}`}>
          <span className="dropzone-title">
            {busy ? "Working..." : "Click to choose a file"}
          </span>
          <span className="dropzone-hint">.csv, .json, or .xlsx</span>
          <input
            type="file"
            accept=".csv,.json,.xlsx"
            disabled={busy}
            onChange={(e) => e.target.files?.[0] && handleFile(e.target.files[0])}
          />
        </label>

        {uploaded && (
          <div className="file-summary">
            <span className="file-summary-name">{uploaded.filename}</span>
            <span className="badge badge-neutral">{uploaded.detected_format}</span>
            <button className="btn" onClick={handleRun} disabled={busy}>
              {busy ? "Running..." : "Generate & run ETL"}
            </button>
          </div>
        )}

        {error && <div className="error-box">{error}</div>}
      </div>
    </div>
  );
}
