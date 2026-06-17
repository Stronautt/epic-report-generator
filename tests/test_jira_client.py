"""Tests for epic_report_generator.core.jira_client."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from jira import JIRAError

from epic_report_generator.core.jira_client import JiraClient
from epic_report_generator.services.auth_manager import AuthManager
from epic_report_generator.services.config_manager import ConfigManager

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_config(tmp_path: Path) -> ConfigManager:
    mgr = ConfigManager()
    mgr._dir = tmp_path
    mgr._path = tmp_path / "config.json"
    mgr.reset()
    return mgr


def _make_auth(tmp_path: Path, **overrides: str) -> AuthManager:
    cfg = _make_config(tmp_path)
    for k, v in overrides.items():
        cfg.set(k, v)
    return AuthManager(cfg)


def _make_raw_issue(
    key: str = "PROJ-1",
    summary: str = "Fix bug",
    status: str = "Open",
    status_cat: str = "To Do",
    sp: float | None = 5.0,
    epic_link: str | object | None = None,
    parent: str | None = None,
) -> SimpleNamespace:
    """Build a mock Jira raw issue matching the attrs used by JiraClient.

    *epic_link* populates the Epic-Link custom field (``customfield_10014``) and
    *parent* attaches a ``parent`` object — both used by the batched fetch to
    regroup children back to their epic. A child must carry one or the other to
    be grouped under an epic.
    """
    status_obj = SimpleNamespace(
        statusCategory=SimpleNamespace(name=status_cat),
    )
    status_obj.__str__ = lambda self: status  # type: ignore[assignment]
    fields = SimpleNamespace(
        summary=summary,
        status=status_obj,
        priority=SimpleNamespace(name="Medium"),
        assignee=SimpleNamespace(displayName="Alice"),
        reporter=SimpleNamespace(displayName="Bob"),
        created="2024-01-10T10:00:00.000+0000",
        updated="2024-06-01T12:00:00.000+0000",
        labels=["backend"],
        fixVersions=[],
        issuetype=SimpleNamespace(name="Story"),
        resolution=None,
        resolutiondate=None,
        story_points=sp,
        customfield_10014=epic_link,
        customfield_10016=None,
        startdate="2024-01-10",
        duedate="2024-01-20",
    )
    if parent is not None:
        fields.parent = SimpleNamespace(key=parent)
    return SimpleNamespace(key=key, fields=fields)


# ---------------------------------------------------------------------------
# connection
# ---------------------------------------------------------------------------


class TestConnected:
    def test_not_connected_initially(self, tmp_path: Path) -> None:
        client = JiraClient(_make_auth(tmp_path))
        assert client.connected is False

    def test_connected_after_jira_set(self, tmp_path: Path) -> None:
        client = JiraClient(_make_auth(tmp_path))
        client._jira = MagicMock()
        assert client.connected is True


class TestConnectOAuth:
    @patch("epic_report_generator.services.auth_manager.keyring")
    def test_connect_fails_without_token(
        self,
        mock_keyring: MagicMock,
        tmp_path: Path,
    ) -> None:
        mock_keyring.get_password.return_value = None
        auth = _make_auth(tmp_path, cloud_id="cid")
        client = JiraClient(auth)
        assert client.connect() is False

    @patch("epic_report_generator.services.auth_manager.keyring")
    def test_connect_fails_without_cloud_id(
        self,
        mock_keyring: MagicMock,
        tmp_path: Path,
    ) -> None:
        mock_keyring.get_password.return_value = None
        auth = _make_auth(tmp_path)
        client = JiraClient(auth)
        assert client.connect() is False


# ---------------------------------------------------------------------------
# static helpers
# ---------------------------------------------------------------------------


class TestStaticHelpers:
    """Test the static helper methods on JiraClient."""

    def test_name_returns_none_for_none(self) -> None:
        assert JiraClient._name(None) is None

    def test_name_returns_string_as_is(self) -> None:
        assert JiraClient._name("Alice") == "Alice"

    def test_name_extracts_displayName(self) -> None:
        obj = SimpleNamespace(displayName="Bob")
        assert JiraClient._name(obj) == "Bob"

    def test_parse_dt_none(self) -> None:
        assert JiraClient._parse_dt(None) is None

    def test_parse_dt_valid_iso(self) -> None:
        result = JiraClient._parse_dt("2024-01-15T10:30:00.000+0000")
        assert isinstance(result, datetime)
        assert result.year == 2024
        assert result.month == 1
        assert result.day == 15

    def test_parse_dt_invalid(self) -> None:
        assert JiraClient._parse_dt("not-a-date") is None

    def test_parse_date_valid(self) -> None:
        result = JiraClient._parse_date("2024-01-15")
        assert result == date(2024, 1, 15)

    def test_parse_date_none(self) -> None:
        assert JiraClient._parse_date(None) is None

    def test_parse_date_invalid(self) -> None:
        assert JiraClient._parse_date("not-a-date") is None

    def test_status_category_none_fields(self) -> None:
        fields = SimpleNamespace()
        assert JiraClient._status_category(fields) == "To Do"

    def test_status_category_extracts_name(self) -> None:
        fields = SimpleNamespace(
            status=SimpleNamespace(
                statusCategory=SimpleNamespace(name="In Progress"),
            )
        )
        assert JiraClient._status_category(fields) == "In Progress"


# ---------------------------------------------------------------------------
# get_myself
# ---------------------------------------------------------------------------


class TestGetMyself:
    def test_returns_none_when_disconnected(self, tmp_path: Path) -> None:
        client = JiraClient(_make_auth(tmp_path))
        assert client.get_myself() is None

    def test_returns_user_info(self, tmp_path: Path) -> None:
        client = JiraClient(_make_auth(tmp_path))
        client._jira = MagicMock()
        client._jira.myself.return_value = {
            "displayName": "Alice",
            "avatarUrls": {"48x48": "https://example.com/avatar.png"},
            "emailAddress": "alice@example.com",
        }
        me = client.get_myself()
        assert me is not None
        assert me["displayName"] == "Alice"
        assert me["avatarUrl"] == "https://example.com/avatar.png"


# ---------------------------------------------------------------------------
# fetch_epic
# ---------------------------------------------------------------------------


class TestFetchEpic:
    def test_returns_none_when_disconnected(self, tmp_path: Path) -> None:
        client = JiraClient(_make_auth(tmp_path))
        assert client.fetch_epic("PROJ-1") is None

    def test_fetch_epic_returns_epic_data(self, tmp_path: Path) -> None:
        client = JiraClient(_make_auth(tmp_path))
        client._jira = MagicMock()

        raw_epic = _make_raw_issue("PROJ-1", "My Epic")
        raw_child = _make_raw_issue("PROJ-2", "Child Issue", sp=3.0, epic_link="PROJ-1")

        # Call 1: combined epic + children query; Call 2: subtasks
        client._jira.search_issues.side_effect = [[raw_epic, raw_child], []]

        epic = client.fetch_epic("PROJ-1")
        assert epic is not None
        assert epic.key == "PROJ-1"
        assert len(epic.children) == 1
        assert epic.children[0].key == "PROJ-2"

    def test_fetch_epic_populates_date_fields(self, tmp_path: Path) -> None:
        client = JiraClient(_make_auth(tmp_path))
        client._jira = MagicMock()

        raw_epic = _make_raw_issue("PROJ-1", "My Epic")
        raw_child = _make_raw_issue("PROJ-2", "Child Issue", sp=3.0, epic_link="PROJ-1")

        client._jira.search_issues.side_effect = [[raw_epic, raw_child], []]

        epic = client.fetch_epic("PROJ-1")
        assert epic is not None
        assert len(epic.children) == 1
        assert epic.children[0].start_date == date(2024, 1, 10)
        assert epic.children[0].due_date == date(2024, 1, 20)

    def test_fetch_epic_returns_none_for_missing_key(self, tmp_path: Path) -> None:
        client = JiraClient(_make_auth(tmp_path))
        client._jira = MagicMock()
        client._jira.search_issues.return_value = []

        assert client.fetch_epic("MISSING-1") is None


# ---------------------------------------------------------------------------
# validate_epic_key
# ---------------------------------------------------------------------------


class TestValidateEpicKey:
    def test_valid_key(self, tmp_path: Path) -> None:
        client = JiraClient(_make_auth(tmp_path))
        client._jira = MagicMock()
        client._jira.search_issues.return_value = [_make_raw_issue("PROJ-1")]
        assert client.validate_epic_key("PROJ-1") is True

    def test_invalid_key(self, tmp_path: Path) -> None:
        client = JiraClient(_make_auth(tmp_path))
        client._jira = MagicMock()
        client._jira.search_issues.return_value = []
        assert client.validate_epic_key("NOPE-1") is False

    def test_returns_false_when_disconnected(self, tmp_path: Path) -> None:
        client = JiraClient(_make_auth(tmp_path))
        assert client.validate_epic_key("X-1") is False


# ---------------------------------------------------------------------------
# retry logic
# ---------------------------------------------------------------------------


class TestRetryLogic:
    def test_retries_on_429(self, tmp_path: Path) -> None:
        """_search_with_retry should retry after a 429 status."""
        client = JiraClient(_make_auth(tmp_path))
        client._jira = MagicMock()

        exc = JIRAError(status_code=429, text="Rate limited")
        client._jira.search_issues.side_effect = [exc, [_make_raw_issue()]]

        with patch("epic_report_generator.core.jira_client.time.sleep"):
            results = client._search_with_retry("key = X-1")

        assert len(results) == 1
        assert client._jira.search_issues.call_count == 2

    def test_raises_non_429_errors(self, tmp_path: Path) -> None:
        """Non-429 JIRAErrors should propagate immediately."""
        client = JiraClient(_make_auth(tmp_path))
        client._jira = MagicMock()

        exc = JIRAError(status_code=404, text="Not found")
        client._jira.search_issues.side_effect = exc

        with pytest.raises(JIRAError):
            client._search_with_retry("key = X-1")


# ---------------------------------------------------------------------------
# fetch_fields / get_project_name
# ---------------------------------------------------------------------------


class TestFetchFields:
    def test_returns_empty_when_disconnected(self, tmp_path: Path) -> None:
        client = JiraClient(_make_auth(tmp_path))
        assert client.fetch_fields() == []

    def test_returns_field_list(self, tmp_path: Path) -> None:
        client = JiraClient(_make_auth(tmp_path))
        client._jira = MagicMock()
        client._jira.fields.return_value = [
            {"id": "summary", "name": "Summary", "custom": False},
            {"id": "customfield_10016", "name": "Story Points", "custom": True},
        ]
        fields = client.fetch_fields()
        assert len(fields) == 2
        assert fields[1]["id"] == "customfield_10016"


class TestFetchSubtasks:
    """Test subtask fetching in the batched bulk fetch."""

    def test_subtasks_included_by_default(self, tmp_path: Path) -> None:
        """When include_subtasks=True, subtasks of children are fetched."""
        client = JiraClient(_make_auth(tmp_path))
        client._jira = MagicMock()

        raw_epic = _make_raw_issue("PROJ-1", "My Epic")
        raw_child = _make_raw_issue("PROJ-2", "Child Story", sp=3.0, epic_link="PROJ-1")
        raw_subtask = _make_raw_issue("PROJ-3", "Subtask", sp=1.0, parent="PROJ-2")

        # Call 1: combined epic + direct children; Call 2: subtasks of children
        client._jira.search_issues.side_effect = [
            [raw_epic, raw_child],
            [raw_subtask],
        ]

        epic = client.fetch_epic("PROJ-1")
        assert epic is not None
        assert len(epic.children) == 2
        keys = {c.key for c in epic.children}
        assert keys == {"PROJ-2", "PROJ-3"}
        # The subtask is flagged; the direct child is not.
        by_key = {c.key: c for c in epic.children}
        assert by_key["PROJ-3"].is_subtask is True
        assert by_key["PROJ-2"].is_subtask is False

    def test_subtasks_skipped_when_disabled(self, tmp_path: Path) -> None:
        """When subtasks are fully disabled, only the combined query runs."""
        client = JiraClient(_make_auth(tmp_path))
        client._jira = MagicMock()

        raw_epic = _make_raw_issue("PROJ-1", "My Epic")
        raw_child = _make_raw_issue("PROJ-2", "Child Story", sp=3.0, epic_link="PROJ-1")

        # Only the combined epic + children query runs.
        client._jira.search_issues.side_effect = [
            [raw_epic, raw_child],
        ]

        epic = client.fetch_epic(
            "PROJ-1", include_subtasks=False, include_subtasks_in_timeline=False
        )
        assert epic is not None
        assert len(epic.children) == 1
        assert epic.children[0].key == "PROJ-2"
        # 1 call: the combined query (no subtask query when fully disabled).
        assert client._jira.search_issues.call_count == 1

    def test_subtasks_deduplicated(self, tmp_path: Path) -> None:
        """A child already seen in phase 1 is not re-added by the subtask query."""
        client = JiraClient(_make_auth(tmp_path))
        client._jira = MagicMock()

        raw_epic = _make_raw_issue("PROJ-1", "My Epic")
        raw_child = _make_raw_issue("PROJ-2", "Child Story", sp=3.0, epic_link="PROJ-1")
        # Subtask query returns the same child key (edge case)
        raw_dup = _make_raw_issue("PROJ-2", "Child Story", sp=3.0, parent="PROJ-2")

        client._jira.search_issues.side_effect = [
            [raw_epic, raw_child],
            [raw_dup],
        ]

        epic = client.fetch_epic("PROJ-1")
        assert epic is not None
        assert len(epic.children) == 1


class TestParentHierarchyChildren:
    """Test that children linked via parent field (Tasks, Defects) are fetched."""

    def test_parent_linked_children_included(self, tmp_path: Path) -> None:
        """Issues linked via parent = epic (e.g. Tasks) are fetched."""
        client = JiraClient(_make_auth(tmp_path))
        client._jira = MagicMock()

        raw_epic = _make_raw_issue("PROJ-1", "My Epic")
        # Story grouped via epic-link; Task grouped via parent hierarchy.
        raw_story = _make_raw_issue("PROJ-2", "A Story", sp=3.0, epic_link="PROJ-1")
        raw_task = _make_raw_issue("PROJ-3", "A Task", sp=2.0, parent="PROJ-1")

        # Call 1: combined query returns the epic plus both children;
        # Call 2: subtasks (empty)
        client._jira.search_issues.side_effect = [
            [raw_epic, raw_story, raw_task],
            [],
        ]

        epic = client.fetch_epic("PROJ-1")
        assert epic is not None
        assert len(epic.children) == 2
        keys = {c.key for c in epic.children}
        assert keys == {"PROJ-2", "PROJ-3"}

    def test_parent_linked_children_deduplicated(self, tmp_path: Path) -> None:
        """A child key appearing twice in the combined result is de-duplicated."""
        client = JiraClient(_make_auth(tmp_path))
        client._jira = MagicMock()

        raw_epic = _make_raw_issue("PROJ-1", "My Epic")
        raw_child = _make_raw_issue("PROJ-2", "Linked Both Ways", sp=3.0, epic_link="PROJ-1")
        raw_child_dup = _make_raw_issue(
            "PROJ-2", "Linked Both Ways", sp=3.0, epic_link="PROJ-1"
        )

        # Call 1: combined query returns the same child twice; Call 2: subtasks
        client._jira.search_issues.side_effect = [
            [raw_epic, raw_child, raw_child_dup],
            [],
        ]

        epic = client.fetch_epic("PROJ-1")
        assert epic is not None
        assert len(epic.children) == 1
        assert epic.children[0].key == "PROJ-2"


class TestGetProjectName:
    def test_returns_none_when_disconnected(self, tmp_path: Path) -> None:
        client = JiraClient(_make_auth(tmp_path))
        assert client.get_project_name("PROJ") is None

    def test_returns_project_name(self, tmp_path: Path) -> None:
        client = JiraClient(_make_auth(tmp_path))
        client._jira = MagicMock()
        client._jira.project.return_value = SimpleNamespace(name="My Project")
        assert client.get_project_name("PROJ") == "My Project"


# ---------------------------------------------------------------------------
# fetch_epics_by_label
# ---------------------------------------------------------------------------


class TestFetchEpicsByLabel:
    def test_returns_empty_when_disconnected(self, tmp_path: Path) -> None:
        client = JiraClient(_make_auth(tmp_path))
        assert client.fetch_epics_by_label("backend") == []

    def test_fetches_epics_by_label(self, tmp_path: Path) -> None:
        client = JiraClient(_make_auth(tmp_path))
        client._jira = MagicMock()

        raw_epic = _make_raw_issue("PROJ-10", "Labelled Epic")
        raw_child = _make_raw_issue("PROJ-11", "Child", sp=3.0, epic_link="PROJ-10")

        # Call 1: label discovery (key-only) returns one epic key
        # Call 2: combined epic + children query for PROJ-10
        # Call 3: subtasks (empty)
        client._jira.search_issues.side_effect = [
            [raw_epic],
            [raw_epic, raw_child],
            [],
        ]

        epics = client.fetch_epics_by_label("backend")
        assert len(epics) == 1
        assert epics[0].key == "PROJ-10"
        assert len(epics[0].children) == 1

    def test_returns_empty_for_no_matches(self, tmp_path: Path) -> None:
        client = JiraClient(_make_auth(tmp_path))
        client._jira = MagicMock()
        client._jira.search_issues.return_value = []

        epics = client.fetch_epics_by_label("nonexistent")
        assert epics == []


# ---------------------------------------------------------------------------
# fetch_fix_version_dates
# ---------------------------------------------------------------------------


class TestFetchFixVersionDates:
    def test_returns_empty_when_disconnected(self, tmp_path: Path) -> None:
        client = JiraClient(_make_auth(tmp_path))
        assert client.fetch_fix_version_dates("PROJ") == {}

    def test_returns_version_dates(self, tmp_path: Path) -> None:
        client = JiraClient(_make_auth(tmp_path))
        client._jira = MagicMock()

        client._jira.project_versions.return_value = [
            SimpleNamespace(name="v1.0", releaseDate="2024-03-15"),
            SimpleNamespace(name="v2.0", releaseDate=None),
        ]

        result = client.fetch_fix_version_dates("PROJ")
        assert len(result) == 2
        assert result["v1.0"] == date(2024, 3, 15)
        assert result["v2.0"] is None

    def test_handles_jira_error(self, tmp_path: Path) -> None:
        client = JiraClient(_make_auth(tmp_path))
        client._jira = MagicMock()
        client._jira.project_versions.side_effect = JIRAError(
            status_code=404, text="Not found"
        )

        result = client.fetch_fix_version_dates("PROJ")
        assert result == {}


# ---------------------------------------------------------------------------
# fetch_epic — epic-level dates
# ---------------------------------------------------------------------------


class TestFetchEpicDates:
    def test_epic_gets_own_dates(self, tmp_path: Path) -> None:
        """Epic's own start/due dates are populated."""
        client = JiraClient(_make_auth(tmp_path))
        client._jira = MagicMock()

        raw_epic = _make_raw_issue("PROJ-1", "Dated Epic")
        # Set dates on the epic itself
        raw_epic.fields.startdate = "2024-01-01"
        raw_epic.fields.duedate = "2024-06-30"

        # Combined query returns just the epic (no children → no subtask query).
        client._jira.search_issues.side_effect = [[raw_epic]]

        epic = client.fetch_epic("PROJ-1", include_subtasks=False)
        assert epic is not None
        assert epic.start_date == date(2024, 1, 1)
        assert epic.due_date == date(2024, 6, 30)

    def test_epic_derives_dates_from_children(self, tmp_path: Path) -> None:
        """When epic has no dates, they are derived from children."""
        client = JiraClient(_make_auth(tmp_path))
        client._jira = MagicMock()

        raw_epic = _make_raw_issue("PROJ-1", "No-dates Epic")
        raw_epic.fields.startdate = None
        raw_epic.fields.duedate = None

        raw_child1 = _make_raw_issue("PROJ-2", "Child 1", epic_link="PROJ-1")
        raw_child1.fields.startdate = "2024-02-01"
        raw_child1.fields.duedate = "2024-03-15"

        raw_child2 = _make_raw_issue("PROJ-3", "Child 2", epic_link="PROJ-1")
        raw_child2.fields.startdate = "2024-01-15"
        raw_child2.fields.duedate = "2024-04-30"

        client._jira.search_issues.side_effect = [
            [raw_epic, raw_child1, raw_child2],  # combined epic + children
            [],  # subtasks
        ]

        epic = client.fetch_epic("PROJ-1")
        assert epic is not None
        assert epic.start_date == date(2024, 1, 15)  # min of children
        assert epic.due_date == date(2024, 4, 30)  # max of children


# ---------------------------------------------------------------------------
# batched bulk fetch: client-side grouping
# ---------------------------------------------------------------------------


class TestBulkGrouping:
    """Children returned by the combined query are grouped back to their epic."""

    def _connected(self, tmp_path: Path) -> JiraClient:
        client = JiraClient(_make_auth(tmp_path))
        client._jira = MagicMock()
        return client

    def test_groups_child_via_epic_link_dict(self, tmp_path: Path) -> None:
        client = self._connected(tmp_path)
        raw_epic = _make_raw_issue("PROJ-1", "Epic")
        # Epic-Link returned as an object/dict rather than a bare string.
        raw_child = _make_raw_issue("PROJ-2", "Child", epic_link={"key": "PROJ-1"})
        client._jira.search_issues.side_effect = [[raw_epic, raw_child], []]

        epics = client._fetch_epics_bulk(["PROJ-1"])
        assert [c.key for c in epics["PROJ-1"].children] == ["PROJ-2"]

    def test_groups_child_via_parent_only(self, tmp_path: Path) -> None:
        """Team-managed children (no Epic-Link) are grouped via parent."""
        client = self._connected(tmp_path)
        raw_epic = _make_raw_issue("PROJ-1", "Epic")
        raw_child = _make_raw_issue("PROJ-2", "Child", epic_link=None, parent="PROJ-1")
        client._jira.search_issues.side_effect = [[raw_epic, raw_child], []]

        epics = client._fetch_epics_bulk(["PROJ-1"])
        assert [c.key for c in epics["PROJ-1"].children] == ["PROJ-2"]

    def test_epic_link_wins_over_parent_when_ambiguous(self, tmp_path: Path) -> None:
        client = self._connected(tmp_path)
        raw_e1 = _make_raw_issue("PROJ-1", "Epic 1")
        raw_e2 = _make_raw_issue("PROJ-2", "Epic 2")
        # epic_link points at PROJ-1, parent at PROJ-2 — epic_link must win.
        raw_child = _make_raw_issue(
            "PROJ-10", "Child", epic_link="PROJ-1", parent="PROJ-2"
        )
        client._jira.search_issues.side_effect = [[raw_e1, raw_e2, raw_child], []]

        epics = client._fetch_epics_bulk(["PROJ-1", "PROJ-2"])
        assert [c.key for c in epics["PROJ-1"].children] == ["PROJ-10"]
        assert epics["PROJ-2"].children == []

    def test_ungroupable_child_is_dropped(self, tmp_path: Path) -> None:
        client = self._connected(tmp_path)
        raw_epic = _make_raw_issue("PROJ-1", "Epic")
        # Neither epic_link nor parent points at a requested epic.
        raw_orphan = _make_raw_issue("PROJ-99", "Orphan", epic_link="OTHER-1")
        # No groupable children → no subtask query, so a single call.
        client._jira.search_issues.side_effect = [[raw_epic, raw_orphan]]

        epics = client._fetch_epics_bulk(["PROJ-1"])
        assert epics["PROJ-1"].children == []
        assert client._jira.search_issues.call_count == 1

    def test_nested_epic_classified_as_epic_not_child(self, tmp_path: Path) -> None:
        """A requested epic that is a child of another requested epic stays an epic."""
        client = self._connected(tmp_path)
        raw_e1 = _make_raw_issue("PROJ-1", "Epic 1")
        # PROJ-2 is requested AND parented to PROJ-1 — key-first keeps it an epic.
        raw_e2 = _make_raw_issue("PROJ-2", "Epic 2", parent="PROJ-1")
        client._jira.search_issues.side_effect = [[raw_e1, raw_e2]]

        epics = client._fetch_epics_bulk(["PROJ-1", "PROJ-2"])
        assert set(epics) == {"PROJ-1", "PROJ-2"}
        assert epics["PROJ-1"].children == []

    def test_multi_epic_single_combined_call_and_subtask_mapping(
        self, tmp_path: Path
    ) -> None:
        client = self._connected(tmp_path)
        raw_e1 = _make_raw_issue("PROJ-1", "Epic 1")
        raw_e2 = _make_raw_issue("PROJ-2", "Epic 2")
        child1 = _make_raw_issue("PROJ-10", "Child of E1", epic_link="PROJ-1")
        child2 = _make_raw_issue("PROJ-20", "Child of E2", epic_link="PROJ-2")
        sub1 = _make_raw_issue("PROJ-11", "Sub of c1", parent="PROJ-10")
        sub2 = _make_raw_issue("PROJ-21", "Sub of c2", parent="PROJ-20")
        client._jira.search_issues.side_effect = [
            [raw_e1, raw_e2, child1, child2],  # one combined query
            [sub1, sub2],  # one subtask query across both epics
        ]

        epics = client._fetch_epics_bulk(["PROJ-1", "PROJ-2"])

        assert client._jira.search_issues.call_count == 2
        assert {c.key for c in epics["PROJ-1"].children} == {"PROJ-10", "PROJ-11"}
        assert {c.key for c in epics["PROJ-2"].children} == {"PROJ-20", "PROJ-21"}
        # Subtasks mapped to the correct epic and flagged.
        e1_subs = [c.key for c in epics["PROJ-1"].children if c.is_subtask]
        assert e1_subs == ["PROJ-11"]


# ---------------------------------------------------------------------------
# field projection
# ---------------------------------------------------------------------------


class TestFieldProjection:
    def test_build_field_list_includes_required_fields(self, tmp_path: Path) -> None:
        client = JiraClient(_make_auth(tmp_path))
        fields = client._build_field_list(
            sp_field="story_points",
            epic_link_field="customfield_10014",
            start_date_field="startdate",
            due_date_field="duedate",
            timeline_start_field="",
            timeline_end_field="",
            sprint_field="customfield_10020",
        )
        # Grouping + parsing essentials must all be present.
        for required in (
            "summary",
            "status",
            "parent",
            "fixVersions",
            "story_points",
            "customfield_10014",  # epic link
            "customfield_10016",  # SP fallback
            "customfield_10020",  # sprint
            "startdate",
            "duedate",
        ):
            assert required in fields
        # No duplicates.
        assert len(fields) == len(set(fields))

    def test_bulk_query_uses_projection_and_post(self, tmp_path: Path) -> None:
        client = JiraClient(_make_auth(tmp_path))
        client._jira = MagicMock()
        client._jira.search_issues.side_effect = [[_make_raw_issue("PROJ-1", "Epic")]]

        client.fetch_epic("PROJ-1")

        call = client._jira.search_issues.call_args_list[0]
        assert call.kwargs["use_post"] is True
        assert call.kwargs["maxResults"] is False  # fetch-all via token pagination
        assert isinstance(call.kwargs["fields"], list)
        assert "parent" in call.kwargs["fields"]

    def test_validate_epic_key_projects_key_only(self, tmp_path: Path) -> None:
        client = JiraClient(_make_auth(tmp_path))
        client._jira = MagicMock()
        client._jira.search_issues.return_value = [_make_raw_issue("PROJ-1")]

        client.validate_epic_key("PROJ-1")
        assert client._jira.search_issues.call_args.kwargs["fields"] == ["key"]

    def test_summary_query_projects_summary_only(self, tmp_path: Path) -> None:
        client = JiraClient(_make_auth(tmp_path))
        client._jira = MagicMock()
        client._jira.search_issues.return_value = []

        client.fetch_child_summaries("PROJ-1")
        for call in client._jira.search_issues.call_args_list:
            assert call.kwargs["fields"] == ["summary"]


# ---------------------------------------------------------------------------
# fetch_report_epics
# ---------------------------------------------------------------------------


class TestFetchReportEpics:
    def test_returns_empty_when_disconnected(self, tmp_path: Path) -> None:
        client = JiraClient(_make_auth(tmp_path))
        assert client.fetch_report_epics(["PROJ-1"], ["backend"]) == ({}, {})

    def test_dedups_overlapping_key_and_preserves_label_order(
        self, tmp_path: Path
    ) -> None:
        client = JiraClient(_make_auth(tmp_path))
        client._jira = MagicMock()

        # PROJ-1 is both a direct item and a member of the "backend" label.
        disc1 = _make_raw_issue("PROJ-1")
        disc2 = _make_raw_issue("PROJ-2")
        raw_e1 = _make_raw_issue("PROJ-1", "Epic 1")
        raw_e2 = _make_raw_issue("PROJ-2", "Epic 2")
        client._jira.search_issues.side_effect = [
            [disc1, disc2],  # label discovery (key-only)
            [raw_e1, raw_e2],  # one combined query for the deduped key set
        ]

        epics_by_key, label_to_keys = client.fetch_report_epics(
            ["PROJ-1"], ["backend"]
        )

        assert set(epics_by_key) == {"PROJ-1", "PROJ-2"}
        assert label_to_keys["backend"] == ["PROJ-1", "PROJ-2"]
        # Discovery (1) + one combined query (1); no subtask query (no children).
        assert client._jira.search_issues.call_count == 2
        combined_jql = client._jira.search_issues.call_args_list[1].args[0]
        assert "PROJ-1" in combined_jql and "PROJ-2" in combined_jql
