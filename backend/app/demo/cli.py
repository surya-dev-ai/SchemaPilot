"""Commands for the disposable bookstore demo. Nothing here runs at API startup."""

import argparse
import sys

from app.core.config import UnsafeDatabaseConfigurationError, get_settings
from app.demo.bookstore import (
    DemoOperationError,
    initialize_demo,
    reset_demo,
    seed_demo,
    upgrade_demo_showcase,
    verify_demo,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Manage the disposable bookstore demo and its additive classroom showcase."
    )
    parser.add_argument(
        "command",
        choices=("init", "seed", "verify", "reset", "showcase-upgrade"),
    )
    parser.add_argument(
        "--confirm-demo-reset",
        action="store_true",
        help="Required with reset. Drops schema bookstore on schemapilot_bookstore.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "reset" and not args.confirm_demo_reset:
        print(
            "Refusing to reset without --confirm-demo-reset. "
            "This drops schema bookstore on the disposable demo database.",
            file=sys.stderr,
        )
        return 2
    try:
        settings = get_settings()
        if args.command == "init":
            initialize_demo(settings)
            print("Initialized the bookstore schema on schemapilot_bookstore.")
        elif args.command == "seed":
            seed_demo(settings)
            print("Seeded the bookstore demo.")
        elif args.command == "verify":
            report = verify_demo(settings)
            print(
                "Bookstore demo verified: "
                f"{report.user_count} users, {report.product_count} products, "
                f"{report.order_count} orders, {report.order_item_count} order items, "
                f"{report.category_count} categories, {report.address_count} addresses, "
                f"{report.payment_count} payments, {report.review_count} reviews, "
                f"{report.inventory_movement_count} inventory movements; "
                f"{len(report.foreign_keys)} relationships."
            )
        elif args.command == "showcase-upgrade":
            report = upgrade_demo_showcase(settings)
            print(
                "Added the bookstore classroom showcase without resetting existing data: "
                f"{len(report.tables)} tables, {len(report.foreign_keys)} relationships, "
                f"{report.user_count} users, {report.product_count} products, "
                f"{report.order_count} orders, {report.order_item_count} order items."
            )
        else:
            reset_demo(settings, confirm=True)
            print("Reset the disposable bookstore demo.")
    except (UnsafeDatabaseConfigurationError, DemoOperationError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 0
