import { useEffect, useState } from "react";
import { NavLink, Route, Routes } from "react-router-dom";
import { getGeminiUsage, GeminiUsage } from "./api/client";
import Dashboard from "./pages/Dashboard";
import PipelineRun from "./pages/PipelineRun";
import Upload from "./pages/Upload";
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

export default function App() {
  const [theme, setTheme] = useState<Theme>(() => getStoredTheme() ?? getSystemTheme());

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
        </div>
        <span className="navbar-spacer" />
        <GeminiUsageBadge />
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
          </Routes>
        </UploadStateProvider>
      </main>
    </div>
  );
}
