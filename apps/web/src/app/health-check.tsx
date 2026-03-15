"use client";

import { useEffect, useState } from "react";

interface HealthStatus {
  status: string;
  environment: string;
  version: string;
  timestamp: string;
}

export function HealthCheck() {
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

  useEffect(() => {
    fetch(`${apiUrl}/health`)
      .then((res) => res.json())
      .then((data: HealthStatus) => {
        setHealth(data);
        setLoading(false);
      })
      .catch((err: Error) => {
        setError(err.message);
        setLoading(false);
      });
  }, [apiUrl]);

  const cardStyle: React.CSSProperties = {
    border: "1px solid #e2e8f0",
    borderRadius: "8px",
    padding: "1.5rem",
    background: "#f8fafc",
  };

  if (loading) {
    return (
      <div style={cardStyle}>
        <p style={{ color: "#94a3b8" }}>Checking API health…</p>
      </div>
    );
  }

  if (error) {
    return (
      <div style={{ ...cardStyle, borderColor: "#fca5a5", background: "#fef2f2" }}>
        <h3 style={{ margin: "0 0 0.5rem", color: "#dc2626" }}>❌ API Unreachable</h3>
        <p style={{ margin: 0, color: "#991b1b", fontSize: "0.875rem" }}>{error}</p>
        <p style={{ margin: "0.5rem 0 0", color: "#9ca3af", fontSize: "0.75rem" }}>
          Endpoint: {apiUrl}/health
        </p>
      </div>
    );
  }

  return (
    <div style={{ ...cardStyle, borderColor: "#86efac", background: "#f0fdf4" }}>
      <h3 style={{ margin: "0 0 0.75rem", color: "#16a34a" }}>✅ API Connected</h3>
      <div style={{ display: "grid", gap: "0.5rem", fontSize: "0.875rem" }}>
        <div>
          <strong>Status:</strong> {health?.status}
        </div>
        <div>
          <strong>Environment:</strong> {health?.environment}
        </div>
        <div>
          <strong>Version:</strong> {health?.version}
        </div>
        <div>
          <strong>Timestamp:</strong> {health?.timestamp}
        </div>
      </div>
      <p style={{ margin: "0.75rem 0 0", color: "#9ca3af", fontSize: "0.75rem" }}>
        Endpoint: {apiUrl}/health
      </p>
    </div>
  );
}
