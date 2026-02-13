"""Tests for epic_report_generator.core.jira_client."""

from __future__ import annotations

from datetime import datetime, timezone
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
) -> SimpleNamespace:
    """Build a mock Jira raw issue matching the attrs used by JiraClient."""
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
        customfield_10014=None,
        customfield_10016=None,
    )
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
        self, mock_keyring: MagicMock, tmp_path: Path,
    ) -> None:
        mock_keyring.get_password.return_value = None
        auth = _make_auth(tmp_path, cloud_id="cid")
        client = JiraClient(auth)
        assert client.connect() is False

    @patch("epic_report_generator.services.auth_manager.keyring")
    def test_connect_fails_without_cloud_id(
        self, mock_keyring: MagicMock, tmp_path: Path,
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
        raw_child = _make_raw_issue("PROJ-2", "Child Issue", sp=3.0)

        # First call returns the epic, second returns one child, third returns empty
        client._jira.search_issues.side_effect = [[raw_epic], [raw_child], []]

        epic = client.fetch_epic("PROJ-1")
        assert epic is not None
        assert epic.key == "PROJ-1"
        assert len(epic.children) == 1
        assert epic.children[0].key == "PROJ-2"

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


class TestGetProjectName:
    def test_returns_none_when_disconnected(self, tmp_path: Path) -> None:
        client = JiraClient(_make_auth(tmp_path))
        assert client.get_project_name("PROJ") is None

    def test_returns_project_name(self, tmp_path: Path) -> None:
        client = JiraClient(_make_auth(tmp_path))
        client._jira = MagicMock()
        client._jira.project.return_value = SimpleNamespace(name="My Project")
        assert client.get_project_name("PROJ") == "My Project"
