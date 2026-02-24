"""Progress, velocity, cycle-time, and forecasting calculations."""

from __future__ import annotations

import logging
from datetime import date, timedelta

from epic_report_generator.core.data_models import EpicData, EpicMetrics, JiraIssue

logger = logging.getLogger(__name__)

# -- Named constants ----------------------------------------------------------

PROGRESS_COMBINED = "combined"
PROGRESS_ISSUES_ONLY = "issues_only"

STATUS_DONE = "Done"

DEFAULT_WEIGHT = 1.0
PROGRESS_MIN = 0.0
PROGRESS_MAX = 100.0
PROGRESS_DONE = 100.0


def _normalise_progress_method(method: str) -> str:
    """Map legacy progress method values to current constants.

    Treats ``"story_points_only"`` as ``PROGRESS_ISSUES_ONLY`` for backward
    compatibility with configs saved before the rename.
    """
    if method == "story_points_only":
        return PROGRESS_ISSUES_ONLY
    return method


# -- Public API ---------------------------------------------------------------


def calculate_metrics(
    epic: EpicData,
    estimation_method: str = "story_points",
    progress_method: str = PROGRESS_COMBINED,
) -> EpicMetrics:
    """Compute all metrics for a single Epic from its child issues.

    *estimation_method* controls how issue estimates are derived:

    * ``"story_points"`` — use the ``story_points`` field (default).
    * ``"time_days"`` — use ``(due_date - start_date).days``.

    *progress_method* controls the progress formula:

    * ``"combined"`` — bottom-up weighted average × (done_issues/total_issues).
    * ``"issues_only"`` — bottom-up weighted average with weight = 1.0 for all
      items (purely counts open vs done).

    Progress is computed **bottom-up**: leaf issues get 100% if Done else 0%.
    Parents aggregate their subtasks' progress via weighted average.  The epic
    progress is the weighted average of its direct children's progress.
    """
    progress_method = _normalise_progress_method(progress_method)
    children = epic.children
    m = EpicMetrics()
    m.estimation_unit = "Days" if estimation_method == "time_days" else "SP"

    if not children:
        logger.debug("Epic %s has no children — returning empty metrics", epic.key)
        return m

    use_estimates = progress_method != PROGRESS_ISSUES_ONLY

    # Pre-compute direct estimates once per child
    direct_estimates: dict[str, float | None] = {
        c.key: _get_estimate(c, estimation_method) for c in children
    }

    # Build parent→subtasks mapping (only among this epic's children)
    child_key_set = {c.key for c in children}
    parent_to_subs: dict[str, list[JiraIssue]] = {}
    subtask_keys: set[str] = set()
    for c in children:
        if c.parent_key and c.parent_key in child_key_set:
            parent_to_subs.setdefault(c.parent_key, []).append(c)
            subtask_keys.add(c.key)

    # Compute bottom-up progress for every issue and set .progress / .effective_weight
    _compute_all_issue_progress(
        children, direct_estimates, parent_to_subs, use_estimates
    )

    # Direct children of the epic (not subtasks of other children)
    direct_children = [c for c in children if c.key not in subtask_keys]

    # Epic progress = weighted average of direct children's progress
    weighted_sum = sum(c.progress * c.effective_weight for c in direct_children)
    weight_total = sum(c.effective_weight for c in direct_children)
    raw_progress = weighted_sum / weight_total if weight_total > 0 else PROGRESS_MIN

    # Apply progress method
    m.total_issues = len(children)
    m.completed_issues = sum(1 for c in children if c.status_category == STATUS_DONE)
    m.open_issues = m.total_issues - m.completed_issues

    if progress_method == PROGRESS_COMBINED and m.total_issues > 0:
        issue_ratio = m.completed_issues / m.total_issues
        m.progress = _clamp_progress(raw_progress * issue_ratio)
    else:
        m.progress = _clamp_progress(raw_progress)

    # SP display fields: use effective estimates, exclude subtasks accounted
    # for through their parent
    accounted_keys: set[str] = set()
    effective_est: dict[str, float | None] = {}
    effective_done: dict[str, float] = {}

    for c in children:
        direct = direct_estimates[c.key]
        if direct is not None or c.key not in parent_to_subs:
            effective_est[c.key] = direct
            effective_done[c.key] = (
                direct
                if (direct is not None and c.status_category == STATUS_DONE)
                else 0.0
            )
            continue

        # Unestimated parent with subtasks — derive from subtask completion
        subs = parent_to_subs[c.key]
        sub_ests = [direct_estimates.get(s.key) for s in subs]

        if any(e is not None for e in sub_ests):
            effective_est[c.key] = sum(e for e in sub_ests if e is not None)
            effective_done[c.key] = sum(
                float(direct_estimates[s.key])  # type: ignore[arg-type]
                for s in subs
                if direct_estimates.get(s.key) is not None
                and s.status_category == STATUS_DONE
            )
        else:
            effective_est[c.key] = float(len(subs))
            effective_done[c.key] = float(
                sum(1 for s in subs if s.status_category == STATUS_DONE)
            )
        accounted_keys.update(s.key for s in subs)

    non_accounted = [c for c in children if c.key not in accounted_keys]
    m.unestimated_issues = sum(
        1 for c in non_accounted if effective_est.get(c.key) is None
    )
    m.total_sp = sum(
        float(effective_est[c.key])  # type: ignore[arg-type]
        for c in non_accounted
        if effective_est.get(c.key) is not None
    )
    m.completed_sp = sum(
        effective_done.get(c.key, 0.0)
        for c in non_accounted
        if effective_est.get(c.key) is not None
    )
    m.remaining_sp = m.total_sp - m.completed_sp

    m.avg_cycle_time_days = _avg_cycle_time(children)
    m.velocity_sp_per_week = _velocity(children, estimation_method, weeks=4)
    m.scope_change_pct = _scope_change(children)
    m.blocked_issues = sum(
        1
        for c in children
        if "blocked" in c.status.lower() and c.status_category != STATUS_DONE
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
    progress_method: str = PROGRESS_COMBINED,
) -> tuple[EpicData, EpicMetrics]:
    """Merge multiple epics into a single synthetic epic and compute metrics.

    Children are merged with key-based deduplication.  The label-group progress
    is computed as the weighted average of per-epic progress values (each
    weighted by the sum of its direct children's effective weights), rather than
    flattening all children and re-computing.
    """
    progress_method = _normalise_progress_method(progress_method)
    seen: set[str] = set()
    merged_children: list[JiraIssue] = []
    all_labels: list[str] = []
    all_fix_versions: list[str] = []
    start_dates: list[date] = []
    due_dates: list[date] = []
    tl_starts: list[date] = []
    tl_ends: list[date] = []

    for epic in epics:
        all_labels.extend(epic.labels)
        all_fix_versions.extend(epic.fix_versions)
        if epic.start_date:
            start_dates.append(epic.start_date)
        if epic.due_date:
            due_dates.append(epic.due_date)
        if epic.timeline_start:
            tl_starts.append(epic.timeline_start)
        if epic.timeline_end:
            tl_ends.append(epic.timeline_end)
        for child in epic.children:
            if child.key not in seen:
                seen.add(child.key)
                merged_children.append(child)

    keys = [e.key for e in epics]
    # Always include child dates so the synthetic epic spans the full range
    # of all source epics and their children.
    # Per-child: prefer start_date/due_date, fall back to created/resolved
    # so every child contributes to the range.
    # Timeline: cascade timeline fields → sprint dates → start_date/due_date
    # (matches Jira Cloud Timeline behaviour).
    for c in merged_children:
        if c.start_date:
            start_dates.append(c.start_date)
        elif c.created:
            start_dates.append(c.created.date())
        if c.due_date:
            due_dates.append(c.due_date)
        elif c.resolved and c.status_category == STATUS_DONE:
            due_dates.append(c.resolved.date())
        # Timeline start cascade
        if c.timeline_start:
            tl_starts.append(c.timeline_start)
        else:
            for sp in c.sprints:
                if sp.start_date:
                    tl_starts.append(sp.start_date)
            if c.start_date:
                tl_starts.append(c.start_date)
        # Timeline end cascade
        if c.timeline_end:
            tl_ends.append(c.timeline_end)
        else:
            for sp in c.sprints:
                if sp.end_date:
                    tl_ends.append(sp.end_date)
            if c.due_date:
                tl_ends.append(c.due_date)
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
        timeline_start=min(tl_starts) if tl_starts else None,
        timeline_end=max(tl_ends) if tl_ends else None,
    )

    # Compute per-epic metrics to get individual progress values, then
    # override label-group progress as weighted average of source epic progress.
    epic_metrics_list: list[EpicMetrics] = []
    for epic in epics:
        epic_metrics_list.append(
            calculate_metrics(epic, estimation_method, progress_method)
        )

    # Compute the label-group metrics from the merged synthetic epic
    m = calculate_metrics(synthetic, estimation_method, progress_method)

    # Override progress: weighted average of per-epic progress values
    if epic_metrics_list:
        # Each epic's weight = sum of its direct children's effective weights
        epic_weights: list[float] = []
        for epic in epics:
            child_key_set = {c.key for c in epic.children}
            subtask_keys: set[str] = set()
            for c in epic.children:
                if c.parent_key and c.parent_key in child_key_set:
                    subtask_keys.add(c.key)
            direct_children = [c for c in epic.children if c.key not in subtask_keys]
            epic_weights.append(
                sum(c.effective_weight for c in direct_children)
                if direct_children
                else DEFAULT_WEIGHT
            )

        weighted_sum = sum(
            em.progress * w for em, w in zip(epic_metrics_list, epic_weights)
        )
        weight_total = sum(epic_weights)
        if weight_total > 0:
            m.progress = _clamp_progress(weighted_sum / weight_total)

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


def _clamp_progress(value: float) -> float:
    """Clamp a progress value to [0, 100]."""
    return max(PROGRESS_MIN, min(PROGRESS_MAX, value))


def _compute_all_issue_progress(
    children: list[JiraIssue],
    direct_estimates: dict[str, float | None],
    parent_to_subs: dict[str, list[JiraIssue]],
    use_estimates: bool,
) -> None:
    """Compute bottom-up progress for every issue.

    Sets ``.progress`` and ``.effective_weight`` on each issue.

    Args:
        children: All child issues of the epic (flat list).
        direct_estimates: Pre-computed estimate per issue key.
        parent_to_subs: Mapping of parent key → list of subtask issues.
        use_estimates: If True, weight = estimate (SP/days); if False, weight = 1.0.

    Side effects:
        Sets ``issue.progress`` and ``issue.effective_weight`` on every issue
        in *children*.
    """
    computed: set[str] = set()

    def _compute(issue: JiraIssue) -> tuple[float, float]:
        """Recursively compute (progress, effective_weight) for an issue.

        Returns:
            A tuple of (progress_pct, effective_weight).
        """
        if issue.key in computed:
            return issue.progress, issue.effective_weight

        subs = parent_to_subs.get(issue.key, [])
        est = direct_estimates.get(issue.key)

        if not subs:
            # Leaf node: 100% if Done, 0% otherwise
            progress = (
                PROGRESS_DONE if issue.status_category == STATUS_DONE else PROGRESS_MIN
            )
            weight = (
                (est if est is not None else DEFAULT_WEIGHT)
                if use_estimates
                else DEFAULT_WEIGHT
            )
            issue.progress = progress
            issue.effective_weight = weight
            computed.add(issue.key)
            return progress, weight

        # Parent with subtasks: aggregate children bottom-up
        weighted_sum = 0.0
        weight_total = 0.0
        for sub in subs:
            sub_progress, sub_weight = _compute(sub)
            weighted_sum += sub_progress * sub_weight
            weight_total += sub_weight

        progress = weighted_sum / weight_total if weight_total > 0 else PROGRESS_MIN
        # Parent weight: own estimate if available, else sum of subtask weights
        if use_estimates:
            weight = est if est is not None else weight_total
        else:
            weight = DEFAULT_WEIGHT
        issue.progress = progress
        issue.effective_weight = weight
        computed.add(issue.key)
        return progress, weight

    for c in children:
        _compute(c)


def _avg_cycle_time(children: list[JiraIssue]) -> float | None:
    durations: list[float] = []
    for c in children:
        if c.status_category == STATUS_DONE and c.created and c.resolved:
            delta = c.resolved - c.created
            durations.append(delta.total_seconds() / 86400)
    return sum(durations) / len(durations) if durations else None


def _velocity(
    children: list[JiraIssue],
    estimation_method: str = "story_points",
    weeks: int = 4,
) -> float | None:
    """Estimate completed per week over the last *weeks* weeks."""
    cutoff_date = date.today() - timedelta(weeks=weeks)
    sp = sum(
        est
        for c in children
        if (est := _get_estimate(c, estimation_method)) is not None
        and c.status_category == STATUS_DONE
        and c.resolved
        and c.resolved.date() >= cutoff_date
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
    """Build daily time-series arrays for the trend chart.

    Uses an O(n log n + d) algorithm with sorted event lists and incremental
    pointers instead of the previous O(n × d) approach.
    """
    dated = [(c, c.created) for c in children if c.created is not None]
    if not dated:
        return

    min_date = min(dt for _, dt in dated).date()
    max_date = date.today()
    if min_date >= max_date:
        return

    # Pre-compute estimates once
    est_map: dict[str, float | None] = {
        c.key: _get_estimate(c, estimation_method) for c, _ in dated
    }

    # Sort by creation date for incremental pointer
    created_sorted = sorted(dated, key=lambda pair: pair[1])
    # Build resolved list: (resolved_date as date, child) sorted by resolved date.
    # Use .date() to avoid timezone-aware vs naive datetime comparison issues.
    resolved_sorted = sorted(
        [
            (c.resolved.date(), c)
            for c, _ in dated
            if c.status_category == STATUS_DONE and c.resolved
        ],
        key=lambda pair: pair[0],
    )

    num_days = (max_date - min_date).days + 1
    dates: list[date] = []
    total_sp_ts: list[float] = []
    completed_sp_ts: list[float] = []
    cum_issues: list[int] = []
    cum_unest: list[int] = []

    # Running totals
    running_total_sp = 0.0
    running_done_sp = 0.0
    running_issues = 0
    running_unest = 0

    created_ptr = 0
    resolved_ptr = 0

    for i in range(num_days):
        day = min_date + timedelta(days=i)

        # Advance created pointer
        while created_ptr < len(created_sorted):
            c, dt = created_sorted[created_ptr]
            if dt.date() <= day:
                est = est_map[c.key]
                running_total_sp += est or 0
                running_issues += 1
                if est is None:
                    running_unest += 1
                created_ptr += 1
            else:
                break

        # Advance resolved pointer (compare date-to-date, no timezone issues)
        while resolved_ptr < len(resolved_sorted):
            resolved_date, c = resolved_sorted[resolved_ptr]
            if resolved_date <= day:
                est = est_map[c.key]
                running_done_sp += est or 0
                resolved_ptr += 1
            else:
                break

        dates.append(day)
        total_sp_ts.append(running_total_sp)
        completed_sp_ts.append(running_done_sp)
        cum_issues.append(running_issues)
        cum_unest.append(running_unest)

    m.dates = dates
    m.total_sp_over_time = total_sp_ts
    m.completed_sp_over_time = completed_sp_ts
    m.cumulative_issues = cum_issues
    m.cumulative_unestimated = cum_unest
