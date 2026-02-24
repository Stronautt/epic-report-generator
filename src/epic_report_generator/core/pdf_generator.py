"""ReportLab PDF builder for landscape 16:9 Epic progress reports."""

from __future__ import annotations

import io
import logging
from datetime import date, timedelta
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
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

from epic_report_generator.core.chart_generator import (
    generate_epic_chart,
    generate_timeline_chart,
)
from epic_report_generator.core.data_models import (
    EpicData,
    EpicMetrics,
    MilestoneItem,
    ReportConfig,
    ReportData,
    ReportItem,
    SprintInfo,
    TimelineItem,
)

logger = logging.getLogger(__name__)

_MONTHS_FULL = [
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
]
_MONTHS_ABBR = [
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
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
    "label_header": colors.HexColor("#E8EDFC"),
    "label_tag_bg": colors.HexColor("#DEEBFF"),
    "label_tag_text": colors.HexColor("#0747A6"),
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
    "label_header": colors.HexColor("#1A3352"),
    "label_tag_bg": colors.HexColor("#0D2137"),
    "label_tag_text": colors.HexColor("#82B1FF"),
}


def generate_pdf(report: ReportData) -> bytes:
    """Build the full PDF report and return it as bytes."""
    dark = report.config.dark_mode
    pal = _DARK_PALETTE if dark else _LIGHT_PALETTE

    logger.info(
        "Generating PDF: %d epic(s), dark_mode=%s, title=%r",
        len(report.epics),
        dark,
        report.config.title,
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

    # Timeline page (after summary, before epic details)
    logger.debug("Building timeline page")
    story.append(PageBreak())
    _add_timeline_page(story, report, styles, pal, dark)

    # Pages 3+ — Individual Epic pages
    show_additional = report.config.show_additional_metrics
    if report.resolved_items:
        for i, (item, epic, metrics) in enumerate(report.resolved_items, 1):
            if (
                item.kind == "label"
                and report.config.expand_label_details
                and item.key in report.label_source_epics
            ):
                label_tag = item.display_name or item.key
                for src_epic, src_metrics in report.label_source_epics[item.key]:
                    logger.debug(
                        "Building expanded label page: %s (%s)", src_epic.key, label_tag
                    )
                    story.append(PageBreak())
                    _add_epic_page(
                        story,
                        src_epic,
                        src_metrics,
                        styles,
                        pal,
                        dark,
                        label_tag=label_tag,
                        show_additional=show_additional,
                    )
            else:
                logger.debug(
                    "Building epic page %d/%d: %s",
                    i,
                    len(report.resolved_items),
                    epic.key,
                )
                story.append(PageBreak())
                _add_epic_page(
                    story,
                    epic,
                    metrics,
                    styles,
                    pal,
                    dark,
                    item,
                    show_additional=show_additional,
                )
    else:
        for i, (epic, metrics) in enumerate(zip(report.epics, report.metrics), 1):
            logger.debug("Building epic page %d/%d: %s", i, len(report.epics), epic.key)
            story.append(PageBreak())
            _add_epic_page(
                story, epic, metrics, styles, pal, dark, show_additional=show_additional
            )

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
            "ReportTitle",
            parent=base["Title"],
            fontSize=36,
            leading=44,
            textColor=pal["text"],
            alignment=TA_CENTER,
        ),
        "subtitle": ParagraphStyle(
            "Subtitle",
            parent=base["Normal"],
            fontSize=18,
            leading=24,
            textColor=pal["muted"],
            alignment=TA_CENTER,
        ),
        "heading": ParagraphStyle(
            "SectionHeading",
            parent=base["Heading1"],
            fontSize=22,
            leading=28,
            textColor=pal["text"],
            spaceAfter=8,
        ),
        "body": ParagraphStyle(
            "Body",
            parent=base["Normal"],
            fontSize=12,
            leading=16,
            textColor=pal["text"],
        ),
        "small": ParagraphStyle(
            "Small",
            parent=base["Normal"],
            fontSize=9,
            leading=12,
            textColor=pal["muted"],
        ),
        "cell": ParagraphStyle(
            "Cell",
            parent=base["Normal"],
            fontSize=9,
            leading=12,
            textColor=pal["text"],
        ),
        "cell_right": ParagraphStyle(
            "CellRight",
            parent=base["Normal"],
            fontSize=9,
            leading=12,
            textColor=pal["text"],
            alignment=TA_RIGHT,
        ),
        "cell_header": ParagraphStyle(
            "CellHeader",
            parent=base["Normal"],
            fontSize=9,
            leading=12,
            textColor=pal["header_text"],
        ),
        "confidential": ParagraphStyle(
            "Confidential",
            parent=base["Normal"],
            fontSize=9,
            leading=12,
            textColor=pal["red"],
            alignment=TA_CENTER,
        ),
        "section_heading": ParagraphStyle(
            "SectionHeading2",
            parent=base["Normal"],
            fontSize=14,
            leading=18,
            textColor=pal["text"],
        ),
        "metric_label": ParagraphStyle(
            "MetricLabel",
            parent=base["Normal"],
            fontSize=10,
            leading=14,
            textColor=pal["muted"],
        ),
        "metric_value": ParagraphStyle(
            "MetricValue",
            parent=base["Normal"],
            fontSize=12,
            leading=16,
            textColor=pal["text"],
        ),
    }


def _aggregate_status(epic: EpicData) -> str:
    """Derive an aggregate status from an epic's children.

    * All children "To Do" → ``"To Do"``
    * All children "Done" → ``"Done"``
    * Any mix (or any "In Progress") → ``"In Progress"``
    """
    if not epic.children:
        return epic.status
    categories = {c.status_category for c in epic.children}
    if categories == {"Done"}:
        return "Done"
    if categories == {"To Do"}:
        return "To Do"
    return "In Progress"


# -- Page 1: Title -----------------------------------------------------------


def _add_title_page(
    story: list[Any],
    config: ReportConfig,
    styles: dict[str, ParagraphStyle],
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
    story: list[Any],
    report: ReportData,
    styles: dict[str, ParagraphStyle],
    pal: dict[str, Any],
) -> None:
    story.append(Paragraph("Epic Progress Summary", styles["heading"]))
    story.append(Spacer(1, 4 * mm))

    # Determine estimation unit from the first epic's metrics (default "SP")
    unit = "SP"
    if report.metrics:
        unit = report.metrics[0].estimation_unit

    headers = [
        "Key",
        "Summary",
        "Progress",
        "Scope Certainty",
        "Status",
        "Total",
        "Done",
        "Unest.",
        f"Total {unit}",
        f"Done {unit}",
    ]
    header_row = [Paragraph(f"<b>{h}</b>", styles["cell_header"]) for h in headers]

    data_rows = []
    group_header_indices: list[int] = []  # row indices (1-based) that are group headers
    num_cols = len(headers)

    def _epic_row(
        epic: EpicData, metrics: EpicMetrics, key_text: str = ""
    ) -> list[Any]:
        """Build a single data row for an epic."""
        kt = key_text or epic.key
        summary_text = epic.summary[:80] + ("..." if len(epic.summary) > 80 else "")
        return [
            Paragraph(kt, styles["cell"]),
            Paragraph(summary_text, styles["cell"]),
            _progress_bar_para(metrics.progress, styles, pal),
            _certainty_para(metrics.scope_certainty, styles, pal),
            Paragraph(_aggregate_status(epic), styles["cell"]),
            Paragraph(str(metrics.total_issues), styles["cell_right"]),
            Paragraph(str(metrics.completed_issues), styles["cell_right"]),
            Paragraph(str(metrics.unestimated_issues), styles["cell_right"]),
            Paragraph(f"{metrics.total_sp:.0f}", styles["cell_right"]),
            Paragraph(f"{metrics.completed_sp:.0f}", styles["cell_right"]),
        ]

    # Use resolved_items if available, otherwise fall back to epics/metrics
    if report.resolved_items:
        for item, epic, metrics in report.resolved_items:
            if item.kind == "label" and item.key in report.label_source_epics:
                # Group header row for the label
                label_name = item.display_name or item.key
                header_cell = Paragraph(
                    f'<b>{label_name}</b> <font size="7">({len(report.label_source_epics[item.key])} epics)</font>',
                    styles["cell"],
                )
                group_row = [header_cell] + [""] * (num_cols - 1)
                data_rows.append(group_row)
                group_header_indices.append(
                    len(data_rows)
                )  # 1-based index in table_data

                # Individual source epic rows
                for src_epic, src_metrics in report.label_source_epics[item.key]:
                    data_rows.append(_epic_row(src_epic, src_metrics))
            else:
                key_text = (
                    epic.key if item.kind == "epic" else item.display_name or item.key
                )
                data_rows.append(_epic_row(epic, metrics, key_text))
    else:
        for epic, metrics in zip(report.epics, report.metrics):
            data_rows.append(_epic_row(epic, metrics))

    table_data = [header_row] + data_rows

    avail_w = PAGE_W - 2 * MARGIN
    # Stretch priority: 1=fixed cols, 2=progress, 3=summary
    col_widths = [
        avail_w * 0.08,  # Key (fixed)
        avail_w * 0.24,  # Summary (3rd priority — largest stretch)
        avail_w * 0.15,  # Progress (2nd priority)
        avail_w * 0.07,  # Certainty (fixed)
        avail_w * 0.08,  # Status (fixed)
        avail_w * 0.06,  # Total (fixed)
        avail_w * 0.06,  # Done (fixed)
        avail_w * 0.06,  # Unest (fixed)
        avail_w * 0.08,  # Total SP (fixed)
        avail_w * 0.08,  # Done SP (fixed)
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

    # Group header row styling (span + background)
    for gi in group_header_indices:
        style_cmds.append(("SPAN", (0, gi), (-1, gi)))
        style_cmds.append(("BACKGROUND", (0, gi), (-1, gi), pal["label_header"]))
        style_cmds.append(("TOPPADDING", (0, gi), (-1, gi), 6))
        style_cmds.append(("BOTTOMPADDING", (0, gi), (-1, gi), 6))

    # Alternating row colours (skip group header rows)
    alt = False
    for i in range(1, len(table_data)):
        if i in group_header_indices:
            alt = False
            continue
        if alt:
            style_cmds.append(("BACKGROUND", (0, i), (-1, i), pal["row_alt"]))
        alt = not alt

    tbl.setStyle(TableStyle(style_cmds))
    story.append(tbl)


def _progress_bar_para(
    pct: float,
    styles: dict[str, ParagraphStyle],
    pal: dict[str, Any],
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
    bar = "█" * bar_len + "░" * (20 - bar_len)
    return Paragraph(
        f'<font color="{hex_colour}" size="8">{bar}</font> '
        f'<font size="9"><b>{pct:.0f}%</b></font>',
        styles["cell"],
    )


def _certainty_para(
    certainty: str | None,
    styles: dict[str, ParagraphStyle],
    pal: dict[str, Any],
) -> Paragraph:
    """Return a coloured text cell for scope certainty."""
    if not certainty:
        return Paragraph("--", styles["cell"])
    colour_map = {"High": pal["green"], "Medium": pal["yellow"], "Low": pal["red"]}
    colour = colour_map.get(certainty, pal["muted"])
    hex_colour = colour.hexval() if hasattr(colour, "hexval") else str(colour)
    return Paragraph(
        f'<font color="{hex_colour}"><b>{certainty}</b></font>', styles["cell"]
    )


# -- Timeline page ------------------------------------------------------------


def _add_timeline_page(
    story: list[Any],
    report: ReportData,
    styles: dict[str, ParagraphStyle],
    pal: dict[str, Any],
    dark: bool,
) -> None:
    """Add a Gantt-style timeline page after the summary table."""
    story.append(Paragraph("Timeline", styles["heading"]))
    story.append(Spacer(1, 4 * mm))

    # Build timeline items from resolved_items or epics/metrics
    timeline_items: list[TimelineItem] = []
    show_children = report.config.show_children_on_timeline

    def _add_epic_timeline(
        epic: EpicData,
        metrics: EpicMetrics,
        name: str,
        group: str = "",
    ) -> None:
        """Append a timeline item for an epic and optionally its children."""
        timeline_items.append(
            TimelineItem(
                name=name,
                start_date=epic.start_date,
                end_date=epic.due_date,
                scope_certainty=metrics.scope_certainty,
                progress=metrics.progress,
                group=group,
            )
        )
        if show_children and epic.children:
            for child in epic.children:
                if child.start_date and child.due_date:
                    timeline_items.append(
                        TimelineItem(
                            name=f"  {child.key}",
                            start_date=child.start_date,
                            end_date=child.due_date,
                            scope_certainty=None,
                            progress=100.0 if child.status_category == "Done" else 0.0,
                            is_child=True,
                            group=group,
                        )
                    )

    if report.resolved_items:
        for item, epic, metrics in report.resolved_items:
            if item.kind == "label" and item.key in report.label_source_epics:
                label_group = item.display_name or item.key
                # Expand label into individual source epics for the timeline
                for src_epic, src_metrics in report.label_source_epics[item.key]:
                    _add_epic_timeline(
                        src_epic, src_metrics, src_epic.key, group=label_group
                    )
            else:
                name = item.display_name or epic.key
                _add_epic_timeline(epic, metrics, name)
    else:
        for epic, metrics in zip(report.epics, report.metrics):
            _add_epic_timeline(epic, metrics, epic.key)

    # Collect date range from items for filtering fix versions
    item_dates: list[date] = []
    for ti in timeline_items:
        if ti.start_date:
            item_dates.append(ti.start_date)
        if ti.end_date:
            item_dates.append(ti.end_date)

    # Build milestones from fix_version_dates, filtering to +-7 days of item date range
    milestones: list[MilestoneItem] = []
    if item_dates:
        range_start = report.config.timeline_hard_start or (
            min(item_dates) - timedelta(days=7)
        )
        range_end = report.config.timeline_hard_end or (
            max(item_dates) + timedelta(days=7)
        )
        for name, release_date in report.fix_version_dates.items():
            if release_date and range_start <= release_date <= range_end:
                milestones.append(MilestoneItem(name=name, release_date=release_date))
    else:
        for name, release_date in report.fix_version_dates.items():
            if release_date:
                milestones.append(MilestoneItem(name=name, release_date=release_date))

    # Available space: full page width, height minus heading + spacer (~22mm)
    avail_w = PAGE_W - 2 * MARGIN
    avail_h = PAGE_H - 2 * MARGIN - 22 * mm

    png = generate_timeline_chart(
        timeline_items,
        milestones,
        report.sprints,
        dpi=150,
        dark=dark,
        xlim_start=report.config.timeline_hard_start,
        xlim_end=report.config.timeline_hard_end,
    )
    if png:
        buf = io.BytesIO(png)
        img = Image(buf, width=avail_w, height=avail_h, kind="proportional")
        story.append(img)
    else:
        story.append(Paragraph("<i>No timeline data available</i>", styles["small"]))


# -- Pages 3+: Individual Epic -----------------------------------------------


def _add_epic_page(
    story: list[Any],
    epic: EpicData,
    metrics: EpicMetrics,
    styles: dict[str, ParagraphStyle],
    pal: dict[str, Any],
    dark: bool,
    item: ReportItem | None = None,
    label_tag: str = "",
    show_additional: bool = True,
) -> None:
    accent_hex = (
        pal["accent"].hexval() if hasattr(pal["accent"], "hexval") else "#0052CC"
    )
    # Header — use label name instead of synthetic key for label items
    if item and item.kind == "label":
        display_key = item.display_name or item.key
    else:
        display_key = epic.key

    # Build heading with optional label tag pill
    tag_html = ""
    if label_tag:
        tag_bg = (
            pal["label_tag_bg"].hexval()
            if hasattr(pal["label_tag_bg"], "hexval")
            else "#DEEBFF"
        )
        tag_fg = (
            pal["label_tag_text"].hexval()
            if hasattr(pal["label_tag_text"], "hexval")
            else "#0747A6"
        )
        tag_html = (
            f'<font backColor="{tag_bg}" color="{tag_fg}" size="9">'
            f"&nbsp;{label_tag}&nbsp;</font>&nbsp;&nbsp;"
        )

    # Avoid repeating the display name when it matches the summary
    if display_key == epic.summary:
        heading_text = f'{tag_html}<font color="{accent_hex}">{display_key}</font>'
    else:
        heading_text = f'{tag_html}<font color="{accent_hex}">{display_key}</font> — {epic.summary}'
    story.append(Paragraph(heading_text, styles["heading"]))
    status = _aggregate_status(epic)
    story.append(Paragraph(f"Status: <b>{status}</b>", styles["body"]))
    story.append(Spacer(1, 4 * mm))

    # Two-column layout: chart on left, summary on right
    chart_img = _build_chart_image(metrics, dark)
    summary_tbl = _build_summary_box(
        metrics, styles, pal, show_additional=show_additional
    )

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
    layout.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    story.append(layout)


def _build_chart_image(metrics: EpicMetrics, dark: bool) -> Image | None:
    png = generate_epic_chart(metrics, dpi=150, dark=dark)
    if not png:
        return None
    buf = io.BytesIO(png)
    return Image(buf, width=240 * mm, height=120 * mm, kind="proportional")


def _build_summary_box(
    metrics: EpicMetrics,
    styles: dict[str, ParagraphStyle],
    pal: dict[str, Any],
    *,
    show_additional: bool = True,
) -> Table:
    """Build the right-side summary metrics table."""
    unit = metrics.estimation_unit
    rows: list[list[Any]] = [
        [Paragraph("<b>Summary</b>", styles["section_heading"]), ""],
        [
            Paragraph("Total Issues", styles["metric_label"]),
            Paragraph(str(metrics.total_issues), styles["metric_value"]),
        ],
        [
            Paragraph("Completed", styles["metric_label"]),
            Paragraph(str(metrics.completed_issues), styles["metric_value"]),
        ],
        [
            Paragraph("Open", styles["metric_label"]),
            Paragraph(str(metrics.open_issues), styles["metric_value"]),
        ],
        [
            Paragraph("Unestimated", styles["metric_label"]),
            Paragraph(str(metrics.unestimated_issues), styles["metric_value"]),
        ],
        [
            Paragraph(f"Total {unit}", styles["metric_label"]),
            Paragraph(f"{metrics.total_sp:.0f}", styles["metric_value"]),
        ],
        [
            Paragraph(f"Done {unit}", styles["metric_label"]),
            Paragraph(f"{metrics.completed_sp:.0f}", styles["metric_value"]),
        ],
        [
            Paragraph(f"Remaining {unit}", styles["metric_label"]),
            Paragraph(f"{metrics.remaining_sp:.0f}", styles["metric_value"]),
        ],
    ]

    style_cmds: list[Any] = [
        ("BACKGROUND", (0, 0), (-1, 0), pal["surface"]),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, pal["accent"]),
    ]

    if show_additional:
        additional_header_idx = len(rows)
        rows.extend(
            [
                [Paragraph("<b>Additional</b>", styles["section_heading"]), ""],
                [
                    Paragraph("Avg Cycle Time", styles["metric_label"]),
                    Paragraph(
                        (
                            f"{metrics.avg_cycle_time_days:.1f} days"
                            if metrics.avg_cycle_time_days
                            else "N/A"
                        ),
                        styles["metric_value"],
                    ),
                ],
                [
                    Paragraph("Velocity (4wk)", styles["metric_label"]),
                    Paragraph(
                        (
                            f"{metrics.velocity_sp_per_week:.1f} {unit}/wk"
                            if metrics.velocity_sp_per_week
                            else "N/A"
                        ),
                        styles["metric_value"],
                    ),
                ],
                [
                    Paragraph("Scope Change", styles["metric_label"]),
                    Paragraph(
                        (
                            f"{metrics.scope_change_pct:.0f}%"
                            if metrics.scope_change_pct is not None
                            else "N/A"
                        ),
                        styles["metric_value"],
                    ),
                ],
                [
                    Paragraph("Blocked", styles["metric_label"]),
                    Paragraph(str(metrics.blocked_issues), styles["metric_value"]),
                ],
                [
                    Paragraph("Forecast", styles["metric_label"]),
                    Paragraph(
                        (
                            _fmt_date(metrics.forecast_date, "%b %d, %Y")
                            if metrics.forecast_date
                            else "N/A"
                        ),
                        styles["metric_value"],
                    ),
                ],
            ]
        )
        style_cmds.append(
            (
                "BACKGROUND",
                (0, additional_header_idx),
                (-1, additional_header_idx),
                pal["surface"],
            )
        )
        style_cmds.append(
            (
                "LINEBELOW",
                (0, additional_header_idx),
                (-1, additional_header_idx),
                0.5,
                pal["accent"],
            )
        )

    tbl = Table(rows, colWidths=["55%", "45%"])
    tbl.setStyle(TableStyle(style_cmds))
    return tbl
