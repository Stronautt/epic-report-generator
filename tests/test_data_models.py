"""Tests for epic_report_generator.core.data_models."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from epic_report_generator.core.data_models import (
    ChildOverride,
    EpicData,
    EpicMetrics,
    JiraIssue,
    MilestoneItem,
    ReportConfig,
    ReportData,
    ReportItem,
    TimelineItem,
    average_certainty,
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
            key="X-1",
            summary="",
            status="",
            status_category="To Do",
            resolution=None,
            issue_type="Bug",
            story_points=None,
            created=None,
            resolved=None,
            assignee=None,
        )
        assert issue.story_points is None
        assert issue.assignee is None
        assert issue.created is None

    def test_progress_and_weight_defaults(self) -> None:
        issue = JiraIssue(
            key="X-1",
            summary="",
            status="",
            status_category="To Do",
            resolution=None,
            issue_type="Task",
            story_points=None,
            created=None,
            resolved=None,
            assignee=None,
        )
        assert issue.progress == 0.0
        assert issue.effective_weight == 1.0

    def test_date_fields_default_none(self) -> None:
        issue = JiraIssue(
            key="X-1",
            summary="",
            status="",
            status_category="To Do",
            resolution=None,
            issue_type="Task",
            story_points=None,
            created=None,
            resolved=None,
            assignee=None,
        )
        assert issue.start_date is None
        assert issue.due_date is None

    def test_date_fields_set(self) -> None:
        issue = JiraIssue(
            key="X-1",
            summary="",
            status="",
            status_category="To Do",
            resolution=None,
            issue_type="Task",
            story_points=None,
            created=None,
            resolved=None,
            assignee=None,
            start_date=date(2024, 1, 1),
            due_date=date(2024, 1, 10),
        )
        assert issue.start_date == date(2024, 1, 1)
        assert issue.due_date == date(2024, 1, 10)


class TestEpicData:
    """Verify EpicData defaults and children list."""

    def test_default_lists(self) -> None:
        epic = EpicData(
            key="E-1",
            summary="Epic",
            status="Open",
            priority=None,
            assignee=None,
            reporter=None,
            created=None,
            updated=None,
        )
        assert epic.labels == []
        assert epic.fix_versions == []
        assert epic.children == []

    def test_children_not_shared(self) -> None:
        """Default factory must produce independent lists."""
        a = EpicData(
            key="A-1",
            summary="",
            status="",
            priority=None,
            assignee=None,
            reporter=None,
            created=None,
            updated=None,
        )
        b = EpicData(
            key="B-1",
            summary="",
            status="",
            priority=None,
            assignee=None,
            reporter=None,
            created=None,
            updated=None,
        )
        a.children.append(
            JiraIssue(
                key="C-1",
                summary="",
                status="",
                status_category="To Do",
                resolution=None,
                issue_type="Task",
                story_points=None,
                created=None,
                resolved=None,
                assignee=None,
            )
        )
        assert len(b.children) == 0


class TestEpicDataDates:
    """Verify EpicData start_date/due_date fields."""

    def test_date_fields_default_none(self) -> None:
        epic = EpicData(
            key="E-1",
            summary="Epic",
            status="Open",
            priority=None,
            assignee=None,
            reporter=None,
            created=None,
            updated=None,
        )
        assert epic.start_date is None
        assert epic.due_date is None

    def test_date_fields_set(self) -> None:
        epic = EpicData(
            key="E-1",
            summary="Epic",
            status="Open",
            priority=None,
            assignee=None,
            reporter=None,
            created=None,
            updated=None,
            start_date=date(2024, 3, 1),
            due_date=date(2024, 6, 30),
        )
        assert epic.start_date == date(2024, 3, 1)
        assert epic.due_date == date(2024, 6, 30)


class TestReportItem:
    """Verify ReportItem dataclass."""

    def test_epic_item(self) -> None:
        item = ReportItem(kind="epic", key="PROJ-1")
        assert item.kind == "epic"
        assert item.key == "PROJ-1"
        assert item.display_name == ""
        assert item.scope_certainty is None

    def test_label_item_with_certainty(self) -> None:
        item = ReportItem(
            kind="label", key="backend", display_name="Backend", scope_certainty="High"
        )
        assert item.kind == "label"
        assert item.key == "backend"
        assert item.display_name == "Backend"
        assert item.scope_certainty == "High"

    def test_child_overrides_default_independent(self) -> None:
        a = ReportItem(kind="label", key="a")
        b = ReportItem(kind="label", key="b")
        assert a.child_overrides == {}
        a.child_overrides["X-1"] = ChildOverride("Name", "Low")
        assert b.child_overrides == {}

    def test_child_override_defaults(self) -> None:
        ov = ChildOverride()
        assert ov.display_name == ""
        assert ov.scope_certainty is None


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        ([], None),
        ([None, "", None], None),
        (["High"], "High"),
        (["Low", "High"], "Medium"),  # (1+3)/2 = 2
        (["High", "High"], "High"),
        (["Low", "Low", "Medium"], "Low"),  # (1+1+2)/3 ≈ 1.33 → 1
        (["Medium", "High", "High"], "High"),  # (2+3+3)/3 ≈ 2.67 → 3
        (["High", None, "High"], "High"),  # None entries ignored
        (["bogus", "Low"], "Low"),  # unknown values ignored
    ],
)
def test_average_certainty(values, expected) -> None:
    assert average_certainty(values) == expected


class TestTimelineItem:
    """Verify TimelineItem dataclass."""

    def test_creation(self) -> None:
        item = TimelineItem(
            name="Epic 1",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 6, 30),
            scope_certainty="Medium",
            progress=45.0,
        )
        assert item.name == "Epic 1"
        assert item.start_date == date(2024, 1, 1)
        assert item.progress == 45.0

    def test_defaults(self) -> None:
        item = TimelineItem(name="Test")
        assert item.start_date is None
        assert item.end_date is None
        assert item.scope_certainty is None
        assert item.progress == 0.0


class TestMilestoneItem:
    """Verify MilestoneItem dataclass."""

    def test_creation(self) -> None:
        ms = MilestoneItem(name="v1.0", release_date=date(2024, 3, 15))
        assert ms.name == "v1.0"
        assert ms.release_date == date(2024, 3, 15)


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
        assert m.estimation_unit == "SP"
        assert m.scope_certainty is None

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
        assert cfg.estimation_method == "story_points"
        assert cfg.progress_method == "combined"
        assert cfg.story_points_field == "story_points"
        assert cfg.epic_link_field == "customfield_10014"
        assert cfg.start_date_field == "startdate"
        assert cfg.due_date_field == "duedate"
        assert cfg.timeline_start_field == "startdate"
        assert cfg.timeline_end_field == "duedate"
        assert cfg.include_subtasks is True
        assert cfg.dark_mode is False
        assert cfg.confidential is False
        assert cfg.report_date == date.today()
        assert cfg.items == []


class TestReportData:
    """Verify ReportData defaults."""

    def test_empty_report(self) -> None:
        cfg = ReportConfig(epic_keys=["PROJ-1"])
        report = ReportData(config=cfg)
        assert report.epics == []
        assert report.metrics == []
        assert report.errors == []
        assert report.resolved_items == []
        assert report.fix_version_dates == {}
