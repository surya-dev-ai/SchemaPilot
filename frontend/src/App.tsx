import { useEffect, useState } from "react";
import { formatApiError, getHealth } from "./api/client";
import type { HealthResponse } from "./api/types";
import { MigrationView } from "./views/MigrationView";
import { SettingsView } from "./views/SettingsView";
import { SourcesView } from "./views/SourcesView";
import { WorkflowDetailView } from "./views/WorkflowDetailView";
import { WorkflowsView } from "./views/WorkflowsView";

type View =
  | { name: "sources" }
  | { name: "migration" }
  | { name: "workflows" }
  | { name: "workflow"; id: string }
  | { name: "settings" };

function parseHash(): View {
  const hash = window.location.hash.replace(/^#/, "");
  if (hash.startsWith("workflow/")) {
    return { name: "workflow", id: hash.slice("workflow/".length) };
  }
  if (hash === "migration") {
    return { name: "migration" };
  }
  if (hash === "workflows") {
    return { name: "workflows" };
  }
  if (hash === "settings") {
    return { name: "settings" };
  }
  return { name: "sources" };
}

export function App() {
  const [view, setView] = useState<View>(() => parseHash());
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [healthError, setHealthError] = useState<string | null>(null);

  useEffect(() => {
    const onHash = () => setView(parseHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void getHealth(controller.signal)
      .then((value) => {
        if (!controller.signal.aborted) {
          setHealth(value);
          setHealthError(null);
        }
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) {
          setHealth(null);
          setHealthError(formatApiError(error));
        }
      });
    return () => controller.abort();
  }, []);

  function go(next: View) {
    if (next.name === "workflow") {
      window.location.hash = `workflow/${next.id}`;
    } else if (next.name === "sources") {
      window.location.hash = "sources";
    } else {
      window.location.hash = next.name;
    }
    setView(next);
  }

  return (
    <div className="app-shell">
      <header className="top">
        <div>
          <p className="eyebrow">SchemaPilot console</p>
          <h1>SchemaPilot</h1>
          <p className="tagline">AI proposes. The system verifies. You approve.</p>
        </div>
        <p className="status-chip" aria-live="polite">
          {health
            ? `API ${health.status} · target ${
                health.target_execution_enabled ? "enabled" : "disabled"
              } · auth unavailable`
            : healthError
              ? `API unreachable: ${healthError}`
              : "Checking API"}
        </p>
      </header>

      <nav aria-label="Primary">
        <button type="button" className={view.name === "sources" ? "active" : ""} onClick={() => go({ name: "sources" })}>
          Data sources
        </button>
        <button
          type="button"
          className={view.name === "migration" ? "active" : ""}
          onClick={() => go({ name: "migration" })}
        >
          New migration
        </button>
        <button
          type="button"
          className={view.name === "workflows" || view.name === "workflow" ? "active" : ""}
          onClick={() => go({ name: "workflows" })}
        >
          History
        </button>
        <button
          type="button"
          className={view.name === "settings" ? "active" : ""}
          onClick={() => go({ name: "settings" })}
        >
          Settings
        </button>
      </nav>

      <main>
        {view.name === "sources" ? <SourcesView /> : null}
        {view.name === "migration" ? <MigrationView /> : null}
        {view.name === "workflows" ? (
          <WorkflowsView onOpen={(id) => go({ name: "workflow", id })} />
        ) : null}
        {view.name === "workflow" ? (
          <WorkflowDetailView workflowId={view.id} onBack={() => go({ name: "workflows" })} />
        ) : null}
        {view.name === "settings" ? <SettingsView /> : null}
      </main>
    </div>
  );
}
