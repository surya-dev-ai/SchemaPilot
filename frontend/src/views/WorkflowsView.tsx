import { useEffect, useState } from "react";
import { formatApiError, listWorkflows, rollbackLabel } from "../api/client";
import type { WorkflowSummary } from "../api/types";
import { ErrorBanner } from "../components/ErrorBanner";

type Props = { onOpen: (workflowId: string) => void };
type LoadState = { kind: "loading" } | { kind: "ready"; workflows: WorkflowSummary[] } | { kind: "error"; message: string };

export function WorkflowsView({ onOpen }: Props) {
  const [state, setState] = useState<LoadState>({ kind: "loading" });
  const [reload, setReload] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    void listWorkflows(controller.signal)
      .then((body) => { if (!controller.signal.aborted) setState({ kind: "ready", workflows: body.workflows }); })
      .catch((error: unknown) => { if (!controller.signal.aborted) setState({ kind: "error", message: formatApiError(error) }); });
    return () => controller.abort();
  }, [reload]);
  if (state.kind === "loading") return <div className="loading-card" role="status">Loading workflow history…</div>;
  if (state.kind === "error") return <div className="stack"><ErrorBanner title="History unavailable" message={state.message} /><p className="muted">History is temporarily unavailable. You can retry the request.</p><button type="button" onClick={() => { setState({ kind: "loading" }); setReload((value) => value + 1); }}>Try again</button></div>;
  if (state.workflows.length === 0) return <div className="empty-state"><h3>No workflows yet</h3><p>Your saved migration proposals and validation results will appear here.</p></div>;
  return (
    <div className="page-stack">
      <div className="page-heading"><div><p className="eyebrow">Workspace</p><h2>Migration history</h2><p className="page-description">Review saved proposals, validation outcomes, and safety evidence.</p></div><span className="schema-count">{state.workflows.length} workflows</span></div>
      <div className="workflow-list">
        {state.workflows.map((workflow) => (
          <article className="workflow-card" key={workflow.id}>
            <div className="workflow-card-main"><div><span className="eyebrow">{workflow.source_id}</span><h3>{workflow.migration_id}</h3><p className="muted">Updated {new Date(workflow.updated_at).toLocaleString()}</p></div><span className="status-pill"><span className="status-dot" />{workflow.state.replaceAll("_", " ")}</span></div>
            <div className="workflow-card-meta"><span>{workflow.visibility === "private" ? "Private workspace" : "Shared team workspace"}</span><span>Rollback: {rollbackLabel(workflow.rollback_status)}</span><span>{workflow.eligible_for_review ? "Eligible for review" : "Review blocked"}</span>{workflow.report_stale ? <span className="warning-text">Evidence is stale</span> : null}</div>
            <button type="button" className="workflow-open" onClick={() => onOpen(workflow.id)}>View workflow <span aria-hidden="true">→</span></button>
          </article>
        ))}
      </div>
    </div>
  );
}
