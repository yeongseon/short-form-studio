import { useEffect, useState } from "react";
import { apiJson } from "../../api/client";
import { STAGE_ORDER } from "../../types/api";

export interface RunTaskInfo {
  readonly id?: number;
  readonly task_type: string;
  readonly status: string;
  readonly attempt: number;
  readonly error_code: string | null;
  readonly error_message: string | null;
  readonly failure?: {
    readonly code: string;
    readonly category: string;
    readonly retryable: boolean;
    readonly recovery_steps: string[];
    readonly message: string;
  } | null;
}

type Snapshot = { readonly current_stage: string; readonly status: string };
type Outcome = "running" | "completed" | "failed" | "error";

export interface RunProgressOptions {
  readonly open: boolean;
  readonly runId: number;
  readonly expectedStage: string;
  readonly apiBase: string;
  readonly pollInterval: number;
  readonly onComplete?: (stage: string, status: string) => void;
  readonly onFailed?: (stage: string, status: string) => void;
}

export function useRunProgress({ open, runId, expectedStage, apiBase, pollInterval, onComplete, onFailed }: RunProgressOptions) {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [outcome, setOutcome] = useState<Outcome>("running");
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [pollCount, setPollCount] = useState(0);
  const [taskInfo, setTaskInfo] = useState<RunTaskInfo | null>(null);

  useEffect(() => {
    setSnapshot(null);
    setOutcome("running");
    setErrorMsg(null);
    setPollCount(0);
    setTaskInfo(null);
    if (!open) return;
    let cancelled = false;
    let polling = false;
    let terminal = false;
    const poll = async () => {
      if (polling || terminal) return;
      polling = true;
      try {
        const data = await apiJson<Snapshot>(`${apiBase}/runs/${runId}`);
        if (cancelled) return;
        setSnapshot(data);
        setPollCount((count) => count + 1);
        setErrorMsg(null);
        try {
          const tasks = await apiJson<RunTaskInfo[]>(`${apiBase}/runs/${runId}/tasks`);
          if (cancelled) return;
          const latest = tasks.reduce<RunTaskInfo | null>((newest, task) =>
            newest === null || (task.id ?? 0) > (newest.id ?? 0) ? task : newest, null);
          setTaskInfo(latest);
        } catch (err: unknown) {
          if (!(err instanceof Error)) throw err;
          if (!cancelled) setTaskInfo(null);
        }
        if (cancelled) return;
        if (data.status === "failed") {
          terminal = true;
          setOutcome("failed");
          onFailed?.(data.current_stage, data.status);
        } else if (STAGE_ORDER.indexOf(data.current_stage) > STAGE_ORDER.indexOf(expectedStage)) {
          terminal = true;
          setOutcome("completed");
          onComplete?.(data.current_stage, data.status);
        }
      } catch (err: unknown) {
        if (cancelled) return;
        setErrorMsg(err instanceof Error ? err.message : "Network error");
        setOutcome("error");
      } finally {
        polling = false;
      }
    };
    void poll();
    const timer = setInterval(() => { void poll(); }, pollInterval);
    return () => { cancelled = true; clearInterval(timer); };
  }, [open, runId, expectedStage, apiBase, pollInterval, onComplete, onFailed]);

  return { snapshot, outcome, errorMsg, pollCount, taskInfo };
}
