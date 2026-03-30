import React from "react";
import { useParams } from "react-router-dom";

export default function ProjectPage(): React.ReactElement {
  const { projectId } = useParams<{ projectId: string }>();
  return (
    <div style={{ padding: "2rem" }}>
      <h1>Project: {projectId}</h1>
      <p>Project details and configuration will appear here.</p>
    </div>
  );
}
