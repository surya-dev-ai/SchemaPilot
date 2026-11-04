import { useEffect, useState } from "react";
import { beginLogin, endSession, formatApiError, getAuthSession, getHealth, setCsrfToken } from "./api/client";
import type { AuthSession, HealthResponse } from "./api/types";
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
  if (hash.startsWith("workflow/")) return { name: "workflow", id: hash.slice("workflow/".length) };
  if (hash === "migration") return { name: "migration" };
  if (hash === "workflows") return { name: "workflows" };
  if (hash === "settings") return { name: "settings" };
  return { name: "sources" };
}

export function App() {
  const [view, setView] = useState<View>(() => parseHash());
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [healthError, setHealthError] = useState<string | null>(null);
  const [auth, setAuth] = useState<AuthSession | null>(null);
  const [authError, setAuthError] = useState<string | null>(null);
  const [logoutBusy, setLogoutBusy] = useState(false);

  useEffect(() => {
    const onHash = () => setView(parseHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void getHealth(controller.signal)
      .then((value) => { if (!controller.signal.aborted) { setHealth(value); setHealthError(null); } })
      .catch((error: unknown) => { if (!controller.signal.aborted) { setHealth(null); setHealthError(formatApiError(error)); } });
    void getAuthSession(controller.signal)
      .then((value) => {
        if (!controller.signal.aborted) {
          setAuth(value);
          setCsrfToken(value.csrf_token);
          setAuthError(null);
        }
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) setAuthError(formatApiError(error));
      });
    return () => controller.abort();
  }, []);

  function go(next: View) {
    window.location.hash = next.name === "workflow" ? `workflow/${next.id}` : next.name === "sources" ? "sources" : next.name;
    setView(next);
  }

  const navItems: { name: View["name"]; label: string; view: View }[] = [
    { name: "migration", label: "New migration", view: { name: "migration" } },
    { name: "sources", label: "Data sources", view: { name: "sources" } },
    { name: "workflows", label: "History", view: { name: "workflows" } },
    { name: "settings", label: "Safety & status", view: { name: "settings" } },
  ];

  if (authError) {
    return <main className="auth-gate"><section className="panel"><h1>Sign-in status unavailable</h1><p>{authError}</p><button type="button" onClick={() => window.location.reload()}>Retry</button></section></main>;
  }
  if (!auth) {
    return <main className="auth-gate"><section className="panel" role="status">Checking your session…</section></main>;
  }
  if (auth.enabled && !auth.authenticated) {
    return <main className="auth-gate"><section className="panel auth-panel"><span className="brand-mark" aria-hidden="true">S</span><p className="eyebrow">SchemaPilot</p><h1>Sign in to your workspace</h1><p className="page-description">Use your organization’s identity provider to access shared and private migration workspaces.</p><button type="button" onClick={beginLogin}>Continue with organization account</button><p className="field-hint">Accounts and group membership are managed by your OIDC identity provider.</p></section></main>;
  }

  return (
    <div className="app-shell">
      <header className="top">
        <div className="brand-lockup">
          <span className="brand-mark" aria-hidden="true">S</span>
          <div><p className="brand-name">SchemaPilot</p><p className="brand-subtitle">Database change workspace</p></div>
        </div>
        <div className="header-right">
          <span className={`status-pill ${health && !health.target_execution_enabled ? "status-safe" : "status-muted"}`}><span className="status-dot" />{health ? `Target execution ${health.target_execution_enabled ? "enabled" : "disabled"}` : "Safety status pending"}</span>
          <p className="status-chip" aria-live="polite">
            {health ? `API ${health.status} · target ${health.target_execution_enabled ? "enabled" : "disabled"}` : healthError ? "API unavailable" : "Connecting to API…"}
          </p>
          {auth.enabled && auth.user ? <div className="user-session"><span title={auth.user.roles.join(", ")}>{auth.user.display_name || auth.user.email || "Signed in"}</span><button type="button" disabled={logoutBusy} onClick={() => { setLogoutBusy(true); void endSession().then((next) => setAuth(next)).catch((error: unknown) => setAuthError(formatApiError(error))).finally(() => setLogoutBusy(false)); }}>{logoutBusy ? "Signing out…" : "Sign out"}</button></div> : null}
        </div>
      </header>
      <nav aria-label="Primary">
        {navItems.map((item) => <button key={item.name} type="button" className={view.name === item.name || (item.name === "workflows" && view.name === "workflow") ? "active" : ""} aria-current={view.name === item.name || (item.name === "workflows" && view.name === "workflow") ? "page" : undefined} onClick={() => go(item.view)}>{item.label}</button>)}
      </nav>
      <main>
        {view.name === "sources" ? <SourcesView /> : null}
        {view.name === "migration" ? <MigrationView authEnabled={auth.enabled} teamWorkspaceAvailable={auth.can_access_team_workspace} /> : null}
        {view.name === "workflows" ? <WorkflowsView onOpen={(id) => go({ name: "workflow", id })} /> : null}
        {view.name === "workflow" ? <WorkflowDetailView workflowId={view.id} onBack={() => go({ name: "workflows" })} /> : null}
        {view.name === "settings" ? <SettingsView /> : null}
      </main>
    </div>
  );
}
