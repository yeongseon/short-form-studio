import type { HTMLAttributes, ReactNode } from "react";

// --------------- types ---------------

interface CardProps extends HTMLAttributes<HTMLDivElement> {
  /** Visual card variant. */
  variant?: "default" | "outlined" | "dashed";
  /** Card padding preset. */
  padding?: "sm" | "md" | "lg";
  children: ReactNode;
}

// --------------- styles ---------------

const PADDING_MAP: Record<string, number> = {
  sm: 16,
  md: 24,
  lg: 32,
};

const VARIANT_STYLES: Record<string, React.CSSProperties> = {
  default: {
    background: "#fff",
    border: "1px solid #e5e7eb",
    boxShadow: "0 1px 3px rgba(0,0,0,0.06)",
  },
  outlined: {
    background: "#fff",
    border: "1px solid #d1d5db",
  },
  dashed: {
    background: "#f9fafb",
    border: "1px dashed #d1d5db",
  },
};

const BASE_STYLE: React.CSSProperties = {
  borderRadius: 8,
};

// --------------- component ---------------

export default function Card({
  variant = "default",
  padding = "md",
  style,
  children,
  ...rest
}: CardProps) {
  return (
    <div
      style={{
        ...BASE_STYLE,
        ...VARIANT_STYLES[variant],
        padding: PADDING_MAP[padding],
        ...style,
      }}
      {...rest}
    >
      {children}
    </div>
  );
}
