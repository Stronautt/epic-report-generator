"""Jira Cloud API client using the ``jira`` library."""

from __future__ import annotations

import logging
import time
from datetime import date, datetime
from typing import Any

import requests as _requests
from dateutil.parser import parse as _dt_parse
from jira import JIRA, JIRAError

from epic_report_generator.core.data_models import (
    EpicData,
    JiraIssue,
    SprintInfo,
    collect_child_timeline_dates,
)
from epic_report_generator.services.auth_manager import AuthManager

logger = logging.getLogger(__name__)

_MAX_RESULTS = 100
_MAX_RETRIES = 4
_BACKOFF_BASE = 1.0  # seconds
# Maximum number of keys in a single JQL IN clause for subtask batching.
# JQL supports much larger IN clauses than the pagination page size.
_JQL_IN_BATCH_SIZE = 500


def _drop_subtasks(children: list[JiraIssue]) -> list[JiraIssue]:
    """Return a copy of *children* with is_subtask=True items removed."""
    return [c for c in children if not c.is_subtask]


class JiraClient:
    """High-level wrapper around the ``jira`` library for Epic data."""

    # TTL for cached Jira field metadata (seconds)
    _FIELDS_CACHE_TTL = 3600  # 1 hour

    def __init__(self, auth: AuthManager) -> None:
        self._auth = auth
        self._jira: JIRA | None = None
        self._fields_cache: list[dict[str, str]] | None = None
        self._fields_cache_time: float = 0.0

    def invalidate_caches(self) -> None:
        """Clear all cached data (e.g. field metadata)."""
        self._fields_cache = None
        self._fields_cache_time = 0.0
        logger.info("Jira client caches invalidated")

    # -- connection -----------------------------------------------------------

    def connect(self) -> bool:
        """Establish (or re-establish) the OAuth Jira connection.

        Returns True on success.
        """
        token = self._auth.get_access_token()
        if not token or not self._auth.cloud_id:
            logger.warning("Cannot connect — missing access token or cloud_id")
            return False
        server = f"https://api.atlassian.com/ex/jira/{self._auth.cloud_id}"
        logger.debug("Connecting to Jira at %s", server)
        try:
            self._jira = JIRA(
                server=server,
                options={"headers": {"Authorization": f"Bearer {token}"}},
            )
            logger.info("Connected to Jira (cloud_id=%s)", self._auth.cloud_id)
            return True
        except Exception as exc:
            logger.error("Failed to connect to Jira: %s", exc)
            return False

    def connect_basic(self, url: str, email: str, token: str) -> bool:
        """Connect to Jira using an API token.

        Tries basic auth against the instance URL first (classic unscoped
        tokens).  If that returns 401, resolves the site's ``cloudId`` and
        retries against ``https://api.atlassian.com/ex/jira/{cloudId}``
        which is required for scoped API keys.

        A lightweight ``myself()`` call validates each attempt.
        Returns True on success.
        """
        # 1) Classic token — basic auth against instance URL
        logger.debug("Connecting to Jira at %s (basic auth)", url)
        try:
            jira = JIRA(server=url, basic_auth=(email, token))
            jira.myself()
            self._jira = jira
            logger.info("Connected to Jira via basic auth (%s)", url)
            return True
        except JIRAError as exc:
            if exc.status_code == 401:
                logger.debug(
                    "Basic auth returned 401, trying scoped token via cloud API"
                )
            else:
                logger.error("Failed to connect to Jira: %s", exc)
                self._jira = None
                return False
        except Exception as exc:
            logger.error("Failed to connect to Jira: %s", exc)
            self._jira = None
            return False

        # 2) Scoped API key — resolve cloudId and use cloud API URL
        cloud_id = self._auth.cloud_id or self._resolve_cloud_id(url)
        if not cloud_id:
            logger.error("Could not resolve cloudId for %s", url)
            self._jira = None
            return False

        cloud_url = f"https://api.atlassian.com/ex/jira/{cloud_id}"
        logger.debug("Retrying with cloud API URL %s", cloud_url)
        try:
            jira = JIRA(server=cloud_url, basic_auth=(email, token))
            jira.myself()
            self._jira = jira
            # Cache cloud_id so subsequent reconnects skip the lookup
            if not self._auth.cloud_id:
                self._auth.set_cloud_id(cloud_id)
            logger.info("Connected to Jira via scoped API key (cloud_id=%s)", cloud_id)
            return True
        except Exception as exc:
            logger.error("Failed to connect to Jira (scoped token): %s", exc)
            self._jira = None
            return False

    @staticmethod
    def _resolve_cloud_id(instance_url: str) -> str | None:
        """Fetch the cloudId from the instance's ``_edge/tenant_info`` endpoint."""
        tenant_url = f"{instance_url.rstrip('/')}/_edge/tenant_info"
        logger.debug("Resolving cloudId from %s", tenant_url)
        try:
            resp = _requests.get(tenant_url, timeout=10)
            resp.raise_for_status()
            cloud_id = resp.json().get("cloudId", "")
            if cloud_id:
                logger.info("Resolved cloudId=%s from %s", cloud_id, instance_url)
            return cloud_id or None
        except Exception as exc:
            logger.warning("Failed to resolve cloudId from %s: %s", tenant_url, exc)
            return None

    def connect_from_config(self) -> bool:
        """Connect using whichever auth method is configured.

        Reads ``auth_method`` from the :class:`AuthManager` and dispatches
        to the appropriate connection path.
        """
        method = self._auth.auth_method
        if method == "api_token":
            api_token = self._auth.get_api_token()
            if not api_token:
                logger.warning("Cannot connect — no API token in keyring")
                return False
            return self.connect_basic(
                self._auth.jira_url,
                self._auth.jira_email,
                api_token,
            )
        if method == "oauth":
            return self.connect()
        logger.debug("No auth_method configured — skipping auto-connect")
        return False

    @property
    def connected(self) -> bool:
        """Return True when the Jira session is active."""
        return self._jira is not None

    # -- user info ------------------------------------------------------------

    def get_myself(self) -> dict[str, str] | None:
        """Fetch the authenticated user's display name and avatar URL."""
        if not self._jira:
            return None
        try:
            me = self._jira.myself()
            name = me.get("displayName", "")
            logger.info("Authenticated as %s", name)
            return {
                "displayName": name,
                "avatarUrl": me.get("avatarUrls", {}).get("48x48", ""),
                "emailAddress": me.get("emailAddress", ""),
            }
        except JIRAError as exc:
            logger.error("myself() failed: %s", exc)
            return None

    # -- epic fetching --------------------------------------------------------

    def fetch_epic(
        self,
        epic_key: str,
        sp_field: str = "story_points",
        epic_link_field: str = "customfield_10014",
        start_date_field: str = "startdate",
        due_date_field: str = "duedate",
        include_subtasks: bool = True,
        include_subtasks_in_timeline: bool = True,
        sprint_field: str = "customfield_10020",
        timeline_start_field: str = "",
        timeline_end_field: str = "",
    ) -> EpicData | None:
        """Fetch a single Epic and all its child issues.

        Returns ``None`` if the Epic cannot be found.
        """
        if not self._jira:
            return None

        logger.debug(
            "Fetching epic %s (date_fields=%s/%s, timeline_fields=%s/%s)",
            epic_key,
            start_date_field,
            due_date_field,
            timeline_start_field or start_date_field,
            timeline_end_field or due_date_field,
        )
        try:
            issue = self._search_with_retry(f"key = {epic_key}", max_results=1)
            if not issue:
                logger.warning("Epic %s not found", epic_key)
                return None
            raw = issue[0]
        except JIRAError as exc:
            logger.error("Failed to fetch epic %s: %s", epic_key, exc)
            return None

        epic = self._parse_epic_from_raw(
            raw,
            start_date_field,
            due_date_field,
            timeline_start_field,
            timeline_end_field,
        )

        # Fetch children with pagination
        epic.children = self._fetch_children(
            epic_key,
            sp_field,
            epic_link_field,
            start_date_field,
            due_date_field,
            include_subtasks=include_subtasks,
            include_subtasks_in_timeline=include_subtasks_in_timeline,
            sprint_field=sprint_field,
            timeline_start_field=timeline_start_field,
            timeline_end_field=timeline_end_field,
        )

        # Expand epic dates to cover the full range of children
        self._fill_epic_dates_from_children(
            epic, include_subtask_timeline=include_subtasks_in_timeline
        )

        # If subtasks were fetched only for timeline but not for progress,
        # remove them so calculate_metrics treats their parents as leaf nodes.
        if not include_subtasks and include_subtasks_in_timeline:
            epic.children = _drop_subtasks(epic.children)

        logger.info(
            "Fetched epic %s: %d children, status=%s",
            epic_key,
            len(epic.children),
            epic.status,
        )
        return epic

    def validate_epic_key(self, epic_key: str) -> bool:
        """Return True if the Epic key exists in Jira."""
        if not self._jira:
            return False
        logger.debug("Validating epic key %s", epic_key)
        try:
            results = self._search_with_retry(f"key = {epic_key}", max_results=1)
            valid = bool(results)
            logger.debug("Epic key %s valid=%s", epic_key, valid)
            return valid
        except JIRAError:
            logger.debug("Epic key %s validation failed", epic_key)
            return False

    def fetch_fields(self) -> list[dict[str, str]]:
        """Return all Jira fields (for custom field mapping UI).

        Results are cached for up to 1 hour to avoid redundant API calls
        when the field picker dialog is reopened.
        """
        if not self._jira:
            return []
        if (
            self._fields_cache is not None
            and (time.monotonic() - self._fields_cache_time) < self._FIELDS_CACHE_TTL
        ):
            logger.debug("Returning %d cached Jira fields", len(self._fields_cache))
            return self._fields_cache
        logger.debug("Fetching Jira fields")
        try:
            result = [
                {"id": f["id"], "name": f["name"], "custom": f.get("custom", False)}
                for f in self._jira.fields()
            ]
            logger.info("Fetched %d Jira fields", len(result))
            self._fields_cache = result
            self._fields_cache_time = time.monotonic()
            return result
        except JIRAError as exc:
            logger.error("Failed to fetch fields: %s", exc)
            return []

    def get_project_name(self, project_key: str) -> str | None:
        """Return the display name of a Jira project."""
        if not self._jira:
            return None
        logger.debug("Looking up project name for %s", project_key)
        try:
            proj = self._jira.project(project_key)
            logger.debug("Project %s → %s", project_key, proj.name)
            return proj.name
        except JIRAError:
            logger.warning("Could not resolve project name for %s", project_key)
            return None

    # -- label / version fetching ------------------------------------------------

    def fetch_epics_by_label(
        self,
        label: str,
        sp_field: str = "story_points",
        epic_link_field: str = "customfield_10014",
        start_date_field: str = "startdate",
        due_date_field: str = "duedate",
        include_subtasks: bool = True,
        include_subtasks_in_timeline: bool = True,
        sprint_field: str = "customfield_10020",
        timeline_start_field: str = "",
        timeline_end_field: str = "",
    ) -> list[EpicData]:
        """Fetch all Epics with the given label, including their children.

        Returns an empty list if the client is not connected or no epics match.
        """
        if not self._jira:
            return []

        jql = f'issuetype = Epic AND labels = "{label}" ORDER BY key ASC'
        logger.info("Fetching epics by label %r", label)
        epics: list[EpicData] = []
        start = 0

        while True:
            results = self._search_with_retry(
                jql, start_at=start, max_results=_MAX_RESULTS
            )
            if not results:
                break
            for raw in results:
                epic = self._parse_epic_from_raw(
                    raw,
                    start_date_field,
                    due_date_field,
                    timeline_start_field,
                    timeline_end_field,
                )

                epic.children = self._fetch_children(
                    epic.key,
                    sp_field,
                    epic_link_field,
                    start_date_field,
                    due_date_field,
                    include_subtasks=include_subtasks,
                    include_subtasks_in_timeline=include_subtasks_in_timeline,
                    sprint_field=sprint_field,
                    timeline_start_field=timeline_start_field,
                    timeline_end_field=timeline_end_field,
                )

                # Expand epic dates to cover the full range of children
                self._fill_epic_dates_from_children(
                    epic, include_subtask_timeline=include_subtasks_in_timeline
                )

                # If subtasks fetched only for timeline, remove for progress
                if not include_subtasks and include_subtasks_in_timeline:
                    epic.children = _drop_subtasks(epic.children)

                epics.append(epic)
            if len(results) < _MAX_RESULTS:
                break
            start += _MAX_RESULTS

        logger.info("Found %d epic(s) with label %r", len(epics), label)
        return epics

    def fetch_fix_version_dates(self, project_key: str) -> dict[str, date | None]:
        """Fetch release dates for all fix versions in a project.

        Returns a dict mapping version name to release date (or None).
        """
        if not self._jira:
            return {}

        logger.debug("Fetching fix version dates for project %s", project_key)
        try:
            versions = self._jira.project_versions(project_key)
            result: dict[str, date | None] = {}
            for v in versions:
                name = getattr(v, "name", "")
                raw_date = getattr(v, "releaseDate", None)
                result[name] = self._parse_date(raw_date)
            logger.info(
                "Fetched %d version(s) for project %s", len(result), project_key
            )
            return result
        except JIRAError as exc:
            logger.warning("Failed to fetch versions for %s: %s", project_key, exc)
            return {}

    def fetch_labels(self) -> list[str]:
        """Fetch available labels from the Jira instance.

        Uses the ``/rest/api/3/label`` suggestion endpoint and falls back
        to collecting labels from a JQL search.
        """
        if not self._jira:
            return []

        logger.debug("Fetching labels")

        # Try the REST label endpoint first (Jira Cloud)
        try:
            url = f"{self._jira.server_url}/rest/api/3/label"
            session = self._jira._session
            if session is None:
                raise RuntimeError("No active Jira session")
            resp = session.get(url, params={"maxResults": 1000})
            if resp.status_code == 200:
                data = resp.json()
                labels = data.get("values", [])
                if labels:
                    logger.info("Fetched %d label(s) via REST endpoint", len(labels))
                    return sorted(labels)
        except Exception as exc:
            logger.debug("REST label endpoint failed: %s", exc)

        # Fallback: collect labels from recent issues
        try:
            results = self._search_with_retry(
                "labels is not EMPTY ORDER BY updated DESC",
                max_results=50,
            )
            label_set: set[str] = set()
            for raw in results:
                for lbl in getattr(raw.fields, "labels", []) or []:
                    label_set.add(lbl)
            logger.info("Collected %d label(s) from JQL fallback", len(label_set))
            return sorted(label_set)
        except Exception as exc:
            logger.warning("Failed to fetch labels: %s", exc)
            return []

    @staticmethod
    def _fill_epic_dates_from_children(
        epic: EpicData,
        *,
        include_subtask_timeline: bool = True,
    ) -> None:
        """Expand epic-level dates to cover the full range of child issues.

        The epic's start_date becomes the earliest date and due_date the
        latest date across the epic's own dates and all children.  For each
        child, prefer start_date/due_date but fall back to created/resolved
        so that every child contributes to the range.

        Timeline dates (timeline_start / timeline_end) are computed with a
        cascade: timeline field values → sprint dates → start_date/due_date.
        This matches Jira Cloud Timeline behaviour, which derives epic ranges
        from child sprint assignments when no explicit dates are set.

        When *include_subtask_timeline* is False, children marked as subtasks
        are excluded from the timeline date collection (estimation dates still
        include all children).

        All four date categories are collected in a single pass over children.
        """
        if not epic.children:
            return

        candidate_starts: list[date] = []
        candidate_ends: list[date] = []
        tl_starts: list[date] = []
        tl_ends: list[date] = []

        if epic.start_date:
            candidate_starts.append(epic.start_date)
        if epic.due_date:
            candidate_ends.append(epic.due_date)
        if epic.timeline_start:
            tl_starts.append(epic.timeline_start)
        if epic.timeline_end:
            tl_ends.append(epic.timeline_end)

        for c in epic.children:
            # Estimation start
            if c.start_date:
                candidate_starts.append(c.start_date)
            elif c.created:
                candidate_starts.append(c.created.date())

            # Estimation end
            if c.due_date:
                candidate_ends.append(c.due_date)
            elif c.resolved and c.status_category == "Done":
                candidate_ends.append(c.resolved.date())

            # Skip subtasks for timeline dates when not included
            if c.is_subtask and not include_subtask_timeline:
                continue

            collect_child_timeline_dates(c, tl_starts, tl_ends)

        if candidate_starts:
            epic.start_date = min(candidate_starts)
        if candidate_ends:
            epic.due_date = max(candidate_ends)
        elif epic.start_date:
            epic.due_date = date.today()
        if tl_starts:
            epic.timeline_start = min(tl_starts)
        if tl_ends:
            epic.timeline_end = max(tl_ends)

    # -- internals ------------------------------------------------------------

    def _parse_epic_from_raw(
        self,
        raw: Any,
        start_date_field: str,
        due_date_field: str,
        timeline_start_field: str,
        timeline_end_field: str,
    ) -> EpicData:
        """Parse a raw Jira issue into an :class:`EpicData` with date fields."""
        fields: Any = raw.fields
        epic = EpicData(
            key=raw.key,
            summary=getattr(fields, "summary", ""),
            status=str(getattr(fields, "status", "")),
            priority=str(getattr(fields, "priority", "")) or None,
            assignee=self._name(getattr(fields, "assignee", None)),
            reporter=self._name(getattr(fields, "reporter", None)),
            created=self._parse_dt(getattr(fields, "created", None)),
            updated=self._parse_dt(getattr(fields, "updated", None)),
            labels=getattr(fields, "labels", []) or [],
            fix_versions=[v.name for v in (getattr(fields, "fixVersions", []) or [])],
        )

        tl_start_attr = timeline_start_field or start_date_field
        tl_end_attr = timeline_end_field or due_date_field

        epic.start_date = self._parse_date(self._get_raw_field(raw, start_date_field))
        epic.due_date = self._parse_date(self._get_raw_field(raw, due_date_field))
        epic.timeline_start = self._parse_date(self._get_raw_field(raw, tl_start_attr))
        epic.timeline_end = self._parse_date(self._get_raw_field(raw, tl_end_attr))
        logger.debug(
            "Epic %s dates: estimation=%s/%s, timeline(%s/%s)=%s/%s",
            epic.key,
            epic.start_date,
            epic.due_date,
            tl_start_attr,
            tl_end_attr,
            epic.timeline_start,
            epic.timeline_end,
        )
        return epic

    def _paginated_search(
        self,
        jql: str,
        sp_field: str,
        start_date_field: str,
        due_date_field: str,
        sprint_field: str,
        timeline_start_field: str,
        timeline_end_field: str,
        seen: set[str],
        children: list[JiraIssue],
    ) -> None:
        """Run a paginated JQL search and append deduplicated child issues."""
        start = 0
        while True:
            results = self._search_with_retry(
                jql, start_at=start, max_results=_MAX_RESULTS
            )
            if not results:
                break
            for raw in results:
                issue = self._parse_child_issue(
                    raw,
                    sp_field,
                    start_date_field,
                    due_date_field,
                    sprint_field,
                    timeline_start_field,
                    timeline_end_field,
                )
                if issue.key not in seen:
                    seen.add(issue.key)
                    children.append(issue)
            if len(results) < _MAX_RESULTS:
                break
            start += _MAX_RESULTS

    def _fetch_children(
        self,
        epic_key: str,
        sp_field: str,
        epic_link_field: str,
        start_date_field: str = "startdate",
        due_date_field: str = "duedate",
        include_subtasks: bool = True,
        include_subtasks_in_timeline: bool = True,
        sprint_field: str = "customfield_10020",
        timeline_start_field: str = "",
        timeline_end_field: str = "",
    ) -> list[JiraIssue]:
        children: list[JiraIssue] = []
        seen: set[str] = set()

        # 1) Issues linked via the Epic Link custom field (Stories, Bugs, etc.)
        jql = f'"{epic_link_field}" = {epic_key} ORDER BY created ASC'
        logger.debug("Fetching children for %s (field=%s)", epic_key, epic_link_field)
        self._paginated_search(
            jql,
            sp_field,
            start_date_field,
            due_date_field,
            sprint_field,
            timeline_start_field,
            timeline_end_field,
            seen,
            children,
        )

        # 2) Issues linked via the parent hierarchy (Tasks, Defects, etc.)
        #    In Jira Cloud, these may not have the Epic Link field set.
        parent_jql = f"parent = {epic_key} ORDER BY created ASC"
        logger.debug("Fetching parent-linked children for %s", epic_key)
        self._paginated_search(
            parent_jql,
            sp_field,
            start_date_field,
            due_date_field,
            sprint_field,
            timeline_start_field,
            timeline_end_field,
            seen,
            children,
        )

        # Fetch subtasks of direct children when needed for progress or timeline
        need_subtasks = include_subtasks or include_subtasks_in_timeline
        if need_subtasks and children:
            direct_child_count = len(children)
            child_keys = [c.key for c in children]
            for batch_start in range(0, len(child_keys), _JQL_IN_BATCH_SIZE):
                batch = child_keys[batch_start : batch_start + _JQL_IN_BATCH_SIZE]
                subtask_jql = f"parent in ({', '.join(batch)}) ORDER BY created ASC"
                logger.debug("Fetching subtasks for %d parent(s)", len(batch))
                self._paginated_search(
                    subtask_jql,
                    sp_field,
                    start_date_field,
                    due_date_field,
                    sprint_field,
                    timeline_start_field,
                    timeline_end_field,
                    seen,
                    children,
                )
            # Mark newly added issues as subtasks
            for c in children[direct_child_count:]:
                c.is_subtask = True
            logger.debug(
                "Total children + subtasks for %s: %d", epic_key, len(children)
            )

        return children

    def _parse_child_issue(
        self,
        raw: Any,
        sp_field: str,
        start_date_field: str,
        due_date_field: str,
        sprint_field: str = "customfield_10020",
        timeline_start_field: str = "",
        timeline_end_field: str = "",
    ) -> JiraIssue:
        """Parse a raw Jira issue into a :class:`JiraIssue`."""
        fields: Any = raw.fields
        sp_val = self._get_raw_field(raw, sp_field)
        if sp_val is None:
            # Fallback: customfield_10016 is the default SP field
            # in Jira Cloud
            sp_val = self._get_raw_field(raw, "customfield_10016")

        raw_sprints = self._get_raw_field(raw, sprint_field)

        # Extract parent key (for subtask → parent relationship)
        parent_obj = getattr(fields, "parent", None)
        parent_key: str | None = None
        if parent_obj is not None:
            parent_key = getattr(parent_obj, "key", None)
            if parent_key is None and isinstance(parent_obj, dict):
                parent_key = parent_obj.get("key")

        issue = JiraIssue(
            key=raw.key,
            summary=getattr(fields, "summary", ""),
            status=str(getattr(fields, "status", "")),
            status_category=self._status_category(fields),
            resolution=str(getattr(fields, "resolution", "")) or None,
            issue_type=str(getattr(fields, "issuetype", "")),
            story_points=float(sp_val) if sp_val is not None else None,
            created=self._parse_dt(getattr(fields, "created", None)),
            resolved=self._parse_dt(getattr(fields, "resolutiondate", None)),
            assignee=self._name(getattr(fields, "assignee", None)),
            parent_key=parent_key,
            start_date=self._parse_date(self._get_raw_field(raw, start_date_field)),
            due_date=self._parse_date(self._get_raw_field(raw, due_date_field)),
            sprints=self._parse_sprints(raw_sprints),
        )

        # Timeline dates: always read from the configured timeline fields
        tl_start_attr = timeline_start_field or start_date_field
        tl_end_attr = timeline_end_field or due_date_field
        issue.timeline_start = self._parse_date(self._get_raw_field(raw, tl_start_attr))
        issue.timeline_end = self._parse_date(self._get_raw_field(raw, tl_end_attr))

        return issue

    def _search_with_retry(
        self, jql: str, *, start_at: int = 0, max_results: int = _MAX_RESULTS
    ) -> list[Any]:
        """Execute a JQL search with exponential backoff on 429."""
        assert self._jira is not None, "call connect() first"
        for attempt in range(_MAX_RETRIES):
            try:
                return self._jira.search_issues(
                    jql, startAt=start_at, maxResults=max_results
                )
            except JIRAError as exc:
                if exc.status_code == 429 and attempt < _MAX_RETRIES - 1:
                    delay = _BACKOFF_BASE * (2**attempt)
                    logger.warning("Rate limited, retrying in %.1fs", delay)
                    time.sleep(delay)
                    continue
                raise

        return []  # unreachable, but satisfies type checker

    @staticmethod
    def _status_category(fields: Any) -> str:
        status = getattr(fields, "status", None)
        if status is None:
            return "To Do"
        cat = getattr(status, "statusCategory", None)
        if cat is None:
            return "To Do"
        name = getattr(cat, "name", None)
        return str(name) if name else "To Do"

    @staticmethod
    def _name(obj: Any) -> str | None:
        if obj is None:
            return None
        if isinstance(obj, str):
            return obj
        return getattr(obj, "displayName", None) or str(obj)

    @staticmethod
    def _parse_dt(value: Any) -> datetime | None:
        if value is None:
            return None
        try:
            return _dt_parse(str(value))
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _parse_sprints(raw_sprints: Any) -> list[SprintInfo]:
        """Parse the sprint custom field into a list of :class:`SprintInfo`.

        The sprint field value can be a list of dicts (REST API v3), a list of
        objects with attributes, or ``None``.
        """
        if not raw_sprints:
            return []
        if not isinstance(raw_sprints, (list, tuple)):
            raw_sprints = [raw_sprints]

        result: list[SprintInfo] = []
        for entry in raw_sprints:
            try:
                if isinstance(entry, dict):
                    name = entry.get("name", "")
                    start = entry.get("startDate")
                    end = entry.get("endDate")
                    state = entry.get("state", "")
                else:
                    name = getattr(entry, "name", "")
                    start = getattr(entry, "startDate", None)
                    end = getattr(entry, "endDate", None)
                    state = getattr(entry, "state", "")

                start_d = None
                if start:
                    try:
                        start_d = date.fromisoformat(str(start)[:10])
                    except (ValueError, TypeError):
                        pass
                end_d = None
                if end:
                    try:
                        end_d = date.fromisoformat(str(end)[:10])
                    except (ValueError, TypeError):
                        pass

                if name:
                    result.append(
                        SprintInfo(
                            name=str(name),
                            start_date=start_d,
                            end_date=end_d,
                            state=str(state),
                        )
                    )
            except Exception:
                continue
        return result

    @staticmethod
    def _get_raw_field(raw_issue: Any, field_name: str) -> Any:
        """Read a field value from the raw API response dict.

        The ``jira`` library wraps fields in a ``PropertyHolder`` which may
        silently drop custom fields.  Accessing ``raw_issue.raw['fields']``
        directly is more reliable for custom and date fields.
        """
        raw = getattr(raw_issue, "raw", None)
        if raw and isinstance(raw, dict):
            value = raw.get("fields", {}).get(field_name)
            if value is not None:
                return value
        # Fallback to PropertyHolder
        fields = getattr(raw_issue, "fields", None)
        return getattr(fields, field_name, None) if fields else None

    @staticmethod
    def _parse_date(value: Any) -> date | None:
        """Parse a Jira date string (``YYYY-MM-DD``) into a :class:`date`."""
        if value is None:
            return None
        if isinstance(value, date):
            return value
        try:
            return date.fromisoformat(str(value)[:10])
        except (ValueError, TypeError):
            return None
