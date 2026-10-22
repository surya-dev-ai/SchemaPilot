"""Commands for the disposable bookstore demo. Nothing here runs at API startup."""

import argparse
import sys

from app.core.config import UnsafeDatabaseConfigurationError, get_settings
from app.demo.bookstore import (
    DemoOperationError,
    initialize_demo,
    reset_demo,
    seed_demo,
    verify_demo,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Initialize, seed, verify, or reset the disposable bookstore demo."
    )
    parser.add_argument("command", choices=("init", "seed", "verify", "reset"))
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
                f"{report.order_count} orders, {report.order_item_count} order items."
            )
        else:
            reset_demo(settings, confirm=True)
            print("Reset the disposable bookstore demo.")
    except (UnsafeDatabaseConfigurationError, DemoOperationError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 0
