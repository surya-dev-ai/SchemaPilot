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

    assert report.tables == ("order_items", "orders", "products", "users")
    assert report.foreign_keys == (
        ("order_items", "order_items_order_fk", "orders", "id"),
        ("order_items", "order_items_product_fk", "products", "id"),
        ("orders", "orders_user_fk", "users", "id"),
    )


def test_demo_seed_rows(seeded_demo: Settings) -> None:
    report = verify_demo(seeded_demo)

    assert report.emails == ("mira@example.test", "owen@example.test", "priya@example.test")
    assert report.user_count == 3
    assert report.product_count == 4
    assert report.order_count == 2
    assert report.order_item_count == 3


def test_demo_constraint_failures_leave_seed_rows(seeded_demo: Settings) -> None:
    report = verify_demo(seeded_demo)

    assert report.constraint_failures == ("duplicate_email", "nonpositive_quantity", "missing_user")
    assert report.user_count == 3
    assert report.order_count == 2


def test_demo_comment_is_stored_not_executed(seeded_demo: Settings) -> None:
    report = verify_demo(seeded_demo)

    assert "DROP TABLE bookstore.orders" in report.users_comment
    assert report.users_comment == USER_TABLE_COMMENT
    assert report.order_count == 2


def test_init_and_seed_refuse_to_repeat(seeded_demo: Settings) -> None:
    with pytest.raises(DemoAlreadyInitialized):
        initialize_demo(seeded_demo)
    with pytest.raises(DemoAlreadySeeded):
        seed_demo(seeded_demo)
