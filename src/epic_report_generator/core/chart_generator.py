"""Matplotlib chart generation replicating the Jira Epic Report style."""

from __future__ import annotations

import io
import logging
from datetime import date

from epic_report_generator.core.data_models import EpicMetrics

import matplotlib  # isort: skip

matplotlib.use("Agg")

import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.ticker as mticker  # noqa: E402

logger = logging.getLogger(__name__)

_MONTHS_ABBR = [
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
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

    logger.debug("Rendering chart: %d data points, dark=%s, dpi=%d", len(metrics.dates), dark, dpi)
    pal = _DARK if dark else _LIGHT

    fig, ax1 = plt.subplots(figsize=(7.2, 3.6), dpi=dpi)
    fig.patch.set_facecolor(pal["face"])
    ax1.set_facecolor(pal["bg"])
    ax2 = ax1.twinx()

    dates = metrics.dates

    # Weekend bands
    _draw_weekend_bands(ax1, dates, pal["weekend"])

    # Total SP area (gray)
    ax1.fill_between(
        dates,
        metrics.total_sp_over_time,
        color=pal["total_sp"],
        alpha=0.7,
        label="Total Story Points",
        step="post",
    )

    # Completed SP area (blue)
    ax1.fill_between(
        dates,
        metrics.completed_sp_over_time,
        color=pal["done_sp"],
        alpha=0.7,
        label="Completed Story Points",
        step="post",
    )

    # Cumulative issues (dark blue step line — right axis)
    ax2.step(
        dates,
        metrics.cumulative_issues,
        where="post",
        color=pal["cum_issues"],
        linewidth=1.5,
        label="Cumulative Issues",
    )

    # Cumulative unestimated (brown step line — right axis)
    ax2.step(
        dates,
        metrics.cumulative_unestimated,
        where="post",
        color=pal["cum_unest"],
        linewidth=1.5,
        linestyle="--",
        label="Unestimated Issues",
    )

    # Axes formatting
    ax1.set_ylabel("Story Points", fontsize=8, color=pal["label_color"])
    ax2.set_ylabel("Issues", fontsize=8, color=pal["label_color"])
    ax1.xaxis.set_major_formatter(_EnglishDateFormatter())
    ax1.xaxis.set_major_locator(mdates.AutoDateLocator(minticks=4, maxticks=10))
    fig.autofmt_xdate(rotation=30, ha="right")

    ax1.tick_params(labelsize=7, colors=pal["label_color"])
    ax2.tick_params(labelsize=7, colors=pal["label_color"])
    ax1.set_xlim(dates[0], dates[-1])
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
        buf, format="png", dpi=dpi, bbox_inches="tight",
        facecolor=fig.get_facecolor(), edgecolor="none",
    )
    plt.close(fig)
    buf.seek(0)
    data = buf.read()
    logger.debug("Chart rendered: %d bytes", len(data))
    return data


def _draw_weekend_bands(ax: plt.Axes, dates: list[date], color: str) -> None:
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
                ax.axvspan(start, d, color=color, zorder=0)
                in_weekend = False

    # Close trailing weekend
    if in_weekend and start is not None:
        ax.axvspan(start, dates[-1], color=color, zorder=0)
