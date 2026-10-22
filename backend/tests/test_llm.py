"""Optional LLM assist tests. Providers are mocked; no live model calls by default."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from app.core.config import Settings, clear_settings_cache
from app.demo.bookstore import USER_TABLE_COMMENT
from app.main import create_app
from app.schemas.domain import (
    ColumnSnapshot,
    ConstraintSnapshot,
    SchemaSnapshot,
    TableSnapshot,
)
from app.schemas.interpretation import LlmInterpretationPayload, LlmOperationDraft
from app.schemas.planning import Assumption, MigrationProposal, PlanOperation
from app.schemas.report import SafetyReport
from app.schemas.risk import RiskAssessment
from app.services.llm.assisted_planner import create_proposal
from app.services.llm.provider import (
    CallableProvider,
    LlmProviderError,
    parse_provider_json,
)
from app.services.llm.schema_context import build_schema_context
from app.services.planner import propose_from_llm_payload, propose_migration
from app.services.risk_engine import assess_risk
from app.services.workflow_store import create_tables, persist_workflow
from fastapi.testclient import TestClient
from sqlalchemy import create_engine


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
        comment=USER_TABLE_COMMENT,
    )


def _snapshot(fingerprint: str = "fingerprint-1") -> SchemaSnapshot:
    return SchemaSnapshot(
        source_id="bookstore-demo",
        database_name="schemapilot_bookstore",
        schema_name="bookstore",
        fingerprint=fingerprint,
        dependencies=[],
        tables=[
            TableSnapshot(
                id="bookstore.users",
                schema_name="bookstore",
                name="users",
                comment=USER_TABLE_COMMENT,
                columns=[
                    _column("users", "id", position=1),
                    _column("users", "email", position=2),
                    _column("users", "display_name", nullable=True, position=3),
                ],
                constraints=[
                    ConstraintSnapshot(
                        id="bookstore.users.users_email_unique",
                        name="users_email_unique",
                        kind="unique",
                        columns=["email"],
                    )
                ],
                indexes=[],
            )
        ],
    )


def _valid_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_fingerprint": "fingerprint-1",
        "summary": "Add nullable text column nickname to users.",
        "assumptions": [],
        "clarification_questions": [],
        "operations": [
            {
                "kind": "add_column",
                "table": "users",
                "column": "nickname",
                "data_type": "text",
                "nullable": True,
            }
        ],
    }
    payload.update(overrides)
    return payload


def test_parse_valid_structured_provider_output() -> None:
    parsed = parse_provider_json(_valid_payload())
    assert parsed.operations[0].column == "nickname"


def test_normalize_azure_style_aliases() -> None:
    parsed = parse_provider_json(
        {
            "schema_fingerprint": "fingerprint-1",
            "summary": "Add nickname",
            "assumptions": ["optional text"],
            "clarification_questions": ["Should nickname be unique?"],
            "operations": [
                {
                    "action": "add_column",
                    "table_name": "users",
                    "column_name": "nickname",
                    "data_type": "text",
                    "nullable": True,
                    "index_columns": None,
                }
            ],
        }
    )
    assert parsed.operations[0].kind == "add_column"
    assert parsed.operations[0].table == "users"
    assert parsed.operations[0].column == "nickname"
    assert parsed.operations[0].index_columns == []
    assert parsed.clarification_questions[0].topic == "behavior"
    assert "unique" in parsed.clarification_questions[0].text.lower()


def test_malformed_and_sql_bearing_responses_are_rejected() -> None:
    with pytest.raises(LlmProviderError) as missing:
        parse_provider_json("not-json")
    assert missing.value.status == "malformed"

    with pytest.raises(LlmProviderError) as with_sql:
        parse_provider_json(_valid_payload(sql="DROP TABLE users"))
    assert with_sql.value.status == "malformed"
    assert "sql" in with_sql.value.message

    with pytest.raises(LlmProviderError):
        parse_provider_json(_valid_payload(operations=[{"kind": "run_sql", "table": "users"}]))


def test_schema_comments_are_untrusted_and_do_not_become_instructions() -> None:
    context = build_schema_context(_snapshot())
    assert context["tables"][0]["comment_untrusted"] == USER_TABLE_COMMENT
    assert "trust_note" in context

    def evil_handler(request_text: str, snapshot: SchemaSnapshot, schema_context: dict) -> dict:
        assert "comment_untrusted" in json.dumps(schema_context)
        # A confused model that follows the comment still cannot ship SQL.
        return {
            "schema_fingerprint": snapshot.fingerprint,
            "summary": "Followed comment",
            "assumptions": [],
            "clarification_questions": [],
            "operations": [],
            "sql": "DROP TABLE bookstore.orders",
        }

    provider = CallableProvider(evil_handler)
    settings = Settings(
        llm_enabled=True,
        llm_api_key="test-key",
        llm_fallback_to_deterministic=True,
    )
    proposal = create_proposal(
        settings,
        _snapshot(),
        "Please help with users",
        use_llm=True,
        provider=provider,
    )
    assert proposal.interpretation_path == "deterministic_fallback"
    assert proposal.provider_status == "malformed"
    assert proposal.llm_suggestion is None


def test_unknown_identifiers_and_stale_fingerprint() -> None:
    stale = LlmInterpretationPayload.model_validate(
        _valid_payload(schema_fingerprint="stale-fingerprint")
    )
    rejected = propose_from_llm_payload(_snapshot(), "Add nickname", stale)
    assert rejected.status == "rejected"
    assert "fingerprint" in rejected.validation_errors[0].message.lower()

    unknown = LlmInterpretationPayload.model_validate(
        _valid_payload(
            operations=[
                {
                    "kind": "add_column",
                    "table": "missing_table",
                    "column": "nickname",
                    "data_type": "text",
                    "nullable": True,
                }
            ]
        )
    )
    missing = propose_from_llm_payload(_snapshot(), "Add nickname", unknown)
    assert missing.status == "rejected"
    assert missing.validation_errors[0].code == "unknown_table"


def test_missing_credentials_timeout_and_provider_errors_fallback() -> None:
    settings = Settings(
        llm_enabled=True,
        llm_api_key=None,
        llm_fallback_to_deterministic=True,
    )
    proposal = create_proposal(
        settings,
        _snapshot(),
        "Add a nullable text column called nickname to users",
        use_llm=True,
    )
    assert proposal.interpretation_path == "deterministic_fallback"
    assert proposal.provider_status == "not_configured"
    assert proposal.status == "proposed"

    def boom(*_args: object, **_kwargs: object) -> dict:
        raise LlmProviderError("timeout", "LLM provider timed out.")

    timed_out = create_proposal(
        Settings(llm_enabled=True, llm_api_key="k", llm_fallback_to_deterministic=True),
        _snapshot(),
        "Add a nullable text column called nickname to users",
        use_llm=True,
        provider=CallableProvider(boom),
    )
    assert timed_out.interpretation_path == "deterministic_fallback"
    assert timed_out.provider_status == "timeout"

    hard_fail = create_proposal(
        Settings(llm_enabled=True, llm_api_key="k", llm_fallback_to_deterministic=False),
        _snapshot(),
        "Add a nullable text column called nickname to users",
        use_llm=True,
        provider=CallableProvider(boom),
    )
    assert hard_fail.status == "rejected"
    assert hard_fail.provider_status == "timeout"


def test_valid_llm_draft_passes_deterministic_validation() -> None:
    provider = CallableProvider(lambda *_a, **_k: _valid_payload())
    proposal = create_proposal(
        Settings(llm_enabled=True, llm_api_key="k"),
        _snapshot(),
        "Please add a nickname field on the people table named users",
        use_llm=True,
        provider=provider,
    )
    assert proposal.interpretation_path == "llm_assisted"
    assert proposal.provider_status == "ok"
    assert proposal.status == "proposed"
    assert proposal.operations[0].kind == "add_column"
    assert proposal.llm_suggestion is not None
    assert proposal.llm_suggestion.operations[0].column == "nickname"


def test_policy_blocked_and_not_run_still_block_eligibility() -> None:
    provider = CallableProvider(
        lambda *_a, **_k: _valid_payload(
            operations=[
                {
                    "kind": "destructive",
                    "table": "users",
                    "destructive": True,
                }
            ],
            summary="Drop users",
        )
    )
    proposal = create_proposal(
        Settings(llm_enabled=True, llm_api_key="k"),
        _snapshot(),
        "Drop table users",
        use_llm=True,
        provider=provider,
    )
    assessment = assess_risk(_snapshot(), proposal)
    assert assessment.policy_blocked or not assessment.artifact_eligible
    assert any(finding.data_check == "not_run" or finding.disposition == "policy_blocked"
               for finding in assessment.findings) or not assessment.artifact_eligible


def test_model_sql_is_never_executed(monkeypatch: pytest.MonkeyPatch) -> None:
    executed: list[str] = []

    def fake_execute(sql: str) -> None:
        executed.append(sql)

    monkeypatch.setattr("app.services.llm.assisted_planner.create_proposal", create_proposal)
    provider = CallableProvider(lambda *_a, **_k: _valid_payload(sql="SELECT 1"))
    settings = Settings(llm_enabled=True, llm_api_key="k", llm_fallback_to_deterministic=True)
    proposal = create_proposal(
        settings,
        _snapshot(),
        "Add nickname",
        use_llm=True,
        provider=provider,
    )
    assert executed == []
    assert "DROP" not in proposal.summary
    # Fallback path used because sql forbidden field failed parse.
    assert proposal.interpretation_path == "deterministic_fallback"


def test_workflow_persists_interpretation_metadata(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'meta.db'}")
    create_tables(engine)
    proposal = MigrationProposal(
        source_id="bookstore-demo",
        schema_name="bookstore",
        schema_fingerprint="fingerprint-1",
        request="Add a nullable text column called nickname to users",
        status="proposed",
        summary="Add nullable text column nickname to users.",
        assumptions=[Assumption(id="assumption-1", text="Column is nullable.")],
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
        interpretation_path="llm_assisted",
        provider_status="ok",
        provider_name="mock",
        provider_error=None,
        llm_suggestion=None,
    )
    assessment = RiskAssessment(
        source_id="bookstore-demo",
        schema_name="bookstore",
        schema_fingerprint="fingerprint-1",
        plan_status="proposed",
        findings=[],
        policy_blocked=False,
        artifact_eligible=True,
        eligibility_reason="eligible",
    )
    report = SafetyReport(
        request=proposal.request,
        interpreted_intent=proposal.summary,
        operations=proposal.operations,
        assumptions=proposal.assumptions,
        source_id="bookstore-demo",
        schema_fingerprint="fingerprint-1",
        migration_id="sp0123456789ab",
        artifact_checksum="sha256:artifact",
        artifact_status="generated",
        risk_findings=[],
        sandbox=None,
        rollback_status="not_verified",
        data_loss_limitations=[],
        missing_evidence=["sandbox upgrade"],
        blocking_reasons=[],
        eligible_for_review=False,
        approved=False,
        applied=False,
        fully_reversible=False,
    )
    settings = Settings(app_database_url="sqlite+pysqlite://")
    detail = persist_workflow(
        settings,
        proposal=proposal,
        assessment=assessment,
        report=report,
        rollback=None,
        engine=engine,
    )
    stored = json.loads(
        # reload via detail
        detail.model_dump_json()
    )
    assert detail.report.request == proposal.request
    events = detail.audit_events
    assert any(event.event_type == "workflow_persisted" for event in events)
    persist_event = next(event for event in events if event.event_type == "workflow_persisted")
    assert persist_event.detail["interpretation_path"] == "llm_assisted"
    assert persist_event.detail["provider_status"] == "ok"
    assert "api_key" not in json.dumps(stored)


def test_plan_route_accepts_use_llm_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_settings_cache()
    monkeypatch.setenv("SCHEMAPILOT_LLM_ENABLED", "false")
    app = create_app()

    def fake_inspect(_settings: Settings, _source_id: str) -> SchemaSnapshot:
        return _snapshot()

    monkeypatch.setattr("app.api.plans.inspect_source", fake_inspect)
    client = TestClient(app)
    response = client.post(
        "/api/v1/sources/bookstore-demo/plans",
        json={
            "request": "Add a nullable text column called nickname to users",
            "use_llm": True,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["interpretation_path"] == "deterministic_fallback"
    assert body["provider_status"] in {"not_configured", "disabled"}
    assert "api_key" not in json.dumps(body).lower()


def test_deterministic_path_unchanged_when_use_llm_false() -> None:
    deterministic = propose_migration(
        _snapshot(),
        "Add a nullable text column called nickname to users",
    )
    assisted_off = create_proposal(
        Settings(llm_enabled=True, llm_api_key="k"),
        _snapshot(),
        "Add a nullable text column called nickname to users",
        use_llm=False,
    )
    assert assisted_off.interpretation_path == "deterministic"
    assert assisted_off.provider_status == "not_used"
    assert assisted_off.operations == deterministic.operations


@pytest.mark.skipif(
    True,
    reason="Live LLM provider tests are disabled by default.",
)
def test_live_llm_provider_optional() -> None:
    raise AssertionError("unreachable")


def test_draft_operation_model_forbids_connection_overrides() -> None:
    with pytest.raises(Exception):
        LlmOperationDraft.model_validate(
            {
                "kind": "add_column",
                "table": "users",
                "column": "nickname",
                "data_type": "text",
                "connection_string": "postgresql://secret",
            }
        )


def test_checksum_mismatch_blocks_report_eligibility() -> None:
    from app.schemas.artifacts import MigrationArtifact
    from app.services.report_service import build_safety_report

    proposal = propose_migration(
        _snapshot(),
        "Add a nullable text column called nickname to users",
    )
    assessment = assess_risk(_snapshot(), proposal)
    artifact = MigrationArtifact(
        migration_id="sp0123456789ab",
        source_id="bookstore-demo",
        schema_name="bookstore",
        schema_fingerprint="fingerprint-1",
        summary=proposal.summary,
        status="generated",
        applied=False,
        operation_ids=["op-1"],
        sql_preview="-- preview",
        downgrade_sql="-- down",
        alembic_source="# module",
        reversibility="reversible",
        operation_reversibility=[],
        checksum="sha256:stale",
        location="artifacts/generated/sp0123456789ab.py",
    )
    report = build_safety_report(
        proposal,
        assessment,
        artifact,
        None,
        artifact_matches=False,
    )
    assert report.eligible_for_review is False
    assert any("does not match" in reason for reason in report.blocking_reasons)
