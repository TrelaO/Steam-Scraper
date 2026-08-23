import { Link, Route, Routes } from "react-router-dom";
import Dashboard from "./pages/Dashboard";
import PipelineRun from "./pages/PipelineRun";
import Upload from "./pages/Upload";

export default function App() {
  return (
    <div>
      <nav style={{ display: "flex", gap: 16, padding: 16, borderBottom: "1px solid #ddd" }}>
        <Link to="/">Upload</Link>
        <Link to="/dashboard">Dashboard</Link>
      </nav>
      <main style={{ padding: 16 }}>
        <Routes>
          <Route path="/" element={<Upload />} />
          <Route path="/pipeline/:jobId" element={<PipelineRun />} />
          <Route path="/dashboard" element={<Dashboard />} />
        </Routes>
      </main>
    </div>
  );
}
