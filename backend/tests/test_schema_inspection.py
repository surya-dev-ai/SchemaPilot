"""Schema inspection tests that do not open PostgreSQL."""

from collections.abc import Mapping

import pytest
from app.core.config import Settings
from app.db import session as session_module
from app.demo.bookstore import USER_TABLE_COMMENT
from app.main import create_app
from app.services.schema_inspector import (
    INSPECTION_QUERIES,
    Catalog,
    assemble_snapshot,
    schema_fingerprint,
)
from app.services.source_manager import BOOKSTORE_SOURCE_ID
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

DEMO_URL = "postgresql+psycopg://demo:secret-token@127.0.0.1:5434/schemapilot_bookstore"
APP_URL = "postgresql+psycopg://app:secret@127.0.0.1:5432/schemapilot"
SANDBOX_URL = "postgresql+psycopg://sandbox:secret@127.0.0.1:5433/schemapilot_sandbox"


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "app_name": "SchemaPilot",
        "api_v1_prefix": "/api/v1",
        "cors_origins": "http://localhost:5173,http://127.0.0.1:5173",
        "app_database_url": APP_URL,
        "sandbox_database_url": SANDBOX_URL,
        "target_database_url": None,
        "demo_database_url": DEMO_URL,
        "demo_environment": "disposable",
        "allow_demo_reset": False,
        "target_execution_enabled": False,
        "allow_app_migrations": False,
    }
    values.update(overrides)
    return Settings.model_construct(**values)


def _fail_if_called(*_args: object, **_kwargs: object) -> None:
    raise AssertionError("inspection used a database engine it should not use")


class FakeResult:
    def __init__(self, rows: list[Mapping[str, object]]) -> None:
        self._rows = rows

    def mappings(self) -> "FakeResult":
        return self

    def all(self) -> list[Mapping[str, object]]:
        return self._rows

    def one(self) -> Mapping[str, object]:
        return self._rows[0]


class FakeConnection:
    def __init__(self, responses: dict[str, list[Mapping[str, object]]]) -> None:
        self.responses = responses
        self.statements: list[str] = []

    def execute(self, statement: object, params: object = None) -> FakeResult:
        del params
        sql = str(statement)
        self.statements.append(sql)
        for marker, rows in self.responses.items():
            if marker in sql:
                return FakeResult(rows)
        raise AssertionError(f"Unexpected inspection SQL: {sql}")


class FakeEngine:
    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection
        self.disposed = False

    def connect(self) -> "FakeEngine":
        return self

    def __enter__(self) -> FakeConnection:
        return self.connection

    def __exit__(self, *_args: object) -> bool:
        return False

    def dispose(self) -> None:
        self.disposed = True


def _catalog() -> Catalog:
    comment = USER_TABLE_COMMENT
    tables = (
        {"table_name": "users", "table_comment": comment},
        {"table_name": "orders", "table_comment": None},
        {"table_name": "products", "table_comment": None},
        {"table_name": "order_items", "table_comment": None},
    )
    columns = (
        _column("users", "id", 1, "bigint", "int8", "NO", None, "YES", "ALWAYS"),
        _column("orders", "user_id", 2, "bigint", "int8", "NO", None, "NO", None),
        _column("orders", "id", 1, "bigint", "int8", "NO", None, "YES", "ALWAYS"),
        _column("products", "id", 1, "bigint", "int8", "NO", None, "YES", "ALWAYS"),
        _column("order_items", "order_id", 2, "bigint", "int8", "NO", None, "NO", None),
        _column("order_items", "id", 1, "bigint", "int8", "NO", None, "YES", "ALWAYS"),
    )
    constraints = (
        _foreign_key("order_items", "order_items_order_fk", "orders", ["order_id"], ["id"], "c"),
        _foreign_key("orders", "orders_user_fk", "users", ["user_id"], ["id"], "r"),
        _foreign_key(
            "order_items",
            "order_items_product_fk",
            "products",
            ["product_id"],
            ["id"],
            "r",
        ),
        {
            "table_name": "users",
            "constraint_name": "users_email_not_blank",
            "constraint_type": "c",
            "definition": "CHECK ((DROP TABLE bookstore.orders))",
            "foreign_schema": None,
            "foreign_table": None,
            "columns": ["email"],
            "referenced_columns": None,
            "update_action": " ",
            "delete_action": " ",
        },
    )
    indexes = (
        {
            "table_name": "orders",
            "index_name": "orders_user_id_idx",
            "is_unique": False,
            "is_primary": False,
            "column_name": "user_id",
            "position": 1,
            "direction": "asc",
        },
    )
    return Catalog(
        tables=tuple(reversed(tables)),
        columns=tuple(reversed(columns)),
        constraints=tuple(reversed(constraints)),
        indexes=indexes,
    )


def _column(
    table: str,
    name: str,
    position: int,
    data_type: str,
    udt_name: str,
    nullable: str,
    default: str | None,
    identity: str,
    generation: str | None,
) -> dict[str, object]:
    return {
        "table_name": table,
        "column_name": name,
        "ordinal_position": position,
        "data_type": data_type,
        "udt_name": udt_name,
        "is_nullable": nullable,
        "column_default": default,
        "is_identity": identity,
        "identity_generation": generation,
        "is_generated": "NEVER",
        "column_comment": None,
    }


def _foreign_key(
    table: str,
    name: str,
    referenced: str,
    columns: list[str],
    referenced_columns: list[str],
    delete_action: str,
) -> dict[str, object]:
    return {
        "table_name": table,
        "constraint_name": name,
        "constraint_type": "f",
        "definition": f"FOREIGN KEY ({columns[0]}) REFERENCES bookstore.{referenced}(id)",
        "foreign_schema": "bookstore",
        "foreign_table": referenced,
        "columns": columns,
        "referenced_columns": referenced_columns,
        "update_action": "a",
        "delete_action": delete_action,
    }


def _responses(connection_rows: dict[str, list[Mapping[str, object]]]) -> FakeConnection:
    return FakeConnection(connection_rows)


def test_inspection_queries_do_not_contain_executable_comments() -> None:
    for sql in INSPECTION_QUERIES:
        assert sql.lstrip().upper().startswith("SELECT")
        assert "DROP TABLE" not in sql.upper()
        assert USER_TABLE_COMMENT not in sql


def test_snapshot_orders_relationships_and_keeps_comment_as_metadata() -> None:
    first = assemble_snapshot(_catalog())
    second = assemble_snapshot(_catalog())

    assert [table.name for table in first.tables] == [
        "order_items",
        "orders",
        "products",
        "users",
    ]
    users = next(table for table in first.tables if table.name == "users")
    assert users.comment == USER_TABLE_COMMENT
    assert users.columns[0].id == "bookstore.users.id"
    assert users.columns[0].identity == "always"
    check = next(item for item in users.constraints if item.name == "users_email_not_blank")
    assert check.check_expression == "CHECK ((DROP TABLE bookstore.orders))"
    dependency_ids = [item.id for item in first.dependencies]
    assert dependency_ids == [
        "bookstore.order_items.order_items_order_fk",
        "bookstore.order_items.order_items_product_fk",
        "bookstore.orders.orders_user_fk",
    ]
    orders_user = next(
        item for item in first.dependencies if item.constraint_name == "orders_user_fk"
    )
    assert orders_user.from_table == "bookstore.orders"
    assert orders_user.to_table == "bookstore.users"
    assert "orders" in [table.name for table in first.tables]
    assert first.fingerprint == second.fingerprint
    assert schema_fingerprint(first) == first.fingerprint
    serialized = first.model_dump_json()
    assert "secret-token" not in serialized
    assert "postgresql://" not in serialized


def test_source_list_hides_credentials_and_does_not_connect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(session_module, "create_engine", _fail_if_called)
    monkeypatch.setattr(session_module, "create_demo_engine", _fail_if_called)
    client = TestClient(create_app(_settings()))

    response = client.get("/api/v1/sources")

    assert response.status_code == 200
    body = response.json()
    assert body["sources"] == [
        {
            "id": BOOKSTORE_SOURCE_ID,
            "kind": "demo",
            "display_name": "Bookstore demo",
            "database_name": "schemapilot_bookstore",
            "schema_name": "bookstore",
            "configured": True,
            "access": "read_only",
        }
    ]
    assert "secret" not in response.text
    assert "postgresql" not in response.text


def test_unconfigured_inspection_fails_without_connecting(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(session_module, "create_engine", _fail_if_called)
    client = TestClient(create_app(_settings(demo_environment="")))

    listed = client.get("/api/v1/sources")
    schema = client.get("/api/v1/sources/bookstore-demo/schema")

    assert listed.json()["sources"][0]["configured"] is False
    assert schema.status_code == 409
    assert schema.json()["detail"] == {"error": "source_not_configured"}
    assert "secret" not in schema.text


def test_unknown_source_is_rejected() -> None:
    client = TestClient(create_app(_settings()))
    response = client.get("/api/v1/sources/production/schema")

    assert response.status_code == 404
    assert response.json()["detail"] == {"error": "unknown_source"}


def test_schema_route_uses_the_read_only_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = _responses(
        {
            "default_transaction_read_only": [{"value": "on"}],
            "current_database": [{"current_database": "schemapilot_bookstore"}],
            "obj_description": [
                {"table_name": "users", "table_comment": USER_TABLE_COMMENT},
                {"table_name": "orders", "table_comment": None},
            ],
            "information_schema.columns": [
                _column("users", "id", 1, "bigint", "int8", "NO", None, "YES", "ALWAYS"),
                _column("orders", "id", 1, "bigint", "int8", "NO", None, "YES", "ALWAYS"),
            ],
            "pg_constraint": [
                _foreign_key("orders", "orders_user_fk", "users", ["user_id"], ["id"], "r"),
            ],
            "pg_index": [],
        }
    )
    engine = FakeEngine(connection)

    def source_engine(_settings: Settings) -> FakeEngine:
        return engine

    monkeypatch.setattr(
        "app.services.schema_inspector.create_bookstore_source_engine",
        source_engine,
    )
    monkeypatch.setattr("app.db.session.create_demo_engine", _fail_if_called)
    monkeypatch.setattr("app.demo.bookstore.initialize_demo", _fail_if_called)
    monkeypatch.setattr("app.demo.bookstore.reset_demo", _fail_if_called)
    client = TestClient(create_app(_settings()))

    response = client.get("/api/v1/sources/bookstore-demo/schema")

    assert response.status_code == 200
    body = response.json()
    assert [table["name"] for table in body["tables"]] == ["orders", "users"]
    assert body["tables"][1]["comment"] == USER_TABLE_COMMENT
    assert engine.disposed is True
    assert connection.statements
    assert all(
        statement.lstrip().upper().startswith("SELECT") for statement in connection.statements
    )
    assert all(statement.strip() != USER_TABLE_COMMENT for statement in connection.statements)
    assert "secret-token" not in response.text
    assert "postgresql://" not in response.text


def test_unreachable_source_returns_a_safe_error(monkeypatch: pytest.MonkeyPatch) -> None:
    class BrokenEngine:
        def connect(self) -> None:
            raise OperationalError(
                "SELECT 1",
                {},
                Exception("password=secret-token postgresql://demo@127.0.0.1/schemapilot_bookstore"),
            )

        def dispose(self) -> None:
            return None

    monkeypatch.setattr(
        "app.services.schema_inspector.create_bookstore_source_engine",
        lambda _settings: BrokenEngine(),
    )
    client = TestClient(create_app(_settings()))

    response = client.get("/api/v1/sources/bookstore-demo/schema")

    assert response.status_code == 503
    assert response.json()["detail"] == {"error": "source_unavailable"}
    assert "secret-token" not in response.text
    assert "postgresql" not in response.text


def test_read_only_session_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = _responses({"default_transaction_read_only": [{"value": "off"}]})
    monkeypatch.setattr(
        "app.services.schema_inspector.create_bookstore_source_engine",
        lambda _settings: FakeEngine(connection),
    )
    client = TestClient(create_app(_settings()))

    response = client.get("/api/v1/sources/bookstore-demo/schema")

    assert response.status_code == 409
    assert response.json()["detail"] == {"error": "source_not_read_only"}
    assert len(connection.statements) == 1


def test_health_stays_independent_of_source_connectivity(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(session_module, "create_engine", _fail_if_called)
    client = TestClient(create_app(_settings()))

    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json()["database_connectivity"] == "not_checked"
