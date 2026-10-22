"""Score a structured proposal against a schema snapshot.

Final risk comes from operations and snapshot metadata. The request text and
schema comments are not inputs to these rules. No SQL is executed.
"""

from app.schemas.domain import ColumnSnapshot, SchemaSnapshot
from app.schemas.planning import MigrationProposal, PlanOperation
from app.schemas.risk import (
    DataCheck,
    EligibilityReason,
    Reversibility,
    RiskAssessment,
    RiskDisposition,
    RiskFinding,
    RiskSeverity,
)
from app.services.dependency_analyzer import related_object_ids
from app.services.sql_safety import (
    ALLOWED_COLUMN_TYPES,
    contains_untrusted_sql,
    target_problems,
)

_NOT_RUN = "not_run: this check was not executed against live rows"


def assess_risk(snapshot: SchemaSnapshot, proposal: MigrationProposal) -> RiskAssessment:
    """Return static findings for a proposal. Data-dependent checks stay not_run."""
    pending: list[RiskFinding] = []
    if proposal.schema_fingerprint != snapshot.fingerprint:
        pending.append(
            _finding(
                rule_id="SP-R018",
                severity="high",
                disposition="policy_blocked",
                operation_id=None,
                affected_objects=[snapshot.schema_name],
                evidence=["static: proposal fingerprint differs from the inspected snapshot"],
                explanation=(
                    "The proposal was built for a different snapshot, so its objects "
                    "cannot be assessed against this schema."
                ),
                mitigation="Inspect the source again and plan against that snapshot.",
                reversibility="unknown",
                data_check="not_required",
            )
        )
    if proposal.status != "proposed":
        pending.append(_plan_status_finding(proposal))
    for operation in proposal.operations:
        pending.extend(_operation_findings(snapshot, operation))
    findings = [
        finding.model_copy(update={"id": f"finding-{index}"})
        for index, finding in enumerate(pending, start=1)
    ]
    eligible, reason = _eligibility(proposal, findings)
    return RiskAssessment(
        source_id=snapshot.source_id,
        schema_name=snapshot.schema_name,
        schema_fingerprint=snapshot.fingerprint,
        plan_status=proposal.status,
        findings=findings,
        policy_blocked=any(finding.disposition == "policy_blocked" for finding in findings),
        artifact_eligible=eligible,
        eligibility_reason=reason,
    )


def _plan_status_finding(proposal: MigrationProposal) -> RiskFinding:
    codes = [error.code for error in proposal.validation_errors]
    evidence = [f"static: plan status is {proposal.status}"]
    if codes:
        evidence.append("static: validation codes " + ", ".join(codes))
    return _finding(
        rule_id="SP-R015",
        severity="high",
        disposition="policy_blocked",
        operation_id=None,
        affected_objects=[],
        evidence=evidence,
        explanation="Only a proposed plan can be considered for a later artifact.",
        mitigation="Resolve the clarification or validation error, then plan again.",
        reversibility="unknown",
        data_check="not_required",
    )


def _operation_findings(
    snapshot: SchemaSnapshot,
    operation: PlanOperation,
) -> list[RiskFinding]:
    problems = target_problems(snapshot, operation)
    if problems:
        return [
            _finding(
                rule_id="SP-R013",
                severity="high",
                disposition="policy_blocked",
                operation_id=operation.id,
                affected_objects=_object_ids(snapshot, operation),
                evidence=[f"static: {problem}" for problem in problems],
                explanation="The operation names an object the snapshot does not support.",
                mitigation="Plan against an object that exists in the inspected snapshot.",
                reversibility="unknown",
                data_check="not_required",
            )
        ]
    if operation.kind == "add_column":
        return _add_column_findings(snapshot, operation)
    if operation.kind == "add_index":
        return [_index_finding(snapshot, operation)]
    if operation.kind == "rename_table":
        return _rename_findings(snapshot, operation, column=None, rule_id="SP-R003")
    if operation.kind == "rename_column":
        return _rename_findings(snapshot, operation, column=operation.column, rule_id="SP-R004")
    if operation.kind == "add_constraint":
        return _constraint_findings(snapshot, operation)
    return _destructive_findings(snapshot, operation)


def _add_column_findings(
    snapshot: SchemaSnapshot,
    operation: PlanOperation,
) -> list[RiskFinding]:
    if contains_untrusted_sql(operation.default):
        return [_untrusted_sql_finding(snapshot, operation, "column default")]
    if operation.data_type not in ALLOWED_COLUMN_TYPES:
        return [
            _finding(
                rule_id="SP-R014",
                severity="high",
                disposition="policy_blocked",
                operation_id=operation.id,
                affected_objects=_object_ids(snapshot, operation),
                evidence=[f"static: data type {operation.data_type or '(none)'} is not supported"],
                explanation="The column type is outside the types this phase can classify.",
                mitigation="Use text, integer, bigint, boolean, or timestamptz.",
                reversibility="unknown",
                data_check="not_required",
            )
        ]
    if operation.nullable is False and operation.default is None:
        return [
            _finding(
                rule_id="SP-R007",
                severity="high",
                disposition="policy_blocked",
                operation_id=operation.id,
                affected_objects=_object_ids(snapshot, operation),
                evidence=[
                    "static: nullable is false and no default is present",
                    _NOT_RUN,
                ],
                explanation=(
                    "A not-null column without a default can fail when existing rows "
                    "have no value. Those rows were not read."
                ),
                mitigation="Add the column as nullable, or supply a default and reassess.",
                reversibility="unknown",
                data_check="not_run",
            )
        ]
    if operation.default is not None:
        findings = [
            _finding(
                rule_id="SP-R006",
                severity="medium",
                disposition="warning",
                operation_id=operation.id,
                affected_objects=_object_ids(snapshot, operation),
                evidence=[
                    "static: the operation includes an explicit default",
                    _NOT_RUN,
                ],
                explanation=(
                    "Existing rows would receive the default. Whether that value fits "
                    "every row was not checked."
                ),
                mitigation="Review the default, then check existing rows before an artifact.",
                reversibility="reversible",
                data_check="not_run",
            )
        ]
        return findings
    findings = [
        _finding(
            rule_id="SP-R005",
            severity="low",
            disposition="info",
            operation_id=operation.id,
            affected_objects=_object_ids(snapshot, operation),
            evidence=["static: new nullable column with no default"],
            explanation=(
                "Adding a nullable column does not rewrite existing values. "
                "Dropping it later would discard only values stored in the new column."
            ),
            mitigation="Keep the column nullable until a separate constraint is assessed.",
            reversibility="reversible",
            data_check="not_required",
        )
    ]
    if _is_soft_delete(operation):
        findings.append(
            _finding(
                rule_id="SP-R016",
                severity="low",
                disposition="info",
                operation_id=operation.id,
                affected_objects=_object_ids(snapshot, operation),
                evidence=["static: nullable timestamptz column deleted_at"],
                explanation=(
                    "This proposal records a deletion timestamp. It does not delete rows."
                ),
                mitigation="Keep the column nullable. Do not treat it as a drop or truncate.",
                reversibility="reversible",
                data_check="not_required",
            )
        )
    return findings


def _index_finding(snapshot: SchemaSnapshot, operation: PlanOperation) -> RiskFinding:
    columns = ", ".join(operation.index_columns)
    return _finding(
        rule_id="SP-R008",
        severity="low",
        disposition="info",
        operation_id=operation.id,
        affected_objects=_object_ids(snapshot, operation),
        evidence=[f"static: index columns {columns}", "static: index build was not executed"],
        explanation="The index is additive. Building it can lock the table; that was not measured.",
        mitigation="Create the index in a later sandbox run and confirm the lock window.",
        reversibility="reversible",
        data_check="not_required",
    )


def _rename_findings(
    snapshot: SchemaSnapshot,
    operation: PlanOperation,
    *,
    column: str | None,
    rule_id: str,
) -> list[RiskFinding]:
    related = related_object_ids(snapshot, operation.table or "", column)
    if related:
        severity: RiskSeverity = "high"
        disposition: RiskDisposition = "high_risk"
        evidence = [f"static: dependent object {name}" for name in related]
    else:
        severity = "medium"
        disposition = "warning"
        evidence = ["static: no foreign key, index, or constraint in the snapshot uses this object"]
    evidence.append("static: application references were not scanned")
    label = "column" if column else "table"
    findings = [
        _finding(
            rule_id=rule_id,
            severity=severity,
            disposition=disposition,
            operation_id=operation.id,
            affected_objects=[*_object_ids(snapshot, operation), *related],
            evidence=evidence,
            explanation=(
                f"Renaming the {label} keeps stored values and breaks database objects "
                "and clients that still use the old name."
            ),
            mitigation="Update dependent keys and clients, and keep the old name for a reversal.",
            reversibility="reversible",
            data_check="not_required",
        )
    ]
    if related:
        findings.append(_dependency_finding(operation, related))
    return findings


def _constraint_findings(
    snapshot: SchemaSnapshot,
    operation: PlanOperation,
) -> list[RiskFinding]:
    if operation.constraint_kind == "check" and contains_untrusted_sql(operation.check_expression):
        return [_untrusted_sql_finding(snapshot, operation, "check expression")]
    if operation.constraint_kind == "check":
        return [
            _finding(
                rule_id="SP-R011",
                severity="high",
                disposition="high_risk",
                operation_id=operation.id,
                affected_objects=_object_ids(snapshot, operation),
                evidence=[
                    "static: check expression stored as text and not interpreted",
                    _NOT_RUN,
                ],
                explanation="Existing rows were not tested against the check expression.",
                mitigation="Review the expression, then validate it against live rows before use.",
                reversibility="reversible",
                data_check="not_run",
            )
        ]
    if operation.constraint_kind == "unique":
        return [
            _finding(
                rule_id="SP-R009",
                severity="high",
                disposition="high_risk",
                operation_id=operation.id,
                affected_objects=_object_ids(snapshot, operation),
                evidence=[
                    f"static: unique constraint requested on {operation.table}.{operation.column}",
                    _NOT_RUN,
                ],
                explanation="Duplicate values in existing rows would reject the constraint.",
                mitigation="Count duplicate values before generating an artifact.",
                reversibility="reversible",
                data_check="not_run",
            )
        ]
    column = _column(snapshot, operation.table, operation.column)
    if column is not None and column.nullable is False:
        return [
            _finding(
                rule_id="SP-R010",
                severity="low",
                disposition="warning",
                operation_id=operation.id,
                affected_objects=_object_ids(snapshot, operation),
                evidence=["static: snapshot metadata already reports the column as not null"],
                explanation=(
                    "The snapshot says this column rejects nulls. No row scan was performed."
                ),
                mitigation="Skip the redundant constraint, or confirm it in a later sandbox run.",
                reversibility="reversible",
                data_check="not_required",
            )
        ]
    return [
        _finding(
            rule_id="SP-R010",
            severity="high",
            disposition="high_risk",
            operation_id=operation.id,
            affected_objects=_object_ids(snapshot, operation),
            evidence=["static: snapshot metadata reports the column as nullable", _NOT_RUN],
            explanation="Existing nulls would reject a not-null constraint. Rows were not read.",
            mitigation="Count nulls in the column before generating an artifact.",
            reversibility="reversible",
            data_check="not_run",
        )
    ]


def _destructive_findings(
    snapshot: SchemaSnapshot,
    operation: PlanOperation,
) -> list[RiskFinding]:
    column = operation.column
    rule_id = "SP-R002" if column else "SP-R001"
    related = related_object_ids(snapshot, operation.table or "", column)
    target = f"{operation.table}.{column}" if column else operation.table
    findings = [
        _finding(
            rule_id=rule_id,
            severity="high",
            disposition="policy_blocked",
            operation_id=operation.id,
            affected_objects=[*_object_ids(snapshot, operation), *related],
            evidence=[
                f"static: destructive operation on {target}",
                "static: row counts were not read; stored rows would be discarded",
            ],
            explanation="The operation would discard data and is blocked by policy.",
            mitigation="Choose a nullable column or a soft-delete timestamp instead.",
            reversibility="irreversible",
            data_check="not_required",
        )
    ]
    if related:
        findings.append(_dependency_finding(operation, related))
    return findings


def _dependency_finding(
    operation: PlanOperation,
    related: tuple[str, ...],
) -> RiskFinding:
    return _finding(
        rule_id="SP-R017",
        severity="high",
        disposition="high_risk",
        operation_id=operation.id,
        affected_objects=list(related),
        evidence=[f"static: snapshot dependency {name}" for name in related],
        explanation="Foreign keys, indexes, or constraints in the snapshot use this object.",
        mitigation="Update or remove those dependencies before renaming or dropping the object.",
        reversibility="unknown",
        data_check="not_required",
    )


def _untrusted_sql_finding(
    snapshot: SchemaSnapshot,
    operation: PlanOperation,
    location: str,
) -> RiskFinding:
    return _finding(
        rule_id="SP-R012",
        severity="high",
        disposition="policy_blocked",
        operation_id=operation.id,
        affected_objects=_object_ids(snapshot, operation),
        evidence=[f"static: {location} contains SQL text and was not executed"],
        explanation="Constraint and default text is untrusted metadata, not a command.",
        mitigation="Replace the text with a value that does not contain SQL commands.",
        reversibility="unknown",
        data_check="not_required",
    )


def _is_soft_delete(operation: PlanOperation) -> bool:
    return (
        operation.column == "deleted_at"
        and operation.data_type == "timestamptz"
        and operation.nullable is True
        and operation.default is None
    )


def _object_ids(snapshot: SchemaSnapshot, operation: PlanOperation) -> list[str]:
    schema_name = snapshot.schema_name
    objects: list[str] = []
    if operation.table:
        objects.append(f"{schema_name}.{operation.table}")
    if operation.table and operation.column:
        objects.append(f"{schema_name}.{operation.table}.{operation.column}")
    if operation.kind == "add_index":
        for column in operation.index_columns:
            objects.append(f"{schema_name}.{operation.table}.{column}")
    if operation.new_name and operation.kind == "rename_table":
        objects.append(f"{schema_name}.{operation.new_name}")
    if operation.new_name and operation.kind == "rename_column" and operation.table:
        objects.append(f"{schema_name}.{operation.table}.{operation.new_name}")
    return list(dict.fromkeys(objects))


def _column(
    snapshot: SchemaSnapshot,
    table_name: str | None,
    column_name: str | None,
) -> ColumnSnapshot | None:
    if table_name is None or column_name is None:
        return None
    for table in snapshot.tables:
        if table.name != table_name:
            continue
        for column in table.columns:
            if column.name == column_name:
                return column
    return None


def _eligibility(
    proposal: MigrationProposal,
    findings: list[RiskFinding],
) -> tuple[bool, EligibilityReason]:
    if proposal.status != "proposed":
        return False, "plan_not_proposed"
    if any(finding.disposition == "policy_blocked" for finding in findings):
        return False, "policy_blocked"
    if any(finding.data_check == "not_run" for finding in findings):
        return False, "data_check_not_run"
    if not proposal.operations:
        return False, "no_operations"
    return True, "eligible"


def _finding(
    *,
    rule_id: str,
    severity: RiskSeverity,
    disposition: RiskDisposition,
    operation_id: str | None,
    affected_objects: list[str],
    evidence: list[str],
    explanation: str,
    mitigation: str,
    reversibility: Reversibility,
    data_check: DataCheck,
) -> RiskFinding:
    return RiskFinding(
        id="pending",
        rule_id=rule_id,
        severity=severity,
        disposition=disposition,
        operation_id=operation_id,
        affected_objects=affected_objects,
        evidence=evidence,
        explanation=explanation,
        mitigation=mitigation,
        reversibility=reversibility,
        data_check=data_check,
    )
