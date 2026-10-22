"""Risk tests. These tests build a snapshot in memory and do not open PostgreSQL."""

from pathlib import Path

import pytest
from app.core.config import Settings
from app.db import session as session_module
from app.demo.bookstore import USER_TABLE_COMMENT
from app.main import create_app
from app.schemas.domain import (
    ColumnSnapshot,
    ConstraintSnapshot,
    DependencySnapshot,
    IndexSnapshot,
    SchemaSnapshot,
    TableSnapshot,
)
from app.schemas.planning import MigrationProposal, PlanOperation, PlanValidationError
from app.schemas.risk import RiskFinding
from app.services.dependency_analyzer import related_object_ids
from app.services.planner import propose_migration
from app.services.risk_engine import assess_risk
from app.services.sql_safety import contains_untrusted_sql
from fastapi.testclient import TestClient

MALICIOUS = USER_TABLE_COMMENT


def _column(
    table: str,
    name: str,
    *,
    nullable: bool = False,
    position: int = 1,
) -> ColumnSnapshot:
    return ColumnSnapshot(
        id=f"bookstore.{table}.{name}",
        name=name,
        ordinal_position=position,
        data_type="text",
        udt_name="text",
        nullable=nullable,
        identity="none",
        generated="never",
        comment=MALICIOUS,
    )


def _table(
    name: str,
    columns: list[ColumnSnapshot],
    constraints: list[ConstraintSnapshot] | None = None,
    indexes: list[IndexSnapshot] | None = None,
) -> TableSnapshot:
    return TableSnapshot(
        id=f"bookstore.{name}",
        schema_name="bookstore",
        name=name,
        comment=MALICIOUS,
        columns=columns,
        constraints=constraints or [],
        indexes=indexes or [],
    )


def _snapshot() -> SchemaSnapshot:
    return SchemaSnapshot(
        source_id="bookstore-demo",
        database_name="schemapilot_bookstore",
        schema_name="bookstore",
        fingerprint="fingerprint-1",
        tables=[
            _table(
                "users",
                [
                    _column("users", "id", position=1),
                    _column("users", "email", position=2),
                    _column("users", "display_name", nullable=True, position=3),
                ],
                constraints=[
                    ConstraintSnapshot(
                        id="bookstore.users.users_pkey",
                        name="users_pkey",
                        kind="primary_key",
                        columns=["id"],
                    ),
                    ConstraintSnapshot(
                        id="bookstore.users.users_email_unique",
                        name="users_email_unique",
                        kind="unique",
                        columns=["email"],
                    ),
                ],
            ),
            _table(
                "orders",
                [
                    _column("orders", "id", position=1),
                    _column("orders", "user_id", position=2),
                    _column("orders", "status", position=3),
                ],
                constraints=[
                    ConstraintSnapshot(
                        id="bookstore.orders.orders_user_fk",
                        name="orders_user_fk",
                        kind="foreign_key",
                        columns=["user_id"],
                        referenced_schema="bookstore",
                        referenced_table="users",
                        referenced_columns=["id"],
                        on_update="no_action",
                        on_delete="restrict",
                    )
                ],
                indexes=[
                    IndexSnapshot(
                        id="bookstore.orders.orders_status_idx",
                        name="orders_status_idx",
                        unique=False,
                        primary=False,
                        columns=["status"],
                        directions=["asc"],
                    )
                ],
            ),
            _table(
                "products",
                [_column("products", "sku", position=1)],
                constraints=[
                    ConstraintSnapshot(
                        id="bookstore.products.products_sku_check",
                        name="products_sku_check",
                        kind="check",
                        columns=["sku"],
                        check_expression=MALICIOUS,
                    )
                ],
            ),
        ],
        dependencies=[
            DependencySnapshot(
                id="bookstore.orders.orders_user_fk",
                from_table="bookstore.orders",
                to_table="bookstore.users",
                constraint_name="orders_user_fk",
                from_columns=["user_id"],
                to_columns=["id"],
            )
        ],
    )


def _operation(**overrides: object) -> PlanOperation:
    values: dict[str, object] = {
        "id": "op-1",
        "kind": "add_column",
        "summary": "structured operation",
        "table": "users",
        "destructive": False,
    }
    values.update(overrides)
    return PlanOperation(**values)  # type: ignore[arg-type]


def _proposal(
    snapshot: SchemaSnapshot,
    operations: list[PlanOperation],
    *,
    status: str = "proposed",
    request: str = "ignored by the risk engine",
    fingerprint: str | None = None,
    errors: list[PlanValidationError] | None = None,
) -> MigrationProposal:
    return MigrationProposal(
        source_id=snapshot.source_id,
        schema_name=snapshot.schema_name,
        schema_fingerprint=snapshot.fingerprint if fingerprint is None else fingerprint,
        request=request,
        status=status,  # type: ignore[arg-type]
        summary="summary",
        assumptions=[],
        clarification_questions=[],
        operations=operations,
        validation_errors=errors or [],
        destructive=any(operation.destructive for operation in operations),
        requires_risk_assessment=any(operation.destructive for operation in operations),
    )


def _rules(findings: list[RiskFinding]) -> list[str]:
    return [finding.rule_id for finding in findings]


def _by_rule(findings: list[RiskFinding], rule_id: str) -> RiskFinding:
    return next(finding for finding in findings if finding.rule_id == rule_id)


def _settings() -> Settings:
    return Settings.model_construct(
        app_name="SchemaPilot",
        api_v1_prefix="/api/v1",
        cors_origins="http://localhost:5173",
        app_database_url=None,
        sandbox_database_url=None,
        target_database_url=None,
        demo_database_url=None,
        demo_environment="",
        allow_demo_reset=False,
        target_execution_enabled=False,
        allow_app_migrations=False,
    )


def test_nullable_column_is_low_risk_and_eligible() -> None:
    snapshot = _snapshot()
    assessment = assess_risk(
        snapshot,
        _proposal(
            snapshot,
            [
                _operation(
                    column="nickname",
                    data_type="text",
                    nullable=True,
                )
            ],
        ),
    )
    finding = _by_rule(assessment.findings, "SP-R005")
    assert finding.disposition == "info"
    assert finding.data_check == "not_required"
    assert finding.reversibility == "reversible"
    assert assessment.artifact_eligible is True
    assert assessment.eligibility_reason == "eligible"
    assert assessment.policy_blocked is False


def test_defaulted_column_needs_a_row_check() -> None:
    snapshot = _snapshot()
    assessment = assess_risk(
        snapshot,
        _proposal(
            snapshot,
            [
                _operation(
                    column="loyalty_points",
                    data_type="integer",
                    nullable=True,
                    default="0",
                )
            ],
        ),
    )
    finding = _by_rule(assessment.findings, "SP-R006")
    assert finding.disposition == "warning"
    assert finding.data_check == "not_run"
    assert assessment.artifact_eligible is False
    assert assessment.eligibility_reason == "data_check_not_run"
    assert "passed" not in assessment.model_dump_json()


def test_not_null_column_without_default_is_blocked() -> None:
    snapshot = _snapshot()
    assessment = assess_risk(
        snapshot,
        _proposal(
            snapshot,
            [
                _operation(
                    column="loyalty_points",
                    data_type="integer",
                    nullable=False,
                )
            ],
        ),
    )
    finding = _by_rule(assessment.findings, "SP-R007")
    assert finding.disposition == "policy_blocked"
    assert finding.data_check == "not_run"
    assert assessment.eligibility_reason == "policy_blocked"


def test_soft_delete_does_not_drop_rows() -> None:
    snapshot = _snapshot()
    assessment = assess_risk(
        snapshot,
        _proposal(
            snapshot,
            [
                _operation(
                    column="deleted_at",
                    data_type="timestamptz",
                    nullable=True,
                )
            ],
        ),
    )
    assert _rules(assessment.findings) == ["SP-R005", "SP-R016"]
    soft_delete = _by_rule(assessment.findings, "SP-R016")
    assert "does not delete rows" in soft_delete.explanation
    assert assessment.artifact_eligible is True


def test_index_uses_snapshot_columns() -> None:
    snapshot = _snapshot()
    assessment = assess_risk(
        snapshot,
        _proposal(
            snapshot,
            [
                _operation(
                    kind="add_index",
                    table="orders",
                    index_columns=["user_id"],
                )
            ],
        ),
    )
    finding = _by_rule(assessment.findings, "SP-R008")
    assert "bookstore.orders.user_id" in finding.affected_objects
    assert finding.data_check == "not_required"
    assert assessment.artifact_eligible is True


def test_rename_column_reports_index_dependency() -> None:
    snapshot = _snapshot()
    assessment = assess_risk(
        snapshot,
        _proposal(
            snapshot,
            [
                _operation(
                    kind="rename_column",
                    table="orders",
                    column="status",
                    new_name="order_status",
                )
            ],
        ),
    )
    rename = _by_rule(assessment.findings, "SP-R004")
    dependency = _by_rule(assessment.findings, "SP-R017")
    assert rename.disposition == "high_risk"
    assert "bookstore.orders.orders_status_idx" in dependency.affected_objects
    assert assessment.artifact_eligible is True


def test_rename_without_dependencies_is_a_warning() -> None:
    snapshot = _snapshot()
    assessment = assess_risk(
        snapshot,
        _proposal(
            snapshot,
            [
                _operation(
                    kind="rename_column",
                    column="display_name",
                    new_name="public_name",
                )
            ],
        ),
    )
    finding = _by_rule(assessment.findings, "SP-R004")
    assert finding.disposition == "warning"
    assert "SP-R017" not in _rules(assessment.findings)


def test_rename_table_reports_foreign_keys() -> None:
    snapshot = _snapshot()
    assessment = assess_risk(
        snapshot,
        _proposal(
            snapshot,
            [_operation(kind="rename_table", table="users", new_name="customers")],
        ),
    )
    rename = _by_rule(assessment.findings, "SP-R003")
    dependency = _by_rule(assessment.findings, "SP-R017")
    assert rename.disposition == "high_risk"
    assert "bookstore.orders.orders_user_fk" in dependency.affected_objects
    assert "bookstore.users.users_pkey" in dependency.affected_objects


def test_unique_constraint_is_not_claimed_to_pass() -> None:
    snapshot = _snapshot()
    assessment = assess_risk(
        snapshot,
        _proposal(
            snapshot,
            [
                _operation(
                    kind="add_constraint",
                    table="users",
                    column="display_name",
                    constraint_kind="unique",
                )
            ],
        ),
    )
    finding = _by_rule(assessment.findings, "SP-R009")
    assert finding.disposition == "high_risk"
    assert finding.data_check == "not_run"
    assert assessment.eligibility_reason == "data_check_not_run"


def test_not_null_constraint_distinguishes_snapshot_nullability() -> None:
    snapshot = _snapshot()
    nullable = assess_risk(
        snapshot,
        _proposal(
            snapshot,
            [
                _operation(
                    kind="add_constraint",
                    column="display_name",
                    constraint_kind="not_null",
                )
            ],
        ),
    )
    already = assess_risk(
        snapshot,
        _proposal(
            snapshot,
            [
                _operation(
                    kind="add_constraint",
                    column="email",
                    constraint_kind="not_null",
                )
            ],
        ),
    )
    pending = _by_rule(nullable.findings, "SP-R010")
    known = _by_rule(already.findings, "SP-R010")
    assert pending.data_check == "not_run"
    assert pending.disposition == "high_risk"
    assert known.data_check == "not_required"
    assert known.disposition == "warning"
    assert nullable.artifact_eligible is False
    assert already.artifact_eligible is True


def test_check_constraint_is_stored_and_not_executed() -> None:
    snapshot = _snapshot()
    assessment = assess_risk(
        snapshot,
        _proposal(
            snapshot,
            [
                _operation(
                    kind="add_constraint",
                    table="orders",
                    constraint_kind="check",
                    check_expression="status in ('pending', 'paid')",
                )
            ],
        ),
    )
    finding = _by_rule(assessment.findings, "SP-R011")
    assert finding.data_check == "not_run"
    assert "not interpreted" in " ".join(finding.evidence)


def test_untrusted_sql_in_check_or_default_is_blocked() -> None:
    snapshot = _snapshot()
    check = assess_risk(
        snapshot,
        _proposal(
            snapshot,
            [
                _operation(
                    kind="add_constraint",
                    table="products",
                    constraint_kind="check",
                    check_expression="sku is not null; DROP TABLE bookstore.orders",
                )
            ],
        ),
    )
    default = assess_risk(
        snapshot,
        _proposal(
            snapshot,
            [
                _operation(
                    column="note",
                    data_type="text",
                    nullable=True,
                    default="DROP TABLE bookstore.orders",
                )
            ],
        ),
    )
    assert _by_rule(check.findings, "SP-R012").disposition == "policy_blocked"
    assert _by_rule(default.findings, "SP-R012").disposition == "policy_blocked"
    assert check.artifact_eligible is False
    assert "SP-R011" not in _rules(check.findings)
    assert "SP-R006" not in _rules(default.findings)


def test_invalid_references_are_blocked() -> None:
    snapshot = _snapshot()
    missing_table = assess_risk(
        snapshot,
        _proposal(
            snapshot,
            [
                _operation(
                    table="customers",
                    column="nickname",
                    data_type="text",
                    nullable=True,
                )
            ],
        ),
    )
    missing_column = assess_risk(
        snapshot,
        _proposal(
            snapshot,
            [
                _operation(
                    kind="add_index",
                    table="users",
                    index_columns=["passport"],
                )
            ],
        ),
    )
    assert _by_rule(missing_table.findings, "SP-R013").evidence[0].endswith("customers")
    assert "passport" in _by_rule(missing_column.findings, "SP-R013").evidence[0]
    assert missing_table.eligibility_reason == "policy_blocked"
    assert missing_column.artifact_eligible is False


def test_unsupported_type_is_blocked() -> None:
    snapshot = _snapshot()
    assessment = assess_risk(
        snapshot,
        _proposal(
            snapshot,
            [
                _operation(
                    column="payload",
                    data_type="json",
                    nullable=True,
                )
            ],
        ),
    )
    assert _by_rule(assessment.findings, "SP-R014").disposition == "policy_blocked"
    assert assessment.artifact_eligible is False


def test_incomplete_plans_are_ineligible() -> None:
    snapshot = _snapshot()
    clarifying = assess_risk(snapshot, _proposal(snapshot, [], status="needs_clarification"))
    rejected = assess_risk(
        snapshot,
        _proposal(
            snapshot,
            [],
            status="rejected",
            errors=[
                PlanValidationError(
                    id="error-1",
                    code="unsupported_operation",
                    message="Changing a column type is not supported.",
                )
            ],
        ),
    )
    assert _by_rule(clarifying.findings, "SP-R015").disposition == "policy_blocked"
    assert clarifying.eligibility_reason == "plan_not_proposed"
    assert "unsupported_operation" in " ".join(_by_rule(rejected.findings, "SP-R015").evidence)


def test_drop_table_is_blocked_and_lists_dependencies() -> None:
    snapshot = _snapshot()
    assessment = assess_risk(
        snapshot,
        _proposal(
            snapshot,
            [_operation(kind="destructive", table="orders", destructive=True)],
        ),
    )
    drop = _by_rule(assessment.findings, "SP-R001")
    dependency = _by_rule(assessment.findings, "SP-R017")
    assert drop.disposition == "policy_blocked"
    assert drop.reversibility == "irreversible"
    assert drop.data_check == "not_required"
    assert "bookstore.orders.orders_user_fk" in dependency.affected_objects
    assert "bookstore.orders.orders_status_idx" in dependency.affected_objects
    assert assessment.eligibility_reason == "policy_blocked"


def test_drop_column_reports_the_foreign_key() -> None:
    snapshot = _snapshot()
    assessment = assess_risk(
        snapshot,
        _proposal(
            snapshot,
            [
                _operation(
                    kind="destructive",
                    table="orders",
                    column="user_id",
                    destructive=True,
                )
            ],
        ),
    )
    assert _by_rule(assessment.findings, "SP-R002").disposition == "policy_blocked"
    assert "bookstore.orders.orders_user_fk" in _by_rule(
        assessment.findings, "SP-R017"
    ).affected_objects
    assert "bookstore.orders.orders_status_idx" not in _by_rule(
        assessment.findings, "SP-R017"
    ).affected_objects


def test_fingerprint_mismatch_is_blocked() -> None:
    snapshot = _snapshot()
    assessment = assess_risk(
        snapshot,
        _proposal(
            snapshot,
            [_operation(column="nickname", data_type="text", nullable=True)],
            fingerprint="other-snapshot",
        ),
    )
    assert _by_rule(assessment.findings, "SP-R018").disposition == "policy_blocked"
    assert assessment.artifact_eligible is False


def test_request_text_and_comments_do_not_change_risk() -> None:
    snapshot = _snapshot()
    operation = _operation(column="nickname", data_type="text", nullable=True)
    benign = assess_risk(snapshot, _proposal(snapshot, [operation], request="add nickname"))
    malicious = assess_risk(
        snapshot,
        _proposal(snapshot, [operation], request=MALICIOUS),
    )
    assert benign.findings == malicious.findings
    assert "SP-R001" not in _rules(benign.findings)
    assert "SP-R012" not in _rules(benign.findings)
    serialized = benign.model_dump_json()
    assert "DROP TABLE" not in serialized
    assert MALICIOUS not in serialized


def test_related_objects_follow_snapshot_metadata() -> None:
    snapshot = _snapshot()
    assert "bookstore.orders.orders_user_fk" in related_object_ids(snapshot, "users", "id")
    assert related_object_ids(snapshot, "users", "display_name") == ()
    assert contains_untrusted_sql("status in ('paid')") is False
    assert contains_untrusted_sql(MALICIOUS) is True


def test_planner_drop_is_assessed_without_connecting(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_if_called(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("risk assessment connected to a database")

    monkeypatch.setattr(session_module, "create_engine", fail_if_called)
    monkeypatch.setattr(session_module, "create_demo_engine", fail_if_called)
    monkeypatch.setattr(session_module, "create_bookstore_source_engine", fail_if_called)
    snapshot = _snapshot()
    proposal = propose_migration(snapshot, "Drop table orders")
    assessment = assess_risk(snapshot, proposal)
    assert proposal.operations[0].kind == "destructive"
    assert _by_rule(assessment.findings, "SP-R001").disposition == "policy_blocked"


def test_risk_modules_do_not_read_comments_or_sqlalchemy() -> None:
    root = Path(__file__).resolve().parents[1] / "app" / "services"
    for name in ("risk_engine.py", "dependency_analyzer.py", "sql_safety.py"):
        source = (root / name).read_text(encoding="utf-8")
        assert ".comment" not in source
        assert "create_engine" not in source
        assert "sqlalchemy" not in source


def test_risk_route_uses_the_structured_plan(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_if_called(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("risk route opened a database engine")

    monkeypatch.setattr(session_module, "create_engine", fail_if_called)
    monkeypatch.setattr(session_module, "create_demo_engine", fail_if_called)
    monkeypatch.setattr(session_module, "create_bookstore_source_engine", fail_if_called)
    monkeypatch.setattr("app.api.risk.inspect_source", lambda _settings, _source_id: _snapshot())
    client = TestClient(create_app(_settings()))
    response = client.post(
        "/api/v1/sources/bookstore-demo/risk",
        json={"request": "Add a nullable text column called nickname to users"},
    )
    extra = client.post(
        "/api/v1/sources/bookstore-demo/risk",
        json={"request": "Add a column", "database_url": "postgresql://secret@db/prod"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["schema_fingerprint"] == "fingerprint-1"
    assert body["artifact_eligible"] is True
    assert body["findings"][0]["rule_id"] == "SP-R005"
    assert "DROP TABLE" not in response.text
    assert "postgresql" not in response.text
    assert extra.status_code == 422
    assert "secret" not in extra.text
