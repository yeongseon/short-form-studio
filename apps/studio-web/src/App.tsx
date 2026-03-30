import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import AppShell from "./components/layout/AppShell";
import CreatePage from "./pages/CreatePage";
import LibraryPage from "./pages/LibraryPage";
import OpsPage from "./pages/OpsPage";
import ProjectPage from "./pages/ProjectPage";
import ReviewPage from "./pages/ReviewPage";
import RunsPage from "./pages/RunsPage";

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<AppShell />}>
          <Route path="/create" element={<CreatePage />} />
          <Route path="/projects/:projectId" element={<ProjectPage />} />
          <Route path="/review/:runId" element={<ReviewPage />} />
          <Route path="/runs" element={<RunsPage />} />
          <Route path="/library" element={<LibraryPage />} />

          <Route path="/ops" element={<OpsPage />} />

          <Route path="*" element={<Navigate replace to="/create" />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
