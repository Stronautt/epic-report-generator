"""ReportLab PDF builder for landscape 16:9 Epic progress reports."""

from __future__ import annotations

import io
import logging
from datetime import date
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    Image,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from epic_report_generator.core.chart_generator import generate_epic_chart
from epic_report_generator.core.data_models import EpicData, EpicMetrics, ReportConfig, ReportData

logger = logging.getLogger(__name__)

_MONTHS_FULL = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]
_MONTHS_ABBR = [
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
]


def _fmt_date(d: date, fmt: str) -> str:
    """Format a date using English month names regardless of system locale.

    Supports ``%B`` (full month) and ``%b`` (abbreviated month); all other
    format codes are delegated to :py:meth:`date.strftime`.
    """
    result = fmt.replace("%B", _MONTHS_FULL[d.month - 1])
    result = result.replace("%b", _MONTHS_ABBR[d.month - 1])
    return d.strftime(result)


# Page dimensions: landscape 16:9
PAGE_W = 406 * mm  # ~1152 pt
PAGE_H = 228.4 * mm  # ~648 pt
MARGIN = 18 * mm

# ---------------------------------------------------------------------------
# Colour palettes
# ---------------------------------------------------------------------------

_LIGHT_PALETTE = {
    "accent": colors.HexColor("#0052CC"),
    "text": colors.HexColor("#172B4D"),
    "muted": colors.HexColor("#6B778C"),
    "bg": colors.white,
    "surface": colors.HexColor("#F4F5F7"),
    "green": colors.HexColor("#36B37E"),
    "yellow": colors.HexColor("#FFAB00"),
    "red": colors.HexColor("#DE350B"),
    "row_alt": colors.HexColor("#F8F9FA"),
    "grid": colors.HexColor("#DFE1E6"),
    "header_text": colors.white,
}

_DARK_PALETTE = {
    "accent": colors.HexColor("#2979FF"),
    "text": colors.HexColor("#E0E0E0"),
    "muted": colors.HexColor("#90A4AE"),
    "bg": colors.HexColor("#1E1E1E"),
    "surface": colors.HexColor("#263238"),
    "green": colors.HexColor("#66BB6A"),
    "yellow": colors.HexColor("#FFA726"),
    "red": colors.HexColor("#EF5350"),
    "row_alt": colors.HexColor("#252525"),
    "grid": colors.HexColor("#37474F"),
    "header_text": colors.white,
}


def generate_pdf(report: ReportData) -> bytes:
    """Build the full PDF report and return it as bytes."""
    dark = report.config.dark_mode
    pal = _DARK_PALETTE if dark else _LIGHT_PALETTE

    logger.info(
        "Generating PDF: %d epic(s), dark_mode=%s, title=%r",
        len(report.epics), dark, report.config.title,
    )

    buf = io.BytesIO()
    doc = _create_doc(buf, pal)
    styles = _build_styles(pal)

    story: list[Any] = []

    # Page 1 — Title
    logger.debug("Building title page")
    _add_title_page(story, report.config, styles, pal)

    # Page 2+ — Summary table
    logger.debug("Building summary table for %d epic(s)", len(report.epics))
    story.append(PageBreak())
    _add_summary_table(story, report, styles, pal)

    # Pages 3+ — Individual Epic pages
    for i, (epic, metrics) in enumerate(zip(report.epics, report.metrics), 1):
        logger.debug("Building epic page %d/%d: %s", i, len(report.epics), epic.key)
        story.append(PageBreak())
        _add_epic_page(story, epic, metrics, styles, pal, dark)

    doc.build(story)
    result = buf.getvalue()
    logger.info("PDF built: %d bytes, %d pages", len(result), 2 + len(report.epics))
    return result


# -- document setup -----------------------------------------------------------


def _create_doc(buf: io.BytesIO, pal: dict[str, Any]) -> BaseDocTemplate:
    doc = BaseDocTemplate(
        buf,
        pagesize=(PAGE_W, PAGE_H),
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=MARGIN,
        bottomMargin=MARGIN,
    )
    frame = Frame(MARGIN, MARGIN, PAGE_W - 2 * MARGIN, PAGE_H - 2 * MARGIN, id="main")

    def _on_page(canvas: Any, doc: Any) -> None:
        canvas.saveState()
        canvas.setFillColor(pal["bg"])
        canvas.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
        canvas.restoreState()

    doc.addPageTemplates([PageTemplate(id="default", frames=[frame], onPage=_on_page)])
    return doc


def _build_styles(pal: dict[str, Any]) -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "ReportTitle", parent=base["Title"],
            fontSize=36, leading=44, textColor=pal["text"], alignment=TA_CENTER,
        ),
        "subtitle": ParagraphStyle(
            "Subtitle", parent=base["Normal"],
            fontSize=18, leading=24, textColor=pal["muted"], alignment=TA_CENTER,
        ),
        "heading": ParagraphStyle(
            "SectionHeading", parent=base["Heading1"],
            fontSize=22, leading=28, textColor=pal["text"], spaceAfter=8,
        ),
        "body": ParagraphStyle(
            "Body", parent=base["Normal"],
            fontSize=12, leading=16, textColor=pal["text"],
        ),
        "small": ParagraphStyle(
            "Small", parent=base["Normal"],
            fontSize=9, leading=12, textColor=pal["muted"],
        ),
        "cell": ParagraphStyle(
            "Cell", parent=base["Normal"],
            fontSize=9, leading=12, textColor=pal["text"],
        ),
        "cell_right": ParagraphStyle(
            "CellRight", parent=base["Normal"],
            fontSize=9, leading=12, textColor=pal["text"], alignment=TA_RIGHT,
        ),
        "cell_header": ParagraphStyle(
            "CellHeader", parent=base["Normal"],
            fontSize=9, leading=12, textColor=pal["header_text"],
        ),
        "confidential": ParagraphStyle(
            "Confidential", parent=base["Normal"],
            fontSize=9, leading=12, textColor=pal["red"], alignment=TA_CENTER,
        ),
        "section_heading": ParagraphStyle(
            "SectionHeading2", parent=base["Normal"],
            fontSize=14, leading=18, textColor=pal["text"],
        ),
        "metric_label": ParagraphStyle(
            "MetricLabel", parent=base["Normal"],
            fontSize=10, leading=14, textColor=pal["muted"],
        ),
        "metric_value": ParagraphStyle(
            "MetricValue", parent=base["Normal"],
            fontSize=12, leading=16, textColor=pal["text"],
        ),
    }


# -- Page 1: Title -----------------------------------------------------------


def _add_title_page(
    story: list[Any], config: ReportConfig, styles: dict[str, ParagraphStyle],
    pal: dict[str, Any],
) -> None:
    story.append(Spacer(1, 60 * mm))
    story.append(Paragraph(config.title, styles["title"]))
    story.append(Spacer(1, 8 * mm))

    if config.project_display_name:
        story.append(Paragraph(config.project_display_name, styles["subtitle"]))
        story.append(Spacer(1, 4 * mm))

    story.append(
        Paragraph(_fmt_date(config.report_date, "%B %d, %Y"), styles["subtitle"])
    )

    if config.author:
        story.append(Spacer(1, 3 * mm))
        story.append(Paragraph(f"Prepared by {config.author}", styles["subtitle"]))

    if config.confidential and config.company_name:
        story.append(Spacer(1, 30 * mm))
        notice = (
            f"CONFIDENTIAL — This document is the property of {config.company_name} "
            "and is intended solely for the use of the intended recipient(s). "
            "Unauthorized distribution is prohibited."
        )
        story.append(Paragraph(notice, styles["confidential"]))


# -- Page 2: Summary table ---------------------------------------------------


def _add_summary_table(
    story: list[Any], report: ReportData, styles: dict[str, ParagraphStyle],
    pal: dict[str, Any],
) -> None:
    story.append(Paragraph("Epic Progress Summary", styles["heading"]))
    story.append(Spacer(1, 4 * mm))

    headers = [
        "Epic Key", "Summary", "Progress", "Status",
        "Total", "Done", "Unest.", "Total SP", "Done SP", "Assignee",
    ]
    header_row = [Paragraph(f"<b>{h}</b>", styles["cell_header"]) for h in headers]

    data_rows = []
    for epic, metrics in zip(report.epics, report.metrics):
        summary_text = epic.summary[:80] + ("..." if len(epic.summary) > 80 else "")

        data_rows.append([
            Paragraph(epic.key, styles["cell"]),
            Paragraph(summary_text, styles["cell"]),
            _progress_bar_para(metrics.progress, styles, pal),
            Paragraph(epic.status, styles["cell"]),
            Paragraph(str(metrics.total_issues), styles["cell_right"]),
            Paragraph(str(metrics.completed_issues), styles["cell_right"]),
            Paragraph(str(metrics.unestimated_issues), styles["cell_right"]),
            Paragraph(f"{metrics.total_sp:.0f}", styles["cell_right"]),
            Paragraph(f"{metrics.completed_sp:.0f}", styles["cell_right"]),
            Paragraph(epic.assignee or "Unassigned", styles["cell"]),
        ])

    table_data = [header_row] + data_rows

    avail_w = PAGE_W - 2 * MARGIN
    col_widths = [
        avail_w * 0.08,  # Key
        avail_w * 0.22,  # Summary
        avail_w * 0.12,  # Progress
        avail_w * 0.09,  # Status
        avail_w * 0.06,  # Total
        avail_w * 0.06,  # Done
        avail_w * 0.06,  # Unest
        avail_w * 0.08,  # Total SP
        avail_w * 0.08,  # Done SP
        avail_w * 0.12,  # Assignee
    ]

    tbl = Table(table_data, colWidths=col_widths, repeatRows=1)
    style_cmds: list[Any] = [
        ("BACKGROUND", (0, 0), (-1, 0), pal["accent"]),
        ("TEXTCOLOR", (0, 0), (-1, 0), pal["header_text"]),
        ("FONTSIZE", (0, 0), (-1, 0), 9),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
        ("TOPPADDING", (0, 0), (-1, 0), 6),
        ("GRID", (0, 0), (-1, -1), 0.25, pal["grid"]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 1), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 4),
    ]
    # Alternating row colours
    for i in range(1, len(table_data)):
        if i % 2 == 0:
            style_cmds.append(("BACKGROUND", (0, i), (-1, i), pal["row_alt"]))

    tbl.setStyle(TableStyle(style_cmds))
    story.append(tbl)


def _progress_bar_para(
    pct: float, styles: dict[str, ParagraphStyle], pal: dict[str, Any],
) -> Paragraph:
    """Return a coloured text representation of the progress bar."""
    if pct >= 75:
        colour = pal["green"]
    elif pct >= 25:
        colour = pal["yellow"]
    else:
        colour = pal["red"]
    hex_colour = colour.hexval() if hasattr(colour, "hexval") else str(colour)
    bar_len = max(1, int(pct / 5))
    bar = "\u2588" * bar_len + "\u2591" * (20 - bar_len)
    return Paragraph(
        f'<font color="{hex_colour}" size="8">{bar}</font> '
        f'<font size="9"><b>{pct:.0f}%</b></font>',
        styles["cell"],
    )


# -- Pages 3+: Individual Epic -----------------------------------------------


def _add_epic_page(
    story: list[Any],
    epic: EpicData,
    metrics: EpicMetrics,
    styles: dict[str, ParagraphStyle],
    pal: dict[str, Any],
    dark: bool,
) -> None:
    accent_hex = pal["accent"].hexval() if hasattr(pal["accent"], "hexval") else "#0052CC"
    # Header
    story.append(
        Paragraph(
            f'<font color="{accent_hex}">{epic.key}</font> — {epic.summary}',
            styles["heading"],
        )
    )
    story.append(
        Paragraph(f"Status: <b>{epic.status}</b>", styles["body"])
    )
    story.append(Spacer(1, 4 * mm))

    # Two-column layout: chart on left, summary on right
    chart_img = _build_chart_image(metrics, dark)
    summary_tbl = _build_summary_box(metrics, styles, pal)

    avail_w = PAGE_W - 2 * MARGIN
    chart_w = avail_w * 0.62
    summary_w = avail_w * 0.35
    gap = avail_w * 0.03

    cols = []
    if chart_img:
        cols.append(chart_img)
    else:
        cols.append(Paragraph("<i>No chart data available</i>", styles["small"]))
    cols.append("")  # gap
    cols.append(summary_tbl)

    layout = Table(
        [cols],
        colWidths=[chart_w, gap, summary_w],
    )
    layout.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    story.append(layout)


def _build_chart_image(metrics: EpicMetrics, dark: bool) -> Image | None:
    png = generate_epic_chart(metrics, dpi=150, dark=dark)
    if not png:
        return None
    buf = io.BytesIO(png)
    return Image(buf, width=240 * mm, height=120 * mm, kind="proportional")


def _build_summary_box(
    metrics: EpicMetrics, styles: dict[str, ParagraphStyle], pal: dict[str, Any],
) -> Table:
    """Build the right-side summary metrics table."""
    rows: list[list[Any]] = [
        [Paragraph("<b>Summary</b>", styles["section_heading"]), ""],
        [Paragraph("Total Issues", styles["metric_label"]),
         Paragraph(str(metrics.total_issues), styles["metric_value"])],
        [Paragraph("Completed", styles["metric_label"]),
         Paragraph(str(metrics.completed_issues), styles["metric_value"])],
        [Paragraph("Open", styles["metric_label"]),
         Paragraph(str(metrics.open_issues), styles["metric_value"])],
        [Paragraph("Unestimated", styles["metric_label"]),
         Paragraph(str(metrics.unestimated_issues), styles["metric_value"])],
        [Paragraph("Total SP", styles["metric_label"]),
         Paragraph(f"{metrics.total_sp:.0f}", styles["metric_value"])],
        [Paragraph("Done SP", styles["metric_label"]),
         Paragraph(f"{metrics.completed_sp:.0f}", styles["metric_value"])],
        [Paragraph("Remaining SP", styles["metric_label"]),
         Paragraph(f"{metrics.remaining_sp:.0f}", styles["metric_value"])],
        [Paragraph("Avg Cycle Time", styles["metric_label"]),
         Paragraph(
             f"{metrics.avg_cycle_time_days:.1f} days" if metrics.avg_cycle_time_days else "N/A",
             styles["metric_value"],
         )],
        [Paragraph("<b>Additional</b>", styles["section_heading"]), ""],
        [Paragraph("Velocity (4wk)", styles["metric_label"]),
         Paragraph(
             f"{metrics.velocity_sp_per_week:.1f} SP/wk" if metrics.velocity_sp_per_week else "N/A",
             styles["metric_value"],
         )],
        [Paragraph("Scope Change", styles["metric_label"]),
         Paragraph(
             f"{metrics.scope_change_pct:.0f}%" if metrics.scope_change_pct is not None else "N/A",
             styles["metric_value"],
         )],
        [Paragraph("Blocked", styles["metric_label"]),
         Paragraph(str(metrics.blocked_issues), styles["metric_value"])],
        [Paragraph("Forecast", styles["metric_label"]),
         Paragraph(
             _fmt_date(metrics.forecast_date, "%b %d, %Y") if metrics.forecast_date else "N/A",
             styles["metric_value"],
         )],
    ]

    tbl = Table(rows, colWidths=["55%", "45%"])
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), pal["surface"]),
        ("BACKGROUND", (0, 9), (-1, 9), pal["surface"]),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, pal["accent"]),
        ("LINEBELOW", (0, 9), (-1, 9), 0.5, pal["accent"]),
    ]))
    return tbl
