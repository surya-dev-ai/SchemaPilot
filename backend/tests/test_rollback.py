"""Rollback and report unit tests. These tests do not prove a live PostgreSQL downgrade."""

import hashlib
from pathlib import Path

import pytest
from app.core.config import Settings
from app.db import session as session_module
from app.main import create_app
from app.schemas.artifacts import MigrationArtifact, OperationReversibility
from app.schemas.domain import ColumnSnapshot, SchemaSnapshot, TableSnapshot
from app.schemas.planning import Assumption, MigrationProposal, PlanOperation
from app.schemas.report import SafetyReport
from app.schemas.rollback import BaselineEvidence, RollbackReport
from app.schemas.sandbox import SandboxRun
from app.services.migration_generator import generate_migration
from app.services.planner import propose_migration
from app.services.report_service import build_safety_report
from app.services.risk_engine import assess_risk
from app.services.rollback_tester import (
    DowngradeRejected,
    classify_restoration,
    parse_downgrade_sql,
    run_rollback_test,
)
from fastapi.testclient import TestClient

SANDBOX_URL = (
    "postgresql+psycopg://schemapilot_sandbox:change_me_local_sandbox"
    "@127.0.0.1:5433/schemapilot_sandbox"
)


def _column(table: str, name: str, *, nullable: bool = False, position: int = 1) -> ColumnSnapshot:
    return ColumnSnapshot(
        id=f"bookstore.{table}.{name}",
        name=name,
        ordinal_position=position,
        data_type="text",
        udt_name="text",
        nullable=nullable,
        identity="none",
        generated="never",
    )


def _table(name: str, columns: list[ColumnSnapshot]) -> TableSnapshot:
    return TableSnapshot(
        id=f"bookstore.{name}",
        schema_name="bookstore",
        name=name,
        columns=columns,
        constraints=[],
        indexes=[],
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
                    _column("users", "id"),
                    _column("users", "email", position=2),
                    _column("users", "display_name", nullable=True, position=3),
                ],
            ),
            _table(
                "orders",
                [
                    _column("orders", "id"),
                    _column("orders", "user_id", position=2),
                    _column("orders", "status", position=3),
                ],
            ),
        ],
        dependencies=[],
    )


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "app_name": "SchemaPilot",
        "api_v1_prefix": "/api/v1",
        "cors_origins": "http://localhost:5173",
        "sandbox_database_url": SANDBOX_URL,
        "allow_sandbox_execution": True,
        "target_execution_enabled": False,
        "allow_app_migrations": False,
        "allow_demo_reset": False,
        "demo_environment": "",
    }
    values.update(overrides)
    return Settings.model_construct(**values)  # type: ignore[arg-type]


def _generated(request: str, directory: Path) -> tuple[SchemaSnapshot, MigrationArtifact]:
    snapshot = _snapshot()
    proposal = propose_migration(snapshot, request)
    artifact = generate_migration(snapshot, proposal, assess_risk(snapshot, proposal), directory)
    return snapshot, artifact


def _evidence() -> BaselineEvidence:
    return BaselineEvidence(
        schema_fingerprint="fingerprint-1",
        tables=["orders", "users"],
        row_counts={"users": 3, "products": 4, "orders": 2, "order_items": 3},
        emails=["mira@example.test"],
    )


def _upgrade(result: str = "passed", applied: bool = True) -> SandboxRun:
    return SandboxRun(
        migration_id="sp0123456789ab",
        source_id="bookstore-demo",
        schema_fingerprint="fingerprint-1",
        artifact_checksum="sha256:abc",
        sandbox_database="schemapilot_sandbox",
        sandbox_user="schemapilot_sandbox",
        postgres_version="16.0",
        started_at="2026-10-15T00:00:00+00:00",
        finished_at="2026-10-15T00:00:01+00:00",
        result=result,  # type: ignore[arg-type]
        upgrade_applied=applied,
        restored=False,
        cleaned_up=False,
        checks=[],
        observed_tables=["orders", "users"],
        error=None if result == "passed" else "upgrade failed",
    )


def test_classify_requires_complete_evidence() -> None:
    assert (
        classify_restoration(
            upgrade_passed=False,
            evidence_complete=True,
            downgrade_executed=False,
            downgrade_failed=False,
            schema_matches=None,
            data_restored=None,
            data_loss=False,
        )
        == "not_verified"
    )
    assert (
        classify_restoration(
            upgrade_passed=True,
            evidence_complete=False,
            downgrade_executed=True,
            downgrade_failed=False,
            schema_matches=True,
            data_restored=True,
            data_loss=False,
        )
        == "not_verified"
    )
    assert (
        classify_restoration(
            upgrade_passed=True,
            evidence_complete=True,
            downgrade_executed=True,
            downgrade_failed=True,
            schema_matches=True,
            data_restored=True,
            data_loss=False,
        )
        == "failed"
    )
    assert (
        classify_restoration(
            upgrade_passed=True,
            evidence_complete=True,
            downgrade_executed=True,
            downgrade_failed=False,
            schema_matches=False,
            data_restored=True,
            data_loss=False,
        )
        == "failed"
    )
    assert (
        classify_restoration(
            upgrade_passed=True,
            evidence_complete=True,
            downgrade_executed=True,
            downgrade_failed=False,
            schema_matches=True,
            data_restored=True,
            data_loss=True,
        )
        == "partial_restoration"
    )
    assert (
        classify_restoration(
            upgrade_passed=True,
            evidence_complete=True,
            downgrade_executed=True,
            downgrade_failed=False,
            schema_matches=True,
            data_restored=True,
            data_loss=False,
        )
        == "exact_restoration"
    )


def test_failed_upgrade_does_not_run_a_downgrade(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _snapshot_artifact = _generated("Add a nullable text column called nickname to users", tmp_path)
    artifact = _snapshot_artifact[1]
    calls = {"downgrade": 0}

    def fail_downgrade(*_args: object, **_kwargs: object) -> None:
        calls["downgrade"] += 1
        raise AssertionError("downgrade ran after a failed upgrade")

    monkeypatch.setattr(
        "app.services.rollback_tester.prepare_sandbox_baseline",
        lambda _settings: _snapshot(),
    )
    monkeypatch.setattr(
        "app.services.rollback_tester.read_baseline_evidence",
        lambda _settings, _snapshot_value: _evidence(),
    )
    monkeypatch.setattr(
        "app.services.rollback_tester.run_sandbox",
        lambda *_args, **_kwargs: _upgrade("failed", applied=False),
    )
    monkeypatch.setattr("app.services.rollback_tester._downgrade", fail_downgrade)
    report = run_rollback_test(_settings(), artifact.migration_id, directory=tmp_path)
    assert report.status == "not_verified"
    assert report.downgrade_executed is False
    assert calls["downgrade"] == 0


def test_missing_baseline_is_not_verified(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    artifact = _generated("Add a nullable text column called nickname to users", tmp_path)[1]
    monkeypatch.setattr(
        "app.services.rollback_tester.prepare_sandbox_baseline",
        lambda _settings: _snapshot(),
    )
    monkeypatch.setattr(
        "app.services.rollback_tester.read_baseline_evidence",
        lambda _settings, _snapshot_value: None,
    )
    monkeypatch.setattr(
        "app.services.rollback_tester.run_sandbox",
        lambda *_args, **_kwargs: _upgrade(),
    )
    report = run_rollback_test(_settings(), artifact.migration_id, directory=tmp_path)
    assert report.status == "not_verified"
    assert report.downgrade_executed is False
    assert report.baseline is None


def test_tampered_artifact_and_checksum_mismatch_are_not_verified(tmp_path: Path) -> None:
    artifact = _generated("Add a nullable text column called nickname to users", tmp_path)[1]
    json_path = tmp_path / f"{artifact.migration_id}.json"
    original = json_path.read_text(encoding="utf-8")
    json_path.write_text(original.replace("TEXT NULL", "TEXT NOT NULL"), encoding="utf-8")
    mismatched = run_rollback_test(_settings(), artifact.migration_id, directory=tmp_path)
    assert mismatched.status == "not_verified"
    assert mismatched.downgrade_executed is False
    assert "checksum" in (mismatched.error or "")
    json_path.write_text(original, encoding="utf-8")
    module_path = tmp_path / f"{artifact.migration_id}.py"
    edited = module_path.read_text(encoding="utf-8") + "\n# edited\n"
    module_path.write_text(edited, encoding="utf-8")
    tampered = run_rollback_test(_settings(), artifact.migration_id, directory=tmp_path)
    assert tampered.status == "not_verified"
    assert "Alembic" in (tampered.error or "")


def test_downgrade_allowlist_rejects_drop_table(tmp_path: Path) -> None:
    artifact = _generated("Add a nullable text column called nickname to users", tmp_path)[1]
    statements = parse_downgrade_sql(artifact.downgrade_sql)
    assert statements[0].kind == "drop_column"
    effect = artifact.operation_reversibility[0].downgrade_effect
    assert "does not recover its former values" in effect
    with pytest.raises(Exception, match="will not run"):
        parse_downgrade_sql('DROP TABLE "bookstore"."orders";')


def test_report_keeps_review_separate_from_approval() -> None:
    proposal = MigrationProposal(
        source_id="bookstore-demo",
        schema_name="bookstore",
        schema_fingerprint="fingerprint-1",
        request="Add a nullable text column called nickname to users",
        status="proposed",
        summary="Add nullable text column nickname to users.",
        assumptions=[Assumption(id="assumption-1", text="The column is nullable.")],
        clarification_questions=[],
        operations=[
            PlanOperation(
                id="op-1",
                kind="add_column",
                summary="Add nullable text column nickname to users.",
                table="users",
                column="nickname",
                data_type="text",
                nullable=True,
            )
        ],
        validation_errors=[],
        destructive=False,
        requires_risk_assessment=False,
    )
    snapshot = _snapshot()
    assessment = assess_risk(snapshot, proposal)
    artifact = MigrationArtifact(
        migration_id="sp0123456789ab",
        source_id="bookstore-demo",
        schema_name="bookstore",
        schema_fingerprint="fingerprint-1",
        summary=proposal.summary,
        status="generated",
        applied=False,
        operation_ids=["op-1"],
        sql_preview='ALTER TABLE "bookstore"."users" ADD COLUMN "nickname" TEXT NULL;',
        downgrade_sql='ALTER TABLE "bookstore"."users" DROP COLUMN "nickname";',
        alembic_source="def upgrade():\n    pass\n\ndef downgrade():\n    pass\n",
        reversibility="partially_reversible",
        operation_reversibility=[
            OperationReversibility(
                operation_id="op-1",
                kind="add_column",
                reversibility="partially_reversible",
                upgrade_effect="Add column.",
                downgrade_effect="Recreating a dropped column does not restore its former values.",
                data_loss_on_downgrade=True,
            )
        ],
        checksum="sha256:abc",
        location="",
    )
    rollback = RollbackReport(
        migration_id=artifact.migration_id,
        artifact_checksum=artifact.checksum,
        source_id=artifact.source_id,
        schema_fingerprint=artifact.schema_fingerprint,
        sandbox_database="schemapilot_sandbox",
        sandbox_user="schemapilot_sandbox",
        postgres_version="16.0",
        started_at="2026-10-15T00:00:00+00:00",
        finished_at="2026-10-15T00:00:02+00:00",
        status="partial_restoration",
        upgrade=_upgrade(),
        baseline=_evidence(),
        downgrade_executed=True,
        schema_matches_baseline=True,
        data_checks=[],
        data_loss_limitations=[
            "Recreating a dropped column does not restore its former values."
        ],
        error=None,
    )
    rollback.upgrade.migration_id = artifact.migration_id  # type: ignore[union-attr]
    report = build_safety_report(
        proposal,
        assessment,
        artifact,
        rollback,
        artifact_matches=True,
    )
    assert isinstance(report, SafetyReport)
    assert report.approved is False
    assert report.applied is False
    assert report.fully_reversible is False
    assert report.eligible_for_review is True
    assert report.rollback_status == "partial_restoration"
    assert report.request == proposal.request
    assert report.risk_findings
    incomplete = build_safety_report(
        proposal,
        assessment,
        artifact,
        None,
        artifact_matches=True,
    )
    assert incomplete.eligible_for_review is False
    assert incomplete.rollback_status == "not_verified"
    assert "sandbox upgrade" in incomplete.missing_evidence


def test_rollback_route_does_not_open_a_database(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_if_called(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("route opened a database")

    monkeypatch.setattr(session_module, "create_engine", fail_if_called)
    monkeypatch.setattr(session_module, "create_demo_engine", fail_if_called)
    monkeypatch.setattr(session_module, "create_bookstore_source_engine", fail_if_called)
    monkeypatch.setattr(session_module, "create_sandbox_engine", fail_if_called)
    client = TestClient(create_app(_settings(allow_sandbox_execution=False)))
    unconfirmed = client.post(
        "/api/v1/sources/bookstore-demo/artifacts/sp0123456789ab/rollback",
        json={"confirm": False},
    )
    extra = client.post(
        "/api/v1/sources/bookstore-demo/artifacts/sp0123456789ab/report",
        json={"request": "Add a column", "confirm": True, "database_url": "postgresql://secret@db/prod"},
    )
    assert unconfirmed.status_code == 409
    assert extra.status_code == 422
    assert "secret" not in extra.text


def test_rollback_modules_do_not_use_source_engines() -> None:
    root = Path(__file__).resolve().parents[1] / "app" / "services"
    for name in ("rollback_tester.py", "report_service.py"):
        source = (root / name).read_text(encoding="utf-8")
        assert "create_demo_engine" not in source
        assert "create_bookstore_source_engine" not in source
        assert ".comment" not in source
    assert hashlib.sha256(b"stable").hexdigest()


def test_unquoted_downgrade_sql_is_rejected() -> None:
    with pytest.raises(DowngradeRejected):
        parse_downgrade_sql("ALTER TABLE bookstore.users DROP COLUMN nickname;")
