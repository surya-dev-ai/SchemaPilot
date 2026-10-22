"""Planner tests. These tests build a snapshot in memory and do not open PostgreSQL."""

from pathlib import Path

import pytest
from app.core.config import Settings
from app.db import session as session_module
from app.demo.bookstore import USER_TABLE_COMMENT
from app.main import create_app
from app.schemas.domain import (
    ColumnSnapshot,
    ConstraintSnapshot,
    IndexSnapshot,
    SchemaSnapshot,
    TableSnapshot,
)
from app.services.planner import propose_migration
from fastapi.testclient import TestClient

MALICIOUS_COMMENT = USER_TABLE_COMMENT


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
        comment=MALICIOUS_COMMENT,
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
        comment=MALICIOUS_COMMENT,
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
        dependencies=[],
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
                        id="bookstore.users.users_email_unique",
                        name="users_email_unique",
                        kind="unique",
                        columns=["email"],
                    )
                ],
            ),
            _table(
                "products",
                [
                    _column("products", "id", position=1),
                    _column("products", "sku", position=2),
                    _column("products", "stock_quantity", position=3),
                ],
                constraints=[
                    ConstraintSnapshot(
                        id="bookstore.products.products_sku_unique",
                        name="products_sku_unique",
                        kind="unique",
                        columns=["sku"],
                    )
                ],
            ),
            _table(
                "orders",
                [
                    _column("orders", "id", position=1),
                    _column("orders", "status", position=2),
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
            _table("order_items", [_column("order_items", "id", position=1)]),
        ],
    )


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


def test_planner_source_does_not_read_schema_comments() -> None:
    source = Path("app/services/planner.py").read_text(encoding="utf-8")
    assert ".comment" not in source


def test_nullable_column_paraphrases_match() -> None:
    requests = (
        "Add a nullable text column called nickname to users",
        "Please give users an optional text column named nickname",
        "users need a nullable text field named nickname",
    )
    proposals = [propose_migration(_snapshot(), text) for text in requests]
    assert all(item.status == "proposed" for item in proposals)
    operations = [item.operations[0] for item in proposals]
    assert {operation.column for operation in operations} == {"nickname"}
    assert {operation.table for operation in operations} == {"users"}
    assert {operation.data_type for operation in operations} == {"text"}
    assert {operation.nullable for operation in operations} == {True}
    assert all(operation.kind == "add_column" for operation in operations)
    assert all(MALICIOUS_COMMENT not in item.model_dump_json() for item in proposals)
    again = propose_migration(_snapshot(), requests[0])
    assert again.model_dump() == proposals[0].model_dump()


def test_column_with_explicit_default() -> None:
    proposal = propose_migration(
        _snapshot(),
        "Add an integer column loyalty_points to users with default 0",
    )
    operation = proposal.operations[0]
    assert proposal.status == "proposed"
    assert operation.kind == "add_column"
    assert operation.data_type == "integer"
    assert operation.default == "0"
    assert operation.nullable is True
    assert proposal.assumptions[0].text.startswith("Nullability was not stated")


def test_soft_delete_uses_nullable_timestamp() -> None:
    proposal = propose_migration(_snapshot(), "Add soft-delete support to orders")
    operation = proposal.operations[0]
    assert operation.column == "deleted_at"
    assert operation.data_type == "timestamptz"
    assert operation.nullable is True
    assert operation.table == "orders"
    assert "DROP TABLE" not in proposal.model_dump_json()


def test_add_index_and_reject_existing_index() -> None:
    created = propose_migration(
        _snapshot(),
        "Add an index on the display_name column of users",
    )
    assert created.status == "proposed"
    assert created.operations[0].kind == "add_index"
    assert created.operations[0].index_columns == ["display_name"]
    existing = propose_migration(_snapshot(), "Index orders by status")
    assert existing.status == "rejected"
    assert existing.validation_errors[0].code == "index_exists"


def test_rename_column_and_table() -> None:
    column = propose_migration(
        _snapshot(),
        "Rename the email column on users to contact_email",
    )
    assert column.operations[0].kind == "rename_column"
    assert column.operations[0].column == "email"
    assert column.operations[0].new_name == "contact_email"
    table = propose_migration(_snapshot(), "Rename table products to catalog_items")
    assert table.operations[0].kind == "rename_table"
    assert table.operations[0].new_name == "catalog_items"


def test_explicit_unique_constraint_and_existing_constraint() -> None:
    created = propose_migration(
        _snapshot(),
        "Add a unique constraint on the display_name column of users",
    )
    assert created.status == "proposed"
    assert created.operations[0].constraint_kind == "unique"
    assert created.operations[0].column == "display_name"
    existing = propose_migration(_snapshot(), "Add a unique constraint on products.sku")
    assert existing.status == "rejected"
    assert existing.validation_errors[0].code == "constraint_exists"


def test_explicit_check_constraint_is_stored_not_executed() -> None:
    proposal = propose_migration(
        _snapshot(),
        "Add a check constraint on products requiring stock_quantity >= 0",
    )
    operation = proposal.operations[0]
    assert proposal.status == "proposed"
    assert operation.constraint_kind == "check"
    assert operation.check_expression == "stock_quantity >= 0"
    assert "CREATE" not in proposal.model_dump_json()


def test_destructive_request_is_marked_and_not_sql() -> None:
    proposal = propose_migration(_snapshot(), "Drop the orders table")
    assert proposal.status == "proposed"
    assert proposal.destructive is True
    assert proposal.requires_risk_assessment is True
    assert proposal.operations[0].kind == "destructive"
    assert proposal.operations[0].table == "orders"
    assert "alembic" not in proposal.model_dump_json().lower()
    serialized = proposal.model_dump_json()
    assert "CREATE " not in serialized
    assert "ALTER " not in serialized


def test_missing_type_asks_for_clarification() -> None:
    proposal = propose_migration(_snapshot(), "Add a nullable nickname column to users")
    assert proposal.status == "needs_clarification"
    assert proposal.operations == []
    assert any(question.topic == "data_type" for question in proposal.clarification_questions)


def test_ambiguous_request_asks_which_table() -> None:
    proposal = propose_migration(_snapshot(), "Add a column")
    assert proposal.status == "needs_clarification"
    assert any(question.topic == "table" for question in proposal.clarification_questions)


def test_unknown_table_and_column_are_rejected() -> None:
    missing_table = propose_migration(
        _snapshot(),
        "Add a nullable text column called bio to customers",
    )
    assert missing_table.status == "rejected"
    assert missing_table.validation_errors[0].code == "unknown_table"
    missing_column = propose_migration(_snapshot(), "Add an index on users.passport")
    assert missing_column.status == "rejected"
    assert missing_column.validation_errors[0].code == "unknown_column"


def test_unsupported_operation_is_rejected() -> None:
    proposal = propose_migration(_snapshot(), "Change the type of users.email to integer")
    assert proposal.status == "rejected"
    assert proposal.validation_errors[0].code == "unsupported_operation"
    assert proposal.operations == []


def test_schema_comment_is_not_an_instruction() -> None:
    proposal = propose_migration(
        _snapshot(),
        "Add a nullable text column called nickname to users",
    )
    serialized = proposal.model_dump_json()
    assert "DROP TABLE bookstore.orders" not in serialized
    assert all(operation.kind != "destructive" for operation in proposal.operations)
    assert proposal.destructive is False


def test_planner_does_not_connect(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_if_called(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("planner connected to a database")

    monkeypatch.setattr(session_module, "create_engine", fail_if_called)
    monkeypatch.setattr(session_module, "create_demo_engine", fail_if_called)
    monkeypatch.setattr(session_module, "create_bookstore_source_engine", fail_if_called)
    proposal = propose_migration(_snapshot(), "Add soft delete to users")
    assert proposal.operations[0].column == "deleted_at"


def test_plan_route_uses_the_inspector_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_if_called(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("plan route opened a database engine")

    monkeypatch.setattr(session_module, "create_engine", fail_if_called)
    monkeypatch.setattr(
        "app.api.plans.inspect_source",
        lambda _settings, source_id: _snapshot(),
    )
    client = TestClient(create_app(_settings()))
    response = client.post(
        "/api/v1/sources/bookstore-demo/plans",
        json={"request": "Add a nullable text column called nickname to users"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["schema_fingerprint"] == "fingerprint-1"
    assert body["status"] == "proposed"
    assert "postgresql" not in response.text
    assert "DROP TABLE" not in response.text


def test_malformed_plan_requests_are_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_if_called(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("malformed plan connected to a database")

    monkeypatch.setattr("app.api.plans.inspect_source", fail_if_called)
    client = TestClient(create_app(_settings()))
    blank = client.post("/api/v1/sources/bookstore-demo/plans", json={"request": "   "})
    extra = client.post(
        "/api/v1/sources/bookstore-demo/plans",
        json={"request": "Add a column", "database_url": "postgresql://secret@db/prod"},
    )
    too_long = client.post(
        "/api/v1/sources/bookstore-demo/plans",
        json={"request": "a" * 2001},
    )
    assert blank.status_code == 422
    assert extra.status_code == 422
    assert too_long.status_code == 422
    assert "secret" not in extra.text
