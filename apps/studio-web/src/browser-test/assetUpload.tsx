import React from "react";
import ReactDOM from "react-dom/client";

import AssetDropZone from "../components/creator/AssetDropZone";

const workspaceId = Number(new URLSearchParams(window.location.search).get("workspaceId"));
const root = document.getElementById("root");

if (root === null) {
  throw new Error("Browser test root is missing");
}

ReactDOM.createRoot(root).render(
  <React.StrictMode>
    <AssetDropZone workspaceId={workspaceId} sceneId="browser-upload-test" />
  </React.StrictMode>,
);
