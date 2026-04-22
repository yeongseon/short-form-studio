/**
 * ConfirmDialog — reusable confirmation modal for destructive / important actions.
 */

import { useEffect, useRef, useId } from "react";

interface ConfirmDialogProps {
  open: boolean;
  title: string;
  message: string;
  confirmLabel?: string;
  cancelLabel?: string;
  variant?: "danger" | "warning" | "info";
  loading?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

const VARIANT_COLORS: Record<string, { bg: string; hover: string }> = {
  danger: { bg: "#dc2626", hover: "#b91c1c" },
  warning: { bg: "#d97706", hover: "#b45309" },
  info: { bg: "#4285f4", hover: "#2563eb" },
};

export default function ConfirmDialog({
  open,
  title,
  message,
  confirmLabel = "Confirm",
  cancelLabel = "Cancel",
  variant = "danger",
  loading = false,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const previousFocusRef = useRef<HTMLElement | null>(null);
  const titleId = useId();
  const descId = useId();

  // Focus trap + Escape handler
  useEffect(() => {
    if (!open) return;

    // Store previously focused element to restore on close
    previousFocusRef.current = document.activeElement as HTMLElement | null;

    // Focus the cancel button (safe default) on open
    const dialog = dialogRef.current;
    if (dialog) {
      const cancelBtn = dialog.querySelector<HTMLElement>("button[data-role='cancel']");
      cancelBtn?.focus();
    }

    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.stopPropagation();
        onCancel();
        return;
      }

      // Focus trap: Tab / Shift+Tab cycles within dialog
      if (e.key === "Tab" && dialog) {
        const focusable = dialog.querySelectorAll<HTMLElement>("button:not([disabled])");
        if (focusable.length === 0) return;
        const first = focusable[0];
        const last = focusable[focusable.length - 1];

        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    }

    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      // Restore focus
      previousFocusRef.current?.focus();
    };
  }, [open, onCancel]);

  if (!open) return null;

  const colors = VARIANT_COLORS[variant] ?? VARIANT_COLORS.danger;

  return (
    <div
      data-testid="confirm-dialog-backdrop"
      onClick={onCancel}
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 1000,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background: "rgba(0,0,0,0.4)",
      }}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={descId}
        data-testid="confirm-dialog"
        onClick={(e) => e.stopPropagation()}
        style={{
          maxWidth: 420,
          width: "90%",
          background: "#fff",
          borderRadius: 8,
          boxShadow: "0 8px 30px rgba(0,0,0,0.18)",
          padding: 24,
        }}
      >
        <h3 id={titleId} style={{ margin: "0 0 12px", fontSize: 16, fontWeight: 700, color: "#111827" }}>
          {title}
        </h3>
        <p id={descId} style={{ margin: "0 0 24px", fontSize: 14, color: "#374151", lineHeight: 1.5 }}>
          {message}
        </p>
        <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
          <button
            type="button"
            data-role="cancel"
            onClick={onCancel}
            disabled={loading}
            style={{
              padding: "8px 16px",
              border: "1px solid #d1d5db",
              borderRadius: 6,
              background: "#fff",
              color: "#374151",
              fontSize: 13,
              fontWeight: 500,
              cursor: loading ? "not-allowed" : "pointer",
            }}
          >
            {cancelLabel}
          </button>
          <button
            type="button"
            data-testid="confirm-dialog-confirm"
            onClick={onConfirm}
            disabled={loading}
            style={{
              padding: "8px 16px",
              border: "none",
              borderRadius: 6,
              background: loading ? "#9ca3af" : colors.bg,
              color: "#fff",
              fontSize: 13,
              fontWeight: 600,
              cursor: loading ? "not-allowed" : "pointer",
            }}
          >
            {loading ? "…" : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
