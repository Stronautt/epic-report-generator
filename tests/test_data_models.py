"""Tests for epic_report_generator.core.data_models."""

from __future__ import annotations

from datetime import date, datetime, timezone

from epic_report_generator.core.data_models import (
    EpicData,
    EpicMetrics,
    JiraIssue,
    ReportConfig,
    ReportData,
)


class TestJiraIssue:
    """Verify JiraIssue dataclass fields."""

    def test_creation(self) -> None:
        issue = JiraIssue(
            key="PROJ-1",
            summary="Do the thing",
            status="Open",
            status_category="To Do",
            resolution=None,
            issue_type="Story",
            story_points=3.0,
            created=datetime(2024, 1, 1, tzinfo=timezone.utc),
            resolved=None,
            assignee="Alice",
        )
        assert issue.key == "PROJ-1"
        assert issue.story_points == 3.0
        assert issue.resolved is None

    def test_nullable_fields(self) -> None:
        issue = JiraIssue(
            key="X-1", summary="", status="", status_category="To Do",
            resolution=None, issue_type="Bug", story_points=None,
            created=None, resolved=None, assignee=None,
        )
        assert issue.story_points is None
        assert issue.assignee is None
        assert issue.created is None


class TestEpicData:
    """Verify EpicData defaults and children list."""

    def test_default_lists(self) -> None:
        epic = EpicData(
            key="E-1", summary="Epic", status="Open",
            priority=None, assignee=None, reporter=None,
            created=None, updated=None,
        )
        assert epic.labels == []
        assert epic.fix_versions == []
        assert epic.children == []

    def test_children_not_shared(self) -> None:
        """Default factory must produce independent lists."""
        a = EpicData(key="A-1", summary="", status="", priority=None,
                     assignee=None, reporter=None, created=None, updated=None)
        b = EpicData(key="B-1", summary="", status="", priority=None,
                     assignee=None, reporter=None, created=None, updated=None)
        a.children.append(
            JiraIssue(key="C-1", summary="", status="", status_category="To Do",
                      resolution=None, issue_type="Task", story_points=None,
                      created=None, resolved=None, assignee=None)
        )
        assert len(b.children) == 0


class TestEpicMetrics:
    """Verify EpicMetrics defaults."""

    def test_defaults(self) -> None:
        m = EpicMetrics()
        assert m.total_issues == 0
        assert m.progress == 0.0
        assert m.avg_cycle_time_days is None
        assert m.velocity_sp_per_week is None
        assert m.forecast_date is None
        assert m.dates == []

    def test_time_series_lists_independent(self) -> None:
        a = EpicMetrics()
        b = EpicMetrics()
        a.dates.append(date(2024, 1, 1))
        assert b.dates == []


class TestReportConfig:
    """Verify ReportConfig defaults."""

    def test_defaults(self) -> None:
        cfg = ReportConfig()
        assert cfg.title == "Epic Progress Report"
        assert cfg.story_points_field == "story_points"
        assert cfg.epic_link_field == "customfield_10014"
        assert cfg.dark_mode is False
        assert cfg.confidential is False
        assert cfg.report_date == date.today()


class TestReportData:
    """Verify ReportData defaults."""

    def test_empty_report(self) -> None:
        cfg = ReportConfig(project_key="PROJ", epic_keys=["PROJ-1"])
        report = ReportData(config=cfg)
        assert report.epics == []
        assert report.metrics == []
        assert report.errors == []
