/**
 * StageActionBar — a presentational action bar shared across pipeline stages.
 *
 * Provides slots for save, approve, generate-next-stage, and restart actions.
 * Pages own the endpoint calls; this component only renders buttons and
 * forwards callbacks.  Actions can be individually shown, disabled, and
 * labelled from the parent.
 */

// --------------- types ---------------

export interface ActionConfig {
  /** Whether the action button is rendered. */
  visible?: boolean;
  /** Whether the action button is disabled (greyed out). */
  disabled?: boolean;
  /** Optional custom label override. */
  label?: string;
  /** Click handler forwarded to the button. */
  onClick?: () => void;
  /** Whether the action is currently loading / in-progress. */
  loading?: boolean;
}

export interface StageActionBarProps {
  /** Save / persist draft action. */
  save?: ActionConfig;
  /** Approve current stage and advance. */
  approve?: ActionConfig;
  /** Trigger generation for the next stage. */
  generate?: ActionConfig;
  /** Restart / regenerate current stage. */
  restart?: ActionConfig;
  /** Optional status message displayed at the leading edge. */
  statusMessage?: string;
}

// --------------- defaults ---------------

const DEFAULT_LABELS: Record<string, string> = {
  save: "Save",
  approve: "Approve",
  generate: "Generate",
  restart: "Restart",
};

// --------------- styles ---------------

const BAR_STYLE: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 8,
  padding: "10px 16px",
  borderTop: "1px solid #dee2e6",
  backgroundColor: "#f8f9fa",
};

const BTN_BASE: React.CSSProperties = {
  padding: "6px 16px",
  borderRadius: 4,
  border: "1px solid transparent",
  fontSize: 13,
  fontWeight: 500,
  cursor: "pointer",
  lineHeight: "20px",
  transition: "opacity 0.15s",
};

const BTN_VARIANTS: Record<string, React.CSSProperties> = {
  save: { backgroundColor: "#6c757d", color: "#fff", borderColor: "#6c757d" },
  approve: { backgroundColor: "#28a745", color: "#fff", borderColor: "#28a745" },
  generate: { backgroundColor: "#007bff", color: "#fff", borderColor: "#007bff" },
  restart: { backgroundColor: "#ffc107", color: "#212529", borderColor: "#ffc107" },
};

const DISABLED_STYLE: React.CSSProperties = {
  opacity: 0.5,
  cursor: "not-allowed",
};

const STATUS_STYLE: React.CSSProperties = {
  fontSize: 12,
  color: "#6c757d",
  marginRight: "auto",
};

// --------------- helpers ---------------

function renderButton(key: string, config: ActionConfig | undefined) {
  if (!config || config.visible === false) return null;

  const label = config.loading
    ? `${config.label ?? DEFAULT_LABELS[key]}…`
    : (config.label ?? DEFAULT_LABELS[key]);

  const isDisabled = config.disabled || config.loading;

  return (
    <button
      key={key}
      type="button"
      data-testid={`action-${key}`}
      disabled={isDisabled}
      onClick={config.onClick}
      style={{
        ...BTN_BASE,
        ...BTN_VARIANTS[key],
        ...(isDisabled ? DISABLED_STYLE : {}),
      }}
      aria-busy={config.loading ?? false}
    >
      {label}
    </button>
  );
}

// --------------- component ---------------

export default function StageActionBar({
  save,
  approve,
  generate,
  restart,
  statusMessage,
}: StageActionBarProps) {
  const buttons = [
    renderButton("save", save),
    renderButton("approve", approve),
    renderButton("generate", generate),
    renderButton("restart", restart),
  ].filter(Boolean);

  // Don't render the bar at all if no actions are visible
  if (buttons.length === 0 && !statusMessage) return null;

  return (
    <div data-testid="stage-action-bar" role="toolbar" aria-label="Stage actions" style={BAR_STYLE}>
      {statusMessage && (
        <span data-testid="action-status" style={STATUS_STYLE}>
          {statusMessage}
        </span>
      )}
      {!statusMessage && <span style={{ marginRight: "auto" }} />}
      {buttons}
    </div>
  );
}
