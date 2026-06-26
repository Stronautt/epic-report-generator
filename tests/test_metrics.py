"""Tests for epic_report_generator.core.metrics."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from epic_report_generator.core.data_models import EpicData, EpicMetrics, JiraIssue
from epic_report_generator.core.metrics import (
    PROGRESS_COMBINED,
    PROGRESS_ESTIMATES_ONLY,
    PROGRESS_ISSUES_ONLY,
    calculate_metrics,
    merge_metrics,
)


def test_status_done_reexported_from_data_models() -> None:
    """metrics.STATUS_DONE stays the single 'Done' constant from data_models."""
    from epic_report_generator.core import data_models, metrics

    assert metrics.STATUS_DONE == data_models.STATUS_DONE == "Done"


def _make_issue(
    key: str = "TEST-1",
    status_category: str = "To Do",
    story_points: float | None = 3.0,
    created: datetime | None = None,
    resolved: datetime | None = None,
    start_date: date | None = None,
    due_date: date | None = None,
    parent_key: str | None = None,
    *,
    hierarchy_parent_key: str | None = None,
    display_tier: int = 1,
    show: bool = True,
    in_estimate: bool = True,
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
        parent_key=parent_key,
        hierarchy_parent_key=hierarchy_parent_key,
        display_tier=display_tier,
        show=show,
        in_estimate=in_estimate,
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


class TestReferenceDate:
    """``reference_date`` makes time-based metrics deterministic (no date.today())."""

    REF = date(2024, 6, 15)

    def _epic(self) -> EpicData:
        children = [
            _make_issue(
                "T-1",
                "Done",
                8.0,
                created=datetime(2024, 5, 1, tzinfo=timezone.utc),
                resolved=datetime(2024, 6, 1, tzinfo=timezone.utc),
            ),
            _make_issue(
                "T-2",
                "To Do",
                4.0,
                created=datetime(2024, 5, 1, tzinfo=timezone.utc),
            ),
        ]
        return _make_epic(children)

    def test_velocity_and_forecast_are_deterministic(self) -> None:
        m = calculate_metrics(self._epic(), reference_date=self.REF)
        # 8 SP done within the 4 weeks before REF → 8 / 4 = 2.0 SP/week
        assert m.velocity_sp_per_week == pytest.approx(2.0)
        # remaining 4 SP / 2.0 per week = 2 weeks after REF
        assert m.forecast_date == date(2024, 6, 29)

    def test_time_series_ends_at_reference_date(self) -> None:
        m = calculate_metrics(self._epic(), reference_date=self.REF)
        # Per-event series: a left anchor (both issues enter 5-1), the done
        # event (6-1), and a right anchor at the reference day.
        assert [d.date() for d in m.dates] == [
            date(2024, 5, 1),
            date(2024, 6, 1),
            date(2024, 6, 15),
        ]
        assert m.dates[-1].date() == self.REF
        assert m.total_sp_over_time[0] == pytest.approx(12.0)
        assert m.completed_sp_over_time[-1] == pytest.approx(8.0)

    def test_repeatable_across_calls(self) -> None:
        a = calculate_metrics(self._epic(), reference_date=self.REF)
        b = calculate_metrics(self._epic(), reference_date=self.REF)
        assert a.velocity_sp_per_week == b.velocity_sp_per_week
        assert a.forecast_date == b.forecast_date == date(2024, 6, 29)


class TestProgressCalculation:
    """Test bottom-up progress with combined method."""

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
        # Bottom-up: weighted_avg = (100*5 + 0*5)/10 = 50%
        # Combined: 50% * (1/2) = 25.0
        assert m.progress == pytest.approx(25.0)

    def test_no_story_points_fallback(self) -> None:
        now = datetime.now(tz=timezone.utc)
        children = [
            _make_issue("T-1", "Done", None, resolved=now),
            _make_issue("T-2", "To Do", None),
        ]
        m = calculate_metrics(_make_epic(children))
        # Both unestimated → weight=1.0 each
        # weighted_avg = (100*1 + 0*1)/2 = 50%
        # Combined: 50% * (1/2) = 25.0
        assert m.progress == pytest.approx(25.0)


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
        # Bottom-up: weighted_avg = (100*10 + 0*10)/20 = 50%
        # Combined: 50% * (1/2) = 25.0
        assert m.progress == pytest.approx(25.0)

    def test_empty_epic_with_time_days(self) -> None:
        m = calculate_metrics(_make_epic([]), estimation_method="time_days")
        assert m.progress == 0.0
        assert m.estimation_unit == "Days"
        assert m.total_issues == 0


class TestIssuesOnlyProgress:
    """Test the issues_only progress method (weight = 1.0 for all items)."""

    def test_issues_only_all_done(self) -> None:
        now = datetime.now(tz=timezone.utc)
        children = [
            _make_issue("T-1", "Done", 5, resolved=now),
            _make_issue("T-2", "Done", 3, resolved=now),
        ]
        m = calculate_metrics(
            _make_epic(children), progress_method=PROGRESS_ISSUES_ONLY
        )
        assert m.progress == pytest.approx(100.0)

    def test_issues_only_partial(self) -> None:
        now = datetime.now(tz=timezone.utc)
        children = [
            _make_issue("T-1", "Done", 5, resolved=now),
            _make_issue("T-2", "To Do", 5),
        ]
        m = calculate_metrics(
            _make_epic(children), progress_method=PROGRESS_ISSUES_ONLY
        )
        # weight=1.0 each: (100*1 + 0*1)/2 = 50.0
        assert m.progress == pytest.approx(50.0)

    def test_issues_only_no_sp(self) -> None:
        now = datetime.now(tz=timezone.utc)
        children = [
            _make_issue("T-1", "Done", None, resolved=now),
            _make_issue("T-2", "To Do", None),
        ]
        m = calculate_metrics(
            _make_epic(children), progress_method=PROGRESS_ISSUES_ONLY
        )
        # weight=1.0 each: (100*1 + 0*1)/2 = 50.0
        assert m.progress == pytest.approx(50.0)

    def test_issues_only_empty_epic(self) -> None:
        m = calculate_metrics(_make_epic([]), progress_method=PROGRESS_ISSUES_ONLY)
        assert m.progress == 0.0

    def test_backward_compat_story_points_only(self) -> None:
        """Passing old 'story_points_only' value should behave as issues_only."""
        now = datetime.now(tz=timezone.utc)
        children = [
            _make_issue("T-1", "Done", 5, resolved=now),
            _make_issue("T-2", "To Do", 5),
        ]
        m = calculate_metrics(_make_epic(children), progress_method="story_points_only")
        # Same as issues_only: (100*1 + 0*1)/2 = 50.0
        assert m.progress == pytest.approx(50.0)


class TestHierarchicalProgress:
    """Test bottom-up hierarchical progress with subtasks."""

    def test_subtask_aggregation(self) -> None:
        """Parent progress = weighted average of subtask progress."""
        now = datetime.now(tz=timezone.utc)
        # Story S-1 has two subtasks: one done (3SP), one todo (5SP)
        parent = _make_issue("S-1", "In Progress", None)  # unestimated parent
        sub1 = _make_issue("S-1-1", "Done", 3, resolved=now, parent_key="S-1")
        sub2 = _make_issue("S-1-2", "To Do", 5, parent_key="S-1")

        children = [parent, sub1, sub2]
        calculate_metrics(_make_epic(children))

        # sub1: progress=100, weight=3
        # sub2: progress=0, weight=5
        # parent progress = (100*3 + 0*5)/(3+5) = 37.5
        assert parent.progress == pytest.approx(37.5)
        # Parent weight = sum of subtask weights = 8 (unestimated parent)
        assert parent.effective_weight == pytest.approx(8.0)

    def test_subtask_aggregation_with_estimated_parent(self) -> None:
        """Parent with own estimate keeps its estimate as weight."""
        now = datetime.now(tz=timezone.utc)
        parent = _make_issue("S-1", "In Progress", 10)  # estimated parent
        sub1 = _make_issue("S-1-1", "Done", 3, resolved=now, parent_key="S-1")
        sub2 = _make_issue("S-1-2", "To Do", 5, parent_key="S-1")

        children = [parent, sub1, sub2]
        calculate_metrics(_make_epic(children))

        # Progress same: (100*3 + 0*5)/(3+5) = 37.5
        assert parent.progress == pytest.approx(37.5)
        # But weight = own estimate = 10
        assert parent.effective_weight == pytest.approx(10.0)

    def test_weighted_average_favors_larger_items(self) -> None:
        """Larger items pull progress proportionally more."""
        now = datetime.now(tz=timezone.utc)
        # 5 stories: S1-S4 are 50% (via subtasks), S5 (20SP) is 100% done
        children = [
            _make_issue("S-1", "Done", 5, resolved=now),
            _make_issue("S-2", "To Do", 5),
            _make_issue("S-3", "To Do", 10),
            _make_issue("S-4", "To Do", 15),
            _make_issue("S-5", "Done", 20, resolved=now),
        ]
        m = calculate_metrics(
            _make_epic(children), progress_method=PROGRESS_ISSUES_ONLY
        )
        # Issues only: weight=1 each, (100+0+0+0+100)/5 = 40.0
        assert m.progress == pytest.approx(40.0)

        m2 = calculate_metrics(_make_epic(children))
        # Combined: weighted_avg = (100*5 + 0*5 + 0*10 + 0*15 + 100*20)/(5+5+10+15+20)
        #         = 2500/55 ≈ 45.45%
        # × (2/5) = 18.18%
        assert m2.progress == pytest.approx(2500 / 55 * 2 / 5)

    def test_issue_progress_set_on_children(self) -> None:
        """Each JiraIssue gets .progress and .effective_weight set."""
        now = datetime.now(tz=timezone.utc)
        done_issue = _make_issue("T-1", "Done", 5, resolved=now)
        todo_issue = _make_issue("T-2", "To Do", 3)

        calculate_metrics(_make_epic([done_issue, todo_issue]))

        assert done_issue.progress == pytest.approx(100.0)
        assert done_issue.effective_weight == pytest.approx(5.0)
        assert todo_issue.progress == pytest.approx(0.0)
        assert todo_issue.effective_weight == pytest.approx(3.0)

    def test_issues_only_ignores_estimates_for_weight(self) -> None:
        """In issues_only mode, all items have weight=1.0."""
        now = datetime.now(tz=timezone.utc)
        big = _make_issue("T-1", "Done", 100, resolved=now)
        small = _make_issue("T-2", "To Do", 1)

        m = calculate_metrics(
            _make_epic([big, small]),
            progress_method=PROGRESS_ISSUES_ONLY,
        )
        # weight=1 each: (100*1 + 0*1)/2 = 50.0
        assert m.progress == pytest.approx(50.0)
        assert big.effective_weight == pytest.approx(1.0)
        assert small.effective_weight == pytest.approx(1.0)

    def test_all_subtasks_done(self) -> None:
        """Parent gets 100% when all subtasks are done."""
        now = datetime.now(tz=timezone.utc)
        parent = _make_issue("S-1", "Done", None)
        sub1 = _make_issue("S-1-1", "Done", 3, resolved=now, parent_key="S-1")
        sub2 = _make_issue("S-1-2", "Done", 5, resolved=now, parent_key="S-1")

        calculate_metrics(_make_epic([parent, sub1, sub2]))
        assert parent.progress == pytest.approx(100.0)

    def test_deep_hierarchy_not_supported(self) -> None:
        """Only one level of subtask nesting is expected from Jira."""
        now = datetime.now(tz=timezone.utc)
        story = _make_issue("S-1", "In Progress", None)
        sub = _make_issue("S-1-1", "In Progress", None, parent_key="S-1")
        # sub-sub is treated as subtask of S-1-1
        subsub = _make_issue("S-1-1-1", "Done", 3, resolved=now, parent_key="S-1-1")

        children = [story, sub, subsub]
        calculate_metrics(_make_epic(children))

        # subsub: done → 100%, weight=3
        # sub: weighted_avg of subsub = 100%, weight=3 (derived from subtask)
        # story: weighted_avg of sub = 100%, weight=3 (derived from subtask)
        assert subsub.progress == pytest.approx(100.0)
        assert sub.progress == pytest.approx(100.0)
        assert story.progress == pytest.approx(100.0)


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

        _, metrics = merge_metrics([epic_a, epic_b])
        assert metrics.total_issues == 2  # deduplicated
        assert metrics.total_sp == 8.0

    def test_merge_empty_list(self) -> None:
        _, metrics = merge_metrics([])
        assert metrics.total_issues == 0
        assert metrics.progress == 0.0

    def test_merge_single_epic(self) -> None:
        now = datetime.now(tz=timezone.utc)
        child = _make_issue("T-1", "Done", 5, resolved=now)
        epic = _make_epic([child])
        epic.key = "PROJ-100"

        _, metrics = merge_metrics([epic])
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

        _, m_combined = merge_metrics([epic], progress_method=PROGRESS_COMBINED)
        _, m_issues = merge_metrics([epic], progress_method=PROGRESS_ISSUES_ONLY)
        # combined: weighted_avg = 50%, × (1/2) = 25.0
        assert m_combined.progress == pytest.approx(25.0)
        # issues_only: (100*1 + 0*1)/2 = 50.0
        assert m_issues.progress == pytest.approx(50.0)

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

    def test_merge_weighted_average_of_epic_progress(self) -> None:
        """Label-group progress = weighted average of per-epic progress values."""
        now = datetime.now(tz=timezone.utc)
        # Epic A: 1 done (10SP), 1 todo (10SP)
        # → bottom-up weighted_avg = 50%, combined = 50% × 0.5 = 25%
        epic_a = _make_epic(
            [
                _make_issue("A-1", "Done", 10, resolved=now),
                _make_issue("A-2", "To Do", 10),
            ]
        )
        epic_a.key = "PROJ-A"

        # Epic B: 1 done (5SP)
        # → progress = 100%
        epic_b = _make_epic(
            [
                _make_issue("B-1", "Done", 5, resolved=now),
            ]
        )
        epic_b.key = "PROJ-B"

        _, m = merge_metrics([epic_a, epic_b])
        # Epic A weight = sum of direct children weights = 10 + 10 = 20
        # Epic B weight = 5
        # Label progress = (25*20 + 100*5) / (20+5) = (500+500)/25 = 40.0
        assert m.progress == pytest.approx(40.0)


class TestEstimatesOnlyProgress:
    """Test the estimates_only progress method."""

    def test_all_estimated_mix(self) -> None:
        """Weighted average without issue ratio multiplier."""
        now = datetime.now(tz=timezone.utc)
        children = [
            _make_issue("T-1", "Done", 5, resolved=now),
            _make_issue("T-2", "To Do", 5),
        ]
        m = calculate_metrics(
            _make_epic(children), progress_method=PROGRESS_ESTIMATES_ONLY
        )
        # weighted_avg = (100*5 + 0*5) / 10 = 50%
        # No issue-ratio multiplier → 50.0
        assert m.progress == pytest.approx(50.0)

    def test_unestimated_items_excluded(self) -> None:
        """Unestimated items get weight=0 and are excluded from the average."""
        now = datetime.now(tz=timezone.utc)
        children = [
            _make_issue("T-1", "Done", 10, resolved=now),
            _make_issue("T-2", "To Do", None),  # unestimated → excluded
        ]
        m = calculate_metrics(
            _make_epic(children), progress_method=PROGRESS_ESTIMATES_ONLY
        )
        # Only T-1 contributes: (100*10) / 10 = 100%
        assert m.progress == pytest.approx(100.0)

    def test_all_unestimated_zero_progress(self) -> None:
        """All unestimated → progress = 0%."""
        now = datetime.now(tz=timezone.utc)
        children = [
            _make_issue("T-1", "Done", None, resolved=now),
            _make_issue("T-2", "To Do", None),
        ]
        m = calculate_metrics(
            _make_epic(children), progress_method=PROGRESS_ESTIMATES_ONLY
        )
        assert m.progress == pytest.approx(0.0)

    def test_all_done(self) -> None:
        """All estimated and done → 100%."""
        now = datetime.now(tz=timezone.utc)
        children = [
            _make_issue("T-1", "Done", 5, resolved=now),
            _make_issue("T-2", "Done", 3, resolved=now),
        ]
        m = calculate_metrics(
            _make_epic(children), progress_method=PROGRESS_ESTIMATES_ONLY
        )
        assert m.progress == pytest.approx(100.0)

    def test_with_subtask_hierarchy(self) -> None:
        """Parent with subtasks: unestimated subtask excluded from average."""
        now = datetime.now(tz=timezone.utc)
        parent = _make_issue("S-1", "In Progress", None)
        sub1 = _make_issue("S-1-1", "Done", 3, resolved=now, parent_key="S-1")
        sub2 = _make_issue("S-1-2", "To Do", None, parent_key="S-1")  # excluded

        children = [parent, sub1, sub2]
        calculate_metrics(
            _make_epic(children),
            progress_method=PROGRESS_ESTIMATES_ONLY,
        )
        # sub1: progress=100, weight=3
        # sub2: progress=0, weight=0 (excluded)
        # parent progress = (100*3 + 0*0) / 3 = 100%
        # parent weight = weight_total = 3 (unestimated parent derives from subs)
        assert parent.progress == pytest.approx(100.0)
        assert parent.effective_weight == pytest.approx(3.0)

    def test_differs_from_combined(self) -> None:
        """Estimates Only gives higher progress than Combined for same data."""
        now = datetime.now(tz=timezone.utc)
        children = [
            _make_issue("T-1", "Done", 5, resolved=now),
            _make_issue("T-2", "To Do", 5),
        ]
        m_combined = calculate_metrics(
            _make_epic(children), progress_method=PROGRESS_COMBINED
        )
        m_estimates = calculate_metrics(
            _make_epic(children), progress_method=PROGRESS_ESTIMATES_ONLY
        )
        # Combined: 50% * (1/2) = 25.0
        # Estimates Only: 50.0 (no issue ratio)
        assert m_combined.progress == pytest.approx(25.0)
        assert m_estimates.progress == pytest.approx(50.0)


class TestFixedDateWindow:
    """Fixed (hard) timeline dates cap the per-epic time-based metrics.

    ``window_start`` / ``window_end`` mirror ``ReportConfig.timeline_hard_start``
    / ``timeline_hard_end``.  They must bound velocity, cycle time, scope change,
    the forecast origin, and the trend chart — without touching progress or the
    estimate roll-ups, which always reflect the whole epic.
    """

    REF = date(2024, 6, 15)
    WIN_START = date(2024, 5, 1)
    WIN_END = date(2024, 6, 1)

    @staticmethod
    def _dt(d: date) -> datetime:
        return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)

    def test_velocity_excludes_resolutions_past_window_end(self) -> None:
        children = [
            _make_issue(
                "IN",
                "Done",
                8.0,
                created=self._dt(date(2024, 5, 10)),
                resolved=self._dt(date(2024, 5, 20)),  # inside window
            ),
            _make_issue(
                "OUT",
                "Done",
                4.0,
                created=self._dt(date(2024, 5, 10)),
                resolved=self._dt(date(2024, 6, 10)),  # after window end (6-1)
            ),
        ]
        epic = _make_epic(children)
        unbounded = calculate_metrics(epic, reference_date=self.REF)
        bounded = calculate_metrics(
            epic,
            reference_date=self.REF,
            window_start=self.WIN_START,
            window_end=self.WIN_END,
        )
        # Unbounded: both resolved within 4wk of 6-15 → 12 SP / 4wk = 3.0.
        assert unbounded.velocity_sp_per_week == pytest.approx(3.0)
        # Bounded: "as of" 6-1, cutoff 5-4 (window_start 5-1 is earlier) → only
        # the 8 SP resolved 5-20 counts; OUT resolved 6-10 is past the end.
        # 8 SP / 4wk = 2.0.
        assert bounded.velocity_sp_per_week == pytest.approx(2.0)

    def test_cycle_time_counts_only_resolutions_in_window(self) -> None:
        children = [
            _make_issue(
                "IN",
                "Done",
                3.0,
                created=self._dt(date(2024, 5, 10)),
                resolved=self._dt(date(2024, 5, 20)),  # 10d cycle, inside window
            ),
            _make_issue(
                "OUT",
                "Done",
                3.0,
                created=self._dt(date(2024, 6, 1)),
                resolved=self._dt(date(2024, 6, 10)),  # resolved after window end
            ),
        ]
        epic = _make_epic(children)
        bounded = calculate_metrics(
            epic,
            reference_date=self.REF,
            window_start=self.WIN_START,
            window_end=self.WIN_END,
        )
        # Only IN's 10-day cycle is in scope.
        assert bounded.avg_cycle_time_days == pytest.approx(10.0, abs=0.1)

    def test_trend_chart_clipped_to_window_with_carryover(self) -> None:
        children = [
            _make_issue(
                "EARLY",
                "To Do",
                5.0,
                created=self._dt(date(2024, 4, 1)),  # before window start (5-1)
            ),
            _make_issue(
                "MID",
                "To Do",
                3.0,
                created=self._dt(date(2024, 5, 15)),  # inside window
            ),
        ]
        epic = _make_epic(children)
        bounded = calculate_metrics(
            epic,
            reference_date=self.REF,
            window_start=self.WIN_START,
            window_end=self.WIN_END,
        )
        # Series is zoomed to [window_start, window_end].
        assert bounded.dates[0].date() == self.WIN_START
        assert bounded.dates[-1].date() == self.WIN_END
        # Carry-over: the pre-window EARLY issue is already counted on day one.
        assert bounded.total_sp_over_time[0] == pytest.approx(5.0)
        # MID joins by the window end → both issues counted.
        assert bounded.total_sp_over_time[-1] == pytest.approx(8.0)

    def test_per_event_subday_resolution(self) -> None:
        """Same-day changelog events become distinct sub-day points (Jira-fidelity).

        Daily aggregation collapsed every event on a calendar day into one step;
        the per-event series keeps each at its real timestamp, so a same-day SP
        bump and completion show as separate points with different totals.
        """
        tz = timezone.utc
        bumped = _make_issue(
            "T-1", "Done", 8.0, created=datetime(2024, 5, 1, 9, 0, tzinfo=tz)
        )
        bumped.sp_history = [
            (datetime(2024, 5, 1, 9, 0, tzinfo=tz), 3.0),  # enters at 3 SP
            (datetime(2024, 5, 1, 15, 0, tzinfo=tz), 8.0),  # re-estimated same day
        ]
        bumped.done_history = [(datetime(2024, 5, 1, 18, 0, tzinfo=tz), True)]
        other = _make_issue(
            "T-2", "To Do", 2.0, created=datetime(2024, 5, 1, 9, 0, tzinfo=tz)
        )
        epic = _make_epic([bumped, other])
        m = calculate_metrics(epic, reference_date=date(2024, 5, 10))

        may1 = [i for i, d in enumerate(m.dates) if d.date() == date(2024, 5, 1)]
        # enter (9:00) + sp-change (15:00) + done (18:00) — three distinct instants.
        assert len(may1) == 3
        assert len({m.dates[i] for i in may1}) == 3
        # Scope steps within the day: 3+2 → then 8+2.
        assert m.total_sp_over_time[may1[0]] == pytest.approx(5.0)
        assert m.total_sp_over_time[may1[1]] == pytest.approx(10.0)
        assert m.completed_sp_over_time[may1[2]] == pytest.approx(8.0)

    def test_scope_change_windowed(self) -> None:
        children = [
            _make_issue("A", "To Do", 1.0, created=self._dt(date(2024, 5, 1))),
            _make_issue(
                "B", "To Do", 1.0, created=self._dt(date(2024, 5, 20))
            ),  # added well after A, inside window
            _make_issue(
                "C", "To Do", 1.0, created=self._dt(date(2024, 7, 1))
            ),  # created after window end → out of scope
        ]
        epic = _make_epic(children)
        bounded = calculate_metrics(
            epic,
            reference_date=self.REF,
            window_start=self.WIN_START,
            window_end=self.WIN_END,
        )
        # In-window set = {A, B}; B is >7d after A → 1/2 = 50%.
        assert bounded.scope_change_pct == pytest.approx(50.0)

    def test_no_window_matches_unbounded(self) -> None:
        """Passing ``None`` windows is identical to omitting them entirely."""
        children = [
            _make_issue(
                "T-1",
                "Done",
                8.0,
                created=self._dt(date(2024, 5, 1)),
                resolved=self._dt(date(2024, 6, 1)),
            ),
            _make_issue("T-2", "To Do", 4.0, created=self._dt(date(2024, 5, 1))),
        ]
        epic = _make_epic(children)
        base = calculate_metrics(epic, reference_date=self.REF)
        explicit_none = calculate_metrics(
            epic, reference_date=self.REF, window_start=None, window_end=None
        )
        assert explicit_none.velocity_sp_per_week == base.velocity_sp_per_week
        assert explicit_none.avg_cycle_time_days == base.avg_cycle_time_days
        assert explicit_none.scope_change_pct == base.scope_change_pct
        assert explicit_none.dates == base.dates
        assert explicit_none.total_sp_over_time == base.total_sp_over_time

    def test_merge_metrics_threads_window(self) -> None:
        """``merge_metrics`` caps both source and merged metrics to the window."""
        epic_a = EpicData(
            key="A-1",
            summary="Epic A",
            status="In Progress",
            priority=None,
            assignee=None,
            reporter=None,
            created=self._dt(date(2024, 4, 1)),
            updated=self._dt(self.REF),
            children=[
                _make_issue(
                    "A-IN",
                    "Done",
                    8.0,
                    created=self._dt(date(2024, 5, 10)),
                    resolved=self._dt(date(2024, 5, 20)),
                ),
                _make_issue(
                    "A-OUT",
                    "Done",
                    4.0,
                    created=self._dt(date(2024, 5, 10)),
                    resolved=self._dt(date(2024, 6, 10)),  # past window end
                ),
            ],
        )
        per_epic: list[EpicMetrics] = []
        _, merged = merge_metrics(
            [epic_a],
            reference_date=self.REF,
            window_start=self.WIN_START,
            window_end=self.WIN_END,
            source_metrics_out=per_epic,
        )
        # Source-epic and merged velocity both exclude the past-window resolution.
        assert per_epic[0].velocity_sp_per_week == pytest.approx(2.0)
        assert merged.velocity_sp_per_week == pytest.approx(2.0)


class TestHierarchyMetrics:
    """Task 4: N-tier roll-up, the in_estimate axis, and tier-2 date pooling."""

    def test_four_tier_rollup_via_hierarchy_parent_key(self) -> None:
        """Progress rolls up N tiers through ``hierarchy_parent_key`` alone.

        ``parent_key`` is left unset to prove the chain-resolved parent drives
        the subtask map (mirrors the custom-chain fetch path).
        """
        now = datetime.now(tz=timezone.utc)
        # Epic E-1 → A (tier 1) → B (tier 2 chain) → C → D(done).  Only D is Done.
        a = _make_issue("A", "In Progress", None, hierarchy_parent_key="E-1")
        b = _make_issue("B", "In Progress", None, hierarchy_parent_key="A")
        c = _make_issue("C", "In Progress", None, hierarchy_parent_key="B")
        d = _make_issue("D", "Done", 4, resolved=now, hierarchy_parent_key="C")
        epic = _make_epic([a, b, c, d])
        epic.key = "E-1"

        m_issues = calculate_metrics(epic, progress_method=PROGRESS_ISSUES_ONLY)
        # Bottom-up: D done → 100% cascades up through C, B, A.
        assert d.progress == pytest.approx(100.0)
        assert c.progress == pytest.approx(100.0)
        assert b.progress == pytest.approx(100.0)
        assert a.progress == pytest.approx(100.0)
        # issues_only: epic = weighted avg of its single direct child A = 100%.
        assert m_issues.progress == pytest.approx(100.0)
        assert m_issues.total_issues == 4

        # combined multiplies by the done/total ratio (1/4) → 25%.
        m_combined = calculate_metrics(epic, progress_method=PROGRESS_COMBINED)
        assert m_combined.progress == pytest.approx(25.0)

    @pytest.mark.parametrize(
        "method",
        [PROGRESS_COMBINED, PROGRESS_ISSUES_ONLY, PROGRESS_ESTIMATES_ONLY],
    )
    def test_in_estimate_false_dropped_from_metrics(self, method: str) -> None:
        """``in_estimate=False`` removes an issue from counts under every method."""
        now = datetime.now(tz=timezone.utc)
        kept = _make_issue("K-1", "Done", 5, resolved=now)
        dropped = _make_issue("K-2", "To Do", 5, in_estimate=False)
        m = calculate_metrics(_make_epic([kept, dropped]), progress_method=method)
        # The excluded issue contributes no count, no weight: only the done
        # issue remains, so every method reports 100% over a single issue.
        assert m.total_issues == 1
        assert m.completed_issues == 1
        assert m.progress == pytest.approx(100.0)
        if method != PROGRESS_ISSUES_ONLY:
            assert m.total_sp == pytest.approx(5.0)
            assert m.completed_sp == pytest.approx(5.0)

    def test_tier2_date_pooling_gated_by_show(self) -> None:
        """A tier-2 child expands the timeline range only when shown."""
        c1 = _make_issue(
            "C1",
            start_date=date(2024, 1, 1),
            due_date=date(2024, 2, 1),
            display_tier=1,
        )

        def _epic_with(sub_show: bool) -> EpicData:
            c2 = _make_issue(
                "C2",
                start_date=date(2024, 3, 1),
                due_date=date(2024, 4, 1),
                display_tier=2,
                hierarchy_parent_key="C1",
                show=sub_show,
            )
            epic = _make_epic([c1, c2])
            epic.key = "E-1"
            return epic

        # Hidden tier-2 child: timeline range stops at the tier-1 child's end.
        hidden, _ = merge_metrics([_epic_with(False)])
        assert hidden.timeline_end == date(2024, 2, 1)
        # Estimation dates always pool every child, regardless of show.
        assert hidden.due_date == date(2024, 4, 1)

        # Shown tier-2 child: it stretches the timeline range.
        shown, _ = merge_metrics([_epic_with(True)])
        assert shown.timeline_end == date(2024, 4, 1)


class TestShownUnestimatedDisplayProgress:
    """Shown-but-unestimated children get a leaf display progress, not 0%."""

    def test_done_shown_unestimated_child_reads_complete(self) -> None:
        done = _make_issue("S-1", "Done", show=True, in_estimate=False)
        todo = _make_issue("S-2", "To Do", show=True, in_estimate=False)
        # An estimated child keeps the metrics pass non-empty.
        est = _make_issue("S-3", "To Do", show=True, in_estimate=True)
        calculate_metrics(_make_epic([done, todo, est]))
        assert done.progress == 100.0
        assert todo.progress == 0.0

    def test_runs_even_with_no_estimated_children(self) -> None:
        # Epic whose only children are shown-but-unestimated: the display pass
        # must run before the empty-`children` early return.
        done = _make_issue("S-1", "Done", show=True, in_estimate=False)
        m = calculate_metrics(_make_epic([done]))
        assert m.total_issues == 0  # excluded from the aggregate
        assert done.progress == 100.0
