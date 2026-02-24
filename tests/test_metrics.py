"""Tests for epic_report_generator.core.metrics."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from epic_report_generator.core.data_models import EpicData, JiraIssue
from epic_report_generator.core.metrics import calculate_metrics, merge_metrics


def _make_issue(
    key: str = "TEST-1",
    status_category: str = "To Do",
    story_points: float | None = 3.0,
    created: datetime | None = None,
    resolved: datetime | None = None,
    start_date: date | None = None,
    due_date: date | None = None,
) -> JiraIssue:
    now = datetime.now(tz=timezone.utc)
    return JiraIssue(
        key=key,
        summary=f"Issue {key}",
        status="Open" if status_category != "Done" else "Done",
        status_category=status_category,
        resolution="Done" if status_category == "Done" else None,
        issue_type="Story",
        story_points=story_points,
        created=created or now - timedelta(days=10),
        resolved=resolved,
        assignee="Test User",
        start_date=start_date,
        due_date=due_date,
    )


def _make_epic(children: list[JiraIssue] | None = None) -> EpicData:
    return EpicData(
        key="PROJ-100",
        summary="Test Epic",
        status="In Progress",
        priority="Medium",
        assignee="Owner",
        reporter="Reporter",
        created=datetime.now(tz=timezone.utc) - timedelta(days=30),
        updated=datetime.now(tz=timezone.utc),
        children=children or [],
    )


class TestProgressCalculation:
    """Test the progress formula: (done_sp/total_sp) * (done/total) * 100."""

    def test_empty_epic(self) -> None:
        m = calculate_metrics(_make_epic([]))
        assert m.progress == 0.0
        assert m.total_issues == 0

    def test_all_done(self) -> None:
        now = datetime.now(tz=timezone.utc)
        children = [
            _make_issue("T-1", "Done", 5, resolved=now),
            _make_issue("T-2", "Done", 3, resolved=now),
        ]
        m = calculate_metrics(_make_epic(children))
        assert m.progress == pytest.approx(100.0)
        assert m.completed_issues == 2
        assert m.completed_sp == 8.0

    def test_partial_progress(self) -> None:
        now = datetime.now(tz=timezone.utc)
        children = [
            _make_issue("T-1", "Done", 5, resolved=now),
            _make_issue("T-2", "To Do", 5),
        ]
        m = calculate_metrics(_make_epic(children))
        # (5/10) * (1/2) * 100 = 25.0
        assert m.progress == pytest.approx(25.0)

    def test_no_story_points_fallback(self) -> None:
        now = datetime.now(tz=timezone.utc)
        children = [
            _make_issue("T-1", "Done", None, resolved=now),
            _make_issue("T-2", "To Do", None),
        ]
        m = calculate_metrics(_make_epic(children))
        # total_sp == 0 → fallback: (1/2) * 100 = 50.0
        assert m.progress == pytest.approx(50.0)


class TestMetrics:
    """Test velocity, cycle time, and other metrics."""

    def test_unestimated_count(self) -> None:
        children = [
            _make_issue("T-1", "To Do", None),
            _make_issue("T-2", "To Do", 5),
            _make_issue("T-3", "To Do", 0),
        ]
        m = calculate_metrics(_make_epic(children))
        # story_points=None and story_points=0 both count as unestimated
        assert m.unestimated_issues == 2

    def test_remaining_sp(self) -> None:
        now = datetime.now(tz=timezone.utc)
        children = [
            _make_issue("T-1", "Done", 5, resolved=now),
            _make_issue("T-2", "In Progress", 8),
        ]
        m = calculate_metrics(_make_epic(children))
        assert m.total_sp == 13.0
        assert m.completed_sp == 5.0
        assert m.remaining_sp == 8.0

    def test_cycle_time(self) -> None:
        now = datetime.now(tz=timezone.utc)
        children = [
            _make_issue(
                "T-1", "Done", 3, created=now - timedelta(days=5), resolved=now
            ),
            _make_issue(
                "T-2", "Done", 2, created=now - timedelta(days=10), resolved=now
            ),
        ]
        m = calculate_metrics(_make_epic(children))
        # avg = (5 + 10) / 2 = 7.5
        assert m.avg_cycle_time_days is not None
        assert m.avg_cycle_time_days == pytest.approx(7.5, abs=0.1)

    def test_time_series_generated(self) -> None:
        now = datetime.now(tz=timezone.utc)
        children = [
            _make_issue(
                "T-1",
                "Done",
                3,
                created=now - timedelta(days=5),
                resolved=now - timedelta(days=1),
            ),
            _make_issue("T-2", "To Do", 5, created=now - timedelta(days=3)),
        ]
        m = calculate_metrics(_make_epic(children))
        assert len(m.dates) > 0
        assert len(m.total_sp_over_time) == len(m.dates)
        assert len(m.completed_sp_over_time) == len(m.dates)


class TestTimeDaysEstimation:
    """Test time-based (days) estimation method."""

    def test_estimation_unit_set_to_days(self) -> None:
        children = [
            _make_issue(
                "T-1",
                "To Do",
                None,
                start_date=date(2024, 1, 1),
                due_date=date(2024, 1, 11),
            ),
        ]
        m = calculate_metrics(_make_epic(children), estimation_method="time_days")
        assert m.estimation_unit == "Days"

    def test_estimation_unit_default_sp(self) -> None:
        children = [_make_issue("T-1", "To Do", 5)]
        m = calculate_metrics(_make_epic(children))
        assert m.estimation_unit == "SP"

    def test_total_sp_with_days(self) -> None:
        now = datetime.now(tz=timezone.utc)
        children = [
            _make_issue(
                "T-1",
                "Done",
                None,
                resolved=now,
                start_date=date(2024, 1, 1),
                due_date=date(2024, 1, 11),
            ),
            _make_issue(
                "T-2",
                "To Do",
                None,
                start_date=date(2024, 2, 1),
                due_date=date(2024, 2, 6),
            ),
        ]
        m = calculate_metrics(_make_epic(children), estimation_method="time_days")
        # T-1: 10 days, T-2: 5 days
        assert m.total_sp == 15.0
        assert m.completed_sp == 10.0
        assert m.remaining_sp == 5.0

    def test_unestimated_missing_dates(self) -> None:
        children = [
            _make_issue(
                "T-1",
                "To Do",
                None,
                start_date=date(2024, 1, 1),
                due_date=date(2024, 1, 11),
            ),
            _make_issue("T-2", "To Do", None),  # no dates → unestimated
            _make_issue(
                "T-3", "To Do", None, start_date=date(2024, 1, 1)
            ),  # no due_date → unestimated
        ]
        m = calculate_metrics(_make_epic(children), estimation_method="time_days")
        assert m.unestimated_issues == 2
        assert m.total_sp == 10.0

    def test_progress_with_days(self) -> None:
        now = datetime.now(tz=timezone.utc)
        children = [
            _make_issue(
                "T-1",
                "Done",
                None,
                resolved=now,
                start_date=date(2024, 1, 1),
                due_date=date(2024, 1, 11),  # 10 days
            ),
            _make_issue(
                "T-2",
                "To Do",
                None,
                start_date=date(2024, 2, 1),
                due_date=date(2024, 2, 11),  # 10 days
            ),
        ]
        m = calculate_metrics(_make_epic(children), estimation_method="time_days")
        # (10/20) * (1/2) * 100 = 25.0
        assert m.progress == pytest.approx(25.0)

    def test_empty_epic_with_time_days(self) -> None:
        m = calculate_metrics(_make_epic([]), estimation_method="time_days")
        assert m.progress == 0.0
        assert m.estimation_unit == "Days"
        assert m.total_issues == 0


class TestStoryPointsOnlyProgress:
    """Test the story_points_only progress method."""

    def test_sp_only_all_done(self) -> None:
        now = datetime.now(tz=timezone.utc)
        children = [
            _make_issue("T-1", "Done", 5, resolved=now),
            _make_issue("T-2", "Done", 3, resolved=now),
        ]
        m = calculate_metrics(_make_epic(children), progress_method="story_points_only")
        assert m.progress == pytest.approx(100.0)

    def test_sp_only_partial(self) -> None:
        now = datetime.now(tz=timezone.utc)
        children = [
            _make_issue("T-1", "Done", 5, resolved=now),
            _make_issue("T-2", "To Do", 5),
        ]
        m = calculate_metrics(_make_epic(children), progress_method="story_points_only")
        # 5/10 * 100 = 50.0 (not 25.0 like combined)
        assert m.progress == pytest.approx(50.0)

    def test_sp_only_no_sp_returns_zero(self) -> None:
        now = datetime.now(tz=timezone.utc)
        children = [
            _make_issue("T-1", "Done", None, resolved=now),
            _make_issue("T-2", "To Do", None),
        ]
        m = calculate_metrics(_make_epic(children), progress_method="story_points_only")
        # total_sp == 0 → 0.0 for story_points_only
        assert m.progress == pytest.approx(0.0)

    def test_sp_only_empty_epic(self) -> None:
        m = calculate_metrics(_make_epic([]), progress_method="story_points_only")
        assert m.progress == 0.0


class TestMergeMetrics:
    """Test merge_metrics for combining multiple epics."""

    def test_merge_deduplicates_children(self) -> None:
        now = datetime.now(tz=timezone.utc)
        child_a = _make_issue("T-1", "Done", 5, resolved=now)
        child_b = _make_issue("T-2", "To Do", 3)
        child_dup = _make_issue("T-1", "Done", 5, resolved=now)  # duplicate

        epic_a = _make_epic([child_a, child_b])
        epic_a.key = "PROJ-100"
        epic_b = _make_epic([child_dup])
        epic_b.key = "PROJ-101"

        synthetic, metrics = merge_metrics([epic_a, epic_b])
        assert metrics.total_issues == 2  # deduplicated
        assert metrics.total_sp == 8.0

    def test_merge_empty_list(self) -> None:
        synthetic, metrics = merge_metrics([])
        assert metrics.total_issues == 0
        assert metrics.progress == 0.0

    def test_merge_single_epic(self) -> None:
        now = datetime.now(tz=timezone.utc)
        child = _make_issue("T-1", "Done", 5, resolved=now)
        epic = _make_epic([child])
        epic.key = "PROJ-100"

        synthetic, metrics = merge_metrics([epic])
        assert metrics.total_issues == 1
        assert metrics.completed_sp == 5.0

    def test_merge_with_progress_method(self) -> None:
        now = datetime.now(tz=timezone.utc)
        children = [
            _make_issue("T-1", "Done", 5, resolved=now),
            _make_issue("T-2", "To Do", 5),
        ]
        epic = _make_epic(children)
        epic.key = "PROJ-100"

        _, m_combined = merge_metrics([epic], progress_method="combined")
        _, m_sp_only = merge_metrics([epic], progress_method="story_points_only")
        # combined: (5/10) * (1/2) * 100 = 25.0
        assert m_combined.progress == pytest.approx(25.0)
        # sp_only: (5/10) * 100 = 50.0
        assert m_sp_only.progress == pytest.approx(50.0)

    def test_merge_dates(self) -> None:
        epic_a = _make_epic([])
        epic_a.key = "PROJ-100"
        epic_a.start_date = date(2024, 1, 1)
        epic_a.due_date = date(2024, 3, 31)

        epic_b = _make_epic([])
        epic_b.key = "PROJ-101"
        epic_b.start_date = date(2024, 2, 1)
        epic_b.due_date = date(2024, 6, 30)

        synthetic, _ = merge_metrics([epic_a, epic_b])
        assert synthetic.start_date == date(2024, 1, 1)
        assert synthetic.due_date == date(2024, 6, 30)
