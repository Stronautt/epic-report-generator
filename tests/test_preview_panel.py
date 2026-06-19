"""Smoke tests for the QPdfView-based PreviewPanel.

Confirms the panel builds, accepts a parsed document, and detaches it on clear
without leaking the document/buffer.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from PySide6.QtGui import QColor, QPalette

from epic_report_generator.core.data_models import ReportConfig, ReportData
from epic_report_generator.core.pdf_generator import generate_pdf
from epic_report_generator.ui.preview_panel import (
    _PDF_AVAILABLE,
    _PREVIEW_BG_DARK,
    _PREVIEW_BG_LIGHT,
    PreviewPanel,
)


def _smoke_pdf() -> bytes:
    """A tiny but valid PDF (title page only) to feed the preview."""
    return generate_pdf(ReportData(config=ReportConfig(title="Smoke Test")))


def test_preview_panel_builds_with_qpdfview(qtbot) -> None:
    panel = PreviewPanel(MagicMock(), MagicMock())
    qtbot.addWidget(panel)
    assert _PDF_AVAILABLE  # dev environment bundles QtPdfWidgets
    assert panel._pdf_view is not None

    # The backdrop (area around pages) is QPdfView-painted from its palette, so
    # the theme colour must land on the palette, not a stylesheet.
    panel.set_dark(True)
    assert panel._pdf_view.palette().color(QPalette.ColorRole.Dark) == QColor(
        _PREVIEW_BG_DARK
    )
    panel.set_dark(False)
    assert panel._pdf_view.palette().color(QPalette.ColorRole.Dark) == QColor(
        _PREVIEW_BG_LIGHT
    )


def test_show_document_and_clear_detaches(qtbot) -> None:
    panel = PreviewPanel(MagicMock(), MagicMock())
    qtbot.addWidget(panel)

    panel._pdf_bytes = _smoke_pdf()
    panel._show_document()
    doc = panel._pdf_view.document()
    assert doc is not None
    assert doc.pageCount() >= 1

    # clear_preview must detach the document from the view and dispose it.
    panel.clear_preview()
    assert panel._pdf_view.document() is None
    assert panel._pdf_doc is None
    assert panel._pdf_buf is None
