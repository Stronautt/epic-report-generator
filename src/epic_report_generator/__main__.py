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
    parser.add_argument(
        "--selftest",
        action="store_true",
        help="Run a headless smoke test of the packaged bundle and exit.",
    )

    args, remaining = parser.parse_known_args()

    if args.selftest:
        return _selftest()

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


def _selftest() -> int:
    """Headless smoke test of the packaged bundle.

    Verifies the size-trimmed/stripped binary still works end to end:
    the canary Qt frameworks load (``QtPdf`` for preview, ``QtNetwork`` for the
    OAuth avatar), the ``qt-material`` chrome renders through the ``qsvg`` plugin
    (both themes applied + an SVG rendered to a pixmap), and the stripped Typst
    compiler still produces a PDF.  Prints ``SELFTEST OK`` and returns 0 on
    success, 1 on any failure.

    A display is required: CI runs this under ``xvfb`` (Linux) or the native
    platform (macOS/Windows); locally set ``QT_QPA_PLATFORM=offscreen``.
    """
    import logging
    import os
    import tempfile

    logging.disable(logging.CRITICAL)
    try:
        # Canary imports — prove the trimmed Qt frameworks still load.
        from PySide6.QtGui import QPixmap
        from PySide6.QtNetwork import QNetworkAccessManager  # noqa: F401
        from PySide6.QtPdf import QPdfDocument  # noqa: F401
        from PySide6.QtWidgets import QApplication
        from qt_material import apply_stylesheet

        app = QApplication.instance() or QApplication(["selftest"])

        # qt-material chrome is drawn from SVG icons via the qsvg plugin.
        for theme in ("light_blue.xml", "dark_blue.xml"):
            apply_stylesheet(app, theme=theme)

        # Render an SVG through the qsvg image plugin — the real QtSvg canary.
        svg = (
            b'<svg xmlns="http://www.w3.org/2000/svg" width="8" height="8">'
            b'<rect width="8" height="8" fill="#3f51b5"/></svg>'
        )
        with tempfile.NamedTemporaryFile(suffix=".svg", delete=False) as fh:
            fh.write(svg)
            svg_path = fh.name
        try:
            pixmap = QPixmap(svg_path)
        finally:
            os.unlink(svg_path)
        if pixmap.isNull():
            raise RuntimeError("qsvg image plugin missing: SVG did not render")

        # Build a minimal PDF — proves the stripped Typst binary still runs.
        from datetime import date

        from epic_report_generator.core.data_models import ReportConfig, ReportData
        from epic_report_generator.core.pdf_generator import generate_pdf

        cfg = ReportConfig(title="Self Test", report_date=date(2024, 1, 1))
        pdf = generate_pdf(ReportData(config=cfg))
        if pdf[:5] != b"%PDF-":
            raise RuntimeError("Typst render did not produce a PDF")
    except Exception as exc:  # noqa: BLE001 — selftest reports any failure as exit 1
        import traceback

        print(f"SELFTEST FAILED: {exc}", file=sys.stderr)
        traceback.print_exc()
        return 1

    print("SELFTEST OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
