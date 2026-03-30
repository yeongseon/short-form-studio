import React from "react";
import { useParams } from "react-router-dom";

export default function ReviewPage(): React.ReactElement {
  const { runId } = useParams<{ runId: string }>();
  return (
    <div style={{ padding: "2rem" }}>
      <h1>Review</h1>
      <p>Review run: {runId}</p>
    </div>
  );
}
