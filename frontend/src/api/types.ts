/** Types mirrored from the Phase 1–9 FastAPI response models. */

export type HealthResponse = {
  status: "ok";
  service: string;
  version: string;
  api_version: "v1";
  target_execution_enabled: boolean;
  migrations_on_startup: false;
  database_connectivity: "not_checked";
  app_database_configured: boolean;
  sandbox_database_configured: boolean;
  target_database_configured: boolean;
  llm_enabled: boolean;
  llm_configured: boolean;
  llm_provider: string;
  llm_model: string | null;
  authentication_available: boolean;
  phase: string;
};

export type SourceSummary = {
  id: string;
  kind: "demo";
  display_name: string;
  database_name: string;
  schema_name: string;
  configured: boolean;
  access: "read_only";
};

export type SourceListResponse = {
  sources: SourceSummary[];
};

export type ColumnSnapshot = {
  id: string;
  name: string;
  ordinal_position: number;
  data_type: string;
  udt_name: string;
  nullable: boolean;
  default: string | null;
  identity: string;
  generated: string;
  comment: string | null;
};

export type ConstraintSnapshot = {
  id: string;
  name: string;
  kind: string;
  columns: string[];
  referenced_schema: string | null;
  referenced_table: string | null;
  referenced_columns: string[];
  on_update: string | null;
  on_delete: string | null;
  check_expression: string | null;
};

export type IndexSnapshot = {
  id: string;
  name: string;
  unique: boolean;
  primary: boolean;
  columns: string[];
  directions: string[];
};

export type DependencySnapshot = {
  id: string;
  from_table: string;
  to_table: string;
  constraint_name: string;
  from_columns: string[];
  to_columns: string[];
};

export type TableSnapshot = {
  id: string;
  schema_name: string;
  name: string;
  comment: string | null;
  columns: ColumnSnapshot[];
  constraints: ConstraintSnapshot[];
  indexes: IndexSnapshot[];
};

export type SchemaSnapshot = {
  source_id: string;
  database_name: string;
  schema_name: string;
  tables: TableSnapshot[];
  dependencies: DependencySnapshot[];
  fingerprint: string;
};

export type PlanOperation = {
  id: string;
  kind: string;
  summary: string;
  table: string | null;
  column: string | null;
  data_type: string | null;
  nullable: boolean | null;
  default: string | null;
  new_name: string | null;
  index_columns: string[];
  constraint_kind: string | null;
  check_expression: string | null;
  destructive: boolean;
};

export type LlmSuggestionSummary = {
  summary: string;
  assumptions: string[];
  clarification_questions: { topic: string; text: string }[];
  operations: Array<{
    kind: string;
    table: string | null;
    column: string | null;
    data_type: string | null;
    nullable: boolean | null;
    default: string | null;
    new_name: string | null;
    index_columns: string[];
    constraint_kind: string | null;
    check_expression: string | null;
    destructive: boolean;
  }>;
  schema_fingerprint: string;
};

export type MigrationProposal = {
  source_id: string;
  schema_name: string;
  schema_fingerprint: string;
  request: string;
  status: "proposed" | "needs_clarification" | "rejected";
  summary: string;
  assumptions: { id: string; text: string }[];
  clarification_questions: { id: string; topic: string; text: string }[];
  operations: PlanOperation[];
  validation_errors: { id: string; code: string; message: string; object_name: string | null }[];
  destructive: boolean;
  requires_risk_assessment: boolean;
  interpretation_path: "deterministic" | "llm_assisted" | "deterministic_fallback";
  provider_status:
    | "not_used"
    | "not_configured"
    | "disabled"
    | "ok"
    | "error"
    | "timeout"
    | "rate_limited"
    | "malformed";
  provider_name: string | null;
  provider_error: string | null;
  llm_suggestion: LlmSuggestionSummary | null;
};

export type RiskFinding = {
  id: string;
  rule_id: string;
  severity: "low" | "medium" | "high";
  disposition: "info" | "warning" | "high_risk" | "policy_blocked";
  operation_id: string | null;
  affected_objects: string[];
  evidence: string[];
  explanation: string;
  mitigation: string;
  reversibility: string;
  data_check: "not_required" | "not_run";
};

export type RiskAssessment = {
  source_id: string;
  schema_name: string;
  schema_fingerprint: string;
  plan_status: string;
  findings: RiskFinding[];
  policy_blocked: boolean;
  artifact_eligible: boolean;
  eligibility_reason: string;
};

export type MigrationArtifact = {
  migration_id: string;
  source_id: string;
  schema_name: string;
  schema_fingerprint: string;
  summary: string;
  status: "generated";
  applied: false;
  operation_ids: string[];
  sql_preview: string;
  downgrade_sql: string;
  alembic_source: string;
  reversibility: string;
  operation_reversibility: {
    operation_id: string;
    kind: string;
    reversibility: string;
    upgrade_effect: string;
    downgrade_effect: string;
    data_loss_on_downgrade: boolean;
  }[];
  checksum: string;
  location: string;
};

export type SandboxCheck = {
  name: string;
  status: "passed" | "failed" | "not_run";
  detail: string;
};

export type SandboxRun = {
  migration_id: string;
  source_id: string;
  schema_fingerprint: string;
  artifact_checksum: string;
  sandbox_database: string;
  sandbox_user: string;
  postgres_version: string;
  started_at: string;
  finished_at: string;
  result: "passed" | "failed" | "rejected";
  upgrade_applied: boolean;
  restored: boolean;
  cleaned_up: boolean;
  checks: SandboxCheck[];
  observed_tables: string[];
  error: string | null;
};

export type RollbackStatus =
  | "exact_restoration"
  | "partial_restoration"
  | "failed"
  | "not_verified";

export type RollbackReport = {
  migration_id: string;
  artifact_checksum: string;
  source_id: string;
  schema_fingerprint: string;
  sandbox_database: string;
  sandbox_user: string;
  postgres_version: string;
  started_at: string;
  finished_at: string;
  status: RollbackStatus;
  upgrade: SandboxRun | null;
  baseline: {
    schema_fingerprint: string;
    tables: string[];
    row_counts: Record<string, number>;
    emails: string[];
  } | null;
  observed_fingerprint: string | null;
  downgrade_executed: boolean;
  schema_matches_baseline: boolean | null;
  data_checks: SandboxCheck[];
  data_loss_limitations: string[];
  error: string | null;
};

export type SafetyReport = {
  request: string;
  interpreted_intent: string;
  operations: PlanOperation[];
  assumptions: { id: string; text: string }[];
  source_id: string;
  schema_fingerprint: string;
  migration_id: string;
  artifact_checksum: string;
  artifact_status: string;
  risk_findings: RiskFinding[];
  sandbox: SandboxRun | null;
  rollback_status: RollbackStatus;
  data_loss_limitations: string[];
  missing_evidence: string[];
  blocking_reasons: string[];
  eligible_for_review: boolean;
  approved: false;
  applied: false;
  fully_reversible: boolean;
};

export type WorkflowSummary = {
  id: string;
  source_id: string;
  migration_id: string;
  artifact_checksum: string;
  schema_fingerprint: string;
  state: "report_ready" | "approval_recorded" | "blocked";
  eligible_for_review: boolean;
  report_stale: boolean;
  rollback_status: RollbackStatus;
  created_at: string;
  updated_at: string;
};

export type ApprovalSummary = {
  id: string;
  migration_id: string;
  artifact_checksum: string;
  report_checksum: string;
  target_identity: string;
  decision: "recorded" | "rejected";
  authentication_available: boolean;
  approver_identity: string | null;
  limitation: string;
  created_at: string;
};

export type AuditEventSummary = {
  id: string;
  event_type: string;
  detail: Record<string, unknown>;
  created_at: string;
};

export type WorkflowDetail = {
  id: string;
  source_id: string;
  migration_id: string;
  artifact_checksum: string;
  artifact_status: string;
  artifact_applied: false;
  schema_fingerprint: string;
  state: "report_ready" | "approval_recorded" | "blocked";
  report_checksum: string;
  evidence_fingerprint: string;
  report_stale: boolean;
  eligible_for_review: boolean;
  fully_reversible: boolean;
  rollback_status: RollbackStatus;
  report: SafetyReport;
  approvals: ApprovalSummary[];
  audit_events: AuditEventSummary[];
  created_at: string;
  updated_at: string;
};

export type ApiErrorBody = {
  detail: {
    error: string;
    message?: string;
  };
};

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly detailMessage: string | undefined;

  constructor(status: number, code: string, detailMessage?: string) {
    super(detailMessage ? `${code}: ${detailMessage}` : code);
    this.status = status;
    this.code = code;
    this.detailMessage = detailMessage;
  }
}
