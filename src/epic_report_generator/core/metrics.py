"""Progress, velocity, cycle-time, and forecasting calculations."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from epic_report_generator.core.data_models import EpicData, EpicMetrics, JiraIssue

logger = logging.getLogger(__name__)


def calculate_metrics(
    epic: EpicData,
    estimation_method: str = "story_points",
    progress_method: str = "combined",
) -> EpicMetrics:
    """Compute all metrics for a single Epic from its child issues.

    *estimation_method* controls how issue estimates are derived:

    * ``"story_points"`` — use the ``story_points`` field (default).
    * ``"time_days"`` — use ``(due_date - start_date).days``.

    *progress_method* controls the progress formula:

    * ``"combined"`` — ``(done_sp/total_sp) * (done/total) * 100`` (default).
    * ``"story_points_only"`` — ``(done_sp/total_sp) * 100``.
    """
    children = epic.children
    m = EpicMetrics()
    m.estimation_unit = "Days" if estimation_method == "time_days" else "SP"

    if not children:
        logger.debug("Epic %s has no children — returning empty metrics", epic.key)
        return m

    m.total_issues = len(children)
    m.completed_issues = sum(1 for c in children if c.status_category == "Done")
    m.open_issues = m.total_issues - m.completed_issues
    m.unestimated_issues = sum(
        1 for c in children if _get_estimate(c, estimation_method) is None
    )
    m.total_sp = sum(
        est
        for c in children
        if (est := _get_estimate(c, estimation_method)) is not None
    )
    m.completed_sp = sum(
        _get_estimate(c, estimation_method) or 0
        for c in children
        if c.status_category == "Done"
        and _get_estimate(c, estimation_method) is not None
    )
    m.remaining_sp = m.total_sp - m.completed_sp
    m.progress = _progress(
        m.completed_sp,
        m.total_sp,
        m.completed_issues,
        m.total_issues,
        progress_method=progress_method,
    )
    m.avg_cycle_time_days = _avg_cycle_time(children)
    m.velocity_sp_per_week = _velocity(children, estimation_method, weeks=4)
    m.scope_change_pct = _scope_change(children)
    m.blocked_issues = sum(
        1
        for c in children
        if "blocked" in c.status.lower() and c.status_category != "Done"
    )
    m.forecast_date = _forecast(m.remaining_sp, m.velocity_sp_per_week)

    # Build time-series
    _build_time_series(m, children, estimation_method)

    logger.debug(
        "Metrics for %s: progress=%.1f%%, %d/%d issues done, %.0f/%.0f %s",
        epic.key,
        m.progress,
        m.completed_issues,
        m.total_issues,
        m.completed_sp,
        m.total_sp,
        m.estimation_unit,
    )
    return m


def merge_metrics(
    epics: list[EpicData],
    estimation_method: str = "story_points",
    progress_method: str = "combined",
) -> tuple[EpicData, EpicMetrics]:
    """Merge multiple epics into a single synthetic epic and compute metrics.

    Children are merged with key-based deduplication. The resulting
    :class:`EpicData` is synthetic — its key is the concatenation of source
    epic keys and its dates span the full range of the source epics.
    """
    seen: set[str] = set()
    merged_children: list[JiraIssue] = []
    all_labels: list[str] = []
    all_fix_versions: list[str] = []
    start_dates: list[date] = []
    due_dates: list[date] = []

    for epic in epics:
        all_labels.extend(epic.labels)
        all_fix_versions.extend(epic.fix_versions)
        if epic.start_date:
            start_dates.append(epic.start_date)
        if epic.due_date:
            due_dates.append(epic.due_date)
        for child in epic.children:
            if child.key not in seen:
                seen.add(child.key)
                merged_children.append(child)

    keys = [e.key for e in epics]
    # Fallback: derive dates from ALL merged children if no epic-level dates.
    # Per-child: prefer start_date/due_date, fall back to created/resolved
    # so every child contributes to the range.
    if not start_dates:
        for c in merged_children:
            if c.start_date:
                start_dates.append(c.start_date)
            elif c.created:
                start_dates.append(c.created.date())
    if not due_dates:
        for c in merged_children:
            if c.due_date:
                due_dates.append(c.due_date)
            elif c.resolved and c.status_category == "Done":
                due_dates.append(c.resolved.date())
        if not due_dates and start_dates:
            due_dates = [date.today()]

    synthetic = EpicData(
        key=", ".join(keys) if keys else "LABEL",
        summary=f"Merged from {len(epics)} epic(s)",
        status="N/A",
        priority=None,
        assignee=None,
        reporter=None,
        created=min((e.created for e in epics if e.created), default=None),
        updated=max((e.updated for e in epics if e.updated), default=None),
        labels=sorted(set(all_labels)),
        fix_versions=sorted(set(all_fix_versions)),
        children=merged_children,
        start_date=min(start_dates) if start_dates else None,
        due_date=max(due_dates) if due_dates else None,
    )

    m = calculate_metrics(synthetic, estimation_method, progress_method)
    return synthetic, m


# -- helpers ------------------------------------------------------------------


def _get_estimate(issue: JiraIssue, method: str) -> float | None:
    """Return the numeric estimate for *issue* based on *method*.

    * ``"story_points"``: returns ``issue.story_points`` (``None``/``0`` → ``None``).
    * ``"time_days"``: returns ``(due_date - start_date).days`` if both dates
      are present, else ``None``.
    """
    if method == "time_days":
        if issue.start_date is not None and issue.due_date is not None:
            days = (issue.due_date - issue.start_date).days
            return float(max(days, 0))
        return None
    # story_points
    return issue.story_points if issue.story_points else None


def _progress(
    completed_sp: float,
    total_sp: float,
    completed_issues: int,
    total_issues: int,
    *,
    progress_method: str = "combined",
) -> float:
    if total_issues == 0:
        return 0.0
    if progress_method == "story_points_only":
        if total_sp == 0:
            return 0.0
        return max(0.0, min(100.0, (completed_sp / total_sp) * 100))
    # combined (default)
    if total_sp == 0:
        return max(0.0, min(100.0, (completed_issues / total_issues) * 100))
    value = (completed_sp / total_sp) * (completed_issues / total_issues) * 100
    return max(0.0, min(100.0, value))


def _avg_cycle_time(children: list[JiraIssue]) -> float | None:
    durations: list[float] = []
    for c in children:
        if c.status_category == "Done" and c.created and c.resolved:
            delta = c.resolved - c.created
            durations.append(delta.total_seconds() / 86400)
    return sum(durations) / len(durations) if durations else None


def _velocity(
    children: list[JiraIssue],
    estimation_method: str = "story_points",
    weeks: int = 4,
) -> float | None:
    """Estimate completed per week over the last *weeks* weeks."""
    cutoff = datetime.now().astimezone() - timedelta(weeks=weeks)
    sp = sum(
        est
        for c in children
        if (est := _get_estimate(c, estimation_method)) is not None
        and c.status_category == "Done"
        and c.resolved
        and c.resolved >= cutoff
    )
    return sp / weeks if sp else None


def _scope_change(children: list[JiraIssue]) -> float | None:
    """Percentage of issues added after the earliest issue."""
    if len(children) < 2:
        return None
    dated = [(c, c.created) for c in children if c.created is not None]
    dated.sort(key=lambda pair: pair[1])
    if len(dated) < 2:
        return None
    first_created = dated[0][1]
    threshold = first_created + timedelta(days=7)
    added_later = sum(1 for _, dt in dated if dt > threshold)
    return (added_later / len(children)) * 100


def _forecast(remaining_sp: float, velocity: float | None) -> date | None:
    if not velocity or velocity <= 0 or remaining_sp <= 0:
        return None
    weeks_remaining = remaining_sp / velocity
    return date.today() + timedelta(weeks=weeks_remaining)


def _build_time_series(
    m: EpicMetrics,
    children: list[JiraIssue],
    estimation_method: str = "story_points",
) -> None:
    """Build daily time-series arrays for the trend chart."""
    dated = [(c, c.created) for c in children if c.created is not None]
    if not dated:
        return

    min_date = min(dt for _, dt in dated).date()
    max_date = date.today()
    if min_date >= max_date:
        return

    day = min_date
    dates: list[date] = []
    total_sp_ts: list[float] = []
    completed_sp_ts: list[float] = []
    cum_issues: list[int] = []
    cum_unest: list[int] = []

    while day <= max_date:
        day_end = datetime(day.year, day.month, day.day, 23, 59, 59)
        day_end = day_end.astimezone()

        created_by_day = [c for c, dt in dated if dt.date() <= day]
        done_by_day = [
            c
            for c in created_by_day
            if c.status_category == "Done" and c.resolved and c.resolved <= day_end
        ]

        dates.append(day)
        total_sp_ts.append(
            sum(_get_estimate(c, estimation_method) or 0 for c in created_by_day)
        )
        completed_sp_ts.append(
            sum(_get_estimate(c, estimation_method) or 0 for c in done_by_day)
        )
        cum_issues.append(len(created_by_day))
        cum_unest.append(
            sum(
                1 for c in created_by_day if _get_estimate(c, estimation_method) is None
            )
        )

        day += timedelta(days=1)

    m.dates = dates
    m.total_sp_over_time = total_sp_ts
    m.completed_sp_over_time = completed_sp_ts
    m.cumulative_issues = cum_issues
    m.cumulative_unestimated = cum_unest
