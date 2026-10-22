import { useEffect, useState } from "react";
import { formatApiError, getHealth } from "../api/client";
import type { HealthResponse } from "../api/types";
import { ErrorBanner } from "../components/ErrorBanner";

type LoadState =
  | { kind: "loading" }
  | { kind: "ready"; health: HealthResponse }
  | { kind: "error"; message: string };

export function SettingsView() {
  const [state, setState] = useState<LoadState>({ kind: "loading" });

  useEffect(() => {
    const controller = new AbortController();
    void getHealth(controller.signal)
      .then((health) => {
        if (!controller.signal.aborted) {
          setState({ kind: "ready", health });
        }
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) {
          setState({ kind: "error", message: formatApiError(error) });
        }
      });
    return () => controller.abort();
  }, []);

  if (state.kind === "loading") {
    return <p>Loading configuration status.</p>;
  }
  if (state.kind === "error") {
    return <ErrorBanner message={state.message} />;
  }

  const { health } = state;
  return (
    <div className="stack">
      <p className="lead">
        Status comes from <code>GET /api/v1/health</code>. Secrets and connection strings are never
        shown.
      </p>
      <dl className="facts">
        <div>
          <dt>Service</dt>
          <dd>{health.service}</dd>
        </div>
        <div>
          <dt>API version</dt>
          <dd>{health.api_version}</dd>
        </div>
        <div>
          <dt>App database configured</dt>
          <dd>{health.app_database_configured ? "Yes" : "No"}</dd>
        </div>
        <div>
          <dt>Sandbox database configured</dt>
          <dd>{health.sandbox_database_configured ? "Yes" : "No"}</dd>
        </div>
        <div>
          <dt>Target database configured</dt>
          <dd>{health.target_database_configured ? "Yes" : "No"}</dd>
        </div>
        <div>
          <dt>Target execution</dt>
          <dd>{health.target_execution_enabled ? "Enabled" : "Disabled"}</dd>
        </div>
        <div>
          <dt>Migrations on startup</dt>
          <dd>{String(health.migrations_on_startup)}</dd>
        </div>
        <div>
          <dt>Database connectivity</dt>
          <dd>{health.database_connectivity}</dd>
        </div>
        <div>
          <dt>Authentication</dt>
          <dd>
            {health.authentication_available
              ? "Available"
              : "Unavailable (authentication_available=false)"}
          </dd>
        </div>
        <div>
          <dt>LLM assist enabled</dt>
          <dd>{health.llm_enabled ? "Yes" : "No"}</dd>
        </div>
        <div>
          <dt>LLM credentials configured</dt>
          <dd>{health.llm_configured ? "Yes" : "No"}</dd>
        </div>
        <div>
          <dt>LLM provider</dt>
          <dd>{health.llm_provider}</dd>
        </div>
        <div>
          <dt>LLM model</dt>
          <dd>{health.llm_model ?? "n/a"}</dd>
        </div>
      </dl>
      <p className="muted">
        API keys stay on the server. This panel never shows secrets or connection strings.
      </p>
      <p className="banner banner-warn">
        There is no frontend control that enables target execution. Approval and apply remain
        separate from this status panel.
      </p>
    </div>
  );
}
