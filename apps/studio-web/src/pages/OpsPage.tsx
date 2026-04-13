const OPS_TOOLS = [
  {
    id: "monitoring",
    title: "Task Monitoring",
    description:
      "View Celery task queue, worker status, and task history via Flower. Requires direct network access to the Flower service.",
    link: `${window.location.protocol}//${window.location.hostname}:5555`,
    external: true,
    icon: "📊",
  },
  {
    id: "health",
    title: "System Health",
    description: "Check API, database, Redis, and worker connectivity status.",
    link: "/health",
    external: true,
    icon: "🩺",
  },
  {
    id: "docs",
    title: "API Documentation",
    description: "Interactive API reference for all creator endpoints.",
    link: "/docs",
    external: true,
    icon: "📖",
  },
];

export default function OpsPage() {
  return (
    <div style={{ maxWidth: 960, margin: "0 auto", padding: 24 }}>
      <h1 style={{ fontSize: 24, fontWeight: 700, marginBottom: 8 }}>
        Operations
      </h1>
      <p style={{ fontSize: 14, color: "#6b7280", marginBottom: 24 }}>
        System monitoring and operational tools. Links open internal service endpoints.
      </p>

      <div
        data-testid="ops-tools-grid"
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))",
          gap: 16,
        }}
      >
        {OPS_TOOLS.map((tool) => (
          <div
            key={tool.id}
            data-testid={`ops-tool-${tool.id}`}
            style={{
              padding: 20,
              border: "1px solid #e5e7eb",
              borderRadius: 8,
              background: "#fff",
            }}
          >
            <div style={{ fontSize: 24, marginBottom: 8 }}>{tool.icon}</div>
            <h3 style={{ fontSize: 16, fontWeight: 600, margin: "0 0 4px" }}>
              {tool.title}
            </h3>
            <p style={{ fontSize: 13, color: "#6b7280", margin: "0 0 12px" }}>
              {tool.description}
            </p>
            <a
              href={tool.link}
              target="_blank"
              rel="noopener noreferrer"
              style={{
                fontSize: 13,
                color: "#4285f4",
                textDecoration: "none",
                fontWeight: 500,
              }}
            >
              Open →
            </a>
          </div>
        ))}
      </div>

      {/* System Info */}
      <div
        data-testid="ops-system-info"
        style={{
          marginTop: 32,
          padding: 20,
          border: "1px solid #e5e7eb",
          borderRadius: 8,
          background: "#f9fafb",
        }}
      >
        <h3 style={{ fontSize: 16, fontWeight: 600, margin: "0 0 12px" }}>
          System Information
        </h3>
        <div style={{ fontSize: 13, color: "#6b7280", lineHeight: 1.8 }}>
          <div>GPU: NVIDIA GTX 1660 SUPER (6 GB VRAM)</div>
          <div>Runtime: Docker Compose (local)</div>
          <div>Rendering: FFmpeg (CPU)</div>
          <div>Storage: Local filesystem</div>
        </div>
      </div>
    </div>
  );
}
