import { HealthCheck } from "./health-check";

export default function HomePage() {
  return (
    <main style={{ fontFamily: "system-ui, sans-serif", padding: "2rem", maxWidth: "600px", margin: "0 auto" }}>
      <h1 style={{ fontSize: "2rem", marginBottom: "0.5rem" }}>Argonis</h1>
      <p style={{ color: "#666", marginBottom: "2rem" }}>AI Agent Platform</p>
      <HealthCheck />
    </main>
  );
}
