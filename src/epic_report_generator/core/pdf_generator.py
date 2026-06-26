"""PDF builder for landscape 16:9 Epic progress reports.

Thin orchestration over the Typst view layer: build the JSON view-model and
chart assets from ``ReportData`` (``report_view_model``), then compile the
bundled Typst templates to PDF bytes (``typst_renderer``). The public contract
is unchanged: ``generate_pdf(report) -> bytes``.
"""

from __future__ import annotations

import logging

from epic_report_generator.core.data_models import ReportData
from epic_report_generator.core.report_view_model import build_report
from epic_report_generator.core.typst_renderer import render_pdf

logger = logging.getLogger(__name__)


def generate_pdf(
    report: ReportData, icons: dict[str, bytes] | None = None
) -> bytes:
    """Build the full PDF report and return it as bytes.

    *icons* maps issue-type id → icon bytes (gathered by the caller from the
    Jira client's in-memory cache).  Only cached types get an ``icon`` path in
    the payload, and their SVGs are written into the Typst project so the
    templates can ``image()`` them.  ``None`` keeps the icon-free default path.
    """
    icons = icons or {}
    payload = build_report(report, icons=icons)
    logger.info(
        "Generating PDF via Typst: %d epic page(s), timeline=%s, dark_mode=%s",
        len(payload["pages"]),
        payload["timeline"]["chart"] is not None,
        report.config.dark_mode,
    )
    font_dir = getattr(report.config, "report_font_dir", "") or ""
    pdf = render_pdf(
        payload,
        extra_font_paths=[font_dir] if font_dir else None,
        icons=icons,
    )
    logger.info("PDF built: %d bytes", len(pdf))
    return pdf
