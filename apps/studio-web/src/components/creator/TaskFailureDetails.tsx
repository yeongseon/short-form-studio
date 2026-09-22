import { categoryLabel } from "../../api/errorLabels";
import type { RunTaskInfo } from "./useRunProgress";

export const TASK_ERROR_LABELS: Record<string, string> = {
  provider_timeout: "Timed out",
  rate_limit: "Rate limited",
  provider_error: "Provider error",
  validation_error: "Invalid input",
  revoked: "Cancelled",
  soft_time_limit: "Timed out",
};

export function TaskFailureDetails({ task }: { readonly task: RunTaskInfo | null }) {
  return task?.failure ? (
    <span data-testid="task-failure" style={{ display: "block", marginTop: 4, fontSize: 12, opacity: 0.9 }}>
      <span style={{ fontWeight: 600 }}>{categoryLabel(task.failure.category)}</span>
      {" — "}
      {task.failure.retryable ? "you can retry" : "not retryable"}
      {task.failure.recovery_steps.length > 0 && (
        <ul data-testid="task-recovery-steps" style={{ margin: "6px 0 0", paddingLeft: 18, fontSize: 11, opacity: 0.85 }}>
          {task.failure.recovery_steps.map((step, i) => <li key={i}>{step}</li>)}
        </ul>
      )}
    </span>
  ) : (
    <>
      {task?.error_code && (
        <span style={{ display: "block", marginTop: 4, fontSize: 12, opacity: 0.85 }}>
          {TASK_ERROR_LABELS[task.error_code] ?? task.error_code}
          {task.attempt > 1 && ` (after ${task.attempt} attempts)`}
        </span>
      )}
      {task?.error_message && (
        <span
          style={{ display: "block", marginTop: 4, fontSize: 11, opacity: 0.7, maxWidth: 320, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
          title={task.error_message}
        >
          {task.error_message}
        </span>
      )}
    </>
  );
}
