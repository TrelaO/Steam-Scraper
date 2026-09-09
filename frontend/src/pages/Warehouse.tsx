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

export default function Warehouse() {
  const [tables, setTables] = useState<SchemaTable[]>([]);
  const [schemaError, setSchemaError] = useState<string | null>(null);
  const [sql, setSql] = useState(PRESET_QUERIES[0].sql);
  const [result, setResult] = useState<SqlQueryResult | null>(null);
  const [queryError, setQueryError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);

  useEffect(() => {
    getSchema()
      .then(setTables)
      .catch((err: Error) => setSchemaError(err.message));
  }, []);

  function runQuery() {
    setRunning(true);
    setQueryError(null);
    runSqlQuery(sql)
      .then(setResult)
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
        <h2 style={{ marginTop: 0 }}>Schema</h2>
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
