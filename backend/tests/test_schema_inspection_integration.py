"""Live bookstore inspection. Skipped when the disposable demo database is unreachable."""

import pytest
from app.core.config import Settings
from app.demo.bookstore import USER_TABLE_COMMENT
from app.main import create_app
from app.services.schema_inspector import inspect_source
from fastapi.testclient import TestClient

pytestmark = pytest.mark.integration


def test_live_bookstore_snapshot_lists_tables_and_relationships(seeded_demo: Settings) -> None:
    first = inspect_source(seeded_demo, "bookstore-demo")
    second = inspect_source(seeded_demo, "bookstore-demo")

    assert [table.name for table in first.tables] == [
        "addresses",
        "categories",
        "inventory_movements",
        "order_items",
        "orders",
        "payments",
        "products",
        "reviews",
        "users",
    ]
    assert len(first.dependencies) == 12
    categories = next(table for table in first.tables if table.name == "categories")
    assert any(
        item.name == "categories_parent_fk" and item.referenced_table == "categories"
        for item in categories.constraints
    )
    products = next(table for table in first.tables if table.name == "products")
    assert any(
        item.name == "products_category_fk" and item.referenced_table == "categories"
        for item in products.constraints
    )
    orders = next(table for table in first.tables if table.name == "orders")
    user_fk = next(item for item in orders.constraints if item.name == "orders_user_fk")
    assert user_fk.kind == "foreign_key"
    assert user_fk.referenced_table == "users"
    assert user_fk.referenced_columns == ["id"]
    assert user_fk.on_delete == "restrict"
    items = next(table for table in first.tables if table.name == "order_items")
    item_fks = {item.name: item for item in items.constraints if item.kind == "foreign_key"}
    assert item_fks["order_items_order_fk"].referenced_table == "orders"
    assert item_fks["order_items_order_fk"].on_delete == "cascade"
    assert item_fks["order_items_product_fk"].referenced_table == "products"
    users = next(table for table in first.tables if table.name == "users")
    user_id = next(column for column in users.columns if column.name == "id")
    assert user_id.identity == "always"
    assert user_id.nullable is False
    assert users.comment == USER_TABLE_COMMENT
    assert "DROP TABLE bookstore.orders" in (users.comment or "")
    assert any(table.name == "orders" for table in first.tables)
    assert first.fingerprint == second.fingerprint
    serialized = first.model_dump_json()
    assert "postgresql://" not in serialized
    assert "change_me" not in serialized


def test_live_schema_route_hides_the_connection_string(seeded_demo: Settings) -> None:
    client = TestClient(create_app(seeded_demo))

    response = client.get("/api/v1/sources/bookstore-demo/schema")

    assert response.status_code == 200
    assert response.json()["schema_name"] == "bookstore"
    assert response.json()["database_name"] == "schemapilot_bookstore"
    assert "postgresql" not in response.text
    assert "password" not in response.text.lower()
