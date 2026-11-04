import type {
  ApprovalSummary,
  AuthSession,
  HealthResponse,
  MigrationArtifact,
  MigrationProposal,
  RiskAssessment,
  RollbackReport,
  SafetyReport,
  SandboxCheckpointSessionStatus,
  SandboxRun,
  SchemaSnapshot,
  SourceListResponse,
  WorkflowDetail,
  WorkflowSummary,
} from "./types";
import { ApiError, type ApiErrorBody } from "./types";

const SOURCE = "bookstore-demo";
const MIGRATION_SOURCE = "sandbox";
let csrfToken: string | null = null;

export function setCsrfToken(value: string | null): void {
  csrfToken = value;
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const method = (init?.method ?? "GET").toUpperCase();
  const response = await fetch(path, {
    ...init,
    headers: {
      Accept: "application/json",
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...(csrfToken && !["GET", "HEAD", "OPTIONS"].includes(method)
        ? { "X-CSRF-Token": csrfToken }
        : {}),
      ...init?.headers,
    },
  });
  if (!response.ok) {
    throw await toApiError(response);
  }
  return (await response.json()) as T;
}

export async function toApiError(response: Response): Promise<ApiError> {
  let code = `http_${response.status}`;
  let message: string | undefined;
  try {
    const body = (await response.json()) as ApiErrorBody;
    if (body?.detail?.error) {
      code = body.detail.error;
      message = body.detail.message;
    }
  } catch {
    // Keep the status-based code when the body is not JSON.
  }
  return new ApiError(response.status, code, message);
}

export function getHealth(signal?: AbortSignal): Promise<HealthResponse> {
  return requestJson<HealthResponse>("/api/v1/health", { signal });
}

export function getAuthSession(signal?: AbortSignal): Promise<AuthSession> {
  return requestJson<AuthSession>("/api/v1/auth/me", { signal });
}

export function beginLogin(): void {
  window.location.assign("/api/v1/auth/login");
}

export async function endSession(): Promise<AuthSession> {
  const session = await requestJson<AuthSession>("/api/v1/auth/logout", { method: "POST" });
  setCsrfToken(null);
  return session;
}

export function listSources(signal?: AbortSignal): Promise<SourceListResponse> {
  return requestJson<SourceListResponse>("/api/v1/sources", { signal });
}

export function getSchema(signal?: AbortSignal): Promise<SchemaSnapshot> {
  return requestJson<SchemaSnapshot>(`/api/v1/sources/${SOURCE}/schema`, { signal });
}

export function createPlan(
  request: string,
  useLlm = false,
): Promise<MigrationProposal> {
  return requestJson<MigrationProposal>(`/api/v1/sources/${MIGRATION_SOURCE}/plans`, {
    method: "POST",
    body: JSON.stringify({ request, use_llm: useLlm }),
  });
}

export function assessRisk(request: string, useLlm = false): Promise<RiskAssessment> {
  return requestJson<RiskAssessment>(`/api/v1/sources/${MIGRATION_SOURCE}/risk`, {
    method: "POST",
    body: JSON.stringify({ request, use_llm: useLlm }),
  });
}

export function createArtifact(
  request: string,
  useLlm = false,
): Promise<MigrationArtifact> {
  return requestJson<MigrationArtifact>(`/api/v1/sources/${MIGRATION_SOURCE}/artifacts`, {
    method: "POST",
    body: JSON.stringify({ request, use_llm: useLlm }),
  });
}

export function runSandbox(migrationId: string, confirm: boolean): Promise<SandboxRun> {
  return requestJson<SandboxRun>(
    `/api/v1/sources/${MIGRATION_SOURCE}/artifacts/${migrationId}/sandbox`,
    {
      method: "POST",
      body: JSON.stringify({ confirm }),
    },
  );
}

export function getSandboxCheckpointSession(): Promise<SandboxCheckpointSessionStatus> {
  return requestJson<SandboxCheckpointSessionStatus>(
    `/api/v1/sources/${MIGRATION_SOURCE}/sandbox-session`,
  );
}

export function runRollback(
  migrationId: string,
  confirm: boolean,
  snapshotSessionId: string,
): Promise<RollbackReport> {
  return requestJson<RollbackReport>(
    `/api/v1/sources/${MIGRATION_SOURCE}/artifacts/${migrationId}/rollback`,
    {
      method: "POST",
      body: JSON.stringify({ confirm, snapshot_session_id: snapshotSessionId }),
    },
  );
}

export function runDowngrade(
  migrationId: string,
  confirm: boolean,
  snapshotSessionId: string,
): Promise<RollbackReport> {
  return requestJson<RollbackReport>(
    `/api/v1/sources/${MIGRATION_SOURCE}/artifacts/${migrationId}/downgrade`,
    {
      method: "POST",
      body: JSON.stringify({ confirm, snapshot_session_id: snapshotSessionId }),
    },
  );
}

export function createSafetyReport(
  migrationId: string,
  request: string,
  confirm: boolean,
  useLlm = false,
  snapshotSessionId?: string,
): Promise<SafetyReport> {
  return requestJson<SafetyReport>(
    `/api/v1/sources/${MIGRATION_SOURCE}/artifacts/${migrationId}/report`,
    {
      method: "POST",
      body: JSON.stringify({ request, confirm, use_llm: useLlm, snapshot_session_id: snapshotSessionId }),
    },
  );
}

export function persistWorkflow(
  migrationId: string,
  request: string,
  confirm: boolean,
  useLlm = false,
  visibility: "shared" | "private" = "shared",
  snapshotSessionId?: string,
): Promise<WorkflowDetail> {
  return requestJson<WorkflowDetail>(
    `/api/v1/sources/${MIGRATION_SOURCE}/artifacts/${migrationId}/workflows`,
    {
      method: "POST",
      body: JSON.stringify({ request, confirm, use_llm: useLlm, visibility, snapshot_session_id: snapshotSessionId }),
    },
  );
}

export function listWorkflows(signal?: AbortSignal): Promise<{ workflows: WorkflowSummary[] }> {
  return requestJson<{ workflows: WorkflowSummary[] }>("/api/v1/workflows", { signal });
}

export function getWorkflow(workflowId: string, signal?: AbortSignal): Promise<WorkflowDetail> {
  return requestJson<WorkflowDetail>(`/api/v1/workflows/${workflowId}`, { signal });
}

export function createApproval(
  workflowId: string,
  targetIdentity: string,
  confirm: boolean,
): Promise<ApprovalSummary> {
  return requestJson<ApprovalSummary>(`/api/v1/workflows/${workflowId}/approvals`, {
    method: "POST",
    body: JSON.stringify({ target_identity: targetIdentity, confirm }),
  });
}

export function getAudit(
  workflowId: string,
  signal?: AbortSignal,
): Promise<{ workflow_id: string; events: WorkflowDetail["audit_events"] }> {
  return requestJson(`/api/v1/workflows/${workflowId}/audit`, { signal });
}

export function formatApiError(error: unknown): string {
  if (error instanceof ApiError) {
    return error.detailMessage ? `${error.code}: ${error.detailMessage}` : error.code;
  }
  if (error instanceof Error) {
    return error.message;
  }
  return "Request failed.";
}

/** Approval stays blocked in the UI while authentication is unavailable. */
export function approvalUiAllowed(detail: WorkflowDetail): {
  allowed: boolean;
  reason: string;
} {
  if (detail.report_stale) {
    return { allowed: false, reason: "The safety report is stale." };
  }
  if (!detail.eligible_for_review) {
    return { allowed: false, reason: "The workflow is not eligible for review." };
  }
  if (detail.report.blocking_reasons.length > 0) {
    return { allowed: false, reason: detail.report.blocking_reasons[0] };
  }
  if (detail.report.missing_evidence.length > 0) {
    return { allowed: false, reason: `Missing evidence: ${detail.report.missing_evidence[0]}` };
  }
  return {
    allowed: false,
    reason:
      "Authentication is unavailable (authentication_available=false). " +
      "SchemaPilot will not treat a UI click as a verified human approval.",
  };
}

export function rollbackLabel(status: string): string {
  switch (status) {
    case "exact_restoration":
      return "Exact restoration";
    case "partial_restoration":
      return "Partial restoration";
    case "failed":
      return "Failed";
    case "not_verified":
      return "Not verified";
    default:
      return status;
  }
}
