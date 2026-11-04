import { useEffect, useState } from "react";
import { formatApiError, getHealth } from "../api/client";
import type { HealthResponse } from "../api/types";
import { ErrorBanner } from "../components/ErrorBanner";

type LoadState = { kind: "loading" } | { kind: "ready"; health: HealthResponse } | { kind: "error"; message: string };

export function SettingsView() {
  const [state, setState] = useState<LoadState>({ kind: "loading" });
  const [reload, setReload] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    void getHealth(controller.signal)
      .then((health) => { if (!controller.signal.aborted) setState({ kind: "ready", health }); })
      .catch((error: unknown) => { if (!controller.signal.aborted) setState({ kind: "error", message: formatApiError(error) }); });
    return () => controller.abort();
  }, [reload]);

  if (state.kind === "loading") return <div className="loading-card" role="status">Checking service and safety status…</div>;
  if (state.kind === "error") return <div className="stack"><ErrorBanner title="Status unavailable" message={state.message} /><button type="button" onClick={() => { setState({ kind: "loading" }); setReload((value) => value + 1); }}>Try again</button></div>;
  const { health } = state;
  const items = [
    { title: "API service", value: health.status === "ok" ? "Operational" : "Needs attention", good: health.status === "ok", detail: `Version ${health.version}` },
    { title: "Sandbox validation", value: health.sandbox_database_configured ? "Configured" : "Unavailable", good: health.sandbox_database_configured, detail: "Migration checks run in an isolated sandbox." },
    { title: "Target database", value: health.target_execution_enabled ? "Execution enabled" : "Execution disabled", good: !health.target_execution_enabled, detail: "Real target changes are currently blocked." },
    { title: "Authentication", value: health.authentication_available ? "Available" : "Not available", good: health.authentication_available, detail: health.authentication_available ? "Access control is available." : "This local console does not provide verified user approval." },
    { title: "AI assistance", value: health.llm_enabled && health.llm_configured ? "Configured" : "Unavailable", good: health.llm_enabled && health.llm_configured, detail: "Configuration does not guarantee that a provider request will succeed." },
  ];
  return (
    <div className="page-stack">
      <div className="page-heading"><div><p className="eyebrow">System overview</p><h2>Safety & status</h2><p className="page-description">A concise view of the safeguards and services available in this workspace.</p></div></div>
      <section className="status-grid" aria-label="Service and safety status">
        {items.map((item) => <article className="status-card" key={item.title}><div className="status-card-top"><span className={`status-pill ${item.good ? "status-ready" : "status-muted"}`}><span className="status-dot" />{item.value}</span></div><h3>{item.title}</h3><p className="muted">{item.detail}</p></article>)}
      </section>
      <p className="banner banner-warn">SchemaPilot is a local development console. Authentication is unavailable, so workflows cannot record a verified human approval. Keep real target execution disabled until access controls and safety checks are in place.</p>
    </div>
  );
}
