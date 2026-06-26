"""Tests for epic_report_generator.core.data_models."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from epic_report_generator.core.data_models import (
    ChildOverride,
    EpicData,
    EpicMetrics,
    HierarchyNode,
    JiraIssue,
    MilestoneItem,
    ReportConfig,
    ReportData,
    ReportItem,
    TimelineItem,
    average_certainty,
    canonical_default_hierarchy,
    coerce_hierarchy,
    epic_tier_type_names,
    migrate_default_hierarchy,
    serialize_hierarchy,
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


class TestHierarchyNode:
    """Verify the custom issue-type hierarchy chain model and helpers."""

    def test_node_defaults(self) -> None:
        n = HierarchyNode(issue_type_id="10000", issue_type="Epic")
        assert n.edge == "parent"
        assert n.link_types == []
        assert n.display_tier == 0
        assert n.show is True
        assert n.in_estimate is True

    def test_config_default_empty(self) -> None:
        assert ReportConfig().issue_hierarchy == []

    def test_jira_issue_hierarchy_defaults(self) -> None:
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
        assert issue.issue_type_id == ""
        assert issue.hierarchy_parent_key is None
        assert issue.display_tier == 1
        assert issue.show is True
        assert issue.in_estimate is True

    def test_serialize_omits_defaults(self) -> None:
        n = HierarchyNode(issue_type_id="1", issue_type="Epic", display_tier=0)
        assert serialize_hierarchy([n]) == [
            {"issue_type_id": "1", "issue_type": "Epic", "display_tier": 0}
        ]

    def test_serialize_includes_non_defaults(self) -> None:
        n = HierarchyNode(
            issue_type_id="3",
            issue_type="Feature",
            edge="link",
            link_types=["blocks", "relates to"],
            display_tier=1,
            show=False,
            in_estimate=False,
        )
        assert serialize_hierarchy([n]) == [
            {
                "issue_type_id": "3",
                "issue_type": "Feature",
                "display_tier": 1,
                "edge": "link",
                "link_types": ["blocks", "relates to"],
                "show": False,
                "in_estimate": False,
            }
        ]

    def test_round_trip(self) -> None:
        chain = [
            HierarchyNode(issue_type_id="1", issue_type="Capability", display_tier=0),
            HierarchyNode(
                issue_type_id="2",
                issue_type="Feature",
                edge="link",
                link_types=["blocks"],
                display_tier=1,
            ),
            HierarchyNode(
                issue_type_id="3",
                issue_type="Sub-task",
                display_tier=2,
                show=False,
                in_estimate=True,
            ),
        ]
        assert coerce_hierarchy(serialize_hierarchy(chain)) == chain

    def test_coerce_from_nodes_copies(self) -> None:
        src = HierarchyNode(
            issue_type_id="1", issue_type="Epic", link_types=["blocks"]
        )
        out = coerce_hierarchy([src])
        assert out == [src]
        out[0].link_types.append("relates to")
        assert src.link_types == ["blocks"]  # independent list

    def test_coerce_none_and_partial(self) -> None:
        assert coerce_hierarchy(None) == []
        assert coerce_hierarchy([{}]) == [HierarchyNode(issue_type_id="", issue_type="")]
        # bogus edge normalises to "parent"
        n = coerce_hierarchy([{"issue_type_id": "1", "issue_type": "E", "edge": "x"}])
        assert n[0].edge == "parent"


@pytest.mark.parametrize(
    ("chain", "expected"),
    [
        ([], ["Epic"]),  # empty derives the default
        (
            [HierarchyNode(issue_type_id="1", issue_type="Initiative", display_tier=0)],
            ["Initiative"],
        ),
        (
            [
                HierarchyNode(issue_type_id="1", issue_type="Capability", display_tier=0),
                HierarchyNode(issue_type_id="2", issue_type="Epic", display_tier=0),
                HierarchyNode(issue_type_id="3", issue_type="Story", display_tier=1),
            ],
            ["Capability", "Epic"],  # multiple tier-0 types, tier-1 excluded
        ),
        (
            # no tier-0 node → falls back to ["Epic"]
            [HierarchyNode(issue_type_id="2", issue_type="Story", display_tier=1)],
            ["Epic"],
        ),
    ],
)
def test_epic_tier_type_names(chain, expected) -> None:
    assert epic_tier_type_names(chain) == expected


class TestMigrateDefaultHierarchy:
    """Verify legacy-boolean → chain migration preserves pre-change output."""

    def test_default_flags_classic_chain(self) -> None:
        # All flags at their historical defaults → classic chain that derives the
        # same fetch/metrics behaviour as the pre-change 2-tier path.
        chain = migrate_default_hierarchy()
        assert [(n.issue_type, n.display_tier, n.edge) for n in chain] == [
            ("Epic", 0, "parent"),
            ("Story", 1, "parent"),
            ("Sub-task", 2, "parent"),
        ]
        # Tier-0 label scope stays ["Epic"]; sub-tasks counted but not shown.
        assert epic_tier_type_names(chain) == ["Epic"]
        story, sub = chain[1], chain[2]
        assert story.show is False  # no nested rows / no story timeline bars
        assert sub.show is False  # no sub-task timeline bars (matches old default)
        assert sub.in_estimate is True  # include_subtasks=True → still counted

    def test_offline_fallback_has_empty_ids(self) -> None:
        chain = migrate_default_hierarchy(issue_types=None)
        assert all(n.issue_type_id == "" for n in chain)
        assert [n.issue_type for n in chain] == ["Epic", "Story", "Sub-task"]

    def test_metadata_backfills_ids_by_name(self) -> None:
        types = [
            {"id": "10001", "name": "Epic"},
            {"id": "10002", "name": "Story"},
            {"id": "10003", "name": "Sub-task"},
            {"id": "10004", "name": "Bug"},
        ]
        chain = migrate_default_hierarchy(issue_types=types)
        assert [n.issue_type_id for n in chain] == ["10001", "10002", "10003"]

    def test_include_subtasks_false_drops_estimate(self) -> None:
        chain = migrate_default_hierarchy(include_subtasks=False)
        assert chain[2].in_estimate is False
        assert chain[2].show is False

    def test_timeline_flags_set_show(self) -> None:
        chain = migrate_default_hierarchy(
            show_epic_stories_on_timeline=True,
            show_subtasks_on_timeline=True,
        )
        assert chain[1].show is True  # Story
        assert chain[2].show is True  # Sub-task

    def test_include_subtasks_in_timeline_sets_subtask_show(self) -> None:
        # The pooling-only flag also flips the single Sub-task show axis.
        chain = migrate_default_hierarchy(include_subtasks_in_timeline=True)
        assert chain[2].show is True


class TestCanonicalDefaultHierarchy:
    """The recommended Jira default: Epic / Story·Task·Bug / Sub-task only."""

    def test_maps_standard_types_onto_tiers(self) -> None:
        types = [
            {"id": "10000", "name": "Epic", "hierarchyLevel": 1},
            {"id": "10001", "name": "Initiative", "hierarchyLevel": 2},  # excluded
            {"id": "10002", "name": "Story", "hierarchyLevel": 0},
            {"id": "10003", "name": "Task", "hierarchyLevel": 0},
            {"id": "10004", "name": "Bug", "hierarchyLevel": 0},
            {"id": "10005", "name": "Defect", "hierarchyLevel": 0},  # excluded
            {"id": "10006", "name": "Sub-task", "subtask": True, "hierarchyLevel": -1},
            {  # excluded: not a canonical name
                "id": "10007",
                "name": "Technical task",
                "subtask": True,
                "hierarchyLevel": -1,
            },
        ]
        chain = canonical_default_hierarchy(types)
        # Only the five standard types, on their tiers; classic show/estimate
        # (only the Epic tier shown, every tier estimated).
        assert [
            (n.issue_type, n.display_tier, n.show, n.in_estimate, n.edge)
            for n in chain
        ] == [
            ("Epic", 0, True, True, "parent"),
            ("Story", 1, False, True, "parent"),
            ("Task", 1, False, True, "parent"),
            ("Bug", 1, False, True, "parent"),
            ("Sub-task", 2, False, True, "parent"),
        ]

    def test_collapses_cross_project_duplicates_to_lowest_id(self) -> None:
        types = [
            {"id": "10000", "name": "Epic", "hierarchyLevel": 1},
            {"id": "10050", "name": "Bug", "hierarchyLevel": 0},
            {"id": "10010", "name": "Bug", "hierarchyLevel": 0},  # lower id wins
            {"id": "10020", "name": "Subtask", "subtask": True, "hierarchyLevel": -1},
        ]
        chain = canonical_default_hierarchy(types)
        ids = {n.issue_type: n.issue_type_id for n in chain}
        assert ids["Bug"] == "10010"  # one Bug card, the lowest-id one
        # the hyphen-less "Subtask" is accepted for the Sub-task tier
        sub = next(n for n in chain if n.issue_type == "Subtask")
        assert sub.display_tier == 2
        assert [n.issue_type for n in chain] == ["Epic", "Bug", "Subtask"]

    def test_skips_missing_canonical_types(self) -> None:
        # An instance without Task/Bug → default is just Epic, Story, Sub-task.
        types = [
            {"id": "1", "name": "Epic", "hierarchyLevel": 1},
            {"id": "2", "name": "Story", "hierarchyLevel": 0},
            {"id": "3", "name": "Sub-task", "subtask": True, "hierarchyLevel": -1},
        ]
        assert [n.issue_type for n in canonical_default_hierarchy(types)] == [
            "Epic",
            "Story",
            "Sub-task",
        ]

    def test_falls_back_to_classic_triple_without_metadata(self) -> None:
        chain = canonical_default_hierarchy(None)
        assert [n.issue_type for n in chain] == ["Epic", "Story", "Sub-task"]


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
