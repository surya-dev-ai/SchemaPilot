import { afterEach, describe, expect, it, vi } from "vitest";
import {
  createApproval,
  createArtifact,
  createPlan,
  createSafetyReport,
  getAudit,
  getSchema,
  getWorkflow,
  listSources,
  listWorkflows,
  persistWorkflow,
  runRollback,
  runSandbox,
} from "./client";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function stubJson(payload: unknown, status = 200): void {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () =>
      new Response(JSON.stringify(payload), {
        status,
        headers: { "Content-Type": "application/json" },
      }),
    ),
  );
}

describe("Phase 7–9 API path contracts", () => {
  it("lists sources and loads bookstore schema", async () => {
    stubJson({ sources: [] });
    await listSources();
    expect(fetch).toHaveBeenCalledWith(
      "/api/v1/sources",
      expect.objectContaining({ headers: expect.any(Object) }),
    );

    stubJson({
      source_id: "bookstore-demo",
      schema_name: "public",
      fingerprint: "fp",
      tables: [],
      dependencies: [],
      database_available: true,
    });
    await getSchema();
    expect(fetch).toHaveBeenCalledWith(
      "/api/v1/sources/bookstore-demo/schema",
      expect.objectContaining({ headers: expect.any(Object) }),
    );
  });

  it("posts plan, artifact, sandbox, rollback, and report with confirm bodies", async () => {
    stubJson({
      request: "x",
      interpreted_intent: "x",
      operations: [],
      assumptions: [],
      clarification_needed: false,
      clarification_questions: [],
      source_id: "bookstore-demo",
      schema_fingerprint: "fp",
    });
    await createPlan("Add nickname", true);
    expect(fetch).toHaveBeenLastCalledWith(
      "/api/v1/sources/bookstore-demo/plans",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ request: "Add nickname", use_llm: true }),
      }),
    );

    stubJson({
      migration_id: "sp0123456789ab",
      checksum: "sha256:a",
      status: "generated",
      applied: false,
      module_identity: "sp0123456789ab_add_nickname",
      sql_preview: "-- preview",
      source_id: "bookstore-demo",
      schema_fingerprint: "fp",
    });
    await createArtifact("Add nickname", false);
    expect(fetch).toHaveBeenLastCalledWith(
      "/api/v1/sources/bookstore-demo/artifacts",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ request: "Add nickname", use_llm: false }),
      }),
    );

    stubJson({ result: "passed", upgrade_applied: true, migration_id: "sp0123456789ab" });
    await runSandbox("sp0123456789ab", true);
    expect(fetch).toHaveBeenLastCalledWith(
      "/api/v1/sources/bookstore-demo/artifacts/sp0123456789ab/sandbox",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ confirm: true }),
      }),
    );

    stubJson({
      migration_id: "sp0123456789ab",
      status: "partial_restoration",
      fully_reversible: false,
    });
    await runRollback("sp0123456789ab", true);
    expect(fetch).toHaveBeenLastCalledWith(
      "/api/v1/sources/bookstore-demo/artifacts/sp0123456789ab/rollback",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ confirm: true }),
      }),
    );

    stubJson({
      request: "Add nickname",
      interpreted_intent: "x",
      operations: [],
      assumptions: [],
      source_id: "bookstore-demo",
      schema_fingerprint: "fp",
      migration_id: "sp0123456789ab",
      artifact_checksum: "sha256:a",
      artifact_status: "generated",
      risk_findings: [],
      sandbox: null,
      rollback_status: "not_verified",
      data_loss_limitations: [],
      missing_evidence: [],
      blocking_reasons: [],
      eligible_for_review: false,
      approved: false,
      applied: false,
      fully_reversible: false,
    });
    await createSafetyReport("sp0123456789ab", "Add nickname", true, true);
    expect(fetch).toHaveBeenLastCalledWith(
      "/api/v1/sources/bookstore-demo/artifacts/sp0123456789ab/report",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ request: "Add nickname", confirm: true, use_llm: true }),
      }),
    );
  });

  it("persists workflows and loads history, detail, approvals, and audit", async () => {
    stubJson({
      id: "wf-1",
      source_id: "bookstore-demo",
      migration_id: "sp0123456789ab",
      artifact_checksum: "sha256:a",
      artifact_status: "generated",
      artifact_applied: false,
      schema_fingerprint: "fp",
      state: "blocked",
      report_checksum: "sha256:r",
      evidence_fingerprint: "sha256:e",
      report_stale: false,
      eligible_for_review: false,
      fully_reversible: false,
      rollback_status: "not_verified",
      report: {
        request: "x",
        interpreted_intent: "x",
        operations: [],
        assumptions: [],
        source_id: "bookstore-demo",
        schema_fingerprint: "fp",
        migration_id: "sp0123456789ab",
        artifact_checksum: "sha256:a",
        artifact_status: "generated",
        risk_findings: [],
        sandbox: null,
        rollback_status: "not_verified",
        data_loss_limitations: [],
        missing_evidence: ["sandbox"],
        blocking_reasons: [],
        eligible_for_review: false,
        approved: false,
        applied: false,
        fully_reversible: false,
      },
      approvals: [],
      audit_events: [],
      created_at: "2026-10-15T00:00:00+00:00",
      updated_at: "2026-10-15T00:00:00+00:00",
    });
    await persistWorkflow("sp0123456789ab", "Add nickname", true, false);
    expect(fetch).toHaveBeenLastCalledWith(
      "/api/v1/sources/bookstore-demo/artifacts/sp0123456789ab/workflows",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ request: "Add nickname", confirm: true, use_llm: false }),
      }),
    );

    stubJson({ workflows: [] });
    await listWorkflows();
    expect(fetch).toHaveBeenLastCalledWith(
      "/api/v1/workflows",
      expect.objectContaining({ headers: expect.any(Object) }),
    );

    stubJson({
      id: "wf-1",
      source_id: "bookstore-demo",
      migration_id: "sp0123456789ab",
      artifact_checksum: "sha256:a",
      artifact_status: "generated",
      artifact_applied: false,
      schema_fingerprint: "fp",
      state: "blocked",
      report_checksum: "sha256:r",
      evidence_fingerprint: "sha256:e",
      report_stale: false,
      eligible_for_review: false,
      fully_reversible: false,
      rollback_status: "not_verified",
      report: {
        request: "x",
        interpreted_intent: "x",
        operations: [],
        assumptions: [],
        source_id: "bookstore-demo",
        schema_fingerprint: "fp",
        migration_id: "sp0123456789ab",
        artifact_checksum: "sha256:a",
        artifact_status: "generated",
        risk_findings: [],
        sandbox: null,
        rollback_status: "not_verified",
        data_loss_limitations: [],
        missing_evidence: [],
        blocking_reasons: [],
        eligible_for_review: false,
        approved: false,
        applied: false,
        fully_reversible: false,
      },
      approvals: [],
      audit_events: [],
      created_at: "2026-10-15T00:00:00+00:00",
      updated_at: "2026-10-15T00:00:00+00:00",
    });
    await getWorkflow("wf-1");
    expect(fetch).toHaveBeenLastCalledWith(
      "/api/v1/workflows/wf-1",
      expect.objectContaining({ headers: expect.any(Object) }),
    );

    stubJson({
      id: "ap-1",
      migration_id: "sp0123456789ab",
      decision: "recorded",
      target_identity: "staging-target",
      artifact_checksum: "sha256:a",
      report_checksum: "sha256:r",
      authentication_available: false,
      approver_identity: null,
      limitation: "Authentication is not implemented.",
      created_at: "2026-10-15T00:00:00+00:00",
    });
    await createApproval("wf-1", "staging-target", true);
    expect(fetch).toHaveBeenLastCalledWith(
      "/api/v1/workflows/wf-1/approvals",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ target_identity: "staging-target", confirm: true }),
      }),
    );

    stubJson({ workflow_id: "wf-1", events: [] });
    await getAudit("wf-1");
    expect(fetch).toHaveBeenLastCalledWith(
      "/api/v1/workflows/wf-1/audit",
      expect.objectContaining({ headers: expect.any(Object) }),
    );
  });
});
