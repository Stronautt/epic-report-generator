"""Build the JSON view-model that drives the Typst templates.

This is the seam between the data/metrics layer and the Typst view layer. It
flattens ``ReportData`` (epics, label groups, label expansion) into a plain,
JSON-serialisable payload of display-ready values, including the geometry data
for the natively-drawn charts: the Gantt timeline (date->day-offset mapping,
ticks, tiers, milestones) and the per-epic trend chart (series + nice axes).
No images are produced — the Typst components draw the charts from this data.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Iterator
from datetime import date, timedelta
from typing import Any

from epic_report_generator.core import theming
from epic_report_generator.core.data_models import (
    STATUS_DONE,
    STATUS_IN_PROGRESS,
    STATUS_TODO,
    EpicData,
    EpicMetrics,
    JiraIssue,
    MilestoneItem,
    ReportData,
    ReportItem,
    TimelineItem,
    collect_child_timeline_dates,
    fmt_date_en,
)

logger = logging.getLogger(__name__)

_DATE_FMT = "%B %d, %Y"


def _is_label_group(item: ReportItem | None, report: ReportData) -> bool:
    """True when *item* is a label row that expands into source epics."""
    return (
        item is not None
        and item.kind == "label"
        and item.key in report.label_source_epics
    )


def build_report(report: ReportData) -> dict[str, Any]:
    """Build the JSON-serialisable payload consumed by ``main.typ``."""
    config = report.config
    dark = config.dark_mode

    unit = report.metrics[0].estimation_unit if report.metrics else "SP"

    rows: list[dict[str, Any]] = []
    pages: list[dict[str, Any]] = []

    real_epics = 0
    sum_total_issues = 0
    sum_total_sp = 0.0
    sum_done_sp = 0.0
    weighted_progress_num = 0.0
    weighted_progress_den = 0.0
    summary_has_certainty = False

    def accumulate(m: EpicMetrics) -> None:
        nonlocal sum_total_issues, sum_total_sp, sum_done_sp
        nonlocal weighted_progress_num, weighted_progress_den
        sum_total_issues += m.total_issues
        sum_total_sp += m.total_sp
        sum_done_sp += m.completed_sp
        weight = m.total_sp if m.total_sp > 0 else m.total_issues
        weighted_progress_num += m.progress * weight
        weighted_progress_den += weight

    def note_certainty(m: EpicMetrics) -> None:
        nonlocal summary_has_certainty
        if m.scope_certainty:
            summary_has_certainty = True

    for item, epic, metrics in _iter_items(report):
        if _is_label_group(item, report):
            sources = report.label_source_epics[item.key]
            rows.append(_group_row(item, epic, metrics, len(sources)))
            accumulate(metrics)
            note_certainty(metrics)
            real_epics += len(sources)
            for src_epic, src_metrics in sources:
                rows.append(_epic_row(src_epic, src_metrics, src_epic.key))
                note_certainty(src_metrics)
            if config.expand_label_details:
                label_tag = item.display_name or item.key
                for src_epic, src_metrics in sources:
                    pages.append(
                        _epic_page(
                            src_epic, src_metrics, config, src_epic.key, label_tag
                        )
                    )
            else:
                pages.append(
                    _epic_page(
                        epic, metrics, config, item.display_name or item.key, None
                    )
                )
        else:
            key_text = (
                epic.key
                if item is None or item.kind == "epic"
                else item.display_name or item.key
            )
            rows.append(_epic_row(epic, metrics, key_text))
            accumulate(metrics)
            note_certainty(metrics)
            real_epics += 1
            pages.append(_epic_page(epic, metrics, config, key_text, None))

    overall = (
        round(weighted_progress_num / weighted_progress_den)
        if weighted_progress_den
        else 0
    )
    kpis = [
        {"label": "Epics", "value": str(real_epics)},
        {"label": "Overall", "value": f"{overall} %"},
        {"label": "Issues", "value": str(sum_total_issues)},
        {"label": f"Total {unit}", "value": f"{sum_total_sp:.0f}"},
        {"label": f"Done {unit}", "value": f"{sum_done_sp:.0f}"},
    ]

    timeline_chart = _timeline_data(report) if config.show_timeline_chart else None

    # Appearance customization (NFR-05): accent-family colour overrides and the
    # custom font family, both empty when nothing is configured (stock palette).
    accent = getattr(config, "report_accent", "") or ""
    accent_colors = (
        theming.report_overrides(accent, dark)
        if accent and theming.is_valid_hex(accent)
        else {}
    )

    payload: dict[str, Any] = {
        "theme": {
            "dark": dark,
            "colors": accent_colors,
            "font": getattr(config, "report_font_family", "") or "",
        },
        "title": _title(config),
        "footer": _footer(config),
        "summary": {
            "unit": unit,
            "kpis": kpis,
            "has-certainty": summary_has_certainty,
            "rows": rows,
        },
        "timeline": {
            "enabled": bool(config.show_timeline_chart),
            "chart": timeline_chart,
            "has-certainty": any(m.scope_certainty for m in report.metrics),
        },
        "pages": pages,
    }

    logger.debug(
        "View-model: %d summary row(s), %d epic page(s), timeline=%s",
        len(rows),
        len(pages),
        timeline_chart is not None,
    )
    return payload


# -- iteration / status -------------------------------------------------------


def _iter_items(
    report: ReportData,
) -> Iterator[tuple[ReportItem | None, EpicData, EpicMetrics]]:
    """Yield ``(item, epic, metrics)`` triples, mirroring the old renderer."""
    if report.resolved_items:
        yield from report.resolved_items
    else:
        for epic, metrics in zip(report.epics, report.metrics):
            yield None, epic, metrics


def _aggregate_status(epic: EpicData) -> str:
    """Derive an aggregate status from an epic's children."""
    if not epic.children:
        return epic.status
    categories = {c.status_category for c in epic.children}
    if categories == {STATUS_DONE}:
        return STATUS_DONE
    if categories == {STATUS_TODO}:
        return STATUS_TODO
    return STATUS_IN_PROGRESS


# -- summary rows -------------------------------------------------------------


def _epic_row(epic: EpicData, metrics: EpicMetrics, key: str) -> dict[str, Any]:
    return {
        "kind": "epic",
        "key": key,
        "summary": epic.summary,
        "progress": int(round(metrics.progress)),
        "certainty": metrics.scope_certainty,
        "status": _aggregate_status(epic),
        "total": metrics.total_issues,
        "done": metrics.completed_issues,
        "unest": metrics.unestimated_issues,
        "total-sp": f"{metrics.total_sp:.0f}",
        "done-sp": f"{metrics.completed_sp:.0f}",
    }


def _group_row(
    item: ReportItem, epic: EpicData, metrics: EpicMetrics, n_epics: int
) -> dict[str, Any]:
    return {
        "kind": "group",
        "label": item.display_name or item.key,
        "n-epics": n_epics,
        "progress": int(round(metrics.progress)),
        "certainty": metrics.scope_certainty,
        "status": _aggregate_status(epic),
        "total": metrics.total_issues,
        "done": metrics.completed_issues,
        "unest": metrics.unestimated_issues,
        "total-sp": f"{metrics.total_sp:.0f}",
        "done-sp": f"{metrics.completed_sp:.0f}",
    }


# -- epic detail pages --------------------------------------------------------


def _epic_page(
    epic: EpicData,
    metrics: EpicMetrics,
    config: Any,
    key: str,
    label_tag: str | None,
) -> dict[str, Any]:
    unit = metrics.estimation_unit
    kpis = [
        {"label": "Total", "value": str(metrics.total_issues)},
        {"label": "Completed", "value": str(metrics.completed_issues)},
        {"label": "Open", "value": str(metrics.open_issues)},
        {"label": "Unestimated", "value": str(metrics.unestimated_issues)},
        {"label": f"Total {unit}", "value": f"{metrics.total_sp:.0f}"},
        {"label": f"Done {unit}", "value": f"{metrics.completed_sp:.0f}"},
        {"label": f"Remaining {unit}", "value": f"{metrics.remaining_sp:.0f}"},
    ]

    additional: list[dict[str, str]] | None = None
    if config.show_additional_metrics:
        additional = [
            {
                "label": "Avg Cycle Time",
                "value": (
                    f"{metrics.avg_cycle_time_days:.1f} days"
                    if metrics.avg_cycle_time_days
                    else "N/A"
                ),
            },
            {
                "label": "Velocity (4wk)",
                "value": (
                    f"{metrics.velocity_sp_per_week:.1f} {unit}/wk"
                    if metrics.velocity_sp_per_week
                    else "N/A"
                ),
            },
            {
                "label": "Scope Change",
                "value": (
                    f"{metrics.scope_change_pct:.0f}%"
                    if metrics.scope_change_pct is not None
                    else "N/A"
                ),
            },
            {"label": "Blocked", "value": str(metrics.blocked_issues)},
            {
                "label": "Forecast",
                "value": (
                    fmt_date_en(metrics.forecast_date, "%b %d, %Y")
                    if metrics.forecast_date
                    else "N/A"
                ),
            },
        ]

    return {
        "key": key,
        "summary": None if key == epic.summary else epic.summary,
        "status": _aggregate_status(epic),
        "label-tag": label_tag,
        "chart": _trend_data(metrics),
        "kpis": kpis,
        "additional": additional,
    }


# -- title / footer -----------------------------------------------------------


def _title(config: Any) -> dict[str, Any]:
    notice = None
    if config.confidential and config.company_name:
        notice = (
            f"CONFIDENTIAL — This document is the property of {config.company_name} "
            "and is intended solely for the use of the intended recipient(s). "
            "Unauthorized distribution is prohibited."
        )
    return {
        "title": config.title,
        "project": config.project_display_name or None,
        "date": fmt_date_en(config.report_date, _DATE_FMT),
        "author": config.author or None,
        "notice": notice,
    }


def _footer(config: Any) -> dict[str, Any]:
    right_parts = [fmt_date_en(config.report_date, _DATE_FMT)]
    if config.author:
        right_parts.append(config.author)
    return {
        "enabled": bool(config.confidential and config.company_name),
        "company": config.company_name,
        "right": "  |  ".join(right_parts),
    }


# -- trend chart data ---------------------------------------------------------


def _nice_axis(maxv: float, target: int = 4) -> tuple[float, list[float]]:
    """Return ``(axis_max, ticks)`` rounded to human-friendly steps."""
    if maxv <= 0:
        return 1, [0, 1]
    raw = maxv / target
    mag = 10 ** math.floor(math.log10(raw))
    step = 10 * mag
    for m in (1, 2, 2.5, 5, 10):
        if raw <= m * mag:
            step = m * mag
            break
    axis_max = math.ceil(maxv / step) * step
    ticks: list[float] = []
    v = 0.0
    while v <= axis_max + step * 1e-6:
        ticks.append(int(v) if float(v).is_integer() else round(v, 2))
        v += step
    axis_out = int(axis_max) if float(axis_max).is_integer() else round(axis_max, 2)
    return axis_out, ticks


def _index_ticks(dates: list[date], target: int = 6) -> list[dict[str, Any]]:
    """Pick ~*target* evenly spaced indices (incl. first/last) with date labels."""
    n = len(dates)
    if n <= target:
        idxs = list(range(n))
    else:
        idxs = sorted({round(i * (n - 1) / (target - 1)) for i in range(target)})
    return [{"i": i, "label": fmt_date_en(dates[i], "%b %d")} for i in idxs]


def _trend_data(metrics: EpicMetrics) -> dict[str, Any] | None:
    """Build the dual-axis trend chart data, or ``None`` when too sparse."""
    dates = metrics.dates
    if len(dates) < 2:
        return None
    n = len(dates)
    total = [round(v, 1) for v in metrics.total_sp_over_time]
    done = [round(v, 1) for v in metrics.completed_sp_over_time]
    cum_iss = list(metrics.cumulative_issues)
    cum_unest = list(metrics.cumulative_unestimated)

    sp_max, sp_ticks = _nice_axis(max(total) if total else 0)
    iss_peak = max((cum_iss or [0]) + (cum_unest or [0]))
    iss_max, iss_ticks = _nice_axis(iss_peak)

    return {
        "n": n,
        "unit": metrics.estimation_unit,
        "sp-max": sp_max,
        "sp-ticks": sp_ticks,
        "iss-max": iss_max,
        "iss-ticks": iss_ticks,
        "total-sp": total,
        "done-sp": done,
        "cum-iss": cum_iss,
        "cum-unest": cum_unest,
        "x-ticks": _index_ticks(dates),
    }


# -- timeline (Gantt) data ----------------------------------------------------


def _resolve_child_timeline_dates(child: JiraIssue) -> tuple[Any, Any]:
    tl_starts: list[Any] = []
    tl_ends: list[Any] = []
    collect_child_timeline_dates(child, tl_starts, tl_ends)
    return (min(tl_starts) if tl_starts else None, max(tl_ends) if tl_ends else None)


def _build_timeline(
    report: ReportData,
) -> tuple[list[TimelineItem], list[MilestoneItem]]:
    """Assemble Gantt timeline items + milestones (ported from the old renderer)."""
    config = report.config
    items: list[TimelineItem] = []
    show_children = config.show_epic_stories_on_timeline
    show_subtasks = config.show_subtasks_on_timeline

    def add_epic(
        epic: EpicData, metrics: EpicMetrics, name: str, group: str = ""
    ) -> None:
        tl_start = epic.timeline_start or epic.start_date
        tl_end = epic.timeline_end or epic.due_date
        weight = metrics.total_sp if metrics.total_sp > 0 else metrics.total_issues
        items.append(
            TimelineItem(
                name=name,
                start_date=tl_start,
                end_date=tl_end,
                scope_certainty=metrics.scope_certainty,
                progress=metrics.progress,
                group=group,
                summary=epic.summary,
                weight=float(weight) if weight else 1.0,
            )
        )
        if show_children and epic.children:
            for child in epic.children:
                if child.is_subtask and not show_subtasks:
                    continue
                c_start, c_end = _resolve_child_timeline_dates(child)
                if c_start and c_end:
                    items.append(
                        TimelineItem(
                            name=f"  {child.key}",
                            start_date=c_start,
                            end_date=c_end,
                            scope_certainty=None,
                            progress=child.progress,
                            is_child=True,
                            group=group,
                            summary=child.summary,
                        )
                    )

    for item, epic, metrics in _iter_items(report):
        if _is_label_group(item, report):
            group = item.display_name or item.key
            for src_epic, src_metrics in report.label_source_epics[item.key]:
                add_epic(src_epic, src_metrics, src_epic.key, group=group)
        else:
            name = (item.display_name or epic.key) if item is not None else epic.key
            add_epic(epic, metrics, name)

    item_dates: list[date] = []
    for ti in items:
        if ti.start_date:
            item_dates.append(ti.start_date)
        if ti.end_date:
            item_dates.append(ti.end_date)

    milestones: list[MilestoneItem] = []
    if item_dates:
        range_start = config.timeline_hard_start or (
            min(item_dates) - timedelta(days=7)
        )
        range_end = config.timeline_hard_end or (max(item_dates) + timedelta(days=7))
        for name, release_date in report.fix_version_dates.items():
            if release_date and range_start <= release_date <= range_end:
                milestones.append(MilestoneItem(name=name, release_date=release_date))
    else:
        for name, release_date in report.fix_version_dates.items():
            if release_date:
                milestones.append(MilestoneItem(name=name, release_date=release_date))

    return items, milestones


def _month_start(d: date) -> date:
    return date(d.year, d.month, 1)


def _add_months(d: date, k: int) -> date:
    idx = (d.year * 12 + (d.month - 1)) + k
    return date(idx // 12, idx % 12 + 1, 1)


def _time_axis(
    range_start: date, range_end: date, domain: int
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Return ``(ticks, tiers, subtiers)`` whose density avoids overlap.

    The top band is a consistent **year (tiers) + quarter (subtiers)** hierarchy
    for every span; only the bottom date ticks change granularity by span:
    weekly (<=120d), monthly (<=800d), else quarterly. Quarters render as small
    dividers on the year band, never as full-height plot lines.
    """
    ticks: list[dict[str, Any]] = []
    tiers: list[dict[str, Any]] = []
    subtiers: list[dict[str, Any]] = []

    def off(d: date) -> int:
        return (d - range_start).days

    def span(d0: date, d1: date, label: str) -> dict[str, Any]:
        s = max(d0, range_start)
        e = min(d1, range_end)
        return {"start": off(s), "end": off(e), "label": label}

    # bottom date ticks: granularity by span
    if domain <= 120:  # weekly date ticks
        first_monday = range_start + timedelta(days=(7 - range_start.weekday()) % 7)
        d = first_monday
        while d <= range_end:
            ticks.append({"off": off(d), "label": fmt_date_en(d, "%b %d")})
            d += timedelta(days=7)
    elif domain <= 800:  # monthly ticks
        m = _month_start(range_start)
        if m < range_start:
            m = _add_months(m, 1)
        while m <= range_end:
            ticks.append({"off": off(m), "label": fmt_date_en(m, "%b")})
            m = _add_months(m, 1)
    else:  # quarterly ticks (very long horizons)
        m = _month_start(range_start)
        while m < range_start or (m.month - 1) % 3 != 0:
            m = _add_months(m, 1)
        while m <= range_end:
            ticks.append({"off": off(m), "label": f"Q{(m.month - 1) // 3 + 1}"})
            m = _add_months(m, 3)

    # top band: year tiers + quarter sub-dividers (consistent for every span)
    yr = date(range_start.year, 1, 1)
    while yr <= range_end:
        nxt = date(yr.year + 1, 1, 1)
        tiers.append(span(yr, nxt - timedelta(days=1), str(yr.year)))
        yr = nxt
    q = _month_start(range_start)
    while (q.month - 1) % 3 != 0:
        q = _add_months(q, -1)
    while q <= range_end:
        nxt = _add_months(q, 3)
        subtiers.append(span(q, nxt - timedelta(days=1), f"Q{(q.month - 1) // 3 + 1}"))
        q = nxt

    return ticks, tiers, subtiers


def _truncate(text: str, n: int) -> str:
    """Trim *text* to at most *n* characters, adding an ellipsis when cut."""
    text = (text or "").strip()
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def _sprint_lane(
    report: ReportData, range_start: date, range_end: date, off: Any
) -> list[dict[str, Any]]:
    """Distinct, in-range sprints (with both dates) as a ribbon layer.

    Sorted by start, de-duplicated by name; the sprint covering the report date
    (or flagged ``active`` by Jira) is marked so the renderer can highlight it.
    """
    valid = [
        s
        for s in report.sprints
        if s.start_date
        and s.end_date
        and s.end_date >= range_start
        and s.start_date <= range_end
    ]
    valid.sort(key=lambda s: s.start_date)
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for s in valid:
        if s.name in seen:
            continue
        seen.add(s.name)
        active = (s.state or "").lower() == "active" or (
            s.start_date <= report.config.report_date <= s.end_date
        )
        out.append(
            {
                "start": off(s.start_date),
                "end": off(s.end_date),
                "label": s.name,
                "short": s.name.split()[-1] if s.name.split() else s.name,
                "active": active,
            }
        )
    return out


def _timeline_data(report: ReportData) -> dict[str, Any] | None:
    """Build the Gantt chart-data dict, or ``None`` when there is nothing to show."""
    config = report.config
    items, milestones = _build_timeline(report)

    all_dates: list[date] = []
    for it in items:
        if it.start_date:
            all_dates.append(it.start_date)
        if it.end_date:
            all_dates.append(it.end_date)
    all_dates.extend(m.release_date for m in milestones)
    if not all_dates:
        return None

    range_start = config.timeline_hard_start or (min(all_dates) - timedelta(days=4))
    range_end = config.timeline_hard_end or (max(all_dates) + timedelta(days=4))
    domain = (range_end - range_start).days
    if domain <= 0:
        return None

    def off(d: date) -> int:
        return max(0, min(domain, (d - range_start).days))

    rows: list[dict[str, Any]] = []
    groups: list[dict[str, Any]] = []
    cur_group: str | None = None
    group_start = 0
    g_prog_num = 0.0
    g_prog_den = 0.0
    g_epics = 0

    def close_group(end_idx: int) -> None:
        prog = int(round(g_prog_num / g_prog_den)) if g_prog_den else 0
        groups.append(
            {
                "label": cur_group,
                "start-row": group_start,
                "count": end_idx - group_start,
                "n-epics": g_epics,
                "progress": prog,
            }
        )

    for idx, it in enumerate(items):
        g = it.group or ""
        if g != cur_group:
            if cur_group is not None:
                close_group(idx)
            cur_group = g
            group_start = idx
            g_prog_num = 0.0
            g_prog_den = 0.0
            g_epics = 0
        dated = it.start_date is not None and it.end_date is not None
        rows.append(
            {
                "key": it.name.strip(),
                "title": "" if it.is_child else _truncate(it.summary, 50),
                "start": off(it.start_date) if dated else None,
                "end": off(it.end_date) if dated else None,
                "progress": int(round(it.progress)),
                "certainty": it.scope_certainty,
                "child": it.is_child,
            }
        )
        if not it.is_child:
            g_epics += 1
            w = it.weight if it.weight else 1.0
            g_prog_num += it.progress * w
            g_prog_den += w
    if cur_group is not None:
        close_group(len(items))
    groups = [g for g in groups if g["count"] > 0]

    ticks, tiers, subtiers = _time_axis(range_start, range_end, domain)

    today_off = None
    if range_start <= config.report_date <= range_end:
        today_off = (config.report_date - range_start).days

    return {
        "domain": domain,
        "today": today_off,
        "groups": groups,
        "rows": rows,
        "ticks": ticks,
        "tiers": tiers,
        "subtiers": subtiers,
        "tick-grid": domain <= 800,
        "sprints": _sprint_lane(report, range_start, range_end, off),
        "milestones": [
            {"off": off(m.release_date), "label": m.name} for m in milestones
        ],
    }
