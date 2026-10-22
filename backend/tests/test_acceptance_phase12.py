"""Phase 12 acceptance and security gates.

These tests are mocked or in-memory. They are not live PostgreSQL evidence.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from app.core.config import Settings
from app.main import create_app
from app.schemas.interpretation import LlmInterpretationPayload
from app.schemas.workflow import ApprovalCreateRequest
from app.services.auth import AuthenticatedPrincipal, require_authenticated_principal
from app.services.llm.assisted_planner import create_proposal
from app.services.llm.provider import CallableProvider, parse_provider_json
from app.services.planner import propose_from_llm_payload, propose_migration
from app.services.report_service import build_safety_report
from app.services.risk_engine import assess_risk
from app.services.target_execution import (
    TargetExecutionPreflight,
    TargetExecutionRejected,
    assert_target_execution_allowed,
)
from app.services.workflow_store import (
    WorkflowStoreError,
    create_tables,
    persist_workflow,
    record_approval,
)
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from tests.test_llm import _snapshot, _valid_payload
from tests.test_workflow_store import _artifact, _eligible_bundle, _settings


def _preflight(**overrides: object) -> TargetExecutionPreflight:
    values: dict[str, object] = {
        "migration_id": "sp0123456789ab",
        "artifact_checksum": "sha256:artifact",
        "report_checksum": "sha256:report",
        "target_identity": "staging-target",
        "schema_fingerprint": "fingerprint-1",
        "rollback_status": "exact_restoration",
        "eligible_for_review": True,
        "report_stale": False,
        "policy_blocked": False,
        "missing_evidence": (),
        "not_run_checks": (),
        "sandbox_upgrade_passed": True,
        "approval_present": True,
        "approval_target_identity": "staging-target",
        "approval_artifact_checksum": "sha256:artifact",
        "approval_report_checksum": "sha256:report",
        "authentication_available": False,
        "principal": None,
    }
    values.update(overrides)
    return TargetExecutionPreflight(**values)  # type: ignore[arg-type]


def test_no_apply_route_and_target_execution_defaults_off() -> None:
    client = TestClient(create_app(_settings()))
    paths = client.get("/openapi.json").json()["paths"]
    assert "/api/v1/apply" not in paths
    assert not any(path.endswith("/apply") for path in paths)
    health = client.get("/api/v1/health").json()
    assert health["target_execution_enabled"] is False
    assert health["authentication_available"] is False
    assert "password" not in json.dumps(health).lower()
    assert "api_key" not in json.dumps(health).lower()


def test_target_execution_preflight_fails_closed_without_auth() -> None:
    settings = Settings.model_construct(
        target_execution_enabled=True,
        authentication_available=False,
        target_database_url="postgresql+psycopg://target:local@127.0.0.1:5435/schemapilot_target",
        app_database_url="postgresql+psycopg://app:local@127.0.0.1:5432/schemapilot",
        sandbox_database_url="postgresql+psycopg://sandbox:local@127.0.0.1:5433/schemapilot_sandbox",
        demo_database_url="postgresql+psycopg://demo:local@127.0.0.1:5434/schemapilot_bookstore",
    )
    with pytest.raises(TargetExecutionRejected) as exc:
        assert_target_execution_allowed(settings, _preflight())
    assert exc.value.code == "authentication_unavailable"


def test_target_execution_disabled_even_with_synthetic_principal() -> None:
    settings = Settings.model_construct(
        target_execution_enabled=False,
        authentication_available=True,
        target_database_url="postgresql+psycopg://target:local@127.0.0.1:5435/schemapilot_target",
        app_database_url="postgresql+psycopg://app:local@127.0.0.1:5432/schemapilot",
        sandbox_database_url="postgresql+psycopg://sandbox:local@127.0.0.1:5433/schemapilot_sandbox",
        demo_database_url="postgresql+psycopg://demo:local@127.0.0.1:5434/schemapilot_bookstore",
    )
    with pytest.raises(TargetExecutionRejected) as exc:
        assert_target_execution_allowed(
            settings,
            _preflight(principal=AuthenticatedPrincipal("reviewer@example.test", "test")),
        )
    assert exc.value.code == "target_execution_disabled"


def test_preflight_blocks_not_verified_stale_wrong_target_and_missing_sandbox() -> None:
    settings = Settings.model_construct(
        target_execution_enabled=True,
        authentication_available=True,
        target_database_url="postgresql+psycopg://target:local@127.0.0.1:5435/schemapilot_target",
        app_database_url="postgresql+psycopg://app:local@127.0.0.1:5432/schemapilot",
        sandbox_database_url="postgresql+psycopg://sandbox:local@127.0.0.1:5433/schemapilot_sandbox",
        demo_database_url="postgresql+psycopg://demo:local@127.0.0.1:5434/schemapilot_bookstore",
    )
    principal = AuthenticatedPrincipal("reviewer@example.test", "test")
    cases = [
        (_preflight(principal=principal, rollback_status="not_verified"), "rollback_not_verified"),
        (_preflight(principal=principal, report_stale=True), "stale_or_ineligible"),
        (
            _preflight(principal=principal, approval_target_identity="other-target"),
            "target_identity_mismatch",
        ),
        (
            _preflight(principal=principal, sandbox_upgrade_passed=False),
            "sandbox_evidence_missing",
        ),
        (
            _preflight(principal=principal, not_run_checks=("row_nulls",)),
            "policy_or_evidence_blocked",
        ),
        (
            _preflight(
                principal=principal,
                approval_artifact_checksum="sha256:other",
            ),
            "artifact_checksum_mismatch",
        ),
        (
            _preflight(
                principal=principal,
                approval_report_checksum="sha256:other-report",
            ),
            "report_checksum_mismatch",
        ),
    ]
    for preflight, code in cases:
        with pytest.raises(TargetExecutionRejected) as exc:
            assert_target_execution_allowed(settings, preflight)
        assert exc.value.code == code


def test_preflight_never_allows_execution_in_phase_12() -> None:
    settings = Settings.model_construct(
        target_execution_enabled=True,
        authentication_available=True,
        target_database_url="postgresql+psycopg://target:local@127.0.0.1:5435/schemapilot_target",
        app_database_url="postgresql+psycopg://app:local@127.0.0.1:5432/schemapilot",
        sandbox_database_url="postgresql+psycopg://sandbox:local@127.0.0.1:5433/schemapilot_sandbox",
        demo_database_url="postgresql+psycopg://demo:local@127.0.0.1:5434/schemapilot_bookstore",
    )
    with pytest.raises(TargetExecutionRejected) as exc:
        assert_target_execution_allowed(
            settings,
            _preflight(principal=AuthenticatedPrincipal("reviewer@example.test", "test")),
        )
    assert exc.value.code == "target_execution_not_implemented"


def test_authentication_rejects_request_body_usernames() -> None:
    with pytest.raises(Exception) as exc:
        require_authenticated_principal(_settings(), None)
    assert exc.value.code == "authentication_unavailable"  # type: ignore[attr-defined]


def test_approval_route_rejects_when_authentication_unavailable(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'meta.db'}")
    create_tables(engine)
    proposal, assessment, report, rollback = _eligible_bundle()
    detail = persist_workflow(
        _settings(),
        proposal=proposal,
        assessment=assessment,
        report=report,
        rollback=rollback,
        engine=engine,
    )
    with pytest.raises(WorkflowStoreError) as exc:
        record_approval(
            _settings(),
            detail.id,
            ApprovalCreateRequest(target_identity="staging-target", confirm=True),
            engine=engine,
        )
    assert exc.value.code == "authentication_unavailable"


def test_safe_additive_plan_remains_deterministic() -> None:
    proposal = propose_migration(
        _snapshot(),
        "Add a nullable text column called nickname to users",
    )
    assert proposal.status == "proposed"
    assert proposal.operations[0].kind == "add_column"
    assert proposal.operations[0].nullable is True
    assessment = assess_risk(_snapshot(), proposal)
    assert assessment.artifact_eligible is True


def test_llm_cannot_bypass_deterministic_controls_or_execute_sql() -> None:
    with pytest.raises(Exception):
        parse_provider_json(_valid_payload(sql="DROP TABLE users;"))
    stale = LlmInterpretationPayload.model_validate(
        _valid_payload(schema_fingerprint="stale")
    )
    rejected = propose_from_llm_payload(_snapshot(), "Add nickname", stale)
    assert rejected.status == "rejected"
    provider = CallableProvider(lambda *_a, **_k: _valid_payload())
    proposal = create_proposal(
        Settings(llm_enabled=True, llm_api_key="k"),
        _snapshot(),
        "Please add nickname somehow",
        use_llm=True,
        provider=provider,
    )
    assert proposal.interpretation_path == "llm_assisted"
    assessment = assess_risk(_snapshot(), proposal)
    assert assessment.artifact_eligible is True
    # Provider success is not approval or apply.
    assert proposal.provider_status == "ok"
    report = build_safety_report(
        proposal,
        assessment,
        _artifact(),
        None,
        artifact_matches=True,
    )
    assert report.approved is False
    assert report.applied is False
    assert report.eligible_for_review is False


def test_use_llm_defaults_false_on_plan_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import clear_settings_cache

    clear_settings_cache()
    app = create_app()

    def fake_inspect(_settings: Settings, _source_id: str):
        return _snapshot()

    monkeypatch.setattr("app.api.plans.inspect_source", fake_inspect)
    client = TestClient(app)
    response = client.post(
        "/api/v1/sources/bookstore-demo/plans",
        json={"request": "Add a nullable text column called nickname to users"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["interpretation_path"] == "deterministic"
    assert body["provider_status"] == "not_used"
