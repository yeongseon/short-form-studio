import type { HTMLAttributes, ReactNode } from "react";

// --------------- types ---------------

export type BadgeVariant = "default" | "success" | "warning" | "error" | "info";

interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  variant?: BadgeVariant;
  children: ReactNode;
}

// --------------- styles ---------------

const VARIANT_STYLES: Record<BadgeVariant, React.CSSProperties> = {
  default: { backgroundColor: "#f3f4f6", color: "#374151" },
  success: { backgroundColor: "#d1fae5", color: "#065f46" },
  warning: { backgroundColor: "#fef3c7", color: "#92400e" },
  error: { backgroundColor: "#fee2e2", color: "#991b1b" },
  info: { backgroundColor: "#dbeafe", color: "#1e40af" },
};

const BASE_STYLE: React.CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  padding: "2px 8px",
  borderRadius: 9999,
  fontSize: 11,
  fontWeight: 600,
  lineHeight: "16px",
  letterSpacing: "0.01em",
};

// --------------- component ---------------

export default function Badge({
  variant = "default",
  style,
  children,
  ...rest
}: BadgeProps) {
  return (
    <span
      style={{
        ...BASE_STYLE,
        ...VARIANT_STYLES[variant],
        ...style,
      }}
      {...rest}
    >
      {children}
    </span>
  );
}
