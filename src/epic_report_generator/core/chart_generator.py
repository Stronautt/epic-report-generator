"""Matplotlib chart generation replicating the Jira Epic Report style."""

from __future__ import annotations

import io
import logging
from datetime import date, timedelta
from typing import Any

from epic_report_generator.core.data_models import (
    EpicMetrics,
    MilestoneItem,
    SprintInfo,
    TimelineItem,
)

import matplotlib  # isort: skip

matplotlib.use("Agg")

import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.ticker as mticker  # noqa: E402

logger = logging.getLogger(__name__)


def _d2n(d: date) -> float:
    """Convert a single date to a matplotlib float ordinal."""
    val: Any = mdates.date2num(d)
    return float(val)


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


class _EnglishDateFormatter(mticker.Formatter):
    """Date formatter that always uses English abbreviated month names.

    Avoids locale-dependent ``%b`` which produces non-Latin characters on
    systems with e.g. Ukrainian or Russian locale — characters that
    matplotlib's default font may not render correctly.
    """

    def __call__(self, x: float, pos: int | None = None) -> str:
        dt = mdates.num2date(x)
        return f"{_MONTHS_ABBR[dt.month - 1]} {dt.day:02d}"


# -- Light theme colour palette ------------------------------------------------
_LIGHT = {
    "total_sp": "#e0e0e0",
    "done_sp": "#4c9aff",
    "cum_issues": "#0747a6",
    "cum_unest": "#8b6914",
    "weekend": "#f4f5f7",
    "label_color": "#505f79",
    "grid": "#dfe1e6",
    "bg": "#ffffff",
    "face": "#ffffff",
    "legend_face": "#ffffff",
    # Timeline-specific
    "sprint_text": "#5243AA",
    "sprint_pill_bg": "#EAE6FF",
    "sprint_pill_edge": "#C0B6F2",
    "sprint_band": "#6554C0",
    "milestone_text": "#7A5C00",
    "milestone_pill_bg": "#FFF7E6",
    "milestone_pill_edge": "#F5CD47",
    "major_date_color": "#172B4D",
    "child_bar": "#B3BAC5",
    "bar_text_light": "#ffffff",
    "bar_text_dark": "#172B4D",
    "group_band": "#F0F4FF",
    "group_label": "#5E6C84",
}

# -- Dark theme colour palette -------------------------------------------------
_DARK = {
    "total_sp": "#455a64",
    "done_sp": "#2979ff",
    "cum_issues": "#82b1ff",
    "cum_unest": "#ffb74d",
    "weekend": "#263238",
    "label_color": "#b0bec5",
    "grid": "#37474f",
    "bg": "#1e1e1e",
    "face": "#1e1e1e",
    "legend_face": "#263238",
    # Timeline-specific
    "sprint_text": "#B39DDB",
    "sprint_pill_bg": "#311B92",
    "sprint_pill_edge": "#5C42A6",
    "sprint_band": "#7E57C2",
    "milestone_text": "#FFD54F",
    "milestone_pill_bg": "#3E2723",
    "milestone_pill_edge": "#8D6E63",
    "major_date_color": "#ECEFF1",
    "child_bar": "#616161",
    "bar_text_light": "#ffffff",
    "bar_text_dark": "#E0E0E0",
    "group_band": "#1E2A3A",
    "group_label": "#90A4AE",
}


def generate_epic_chart(
    metrics: EpicMetrics, *, dpi: int = 150, dark: bool = False
) -> bytes | None:
    """Render a Jira-style trend chart and return the image as PNG bytes.

    Returns ``None`` if there is no time-series data to plot.
    """
    if not metrics.dates:
        logger.debug("No time-series data — skipping chart")
        return None

    logger.debug(
        "Rendering chart: %d data points, dark=%s, dpi=%d",
        len(metrics.dates),
        dark,
        dpi,
    )
    pal = _DARK if dark else _LIGHT

    fig, ax1 = plt.subplots(figsize=(7.2, 3.6), dpi=dpi)
    fig.patch.set_facecolor(pal["face"])
    ax1.set_facecolor(pal["bg"])
    ax2 = ax1.twinx()

    dates = metrics.dates

    # Weekend bands
    _draw_weekend_bands(ax1, dates, pal["weekend"])

    unit = metrics.estimation_unit  # "SP" or "Days"

    # Total estimate area (gray)
    date_nums = [_d2n(d) for d in dates]
    ax1.fill_between(
        date_nums,
        metrics.total_sp_over_time,
        color=pal["total_sp"],
        alpha=0.7,
        label=f"Total {unit}",
        step="post",
    )

    # Completed estimate area (blue)
    ax1.fill_between(
        date_nums,
        metrics.completed_sp_over_time,
        color=pal["done_sp"],
        alpha=0.7,
        label=f"Completed {unit}",
        step="post",
    )

    # Cumulative issues (dark blue step line — right axis)
    ax2.step(
        date_nums,
        metrics.cumulative_issues,
        where="post",
        color=pal["cum_issues"],
        linewidth=1.5,
        label="Cumulative Issues",
    )

    # Cumulative unestimated (brown step line — right axis)
    ax2.step(
        date_nums,
        metrics.cumulative_unestimated,
        where="post",
        color=pal["cum_unest"],
        linewidth=1.5,
        linestyle="--",
        label="Unestimated Issues",
    )

    # Axes formatting
    ax1.set_ylabel(unit, fontsize=8, color=pal["label_color"])
    ax2.set_ylabel("Issues", fontsize=8, color=pal["label_color"])
    ax1.xaxis.set_major_formatter(_EnglishDateFormatter())
    ax1.xaxis.set_major_locator(mdates.AutoDateLocator(minticks=4, maxticks=10))
    fig.autofmt_xdate(rotation=30, ha="right")

    ax1.tick_params(labelsize=7, colors=pal["label_color"])
    ax2.tick_params(labelsize=7, colors=pal["label_color"])
    ax1.set_xlim(_d2n(dates[0]), _d2n(dates[-1]))
    ax1.set_ylim(bottom=0)
    ax2.set_ylim(bottom=0)

    for spine in (*ax1.spines.values(), *ax2.spines.values()):
        spine.set_color(pal["grid"])

    # Combined legend
    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    legend = ax1.legend(
        lines1 + lines2,
        labels1 + labels2,
        fontsize=6,
        loc="upper left",
        framealpha=0.9,
        facecolor=pal["legend_face"],
    )
    for text in legend.get_texts():
        text.set_color(pal["label_color"])

    ax1.grid(axis="y", linewidth=0.3, color=pal["grid"])
    ax1.set_axisbelow(True)
    fig.tight_layout()

    buf = io.BytesIO()
    fig.savefig(
        buf,
        format="png",
        dpi=dpi,
        bbox_inches="tight",
        facecolor=fig.get_facecolor(),
        edgecolor="none",
    )
    plt.close(fig)
    buf.seek(0)
    data = buf.read()
    logger.debug("Chart rendered: %d bytes", len(data))
    return data


class _MonthFormatter(mticker.Formatter):
    """Format dates as abbreviated month name (e.g. 'Jan', 'Feb')."""

    def __call__(self, x: float, pos: int | None = None) -> str:
        dt = mdates.num2date(x)
        return _MONTHS_ABBR[dt.month - 1]


class _QuarterFormatter(mticker.Formatter):
    """Format dates as 'Q1', 'Q2', etc."""

    def __call__(self, x: float, pos: int | None = None) -> str:
        dt = mdates.num2date(x)
        q = (dt.month - 1) // 3 + 1
        return f"Q{q}"


def generate_timeline_chart(
    items: list[TimelineItem],
    milestones: list[MilestoneItem] | None = None,
    sprints: list[SprintInfo] | None = None,
    *,
    dpi: int = 150,
    dark: bool = False,
    max_height_inches: float = 7.0,
    xlim_start: date | None = None,
    xlim_end: date | None = None,
) -> bytes | None:
    """Render a horizontal Gantt-style timeline chart and return PNG bytes.

    Returns ``None`` if no items have date ranges to display.
    The chart height is capped at *max_height_inches* so it fits on a single
    PDF page; bar thickness scales down when there are many items.
    """
    if not items:
        logger.debug("No timeline items — skipping chart")
        return None

    pal = _DARK if dark else _LIGHT
    milestones = milestones or []
    sprints = sprints or []

    # Certainty colour mapping
    certainty_colors = {
        "High": "#36B37E" if not dark else "#66BB6A",
        "Medium": "#FFAB00" if not dark else "#FFA726",
        "Low": "#DE350B" if not dark else "#EF5350",
    }
    default_bar_color = pal["done_sp"]

    # Scale figure height to item count but cap to fit one page
    n = len(items)
    natural_height = max(2.5, n * 0.4)
    fig_height = min(natural_height, max_height_inches)
    epic_bar_height = min(0.6, (fig_height / max(n, 1)) * 0.8)
    child_bar_height = epic_bar_height * 0.55
    epic_font = max(5.5, min(7.5, epic_bar_height * 12))
    child_font = max(4.5, min(6.0, child_bar_height * 12))

    # Match figure aspect ratio to the landscape 16:9 PDF available space
    # so proportional scaling fills the entire page width.
    fig_width = fig_height * 2.2
    fig, ax = plt.subplots(figsize=(fig_width, fig_height), dpi=dpi)
    fig.patch.set_facecolor(pal["face"])
    ax.set_facecolor(pal["bg"])

    all_dates: list[date] = []
    y_labels: list[str] = []
    bar_drawn = False

    for i, item in enumerate(items):
        y_labels.append(item.name)
        if item.start_date and item.end_date:
            full_duration = max((item.end_date - item.start_date).days, 1)
            bar_left = _d2n(item.start_date)

            is_child = item.is_child
            h = child_bar_height if is_child else epic_bar_height
            fsize = child_font if is_child else epic_font
            fweight = "normal" if is_child else "bold"

            if is_child:
                color = pal["child_bar"]
            else:
                color = certainty_colors.get(
                    item.scope_certainty or "", default_bar_color
                )

            # Light bar (total scope) + dark bar (completed portion)
            ax.barh(
                i,
                full_duration,
                left=bar_left,
                height=h,
                color=color,
                alpha=0.25,
                edgecolor="none",
            )
            done_duration = full_duration * (item.progress / 100.0)
            if done_duration > 0:
                ax.barh(
                    i,
                    done_duration,
                    left=bar_left,
                    height=h,
                    color=color,
                    alpha=0.85,
                    edgecolor="none",
                )

            # Adaptive text: dark text on light/short bars, white on dark bars
            text_color = pal["bar_text_light"]
            if is_child and item.progress < 50:
                text_color = pal["bar_text_dark"]

            # Centre text on the visible portion of the bar when clamped
            vis_left = bar_left
            vis_right = bar_left + full_duration
            if xlim_start:
                vis_left = max(vis_left, _d2n(xlim_start))
            if xlim_end:
                vis_right = min(vis_right, _d2n(xlim_end))
            text_x = vis_left + (vis_right - vis_left) * 0.5

            ax.text(
                text_x,
                i,
                item.name,
                ha="center",
                va="center",
                fontsize=fsize,
                color=text_color,
                fontweight=fweight,
                clip_on=True,
                bbox=dict(
                    boxstyle="round,pad=0.1",
                    facecolor=color,
                    edgecolor="none",
                    alpha=0.45,
                ),
            )
            all_dates.extend([item.start_date, item.end_date])
            bar_drawn = True
        else:
            ax.annotate(
                "No dates",
                (_d2n(date.today()), i),
                fontsize=child_font,
                color=pal["label_color"],
                va="center",
            )

    if not bar_drawn and not milestones:
        plt.close(fig)
        return None

    # -- Group separators for label-grouped items --------------------------------
    groups: dict[str, list[int]] = {}
    for i, item in enumerate(items):
        if item.group:
            groups.setdefault(item.group, []).append(i)

    for group_name, indices in groups.items():
        y_min = min(indices) - 0.5
        y_max = max(indices) + 0.5
        # Draw thin horizontal separator lines at group boundaries
        ax.axhline(
            y_min,
            color=pal["group_label"],
            linewidth=0.6,
            linestyle="-",
            alpha=0.5,
            zorder=1,
        )
        ax.axhline(
            y_max,
            color=pal["group_label"],
            linewidth=0.6,
            linestyle="-",
            alpha=0.5,
            zorder=1,
        )
        # Group label in the left margin via y-axis tick area
        label_y = (y_min + y_max) / 2
        ax.annotate(
            group_name,
            xy=(0, label_y),
            xycoords=("axes fraction", "data"),
            xytext=(-8, 0),
            textcoords="offset points",
            fontsize=5.5,
            color=pal["group_label"],
            fontweight="bold",
            va="center",
            ha="right",
            annotation_clip=False,
        )

    # -- Effective visible range for filtering sprint/milestone drawing --------
    eff_start = xlim_start
    eff_end = xlim_end

    # -- Filter milestones to the visible range when hard limits are set ---------
    if eff_start or eff_end:
        ms_start = eff_start or (min(all_dates) if all_dates else None)
        ms_end = eff_end or (max(all_dates) if all_dates else None)
        if ms_start and ms_end:
            milestones = [
                ms for ms in milestones if ms_start <= ms.release_date <= ms_end
            ]

    # Sort sprints by start date for absolute numbering
    sprints = sorted(sprints, key=lambda sp: sp.start_date or date.min)

    # -- Sprint bands (vertical shading + pill labels at y=1.0) ----------------
    sprint_annotations: list[Any] = []
    for sp in sprints:
        if sp.start_date and sp.end_date:
            # Skip sprints entirely outside the hard date range
            if eff_start and sp.end_date < eff_start:
                continue
            if eff_end and sp.start_date > eff_end:
                continue

            # Clamp span/line drawing to the effective visible range so
            # partially-overlapping sprints don't extend axes data limits
            draw_left = sp.start_date
            draw_right = sp.end_date
            if eff_start and draw_left < eff_start:
                draw_left = eff_start
            if eff_end and draw_right > eff_end:
                draw_right = eff_end

            sp_left = _d2n(draw_left)
            sp_right = _d2n(draw_right)
            ax.axvspan(
                sp_left, sp_right, color=pal["sprint_band"], alpha=0.06, zorder=0
            )
            for bx in (sp_left, sp_right):
                ax.axvline(
                    bx,
                    color=pal["sprint_pill_edge"],
                    linewidth=0.4,
                    linestyle=":",
                    zorder=1,
                )

            # Sprint pill label: condensed date range (uses original dates)
            pill_left = _d2n(sp.start_date)
            pill_right = _d2n(sp.end_date)
            mid_x = pill_left + (pill_right - pill_left) / 2
            s_lbl = f"{_MONTHS_ABBR[sp.start_date.month - 1]}{sp.start_date.day:02d}"
            e_lbl = f"{_MONTHS_ABBR[sp.end_date.month - 1]}{sp.end_date.day:02d}"
            pill_text = f"{s_lbl}-\n{e_lbl}"
            ann = ax.annotate(
                pill_text,
                xy=(mid_x, 1.0),
                xycoords=("data", "axes fraction"),
                fontsize=5.5,
                color=pal["sprint_text"],
                fontweight="medium",
                ha="center",
                va="bottom",
                annotation_clip=True,
                multialignment="center",
                bbox=dict(
                    boxstyle="round,pad=0.35",
                    facecolor=pal["sprint_pill_bg"],
                    edgecolor=pal["sprint_pill_edge"],
                    linewidth=0.6,
                    alpha=0.95,
                ),
            )
            sprint_annotations.append(ann)
            all_dates.extend([draw_left, draw_right])

    # -- Milestones (dashed line + pill label at y=1.07) -----------------------
    for ms in milestones:
        ms_x = _d2n(ms.release_date)
        ax.axvline(
            ms_x,
            color=pal["milestone_pill_edge"],
            linestyle="--",
            linewidth=1.0,
            zorder=3,
        )
        ax.annotate(
            f"  {ms.name}",
            xy=(ms_x, 1.07),
            xycoords=("data", "axes fraction"),
            fontsize=6,
            fontweight="bold",
            color=pal["milestone_text"],
            ha="left",
            va="bottom",
            annotation_clip=True,
            bbox=dict(
                boxstyle="round,pad=0.3",
                facecolor=pal["milestone_pill_bg"],
                edgecolor=pal["milestone_pill_edge"],
                linewidth=0.7,
                alpha=0.95,
            ),
        )
        all_dates.append(ms.release_date)

    # -- Axis layout -----------------------------------------------------------
    ax.set_yticks(range(len(y_labels)))
    ax.set_yticklabels([""] * len(y_labels))
    ax.invert_yaxis()

    min_d = max_d = date.today()
    span = 90
    if all_dates:
        min_d = min(all_dates)
        max_d = max(all_dates)
        if xlim_start:
            min_d = xlim_start
        if xlim_end:
            max_d = xlim_end
        span = max((max_d - min_d).days, 1)
        auto_pad = timedelta(days=max(int(span * 0.05), 1))
        left_pad = timedelta(0) if xlim_start else auto_pad
        right_pad = timedelta(0) if xlim_end else auto_pad
        ax.set_xlim(_d2n(min_d - left_pad), _d2n(max_d + right_pad))

    # Lock x-axis: prevent barh/axvspan data limits from overriding the view
    ax.set_autoscalex_on(False)

    # Date ticks at the bottom
    ax.xaxis.tick_bottom()
    ax.xaxis.set_label_position("bottom")

    if span <= 90:
        ax.xaxis.set_major_locator(
            mdates.WeekdayLocator(byweekday=mdates.MO)  # type: ignore[arg-type]
        )
        ax.xaxis.set_major_formatter(_EnglishDateFormatter())
    elif span <= 365:
        ax.xaxis.set_major_locator(mdates.MonthLocator())
        ax.xaxis.set_major_formatter(_MonthFormatter())
    else:
        ax.xaxis.set_major_locator(mdates.MonthLocator(bymonth=[1, 4, 7, 10]))
        ax.xaxis.set_major_formatter(_QuarterFormatter())

    ax.tick_params(
        axis="x", which="major", labelsize=6, colors=pal["label_color"], pad=2, length=3
    )
    for lbl in ax.get_xticklabels():
        lbl.set_rotation(45)
        lbl.set_horizontalalignment("right")

    fig.canvas.draw()
    _prune_overlapping_tick_labels(ax)
    _prune_overlapping_annotations(fig, sprint_annotations)

    # Major date labels — topmost tier above sprint pills
    if all_dates:
        _draw_major_date_labels(ax, min_d, max_d, span, pal)

    ax.tick_params(axis="y", length=0)
    ax.tick_params(axis="y", labelsize=7, colors=pal["label_color"])
    ax.grid(axis="x", linewidth=0.3, color=pal["grid"])
    ax.set_axisbelow(True)

    for spine in ax.spines.values():
        spine.set_color(pal["grid"])

    # Reserve top portion of figure for above-axes annotations (sprint pills,
    # milestone pills, major date labels).  Save with fixed figure dimensions
    # instead of bbox_inches="tight" which produces unpredictable sizes when
    # annotations or data limits extend beyond the axes view.
    fig.tight_layout(rect=(0, 0, 1, 0.85))

    buf = io.BytesIO()
    fig.savefig(
        buf, format="png", dpi=dpi, facecolor=fig.get_facecolor(), edgecolor="none"
    )
    plt.close(fig)
    buf.seek(0)
    data = buf.read()
    logger.debug("Timeline chart rendered: %d bytes", len(data))
    return data


# -- Timeline helpers ----------------------------------------------------------


def _prune_overlapping_tick_labels(ax: Any) -> None:
    """Hide tick labels whose bounding boxes overlap with their neighbours."""
    renderer = ax.get_figure().canvas.get_renderer()
    labels = ax.get_xticklabels()
    prev_bb = None
    for lbl in labels:
        if not lbl.get_text():
            continue
        bb = lbl.get_window_extent(renderer)
        if prev_bb is not None and bb.x0 < prev_bb.x1 + 4:
            lbl.set_visible(False)
        else:
            lbl.set_visible(True)
            prev_bb = bb


def _prune_overlapping_annotations(fig: Any, annotations: list[Any]) -> None:
    """Hide annotation pills whose bounding boxes overlap with prior visible ones."""
    if not annotations:
        return
    renderer = fig.canvas.get_renderer()
    prev_bb = None
    for ann in annotations:
        try:
            bb = ann.get_window_extent(renderer)
        except Exception:
            continue
        if prev_bb is not None and bb.x0 < prev_bb.x1 + 4:
            ann.set_visible(False)
        else:
            ann.set_visible(True)
            prev_bb = bb


def _draw_major_date_labels(
    ax: Any,
    min_d: date,
    max_d: date,
    span_days: int,
    pal: dict[str, str],
) -> None:
    """Draw the topmost tier of bold date labels (months/quarters/years).

    Positioned at axes-fraction y=1.21 so they sit clearly above the milestone
    pills at y=1.07 and sprint pills at y=1.0.
    """
    y_top = 1.21
    color = pal["major_date_color"]

    def _emit(
        left_num: float,
        right_num: float,
        label: str,
        *,
        draw_sep: bool = True,
    ) -> None:
        mid = left_num + (right_num - left_num) / 2
        ax.annotate(
            label,
            xy=(mid, y_top),
            xycoords=("data", "axes fraction"),
            fontsize=8.5,
            fontweight="bold",
            color=color,
            ha="center",
            va="bottom",
            annotation_clip=False,
        )
        if draw_sep:
            # Full-height vertical separator from bottom of axes through
            # the annotation area so quarter/month/year boundaries are
            # clearly visible in the chart body.
            ax.annotate(
                "",
                xy=(left_num, y_top),
                xytext=(left_num, 0),
                xycoords=("data", "axes fraction"),
                textcoords=("data", "axes fraction"),
                arrowprops=dict(arrowstyle="-", color=pal["grid"], lw=0.7),
                annotation_clip=False,
            )

    if span_days <= 90:
        d = date(min_d.year, min_d.month, 1)
        first = True
        while d <= max_d:
            nxt = date(d.year + (d.month // 12), (d.month % 12) + 1, 1)
            _emit(
                _d2n(max(d, min_d)),
                _d2n(min(nxt, max_d)),
                f"{_MONTHS_ABBR[d.month - 1]} {d.year}",
                draw_sep=not first,
            )
            first = False
            d = nxt
    elif span_days <= 365:
        d = date(min_d.year, ((min_d.month - 1) // 3) * 3 + 1, 1)
        first = True
        while d <= max_d:
            q = (d.month - 1) // 3 + 1
            nm = d.month + 3
            nxt = date(d.year + (nm - 1) // 12, ((nm - 1) % 12) + 1, 1)
            _emit(
                _d2n(max(d, min_d)),
                _d2n(min(nxt, max_d)),
                f"Q{q} {d.year}",
                draw_sep=not first,
            )
            first = False
            d = nxt
    else:
        year = min_d.year
        first = True
        while year <= max_d.year:
            _emit(
                _d2n(max(date(year, 1, 1), min_d)),
                _d2n(min(date(year + 1, 1, 1), max_d)),
                str(year),
                draw_sep=not first,
            )
            first = False
            year += 1


def _draw_weekend_bands(ax: Any, dates: list[date], color: str) -> None:
    """Draw light gray vertical bands for weekends."""
    if not dates:
        return

    in_weekend = False
    start: date | None = None

    for d in dates:
        if d.weekday() >= 5:  # Saturday=5, Sunday=6
            if not in_weekend:
                start = d
                in_weekend = True
        else:
            if in_weekend and start is not None:
                ax.axvspan(_d2n(start), _d2n(d), color=color, zorder=0)
                in_weekend = False

    # Close trailing weekend
    if in_weekend and start is not None:
        ax.axvspan(_d2n(start), _d2n(dates[-1]), color=color, zorder=0)
