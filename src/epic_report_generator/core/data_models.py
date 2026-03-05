"""Data models for Epic Report Generator."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Literal

# Locale-independent English month names — shared across PDF, chart, and UI code.
MONTHS_ABBR = [
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

MONTHS_FULL = [
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


def fmt_date_en(d: date, fmt: str) -> str:
    """Format a date using English month names regardless of system locale.

    Supports ``%B`` (full month) and ``%b`` (abbreviated month); all other
    format codes are delegated to :py:meth:`date.strftime`.
    """
    result = fmt.replace("%B", MONTHS_FULL[d.month - 1])
    result = result.replace("%b", MONTHS_ABBR[d.month - 1])
    return d.strftime(result)


@dataclass
class SprintInfo:
    """Sprint metadata extracted from a Jira issue's sprint field."""

    name: str
    start_date: date | None = None
    end_date: date | None = None
    state: str = ""


@dataclass
class JiraIssue:
    """A single Jira issue (child of an Epic)."""

    key: str
    summary: str
    status: str
    status_category: str  # "To Do", "In Progress", "Done"
    resolution: str | None
    issue_type: str
    story_points: float | None
    created: datetime | None
    resolved: datetime | None
    assignee: str | None
    parent_key: str | None = None
    start_date: date | None = None
    due_date: date | None = None
    timeline_start: date | None = None
    timeline_end: date | None = None
    sprints: list[SprintInfo] = field(default_factory=list)
    progress: float = 0.0
    effective_weight: float = 1.0
    is_subtask: bool = False


@dataclass
class EpicData:
    """Full data for a single Jira Epic, including its child issues."""

    key: str
    summary: str
    status: str
    priority: str | None
    assignee: str | None
    reporter: str | None
    created: datetime | None
    updated: datetime | None
    labels: list[str] = field(default_factory=list)
    fix_versions: list[str] = field(default_factory=list)
    children: list[JiraIssue] = field(default_factory=list)
    start_date: date | None = None
    due_date: date | None = None
    timeline_start: date | None = None
    timeline_end: date | None = None


@dataclass
class ReportItem:
    """A single user input unit for the report — either an epic key or a label."""

    kind: Literal["epic", "label"]
    key: str
    display_name: str = ""
    scope_certainty: str | None = None  # None, "Low", "Medium", "High"


@dataclass
class TimelineItem:
    """Data for a single bar in the timeline Gantt chart."""

    name: str
    start_date: date | None = None
    end_date: date | None = None
    scope_certainty: str | None = None
    progress: float = 0.0
    is_child: bool = False
    group: str = ""


@dataclass
class MilestoneItem:
    """A fix version marker on the timeline chart."""

    name: str
    release_date: date


@dataclass
class EpicMetrics:
    """Calculated metrics for a single Epic."""

    total_issues: int = 0
    completed_issues: int = 0
    open_issues: int = 0
    unestimated_issues: int = 0
    total_sp: float = 0.0
    completed_sp: float = 0.0
    remaining_sp: float = 0.0
    progress: float = 0.0
    avg_cycle_time_days: float | None = None
    velocity_sp_per_week: float | None = None
    scope_change_pct: float | None = None
    blocked_issues: int = 0
    forecast_date: date | None = None
    estimation_unit: str = "SP"
    scope_certainty: str | None = None

    # Time-series data for charts
    dates: list[date] = field(default_factory=list)
    total_sp_over_time: list[float] = field(default_factory=list)
    completed_sp_over_time: list[float] = field(default_factory=list)
    cumulative_issues: list[int] = field(default_factory=list)
    cumulative_unestimated: list[int] = field(default_factory=list)


@dataclass
class ReportConfig:
    """Configuration for a report generation run."""

    project_key: str = ""
    epic_keys: list[str] = field(default_factory=list)
    items: list[ReportItem] = field(default_factory=list)
    title: str = "Epic Progress Report"
    author: str = ""
    project_display_name: str = ""
    report_date: date = field(default_factory=date.today)
    confidential: bool = False
    company_name: str = ""
    estimation_method: str = "story_points"  # "story_points" or "time_days"
    progress_method: str = "combined"  # "combined", "issues_only", or "estimates_only"
    story_points_field: str = "story_points"
    epic_link_field: str = "customfield_10014"
    start_date_field: str = "startdate"
    due_date_field: str = "duedate"
    timeline_start_field: str = "startdate"
    timeline_end_field: str = "duedate"
    timeline_hard_start: date | None = None
    timeline_hard_end: date | None = None
    include_subtasks: bool = True
    include_subtasks_in_timeline: bool = False
    show_epic_stories_on_timeline: bool = False
    show_subtasks_on_timeline: bool = False
    expand_label_details: bool = True
    show_additional_metrics: bool = True
    show_timeline_chart: bool = True  # include/exclude the Gantt timeline page
    dark_mode: bool = False


def collect_child_timeline_dates(
    child: JiraIssue,
    tl_starts: list[date],
    tl_ends: list[date],
) -> None:
    """Append timeline date candidates from a child issue into *tl_starts* / *tl_ends*.

    Cascade order: explicit timeline field → sprint dates → start_date/due_date.
    All eligible sprint dates are appended so callers can take min/max across
    the full set.  This mirrors the Jira Cloud Timeline behaviour which derives
    epic ranges from child sprint assignments when no explicit date fields are set.

    Args:
        child: The child issue whose timeline dates to collect.
        tl_starts: Accumulator list for timeline start date candidates.
        tl_ends: Accumulator list for timeline end date candidates.
    """
    if child.timeline_start:
        tl_starts.append(child.timeline_start)
    else:
        for sp in child.sprints:
            if sp.start_date:
                tl_starts.append(sp.start_date)
        if child.start_date:
            tl_starts.append(child.start_date)

    if child.timeline_end:
        tl_ends.append(child.timeline_end)
    else:
        for sp in child.sprints:
            if sp.end_date:
                tl_ends.append(sp.end_date)
        if child.due_date:
            tl_ends.append(child.due_date)


@dataclass
class ReportData:
    """All data needed to render the final PDF report."""

    config: ReportConfig
    epics: list[EpicData] = field(default_factory=list)
    metrics: list[EpicMetrics] = field(default_factory=list)
    resolved_items: list[tuple[ReportItem, EpicData, EpicMetrics]] = field(
        default_factory=list
    )
    label_source_epics: dict[str, list[tuple[EpicData, EpicMetrics]]] = field(
        default_factory=dict
    )
    fix_version_dates: dict[str, date | None] = field(default_factory=dict)
    sprints: list[SprintInfo] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
