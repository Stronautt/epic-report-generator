"""Data models for Epic Report Generator."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime


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
    title: str = "Epic Progress Report"
    author: str = ""
    project_display_name: str = ""
    report_date: date = field(default_factory=date.today)
    confidential: bool = False
    company_name: str = ""
    story_points_field: str = "story_points"
    epic_link_field: str = "customfield_10014"
    dark_mode: bool = False


@dataclass
class ReportData:
    """All data needed to render the final PDF report."""

    config: ReportConfig
    epics: list[EpicData] = field(default_factory=list)
    metrics: list[EpicMetrics] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
