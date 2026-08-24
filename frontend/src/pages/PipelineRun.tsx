import { useEffect, useState } from "react";
import { useLocation, useParams } from "react-router-dom";
import { ETLJobStatus, getEtlStatus } from "../api/client";

const MAX_ATTEMPTS = 3;
const POLL_INTERVAL_MS = 1500;

const STATUS_BADGE: Record<string, string> = {
  success: "badge-success",
  failed: "badge-danger",
  running: "badge-warning",
};

export default function PipelineRun() {
  const { jobId } = useParams();
  const location = useLocation();
  const initialJob = (location.state as { job?: ETLJobStatus } | null)?.job ?? null;
  const [job, setJob] = useState<ETLJobStatus | null>(initialJob);
  const [error, setError] = useState<string | null>(null);

  // Initial fetch, e.g. on a direct link or a page refresh where router state is gone.
  useEffect(() => {
    if (job || !jobId) return;
    getEtlStatus(jobId)
      .then(setJob)
      .catch((err) => setError((err as Error).message));
  }, [job, jobId]);

  // While the job is still running server-side, poll for live progress (attempts as
  // they complete) instead of leaving the user staring at a spinner with no feedback.
  useEffect(() => {
    if (!job || job.status !== "running") return;
    const id = window.setInterval(() => {
      getEtlStatus(job.job_id)
        .then(setJob)
        .catch((err) => setError((err as Error).message));
    }, POLL_INTERVAL_MS);
    return () => window.clearInterval(id);
  }, [job?.job_id, job?.status]);

  if (error) {
    return (
      <div className="page">
        <div className="error-box">{error}</div>
      </div>
    );
  }
  if (!job) {
    return (
      <div className="page">
        <p className="muted">Loading...</p>
      </div>
    );
  }

  const isRunning = job.status === "running";
  const currentAttempt = Math.min(job.logs.length + 1, MAX_ATTEMPTS);

  return (
    <div className="page">
      <div className="page-header">
        <h1>ETL run</h1>
        <p className="job-id">{job.job_id}</p>
      </div>

      <div className="card">
        <span className={`badge ${STATUS_BADGE[job.status] ?? "badge-neutral"}${isRunning ? " badge-pulse" : ""}`}>
          {job.status}
        </span>

        {isRunning && (
          <p className="muted" style={{ marginTop: 12 }}>
            Attempt {currentAttempt} of {MAX_ATTEMPTS} — calling Gemini and executing the
            generated code. Each attempt can take up to a minute; failed attempts are fed
            back to the model for a correction automatically.
          </p>
        )}

        {job.error && <div className="error-box">{job.error}</div>}

        {job.result && (
          <>
            <h2>Rows written</h2>
            <div className="result-grid">
              {Object.entries(job.result).map(([table, count]) => (
                <div className="result-tile" key={table}>
                  <div className="result-tile-value">{String(count)}</div>
                  <div className="result-tile-label">{table}</div>
                </div>
              ))}
            </div>
          </>
        )}

        {job.generated_code && (
          <>
            <h2>Generated code (final attempt)</h2>
            <pre className="code-block">{job.generated_code}</pre>
          </>
        )}

        {job.logs.length > 0 && (
          <>
            <h2>Attempt log</h2>
            {job.logs.map((entry, i) => (
              <details className="attempt" key={i} open={entry.status === "error"}>
                <summary>
                  <span className={`badge ${STATUS_BADGE[entry.status ?? ""] ?? "badge-neutral"}`}>
                    attempt {entry.attempt}
                  </span>
                  {entry.status}
                </summary>
                {entry.error && <pre>{entry.error}</pre>}
              </details>
            ))}
          </>
        )}
      </div>
    </div>
  );
}
