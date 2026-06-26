"""Tests for epic_report_generator.core.jira_client."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
import requests
from jira import JIRAError

from epic_report_generator.core.data_models import EpicData, HierarchyNode, JiraIssue
from epic_report_generator.core.jira_client import JiraClient, _is_custom, _link_targets
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
    type_name: str = "Story",
    type_id: str = "",
    links: list[dict] | None = None,
) -> SimpleNamespace:
    """Build a mock Jira raw issue matching the attrs used by JiraClient.

    *epic_link* populates the Epic-Link custom field (``customfield_10014``) and
    *parent* attaches a ``parent`` object — both used by the batched fetch to
    regroup children back to their epic. A child must carry one or the other to
    be grouped under an epic.  *type_name* / *type_id* set the issue type (the
    id drives custom-chain node matching); *links* sets the ``issuelinks`` field
    (a list of REST link dicts) for link-edge traversal.
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
        issuetype=SimpleNamespace(name=type_name, id=type_id),
        resolution=None,
        resolutiondate=None,
        story_points=sp,
        customfield_10014=epic_link,
        customfield_10016=None,
        startdate="2024-01-10",
        duedate="2024-01-20",
        issuelinks=links or [],
    )
    if parent is not None:
        fields.parent = SimpleNamespace(key=parent)
    return SimpleNamespace(key=key, fields=fields)


def _link(name: str, target_key: str, direction: str = "outward") -> dict:
    """Build an ``issuelinks`` entry of *name* pointing at *target_key*."""
    end = "outwardIssue" if direction == "outward" else "inwardIssue"
    return {"type": {"name": name}, end: {"key": target_key}}


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


class _RecordingSession:
    """Stand-in for jira's ResilientSession that records timeout values.

    ``_search_with_retry`` mutates ``session.timeout`` per attempt, so the
    recorded sequence proves the progressive 1→3→5 escalation and the baseline
    restore.
    """

    def __init__(self) -> None:
        self.timeout: object = 5  # the baseline our JIRA(...) constructor sets
        self.seen: list[object] = []


def _client_with_recording_session(
    tmp_path: Path, outcomes: list[object]
) -> tuple[JiraClient, _RecordingSession]:
    """Build a connected client whose ``search_issues`` plays *outcomes* in order.

    Each outcome is either an ``Exception`` to raise or a value to return; the
    session's current ``timeout`` is recorded immediately before each call.
    """
    client = JiraClient(_make_auth(tmp_path))
    jira = MagicMock()
    session = _RecordingSession()
    jira._session = session
    outcomes_iter = iter(outcomes)

    def _search(*_args: object, **_kwargs: object) -> object:
        session.seen.append(session.timeout)
        outcome = next(outcomes_iter)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    jira.search_issues.side_effect = _search
    client._jira = jira
    return client, session


class TestProgressiveTimeout:
    def test_retries_on_read_timeout_and_escalates(self, tmp_path: Path) -> None:
        """A stalled-body ReadTimeout retries on a longer timeout, then succeeds."""
        timeout_exc = requests.exceptions.ReadTimeout("stalled body read")
        client, session = _client_with_recording_session(
            tmp_path, [timeout_exc, [_make_raw_issue()]]
        )

        with patch("epic_report_generator.core.jira_client.time.sleep"):
            results = client._search_with_retry("key = X-1")

        assert len(results) == 1
        assert client._jira.search_issues.call_count == 2
        assert session.seen == [1, 3]  # progressive 1s → 3s
        assert session.timeout == 5  # baseline restored after success

    def test_exhausts_progressive_timeouts_then_raises(self, tmp_path: Path) -> None:
        """Persistent transport failure walks 1→3→5 then re-raises."""
        exc = requests.exceptions.ReadTimeout("dead socket")
        client, session = _client_with_recording_session(tmp_path, [exc, exc, exc])

        with patch("epic_report_generator.core.jira_client.time.sleep"):
            with pytest.raises(requests.exceptions.Timeout):
                client._search_with_retry("key = X-1")

        assert session.seen == [1, 3, 5]
        assert session.timeout == 5  # baseline restored even on failure


class TestReauthOn401:
    def test_oauth_reauthenticates_once_then_retries(self, tmp_path: Path) -> None:
        client = JiraClient(_make_auth(tmp_path))
        client._jira = MagicMock()
        client._auth_method = "oauth"
        exc = JIRAError(status_code=401, text="Unauthorized")
        client._jira.search_issues.side_effect = [exc, [_make_raw_issue()]]

        with (
            patch.object(client, "reauthenticate", return_value=True) as reauth,
            patch("epic_report_generator.core.jira_client.time.sleep"),
        ):
            results = client._search_with_retry("key = X-1")

        assert len(results) == 1
        reauth.assert_called_once()
        assert client._jira.search_issues.call_count == 2

    def test_api_token_401_does_not_loop(self, tmp_path: Path) -> None:
        """An API-token 401 can't self-heal — single attempt, then re-raise."""
        client = JiraClient(_make_auth(tmp_path))
        client._jira = MagicMock()
        client._auth_method = "api_token"
        client._jira.search_issues.side_effect = JIRAError(
            status_code=401, text="Unauthorized"
        )

        with pytest.raises(JIRAError):
            client._search_with_retry("key = X-1")

        assert client._jira.search_issues.call_count == 1

    def test_reauthenticate_returns_false_for_api_token(self, tmp_path: Path) -> None:
        client = JiraClient(_make_auth(tmp_path))
        client._auth_method = "api_token"
        assert client.reauthenticate() is False

    def test_oauth_401_on_final_attempt_still_retries(self, tmp_path: Path) -> None:
        """A 401 surfacing only on the final attempt must still reauth and retry."""
        from epic_report_generator.core import jira_client as jc

        client = JiraClient(_make_auth(tmp_path))
        client._jira = MagicMock()
        client._auth_method = "oauth"
        timeout = requests.exceptions.ReadTimeout("slow")
        exc = JIRAError(status_code=401, text="Unauthorized")
        # Burn every retryable attempt, then 401 on the last one before success.
        client._jira.search_issues.side_effect = [
            *([timeout] * (len(jc._PROGRESSIVE_TIMEOUTS) - 1)),
            exc,
            [_make_raw_issue()],
        ]

        with (
            patch.object(client, "reauthenticate", return_value=True) as reauth,
            patch("epic_report_generator.core.jira_client.time.sleep"),
        ):
            results = client._search_with_retry("key = X-1")

        assert len(results) == 1
        reauth.assert_called_once()


class TestConnectTimeout:
    def test_connect_basic_passes_timeout(self, tmp_path: Path) -> None:
        from epic_report_generator.core import jira_client as jc

        client = JiraClient(_make_auth(tmp_path))
        fake = MagicMock()
        fake.myself.return_value = {"displayName": "X"}
        with patch.object(jc, "JIRA", return_value=fake) as ctor:
            ok = client.connect_basic("https://x.atlassian.net", "e@x.com", "tok")

        assert ok is True
        assert ctor.call_args.kwargs.get("timeout") == jc._PROGRESSIVE_TIMEOUTS[-1]
        assert client._auth_method == "api_token"

    def test_connect_oauth_passes_timeout(self, tmp_path: Path) -> None:
        from epic_report_generator.core import jira_client as jc

        client = JiraClient(_make_auth(tmp_path))
        client._auth.get_access_token = MagicMock(return_value="tok")  # type: ignore[method-assign]
        client._auth.set_cloud_id("cid")
        with patch.object(jc, "JIRA", return_value=MagicMock()) as ctor:
            ok = client.connect()

        assert ok is True
        assert ctor.call_args.kwargs.get("timeout") == jc._PROGRESSIVE_TIMEOUTS[-1]
        assert client._auth_method == "oauth"


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


class TestHierarchyMetadata:
    """Issue-type / link-type / icon / picker metadata for the constructor."""

    @staticmethod
    def _connected(tmp_path: Path) -> JiraClient:
        client = JiraClient(_make_auth(tmp_path))
        client._jira = MagicMock()
        client._jira.server_url = "https://example.atlassian.net"
        return client

    def test_issue_types_disconnected(self, tmp_path: Path) -> None:
        assert JiraClient(_make_auth(tmp_path)).fetch_issue_types() == []

    def test_issue_types_parse_and_cache(self, tmp_path: Path) -> None:
        client = self._connected(tmp_path)
        client._jira.issue_types.return_value = [
            SimpleNamespace(
                id=10000,
                name="Epic",
                iconUrl="https://x/epic.svg",
                subtask=False,
                hierarchyLevel=2,
            ),
            SimpleNamespace(
                id=10001,
                name="Sub-task",
                iconUrl="https://x/sub.svg",
                subtask=True,
                hierarchyLevel=-1,
            ),
        ]
        types = client.fetch_issue_types()
        assert types[0] == {
            "id": "10000",
            "name": "Epic",
            "iconUrl": "https://x/epic.svg",
            "subtask": False,
            "hierarchyLevel": 2,
        }
        assert types[1]["subtask"] is True and types[1]["hierarchyLevel"] == -1
        # second call is served from cache (no extra API hit)
        client.fetch_issue_types()
        assert client._jira.issue_types.call_count == 1

    def test_link_types_parse_and_cache(self, tmp_path: Path) -> None:
        client = self._connected(tmp_path)
        client._jira.issue_link_types.return_value = [
            SimpleNamespace(
                id=10100, name="Blocks", inward="is blocked by", outward="blocks"
            ),
        ]
        links = client.fetch_issue_link_types()
        assert links == [
            {
                "id": "10100",
                "name": "Blocks",
                "inward": "is blocked by",
                "outward": "blocks",
            }
        ]
        client.fetch_issue_link_types()
        assert client._jira.issue_link_types.call_count == 1

    def test_invalidate_caches_clears_metadata(self, tmp_path: Path) -> None:
        client = self._connected(tmp_path)
        client._jira.issue_types.return_value = [
            SimpleNamespace(
                id=1, name="Epic", iconUrl="", subtask=False, hierarchyLevel=2
            )
        ]
        client._jira.issue_link_types.return_value = []
        client.fetch_issue_types()
        client.fetch_issue_link_types()
        client._icon_cache["1"] = b"cached"
        client.invalidate_caches()
        assert client._issue_types_cache is None
        assert client._link_types_cache is None
        assert client._icon_cache == {}
        # re-fetch hits the API again
        client.fetch_issue_types()
        assert client._jira.issue_types.call_count == 2

    def test_issue_picker_parses_sections(self, tmp_path: Path) -> None:
        client = self._connected(tmp_path)
        resp = MagicMock(status_code=200)
        resp.json.return_value = {
            "sections": [
                {
                    "issues": [
                        {"key": "PROJ-1", "summaryText": "Login epic"},
                        {"key": "PROJ-2", "summary": "Fallback summary"},
                    ]
                },
                {"issues": [{"key": "PROJ-1", "summaryText": "dup dropped"}]},
            ]
        }
        client._jira._session.get.return_value = resp
        out = client.fetch_issue_picker("log", current_jql="issuetype = Epic")
        assert out == [("PROJ-1", "Login epic"), ("PROJ-2", "Fallback summary")]
        # currentJQL is forwarded
        _, kwargs = client._jira._session.get.call_args
        assert kwargs["params"]["currentJQL"] == "issuetype = Epic"
        # No explicit timeout: the jira ResilientSession injects its own and
        # raises "got multiple values for keyword argument 'timeout'" otherwise.
        assert "timeout" not in kwargs

    def test_issue_picker_blank_query_skips_request(self, tmp_path: Path) -> None:
        client = self._connected(tmp_path)
        assert client.fetch_issue_picker("   ") == []
        client._jira._session.get.assert_not_called()

    def test_issue_picker_caches_by_query(self, tmp_path: Path) -> None:
        """A repeated (query, jql) is served from cache — no second request."""
        client = self._connected(tmp_path)
        resp = MagicMock(status_code=200)
        resp.json.return_value = {"sections": [{"issues": [{"key": "PROJ-1"}]}]}
        client._jira._session.get.return_value = resp
        first = client.fetch_issue_picker("log", current_jql="issuetype = Epic")
        second = client.fetch_issue_picker("log", current_jql="issuetype = Epic")
        assert first == second == [("PROJ-1", "")]
        assert client._jira._session.get.call_count == 1  # cached on repeat
        # A different query still hits the network.
        client.fetch_issue_picker("logi", current_jql="issuetype = Epic")
        assert client._jira._session.get.call_count == 2
        # Refresh clears the cache → the original query re-fetches.
        client.invalidate_caches()
        client.fetch_issue_picker("log", current_jql="issuetype = Epic")
        assert client._jira._session.get.call_count == 3

    def test_issue_type_icon_fetches_and_caches(self, tmp_path: Path) -> None:
        client = self._connected(tmp_path)
        client._jira.issue_types.return_value = [
            SimpleNamespace(
                id=10000,
                name="Epic",
                iconUrl="https://x/epic.svg",
                subtask=False,
                hierarchyLevel=2,
            )
        ]
        resp = MagicMock(status_code=200, content=b"<svg/>")
        client._jira._session.get.return_value = resp
        assert client.issue_type_icon("10000") == b"<svg/>"
        # cached: a second call does not GET again
        assert client.issue_type_icon("10000") == b"<svg/>"
        assert client._jira._session.get.call_count == 1
        # No explicit timeout (ResilientSession injects its own; see picker test).
        _, kwargs = client._jira._session.get.call_args
        assert "timeout" not in kwargs

    def test_issue_type_icon_unknown_type(self, tmp_path: Path) -> None:
        client = self._connected(tmp_path)
        client._jira.issue_types.return_value = []
        assert client.issue_type_icon("999") is None
        client._jira._session.get.assert_not_called()

    def test_issue_type_icon_http_error_caches_none(self, tmp_path: Path) -> None:
        client = self._connected(tmp_path)
        client._jira.issue_types.return_value = [
            SimpleNamespace(
                id=10000,
                name="Epic",
                iconUrl="https://x/epic.svg",
                subtask=False,
                hierarchyLevel=2,
            )
        ]
        client._jira._session.get.return_value = MagicMock(status_code=404, content=b"")
        assert client.issue_type_icon("10000") is None
        # the failure is cached — no retry storm
        assert client.issue_type_icon("10000") is None
        assert client._jira._session.get.call_count == 1


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

    def test_chain_drops_off_chain_type_on_fast_path(self, tmp_path: Path) -> None:
        """A parent-only chain that omits a child's type drops it (fast path).

        This is the "Exclude pool drops a type" behaviour: the default all-types
        chain keeps every type, but removing one (here Task) filters it from the
        report via apply_hierarchy — even on the fast 2-query path.
        """
        client = JiraClient(_make_auth(tmp_path))
        client._jira = MagicMock()

        raw_epic = _make_raw_issue("PROJ-1", "Epic", type_name="Epic", type_id="E")
        story = _make_raw_issue(
            "PROJ-2", "Story", epic_link="PROJ-1", type_name="Story", type_id="S"
        )
        task = _make_raw_issue(
            "PROJ-3", "Task", epic_link="PROJ-1", type_name="Task", type_id="T"
        )
        client._jira.search_issues.side_effect = [[raw_epic, story, task], []]

        chain = [
            HierarchyNode("E", "Epic", display_tier=0),
            HierarchyNode("S", "Story", edge="parent", display_tier=1),  # no Task
            HierarchyNode("SUB", "Sub-task", edge="parent", display_tier=2),
        ]
        epic = client.fetch_epic("PROJ-1", chain=chain)
        assert epic is not None
        assert {c.key for c in epic.children} == {"PROJ-2"}  # Task dropped
        assert epic.children[0].display_tier == 1

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


# ---------------------------------------------------------------------------
# custom issue-type hierarchy chain (Task 3)
# ---------------------------------------------------------------------------


def _cap_feat_story_chain(
    *,
    feature_show: bool = True,
    feature_estimate: bool = True,
    story_show: bool = True,
    story_estimate: bool = True,
) -> list[HierarchyNode]:
    """Capability —(link Blocks)→ Feature —(parent)→ Story (a custom chain)."""
    return [
        HierarchyNode(issue_type_id="C", issue_type="Capability", display_tier=0),
        HierarchyNode(
            issue_type_id="F",
            issue_type="Feature",
            edge="link",
            link_types=["Blocks"],
            display_tier=1,
            show=feature_show,
            in_estimate=feature_estimate,
        ),
        HierarchyNode(
            issue_type_id="S",
            issue_type="Story",
            edge="parent",
            display_tier=2,
            show=story_show,
            in_estimate=story_estimate,
        ),
    ]


class TestIsCustom:
    def test_empty_or_none_is_default(self) -> None:
        assert _is_custom(None) is False
        assert _is_custom([]) is False

    def test_three_node_parent_chain_is_default(self) -> None:
        chain = [
            HierarchyNode("1", "Epic", display_tier=0),
            HierarchyNode("2", "Story", edge="parent", display_tier=1),
            HierarchyNode("3", "Sub-task", edge="parent", display_tier=2),
        ]
        assert _is_custom(chain) is False

    def test_link_edge_is_custom(self) -> None:
        assert _is_custom(_cap_feat_story_chain()) is True

    def test_many_parent_nodes_stay_on_fast_path(self) -> None:
        # A wide parent-only chain (several types at one tier = siblings) is NOT
        # custom: the fast path's epic→children→subtasks structure expresses it,
        # and apply_hierarchy filters by type. Only link edges force the BFS.
        chain = [
            HierarchyNode("1", "Epic", display_tier=0),
            HierarchyNode("2", "Story", edge="parent", display_tier=1),
            HierarchyNode("3", "Task", edge="parent", display_tier=1),
            HierarchyNode("4", "Bug", edge="parent", display_tier=1),
            HierarchyNode("5", "Sub-task", edge="parent", display_tier=2),
        ]
        assert _is_custom(chain) is False

    def test_link_edge_is_custom_regardless_of_size(self) -> None:
        chain = [
            HierarchyNode("1", "Epic", display_tier=0),
            HierarchyNode("2", "Story", edge="link", link_types=["blocks"],
                          display_tier=1),
        ]
        assert _is_custom(chain) is True


class TestLinkTargets:
    def test_matches_either_direction_filters_and_dedups(self) -> None:
        rows = [
            SimpleNamespace(
                key="CAP-1",
                fields=SimpleNamespace(
                    issuelinks=[
                        _link("Blocks", "FEAT-1", "outward"),
                        _link("Relates", "FEAT-9", "outward"),  # wrong type → dropped
                        _link("Blocks", "FEAT-2", "inward"),  # inward counts
                    ]
                ),
            ),
            SimpleNamespace(
                key="CAP-2",
                fields=SimpleNamespace(
                    issuelinks=[_link("Blocks", "FEAT-1", "outward")]  # dup target
                ),
            ),
        ]
        targets = _link_targets(rows, ["Blocks"])
        assert targets == {"FEAT-1": "CAP-1", "FEAT-2": "CAP-1"}

    def test_empty_link_types_matches_any(self) -> None:
        # Empty list means "(any)" in the editor — must match every link type,
        # not silently fetch nothing.
        rows = [
            SimpleNamespace(
                key="CAP-1",
                fields=SimpleNamespace(
                    issuelinks=[
                        _link("Blocks", "FEAT-1", "outward"),
                        _link("Relates", "FEAT-2", "inward"),
                    ]
                ),
            )
        ]
        assert _link_targets(rows, []) == {"FEAT-1": "CAP-1", "FEAT-2": "CAP-1"}


class TestChainTraversal:
    def _client(self, tmp_path: Path) -> JiraClient:
        client = JiraClient(_make_auth(tmp_path))
        client._jira = MagicMock()
        return client

    def test_parent_and_link_traversal(self, tmp_path: Path) -> None:
        client = self._client(tmp_path)
        cap = _make_raw_issue(
            "CAP-1", "Cap", type_name="Capability", type_id="C",
            links=[_link("Blocks", "FEAT-1")],
        )
        feat = _make_raw_issue("FEAT-1", "Feat", type_name="Feature", type_id="F")
        story = _make_raw_issue(
            "STORY-1", "Story", type_name="Story", type_id="S", parent="FEAT-1"
        )
        # phase0 (key in), tier1 link (key in FEAT-1), tier2 parent (parent in)
        client._jira.search_issues.side_effect = [[cap], [feat], [story]]

        epic = client.fetch_epic("CAP-1", chain=_cap_feat_story_chain())
        assert epic is not None
        by_key = {c.key: c for c in epic.children}
        assert set(by_key) == {"FEAT-1", "STORY-1"}
        assert by_key["FEAT-1"].hierarchy_parent_key == "CAP-1"
        assert by_key["FEAT-1"].display_tier == 1
        assert by_key["STORY-1"].hierarchy_parent_key == "FEAT-1"
        assert by_key["STORY-1"].display_tier == 2

    def test_multi_node_tier_does_not_collapse_frontier(
        self, tmp_path: Path
    ) -> None:
        """Two nodes at a tier + a link edge at the next tier (the HHP-410 shape).

        Chain: Epic / Story+Bug (parent) / Task (link Blocks) + Sub-task (parent),
        where the Tasks are link-children of the Story.  Walking the chain
        node-by-node used to reassign the BFS frontier after *every* node, so the
        second tier-1 node (Bug, no children) overwrote the Story frontier with an
        empty one and the deeper Task tier broke on ``if not frontier`` — the
        link-edge Tasks never got fetched.  Tier-grouped traversal keeps the Story
        in the tier-1 frontier, so the many-to-many Task tier resolves.
        """
        client = self._client(tmp_path)
        chain = [
            HierarchyNode("E", "Epic", display_tier=0),
            HierarchyNode("S", "Story", edge="parent", display_tier=1),
            HierarchyNode("B", "Bug", edge="parent", display_tier=1),
            HierarchyNode(
                "T", "Task", edge="link", link_types=["Blocks"], display_tier=2
            ),
            HierarchyNode("ST", "Sub-task", edge="parent", display_tier=2),
        ]
        epic = _make_raw_issue("EPIC-1", type_name="Epic", type_id="E")
        story = _make_raw_issue(
            "STORY-1", type_name="Story", type_id="S", parent="EPIC-1",
            links=[_link("Blocks", "TASK-1")],
        )
        task = _make_raw_issue("TASK-1", type_name="Task", type_id="T")
        # phase0 (key in EPIC-1); tier1 parent (parent in EPIC-1) -> Story, no Bug;
        # tier2 parent (parent in STORY-1) -> none; tier2 link (key in TASK-1).
        client._jira.search_issues.side_effect = [[epic], [story], [], [task]]

        result = client.fetch_epic("EPIC-1", chain=chain)
        assert result is not None
        by_key = {c.key: c for c in result.children}
        assert set(by_key) == {"STORY-1", "TASK-1"}
        assert by_key["TASK-1"].display_tier == 2
        assert by_key["TASK-1"].hierarchy_parent_key == "STORY-1"

    def test_show_and_estimate_both_cascade(self, tmp_path: Path) -> None:
        """Both axes AND-cascade down the parent chain: a hidden Feature hides
        its Story; an unestimated Story is excluded from the metrics."""
        client = self._client(tmp_path)
        cap = _make_raw_issue(
            "CAP-1", type_name="Capability", type_id="C",
            links=[_link("Blocks", "FEAT-1")],
        )
        feat = _make_raw_issue("FEAT-1", type_name="Feature", type_id="F")
        story = _make_raw_issue("STORY-1", type_name="Story", type_id="S", parent="FEAT-1")
        client._jira.search_issues.side_effect = [[cap], [feat], [story]]

        chain = _cap_feat_story_chain(feature_show=False, story_estimate=False)
        epic = client.fetch_epic("CAP-1", chain=chain)
        assert epic is not None
        by_key = {c.key: c for c in epic.children}
        # Feature hidden by its own node; Story hidden too because its parent
        # Feature is hidden (show cascades down the ancestry).
        assert by_key["FEAT-1"].show is False
        assert by_key["STORY-1"].show is False
        # in_estimate cascades the same way: Story's own estimate flag is off.
        assert by_key["FEAT-1"].in_estimate is True
        assert by_key["STORY-1"].in_estimate is False

    def test_off_chain_child_dropped(self, tmp_path: Path) -> None:
        """A type not in the chain (Exclude pane) is dropped, not leaked in.

        A parent-edge tier's untyped ``parent in (...)`` query pulls every child
        of the frontier, including off-chain types; ``apply_hierarchy`` must drop
        them rather than keep them at JiraIssue defaults (shown + estimated).
        """
        client = self._client(tmp_path)
        cap = _make_raw_issue(
            "CAP-1", type_name="Capability", type_id="C",
            links=[_link("Blocks", "FEAT-1")],
        )
        feat = _make_raw_issue("FEAT-1", type_name="Feature", type_id="F")
        story = _make_raw_issue("STORY-1", type_name="Story", type_id="S", parent="FEAT-1")
        bug = _make_raw_issue("BUG-1", type_name="Bug", type_id="B", parent="FEAT-1")
        # tier2 parent query returns the Story plus an off-chain Bug.
        client._jira.search_issues.side_effect = [[cap], [feat], [story, bug]]

        epic = client.fetch_epic("CAP-1", chain=_cap_feat_story_chain())
        assert epic is not None
        assert {c.key for c in epic.children} == {"FEAT-1", "STORY-1"}

    def test_off_chain_intermediate_does_not_leak_grandchildren(
        self, tmp_path: Path
    ) -> None:
        """An off-chain *intermediate* tier is pruned, so its on-chain-typed
        descendants are never advanced (they'd otherwise leak under a dropped
        parent with a broken ancestry)."""
        client = self._client(tmp_path)
        cap = _make_raw_issue(
            "CAP-1", type_name="Capability", type_id="C",
            links=[_link("Blocks", "FEAT-1"), _link("Blocks", "BUG-1")],
        )
        feat = _make_raw_issue("FEAT-1", type_name="Feature", type_id="F")
        bug = _make_raw_issue("BUG-1", type_name="Bug", type_id="B")  # off-chain
        story1 = _make_raw_issue("STORY-1", type_name="Story", type_id="S", parent="FEAT-1")
        # A Story under the off-chain Bug; must NOT leak into the report.
        story2 = _make_raw_issue("STORY-2", type_name="Story", type_id="S", parent="BUG-1")
        # phase0; tier1 link returns Feature + off-chain Bug; tier2 parent query.
        client._jira.search_issues.side_effect = [[cap], [feat, bug], [story1, story2]]

        epic = client.fetch_epic("CAP-1", chain=_cap_feat_story_chain())
        assert epic is not None
        assert {c.key for c in epic.children} == {"FEAT-1", "STORY-1"}

    def test_seen_set_dedups_across_tiers(self, tmp_path: Path) -> None:
        """A target reachable from two parents attaches once (no duplicate row)."""
        client = self._client(tmp_path)
        cap1 = _make_raw_issue(
            "CAP-1", type_name="Capability", type_id="C",
            links=[_link("Blocks", "FEAT-1")],
        )
        cap2 = _make_raw_issue(
            "CAP-2", type_name="Capability", type_id="C",
            links=[_link("Blocks", "FEAT-1")],
        )
        feat = _make_raw_issue("FEAT-1", type_name="Feature", type_id="F")
        # phase0 (both caps), tier1 link (FEAT-1 once), tier2 parent (none)
        client._jira.search_issues.side_effect = [[cap1, cap2], [feat], []]

        epics = client.fetch_report_epics(
            ["CAP-1", "CAP-2"], [], chain=_cap_feat_story_chain()
        )[0]
        feat_owners = [
            e.key for e, in [(e,) for e in epics.values()]
            for c in e.children if c.key == "FEAT-1"
        ]
        assert len(feat_owners) == 1  # attached to exactly one capability

    def test_multi_type_label_scope_in_discovery_jql(self, tmp_path: Path) -> None:
        client = self._client(tmp_path)
        client._jira.search_issues.side_effect = [[], []]  # discovery, then bulk
        client.fetch_report_epics([], ["backend"], chain=_cap_feat_story_chain())
        discovery_jql = client._jira.search_issues.call_args_list[0].args[0]
        assert 'issuetype in ("Capability")' in discovery_jql
        assert 'labels = "backend"' in discovery_jql

    def test_fetch_epic_keys_by_label_defaults_to_epic(self, tmp_path: Path) -> None:
        client = self._client(tmp_path)
        client._jira.search_issues.return_value = []
        client._fetch_epic_keys_by_label("backend")
        jql = client._jira.search_issues.call_args.args[0]
        assert 'issuetype in ("Epic")' in jql


class TestChainAwareChildSummaries:
    def test_link_edge_lists_linked_children(self, tmp_path: Path) -> None:
        client = JiraClient(_make_auth(tmp_path))
        client._jira = MagicMock()
        cap = _make_raw_issue(
            "CAP-1", type_name="Capability", type_id="C",
            links=[_link("Blocks", "FEAT-1")],
        )
        feat = _make_raw_issue("FEAT-1", "A Feature", type_name="Feature", type_id="F")
        # 1) key = CAP-1 (issuelinks), 2) key in (FEAT-1) summaries,
        # 3) key in (FEAT-1) issue-meta (tier filter — FEAT-1 resolves to tier 1).
        client._jira.search_issues.side_effect = [[cap], [feat], [feat]]

        out = client.fetch_child_summaries("CAP-1", chain=_cap_feat_story_chain())
        assert out == [("FEAT-1", "A Feature")]

    def test_default_chain_uses_epic_link_and_parent(self, tmp_path: Path) -> None:
        client = JiraClient(_make_auth(tmp_path))
        client._jira = MagicMock()
        client._jira.search_issues.return_value = []
        client.fetch_child_summaries("PROJ-1")  # no chain
        jqls = [c.args[0] for c in client._jira.search_issues.call_args_list]
        assert any("customfield_10014" in j for j in jqls)
        assert any(j.startswith("parent = PROJ-1") for j in jqls)

    @staticmethod
    def _epic_story_task_chain() -> list[HierarchyNode]:
        # Task is pinned to the Sub-task tier (2), not a sibling of Story.
        return [
            HierarchyNode(issue_type_id="E", issue_type="Epic", display_tier=0),
            HierarchyNode(issue_type_id="S", issue_type="Story", display_tier=1),
            HierarchyNode(issue_type_id="K", issue_type="Task", display_tier=2),
        ]

    def test_epic_fetch_drops_type_pinned_to_deeper_tier(
        self, tmp_path: Path
    ) -> None:
        """A Task pinned to Sub-task tier is absent from the Epic's tier-1 fetch."""
        client = JiraClient(_make_auth(tmp_path))
        client._jira = MagicMock()
        story = _make_raw_issue("STORY-1", "A story", type_name="Story", type_id="S")
        task = _make_raw_issue("TASK-1", "A task", type_name="Task", type_id="K")
        # 1) epic-link (empty), 2) parent = EPIC-1 (story + task),
        # 3) one batched issue-meta lookup that drives the tier filter.
        client._jira.search_issues.side_effect = [[], [story, task], [story, task]]

        out = client.fetch_child_summaries(
            "EPIC-1", chain=self._epic_story_task_chain(), parent_tier=0
        )
        assert out == [("STORY-1", "A story")]  # tier-2 Task dropped at the Epic level
        # Exactly one batched meta call (no per-candidate lookup).
        assert client._jira.search_issues.call_count == 3

    def test_story_fetch_includes_its_subtask_tier(self, tmp_path: Path) -> None:
        """Drilling a Story (parent_tier=1) surfaces its tier-2 children."""
        client = JiraClient(_make_auth(tmp_path))
        client._jira = MagicMock()
        task = _make_raw_issue("TASK-2", "Sub work", type_name="Task", type_id="K")
        # parent = STORY-1 (one query, no epic-link deeper), then the meta lookup.
        client._jira.search_issues.side_effect = [[task], [task]]

        out = client.fetch_child_summaries(
            "STORY-1", chain=self._epic_story_task_chain(), parent_tier=1
        )
        assert out == [("TASK-2", "Sub work")]

    def test_link_child_kept_when_only_type_name_matches(
        self, tmp_path: Path
    ) -> None:
        """A linked child whose type id differs but name matches is still kept.

        The same type name carries different ids across projects (team-managed),
        so the tier filter must resolve id-then-name like apply_hierarchy — else a
        valid linked child silently vanishes from the dialog.
        """
        client = JiraClient(_make_auth(tmp_path))
        client._jira = MagicMock()
        chain = [
            HierarchyNode(issue_type_id="E", issue_type="Epic", display_tier=0),
            HierarchyNode(issue_type_id="S", issue_type="Story", display_tier=1),
            HierarchyNode(
                issue_type_id="K",
                issue_type="Task",
                edge="link",
                link_types=[],  # "any" link type
                display_tier=2,
            ),
        ]
        story = _make_raw_issue(
            "STORY-1", "A story", type_name="Story", type_id="S",
            links=[_link("Blocks", "TASK-1")],
        )
        # The linked Task's id (K2) ≠ the chain node's id (K); only the name matches.
        task = _make_raw_issue("TASK-1", "A task", type_name="Task", type_id="K2")
        client._jira.search_issues.side_effect = [[story], [task], [task]]

        out = client.fetch_child_summaries("STORY-1", chain=chain, parent_tier=1)
        assert out == [("TASK-1", "A task")]


class TestApplyHierarchy:
    def test_cascade_and_tier_assignment(self) -> None:
        epic = EpicData(
            key="CAP-1", summary="", status="", priority=None, assignee=None,
            reporter=None, created=None, updated=None,
        )
        feat = JiraIssue(
            key="FEAT-1", summary="", status="", status_category="To Do",
            resolution=None, issue_type="Feature", story_points=None,
            created=None, resolved=None, assignee=None, issue_type_id="F",
            hierarchy_parent_key="CAP-1",
        )
        story = JiraIssue(
            key="STORY-1", summary="", status="", status_category="To Do",
            resolution=None, issue_type="Story", story_points=None,
            created=None, resolved=None, assignee=None, issue_type_id="S",
            hierarchy_parent_key="FEAT-1",
        )
        epic.children = [feat, story]
        JiraClient.apply_hierarchy(epic, _cap_feat_story_chain(feature_estimate=False))
        assert feat.display_tier == 1 and story.display_tier == 2
        # Feature not estimated → its descendant Story drops out of estimate too.
        assert feat.in_estimate is False
        assert story.in_estimate is False

    def test_show_cascades_from_hidden_parent(self) -> None:
        """A Sub-task whose specific tier-1 parent (Bug) is hidden is hidden too
        — show AND-cascades up the actual parent ancestry."""
        epic = EpicData(
            key="EP-1", summary="", status="", priority=None, assignee=None,
            reporter=None, created=None, updated=None,
        )
        bug = JiraIssue(
            key="B-1", summary="", status="", status_category="To Do",
            resolution=None, issue_type="Bug", story_points=None, created=None,
            resolved=None, assignee=None, issue_type_id="BUG",
            hierarchy_parent_key="EP-1",
        )
        sub = JiraIssue(
            key="ST-1", summary="", status="", status_category="To Do",
            resolution=None, issue_type="Sub-task", story_points=None, created=None,
            resolved=None, assignee=None, issue_type_id="SUB",
            hierarchy_parent_key="B-1",
        )
        epic.children = [bug, sub]
        chain = [
            HierarchyNode("E", "Epic", display_tier=0),
            HierarchyNode("BUG", "Bug", edge="parent", display_tier=1, show=False),
            HierarchyNode("SUB", "Sub-task", edge="parent", display_tier=2, show=True),
        ]
        JiraClient.apply_hierarchy(epic, chain)
        by = {c.key: c for c in epic.children}
        assert by["B-1"].show is False  # Bug hidden by its own node
        assert by["ST-1"].show is False  # Sub-task hidden too: its Bug parent is hidden


class TestDefaultPathSubtaskFromChain:
    """The non-custom (migrated) chain drives the default-path subtask fetch."""

    def _epic_and_child(self) -> tuple[SimpleNamespace, SimpleNamespace, SimpleNamespace]:
        epic = _make_raw_issue("PROJ-1", "Epic", type_name="Epic", type_id="E")
        child = _make_raw_issue(
            "PROJ-2", "Story", sp=3.0, epic_link="PROJ-1", type_id="S"
        )
        sub = _make_raw_issue("PROJ-3", "Sub", sp=1.0, parent="PROJ-2", type_id="SUB")
        return epic, child, sub

    def _default_chain(self, *, sub_estimate: bool, sub_show: bool) -> list[HierarchyNode]:
        return [
            HierarchyNode("E", "Epic", display_tier=0),
            HierarchyNode("S", "Story", edge="parent", display_tier=1),
            HierarchyNode(
                "SUB", "Sub-task", edge="parent", display_tier=2,
                show=sub_show, in_estimate=sub_estimate,
            ),
        ]

    def test_subtasks_fetched_when_tier2_estimated(self, tmp_path: Path) -> None:
        client = JiraClient(_make_auth(tmp_path))
        client._jira = MagicMock()
        epic, child, sub = self._epic_and_child()
        client._jira.search_issues.side_effect = [[epic, child], [sub]]
        result = client.fetch_epic(
            "PROJ-1", chain=self._default_chain(sub_estimate=True, sub_show=False)
        )
        assert result is not None
        assert {c.key for c in result.children} == {"PROJ-2", "PROJ-3"}
        assert client._jira.search_issues.call_count == 2  # combined + subtasks

    def test_subtasks_skipped_when_tier2_off(self, tmp_path: Path) -> None:
        client = JiraClient(_make_auth(tmp_path))
        client._jira = MagicMock()
        epic, child, _sub = self._epic_and_child()
        client._jira.search_issues.side_effect = [[epic, child]]
        result = client.fetch_epic(
            "PROJ-1", chain=self._default_chain(sub_estimate=False, sub_show=False)
        )
        assert result is not None
        assert {c.key for c in result.children} == {"PROJ-2"}
        assert client._jira.search_issues.call_count == 1  # no subtask query

    def test_subtask_estimate_cascades_from_story(self, tmp_path: Path) -> None:
        """Story not estimated → sub-tasks excluded too (fast-path AND cascade).

        The editor greys but doesn't uncheck a child estimate toggle, so a
        user-built chain can persist Story in_estimate=False with Sub-task
        in_estimate=True.  The fast path must AND-resolve the cascade (matching
        apply_hierarchy) and skip the sub-task fetch entirely.
        """
        client = JiraClient(_make_auth(tmp_path))
        client._jira = MagicMock()
        epic, child, _sub = self._epic_and_child()
        client._jira.search_issues.side_effect = [[epic, child]]
        chain = [
            HierarchyNode("E", "Epic", display_tier=0),
            HierarchyNode("S", "Story", edge="parent", display_tier=1, in_estimate=False),
            HierarchyNode(
                "SUB", "Sub-task", edge="parent", display_tier=2,
                show=False, in_estimate=True,
            ),
        ]
        result = client.fetch_epic("PROJ-1", chain=chain)
        assert result is not None
        assert {c.key for c in result.children} == {"PROJ-2"}
        assert client._jira.search_issues.call_count == 1  # cascade dropped sub fetch

    def test_children_carry_issue_type_id(self, tmp_path: Path) -> None:
        """Fast-path children carry issue_type_id so the view-model can icon them."""
        client = JiraClient(_make_auth(tmp_path))
        client._jira = MagicMock()
        epic, child, sub = self._epic_and_child()
        client._jira.search_issues.side_effect = [[epic, child], [sub]]
        result = client.fetch_epic(
            "PROJ-1", chain=self._default_chain(sub_estimate=True, sub_show=True)
        )
        assert result is not None
        by_key = {c.key: c for c in result.children}
        assert by_key["PROJ-2"].issue_type_id == "S"
        assert by_key["PROJ-3"].issue_type_id == "SUB"

    def _chain_story_show(self, show: bool) -> list[HierarchyNode]:
        return [
            HierarchyNode("E", "Epic", display_tier=0),
            HierarchyNode("S", "Story", edge="parent", display_tier=1, show=show),
            HierarchyNode(
                "SUB", "Sub-task", edge="parent", display_tier=2,
                show=False, in_estimate=False,
            ),
        ]

    def test_tier1_story_show_applied_to_direct_children(self, tmp_path: Path) -> None:
        """A migrated chain's Story tier-1 ``show`` lands on fast-path children.

        Regression: the fast path only mirrored the Sub-task tier onto subtasks,
        leaving direct children at the JiraIssue default ``show=True`` — so a
        migrated profile with ``show_epic_stories_on_timeline=False`` still
        rendered story bars and nested summary rows.
        """
        client = JiraClient(_make_auth(tmp_path))
        client._jira = MagicMock()
        epic, child, _sub = self._epic_and_child()
        client._jira.search_issues.side_effect = [[epic, child]]
        result = client.fetch_epic("PROJ-1", chain=self._chain_story_show(False))
        assert result is not None
        story = next(c for c in result.children if c.key == "PROJ-2")
        assert story.display_tier == 1
        assert story.show is False
        assert story.in_estimate is True  # Story tier always estimates

    def test_tier1_story_shown_when_node_shown(self, tmp_path: Path) -> None:
        client = JiraClient(_make_auth(tmp_path))
        client._jira = MagicMock()
        epic, child, _sub = self._epic_and_child()
        client._jira.search_issues.side_effect = [[epic, child]]
        result = client.fetch_epic("PROJ-1", chain=self._chain_story_show(True))
        assert result is not None
        story = next(c for c in result.children if c.key == "PROJ-2")
        assert story.show is True


class TestFetchIssueTypeIds:
    """Batched key→issue-type-id lookup that drives report-item row icons."""

    def test_maps_keys_to_type_ids(self, tmp_path: Path) -> None:
        client = JiraClient(_make_auth(tmp_path))
        client._jira = MagicMock()
        rows = [
            _make_raw_issue("HHP-1", type_id="10000"),
            _make_raw_issue("HHP-2", type_id="10001"),
        ]
        with patch.object(client, "_search_with_retry", return_value=rows) as m:
            out = client.fetch_issue_type_ids(["HHP-1", "HHP-2", "HHP-1"])
        assert out == {"HHP-1": "10000", "HHP-2": "10001"}
        assert "key in (" in m.call_args[0][0]  # one batched JQL

    def test_meta_returns_type_id_name_and_summary(self, tmp_path: Path) -> None:
        client = JiraClient(_make_auth(tmp_path))
        client._jira = MagicMock()
        rows = [
            _make_raw_issue("HHP-1", "Alpha test", type_name="Task", type_id="10000")
        ]
        with patch.object(client, "_search_with_retry", return_value=rows):
            assert client.fetch_issue_meta(["HHP-1"]) == {
                "HHP-1": ("10000", "Task", "Alpha test")
            }

    def test_empty_keys(self, tmp_path: Path) -> None:
        client = JiraClient(_make_auth(tmp_path))
        client._jira = MagicMock()
        assert client.fetch_issue_type_ids([]) == {}
        assert client.fetch_issue_meta([]) == {}

    def test_disconnected(self, tmp_path: Path) -> None:
        client = JiraClient(_make_auth(tmp_path))  # _jira is None
        assert client.fetch_issue_type_ids(["X-1"]) == {}
