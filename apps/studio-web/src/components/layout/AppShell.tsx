import { Link, useLocation, Outlet } from "react-router-dom";

const CREATOR_LINKS = [
  { to: "/create", label: "Create" },
  { to: "/runs", label: "Projects" },
];

const OPS_LINKS = [
  { to: "/ops", label: "Ops" },
  { to: "/settings", label: "Settings" },
];

export default function AppShell() {
  const location = useLocation();

  const isActive = (path: string) => {
    if (path === "/create") return location.pathname === "/create";
    if (path === "/runs") {
      return (
        location.pathname.startsWith("/runs") ||
        location.pathname.startsWith("/projects") ||
        location.pathname.startsWith("/review")
      );
    }
    if (path === "/ops") return location.pathname.startsWith("/ops");
    if (path === "/settings") return location.pathname === "/settings";
    return false;
  };

  return (
    <div>
      <nav
        data-testid="app-nav"
        style={{
          display: "flex",
          alignItems: "center",
          padding: "0 24px",
          height: 48,
          borderBottom: "1px solid #e5e7eb",
          background: "#fff",
          gap: 24,
        }}
      >
        <Link
          to="/create"
          style={{
            fontWeight: 700,
            fontSize: 15,
            color: "#111827",
            textDecoration: "none",
            marginRight: 16,
          }}
        >
          Short-Form Pipeline
        </Link>

        <div style={{ display: "flex", gap: 4 }} data-testid="creator-nav">
          {CREATOR_LINKS.map((link) => (
            <Link
              key={link.to}
              to={link.to}
              style={{
                padding: "6px 12px",
                borderRadius: 4,
                fontSize: 13,
                fontWeight: isActive(link.to) ? 600 : 400,
                color: isActive(link.to) ? "#4285f4" : "#6b7280",
                background: isActive(link.to) ? "#eff6ff" : "transparent",
                textDecoration: "none",
              }}
            >
              {link.label}
            </Link>
          ))}
        </div>

        <div style={{ flex: 1 }} />

        <div style={{ display: "flex", gap: 4 }} data-testid="ops-nav">
          {OPS_LINKS.map((link) => (
            <Link
              key={link.to}
              to={link.to}
              style={{
                padding: "6px 12px",
                borderRadius: 4,
                fontSize: 13,
                fontWeight: isActive(link.to) ? 600 : 400,
                color: isActive(link.to) ? "#9333ea" : "#6b7280",
                background: isActive(link.to) ? "#faf5ff" : "transparent",
                textDecoration: "none",
              }}
            >
              {link.label}
            </Link>
          ))}
        </div>
      </nav>

      <main>
        <Outlet />
      </main>
    </div>
  );
}
