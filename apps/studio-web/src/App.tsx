import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import AppShell from "./components/layout/AppShell";
import CreatePage from "./pages/CreatePage";
import OpsPage from "./pages/OpsPage";
import ProjectPage from "./pages/ProjectPage";
import ReviewPage from "./pages/ReviewPage";
import RunsPage from "./pages/RunsPage";
import SettingsPage from "./pages/SettingsPage";

export default function App() {
  return (
    <BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <Routes>
        <Route element={<AppShell />}>
          <Route path="/create" element={<CreatePage />} />
          <Route path="/projects/:projectId" element={<ProjectPage />} />
          <Route path="/review/:runId" element={<ReviewPage />} />
          <Route path="/runs" element={<RunsPage />} />

          <Route path="/ops" element={<OpsPage />} />
          <Route path="/settings" element={<SettingsPage />} />

          <Route path="*" element={<Navigate replace to="/create" />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
