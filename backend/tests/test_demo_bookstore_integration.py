"""Live bookstore checks. Skipped when the disposable demo database is unreachable."""

import pytest
from app.core.config import Settings
from app.demo.bookstore import (
    USER_TABLE_COMMENT,
    DemoAlreadyInitialized,
    DemoAlreadySeeded,
    initialize_demo,
    seed_demo,
    verify_demo,
)

pytestmark = pytest.mark.integration


def test_demo_schema_tables_and_relationships(seeded_demo: Settings) -> None:
    report = verify_demo(seeded_demo)

    assert report.tables == (
        "addresses",
        "categories",
        "inventory_movements",
        "order_items",
        "orders",
        "payments",
        "products",
        "reviews",
        "users",
    )
    assert report.foreign_keys == (
        ("addresses", "addresses_user_fk", "users", "id"),
        ("categories", "categories_parent_fk", "categories", "id"),
        ("inventory_movements", "inventory_movements_order_item_fk", "order_items", "id"),
        ("inventory_movements", "inventory_movements_product_fk", "products", "id"),
        ("order_items", "order_items_order_fk", "orders", "id"),
        ("order_items", "order_items_product_fk", "products", "id"),
        ("orders", "orders_shipping_address_fk", "addresses", "id"),
        ("orders", "orders_user_fk", "users", "id"),
        ("payments", "payments_order_fk", "orders", "id"),
        ("products", "products_category_fk", "categories", "id"),
        ("reviews", "reviews_product_fk", "products", "id"),
        ("reviews", "reviews_user_fk", "users", "id"),
    )


def test_demo_seed_rows(seeded_demo: Settings) -> None:
    report = verify_demo(seeded_demo)

    assert len(report.emails) == report.user_count == 10
    assert report.emails[0:3] == (
        "mira@example.test",
        "owen@example.test",
        "priya@example.test",
    )
    assert report.product_count == 8
    assert report.order_count == 12
    assert report.order_item_count == 17
    assert report.category_count == 5
    assert report.address_count == 12
    assert report.payment_count == 9
    assert report.review_count == 8
    assert report.inventory_movement_count == 18


def test_demo_constraint_failures_leave_seed_rows(seeded_demo: Settings) -> None:
    report = verify_demo(seeded_demo)

    assert report.constraint_failures == ("duplicate_email", "nonpositive_quantity", "missing_user")
    assert report.user_count == 10
    assert report.order_count == 12


def test_demo_comment_is_stored_not_executed(seeded_demo: Settings) -> None:
    report = verify_demo(seeded_demo)

    assert "DROP TABLE bookstore.orders" in report.users_comment
    assert report.users_comment == USER_TABLE_COMMENT
    assert report.order_count == 12


def test_init_and_seed_refuse_to_repeat(seeded_demo: Settings) -> None:
    with pytest.raises(DemoAlreadyInitialized):
        initialize_demo(seeded_demo)
    with pytest.raises(DemoAlreadySeeded):
        seed_demo(seeded_demo)
