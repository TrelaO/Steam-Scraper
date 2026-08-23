import { useEffect, useState } from "react";
import { useLocation, useParams } from "react-router-dom";
import { ETLJobStatus, getEtlStatus } from "../api/client";

export default function PipelineRun() {
  const { jobId } = useParams();
  const location = useLocation();
  const initialJob = (location.state as { job?: ETLJobStatus } | null)?.job ?? null;
  const [job, setJob] = useState<ETLJobStatus | null>(initialJob);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (job || !jobId) return;
    getEtlStatus(jobId)
      .then(setJob)
      .catch((err) => setError((err as Error).message));
  }, [job, jobId]);

  if (error) return <p style={{ color: "red" }}>{error}</p>;
  if (!job) return <p>Loading...</p>;

  return (
    <div>
      <h1>ETL run {job.job_id}</h1>
      <p>Status: {job.status}</p>
      {job.error && <pre style={{ color: "red", whiteSpace: "pre-wrap" }}>{job.error}</pre>}
      {job.result && (
        <>
          <h2>Rows written</h2>
          <pre>{JSON.stringify(job.result, null, 2)}</pre>
        </>
      )}
      <h2>Generated code (final attempt)</h2>
      <pre style={{ whiteSpace: "pre-wrap", background: "#f5f5f5", padding: 12 }}>
        {job.generated_code}
      </pre>
      <h2>Attempt log</h2>
      {job.logs.map((entry, i) => (
        <details key={i} open={entry.status === "error"}>
          <summary>
            Attempt {entry.attempt}: {entry.status}
          </summary>
          {entry.error && <pre style={{ whiteSpace: "pre-wrap", color: "red" }}>{entry.error}</pre>}
        </details>
      ))}
    </div>
  );
}
