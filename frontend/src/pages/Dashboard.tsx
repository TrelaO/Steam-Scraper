import { useEffect, useMemo, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { clearWarehouse, GameRow, listGames } from "../api/client";

const YEAR_PATTERN = /\b(19|20)\d{2}\b/;

const CHART_TOOLTIP_STYLE = {
  background: "var(--surface)",
  border: "1px solid var(--border)",
  borderRadius: 8,
  color: "var(--text)",
};

type SortKey = keyof GameRow;
type SortDir = "asc" | "desc";

const COLUMNS: { key: SortKey; label: string; numeric?: boolean }[] = [
  { key: "game_name", label: "Game" },
  { key: "genres", label: "Genres" },
  { key: "platform_combo", label: "Platform" },
  { key: "price_usd", label: "Price (USD)", numeric: true },
  { key: "discount_pct", label: "Discount %", numeric: true },
  { key: "peak_ccu", label: "Peak CCU", numeric: true },
  { key: "positive_reviews", label: "Positive", numeric: true },
  { key: "negative_reviews", label: "Negative", numeric: true },
  { key: "average_playtime_mins", label: "Avg playtime (min)", numeric: true },
  { key: "release_date", label: "Released" },
  { key: "snapshot_date", label: "Snapshot" },
];

const COLUMN_HELP: Record<SortKey, string> = {
  app_id: "Steam's numeric application ID for the game.",
  game_name: "The game's title as it appeared in the source file.",
  genres: "Genre tags assigned to the game, comma-separated.",
  platform_combo: "Which OS combination (Windows/Mac/Linux) this row's price applies to.",
  price_usd: "Listed price in USD at the time of this snapshot.",
  discount_pct: "Discount percentage active at the time of this snapshot.",
  peak_ccu: "Peak concurrent players recorded for the game.",
  positive_reviews: "Total count of positive user reviews.",
  negative_reviews: "Total count of negative user reviews.",
  average_playtime_mins: "Average playtime per player, in minutes.",
  release_date: "The game's original release date (an attribute of the game, not the snapshot).",
  snapshot_date: "The date this row's data was imported/observed - i.e. dim_date, not the release date.",
};

function formatCell(key: SortKey, value: GameRow[SortKey]): string {
  if (value === null || value === undefined || value === "") return "—";
  if (key === "price_usd") return `$${Number(value).toFixed(2)}`;
  if (key === "discount_pct") return `${value}%`;
  return String(value);
}

function HelpModal({ onClose }: { onClose: () => void }) {
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h2>Column guide</h2>
          <button className="modal-close" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </div>
        <dl className="help-list">
          {COLUMNS.map((col) => (
            <div key={col.key}>
              <dt>{col.label}</dt>
              <dd>{COLUMN_HELP[col.key]}</dd>
            </div>
          ))}
        </dl>
      </div>
    </div>
  );
}

function ConfirmClearModal({
  busy,
  error,
  onConfirm,
  onCancel,
}: {
  busy: boolean;
  error: string | null;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape" && !busy) onCancel();
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [busy, onCancel]);

  return (
    <div className="modal-backdrop" onClick={busy ? undefined : onCancel}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h2>Clear database?</h2>
          <button className="modal-close" onClick={onCancel} disabled={busy} aria-label="Close">
            ✕
          </button>
        </div>
        <p className="muted">
          This permanently deletes every game, genre, and price snapshot from the warehouse
          (dim_game, dim_genre, bridge_game_genre, fact_game). Uploaded source files and the
          generated ETL code archive in <code>generated_etl/</code> are not affected. This
          cannot be undone.
        </p>
        {error && <div className="error-box">{error}</div>}
        <div style={{ display: "flex", justifyContent: "flex-end", gap: 10, marginTop: 20 }}>
          <button className="btn btn-ghost" onClick={onCancel} disabled={busy}>
            Cancel
          </button>
          <button className="btn btn-danger" onClick={onConfirm} disabled={busy}>
            {busy ? "Clearing..." : "Clear database"}
          </button>
        </div>
      </div>
    </div>
  );
}

export default function Dashboard() {
  const [rows, setRows] = useState<GameRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [search, setSearch] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("game_name");
  const [sortDir, setSortDir] = useState<SortDir>("asc");
  const [showHelp, setShowHelp] = useState(false);
  const [selectedAppId, setSelectedAppId] = useState<string | null>(null);
  const [showConfirmClear, setShowConfirmClear] = useState(false);
  const [clearing, setClearing] = useState(false);
  const [clearError, setClearError] = useState<string | null>(null);

  useEffect(() => {
    listGames()
      .then(setRows)
      .catch((err) => setError((err as Error).message))
      .finally(() => setLoaded(true));
  }, []);

  async function handleClear() {
    setClearing(true);
    setClearError(null);
    try {
      await clearWarehouse();
      setRows([]);
      setSelectedAppId(null);
      setShowConfirmClear(false);
    } catch (err) {
      setClearError((err as Error).message);
    } finally {
      setClearing(false);
    }
  }

  function toggleSort(key: SortKey) {
    if (key === sortKey) {
      setSortDir((dir) => (dir === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("asc");
    }
  }

  const filteredSorted = useMemo(() => {
    const needle = search.trim().toLowerCase();
    const filtered = needle
      ? rows.filter((row) =>
          [row.game_name, row.genres, row.app_id, row.platform_combo]
            .filter(Boolean)
            .some((field) => String(field).toLowerCase().includes(needle))
        )
      : rows;

    const sorted = [...filtered].sort((a, b) => {
      const av = a[sortKey];
      const bv = b[sortKey];
      if (av === null || av === undefined) return 1;
      if (bv === null || bv === undefined) return -1;
      if (typeof av === "number" && typeof bv === "number") return av - bv;
      return String(av).localeCompare(String(bv));
    });
    if (sortDir === "desc") sorted.reverse();
    return sorted;
  }, [rows, search, sortKey, sortDir]);

  const releaseYearCohorts = useMemo(() => {
    const buckets = new Map<number, { priceSum: number; discountSum: number; count: number }>();
    for (const row of rows) {
      if (row.price_usd === null || !row.release_date) continue;
      const match = row.release_date.match(YEAR_PATTERN);
      if (!match) continue;
      const year = Number(match[0]);
      const bucket = buckets.get(year) ?? { priceSum: 0, discountSum: 0, count: 0 };
      bucket.priceSum += row.price_usd;
      bucket.discountSum += row.discount_pct ?? 0;
      bucket.count += 1;
      buckets.set(year, bucket);
    }
    return Array.from(buckets.entries())
      .map(([year, b]) => ({
        year: String(year),
        avgPrice: b.priceSum / b.count,
        avgDiscount: b.discountSum / b.count,
        count: b.count,
      }))
      .sort((a, b) => a.year.localeCompare(b.year));
  }, [rows]);

  const selectedGameName = rows.find((r) => r.app_id === selectedAppId)?.game_name ?? null;

  const priceHistory = useMemo(() => {
    if (!selectedAppId) return [];
    return rows
      .filter((r) => r.app_id === selectedAppId && r.price_usd !== null && r.snapshot_date)
      .map((r) => ({
        date: r.snapshot_date as string,
        price: r.price_usd as number,
        platform: r.platform_combo,
        discount: r.discount_pct,
      }))
      .sort((a, b) => a.date.localeCompare(b.date));
  }, [rows, selectedAppId]);

  return (
    <div className="page">
      <div className="page-header" style={{ display: "flex", justifyContent: "space-between", gap: 16 }}>
        <div>
          <h1>Warehouse contents</h1>
          <p>Every fact_game row currently in the SQLite warehouse, joined against its dimensions.</p>
        </div>
        <button
          className="btn btn-danger"
          onClick={() => setShowConfirmClear(true)}
          disabled={rows.length === 0}
          style={{ height: "fit-content", whiteSpace: "nowrap" }}
        >
          🗑 Clear database
        </button>
      </div>

      {error && <div className="error-box">{error}</div>}

      {loaded && !error && rows.length === 0 && (
        <div className="card">
          <p className="muted">No data yet — upload a file and run the ETL to populate the warehouse.</p>
        </div>
      )}

      {rows.length > 0 && (
        <>
          <div className="card">
            <h2 style={{ marginTop: 0 }}>Price &amp; discount by release-year cohort</h2>
            <p className="muted">
              The dataset is a single snapshot, not a price history — this is the trend view
              that actually works on one-time-import data: games grouped by release year,
              averaged. Hover a bar for the exact averages and cohort size.
            </p>

            {releaseYearCohorts.length === 0 && (
              <p className="muted">No games with both a price and a parseable release date yet.</p>
            )}
            {releaseYearCohorts.length > 0 && (
              <ResponsiveContainer width="100%" height={320}>
                <BarChart data={releaseYearCohorts}>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                  <XAxis dataKey="year" stroke="var(--text-muted)" />
                  <YAxis stroke="var(--text-muted)" width={56} />
                  <Tooltip
                    contentStyle={CHART_TOOLTIP_STYLE}
                    formatter={(value: number, name: string) => {
                      if (name === "avgPrice") return [`$${value.toFixed(2)}`, "Avg price"];
                      if (name === "avgDiscount") return [`${value.toFixed(0)}%`, "Avg discount"];
                      return [value, name];
                    }}
                    labelFormatter={(year: string) => {
                      const bucket = releaseYearCohorts.find((c) => c.year === year);
                      return `${year} (${bucket?.count ?? 0} game${bucket?.count === 1 ? "" : "s"})`;
                    }}
                  />
                  <Legend
                    formatter={(name: string) => (name === "avgPrice" ? "Avg price (USD)" : "Avg discount %")}
                  />
                  <Bar dataKey="avgPrice" fill="#4f46e5" radius={[4, 4, 0, 0]} />
                  <Bar dataKey="avgDiscount" fill="#f97316" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            )}
          </div>

          <div className="card">
            <h2 style={{ marginTop: 0 }}>
              Price history{selectedGameName ? ` — ${selectedGameName}` : ""}
            </h2>
            <p className="muted">
              Per-game trend across repeated ETL runs. With a one-off dataset import this will
              usually show a single point — it becomes useful once the warehouse holds more
              than one snapshot for the same game (see the "otwarte pytania" section of the
              brief on adding periodic Steam API snapshots).
            </p>

            {!selectedAppId && (
              <p className="muted">Click a row in the table below to see that game's price over time.</p>
            )}
            {selectedAppId && priceHistory.length === 0 && (
              <p className="muted">No priced snapshots recorded for this game yet.</p>
            )}
            {selectedAppId && priceHistory.length === 1 && (
              <p className="muted">
                Only one snapshot recorded so far ({priceHistory[0].date}, ${priceHistory[0].price.toFixed(2)}).
                Run the ETL again on a later date to build a trend.
              </p>
            )}
            {priceHistory.length > 0 && (
              <ResponsiveContainer width="100%" height={280}>
                <LineChart data={priceHistory}>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                  <XAxis dataKey="date" stroke="var(--text-muted)" />
                  <YAxis stroke="var(--text-muted)" width={56} />
                  <Tooltip
                    contentStyle={CHART_TOOLTIP_STYLE}
                    formatter={(value: number, name: string) =>
                      name === "price" ? [`$${value.toFixed(2)}`, "Price"] : [value, name]
                    }
                  />
                  <Line
                    type="monotone"
                    dataKey="price"
                    stroke="#4f46e5"
                    strokeWidth={2}
                    dot={{ r: 4 }}
                    activeDot={{ r: 6 }}
                    name="price"
                  />
                </LineChart>
              </ResponsiveContainer>
            )}
          </div>

          <div className="card">
            <div className="toolbar">
              <input
                className="search-input"
                type="text"
                placeholder="Filter by game, genre, or platform..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
              <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                <span className="row-count">
                  {filteredSorted.length} of {rows.length} rows
                </span>
                <button className="help-btn" onClick={() => setShowHelp(true)}>
                  ❓ What do these columns mean?
                </button>
              </div>
            </div>

            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    {COLUMNS.map((col) => (
                      <th
                        key={col.key}
                        className={sortKey === col.key ? "sorted" : ""}
                        onClick={() => toggleSort(col.key)}
                      >
                        {col.label}
                        {sortKey === col.key && (
                          <span className="sort-arrow">{sortDir === "asc" ? "↑" : "↓"}</span>
                        )}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {filteredSorted.map((row, i) => (
                    <tr
                      key={`${row.app_id}-${row.platform_combo}-${row.snapshot_date}-${i}`}
                      className={row.app_id === selectedAppId ? "selected" : ""}
                      onClick={() => setSelectedAppId(row.app_id)}
                    >
                      {COLUMNS.map((col) => (
                        <td key={col.key} className={col.numeric ? "numeric" : ""}>
                          {formatCell(col.key, row[col.key])}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}

      {showHelp && <HelpModal onClose={() => setShowHelp(false)} />}
      {showConfirmClear && (
        <ConfirmClearModal
          busy={clearing}
          error={clearError}
          onConfirm={handleClear}
          onCancel={() => setShowConfirmClear(false)}
        />
      )}
    </div>
  );
}
