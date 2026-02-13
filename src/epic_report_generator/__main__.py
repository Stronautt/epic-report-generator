"""Entry point for ``python -m epic_report_generator``."""

from __future__ import annotations

import argparse
import logging
import sys


def main() -> int:
    """Launch the Epic Report Generator application."""
    parser = argparse.ArgumentParser(
        prog="epic-report-generator",
        description="Generate PDF Epic progress reports from Jira Cloud.",
    )
    parser.add_argument(
        "--install-desktop",
        action="store_true",
        help="Install a desktop launcher shortcut and exit.",
    )
    parser.add_argument(
        "--uninstall-desktop",
        action="store_true",
        help="Remove the desktop launcher shortcut and exit.",
    )

    args, remaining = parser.parse_known_args()

    if args.install_desktop or args.uninstall_desktop:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        )
        from epic_report_generator.desktop import install_desktop, uninstall_desktop

        if args.install_desktop:
            install_desktop()
        else:
            uninstall_desktop()
        return 0

    from epic_report_generator.app import run_app

    return run_app([sys.argv[0], *remaining])


if __name__ == "__main__":
    raise SystemExit(main())
