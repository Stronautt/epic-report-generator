"""Tests for epic_report_generator.core.metrics."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from epic_report_generator.core.data_models import EpicData, JiraIssue
from epic_report_generator.core.metrics import calculate_metrics


def _make_issue(
    key: str = "TEST-1",
    status_category: str = "To Do",
    story_points: float | None = 3.0,
    created: datetime | None = None,
    resolved: datetime | None = None,
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
            _make_issue("T-1", "Done", 3, created=now - timedelta(days=5), resolved=now),
            _make_issue("T-2", "Done", 2, created=now - timedelta(days=10), resolved=now),
        ]
        m = calculate_metrics(_make_epic(children))
        # avg = (5 + 10) / 2 = 7.5
        assert m.avg_cycle_time_days is not None
        assert m.avg_cycle_time_days == pytest.approx(7.5, abs=0.1)

    def test_time_series_generated(self) -> None:
        now = datetime.now(tz=timezone.utc)
        children = [
            _make_issue("T-1", "Done", 3, created=now - timedelta(days=5), resolved=now - timedelta(days=1)),
            _make_issue("T-2", "To Do", 5, created=now - timedelta(days=3)),
        ]
        m = calculate_metrics(_make_epic(children))
        assert len(m.dates) > 0
        assert len(m.total_sp_over_time) == len(m.dates)
        assert len(m.completed_sp_over_time) == len(m.dates)
