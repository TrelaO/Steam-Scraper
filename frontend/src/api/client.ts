// Relative by default: same-origin in production (FastAPI serves the built frontend and
// /api together) and proxied to the backend by the Vite dev server (see vite.config.ts).
const API_BASE = import.meta.env.VITE_API_BASE ?? "/api";

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
  current_step?: string;
}

export interface GameRow {
  app_id: string;
  game_name: string | null;
  release_date: string | null;
  platform_combo: string | null;
  price_usd: number | null;
  discount_pct: number | null;
  peak_ccu: number | null;
  positive_reviews: number | null;
  negative_reviews: number | null;
  average_playtime_mins: number | null;
  snapshot_date: string | null;
  genres: string | null;
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
  return fetch(`${API_BASE}/upload`, { method: "POST", body: form }).then(handle<UploadResponse>);
}

export function runEtl(fileId: string): Promise<ETLJobStatus> {
  return fetch(`${API_BASE}/etl/run/${fileId}`, { method: "POST" }).then(handle<ETLJobStatus>);
}

export function getEtlStatus(jobId: string): Promise<ETLJobStatus> {
  return fetch(`${API_BASE}/etl/status/${jobId}`).then(handle<ETLJobStatus>);
}

export interface GamesPage {
  rows: GameRow[];
  has_more: boolean;
}

export function listGames(params: {
  q?: string;
  sort?: string;
  dir?: "asc" | "desc";
  limit?: number;
  offset?: number;
}): Promise<GamesPage> {
  const usp = new URLSearchParams();
  if (params.q) usp.set("q", params.q);
  if (params.sort) usp.set("sort", params.sort);
  if (params.dir) usp.set("dir", params.dir);
  if (params.limit !== undefined) usp.set("limit", String(params.limit));
  if (params.offset !== undefined) usp.set("offset", String(params.offset));
  return fetch(`${API_BASE}/games?${usp.toString()}`).then(handle<GamesPage>);
}

export interface YearCohort {
  year: number;
  avg_price: number;
  avg_discount: number;
  count: number;
}

export function getPriceByYear(): Promise<YearCohort[]> {
  return fetch(`${API_BASE}/analytics/price-by-year`).then(handle<YearCohort[]>);
}

export interface PriceHistoryPoint {
  price_usd: number;
  discount_pct: number | null;
  platform_combo: string | null;
  snapshot_date: string | null;
}

export function getGamePriceHistory(appId: string): Promise<PriceHistoryPoint[]> {
  return fetch(`${API_BASE}/games/${encodeURIComponent(appId)}/history`).then(
    handle<PriceHistoryPoint[]>
  );
}

export function clearWarehouse(): Promise<{ status: string }> {
  return fetch(`${API_BASE}/warehouse`, { method: "DELETE" }).then(handle<{ status: string }>);
}

export interface GeminiUsage {
  date: string;
  count: number;
  budget: number;
  remaining: number;
}

export function getGeminiUsage(): Promise<GeminiUsage> {
  return fetch(`${API_BASE}/gemini-usage`).then(handle<GeminiUsage>);
}
