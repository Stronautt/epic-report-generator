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
    STATUS_TODO,
    EpicData,
    JiraIssue,
    SprintInfo,
    collect_child_estimation_dates,
    collect_child_timeline_dates,
)
from epic_report_generator.services.auth_manager import AuthManager

logger = logging.getLogger(__name__)

_MAX_RESULTS = 100
_BACKOFF_BASE = 1.0  # seconds — exponential backoff base for 429 rate-limit retries
# Progressive per-attempt request timeouts for searches: fail fast on a stale /
# idle-reaped keep-alive socket (1s), then grant a genuinely slow server more
# headroom on retry (3s, 5s). Each value is a scalar applied to both connect and
# read. The tuple length is also the number of search attempts.
_PROGRESSIVE_TIMEOUTS = (1, 3, 5)  # seconds
_TRANSPORT_RETRY_DELAY = 0.25  # seconds — short pause before a fresh-socket retry
# Baseline timeout for one-shot, non-search calls (myself / fields / project /
# the raw label endpoint). Searches override this per attempt (see
# ``_search_with_retry``); everything else inherits this ceiling.
_DEFAULT_TIMEOUT = _PROGRESSIVE_TIMEOUTS[-1]
# Maximum number of keys in a single JQL IN clause for subtask batching.
# JQL supports much larger IN clauses than the pagination page size.
_JQL_IN_BATCH_SIZE = 500
# The combined epics+children query repeats the key list three times
# (key in / epic_link in / parent in), so keep each batch small enough that
# 3× the list stays well under practical JQL IN-clause limits.
_COMBINED_BATCH_SIZE = 150

# Explicit field projection so searches don't download every custom field.
# ``status`` carries the nested ``statusCategory``; ``parent`` and the configured
# epic-link field are required for client-side grouping of batched results.
_FIXED_FIELDS: tuple[str, ...] = (
    "summary",
    "status",
    "priority",
    "assignee",
    "reporter",
    "created",
    "updated",
    "resolution",
    "resolutiondate",
    "issuetype",
    "labels",
    "fixVersions",
    "parent",
)


def _drop_subtasks(children: list[JiraIssue]) -> list[JiraIssue]:
    """Return a copy of *children* with is_subtask=True items removed."""
    return [c for c in children if not c.is_subtask]


def _chunks(seq: list[str], size: int) -> list[list[str]]:
    """Split *seq* into consecutive chunks of at most *size* items."""
    return [seq[i : i + size] for i in range(0, len(seq), size)]


class JiraClient:
    """High-level wrapper around the ``jira`` library for Epic data."""

    # TTL for cached Jira field metadata (seconds)
    _FIELDS_CACHE_TTL = 3600  # 1 hour

    def __init__(self, auth: AuthManager) -> None:
        self._auth = auth
        self._jira: JIRA | None = None
        # Which auth path built the live client ("oauth" / "api_token" / None).
        # Drives whether a 401 can self-heal via :meth:`reauthenticate`.
        self._auth_method: str | None = None
        # Raw ``myself()`` payload captured during connection validation so the
        # login flow doesn't issue a second identical request.
        self._myself: dict[str, Any] | None = None
        self._fields_cache: list[dict[str, str]] | None = None
        self._fields_cache_time: float = 0.0

    def invalidate_caches(self) -> None:
        """Clear all cached data (e.g. field metadata)."""
        self._fields_cache = None
        self._fields_cache_time = 0.0
        self._myself = None
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
                timeout=_DEFAULT_TIMEOUT,
            )
            self._auth_method = "oauth"
            self._myself = None  # fetched lazily by get_myself()
            logger.info("Connected to Jira (cloud_id=%s)", self._auth.cloud_id)
            return True
        except (JIRAError, _requests.RequestException) as exc:
            logger.error("Failed to connect to Jira: %s", exc)
            return False

    def connect_basic(self, url: str, email: str, token: str) -> bool:
        """Connect to Jira using an API token.

        A scoped API key only works against the cloud API URL
        (``https://api.atlassian.com/ex/jira/{cloudId}``), while a classic
        unscoped token works against the instance URL.  When the site's
        ``cloudId`` is already known (cached from a previous connect, or an
        OAuth login) we go straight to the cloud API URL — skipping the
        instance-URL attempt that always 401s for scoped keys and costs two
        wasted round trips on every launch.  Otherwise we try the instance URL
        first and fall back to the cloud API on a 401.

        A lightweight ``myself()`` call validates each attempt; its payload is
        cached on the client so the caller need not re-fetch it.
        Returns True on success.
        """
        cloud_id = self._auth.cloud_id

        # 1) No cached cloudId — try classic basic auth against the instance URL.
        if not cloud_id:
            logger.debug("Connecting to Jira at %s (basic auth)", url)
            try:
                jira = JIRA(
                    server=url, basic_auth=(email, token), timeout=_DEFAULT_TIMEOUT
                )
                self._myself = jira.myself()
                self._jira = jira
                self._auth_method = "api_token"
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
            except _requests.RequestException as exc:
                logger.error("Failed to connect to Jira: %s", exc)
                self._jira = None
                return False

            cloud_id = self._resolve_cloud_id(url)
            if not cloud_id:
                logger.error("Could not resolve cloudId for %s", url)
                self._jira = None
                return False

        # 2) Scoped API key (or cached cloudId) — use the cloud API URL.
        cloud_url = f"https://api.atlassian.com/ex/jira/{cloud_id}"
        logger.debug("Connecting via cloud API URL %s", cloud_url)
        try:
            jira = JIRA(
                server=cloud_url, basic_auth=(email, token), timeout=_DEFAULT_TIMEOUT
            )
            self._myself = jira.myself()
            self._jira = jira
            self._auth_method = "api_token"
            # Cache cloud_id so subsequent reconnects skip the lookup
            if not self._auth.cloud_id:
                self._auth.set_cloud_id(cloud_id)
            logger.info("Connected to Jira via scoped API key (cloud_id=%s)", cloud_id)
            return True
        except (JIRAError, _requests.RequestException) as exc:
            logger.error("Failed to connect to Jira (scoped token): %s", exc)
            self._jira = None
            return False

    def reauthenticate(self) -> bool:
        """Refresh credentials and rebuild the client after an auth failure.

        Only OAuth sessions can self-heal: :meth:`connect` fetches a fresh
        access token (the auth manager refreshes it if expired) and rebuilds the
        client with it. API-token sessions cannot — a 401 there means a revoked
        or invalid token — so this returns False without retrying.
        """
        if self._auth_method != "oauth":
            return False
        logger.info("Re-authenticating OAuth session after an auth failure")
        return self.connect()

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
        except (_requests.RequestException, ValueError) as exc:
            logger.warning("Failed to resolve cloudId from %s: %s", tenant_url, exc)
            return None

    @property
    def connected(self) -> bool:
        """Return True when the Jira session is active."""
        return self._jira is not None

    # -- user info ------------------------------------------------------------

    def get_myself(self) -> dict[str, str] | None:
        """Return the authenticated user's display name and avatar URL.

        Reuses the ``myself()`` payload captured during connection validation
        when available, so a freshly-restored session needs no extra request.
        """
        if not self._jira:
            return None
        me = self._myself
        if me is None:
            try:
                me = self._jira.myself()
                self._myself = me
            except JIRAError as exc:
                logger.error("myself() failed: %s", exc)
                return None
        name = me.get("displayName", "")
        logger.info("Authenticated as %s", name)
        return {
            "displayName": name,
            "avatarUrl": me.get("avatarUrls", {}).get("48x48", ""),
            "emailAddress": me.get("emailAddress", ""),
        }

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
            epics = self._fetch_epics_bulk(
                [epic_key],
                sp_field=sp_field,
                epic_link_field=epic_link_field,
                start_date_field=start_date_field,
                due_date_field=due_date_field,
                include_subtasks=include_subtasks,
                include_subtasks_in_timeline=include_subtasks_in_timeline,
                sprint_field=sprint_field,
                timeline_start_field=timeline_start_field,
                timeline_end_field=timeline_end_field,
            )
        except JIRAError as exc:
            logger.error("Failed to fetch epic %s: %s", epic_key, exc)
            return None

        epic = epics.get(epic_key)
        if epic is None:
            logger.warning("Epic %s not found", epic_key)
            return None

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
            results = self._search_with_retry(
                f"key = {epic_key}", max_results=1, fields=["key"]
            )
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
            result = [{"id": f["id"], "name": f["name"]} for f in self._jira.fields()]
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

        logger.info("Fetching epics by label %r", label)
        keys = self._fetch_epic_keys_by_label(label)
        if not keys:
            logger.info("Found 0 epic(s) with label %r", label)
            return []

        epics_by_key = self._fetch_epics_bulk(
            keys,
            sp_field=sp_field,
            epic_link_field=epic_link_field,
            start_date_field=start_date_field,
            due_date_field=due_date_field,
            include_subtasks=include_subtasks,
            include_subtasks_in_timeline=include_subtasks_in_timeline,
            sprint_field=sprint_field,
            timeline_start_field=timeline_start_field,
            timeline_end_field=timeline_end_field,
        )
        # Preserve the key-ASC discovery order.
        epics = [epics_by_key[k] for k in keys if k in epics_by_key]
        logger.info("Found %d epic(s) with label %r", len(epics), label)
        return epics

    def _fetch_epic_keys_by_label(self, label: str) -> list[str]:
        """Return the Epic keys carrying *label*, ordered by key (key-only)."""
        jql = f'issuetype = Epic AND labels = "{label}" ORDER BY key ASC'
        try:
            rows = self._search_with_retry(
                jql, max_results=False, fields=["key"], use_post=True
            )
        except JIRAError as exc:
            logger.warning("Label epic discovery failed (%s): %s", label, exc)
            return []
        return [raw.key for raw in rows]

    def fetch_report_epics(
        self,
        epic_keys: list[str],
        labels: list[str],
        *,
        sp_field: str = "story_points",
        epic_link_field: str = "customfield_10014",
        start_date_field: str = "startdate",
        due_date_field: str = "duedate",
        include_subtasks: bool = True,
        include_subtasks_in_timeline: bool = True,
        sprint_field: str = "customfield_10020",
        timeline_start_field: str = "",
        timeline_end_field: str = "",
    ) -> tuple[dict[str, EpicData], dict[str, list[str]]]:
        """Fetch every epic needed for a report in as few requests as possible.

        Resolves each label to its epic keys (one cheap key-only query per
        label), then fetches all epics — direct items plus label members,
        de-duplicated — through a single batched :meth:`_fetch_epics_bulk` pass.

        Returns ``(epics_by_key, label_to_keys)`` where *epics_by_key* maps each
        resolved epic key to its fully-assembled :class:`EpicData`, and
        *label_to_keys* maps each label to its epic keys in key-ASC order.  A
        requested key absent from *epics_by_key* simply was not found in Jira.
        """
        if not self._jira:
            return {}, {}

        label_to_keys: dict[str, list[str]] = {}
        all_keys: list[str] = list(epic_keys)
        for label in labels:
            keys = self._fetch_epic_keys_by_label(label)
            label_to_keys[label] = keys
            all_keys.extend(keys)

        # De-duplicate while preserving first-seen order.
        unique_keys = list(dict.fromkeys(all_keys))
        epics_by_key = self._fetch_epics_bulk(
            unique_keys,
            sp_field=sp_field,
            epic_link_field=epic_link_field,
            start_date_field=start_date_field,
            due_date_field=due_date_field,
            include_subtasks=include_subtasks,
            include_subtasks_in_timeline=include_subtasks_in_timeline,
            sprint_field=sprint_field,
            timeline_start_field=timeline_start_field,
            timeline_end_field=timeline_end_field,
        )
        logger.info(
            "Report fetch: %d epic(s) across %d label(s) → %d resolved",
            len(epic_keys),
            len(labels),
            len(epics_by_key),
        )
        return epics_by_key, label_to_keys

    def fetch_epic_summaries_by_label(self, label: str) -> list[tuple[str, str]]:
        """Return ``(key, summary)`` for every Epic carrying *label*.

        Lightweight counterpart to :meth:`fetch_epics_by_label` — it does not
        pull child issues, so it is cheap enough to call when opening the
        per-item customize dialog.
        """
        if not self._jira:
            return []
        jql = f'issuetype = Epic AND labels = "{label}" ORDER BY key ASC'
        logger.debug("Fetching epic summaries for label %r", label)
        return self._fetch_key_summaries(jql)

    def fetch_child_summaries(
        self,
        epic_key: str,
        epic_link_field: str = "customfield_10014",
    ) -> list[tuple[str, str]]:
        """Return ``(key, summary)`` for the direct stories/tasks of *epic_key*.

        Combines the Epic-Link and parent-hierarchy queries (deduplicated),
        excluding deeper subtasks — mirroring the direct children used in the
        report. Lightweight; intended for the per-item customize dialog.
        """
        if not self._jira:
            return []
        logger.debug("Fetching child summaries for %s", epic_key)
        seen: set[str] = set()
        out: list[tuple[str, str]] = []
        for jql in (
            f'"{epic_link_field}" = {epic_key} ORDER BY created ASC',
            f"parent = {epic_key} ORDER BY created ASC",
        ):
            for key, summary in self._fetch_key_summaries(jql):
                if key not in seen:
                    seen.add(key)
                    out.append((key, summary))
        return out

    def _fetch_key_summaries(self, jql: str) -> list[tuple[str, str]]:
        """Run a JQL search returning ``(key, summary)`` pairs (summary only)."""
        try:
            results = self._search_with_retry(
                jql, max_results=False, fields=["summary"], use_post=True
            )
        except JIRAError as exc:
            logger.warning("Summary search failed (%s): %s", jql, exc)
            return []
        return [(raw.key, getattr(raw.fields, "summary", "") or "") for raw in results]

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
            # getattr so a future jira-lib rename degrades to the JQL fallback
            # explicitly rather than relying on the broad except below.
            session = getattr(self._jira, "_session", None)
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
                fields=["labels"],
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
            collect_child_estimation_dates(c, candidate_starts, candidate_ends)

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

    def _build_field_list(
        self,
        sp_field: str,
        epic_link_field: str,
        start_date_field: str,
        due_date_field: str,
        timeline_start_field: str,
        timeline_end_field: str,
        sprint_field: str,
    ) -> list[str]:
        """Build the explicit field projection for epic/children searches.

        Combines the fixed fields read by the parsers with the configurable
        field ids (estimate, epic-link, sprint, estimation + timeline dates) and
        the ``customfield_10016`` story-points fallback.  ``epic_link_field`` and
        ``parent`` (in :data:`_FIXED_FIELDS`) are required to regroup batched
        results back to their epics.
        """
        fields = [
            *_FIXED_FIELDS,
            sp_field,
            "customfield_10016",  # default Jira Cloud SP field (fallback)
            epic_link_field,
            sprint_field,
            start_date_field,
            due_date_field,
            timeline_start_field or start_date_field,
            timeline_end_field or due_date_field,
        ]
        # De-duplicate, preserving order and dropping empty names.
        seen: set[str] = set()
        out: list[str] = []
        for name in fields:
            if name and name not in seen:
                seen.add(name)
                out.append(name)
        return out

    @staticmethod
    def _epic_key_of(value: Any) -> str | None:
        """Normalise an Epic-Link field value to a plain issue key.

        Classic projects store the epic key as a string; some configurations
        return a dict or object — handle all three.
        """
        if value is None:
            return None
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            return value.get("key")
        return getattr(value, "key", None)

    def _fetch_epics_bulk(
        self,
        epic_keys: list[str],
        *,
        sp_field: str = "story_points",
        epic_link_field: str = "customfield_10014",
        start_date_field: str = "startdate",
        due_date_field: str = "duedate",
        include_subtasks: bool = True,
        include_subtasks_in_timeline: bool = True,
        sprint_field: str = "customfield_10020",
        timeline_start_field: str = "",
        timeline_end_field: str = "",
    ) -> dict[str, EpicData]:
        """Fetch many epics and all their children in a handful of requests.

        Issues one combined ``key in / epic_link in / parent in`` query per key
        batch (epics + direct children together), then one batched
        ``parent in (...)`` query for subtasks across every epic.  Results are
        grouped back to their epics client-side.  Returns a mapping of epic key →
        assembled :class:`EpicData`; requested keys not found in Jira are simply
        absent from the result.
        """
        if not self._jira or not epic_keys:
            return {}

        unique_keys = list(dict.fromkeys(epic_keys))
        epic_set = set(unique_keys)
        fields = self._build_field_list(
            sp_field,
            epic_link_field,
            start_date_field,
            due_date_field,
            timeline_start_field,
            timeline_end_field,
            sprint_field,
        )

        epics: dict[str, EpicData] = {}
        direct_children: dict[str, list[JiraIssue]] = {k: [] for k in unique_keys}
        subtasks: dict[str, list[JiraIssue]] = {k: [] for k in unique_keys}
        child_to_epic: dict[str, str] = {}
        seen_children: set[str] = set()

        def parse_child(raw: Any) -> JiraIssue:
            return self._parse_child_issue(
                raw,
                sp_field,
                start_date_field,
                due_date_field,
                sprint_field,
                timeline_start_field,
                timeline_end_field,
            )

        # Phase 1: epics + their direct children, batched into combined queries.
        for batch in _chunks(unique_keys, _COMBINED_BATCH_SIZE):
            keys_csv = ", ".join(batch)
            jql = (
                f"(key in ({keys_csv}) "
                f'OR "{epic_link_field}" in ({keys_csv}) '
                f"OR parent in ({keys_csv})) "
                f"ORDER BY created ASC"
            )
            logger.debug("Bulk fetch epics+children for %d key(s)", len(batch))
            rows = self._search_with_retry(
                jql, max_results=False, fields=fields, use_post=True
            )
            for raw in rows:
                # Key-first: a requested key is always its own epic, never a
                # child (covers an epic nested under another requested epic).
                if raw.key in epic_set:
                    if raw.key not in epics:
                        epics[raw.key] = self._parse_epic_from_raw(
                            raw,
                            start_date_field,
                            due_date_field,
                            timeline_start_field,
                            timeline_end_field,
                        )
                    continue
                if raw.key in seen_children:
                    continue
                issue = parse_child(raw)
                link = self._epic_key_of(self._get_raw_field(raw, epic_link_field))
                if link in epic_set:
                    owner: str | None = link
                elif issue.parent_key in epic_set:
                    owner = issue.parent_key
                else:
                    logger.debug("Ungroupable child row %s — skipping", raw.key)
                    continue
                issue.is_subtask = False
                seen_children.add(issue.key)
                direct_children[owner].append(issue)
                child_to_epic[issue.key] = owner

        # Phase 2: subtasks of every direct child, batched across all epics.
        need_subtasks = include_subtasks or include_subtasks_in_timeline
        if need_subtasks and child_to_epic:
            for batch in _chunks(list(child_to_epic), _JQL_IN_BATCH_SIZE):
                keys_csv = ", ".join(batch)
                jql = f"parent in ({keys_csv}) ORDER BY created ASC"
                logger.debug("Bulk fetch subtasks for %d parent(s)", len(batch))
                rows = self._search_with_retry(
                    jql, max_results=False, fields=fields, use_post=True
                )
                for raw in rows:
                    if raw.key in seen_children or raw.key in epic_set:
                        continue
                    issue = parse_child(raw)
                    owner = child_to_epic.get(issue.parent_key or "")
                    if owner is None:
                        continue
                    issue.is_subtask = True
                    seen_children.add(issue.key)
                    subtasks[owner].append(issue)

        # Assemble each epic: direct children (created-ASC from the per-epic
        # query) followed by subtasks; expand epic dates; optionally drop the
        # timeline-only subtasks so metrics treat their parents as leaves.
        for key, epic in epics.items():
            epic.children = direct_children[key] + subtasks[key]
            self._fill_epic_dates_from_children(
                epic, include_subtask_timeline=include_subtasks_in_timeline
            )
            if not include_subtasks and include_subtasks_in_timeline:
                epic.children = _drop_subtasks(epic.children)
            logger.debug("Assembled epic %s: %d children", key, len(epic.children))

        return epics

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
        self,
        jql: str,
        *,
        start_at: int = 0,
        max_results: int | bool = _MAX_RESULTS,
        fields: list[str] | None = None,
        use_post: bool = False,
    ) -> list[Any]:
        """Execute a JQL search with a progressive timeout and retry policy.

        Each attempt uses a longer request timeout (``_PROGRESSIVE_TIMEOUTS``):
        the first fails fast on a stale / idle-reaped keep-alive socket, later
        attempts grant a slow server more headroom. Retries cover transient
        transport errors (``Timeout`` / ``ConnectionError`` — notably the
        stalled-body read the underlying session does *not* retry), 429 rate
        limits (exponential backoff), and a single 401 re-authentication for
        OAuth sessions.

        *fields* restricts the returned field set (a projection); ``None`` keeps
        the library default of every field.  Passing a falsy *max_results* lets
        the ``jira`` library fetch all pages in one call via the Jira Cloud
        token-paginated endpoint — this is required because ``search_issues``
        raises on ``startAt > 0`` against Cloud.  *use_post* sends the JQL in the
        request body, avoiding URL-length limits for large ``IN`` clauses.
        """
        if self._jira is None:
            raise RuntimeError("call connect() first")

        # Progressive timeout is applied by mutating the shared ResilientSession
        # (the library hardcodes ``timeout=self.timeout`` per request and rejects
        # a per-call override), restoring the baseline in ``finally`` so other
        # call sites aren't left on a short timeout.
        session = getattr(self._jira, "_session", None)
        baseline = getattr(session, "timeout", None)
        reauthed = False
        attempt = 0
        last_attempt = len(_PROGRESSIVE_TIMEOUTS) - 1
        try:
            while True:
                if session is not None:
                    session.timeout = _PROGRESSIVE_TIMEOUTS[attempt]
                try:
                    return self._jira.search_issues(
                        jql,
                        startAt=start_at,
                        maxResults=max_results,
                        fields=fields,
                        use_post=use_post,
                    )
                except (
                    _requests.exceptions.Timeout,
                    _requests.exceptions.ConnectionError,
                ) as exc:
                    if attempt >= last_attempt:
                        raise
                    logger.warning(
                        "Transport error (%s), retrying on a fresh connection",
                        type(exc).__name__,
                    )
                    time.sleep(_TRANSPORT_RETRY_DELAY)
                    attempt += 1
                except JIRAError as exc:
                    if exc.status_code == 429 and attempt < last_attempt:
                        delay = _BACKOFF_BASE * (2**attempt)
                        logger.warning("Rate limited, retrying in %.1fs", delay)
                        time.sleep(delay)
                        attempt += 1
                        continue
                    if exc.status_code == 401 and not reauthed:
                        reauthed = True
                        logger.warning("Auth rejected (401), re-authenticating")
                        if self.reauthenticate():
                            # connect() rebuilt the client — refresh our handles
                            # and retry without consuming the timeout budget.
                            session = getattr(self._jira, "_session", None)
                            baseline = getattr(session, "timeout", None)
                            continue
                    raise
        finally:
            if session is not None:
                session.timeout = baseline

    @staticmethod
    def _status_category(fields: Any) -> str:
        status = getattr(fields, "status", None)
        if status is None:
            return STATUS_TODO
        cat = getattr(status, "statusCategory", None)
        if cat is None:
            return STATUS_TODO
        name = getattr(cat, "name", None)
        return str(name) if name else STATUS_TODO

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

                if name:
                    result.append(
                        SprintInfo(
                            name=str(name),
                            start_date=JiraClient._parse_date(start),
                            end_date=JiraClient._parse_date(end),
                            state=str(state),
                        )
                    )
            except (TypeError, AttributeError, KeyError) as exc:
                logger.debug("Skipping malformed sprint entry: %s", exc)
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
