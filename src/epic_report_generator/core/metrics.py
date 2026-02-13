"""Progress, velocity, cycle-time, and forecasting calculations."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from epic_report_generator.core.data_models import EpicData, EpicMetrics, JiraIssue

logger = logging.getLogger(__name__)


def calculate_metrics(epic: EpicData) -> EpicMetrics:
    """Compute all metrics for a single Epic from its child issues."""
    children = epic.children
    m = EpicMetrics()

    if not children:
        logger.debug("Epic %s has no children — returning empty metrics", epic.key)
        return m

    m.total_issues = len(children)
    m.completed_issues = sum(1 for c in children if c.status_category == "Done")
    m.open_issues = m.total_issues - m.completed_issues
    m.unestimated_issues = sum(1 for c in children if not c.story_points)
    m.total_sp = sum(c.story_points for c in children if c.story_points)
    m.completed_sp = sum(
        c.story_points for c in children if c.story_points and c.status_category == "Done"
    )
    m.remaining_sp = m.total_sp - m.completed_sp
    m.progress = _progress(m.completed_sp, m.total_sp, m.completed_issues, m.total_issues)
    m.avg_cycle_time_days = _avg_cycle_time(children)
    m.velocity_sp_per_week = _velocity(children, weeks=4)
    m.scope_change_pct = _scope_change(children)
    m.blocked_issues = sum(
        1 for c in children if "blocked" in c.status.lower() and c.status_category != "Done"
    )
    m.forecast_date = _forecast(m.remaining_sp, m.velocity_sp_per_week)

    # Build time-series
    _build_time_series(m, children)

    logger.debug(
        "Metrics for %s: progress=%.1f%%, %d/%d issues done, %.0f/%.0f SP",
        epic.key, m.progress, m.completed_issues, m.total_issues,
        m.completed_sp, m.total_sp,
    )
    return m


# -- helpers ------------------------------------------------------------------


def _progress(
    completed_sp: float, total_sp: float, completed_issues: int, total_issues: int
) -> float:
    if total_issues == 0:
        return 0.0
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


def _velocity(children: list[JiraIssue], weeks: int = 4) -> float | None:
    """SP completed per week over the last *weeks* weeks."""
    cutoff = datetime.now().astimezone() - timedelta(weeks=weeks)
    sp = sum(
        c.story_points
        for c in children
        if c.story_points
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


def _build_time_series(m: EpicMetrics, children: list[JiraIssue]) -> None:
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

        created_by_day = [
            c for c, dt in dated if dt.date() <= day
        ]
        done_by_day = [
            c for c in created_by_day
            if c.status_category == "Done" and c.resolved and c.resolved <= day_end
        ]

        dates.append(day)
        total_sp_ts.append(sum(c.story_points or 0 for c in created_by_day))
        completed_sp_ts.append(sum(c.story_points or 0 for c in done_by_day))
        cum_issues.append(len(created_by_day))
        cum_unest.append(sum(1 for c in created_by_day if not c.story_points))

        day += timedelta(days=1)

    m.dates = dates
    m.total_sp_over_time = total_sp_ts
    m.completed_sp_over_time = completed_sp_ts
    m.cumulative_issues = cum_issues
    m.cumulative_unestimated = cum_unest
