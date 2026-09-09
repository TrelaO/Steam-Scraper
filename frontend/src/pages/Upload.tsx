import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { FormatComparison, getFormatComparison, runEtl, uploadFile } from "../api/client";
import { useUploadState } from "../uploadState";

const TABULAR_FORMATS = new Set(["csv", "json", "xlsx"]);
const FORMAT_ORDER = ["csv", "json", "xlsx"];

function FormatComparisonCard() {
  const [comparison, setComparison] = useState<FormatComparison | null>(null);

  useEffect(() => {
    getFormatComparison()
      .then(setComparison)
      .catch(() => {
        /* non-fatal - this card is meta-info about past runs, not core functionality */
      });
  }, []);

  const formats = comparison
    ? FORMAT_ORDER.filter((f) => f in comparison).concat(
        Object.keys(comparison).filter((f) => !FORMAT_ORDER.includes(f))
      )
    : [];

  if (!comparison || formats.length === 0) return null;

  return (
    <div className="card">
      <h2 style={{ marginTop: 0 }}>How the LLM has done, by format</h2>
      <p className="muted" style={{ marginTop: -6, marginBottom: 14 }}>
        The same Steam dataset in different shapes tends to produce different generated code —
        this is the actual comparison the project is about, aggregated from every run archived
        in <code>generated_etl/</code>.
      </p>
      <div className="table-wrap">
        <table className="data-table">
          <thead>
            <tr>
              <th>Format</th>
              <th>Runs</th>
              <th>Success rate</th>
              <th>Avg. attempts</th>
              <th>Most common failures</th>
            </tr>
          </thead>
          <tbody>
            {formats.map((fmt) => {
              const s = comparison[fmt];
              return (
                <tr key={fmt}>
                  <td>{fmt}</td>
                  <td className="numeric">{s.runs}</td>
                  <td className="numeric">
                    {s.success_rate === null ? "—" : `${s.success_rate.toFixed(0)}%`}
                  </td>
                  <td className="numeric">
                    {s.avg_attempts === null ? "—" : s.avg_attempts.toFixed(1)}
                  </td>
                  <td>
                    {s.top_errors.length === 0
                      ? "—"
                      : s.top_errors.map((e) => `${e.type} (${e.count})`).join(", ")}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default function Upload() {
  const { uploaded, setUploaded, busy, setBusy, error, setError } = useUploadState();
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

  const isTabular = uploaded ? TABULAR_FORMATS.has(uploaded.detected_format) : true;

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
          <span className="dropzone-hint">
            Any file type accepted — only csv, json, and xlsx can actually be processed
          </span>
          <input
            type="file"
            disabled={busy}
            onChange={(e) => e.target.files?.[0] && handleFile(e.target.files[0])}
          />
        </label>

        {uploaded && (
          <div className="file-summary">
            <span className="file-summary-name">{uploaded.filename}</span>
            <span className={`badge ${isTabular ? "badge-neutral" : "badge-warning"}`}>
              {uploaded.detected_format}
            </span>
            <button className="btn" onClick={handleRun} disabled={busy}>
              {busy ? "Running..." : "Generate & run ETL"}
            </button>
          </div>
        )}

        {uploaded && !isTabular && (
          <p className="muted" style={{ marginTop: 10 }}>
            "{uploaded.detected_format}" isn't tabular data (no rows/columns) — the ETL run
            will fail cleanly with an explanation if you continue, since there's nothing to
            map into the warehouse schema.
          </p>
        )}

        {error && <div className="error-box">{error}</div>}
      </div>

      <FormatComparisonCard />
    </div>
  );
}
