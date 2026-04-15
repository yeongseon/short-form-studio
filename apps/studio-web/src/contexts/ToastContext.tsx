import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";

// --------------- types ---------------

export type ToastType = "success" | "error" | "info";

export interface Toast {
  message: string;
  type: ToastType;
}

interface ToastContextValue {
  toast: Toast | null;
  showToast: (message: string, type?: ToastType) => void;
  clearToast: () => void;
}

// --------------- context ---------------

const ToastContext = createContext<ToastContextValue | null>(null);

// --------------- hook ---------------

/**
 * Returns global toast controls when wrapped in `<ToastProvider>`.
 * Falls back to component-local state when no provider is present
 * (e.g. in unit tests), so callers never need to check.
 */
export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext);

  // Fallback: local state for test / unwrapped scenarios
  const [localToast, setLocalToast] = useState<Toast | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout>>();

  const localShow = useCallback((message: string, type: ToastType = "info") => {
    setLocalToast({ message, type });
    clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => setLocalToast(null), 4000);
  }, []);

  const localClear = useCallback(() => {
    clearTimeout(timerRef.current);
    setLocalToast(null);
  }, []);

  useEffect(() => () => clearTimeout(timerRef.current), []);

  if (ctx) return ctx;
  return { toast: localToast, showToast: localShow, clearToast: localClear };
}

// --------------- provider ---------------

const AUTO_DISMISS_MS = 4000;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toast, setToast] = useState<Toast | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout>>();

  const showToast = useCallback((message: string, type: ToastType = "info") => {
    setToast({ message, type });
    clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => setToast(null), AUTO_DISMISS_MS);
  }, []);

  const clearToast = useCallback(() => {
    clearTimeout(timerRef.current);
    setToast(null);
  }, []);

  useEffect(() => () => clearTimeout(timerRef.current), []);

  return (
    <ToastContext.Provider value={{ toast, showToast, clearToast }}>
      {children}
      {toast && (
        <div
          data-testid="status-toast"
          style={{
            position: "fixed",
            bottom: 24,
            left: "50%",
            transform: "translateX(-50%)",
            padding: "10px 24px",
            background: "#1f2937",
            color: "#fff",
            borderRadius: 8,
            fontSize: 13,
            fontWeight: 500,
            boxShadow: "0 4px 12px rgba(0,0,0,0.15)",
            zIndex: 1000,
          }}
        >
          {toast.message}
        </div>
      )}
    </ToastContext.Provider>
  );
}
