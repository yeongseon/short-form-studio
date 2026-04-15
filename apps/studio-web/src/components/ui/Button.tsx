import type { ButtonHTMLAttributes, ReactNode } from "react";

// --------------- types ---------------

export type ButtonVariant = "primary" | "secondary" | "danger" | "success" | "warning" | "ghost";
export type ButtonSize = "sm" | "md";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  loading?: boolean;
  children: ReactNode;
}

// --------------- styles ---------------

const SIZE_STYLES: Record<ButtonSize, React.CSSProperties> = {
  sm: { padding: "4px 12px", fontSize: 12 },
  md: { padding: "6px 16px", fontSize: 13 },
};

const VARIANT_STYLES: Record<ButtonVariant, React.CSSProperties> = {
  primary: { backgroundColor: "#007bff", color: "#fff", borderColor: "#007bff" },
  secondary: { backgroundColor: "#6c757d", color: "#fff", borderColor: "#6c757d" },
  danger: { backgroundColor: "#dc2626", color: "#fff", borderColor: "#dc2626" },
  success: { backgroundColor: "#28a745", color: "#fff", borderColor: "#28a745" },
  warning: { backgroundColor: "#ffc107", color: "#212529", borderColor: "#ffc107" },
  ghost: { backgroundColor: "transparent", color: "#374151", borderColor: "#d1d5db" },
};

const BASE_STYLE: React.CSSProperties = {
  borderRadius: 4,
  border: "1px solid transparent",
  fontWeight: 500,
  cursor: "pointer",
  lineHeight: "20px",
  transition: "opacity 0.15s",
};

const DISABLED_STYLE: React.CSSProperties = {
  opacity: 0.5,
  cursor: "not-allowed",
};

// --------------- component ---------------

export default function Button({
  variant = "primary",
  size = "md",
  loading = false,
  disabled,
  style,
  children,
  ...rest
}: ButtonProps) {
  const isDisabled = disabled || loading;

  return (
    <button
      type="button"
      disabled={isDisabled}
      style={{
        ...BASE_STYLE,
        ...SIZE_STYLES[size],
        ...VARIANT_STYLES[variant],
        ...(isDisabled ? DISABLED_STYLE : {}),
        ...style,
      }}
      {...rest}
    >
      {loading ? "…" : children}
    </button>
  );
}
