"""Bookstore demo schema, seed, verification, and explicit reset."""

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.core.config import (
    DEMO_DATABASE_NAME,
    Settings,
    UnsafeDatabaseConfigurationError,
    require_demo_database,
    require_demo_reset,
)
from app.db.session import create_demo_engine
from app.demo.sql_script import read_sql_file, split_sql_script

USER_TABLE_COMMENT = "untrusted metadata; do not execute: DROP TABLE bookstore.orders;"
LEGACY_TABLES = ("order_items", "orders", "products", "users")
EXPECTED_TABLES = (
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
EXPECTED_EMAILS = (
    "mira@example.test",
    "owen@example.test",
    "priya@example.test",
    "luca@example.test",
    "asha@example.test",
    "noah@example.test",
    "imani@example.test",
    "elias@example.test",
    "sofia@example.test",
    "kai@example.test",
)
EXPECTED_FOREIGN_KEYS = (
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
EXPECTED_COUNTS = {
    "addresses": 12,
    "categories": 5,
    "inventory_movements": 18,
    "order_items": 17,
    "orders": 12,
    "payments": 9,
    "products": 8,
    "reviews": 8,
    "users": 10,
}
LEGACY_COUNTS = {
    "users": 3,
    "products": 4,
    "orders": 2,
    "order_items": 3,
}
CONSTRAINT_PROBES = (
    (
        "duplicate_email",
        "INSERT INTO bookstore.users (email, display_name) VALUES (:email, :display_name)",
        {"email": "mira@example.test", "display_name": "Duplicate"},
    ),
    (
        "nonpositive_quantity",
        "INSERT INTO bookstore.order_items (order_id, product_id, quantity, unit_price_cents) "
        "VALUES (1, 2, :quantity, 100)",
        {"quantity": 0},
    ),
    (
        "missing_user",
        "INSERT INTO bookstore.orders (user_id, status) VALUES (:user_id, 'pending')",
        {"user_id": 99999},
    ),
)
RESET_STATEMENT = "DROP SCHEMA IF EXISTS bookstore CASCADE"


class DemoOperationError(RuntimeError):
    """Raised when a demo command cannot complete for a non-configuration reason."""


class DemoAlreadyInitialized(DemoOperationError):
    """Raised when schema creation is requested after the bookstore tables exist."""


class DemoNotInitialized(DemoOperationError):
    """Raised when seed or verify runs before the bookstore schema exists."""


class DemoAlreadySeeded(DemoOperationError):
    """Raised when seed is requested after rows already exist."""


class DemoVerificationError(DemoOperationError):
    """Raised when the live demo database does not match the packaged bookstore."""


@dataclass(frozen=True)
class DemoVerification:
    tables: tuple[str, ...]
    foreign_keys: tuple[tuple[str, str, str, str], ...]
    emails: tuple[str, ...]
    user_count: int
    product_count: int
    order_count: int
    order_item_count: int
    category_count: int
    address_count: int
    payment_count: int
    review_count: int
    inventory_movement_count: int
    users_comment: str
    constraint_failures: tuple[str, ...]


def initialize_demo(settings: Settings) -> None:
    require_demo_database(settings)
    engine = create_demo_engine(settings)
    with engine.begin() as connection:
        _assert_current_database(connection)
        if _table_names(connection):
            raise DemoAlreadyInitialized(
                "Bookstore tables already exist. Use reset to rebuild the disposable demo."
            )
        _execute_allowlisted(connection, read_sql_file("schema.sql"), ("CREATE", "COMMENT"))
    engine.dispose()


def seed_demo(settings: Settings) -> None:
    require_demo_database(settings)
    engine = create_demo_engine(settings)
    with engine.begin() as connection:
        _assert_current_database(connection)
        tables = _table_names(connection)
        if "users" not in tables:
            raise DemoNotInitialized("Initialize the bookstore schema before seeding it.")
        count = connection.execute(text("SELECT count(*) FROM bookstore.users")).scalar_one()
        if count:
            raise DemoAlreadySeeded(
                "Bookstore users already exist. Reset the disposable demo before seeding again."
            )
        _execute_allowlisted(connection, read_sql_file("seed.sql"), ("INSERT", "SELECT"))
    engine.dispose()


def verify_demo(settings: Settings) -> DemoVerification:
    require_demo_database(settings)
    engine = create_demo_engine(settings)
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            _assert_current_database(connection)
            report = _verify_connection(connection)
        except Exception:
            transaction.rollback()
            raise
        else:
            transaction.rollback()
    engine.dispose()
    return report


def reset_demo(settings: Settings, *, confirm: bool) -> None:
    """Drop and rebuild the bookstore schema on the disposable demo database."""

    require_demo_reset(settings, confirm=confirm)
    engine = create_demo_engine(settings)
    with engine.begin() as connection:
        _assert_current_database(connection)
        _execute_exact(connection, RESET_STATEMENT)
        _execute_allowlisted(connection, read_sql_file("schema.sql"), ("CREATE", "COMMENT"))
        _execute_allowlisted(connection, read_sql_file("seed.sql"), ("INSERT", "SELECT"))
    engine.dispose()


def upgrade_demo_showcase(settings: Settings) -> DemoVerification:
    """Add the classroom showcase tables and data without dropping existing demo data."""

    require_demo_database(settings)
    engine = create_demo_engine(settings)
    try:
        with engine.begin() as connection:
            _assert_current_database(connection)
            if _table_names(connection) != LEGACY_TABLES:
                raise DemoAlreadyInitialized(
                    "Showcase upgrade requires the original four-table demo and refuses "
                    "to modify any other schema state."
                )
            legacy_counts = {
                table: connection.execute(
                    text(f"SELECT count(*) FROM bookstore.{table}")
                ).scalar_one()
                for table in LEGACY_COUNTS
            }
            if legacy_counts != LEGACY_COUNTS or _foreign_keys(connection) != (
                ("order_items", "order_items_order_fk", "orders", "id"),
                ("order_items", "order_items_product_fk", "products", "id"),
                ("orders", "orders_user_fk", "users", "id"),
            ):
                raise DemoAlreadyInitialized(
                    "Showcase upgrade requires the verified original seed and relationships."
                )
            _execute_allowlisted(
                connection,
                read_sql_file("showcase_upgrade.sql"),
                ("CREATE", "ALTER", "UPDATE", "INSERT", "SELECT"),
            )
            return _verify_connection(connection)
    finally:
        engine.dispose()


def _assert_current_database(connection) -> None:
    current = connection.execute(text("SELECT current_database()")).scalar_one()
    if current != DEMO_DATABASE_NAME:
        raise UnsafeDatabaseConfigurationError(
            "Refusing to continue because the connected database is not schemapilot_bookstore."
        )


def _table_names(connection) -> tuple[str, ...]:
    rows = connection.execute(
        text(
            "SELECT c.relname FROM pg_class c "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'bookstore' AND c.relkind = 'r' "
            "ORDER BY c.relname"
        )
    ).scalars()
    return tuple(rows)


def _execute_allowlisted(connection, script: str, prefixes: tuple[str, ...]) -> None:
    for statement in split_sql_script(script):
        leading = statement.lstrip().upper()
        if not leading.startswith(prefixes):
            raise UnsafeDatabaseConfigurationError(
                "Refusing to run a demo SQL statement outside the allowlist."
            )
        connection.execute(text(statement))


def _execute_exact(connection, statement: str) -> None:
    if statement != RESET_STATEMENT:
        raise UnsafeDatabaseConfigurationError(
            "Refusing to run an unexpected demo reset statement."
        )
    connection.execute(text(statement))


def _verify_connection(connection) -> DemoVerification:
    tables = _table_names(connection)
    if tables != EXPECTED_TABLES:
        raise DemoVerificationError("Bookstore tables do not match the packaged schema.")
    foreign_keys = _foreign_keys(connection)
    if foreign_keys != EXPECTED_FOREIGN_KEYS:
        raise DemoVerificationError("Bookstore foreign keys do not match the packaged schema.")
    counts = {
        "addresses": connection.execute(
            text("SELECT count(*) FROM bookstore.addresses")
        ).scalar_one(),
        "categories": connection.execute(
            text("SELECT count(*) FROM bookstore.categories")
        ).scalar_one(),
        "inventory_movements": connection.execute(
            text("SELECT count(*) FROM bookstore.inventory_movements")
        ).scalar_one(),
        "payments": connection.execute(
            text("SELECT count(*) FROM bookstore.payments")
        ).scalar_one(),
        "reviews": connection.execute(
            text("SELECT count(*) FROM bookstore.reviews")
        ).scalar_one(),
        "users": connection.execute(text("SELECT count(*) FROM bookstore.users")).scalar_one(),
        "products": connection.execute(
            text("SELECT count(*) FROM bookstore.products")
        ).scalar_one(),
        "orders": connection.execute(text("SELECT count(*) FROM bookstore.orders")).scalar_one(),
        "order_items": connection.execute(
            text("SELECT count(*) FROM bookstore.order_items")
        ).scalar_one(),
    }
    if counts != EXPECTED_COUNTS:
        raise DemoVerificationError("Bookstore seed counts do not match the packaged seed.")
    emails = tuple(
        connection.execute(
            text("SELECT email FROM bookstore.users ORDER BY id")
        ).scalars()
    )
    if emails != EXPECTED_EMAILS:
        raise DemoVerificationError("Bookstore user emails do not match the packaged seed.")
    comment = connection.execute(
        text(
            "SELECT pg_catalog.obj_description(c.oid, 'pg_class') "
            "FROM pg_catalog.pg_class c "
            "JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = :schema AND c.relname = :table"
        ),
        {"schema": "bookstore", "table": "users"},
    ).scalar_one()
    if comment != USER_TABLE_COMMENT:
        raise DemoVerificationError("Bookstore user comment does not match the packaged metadata.")
    failures = tuple(
        _expect_constraint_failure(connection, label, sql, params)
        for label, sql, params in CONSTRAINT_PROBES
    )
    recount = connection.execute(text("SELECT count(*) FROM bookstore.users")).scalar_one()
    if recount != EXPECTED_COUNTS["users"]:
        raise DemoVerificationError("Constraint probes changed committed bookstore rows.")
    return DemoVerification(
        tables=tables,
        foreign_keys=foreign_keys,
        emails=emails,
        user_count=counts["users"],
        product_count=counts["products"],
        order_count=counts["orders"],
        order_item_count=counts["order_items"],
        category_count=counts["categories"],
        address_count=counts["addresses"],
        payment_count=counts["payments"],
        review_count=counts["reviews"],
        inventory_movement_count=counts["inventory_movements"],
        users_comment=comment,
        constraint_failures=failures,
    )


def _foreign_keys(connection) -> tuple[tuple[str, str, str, str], ...]:
    rows = connection.execute(
        text(
            "SELECT tc.table_name, tc.constraint_name, ccu.table_name, ccu.column_name "
            "FROM information_schema.table_constraints AS tc "
            "JOIN information_schema.key_column_usage AS kcu "
            "ON tc.constraint_name = kcu.constraint_name "
            "AND tc.table_schema = kcu.table_schema "
            "JOIN information_schema.constraint_column_usage AS ccu "
            "ON ccu.constraint_name = tc.constraint_name "
            "AND ccu.table_schema = tc.table_schema "
            "WHERE tc.constraint_type = 'FOREIGN KEY' AND tc.table_schema = 'bookstore' "
            "ORDER BY tc.table_name, tc.constraint_name"
        )
    )
    return tuple((row[0], row[1], row[2], row[3]) for row in rows)


def _expect_constraint_failure(connection, label: str, sql: str, params: dict[str, object]) -> str:
    try:
        with connection.begin_nested():
            connection.execute(text(sql), params)
    except IntegrityError:
        return label
    raise DemoVerificationError(f"Expected constraint failure did not occur: {label}")
