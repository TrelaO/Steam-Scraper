import { useEffect, useState } from "react";
import { NavLink, Route, Routes } from "react-router-dom";
import {
  ApiKeyStatus,
  clearApiKey,
  getApiKeyStatus,
  getGeminiUsage,
  GeminiUsage,
  setApiKey,
} from "./api/client";
import Dashboard from "./pages/Dashboard";
import PipelineRun from "./pages/PipelineRun";
import Upload from "./pages/Upload";
import Warehouse from "./pages/Warehouse";
import { applyTheme, getStoredTheme, getSystemTheme, Theme } from "./theme";
import { UploadStateProvider } from "./uploadState";

const USAGE_POLL_MS = 20000;

function GeminiUsageBadge() {
  const [usage, setUsage] = useState<GeminiUsage | null>(null);

  useEffect(() => {
    function refresh() {
      getGeminiUsage()
        .then(setUsage)
        .catch(() => setUsage(null));
    }
    refresh();
    const id = window.setInterval(refresh, USAGE_POLL_MS);
    return () => window.clearInterval(id);
  }, []);

  if (!usage) return null;

  const variant = usage.remaining === 0 ? "badge-danger" : usage.remaining <= 3 ? "badge-warning" : "badge-neutral";

  return (
    <span
      className={`badge ${variant}`}
      title={`Self-imposed daily budget to avoid burning through Google's free-tier quota (resets ${usage.date} UTC).`}
    >
      Gemini {usage.count}/{usage.budget} today
    </span>
  );
}

const SOURCE_LABEL: Record<ApiKeyStatus["source"], string> = {
  override: "Custom key (set in app)",
  env: "From .env (GEMINI_API_KEY)",
  none: "Not configured",
};

function SettingsModal({ onClose }: { onClose: () => void }) {
  const [status, setStatus] = useState<ApiKeyStatus | null>(null);
  const [input, setInput] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function refresh() {
    getApiKeyStatus()
      .then(setStatus)
      .catch((err: Error) => setError(err.message));
  }

  useEffect(() => {
    refresh();
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  function handleSave() {
    if (!input.trim()) return;
    setSaving(true);
    setError(null);
    setApiKey(input.trim())
      .then((s) => {
        setStatus(s);
        setInput("");
      })
      .catch((err: Error) => setError(err.message))
      .finally(() => setSaving(false));
  }

  function handleClear() {
    setSaving(true);
    setError(null);
    clearApiKey()
      .then(setStatus)
      .catch((err: Error) => setError(err.message))
      .finally(() => setSaving(false));
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h2>Settings</h2>
          <button className="modal-close" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </div>

        <p className="muted" style={{ marginTop: 0 }}>
          API key used to call the LLM (Gemini today, but the app checks this before
          anything else regardless of provider). A key entered here overrides
          <code> GEMINI_API_KEY</code> from <code>.env</code> immediately — no restart needed.
        </p>

        {status && (
          <p style={{ marginBottom: 14 }}>
            <span className={`badge ${status.source === "none" ? "badge-danger" : "badge-neutral"}`}>
              {SOURCE_LABEL[status.source]}
            </span>
            {status.masked && <span className="job-id" style={{ marginLeft: 10 }}>{status.masked}</span>}
          </p>
        )}

        <input
          className="search-input"
          type="password"
          placeholder="Paste API key..."
          value={input}
          onChange={(e) => setInput(e.target.value)}
          style={{ width: "100%", marginBottom: 12 }}
          onKeyDown={(e) => {
            if (e.key === "Enter") handleSave();
          }}
        />

        {error && <div className="error-box">{error}</div>}

        <div style={{ display: "flex", justifyContent: "flex-end", gap: 10, marginTop: 16 }}>
          {status?.source === "override" && (
            <button className="btn btn-ghost" onClick={handleClear} disabled={saving}>
              Clear (use .env instead)
            </button>
          )}
          <button className="btn" onClick={handleSave} disabled={saving || !input.trim()}>
            {saving ? "Saving..." : "Save"}
          </button>
        </div>
      </div>
    </div>
  );
}

export default function App() {
  const [theme, setTheme] = useState<Theme>(() => getStoredTheme() ?? getSystemTheme());
  const [showSettings, setShowSettings] = useState(false);

  useEffect(() => {
    applyTheme(theme);
  }, [theme]);

  return (
    <div className="app-shell">
      <nav className="navbar">
        <span className="brand">
          <span className="brand-mark" />
          Steam Scraper
        </span>
        <div className="nav-links">
          <NavLink to="/" end className={({ isActive }) => `nav-link${isActive ? " active" : ""}`}>
            Upload
          </NavLink>
          <NavLink to="/dashboard" className={({ isActive }) => `nav-link${isActive ? " active" : ""}`}>
            Dashboard
          </NavLink>
          <NavLink to="/warehouse" className={({ isActive }) => `nav-link${isActive ? " active" : ""}`}>
            Warehouse
          </NavLink>
        </div>
        <span className="navbar-spacer" />
        <GeminiUsageBadge />
        <button
          className="icon-btn"
          onClick={() => setShowSettings(true)}
          aria-label="Settings"
          title="Settings (API key)"
        >
          ⚙
        </button>
        <button
          className="icon-btn"
          onClick={() => setTheme((t) => (t === "dark" ? "light" : "dark"))}
          aria-label="Toggle dark mode"
          title="Toggle dark mode"
        >
          {theme === "dark" ? "☀️" : "🌙"}
        </button>
      </nav>
      <main>
        <UploadStateProvider>
          <Routes>
            <Route path="/" element={<Upload />} />
            <Route path="/pipeline/:jobId" element={<PipelineRun />} />
            <Route path="/dashboard" element={<Dashboard />} />
            <Route path="/warehouse" element={<Warehouse />} />
          </Routes>
        </UploadStateProvider>
      </main>
      {showSettings && <SettingsModal onClose={() => setShowSettings(false)} />}
    </div>
  );
}
