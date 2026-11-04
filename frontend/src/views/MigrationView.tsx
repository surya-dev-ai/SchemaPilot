import { useEffect, useState } from "react";
import {
  assessRisk,
  createArtifact,
  createPlan,
  createSafetyReport,
  formatApiError,
  getSandboxCheckpointSession,
  persistWorkflow,
  rollbackLabel,
  runDowngrade,
  runRollback,
  runSandbox,
} from "../api/client";
import type {
  MigrationArtifact,
  MigrationProposal,
  RiskAssessment,
  RollbackReport,
  SafetyReport,
  SandboxCheckpointSessionStatus,
  SandboxRun,
  WorkflowDetail,
} from "../api/types";
import { ConfirmPanel } from "../components/ConfirmPanel";
import { ErrorBanner } from "../components/ErrorBanner";

type SessionState = {
  request: string;
  plan: MigrationProposal | null;
  risk: RiskAssessment | null;
  artifact: MigrationArtifact | null;
  sandbox: SandboxRun | null;
  rollback: RollbackReport | null;
  report: SafetyReport | null;
  workflow: WorkflowDetail | null;
};

const empty: SessionState = {
  request: "",
  plan: null,
  risk: null,
  artifact: null,
  sandbox: null,
  rollback: null,
  report: null,
  workflow: null,
};

export function MigrationView({ authEnabled = false, teamWorkspaceAvailable = true }: { authEnabled?: boolean; teamWorkspaceAvailable?: boolean }) {
  const [session, setSession] = useState<SessionState>(empty);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [useLlm, setUseLlm] = useState(false);
  const [sandboxConfirm, setSandboxConfirm] = useState(false);
  const [rollbackConfirm, setRollbackConfirm] = useState(false);
  const [downgradeConfirm, setDowngradeConfirm] = useState(false);
  const [persistConfirm, setPersistConfirm] = useState(false);
  const [visibility, setVisibility] = useState<"shared" | "private">(authEnabled ? "private" : "shared");
  const [retryAction, setRetryAction] = useState<(() => Promise<void>) | null>(null);
  const [recoverySession, setRecoverySession] = useState<SandboxCheckpointSessionStatus | null>(null);
  const [recoveryConfirm, setRecoveryConfirm] = useState(false);
  const [recoveryReport, setRecoveryReport] = useState<RollbackReport | null>(null);
  const [recoveryDowngradeReport, setRecoveryDowngradeReport] = useState<RollbackReport | null>(null);

  useEffect(() => {
    void getSandboxCheckpointSession()
      .then((status) => {
        if (status.active) {
          setRecoverySession(status);
          if (status.downgrade_report) {
            setRecoveryDowngradeReport(status.downgrade_report as unknown as RollbackReport);
          }
        }
      })
      .catch((err: unknown) => setError(formatApiError(err)));
  }, []);

  async function runStep(label: string, action: () => Promise<void>) {
    setBusy(label);
    setError(null);
    setRetryAction(() => action);
    try {
      await action();
      setRetryAction(null);
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setBusy(null);
    }
  }

  const currentStep = session.workflow ? 4 : session.artifact ? 3 : session.plan || session.risk ? 2 : 1;
  const examples = ["Add a nullable text column called phone_number to users.", "Create an index on orders.placed_at.", "Rename users.display_name to full_name."];

  return (
    <div className="page-stack">
      <div className="page-heading"><div><p className="eyebrow">Migration workspace</p><h2>Propose a database change</h2><p className="page-description">Describe the change you need. Review the plan and risk before generating an artifact or validating it in the sandbox.</p></div><span className="status-pill status-safe"><span className="status-dot" /> Sandbox only</span></div>
      <p className="muted">Plans use the current sandbox schema. The demo/source and target databases are not queried by this migration workflow.</p>
      <ol className="journey-steps" aria-label="Migration workflow">{["Describe", "Review", "Validate", "Record"].map((label, index) => { const step = index + 1; return <li key={label} className={step === currentStep ? "journey-active" : step < currentStep ? "journey-complete" : ""} aria-current={step === currentStep ? "step" : undefined}><span>{step < currentStep ? "✓" : step}</span>{label}</li>; })}</ol>
      <p className="muted">Your proposal stays in this session until you choose to save the resulting workflow.</p>
      {error ? <div className="stack"><ErrorBanner message={error} />{retryAction ? <button type="button" onClick={() => void runStep("retry", retryAction)}>Try again</button> : null}</div> : null}
      {busy ? <div className="loading-card" role="status" aria-live="polite">Working on {busy}…</div> : null}

      {recoverySession?.active || recoveryReport ? (
        <article className="panel" aria-labelledby="snapshot-recovery-title">
          <h3 id="snapshot-recovery-title">Resume sandbox recovery</h3>
          {recoverySession?.active ? (
            <>
              <p>
                An earlier sandbox run has not reached a verified restore. Its saved checkpoint is
                {" "}{recoverySession.checkpoint_verified ? "verified" : "not verified"}; session state:
                {" "}<code>{recoverySession.state}</code>.
              </p>
              <p className="muted">This restores the saved pre-migration checkpoint and verifies the sandbox schema and data. It does not run a migration downgrade or touch the demo, app, or target databases.</p>
              {recoverySession.validation_run ? (
                <div>
                  <p>Saved validation: <code>{recoverySession.validation_run.result}</code> · artifact <code>{recoverySession.validation_run.migration_id}</code></p>
                  <p>Baseline schema fingerprint: <code>{recoverySession.baseline_evidence?.schema_fingerprint ?? "missing"}</code> · tables: {recoverySession.baseline_evidence?.tables.length ?? 0}</p>
                  {!session.artifact && recoverySession.validation_run.result === "passed" && !recoverySession.downgrade_report ? (
                    <>
                      <ConfirmPanel label="I confirm testing the migration downgrade in the sandbox only" confirmed={downgradeConfirm} onChange={setDowngradeConfirm} help="This executes the artifact downgrade and verifies its schema result. It does not restore data removed by a downgrade." />
                      <button type="button" disabled={!downgradeConfirm || busy !== null} onClick={() => void runStep("migration downgrade", async () => {
                        const report = await runDowngrade(recoverySession.migration_id!, true, recoverySession.snapshot_session_id!);
                        setRecoveryDowngradeReport(report);
                        setRecoverySession((current) => current ? { ...current, downgrade_report: report as unknown as Record<string, unknown> } : current);
                      })}>Test migration downgrade</button>
                    </>
                  ) : null}
                  {recoveryDowngradeReport ? <p role="status">Migration downgrade: {recoveryDowngradeReport.downgrade_executed ? "executed" : "not executed"} · {rollbackLabel(recoveryDowngradeReport.status)}</p> : null}
                </div>
              ) : null}
              <ConfirmPanel
                label="I confirm resuming recovery on the disposable sandbox only"
                confirmed={recoveryConfirm}
                onChange={setRecoveryConfirm}
                help="The saved checkpoint is retained until restoration is verified."
              />
              <button
                type="button"
                disabled={!recoveryConfirm || busy !== null || !recoverySession.snapshot_session_id || !recoverySession.checkpoint_verified}
                onClick={() => void runStep("sandbox recovery", async () => {
                  const report = await runRollback(
                    recoverySession.migration_id!,
                    true,
                    recoverySession.snapshot_session_id!,
                  );
                  setRecoveryReport(report);
                  if (report.preexisting_sandbox_recovery?.restore_status === "restore_verified") {
                    setRecoverySession((current) => current ? { ...current, active: false } : current);
                  } else {
                    setRecoverySession((current) => current ? { ...current, state: "recovery_required" } : current);
                  }
                })}
              >
                Resume recovery and verify restore
              </button>
              {recoverySession.error ? <p role="alert">{recoverySession.error}</p> : null}
            </>
          ) : null}
          {recoveryReport ? <p role="status">Restore result: <code>{recoveryReport.preexisting_sandbox_recovery?.restore_status ?? "not verified"}</code>.</p> : null}
        </article>
      ) : null}

      <label className="field">
        Describe the change
        <textarea
          value={session.request}
          onChange={(event) =>
            setSession((current) => ({ ...current, request: event.target.value }))
          }
          rows={4}
          maxLength={2000}
          placeholder="Example: Add a nullable text column called phone_number to users."
        />
        <span className="field-hint">Be specific about the table, column, and any default for existing records. Maximum 2,000 characters.</span>
      </label>

      <div className="prompt-examples" aria-label="Example requests"><span className="field-hint">Try an example</span>{examples.map((example) => <button type="button" className="prompt-chip" key={example} onClick={() => setSession((current) => ({ ...current, request: example }))}>{example}</button>)}</div>

      <label className="confirm">
        <input
          type="checkbox"
          checked={useLlm}
          onChange={(event) => setUseLlm(event.target.checked)}
        />
        Use optional AI assistance to interpret this request
      </label>

      <div className="button-row">
        <button
          type="button"
          disabled={!session.request.trim() || busy !== null}
          onClick={() =>
            void runStep("plan", async () => {
              const plan = await createPlan(session.request.trim(), useLlm);
              setSession((current) => ({
                ...current,
                plan,
                risk: null,
                artifact: null,
                sandbox: null,
                rollback: null,
                report: null,
                workflow: null,
              }));
            })
          }
        >
          Review plan
        </button>
        <button
          type="button"
          disabled={!session.request.trim() || busy !== null}
          onClick={() =>
            void runStep("risk", async () => {
              const risk = await assessRisk(session.request.trim(), useLlm);
              setSession((current) => ({ ...current, risk }));
            })
          }
        >
          Assess risk
        </button>
        <button
          type="button"
          disabled={!session.request.trim() || busy !== null}
          onClick={() =>
            void runStep("artifact", async () => {
              const artifact = await createArtifact(session.request.trim(), useLlm);
              setSession((current) => ({
                ...current,
                artifact,
                sandbox: null,
                rollback: null,
                report: null,
                workflow: null,
              }));
            })
          }
        >
          Generate migration
        </button>
      </div>

      {session.plan ? (
        <article className="panel">
          <h3>Plan</h3>
          <p>
            Original request: <code>{session.plan.request}</code>
          </p>
          <p>
            Interpretation path: <code>{session.plan.interpretation_path}</code> · provider:{" "}
            <code>{session.plan.provider_status}</code>
            {session.plan.provider_name ? (
              <>
                {" "}
                (<code>{session.plan.provider_name}</code>)
              </>
            ) : null}
          </p>
          {session.plan.provider_error ? (
            <p className="banner banner-warn">{session.plan.provider_error}</p>
          ) : null}
          {session.plan.llm_suggestion ? (
            <div>
              <h4>Model-suggested interpretation</h4>
              <p>{session.plan.llm_suggestion.summary}</p>
              <ul>
                {session.plan.llm_suggestion.clarification_questions.map((question) => (
                  <li key={`${question.topic}-${question.text}`}>
                    Clarification ({question.topic}): {question.text}
                  </li>
                ))}
                {session.plan.llm_suggestion.operations.map((operation, index) => (
                  <li key={`${operation.kind}-${index}`}>
                    Suggested {operation.kind}
                    {operation.table ? ` on ${operation.table}` : ""}
                    {operation.column ? `.${operation.column}` : ""}
                  </li>
                ))}
              </ul>
              <p className="muted">
                Suggestions are untrusted. The deterministic plan and risk engine below are
                authoritative. An LLM result is never an approval.
              </p>
            </div>
          ) : null}
          <p>
            Status: <code>{session.plan.status}</code>
          </p>
          <p>{session.plan.summary}</p>
          {session.plan.clarification_questions.length > 0 ? (
            <ul>
              {session.plan.clarification_questions.map((question) => (
                <li key={question.id}>{question.text}</li>
              ))}
            </ul>
          ) : null}
          {session.plan.validation_errors.length > 0 ? (
            <ul>
              {session.plan.validation_errors.map((item) => (
                <li key={item.id}>
                  {item.code}: {item.message}
                </li>
              ))}
            </ul>
          ) : null}
          <ul>
            {session.plan.operations.map((operation) => (
              <li key={operation.id}>
                {operation.kind}: {operation.summary}
              </li>
            ))}
          </ul>
        </article>
      ) : null}

      {session.risk ? (
        <article className="panel">
          <h3>Risk</h3>
          <p>
            {session.artifact?.sandbox_only
              ? "Risk remains policy-blocked for a target database; a sandbox-only review artifact was generated."
              : `Eligible for artifact: ${String(session.risk.artifact_eligible)} (${session.risk.eligibility_reason})`}
          </p>
          <ul>
            {session.risk.findings.map((finding) => (
              <li key={finding.id}>
                <code>{finding.rule_id}</code> · {finding.severity} · {finding.disposition} · data
                check {finding.data_check}
                <br />
                {finding.explanation}
                <br />
                Mitigation: {finding.mitigation}
              </li>
            ))}
          </ul>
        </article>
      ) : null}

      {session.artifact ? (
        <article className="panel">
          <h3>Artifact</h3>
          <p>
            Migration ID: <code>{session.artifact.migration_id}</code>
          </p>
          <p>
            Checksum: <code>{session.artifact.checksum}</code>
          </p>
          <p>
            Status: <code>{session.artifact.status}</code> · applied:{" "}
            <code>{String(session.artifact.applied)}</code>
          </p>
          {session.artifact.sandbox_only ? (
            <p role="alert" className="warning-text">
              Sandbox-only destructive preview. The risk remains policy-blocked for any target
              database. Dropping this column deletes its stored values; the downgrade can recreate
              the column shape, but cannot recover those values or its original nullability.
            </p>
          ) : null}
          <p>
            Module location: <code>{session.artifact.location}</code>
          </p>
          <pre className="code-block">{session.artifact.sql_preview}</pre>
          <p className="muted">
            Generated does not mean applied. Target execution is not available in this UI.
          </p>
        </article>
      ) : null}

      {session.artifact ? (
        <article className="panel">
          <h3>Sandbox</h3>
          <ConfirmPanel
            label="I confirm running this artifact on schemapilot_sandbox only"
            confirmed={sandboxConfirm}
            onChange={setSandboxConfirm}
            help="This validation runs against the isolated sandbox database only."
          />
          <button
            type="button"
            disabled={!sandboxConfirm || busy !== null || !!session.sandbox?.snapshot_session_id}
            onClick={() =>
              void runStep("sandbox", async () => {
                const sandbox = await runSandbox(session.artifact!.migration_id, true);
                setSession((current) => ({ ...current, sandbox }));
                const savedSession = await getSandboxCheckpointSession();
                if (savedSession.active) setRecoverySession(savedSession);
              })
            }
          >
            Validate in sandbox
          </button>
          {session.sandbox ? (
            <div>
              <p>
                Result: <code>{session.sandbox.result}</code> · upgrade_applied:{" "}
                {String(session.sandbox.upgrade_applied)}
              </p>
                  <p>
                    Pre-migration sandbox snapshot: {session.sandbox.pre_migration_snapshot_verified ? "verified" : "not verified"}
                  </p>
              {session.sandbox.error ? <p role="alert">{session.sandbox.error}</p> : null}
              <ul>
                {session.sandbox.checks.map((check) => (
                  <li key={check.name}>
                    {check.name}: {check.status} — {check.detail}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </article>
      ) : null}

      {session.artifact ? (
        <article className="panel">
          <h3>Migration downgrade test</h3>
          <p className="muted">This executes the generated downgrade inside the sandbox and records schema/data checks. A successful downgrade does not mean data removed by the downgrade was recovered.</p>
          <ConfirmPanel
            label="I confirm testing this migration downgrade in the sandbox only"
            confirmed={downgradeConfirm}
            onChange={setDowngradeConfirm}
            help="This is a separate operation from restoring the pre-migration snapshot."
          />
          <button
            type="button"
            disabled={!downgradeConfirm || busy !== null || session.sandbox?.result !== "passed" || !session.sandbox.snapshot_session_id || !!recoveryDowngradeReport}
            onClick={() => void runStep("migration downgrade", async () => {
              const report = await runDowngrade(
                session.artifact!.migration_id,
                true,
                session.sandbox!.snapshot_session_id!,
              );
              setRecoveryDowngradeReport(report);
              setRecoverySession((current) => current ? { ...current, downgrade_report: report as unknown as Record<string, unknown> } : current);
            })}
          >Test migration downgrade</button>
          {recoveryDowngradeReport ? <p role="status">Downgrade: {recoveryDowngradeReport.downgrade_executed ? "executed" : "not executed"} · {rollbackLabel(recoveryDowngradeReport.status)}</p> : null}
        </article>
      ) : null}

      {session.artifact ? (
        <article className="panel">
          <h3>Sandbox snapshot restoration</h3>
          <ConfirmPanel
            label="I confirm restoring the saved checkpoint on the sandbox only"
            confirmed={rollbackConfirm}
            onChange={setRollbackConfirm}
            help="This restores the verified pre-migration checkpoint and compares the sandbox schema and data. It does not run a migration downgrade. The same-cluster checkpoint is for sandbox recovery, not an independent or production backup."
          />
          <button
            type="button"
            disabled={!rollbackConfirm || busy !== null || !session.sandbox?.snapshot_session_id}
            onClick={() =>
              void runStep("rollback", async () => {
                const rollback = await runRollback(
                  session.artifact!.migration_id,
                  true,
                  session.sandbox!.snapshot_session_id!,
                );
                if (rollback.preexisting_sandbox_recovery?.restore_status === "restore_verified") {
                  setRecoverySession(null);
                }
                setSession((current) => ({ ...current, rollback }));
              })
            }
          >
            Restore sandbox from the saved checkpoint
          </button>
          {session.rollback ? (
            <div>
              <p>
                Migration downgrade executed: <code>{String(session.rollback.downgrade_executed)}</code>
              </p>
              <p>Snapshot restoration outcome: <code>{session.rollback.snapshot_recovery?.restore_status ?? "not attempted"}</code></p>
              {session.rollback.data_loss_limitations.map((item) => (
                <p key={item} className="banner banner-warn">
                  {item}
                </p>
              ))}
              {session.rollback.error ? <p role="alert">{session.rollback.error}</p> : null}
              {session.rollback.snapshot_recovery ? (
                <section aria-label="Sandbox snapshot recovery">
                  <h4>Sandbox snapshot recovery</h4>
                  <p>
                    Checkpoint capture: <code>{session.rollback.snapshot_recovery.backup_status}</code> ·
                    restore: <code>{session.rollback.snapshot_recovery.restore_status}</code>
                  </p>
                  <p>
                    Schema match: {String(session.rollback.snapshot_recovery.schema_match)} · data match: {String(session.rollback.snapshot_recovery.data_match)} · checkpoint retained: {String(session.rollback.snapshot_recovery.checkpoint_retained)}
                  </p>
                  {session.rollback.snapshot_recovery.error ? (
                    <p role="alert">{session.rollback.snapshot_recovery.error}</p>
                  ) : null}
                  <ul>
                    {session.rollback.snapshot_recovery.verification_checks.map((check) => (
                      <li key={check.name}>{check.name}: {check.status} — {check.detail}</li>
                    ))}
                  </ul>
                  <p className="muted">This is a PostgreSQL clone on the same cluster for sandbox recovery only, not an independent or production backup. Rollback evidence is not human approval or production-apply authorization; target execution remains disabled.</p>
                  <p>Pre-existing sandbox state: {session.rollback.preexisting_sandbox_recovery?.restore_status ?? "not verified"}</p>
                </section>
              ) : null}
            </div>
          ) : null}
        </article>
      ) : null}

      {session.artifact ? (
        <article className="panel">
          <h3>Safety report</h3>
          <button
            type="button"
            disabled={
              busy !== null ||
              !session.sandbox?.snapshot_session_id ||
              session.rollback?.snapshot_session_id !== session.sandbox.snapshot_session_id
            }
            onClick={() =>
              void runStep("report", async () => {
                const report = await createSafetyReport(
                  session.artifact!.migration_id,
                  session.request.trim(),
                  true,
                  useLlm,
                  session.sandbox?.snapshot_session_id ?? undefined,
                );
                setSession((current) => ({ ...current, report }));
              })
            }
          >
            Create safety report
          </button>
          {session.report ? (
            <div>
              <p>
                Eligible for review: {String(session.report.eligible_for_review)} · approved:{" "}
                {String(session.report.approved)} · applied: {String(session.report.applied)} ·
                fully_reversible: {String(session.report.fully_reversible)}
              </p>
              {session.artifact?.sandbox_only ? (
                <p className="muted">
                  Review eligibility is not approval. This destructive change remains blocked for
                  target execution; authentication is unavailable and no approval has been recorded.
                </p>
              ) : null}
              <p>Migration downgrade executed: {String(session.report.downgrade_executed)}</p>
              <p>Snapshot restoration: {session.report.snapshot_recovery?.restore_status ?? "not attempted"}</p>
              <p>Sandbox checkpoint restore: {session.report.snapshot_recovery?.restore_status ?? "not verified"}</p>
              <p>Pre-existing sandbox preservation: {session.report.preexisting_sandbox_recovery?.restore_status ?? "not verified"}</p>
              {session.report.blocking_reasons.length > 0 ? (
                <ul>
                  {session.report.blocking_reasons.map((reason) => (
                    <li key={reason}>{reason}</li>
                  ))}
                </ul>
              ) : null}
              {session.report.missing_evidence.length > 0 ? (
                <ul>
                  {session.report.missing_evidence.map((item) => (
                    <li key={item}>Missing: {item}</li>
                  ))}
                </ul>
              ) : null}
            </div>
          ) : null}
        </article>
      ) : null}

      {session.artifact ? (
        <article className="panel">
          <h3>Persist workflow</h3>
          {authEnabled ? <label className="field">Save in
            <select value={visibility} onChange={(event) => setVisibility(event.target.value as "shared" | "private")}>
              <option value="private">My private workspace</option>
              {teamWorkspaceAvailable ? <option value="shared">Shared team workspace</option> : null}
            </select>
            <span className="field-hint">Private workflows are visible only to you. Shared workflows are visible to all signed-in team members.</span>
          </label> : null}
          <ConfirmPanel
            label="Persist this evidence in the application database"
            confirmed={persistConfirm}
            onChange={setPersistConfirm}
            help="Save the proposal and its validation evidence to workflow history."
          />
          <button
            type="button"
            disabled={
              !persistConfirm ||
              busy !== null ||
              !session.sandbox?.snapshot_session_id ||
              session.rollback?.snapshot_session_id !== session.sandbox.snapshot_session_id
            }
            onClick={() =>
              void runStep("persist", async () => {
                const workflow = await persistWorkflow(
                  session.artifact!.migration_id,
                  session.request.trim(),
                  true,
                  useLlm,
                  visibility,
                  session.sandbox?.snapshot_session_id ?? undefined,
                );
                setSession((current) => ({ ...current, workflow }));
              })
            }
          >
            Save to history
          </button>
          {session.workflow ? (
            <p>
              Persisted workflow <code>{session.workflow.id}</code>. Open History to inspect
              approvals and audit.
            </p>
          ) : null}
        </article>
      ) : null}
    </div>
  );
}
