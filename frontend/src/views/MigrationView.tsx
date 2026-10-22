import { useState } from "react";
import {
  assessRisk,
  createArtifact,
  createPlan,
  createSafetyReport,
  formatApiError,
  persistWorkflow,
  rollbackLabel,
  runRollback,
  runSandbox,
} from "../api/client";
import type {
  MigrationArtifact,
  MigrationProposal,
  RiskAssessment,
  RollbackReport,
  SafetyReport,
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

export function MigrationView() {
  const [session, setSession] = useState<SessionState>(empty);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [useLlm, setUseLlm] = useState(false);
  const [sandboxConfirm, setSandboxConfirm] = useState(false);
  const [rollbackConfirm, setRollbackConfirm] = useState(false);
  const [persistConfirm, setPersistConfirm] = useState(false);

  async function runStep(label: string, action: () => Promise<void>) {
    setBusy(label);
    setError(null);
    try {
      await action();
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="stack">
      <p className="lead">
        This wizard calls the real Phase 4–9 endpoints. Values below are{" "}
        <strong>temporary session state</strong> until you persist a workflow to the application
        database.
      </p>
      {error ? <ErrorBanner message={error} /> : null}
      {busy ? <p aria-live="polite">Working: {busy}</p> : null}

      <label className="field">
        Natural-language request
        <textarea
          value={session.request}
          onChange={(event) =>
            setSession((current) => ({ ...current, request: event.target.value }))
          }
          rows={3}
          maxLength={2000}
        />
      </label>

      <label className="confirm">
        <input
          type="checkbox"
          checked={useLlm}
          onChange={(event) => setUseLlm(event.target.checked)}
        />
        Request optional LLM-assisted interpretation (server-side; falls back if unavailable)
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
          1. Plan
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
          2. Risk
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
          3. Generate artifact
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
            Eligible for artifact: {String(session.risk.artifact_eligible)} (
            {session.risk.eligibility_reason})
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
            help="POST /api/v1/sources/bookstore-demo/artifacts/{migration_id}/sandbox requires confirm=true."
          />
          <button
            type="button"
            disabled={!sandboxConfirm || busy !== null}
            onClick={() =>
              void runStep("sandbox", async () => {
                const sandbox = await runSandbox(session.artifact!.migration_id, true);
                setSession((current) => ({ ...current, sandbox }));
              })
            }
          >
            4. Run sandbox
          </button>
          {session.sandbox ? (
            <div>
              <p>
                Result: <code>{session.sandbox.result}</code> · upgrade_applied:{" "}
                {String(session.sandbox.upgrade_applied)}
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
          <h3>Rollback</h3>
          <ConfirmPanel
            label="I confirm rollback testing on schemapilot_sandbox only"
            confirmed={rollbackConfirm}
            onChange={setRollbackConfirm}
            help="A successful downgrade does not recover former column values. not_verified is not success."
          />
          <button
            type="button"
            disabled={!rollbackConfirm || busy !== null}
            onClick={() =>
              void runStep("rollback", async () => {
                const rollback = await runRollback(session.artifact!.migration_id, true);
                setSession((current) => ({ ...current, rollback }));
              })
            }
          >
            5. Run rollback test
          </button>
          {session.rollback ? (
            <div>
              <p>
                Status: <code>{session.rollback.status}</code> (
                {rollbackLabel(session.rollback.status)})
              </p>
              {session.rollback.data_loss_limitations.map((item) => (
                <p key={item} className="banner banner-warn">
                  {item}
                </p>
              ))}
              {session.rollback.error ? <p role="alert">{session.rollback.error}</p> : null}
            </div>
          ) : null}
        </article>
      ) : null}

      {session.artifact ? (
        <article className="panel">
          <h3>Safety report</h3>
          <button
            type="button"
            disabled={busy !== null}
            onClick={() =>
              void runStep("report", async () => {
                const report = await createSafetyReport(
                  session.artifact!.migration_id,
                  session.request.trim(),
                  true,
                  useLlm,
                );
                setSession((current) => ({ ...current, report }));
              })
            }
          >
            6. Request safety report
          </button>
          {session.report ? (
            <div>
              <p>
                Eligible for review: {String(session.report.eligible_for_review)} · approved:{" "}
                {String(session.report.approved)} · applied: {String(session.report.applied)} ·
                fully_reversible: {String(session.report.fully_reversible)}
              </p>
              <p>Rollback: {rollbackLabel(session.report.rollback_status)}</p>
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
          <ConfirmPanel
            label="Persist this evidence in the application database"
            confirmed={persistConfirm}
            onChange={setPersistConfirm}
            help="POST /api/v1/sources/bookstore-demo/artifacts/{migration_id}/workflows. Requires the app database."
          />
          <button
            type="button"
            disabled={!persistConfirm || busy !== null}
            onClick={() =>
              void runStep("persist", async () => {
                const workflow = await persistWorkflow(
                  session.artifact!.migration_id,
                  session.request.trim(),
                  true,
                  useLlm,
                );
                setSession((current) => ({ ...current, workflow }));
              })
            }
          >
            7. Persist workflow
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
