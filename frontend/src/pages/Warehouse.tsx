import { useEffect, useState } from "react";
import { getSchema, runSqlQuery, SchemaTable, SqlQueryResult } from "../api/client";

const KIND_BADGE: Record<SchemaTable["kind"], string> = {
  dimension: "badge-neutral",
  fact: "badge-success",
  bridge: "badge-warning",
};

const PRESET_QUERIES: { label: string; sql: string }[] = [
  {
    label: "Top 10 priciest games",
    sql: "SELECT game_name, price_usd\nFROM fact_game\nJOIN dim_game USING (game_sk)\nORDER BY price_usd DESC\nLIMIT 10;",
  },
  {
    label: "Genre distribution",
    sql: "SELECT genre_name, COUNT(*) AS game_count\nFROM bridge_game_genre\nJOIN dim_genre USING (genre_sk)\nGROUP BY genre_name\nORDER BY game_count DESC\nLIMIT 20;",
  },
  {
    label: "Avg price by platform",
    sql: "SELECT platform_combo, ROUND(AVG(price_usd), 2) AS avg_price, COUNT(*) AS snapshots\nFROM fact_game\nJOIN dim_platform USING (platform_sk)\nGROUP BY platform_combo\nORDER BY avg_price DESC;",
  },
  {
    label: "Row counts per table",
    sql: "SELECT 'fact_game' AS table_name, COUNT(*) AS rows FROM fact_game\nUNION ALL SELECT 'dim_game', COUNT(*) FROM dim_game\nUNION ALL SELECT 'dim_genre', COUNT(*) FROM dim_genre;",
  },
];

function formatCell(value: string | number | null): string {
  if (value === null) return "NULL";
  return String(value);
}

const HISTORY_KEY = "steam-scraper:sql-history";
const MAX_HISTORY = 10;

function loadHistory(): string[] {
  try {
    const raw = localStorage.getItem(HISTORY_KEY);
    return raw ? (JSON.parse(raw) as string[]) : [];
  } catch {
    return [];
  }
}

function saveHistory(history: string[]): void {
  try {
    localStorage.setItem(HISTORY_KEY, JSON.stringify(history));
  } catch {
    // Private browsing / storage disabled - history just won't persist, not fatal.
  }
}

function csvEscape(value: string | number | null): string {
  if (value === null) return "";
  const s = String(value);
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

function downloadCsv(result: SqlQueryResult): void {
  const lines = [
    result.columns.map(csvEscape).join(","),
    ...result.rows.map((row) => row.map(csvEscape).join(",")),
  ];
  const blob = new Blob([lines.join("\r\n")], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `query-result-${new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-")}.csv`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

const ERD_STROKE: Record<SchemaTable["kind"], string> = {
  dimension: "var(--border)",
  fact: "var(--success)",
  bridge: "var(--warning)",
};

interface ErdNode {
  table: string;
  cx: number;
  cy: number;
  w: number;
  h: number;
}

const ERD_NODES: ErdNode[] = [
  { table: "dim_date", cx: 150, cy: 60, w: 172, h: 64 },
  { table: "dim_platform", cx: 750, cy: 60, w: 172, h: 64 },
  { table: "fact_game", cx: 450, cy: 235, w: 190, h: 72 },
  { table: "dim_game", cx: 150, cy: 410, w: 172, h: 64 },
  { table: "bridge_game_genre", cx: 450, cy: 410, w: 200, h: 64 },
  { table: "dim_genre", cx: 750, cy: 410, w: 172, h: 64 },
];

const ERD_EDGES: { from: string; to: string; label: string }[] = [
  { from: "dim_date", to: "fact_game", label: "date_sk" },
  { from: "dim_platform", to: "fact_game", label: "platform_sk" },
  { from: "dim_game", to: "fact_game", label: "game_sk" },
  { from: "dim_game", to: "bridge_game_genre", label: "game_sk" },
  { from: "dim_genre", to: "bridge_game_genre", label: "genre_sk" },
];

function SchemaDiagram({ tables }: { tables: SchemaTable[] }) {
  const nodeByName = (name: string) => ERD_NODES.find((n) => n.table === name)!;
  const rowCount = (name: string) => tables.find((t) => t.name === name)?.row_count;
  const kindOf = (name: string) => tables.find((t) => t.name === name)?.kind ?? "dimension";

  return (
    <svg
      className="schema-diagram"
      viewBox="0 0 900 470"
      style={{ width: "100%", height: "auto", display: "block" }}
    >
      {ERD_EDGES.map((edge, i) => {
        const a = nodeByName(edge.from);
        const b = nodeByName(edge.to);
        const mx = (a.cx + b.cx) / 2;
        const my = (a.cy + b.cy) / 2;
        return (
          <g key={i}>
            <line
              x1={a.cx}
              y1={a.cy}
              x2={b.cx}
              y2={b.cy}
              stroke="var(--border)"
              strokeWidth={1.5}
            />
            <rect
              x={mx - 30}
              y={my - 10}
              width={60}
              height={18}
              rx={5}
              fill="var(--surface)"
              stroke="var(--border)"
              strokeWidth={1}
            />
            <text
              x={mx}
              y={my + 4}
              textAnchor="middle"
              fontFamily="Cascadia Code, SF Mono, Consolas, monospace"
              fontSize={10}
              fill="var(--text-muted)"
            >
              {edge.label}
            </text>
          </g>
        );
      })}
      {ERD_NODES.map((node) => {
        const count = rowCount(node.table);
        const kind = kindOf(node.table);
        return (
          <g key={node.table}>
            <rect
              x={node.cx - node.w / 2}
              y={node.cy - node.h / 2}
              width={node.w}
              height={node.h}
              rx={10}
              fill="var(--surface)"
              stroke={ERD_STROKE[kind]}
              strokeWidth={kind === "fact" ? 2.5 : 1.5}
            />
            <text
              x={node.cx}
              y={node.cy - 6}
              textAnchor="middle"
              fontFamily="Cascadia Code, SF Mono, Consolas, monospace"
              fontWeight={700}
              fontSize={14}
              fill="var(--text)"
            >
              {node.table}
            </text>
            <text x={node.cx} y={node.cy + 14} textAnchor="middle" fontSize={11} fill="var(--text-muted)">
              {count === undefined ? "…" : `${count.toLocaleString()} rows`}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

export default function Warehouse() {
  const [tables, setTables] = useState<SchemaTable[]>([]);
  const [schemaError, setSchemaError] = useState<string | null>(null);
  const [sql, setSql] = useState(PRESET_QUERIES[0].sql);
  const [result, setResult] = useState<SqlQueryResult | null>(null);
  const [queryError, setQueryError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [history, setHistory] = useState<string[]>(() => loadHistory());

  useEffect(() => {
    getSchema()
      .then(setTables)
      .catch((err: Error) => setSchemaError(err.message));
  }, []);

  function runQuery() {
    setRunning(true);
    setQueryError(null);
    runSqlQuery(sql)
      .then((res) => {
        setResult(res);
        setHistory((prev) => {
          const next = [sql, ...prev.filter((q) => q !== sql)].slice(0, MAX_HISTORY);
          saveHistory(next);
          return next;
        });
      })
      .catch((err: Error) => {
        setQueryError(err.message.replace(/^\d+ [^:]+:\s*/, ""));
        setResult(null);
      })
      .finally(() => setRunning(false));
  }

  return (
    <div className="page">
      <div className="page-header">
        <h1>Warehouse</h1>
        <p>Star-schema layout and a read-only SQL console for exploring the data directly.</p>
      </div>

      {schemaError && <div className="error-box">{schemaError}</div>}

      <div className="card">
        <h2 style={{ marginTop: 0 }}>Table relationships</h2>
        <p className="muted" style={{ marginTop: -6, marginBottom: 14 }}>
          A classic star schema: <code>fact_game</code> at the center, one row per game/date/
          platform snapshot, surrounded by its dimensions and the genre bridge table.
        </p>
        <SchemaDiagram tables={tables} />
      </div>

      <div className="card">
        <h2 style={{ marginTop: 0 }}>Column detail</h2>
        <div className="schema-grid">
          {tables.map((table) => (
            <div className="schema-card" key={table.name}>
              <div className="schema-card-header">
                <span className="schema-card-name">{table.name}</span>
                <span className={`badge ${KIND_BADGE[table.kind]}`}>{table.kind}</span>
              </div>
              <div className="schema-card-count muted" style={{ marginBottom: 10 }}>
                {table.row_count.toLocaleString()} rows
              </div>
              <div className="schema-col-list">
                {table.columns.map((col, i) => (
                  <div className="schema-col" key={i}>
                    <span className="schema-col-name">{col.name || <em>—</em>}</span>
                    <span className="schema-col-meta">
                      <span className="schema-col-type">{col.type}</span>
                      {col.key && <span className="schema-col-key">{col.key}</span>}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="card">
        <h2 style={{ marginTop: 0 }}>SQL console</h2>
        <p className="muted" style={{ marginTop: -6, marginBottom: 14 }}>
          Read-only — only SELECT / WITH / EXPLAIN statements are allowed, capped at 500 rows and
          20 seconds.
        </p>

        <div className="sql-presets">
          <span className="sql-preset-label">Examples:</span>
          {PRESET_QUERIES.map((preset) => (
            <button
              key={preset.label}
              className="sql-preset-btn"
              onClick={() => setSql(preset.sql)}
              type="button"
            >
              {preset.label}
            </button>
          ))}
        </div>

        {history.length > 0 && (
          <div className="sql-presets">
            <span className="sql-preset-label">History:</span>
            {history.map((q, i) => (
              <button
                key={i}
                className="sql-preset-btn"
                onClick={() => setSql(q)}
                type="button"
                title={q}
              >
                {q.replace(/\s+/g, " ").slice(0, 40)}
                {q.length > 40 ? "…" : ""}
              </button>
            ))}
          </div>
        )}

        <textarea
          className="sql-textarea"
          value={sql}
          onChange={(e) => setSql(e.target.value)}
          spellCheck={false}
          onKeyDown={(e) => {
            if ((e.ctrlKey || e.metaKey) && e.key === "Enter") runQuery();
          }}
        />

        <div className="sql-toolbar">
          <button className="btn" onClick={runQuery} disabled={running || !sql.trim()}>
            {running ? "Running…" : "Run query"}
          </button>
          {result && result.columns.length > 0 && (
            <button className="btn btn-ghost" onClick={() => downloadCsv(result)} type="button">
              ⬇ Export CSV
            </button>
          )}
          <span className="sql-meta">Ctrl+Enter to run</span>
          {result && (
            <span className="sql-meta">
              {result.row_count.toLocaleString()} row{result.row_count === 1 ? "" : "s"}
              {result.truncated ? " (truncated to 500)" : ""} in {result.elapsed_ms}ms
            </span>
          )}
        </div>

        {queryError && <div className="error-box">{queryError}</div>}

        {result && result.columns.length > 0 && (
          <div className="table-wrap" style={{ marginTop: 16 }}>
            <table className="data-table">
              <thead>
                <tr>
                  {result.columns.map((col) => (
                    <th key={col}>{col}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {result.rows.map((row, i) => (
                  <tr key={i}>
                    {row.map((cell, j) => (
                      <td key={j}>{formatCell(cell)}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
