import { useEffect, useState } from "react";
import { approvalUiAllowed, formatApiError, getAudit, getWorkflow, rollbackLabel } from "../api/client";
import type { AuditEventSummary, WorkflowDetail } from "../api/types";
import { ErrorBanner } from "../components/ErrorBanner";

type Props = { workflowId: string; onBack: () => void };
type LoadState = { kind: "loading" } | { kind: "ready"; detail: WorkflowDetail; events: AuditEventSummary[] } | { kind: "error"; message: string };

export function WorkflowDetailView({ workflowId, onBack }: Props) {
  const [state, setState] = useState<LoadState>({ kind: "loading" });
  const [reload, setReload] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    async function load() {
      try {
        const detail = await getWorkflow(workflowId, controller.signal);
        const audit = await getAudit(workflowId, controller.signal);
        if (!controller.signal.aborted) setState({ kind: "ready", detail, events: audit.events });
      } catch (error) {
        if (!controller.signal.aborted) setState({ kind: "error", message: formatApiError(error) });
      }
    }
    void load();
    return () => controller.abort();
  }, [workflowId, reload]);

  if (state.kind === "loading") return <div className="loading-card" role="status">Loading workflow details…</div>;
  if (state.kind === "error") return <div className="stack"><button type="button" onClick={onBack}>Back to history</button><ErrorBanner message={state.message} /><button type="button" onClick={() => { setState({ kind: "loading" }); setReload((value) => value + 1); }}>Try again</button></div>;

  const { detail, events } = state;
  const approvalGate = approvalUiAllowed(detail);
  return (
    <div className="page-stack">
      <button type="button" className="back-button" onClick={onBack}>← Back to history</button>
      <div className="page-heading"><div><p className="eyebrow">Workflow details</p><h2>{detail.migration_id}</h2><p className="page-description">Request summary, safety findings, and recorded validation evidence.</p></div><span className="status-pill">{detail.state.replaceAll("_", " ")}</span></div>
      <dl className="facts">
        <div><dt>Rollback</dt><dd>{rollbackLabel(detail.rollback_status)}</dd></div>
        <div><dt>Review status</dt><dd>{detail.eligible_for_review ? "Eligible" : "Blocked"}</dd></div>
        <div><dt>Evidence freshness</dt><dd>{detail.report_stale ? "Needs refresh" : "Current"}</dd></div>
        <div><dt>Reversibility</dt><dd>{detail.fully_reversible ? "Fully reversible" : "Partial or unknown"}</dd></div>
      </dl>
      <details className="technical-details"><summary>Technical identifiers</summary><dl className="inline-facts">
        <div><dt>Workflow ID</dt><dd className="mono">{detail.id}</dd></div><div><dt>Artifact checksum</dt><dd className="mono">{detail.artifact_checksum}</dd></div><div><dt>Report checksum</dt><dd className="mono">{detail.report_checksum}</dd></div><div><dt>Artifact applied</dt><dd>{detail.artifact_applied ? "Yes" : "No"}</dd></div>
      </dl></details>

      <article className="panel"><h3>Request and intent</h3><p>{detail.report.request}</p><p className="muted">{detail.report.interpreted_intent}</p>
        <ul className="operation-list">{detail.report.operations.map((operation) => <li key={operation.id}><span className="operation-kind">{operation.kind.replaceAll("_", " ")}</span><span>{operation.summary}</span></li>)}</ul>
      </article>

      <article className="panel"><h3>Risk findings</h3>{detail.report.risk_findings.length === 0 ? <p className="muted">No risk findings were recorded.</p> : <div className="finding-list">{detail.report.risk_findings.map((finding) => <div className="finding-card" key={finding.id}><div><strong>{finding.disposition.replaceAll("_", " ")}</strong><span className="muted"> · {finding.severity}</span></div><p>{finding.explanation}</p>{finding.mitigation ? <p className="muted">Mitigation: {finding.mitigation}</p> : null}</div>)}</div>}</article>

      <article className="panel"><h3>Sandbox validation, migration downgrade, and snapshot recovery</h3>{detail.report.sandbox ? <div className="result-summary"><span className={`status-pill ${detail.report.sandbox.result === "passed" ? "status-ready" : "status-muted"}`}><span className="status-dot" />Validation {detail.report.sandbox.result}</span><span>{detail.report.sandbox.checks.filter((check) => check.status === "passed").length} checks passed</span></div> : <p className="muted">No sandbox validation evidence on this report.</p>}
        <p>Migration downgrade executed: {String(detail.report.downgrade_executed)}</p>
        <p>Downgrade assessment: {rollbackLabel(detail.rollback_status)}</p>
        {detail.report.snapshot_recovery ? <div><p>Checkpoint capture: {detail.report.snapshot_recovery.backup_status} · Snapshot restore: {detail.report.snapshot_recovery.restore_status}</p><p>Schema match: {String(detail.report.snapshot_recovery.schema_match)} · Data match: {String(detail.report.snapshot_recovery.data_match)} · Checkpoint retained: {String(detail.report.snapshot_recovery.checkpoint_retained)}</p>{detail.report.snapshot_recovery.error ? <p role="alert">{detail.report.snapshot_recovery.error}</p> : null}<details className="technical-details"><summary>Snapshot verification checks</summary><ul>{detail.report.snapshot_recovery.verification_checks.map((check) => <li key={check.name}><strong>{check.name}</strong> · {check.status} — {check.detail}</li>)}</ul></details><p className="muted">This is a PostgreSQL clone on the same cluster for sandbox recovery only, not an independent or production backup. Rollback evidence is not approval or production-apply authorization; target execution remains disabled.</p></div> : <p className="banner banner-warn">No verified snapshot restoration evidence is recorded.</p>}
        {detail.report.preexisting_sandbox_recovery ? <p>Pre-existing sandbox preservation: {detail.report.preexisting_sandbox_recovery.backup_status} · restore {detail.report.preexisting_sandbox_recovery.restore_status} · schema match {String(detail.report.preexisting_sandbox_recovery.schema_match)} · data match {String(detail.report.preexisting_sandbox_recovery.data_match)}</p> : <p className="banner banner-warn">No pre-existing sandbox state preservation evidence is recorded.</p>}
        {detail.report.data_loss_limitations.map((item) => <p key={item} className="banner banner-warn">{item}</p>)}
        {detail.report.sandbox?.checks.length ? <details className="technical-details"><summary>Validation checks</summary><ul>{detail.report.sandbox.checks.map((check) => <li key={check.name}><strong>{check.name}</strong> · {check.status} — {check.detail}</li>)}</ul></details> : null}
      </article>

      <article className="panel"><h3>Review readiness</h3>{detail.report.blocking_reasons.length === 0 && detail.report.missing_evidence.length === 0 ? <p>No blockers or missing evidence recorded.</p> : <ul>{detail.report.blocking_reasons.map((reason) => <li key={reason}>{reason}</li>)}{detail.report.missing_evidence.map((item) => <li key={item}>Missing: {item}</li>)}</ul>}</article>

      <article className="panel"><h3>Approval</h3><p>Approval and target execution are separate. Verified authentication is unavailable, so this workspace cannot record a human approval or apply the migration.</p><p className="banner banner-warn">{approvalGate.reason}</p><button type="button" disabled>Approval unavailable</button>
        {detail.approvals.length ? <details className="technical-details"><summary>Recorded approval metadata</summary><ul>{detail.approvals.map((approval) => <li key={approval.id}>{approval.decision} · authentication {approval.authentication_available ? "available" : "unavailable"} · {approval.limitation}</li>)}</ul></details> : <p className="muted">No approval records.</p>}
      </article>

      <article className="panel"><h3>Audit trail</h3>{events.length === 0 ? <p className="muted">No audit events were recorded.</p> : <div className="audit-list">{events.map((event) => <details className="audit-event" key={event.id}><summary><strong>{event.event_type.replaceAll("_", " ")}</strong><span>{new Date(event.created_at).toLocaleString()}</span></summary><pre className="code-block">{JSON.stringify(event.detail, null, 2)}</pre></details>)}</div>}</article>
    </div>
  );
}
