import { useEffect, useState } from "react";
import {
  approvalUiAllowed,
  formatApiError,
  getAudit,
  getWorkflow,
  rollbackLabel,
} from "../api/client";
import type { AuditEventSummary, WorkflowDetail } from "../api/types";
import { ErrorBanner } from "../components/ErrorBanner";

type Props = {
  workflowId: string;
  onBack: () => void;
};

type LoadState =
  | { kind: "loading" }
  | { kind: "ready"; detail: WorkflowDetail; events: AuditEventSummary[] }
  | { kind: "error"; message: string };

export function WorkflowDetailView({ workflowId, onBack }: Props) {
  const [state, setState] = useState<LoadState>({ kind: "loading" });

  useEffect(() => {
    const controller = new AbortController();
    async function load() {
      try {
        const detail = await getWorkflow(workflowId, controller.signal);
        const audit = await getAudit(workflowId, controller.signal);
        if (!controller.signal.aborted) {
          setState({ kind: "ready", detail, events: audit.events });
        }
      } catch (error) {
        if (!controller.signal.aborted) {
          setState({ kind: "error", message: formatApiError(error) });
        }
      }
    }
    void load();
    return () => controller.abort();
  }, [workflowId]);

  if (state.kind === "loading") {
    return <p>Loading workflow detail.</p>;
  }
  if (state.kind === "error") {
    return (
      <div className="stack">
        <button type="button" onClick={onBack}>
          Back to history
        </button>
        <ErrorBanner message={state.message} />
      </div>
    );
  }

  const { detail, events } = state;
  const approvalGate = approvalUiAllowed(detail);

  return (
    <div className="stack">
      <button type="button" onClick={onBack}>
        Back to history
      </button>
      <h3>Workflow {detail.id}</h3>
      <dl className="facts">
        <div>
          <dt>Migration ID</dt>
          <dd className="mono">{detail.migration_id}</dd>
        </div>
        <div>
          <dt>Artifact checksum</dt>
          <dd className="mono">{detail.artifact_checksum}</dd>
        </div>
        <div>
          <dt>Report checksum</dt>
          <dd className="mono">{detail.report_checksum}</dd>
        </div>
        <div>
          <dt>State</dt>
          <dd>{detail.state}</dd>
        </div>
        <div>
          <dt>Artifact applied</dt>
          <dd>{String(detail.artifact_applied)}</dd>
        </div>
        <div>
          <dt>Rollback</dt>
          <dd>{rollbackLabel(detail.rollback_status)}</dd>
        </div>
        <div>
          <dt>Eligible for review</dt>
          <dd>{String(detail.eligible_for_review)}</dd>
        </div>
        <div>
          <dt>Report stale</dt>
          <dd>{String(detail.report_stale)}</dd>
        </div>
        <div>
          <dt>Fully reversible</dt>
          <dd>{String(detail.fully_reversible)}</dd>
        </div>
      </dl>

      <article className="panel">
        <h4>Request and intent</h4>
        <p>{detail.report.request}</p>
        <p>{detail.report.interpreted_intent}</p>
        <ul>
          {detail.report.operations.map((operation) => (
            <li key={operation.id}>
              {operation.kind}: {operation.summary}
            </li>
          ))}
        </ul>
      </article>

      <article className="panel">
        <h4>Risk findings</h4>
        <ul>
          {detail.report.risk_findings.map((finding) => (
            <li key={finding.id}>
              <code>{finding.rule_id}</code> · {finding.disposition} · {finding.data_check}
              <br />
              {finding.explanation}
            </li>
          ))}
        </ul>
      </article>

      <article className="panel">
        <h4>Sandbox and rollback</h4>
        {detail.report.sandbox ? (
          <p>
            Sandbox result: <code>{detail.report.sandbox.result}</code> · upgrade_applied:{" "}
            {String(detail.report.sandbox.upgrade_applied)}
          </p>
        ) : (
          <p>No sandbox evidence on this report.</p>
        )}
        <p>Rollback status: {rollbackLabel(detail.rollback_status)}</p>
        {detail.report.data_loss_limitations.map((item) => (
          <p key={item} className="banner banner-warn">
            {item}
          </p>
        ))}
      </article>

      <article className="panel">
        <h4>Blockers and missing evidence</h4>
        {detail.report.blocking_reasons.length === 0 &&
        detail.report.missing_evidence.length === 0 ? (
          <p>None recorded.</p>
        ) : (
          <ul>
            {detail.report.blocking_reasons.map((reason) => (
              <li key={reason}>{reason}</li>
            ))}
            {detail.report.missing_evidence.map((item) => (
              <li key={item}>Missing: {item}</li>
            ))}
          </ul>
        )}
      </article>

      <article className="panel">
        <h4>Approval</h4>
        <p>
          Approval and target execution are different. This UI does not enable target apply. The
          backend reports authentication_available=false, so a verified human approval cannot be
          recorded from the console.
        </p>
        <p>
          Bound values that any future approval must use: artifact checksum{" "}
          <code>{detail.artifact_checksum}</code>, report checksum{" "}
          <code>{detail.report_checksum}</code>.
        </p>
        <p className="banner banner-warn">{approvalGate.reason}</p>
        <button type="button" disabled>
          Record approval (blocked)
        </button>
        {detail.approvals.length > 0 ? (
          <ul>
            {detail.approvals.map((approval) => (
              <li key={approval.id}>
                {approval.decision} for target <code>{approval.target_identity}</code> · auth{" "}
                {String(approval.authentication_available)} · approver{" "}
                {approval.approver_identity ?? "none"}
                <br />
                {approval.limitation}
              </li>
            ))}
          </ul>
        ) : (
          <p>No approval records.</p>
        )}
      </article>

      <article className="panel">
        <h4>Audit</h4>
        <p>
          Events from <code>GET /api/v1/workflows/{`{id}`}/audit</code>.
        </p>
        <ul>
          {events.map((event) => (
            <li key={event.id}>
              <code>{event.event_type}</code> · {event.created_at}
              <pre className="code-block">{JSON.stringify(event.detail, null, 2)}</pre>
            </li>
          ))}
        </ul>
      </article>
    </div>
  );
}
