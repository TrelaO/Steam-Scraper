import { useEffect, useState } from "react";
import { NavLink, Route, Routes } from "react-router-dom";
import Dashboard from "./pages/Dashboard";
import PipelineRun from "./pages/PipelineRun";
import Upload from "./pages/Upload";
import { applyTheme, getStoredTheme, getSystemTheme, Theme } from "./theme";

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
        <Routes>
          <Route path="/" element={<Upload />} />
          <Route path="/pipeline/:jobId" element={<PipelineRun />} />
          <Route path="/dashboard" element={<Dashboard />} />
        </Routes>
      </main>
    </div>
  );
}
