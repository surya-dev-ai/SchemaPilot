import { useEffect, useState } from "react";
import { formatApiError, listWorkflows, rollbackLabel } from "../api/client";
import type { WorkflowSummary } from "../api/types";
import { ErrorBanner } from "../components/ErrorBanner";

type Props = {
  onOpen: (workflowId: string) => void;
};

type LoadState =
  | { kind: "loading" }
  | { kind: "ready"; workflows: WorkflowSummary[] }
  | { kind: "error"; message: string };

export function WorkflowsView({ onOpen }: Props) {
  const [state, setState] = useState<LoadState>({ kind: "loading" });

  useEffect(() => {
    const controller = new AbortController();
    void listWorkflows(controller.signal)
      .then((body) => {
        if (!controller.signal.aborted) {
          setState({ kind: "ready", workflows: body.workflows });
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
    return <p>Loading persisted workflows from the application database.</p>;
  }
  if (state.kind === "error") {
    return (
      <div className="stack">
        <ErrorBanner
          title="History unavailable"
          message={state.message}
        />
        <p className="muted">
          This view does not invent local history when the application database is unavailable.
        </p>
      </div>
    );
  }

  if (state.workflows.length === 0) {
    return <p>No persisted workflows yet.</p>;
  }

  return (
    <div className="stack">
      <p className="lead">
        History comes from <code>GET /api/v1/workflows</code>.
      </p>
      <ul className="plain-list">
        {state.workflows.map((workflow) => (
          <li key={workflow.id}>
            <button type="button" className="linkish" onClick={() => onOpen(workflow.id)}>
              {workflow.migration_id}
            </button>{" "}
            · state <code>{workflow.state}</code> · rollback{" "}
            {rollbackLabel(workflow.rollback_status)} ·{" "}
            {workflow.eligible_for_review ? "eligible" : "not eligible"}
            {workflow.report_stale ? " · stale" : ""}
            <br />
            <span className="mono muted">{workflow.artifact_checksum}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
