"""Progress, velocity, cycle-time, and forecasting calculations."""

from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta
from typing import Any

from epic_report_generator.core.data_models import (
    STATUS_DONE,
    EpicData,
    EpicMetrics,
    JiraIssue,
    collect_child_estimation_dates,
    collect_child_timeline_dates,
)

logger = logging.getLogger(__name__)

PROGRESS_COMBINED = "combined"
PROGRESS_ISSUES_ONLY = "issues_only"
PROGRESS_ESTIMATES_ONLY = "estimates_only"

DEFAULT_WEIGHT = 1.0
PROGRESS_MIN = 0.0
PROGRESS_MAX = 100.0
PROGRESS_DONE = 100.0

_SECONDS_PER_DAY = 86400
_SCOPE_CHANGE_THRESHOLD_DAYS = 7


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
    *,
    reference_date: date | None = None,
    window_start: date | None = None,
    window_end: date | None = None,
) -> EpicMetrics:
    """Compute all metrics for a single Epic from its child issues.

    *estimation_method* controls how issue estimates are derived:

    * ``"story_points"`` — use the ``story_points`` field (default).
    * ``"time_days"`` — use ``(due_date - start_date).days``.

    *progress_method* controls the progress formula:

    * ``"combined"`` — bottom-up weighted average × (done_issues/total_issues).
    * ``"issues_only"`` — bottom-up weighted average with weight = 1.0 for all
      items (purely counts open vs done).
    * ``"estimates_only"`` — bottom-up weighted average using estimates as
      weights (like combined) but without the issue-count ratio multiplier.
      Unestimated items are excluded (weight = 0.0).

    *window_start* / *window_end* are the report's fixed (hard) timeline dates.
    When set, the **time-based** metrics are capped to that window so the
    per-epic page never reflects activity outside it: ``window_end`` caps the
    "as of" point for velocity, forecasting, and the trend chart, while both
    bounds scope ``avg_cycle_time`` (by resolution date) and ``scope_change``
    (by creation date) and clip the trend chart's start.  Progress and the
    estimate roll-ups are *not* windowed — they always reflect the full epic.
    Leaving both ``None`` keeps the historical, unbounded behaviour exactly.

    Progress is computed **bottom-up**: leaf issues get 100% if Done else 0%.
    Parents aggregate their subtasks' progress via weighted average.  The epic
    progress is the weighted average of its direct children's progress.
    """
    progress_method = _normalise_progress_method(progress_method)
    reference_date = reference_date or date.today()
    # A fixed end date caps the "as of" instant for every time-based metric
    # (velocity lookback, forecast origin, trend-chart end) so they line up with
    # the Gantt's fixed axis instead of running on to today.
    if window_end is not None and window_end < reference_date:
        reference_date = window_end
    # in_estimate=False issues are dropped from metrics entirely (no weight, no
    # done/total count, no velocity/trend contribution), mirroring the old
    # include_subtasks=False.  `show` is display-only and handled elsewhere.
    children = [c for c in epic.children if c.in_estimate]
    m = EpicMetrics()
    m.estimation_unit = "Days" if estimation_method == "time_days" else "SP"

    # Shown-but-unestimated children are excluded from the metrics pass below, so
    # their `.progress` would otherwise stay a hard 0.0 even when Done.  Give each
    # a leaf display value so the timeline bar / nested summary row reflects real
    # completion (display only — they stay out of the aggregate).  Runs before the
    # empty-`children` early return so it still applies when an epic has only
    # shown-but-unestimated children.
    for c in epic.children:
        if c.show and not c.in_estimate:
            c.progress = (
                PROGRESS_DONE if c.status_category == STATUS_DONE else PROGRESS_MIN
            )

    if not children:
        logger.debug("Epic %s has no children — returning empty metrics", epic.key)
        return m

    use_estimates = progress_method != PROGRESS_ISSUES_ONLY

    # Single pass: build estimates, key set, and parent→subtask mapping
    direct_estimates: dict[str, float | None] = {}
    child_key_set: set[str] = set()
    for c in children:
        direct_estimates[c.key] = _get_estimate(c, estimation_method)
        child_key_set.add(c.key)

    parent_to_subs: dict[str, list[JiraIssue]] = {}
    subtask_keys: set[str] = set()
    for c in children:
        pk = _hier_parent(c)
        if pk and pk in child_key_set:
            parent_to_subs.setdefault(pk, []).append(c)
            subtask_keys.add(c.key)

    omit_unestimated = progress_method == PROGRESS_ESTIMATES_ONLY
    _compute_all_issue_progress(
        children, direct_estimates, parent_to_subs, use_estimates, omit_unestimated
    )

    weighted_sum = 0.0
    weight_total = 0.0
    completed_issues = 0
    for c in children:
        if c.status_category == STATUS_DONE:
            completed_issues += 1
        if c.key not in subtask_keys:
            weighted_sum += c.progress * c.effective_weight
            weight_total += c.effective_weight
    raw_progress = weighted_sum / weight_total if weight_total > 0 else PROGRESS_MIN

    # Apply progress method
    m.total_issues = len(children)
    m.completed_issues = completed_issues
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
                est
                for s in subs
                if (est := direct_estimates.get(s.key)) is not None
                and s.status_category == STATUS_DONE
            )
        else:
            effective_est[c.key] = float(len(subs))
            effective_done[c.key] = float(
                sum(1 for s in subs if s.status_category == STATUS_DONE)
            )
        accounted_keys.update(s.key for s in subs)

    unestimated = 0
    total_sp = 0.0
    completed_sp = 0.0
    for c in children:
        if c.key in accounted_keys:
            continue
        est = effective_est.get(c.key)
        if est is None:
            unestimated += 1
        else:
            total_sp += est
            completed_sp += effective_done.get(c.key, 0.0)
    m.unestimated_issues = unestimated
    m.total_sp = total_sp
    m.completed_sp = completed_sp
    m.remaining_sp = total_sp - completed_sp

    m.avg_cycle_time_days = _avg_cycle_time(
        children, window_start=window_start, window_end=window_end
    )
    m.velocity_sp_per_week = _velocity(
        children,
        estimation_method,
        weeks=4,
        reference_date=reference_date,
        window_start=window_start,
    )
    m.scope_change_pct = _scope_change(
        children, window_start=window_start, window_end=window_end
    )
    m.blocked_issues = sum(
        1
        for c in children
        if "blocked" in c.status.lower() and c.status_category != STATUS_DONE
    )
    m.forecast_date = _forecast(
        m.remaining_sp, m.velocity_sp_per_week, reference_date=reference_date
    )

    # Build time-series
    _build_time_series(
        m,
        children,
        estimation_method,
        reference_date=reference_date,
        window_start=window_start,
    )

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
    *,
    source_metrics_out: list[EpicMetrics] | None = None,
    reference_date: date | None = None,
    window_start: date | None = None,
    window_end: date | None = None,
) -> tuple[EpicData, EpicMetrics]:
    """Merge multiple epics into a single synthetic epic and compute metrics.

    Children are merged with key-based deduplication.  The label-group progress
    is computed as the weighted average of per-epic progress values (each
    weighted by the sum of its direct children's effective weights), rather than
    flattening all children and re-computing.

    If *source_metrics_out* is provided (an empty list), it will be populated
    with the per-epic metrics computed during merging — one entry per epic in
    the same order as *epics*.  This avoids callers needing to recompute them.

    *window_start* / *window_end* (the report's fixed timeline dates) are passed
    through to every underlying :func:`calculate_metrics` call so both the
    per-epic source metrics and the merged label-group metrics cap their
    time-based figures to the fixed window.
    """
    progress_method = _normalise_progress_method(progress_method)
    reference_date = reference_date or date.today()
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
    # Expand date ranges to cover all merged children (estimation + timeline).
    for c in merged_children:
        collect_child_estimation_dates(c, start_dates, due_dates)
        # A tier-2 (sub-task) child expands the timeline range only when shown;
        # `show` already encodes the old include_subtasks_in_timeline flag.
        if c.display_tier == 2 and not c.show:
            continue
        collect_child_timeline_dates(c, tl_starts, tl_ends)
    if not due_dates and start_dates:
        due_dates = [reference_date]

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
            calculate_metrics(
                epic,
                estimation_method,
                progress_method,
                reference_date=reference_date,
                window_start=window_start,
                window_end=window_end,
            )
        )
    if source_metrics_out is not None:
        source_metrics_out.extend(epic_metrics_list)

    # Compute the label-group metrics from the merged synthetic epic
    m = calculate_metrics(
        synthetic,
        estimation_method,
        progress_method,
        reference_date=reference_date,
        window_start=window_start,
        window_end=window_end,
    )

    # Override progress: weighted average of per-epic progress values.
    # Reuses .effective_weight already set by the calculate_metrics calls above.
    if epic_metrics_list:
        epic_weights: list[float] = []
        for epic in epics:
            subtask_keys = _subtask_keys(epic.children)
            direct_children = [
                c
                for c in epic.children
                if c.in_estimate and c.key not in subtask_keys
            ]
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


def _hier_parent(issue: JiraIssue) -> str | None:
    """Effective parent key for hierarchy roll-up.

    Prefers the chain-resolved ``hierarchy_parent_key`` (set by N-tier traversal)
    and falls back to the native ``parent_key`` so the default 2-tier path — which
    never sets ``hierarchy_parent_key`` — behaves exactly as before.
    """
    return issue.hierarchy_parent_key or issue.parent_key


def _subtask_keys(children: list[JiraIssue]) -> set[str]:
    """Return keys of children whose parent is also among *children* (subtasks)."""
    child_key_set = {c.key for c in children}
    return {
        c.key for c in children if (pk := _hier_parent(c)) and pk in child_key_set
    }


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
    omit_unestimated: bool = False,
) -> None:
    """Compute bottom-up progress for every issue.

    Sets ``.progress`` and ``.effective_weight`` on each issue.

    Args:
        children: All child issues of the epic (flat list).
        direct_estimates: Pre-computed estimate per issue key.
        parent_to_subs: Mapping of parent key → list of subtask issues.
        use_estimates: If True, weight = estimate (SP/days); if False, weight = 1.0.
        omit_unestimated: If True, unestimated items get weight = 0.0
            instead of the default fallback.  Used by ``estimates_only``.

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
            if use_estimates:
                if est is not None:
                    weight = est
                elif omit_unestimated:
                    weight = 0.0
                else:
                    weight = DEFAULT_WEIGHT
            else:
                weight = DEFAULT_WEIGHT
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
            if est is not None:
                weight = est
            elif omit_unestimated:
                weight = weight_total
            else:
                weight = weight_total
        else:
            weight = DEFAULT_WEIGHT
        issue.progress = progress
        issue.effective_weight = weight
        computed.add(issue.key)
        return progress, weight

    for c in children:
        _compute(c)


def _avg_cycle_time(
    children: list[JiraIssue],
    *,
    window_start: date | None = None,
    window_end: date | None = None,
) -> float | None:
    """Average created→resolved duration (days) over Done issues.

    When a fixed window is given, only issues **resolved inside** it count, so
    the figure reflects work completed during the report period (the full
    created→resolved span is still measured, even if it begins before the
    window).
    """
    durations: list[float] = []
    for c in children:
        if c.status_category == STATUS_DONE and c.created and c.resolved:
            resolved_day = c.resolved.date()
            if window_start is not None and resolved_day < window_start:
                continue
            if window_end is not None and resolved_day > window_end:
                continue
            delta = c.resolved - c.created
            durations.append(delta.total_seconds() / _SECONDS_PER_DAY)
    return sum(durations) / len(durations) if durations else None


def _velocity(
    children: list[JiraIssue],
    estimation_method: str = "story_points",
    weeks: int = 4,
    *,
    reference_date: date | None = None,
    window_start: date | None = None,
) -> float | None:
    """Estimate completed per week over the last *weeks* weeks.

    The lookback ends at *reference_date* (already capped to the fixed window
    end by the caller) and only counts work resolved on or before it.  When
    *window_start* falls inside the lookback, the period is clamped to it and
    the per-week divisor shrinks to match, so a window narrower than *weeks*
    still yields a meaningful rate rather than dividing by a period that
    reaches outside the report.
    """
    ref = reference_date or date.today()
    cutoff_date = ref - timedelta(weeks=weeks)
    if window_start is not None and window_start > cutoff_date:
        cutoff_date = window_start
    period_weeks = (ref - cutoff_date).days / 7
    if period_weeks <= 0:
        return None
    sp = sum(
        est
        for c in children
        if (est := _get_estimate(c, estimation_method)) is not None
        and c.status_category == STATUS_DONE
        and c.resolved
        and cutoff_date <= c.resolved.date() <= ref
    )
    return sp / period_weeks if sp else None


def _scope_change(
    children: list[JiraIssue],
    *,
    window_start: date | None = None,
    window_end: date | None = None,
) -> float | None:
    """Percentage of issues added after the earliest issue.

    With a fixed window, only issues **created inside** it are considered, and
    they alone form the denominator — scope churn outside the report period is
    neither counted nor used as the baseline.  Without a window the denominator
    stays the full child count (legacy behaviour, undated issues included).
    """
    windowed = window_start is not None or window_end is not None
    in_window = [
        c
        for c in children
        if c.created is not None
        and (window_start is None or c.created.date() >= window_start)
        and (window_end is None or c.created.date() <= window_end)
    ]
    total = len(in_window) if windowed else len(children)
    if total < 2:
        return None
    dated = sorted(c.created for c in in_window)
    if len(dated) < 2:
        return None
    first_created = dated[0]
    threshold = first_created + timedelta(days=_SCOPE_CHANGE_THRESHOLD_DAYS)
    added_later = sum(1 for dt in dated if dt > threshold)
    return (added_later / total) * 100


def _forecast(
    remaining_sp: float,
    velocity: float | None,
    *,
    reference_date: date | None = None,
) -> date | None:
    if not velocity or velocity <= 0 or remaining_sp <= 0:
        return None
    weeks_remaining = remaining_sp / velocity
    return (reference_date or date.today()) + timedelta(weeks=weeks_remaining)


def _naive(dt: datetime) -> datetime:
    """Drop tz so Jira's aware timestamps compare with naive window/ref dates.

    Mixing an aware ``datetime`` with a naive one raises ``TypeError`` on
    subtraction/comparison. Stripping the offset keeps every event timestamp
    comparable and leaves ``.date()`` labels identical to the old daily path.
    """
    return dt.replace(tzinfo=None) if dt.tzinfo is not None else dt


def _build_time_series(
    m: EpicMetrics,
    children: list[JiraIssue],
    estimation_method: str = "story_points",
    *,
    reference_date: date | None = None,
    window_start: date | None = None,
) -> None:
    """Build the trend chart's time-series as one point **per changelog event**.

    Each scope/estimate/completion event (enter / sp-change / done) becomes a
    point at its **exact timestamp**, and the view-model positions x by time —
    matching Jira's burnup, where same-day events spread along a continuous
    axis instead of collapsing into one daily step.

    *window_start* clips the left edge to the fixed start date (the right edge
    is clipped by the caller capping *reference_date* to the fixed end). The
    cumulative running totals carry over: every event at or before the window
    start folds into the left-edge anchor, so the series is zoomed to the
    window, not recomputed as if earlier work never happened.
    """
    dated = [c for c in children if c.created is not None]
    if not dated:
        return

    min_date = min(c.created for c in dated).date()
    if window_start is not None and window_start > min_date:
        min_date = window_start
    max_date = reference_date or date.today()
    if min_date >= max_date:
        return

    # Continuous datetime bounds for the time-proportional x-axis. The left edge
    # is the earliest event instant (or the window start at midnight); the right
    # edge is the end of the reference day, so an event at any time on that day
    # is admitted while `.date()` still equals the reference date.
    range_start = min(_naive(c.created) for c in dated)
    if window_start is not None:
        ws = datetime.combine(window_start, time.min)
        if ws > range_start:
            range_start = ws
    range_end = datetime.combine(max_date, time.max)

    # Per-issue event timelines feed one chronological replay. When the changelog
    # was attached (story-point method + events present) the scope line steps on
    # every estimate change and completion is dated by the resolution event —
    # Jira-fidelity burnup. Otherwise each issue contributes a single scope point
    # at `created` (its final estimate) and a single done point at `resolved`,
    # reproducing the historical created/resolved approximation byte-for-byte.
    # Event kinds double as the same-day tiebreak order: 0=enter, 1=sp, 2=done.
    use_changelog = estimation_method != "time_days"
    events: list[tuple[datetime, int, int, Any]] = []
    for idx, c in enumerate(dated):
        if use_changelog and c.sp_history:
            events.append((_naive(c.created), 0, idx, c.sp_history[0][1]))
            for dt, val in c.sp_history[1:]:
                events.append((_naive(dt), 1, idx, val))
        else:
            events.append(
                (_naive(c.created), 0, idx, _get_estimate(c, estimation_method))
            )
        # Completion: prefer the changelog resolution toggles; fall back to the
        # resolved date so a missing/truncated changelog never loses a done event.
        done_hist = c.done_history
        if not done_hist and c.status_category == STATUS_DONE and c.resolved:
            done_hist = [(c.resolved, True)]
        for dt, is_done in done_hist:
            events.append((_naive(dt), 2, idx, is_done))
    events.sort(key=lambda e: (e[0], e[1]))

    sp_state: list[float | None] = [None] * len(dated)
    done_state: list[bool] = [False] * len(dated)
    running_total_sp = 0.0
    running_done_sp = 0.0
    running_issues = 0
    running_unest = 0

    def _apply(idx: int, kind: int, value: Any) -> None:
        nonlocal running_total_sp, running_done_sp, running_issues, running_unest
        if kind == 0:  # issue enters scope
            sp_state[idx] = value
            running_total_sp += value or 0
            running_issues += 1
            if value is None:
                running_unest += 1
        elif kind == 1:  # estimate changed
            old, new = sp_state[idx], value
            running_total_sp += (new or 0) - (old or 0)
            if done_state[idx]:
                running_done_sp += (new or 0) - (old or 0)
            if (old is None) != (new is None):
                running_unest += -1 if new is not None else 1
            sp_state[idx] = new
        else:  # done state toggled
            if value and not done_state[idx]:
                running_done_sp += sp_state[idx] or 0
                done_state[idx] = True
            elif not value and done_state[idx]:
                running_done_sp -= sp_state[idx] or 0
                done_state[idx] = False

    dates: list[datetime] = []
    total_sp_ts: list[float] = []
    completed_sp_ts: list[float] = []
    cum_issues: list[int] = []
    cum_unest: list[int] = []

    def _snapshot(t: datetime) -> None:
        dates.append(t)
        total_sp_ts.append(running_total_sp)
        completed_sp_ts.append(running_done_sp)
        cum_issues.append(running_issues)
        cum_unest.append(running_unest)

    ptr = 0
    # Left-edge anchor: fold every event at/before the window start into day-one
    # totals (carryover), then emit the baseline point.
    while ptr < len(events) and events[ptr][0] <= range_start:
        _, kind, idx, value = events[ptr]
        _apply(idx, kind, value)
        ptr += 1
    _snapshot(range_start)
    # One point per distinct event timestamp inside the window — simultaneous
    # events collapse into a single combined step (no zero-width jumps).
    while ptr < len(events) and events[ptr][0] <= range_end:
        t = events[ptr][0]
        while ptr < len(events) and events[ptr][0] == t:
            _, kind, idx, value = events[ptr]
            _apply(idx, kind, value)
            ptr += 1
        _snapshot(t)
    # Right-edge anchor holds the last totals to the plot edge (the staircase
    # would otherwise stop at the final event).
    if dates[-1] != range_end:
        _snapshot(range_end)

    m.dates = dates
    m.total_sp_over_time = total_sp_ts
    m.completed_sp_over_time = completed_sp_ts
    m.cumulative_issues = cum_issues
    m.cumulative_unestimated = cum_unest
