import type { CSSProperties } from "react";

export const cardStyle: CSSProperties = {
  marginBottom: 24, padding: 20, border: "1px solid #e5e7eb", borderRadius: 8, background: "#fff",
};
export const headerStyle: CSSProperties = {
  display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12,
};
export const sectionTitle: CSSProperties = { fontSize: 16, fontWeight: 600, margin: 0 };
export const metaStyle: CSSProperties = { fontSize: 12, color: "#6b7280" };
export const editLinkStyle: CSSProperties = { fontSize: 12, color: "#4285f4", textDecoration: "none" };
export const previewBoxStyle: CSSProperties = {
  padding: 12, background: "#f9fafb", borderRadius: 6, fontSize: 13,
  fontFamily: '"JetBrains Mono", "Fira Code", "Cascadia Code", "SF Mono", monospace',
  whiteSpace: "pre-wrap", overflowX: "auto", maxHeight: 300, overflowY: "auto",
};
