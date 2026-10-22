import { describe, expect, it } from "vitest";
import { approvalUiAllowed, rollbackLabel, toApiError } from "./client";
import type { WorkflowDetail } from "./types";

function detail(overrides: Partial<WorkflowDetail> = {}): WorkflowDetail {
  return {
    id: "wf-1",
    source_id: "bookstore-demo",
    migration_id: "sp0123456789ab",
    artifact_checksum: "sha256:artifact",
    artifact_status: "generated",
    artifact_applied: false,
    schema_fingerprint: "fingerprint-1",
    state: "report_ready",
    report_checksum: "sha256:report",
    evidence_fingerprint: "sha256:evidence",
    report_stale: false,
    eligible_for_review: true,
    fully_reversible: false,
    rollback_status: "partial_restoration",
    report: {
      request: "Add a nullable text column called nickname to users",
      interpreted_intent: "Add nickname",
      operations: [],
      assumptions: [],
      source_id: "bookstore-demo",
      schema_fingerprint: "fingerprint-1",
      migration_id: "sp0123456789ab",
      artifact_checksum: "sha256:artifact",
      artifact_status: "generated",
      risk_findings: [],
      sandbox: null,
      rollback_status: "partial_restoration",
      data_loss_limitations: [
        "Recreating a dropped column does not restore its former values.",
      ],
      missing_evidence: [],
      blocking_reasons: [],
      eligible_for_review: true,
      approved: false,
      applied: false,
      fully_reversible: false,
    },
    approvals: [],
    audit_events: [],
    created_at: "2026-10-15T00:00:00+00:00",
    updated_at: "2026-10-15T00:00:00+00:00",
    ...overrides,
  };
}

describe("rollbackLabel", () => {
  it("labels every backend rollback status", () => {
    expect(rollbackLabel("exact_restoration")).toBe("Exact restoration");
    expect(rollbackLabel("partial_restoration")).toBe("Partial restoration");
    expect(rollbackLabel("failed")).toBe("Failed");
    expect(rollbackLabel("not_verified")).toBe("Not verified");
  });
});

describe("approvalUiAllowed", () => {
  it("blocks approval while authentication is unavailable", () => {
    const result = approvalUiAllowed(detail());
    expect(result.allowed).toBe(false);
    expect(result.reason).toContain("authentication_available=false");
    expect(result.allowed).not.toBe(true);
  });

  it("never treats eligibility alone as approval permission", () => {
    const result = approvalUiAllowed(
      detail({ eligible_for_review: true, report_stale: false }),
    );
    expect(result.allowed).toBe(false);
    expect(result.reason.toLowerCase()).toContain("authentication");
  });

  it("surfaces stale evidence before any approval action", () => {
    const result = approvalUiAllowed(detail({ report_stale: true, eligible_for_review: false }));
    expect(result.allowed).toBe(false);
    expect(result.reason).toContain("stale");
  });

  it("surfaces blockers and missing evidence", () => {
    const blocked = approvalUiAllowed(
      detail({
        eligible_for_review: true,
        report: {
          ...detail().report,
          blocking_reasons: ["A risk finding is policy_blocked."],
        },
      }),
    );
    expect(blocked.allowed).toBe(false);
    expect(blocked.reason).toContain("policy_blocked");

    const missing = approvalUiAllowed(
      detail({
        report: {
          ...detail().report,
          missing_evidence: ["sandbox upgrade"],
        },
      }),
    );
    expect(missing.allowed).toBe(false);
    expect(missing.reason).toContain("sandbox upgrade");
  });
});

describe("toApiError", () => {
  it("reads the backend detail.error contract", async () => {
    const response = new Response(
      JSON.stringify({
        detail: { error: "stale_safety_report", message: "The safety report is stale." },
      }),
      { status: 409 },
    );
    const error = await toApiError(response);
    expect(error.status).toBe(409);
    expect(error.code).toBe("stale_safety_report");
    expect(error.detailMessage).toContain("stale");
  });

  it("handles non-json failures without inventing success", async () => {
    const response = new Response("nope", { status: 503 });
    const error = await toApiError(response);
    expect(error.code).toBe("http_503");
  });
});
