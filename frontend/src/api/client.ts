const API_BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";

export interface UploadResponse {
  file_id: string;
  filename: string;
  detected_format: string;
}

export interface ETLAttemptLog {
  attempt: number;
  status?: string;
  error?: string;
  code?: string;
}

export interface ETLJobStatus {
  job_id: string;
  file_id: string;
  status: string;
  generated_code?: string;
  logs: ETLAttemptLog[];
  result?: Record<string, unknown>;
  error?: string;
}

async function handle<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${res.status} ${res.statusText}: ${text}`);
  }
  return res.json() as Promise<T>;
}

export function uploadFile(file: File): Promise<UploadResponse> {
  const form = new FormData();
  form.append("file", file);
  return fetch(`${API_BASE}/upload`, { method: "POST", body: form }).then(handle);
}

export function runEtl(fileId: string): Promise<ETLJobStatus> {
  return fetch(`${API_BASE}/etl/run/${fileId}`, { method: "POST" }).then(handle);
}

export function getEtlStatus(jobId: string): Promise<ETLJobStatus> {
  return fetch(`${API_BASE}/etl/status/${jobId}`).then(handle);
}

export function getAnalytics<T>(path: string): Promise<T> {
  return fetch(`${API_BASE}/analytics/${path}`).then(handle);
}
