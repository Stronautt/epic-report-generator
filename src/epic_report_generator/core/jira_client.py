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
    HierarchyNode,
    JiraIssue,
    SprintInfo,
    collect_child_estimation_dates,
    collect_child_timeline_dates,
    epic_tier_type_names,
)
from epic_report_generator.core.hierarchy import HierarchyResolver
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


# Changelog (expand=changelog) responses are heavy, so keep each batch small —
# well under Jira's default 100-issue page so json_result returns it in one page.
_CHANGELOG_BATCH_SIZE = 50


def _to_float(value: Any) -> float | None:
    """Parse a changelog string value to float, or ``None`` when blank/invalid."""
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _is_custom(chain: list[HierarchyNode] | None) -> bool:
    """True when *chain* needs the N-tier BFS path rather than the fast default.

    Only a ``link`` edge forces the BFS — that's the one shape the fast
    ``key/epic_link/parent`` query can't express. A **parent-only** chain (any
    number of types) maps onto the fast path's epic → direct-children → sub-tasks
    structure: several types at one tier are siblings (all direct children of the
    tier above), and :meth:`apply_hierarchy` filters by type and resolves the
    show/estimate cascade. An empty chain stays on the byte-for-byte default.
    """
    if not chain:
        return False
    return any(n.edge == "link" for n in chain)


def _link_targets(
    rows: list[Any], link_types: list[str]
) -> dict[str, str]:
    """Map ``target_key -> source_key`` for issue links matching *link_types*.

    Reads each row's ``issuelinks`` field and keeps entries whose
    ``type.name`` is in *link_types* (either direction — inward or outward).
    An empty *link_types* means **any** link type, matching the editor's
    "Links: (any)" label — otherwise the tier would silently fetch nothing.
    The first source to reference a target wins, so a target attaches to a
    single hierarchy parent.
    """
    wanted = set(link_types)
    out: dict[str, str] = {}
    for raw in rows:
        links = JiraClient._get_raw_field(raw, "issuelinks") or []
        for link in links:
            if isinstance(link, dict):
                name = (link.get("type") or {}).get("name")
                other = link.get("inwardIssue") or link.get("outwardIssue")
                tkey = (other or {}).get("key") if isinstance(other, dict) else None
            else:
                name = getattr(getattr(link, "type", None), "name", None)
                other = getattr(link, "inwardIssue", None) or getattr(
                    link, "outwardIssue", None
                )
                tkey = getattr(other, "key", None)
            if (not wanted or name in wanted) and tkey and tkey not in out:
                out[tkey] = raw.key
    return out


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
        # Issue-type / link-type metadata for the hierarchy constructor. Lazily
        # fetched, cleared by the Refresh button via :meth:`invalidate_caches`
        # (metadata rarely changes, so a None-guard is enough — no TTL).
        self._issue_types_cache: list[dict[str, Any]] | None = None
        self._link_types_cache: list[dict[str, str]] | None = None
        # type_id -> icon bytes (or None when the fetch failed / no iconUrl), so
        # a missing icon isn't re-requested every render.
        self._icon_cache: dict[str, bytes | None] = {}
        # (query, jql) -> picker suggestions, so autocomplete re-issues no request
        # for a query already seen this session (e.g. backspace/retype). Bounded.
        self._picker_cache: dict[tuple[str, str], list[tuple[str, str]]] = {}

    def invalidate_caches(self) -> None:
        """Clear all cached data (e.g. field metadata)."""
        self._fields_cache = None
        self._fields_cache_time = 0.0
        self._myself = None
        self._issue_types_cache = None
        self._link_types_cache = None
        self._icon_cache = {}
        self._picker_cache = {}
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
        chain: list[HierarchyNode] | None = None,
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
                chain=chain,
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

    # -- hierarchy metadata (issue types / link types / icons / picker) --------

    def fetch_issue_types(self) -> list[dict[str, Any]]:
        """Return the instance's issue types for the hierarchy constructor.

        Each entry is ``{id, name, iconUrl, subtask, hierarchyLevel}``.
        ``hierarchyLevel`` (Jira Cloud) maps cleanly to the report's tiers
        (1+=Epic-tier, 0=Story-tier, <0=Sub-task; standard Epic is level 1).
        Cached in-memory until
        :meth:`invalidate_caches` (Refresh).
        """
        if not self._jira:
            return []
        if self._issue_types_cache is not None:
            return self._issue_types_cache
        # getattr so a future jira-lib rename degrades gracefully.
        getter = getattr(self._jira, "issue_types", None)
        if getter is None:
            return []
        try:
            raw = getter()
        except JIRAError as exc:
            logger.error("Failed to fetch issue types: %s", exc)
            return []
        result = [
            {
                "id": str(getattr(t, "id", "")),
                "name": getattr(t, "name", "") or "",
                "iconUrl": getattr(t, "iconUrl", "") or "",
                "subtask": bool(getattr(t, "subtask", False)),
                "hierarchyLevel": getattr(t, "hierarchyLevel", None),
            }
            for t in raw
        ]
        logger.info("Fetched %d issue type(s)", len(result))
        self._issue_types_cache = result
        return result

    def fetch_issue_link_types(self) -> list[dict[str, str]]:
        """Return the instance's issue link types (``{id, name, inward, outward}``).

        Cached in-memory until :meth:`invalidate_caches` (Refresh).
        """
        if not self._jira:
            return []
        if self._link_types_cache is not None:
            return self._link_types_cache
        getter = getattr(self._jira, "issue_link_types", None)
        if getter is None:
            return []
        try:
            raw = getter()
        except JIRAError as exc:
            logger.error("Failed to fetch issue link types: %s", exc)
            return []
        result = [
            {
                "id": str(getattr(lt, "id", "")),
                "name": getattr(lt, "name", "") or "",
                "inward": getattr(lt, "inward", "") or "",
                "outward": getattr(lt, "outward", "") or "",
            }
            for lt in raw
        ]
        logger.info("Fetched %d issue link type(s)", len(result))
        self._link_types_cache = result
        return result

    def fetch_issue_picker(
        self, query: str, current_jql: str = ""
    ) -> list[tuple[str, str]]:
        """Return ``(key, summary)`` autocomplete suggestions for *query*.

        Hits the ``/rest/api/3/issue/picker`` endpoint (matches both key and
        summary), mirroring the raw ``_session`` call in :meth:`fetch_labels`.
        *current_jql* scopes the suggestions (e.g. to Epic-tier issue types).
        """
        if not self._jira or not query.strip():
            return []
        cache_key = (query, current_jql)
        cached = self._picker_cache.get(cache_key)
        if cached is not None:
            return cached
        try:
            url = f"{self._jira.server_url}/rest/api/3/issue/picker"
            session = getattr(self._jira, "_session", None)
            if session is None:
                raise RuntimeError("No active Jira session")
            params: dict[str, str] = {"query": query}
            if current_jql:
                params["currentJQL"] = current_jql
            # No timeout= here: the jira lib's ResilientSession injects its own
            # timeout into request(), and passing one again raises
            # "got multiple values for keyword argument 'timeout'" (mirrors
            # fetch_labels, which also omits it).
            resp = session.get(url, params=params)
            if resp.status_code != 200:
                logger.debug("Issue picker returned HTTP %d", resp.status_code)
                return []
            seen: set[str] = set()
            out: list[tuple[str, str]] = []
            for section in resp.json().get("sections", []) or []:
                for issue in section.get("issues", []) or []:
                    key = issue.get("key", "")
                    if not key or key in seen:
                        continue
                    seen.add(key)
                    summary = issue.get("summaryText") or issue.get("summary") or ""
                    out.append((key, summary))
            if len(self._picker_cache) > 128:  # simple bound; clear wholesale
                self._picker_cache.clear()
            self._picker_cache[cache_key] = out
            return out
        except Exception as exc:
            logger.debug("Issue picker failed for %r: %s", query, exc)
            return []

    def issue_type_icon(self, type_id: str) -> bytes | None:
        """Return the SVG/PNG icon bytes for *type_id*, or None.

        Lazily ``GET``-s the type's ``iconUrl`` via the live ``_session`` and
        caches the result (including failures, so a broken URL isn't refetched
        every render). Cleared by :meth:`invalidate_caches`.
        """
        if not self._jira or not type_id:
            return None
        if type_id in self._icon_cache:
            return self._icon_cache[type_id]
        icon_url = next(
            (t["iconUrl"] for t in self.fetch_issue_types() if t["id"] == type_id),
            "",
        )
        result: bytes | None = None
        if icon_url:
            try:
                session = getattr(self._jira, "_session", None)
                if session is None:
                    raise RuntimeError("No active Jira session")
                # No timeout= — the ResilientSession injects its own (see
                # fetch_issue_picker); passing one raises a duplicate-kwarg error.
                resp = session.get(icon_url)
                if resp.status_code == 200 and resp.content:
                    result = resp.content
                else:
                    logger.debug(
                        "Icon fetch for %s returned HTTP %d", type_id, resp.status_code
                    )
            except Exception as exc:
                logger.debug("Icon fetch for %s failed: %s", type_id, exc)
        self._icon_cache[type_id] = result
        return result

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
        chain: list[HierarchyNode] | None = None,
    ) -> list[EpicData]:
        """Fetch all Epics with the given label, including their children.

        Returns an empty list if the client is not connected or no epics match.
        """
        if not self._jira:
            return []

        logger.info("Fetching epics by label %r", label)
        keys = self._fetch_epic_keys_by_label(label, epic_tier_type_names(chain or []))
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
            chain=chain,
        )
        # Preserve the key-ASC discovery order.
        epics = [epics_by_key[k] for k in keys if k in epics_by_key]
        logger.info("Found %d epic(s) with label %r", len(epics), label)
        return epics

    def _fetch_epic_keys_by_label(
        self, label: str, epic_tier_types: list[str] | None = None
    ) -> list[str]:
        """Return the Epic keys carrying *label*, ordered by key (key-only).

        *epic_tier_types* scopes the issue-type filter to the chain's Epic-tier
        type names (default ``["Epic"]``), so a custom chain whose top tier is
        e.g. ``Capability`` resolves the right issues.
        """
        types_csv = ", ".join(f'"{t}"' for t in (epic_tier_types or ["Epic"]))
        jql = f'issuetype in ({types_csv}) AND labels = "{label}" ORDER BY key ASC'
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
        chain: list[HierarchyNode] | None = None,
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

        epic_tier_types = epic_tier_type_names(chain or [])
        label_to_keys: dict[str, list[str]] = {}
        all_keys: list[str] = list(epic_keys)
        for label in labels:
            keys = self._fetch_epic_keys_by_label(label, epic_tier_types)
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
            chain=chain,
        )
        logger.info(
            "Report fetch: %d epic(s) across %d label(s) → %d resolved",
            len(epic_keys),
            len(labels),
            len(epics_by_key),
        )
        return epics_by_key, label_to_keys

    def fetch_epic_summaries_by_label(
        self, label: str, epic_tier_types: list[str] | None = None
    ) -> list[tuple[str, str]]:
        """Return ``(key, summary)`` for every Epic carrying *label*.

        Lightweight counterpart to :meth:`fetch_epics_by_label` — it does not
        pull child issues, so it is cheap enough to call when opening the
        per-item customize dialog.  *epic_tier_types* scopes the issue-type
        filter to the chain's Epic-tier names (default ``["Epic"]``).
        """
        if not self._jira:
            return []
        types_csv = ", ".join(f'"{t}"' for t in (epic_tier_types or ["Epic"]))
        jql = f'issuetype in ({types_csv}) AND labels = "{label}" ORDER BY key ASC'
        logger.debug("Fetching epic summaries for label %r", label)
        return self._fetch_key_summaries(jql)

    def fetch_child_summaries(
        self,
        epic_key: str,
        epic_link_field: str = "customfield_10014",
        chain: list[HierarchyNode] | None = None,
        parent_tier: int = 0,
    ) -> list[tuple[str, str]]:
        """Return ``(key, summary)`` for *epic_key*'s children one display tier down.

        *parent_tier* is *epic_key*'s own tier (0 for a report Epic, 1 when drilling
        into a Story), so this returns its tier-``parent_tier+1`` children — the
        single source the strict-tier-nesting customize dialog drills through.

        With an **empty chain** it combines the Epic-Link and parent queries
        (deduplicated) — the classic direct-children behaviour.  With a **chain**
        it fetches the same candidates (Epic-Link *or* parent at the Epic tier,
        parent deeper, plus any link-edge next-tier node's issue-links) and then
        keeps only those whose issue type actually resolves to ``parent_tier+1`` —
        so a type pinned to a deeper tier (e.g. a Task moved to Sub-task) never
        leaks in at this level, matching :meth:`apply_hierarchy` in the report.
        Lightweight; for the per-item customize dialog.
        """
        if not self._jira:
            return []
        logger.debug("Fetching tier-%d children for %s", parent_tier + 1, epic_key)
        chain = chain or []
        if not chain:
            return self._direct_child_summaries(epic_key, epic_link_field)
        return self._chain_tier_summaries(
            epic_key, epic_link_field, chain, parent_tier
        )

    def _direct_child_summaries(
        self, epic_key: str, epic_link_field: str
    ) -> list[tuple[str, str]]:
        """``(key, summary)`` for an epic's direct children (Epic-Link + parent)."""
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

    def _chain_tier_summaries(
        self,
        parent_key: str,
        epic_link_field: str,
        chain: list[HierarchyNode],
        parent_tier: int,
    ) -> list[tuple[str, str]]:
        """``(key, summary)`` for *parent_key*'s chain-children at ``parent_tier+1``.

        Mirrors the report fetch: the Epic tier reaches children via Epic-Link *or*
        parent, deeper tiers via parent; each link-edge next-tier node adds an
        issue-links read.  The union is then filtered to the issue types that
        resolve to ``parent_tier+1`` via :class:`HierarchyResolver`.
        """
        resolver = HierarchyResolver(chain)
        nodes = resolver.child_nodes_of(parent_tier)
        if not nodes:
            return []
        seen: set[str] = set()
        candidates: list[tuple[str, str]] = []

        def _add(rows: list[tuple[str, str]]) -> None:
            for key, summary in rows:
                if key not in seen:
                    seen.add(key)
                    candidates.append((key, summary))

        if any(n.edge == "parent" for n in nodes):
            if parent_tier == 0:
                _add(self._direct_child_summaries(parent_key, epic_link_field))
            else:
                _add(
                    self._fetch_key_summaries(
                        f"parent = {parent_key} ORDER BY created ASC"
                    )
                )
        for node in nodes:
            if node.edge == "link":
                _add(self._chain_child_summaries_link(parent_key, node.link_types))

        if not any(n.issue_type_id for n in chain):
            # An id-less chain (offline / not yet refreshed) can't be matched by the
            # issue-type projection; return unfiltered rather than drop everything.
            return candidates
        target = parent_tier + 1
        meta = self.fetch_issue_meta([k for k, _ in candidates])

        def _at_target(key: str) -> bool:
            tid, tname, _ = meta.get(key, ("", "", ""))
            return resolver.tier_of(tid, tname) == target

        return [(key, summary) for key, summary in candidates if _at_target(key)]

    def _chain_child_summaries_link(
        self, epic_key: str, link_types: list[str]
    ) -> list[tuple[str, str]]:
        """``(key, summary)`` for *epic_key*'s link-connected children (one tier)."""
        try:
            rows = self._search_with_retry(
                f"key = {epic_key}", max_results=1, fields=["issuelinks"]
            )
        except JIRAError as exc:
            logger.warning("Link-child lookup failed for %s: %s", epic_key, exc)
            return []
        targets = _link_targets(rows, link_types)
        if not targets:
            return []
        out: list[tuple[str, str]] = []
        for batch in _chunks(list(targets), _JQL_IN_BATCH_SIZE):
            csv = ", ".join(batch)
            out.extend(self._fetch_key_summaries(f"key in ({csv})"))
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

    def fetch_issue_meta(self, keys: list[str]) -> dict[str, tuple[str, str, str]]:
        """Return ``{key: (issue-type id, issue-type name, summary)}`` (batched).

        Lightweight (issue-type + summary projection only) — drives report-item
        row icons, the display-name placeholder, and the customize dialog's
        tier filter.  The **name** is carried alongside the id so callers resolve
        a type by id-then-name (mirroring :meth:`apply_hierarchy`): the same type
        name can have different ids across projects, so id alone would drop valid
        children.  Unknown keys are absent.
        """
        if not self._jira or not keys:
            return {}
        out: dict[str, tuple[str, str, str]] = {}
        for chunk in _chunks(list(dict.fromkeys(keys)), 50):
            csv = ", ".join(chunk)
            try:
                rows = self._search_with_retry(
                    f"key in ({csv})",
                    max_results=False,
                    fields=["issuetype", "summary"],
                    use_post=True,
                )
            except JIRAError as exc:
                logger.warning("Issue meta lookup failed (%s): %s", csv, exc)
                continue
            for raw in rows:
                summary = getattr(getattr(raw, "fields", None), "summary", "") or ""
                out[raw.key] = (
                    self._issue_type_id_of(raw),
                    self._issue_type_name_of(raw),
                    summary,
                )
        return out

    def fetch_issue_type_ids(self, keys: list[str]) -> dict[str, str]:
        """Return ``{issue key: issue-type id}`` for *keys* (see fetch_issue_meta)."""
        return {k: tid for k, (tid, _n, _s) in self.fetch_issue_meta(keys).items()}

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
    def _fill_epic_dates_from_children(epic: EpicData) -> None:
        """Expand epic-level dates to cover the full range of child issues.

        The epic's start_date becomes the earliest date and due_date the
        latest date across the epic's own dates and all children.  For each
        child, prefer start_date/due_date but fall back to created/resolved
        so that every child contributes to the range.

        Timeline dates (timeline_start / timeline_end) are computed with a
        cascade: timeline field values → sprint dates → start_date/due_date.
        This matches Jira Cloud Timeline behaviour, which derives epic ranges
        from child sprint assignments when no explicit dates are set.

        Tier-1 children always pool timeline dates; a tier-2 (sub-task) child
        expands the timeline range only when ``show`` is set (estimation dates
        still include all children).  ``show`` encodes the old
        ``include_subtasks_in_timeline`` flag for the default 2-tier path, so
        the default Gantt range stays byte-for-byte identical.

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

            # A tier-2 (sub-task) child expands the timeline range only when shown.
            if c.display_tier == 2 and not c.show:
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
        chain: list[HierarchyNode] | None = None,
    ) -> dict[str, EpicData]:
        """Fetch many epics and all their children in a handful of requests.

        Issues one combined ``key in / epic_link in / parent in`` query per key
        batch (epics + direct children together), then one batched
        ``parent in (...)`` query for subtasks across every epic.  Results are
        grouped back to their epics client-side.  Returns a mapping of epic key →
        assembled :class:`EpicData`; requested keys not found in Jira are simply
        absent from the result.

        A *custom* chain (any link edge) is delegated to the N-tier
        :meth:`_fetch_epics_chain`.  A non-custom chain (the migrated
        ``Epic→Story→Sub-task`` default) still runs this fast path, but the
        subtask fetch is derived from its Sub-task tier-2 node instead of the
        ``include_subtasks*`` flags: fetch when that node is shown or estimated.
        """
        if not self._jira or not epic_keys:
            return {}

        if _is_custom(chain):
            return self._fetch_epics_chain(
                epic_keys,
                chain or [],
                sp_field=sp_field,
                epic_link_field=epic_link_field,
                start_date_field=start_date_field,
                due_date_field=due_date_field,
                sprint_field=sprint_field,
                timeline_start_field=timeline_start_field,
                timeline_end_field=timeline_end_field,
            )

        tier1_show = True
        tier1_estimate = True
        if chain:
            # A child tier maps many-to-many onto the tier above (a sub-task hangs
            # off any tier-1 type — Story / Task / Bug), so gate the sub-task fetch
            # on EVERY tier-2/tier-1 node, not a single representative. Fetch when
            # the Sub-task tier is shown by any of its nodes, or estimated by any
            # node AND some tier-1 ancestor + the epic are estimated (else
            # apply_hierarchy's metrics cascade would drop them anyway, so skipping
            # the query is safe).
            root_node = next((n for n in chain if n.display_tier == 0), None)
            tier1_nodes = [n for n in chain if n.display_tier == 1]
            tier2_nodes = [n for n in chain if n.display_tier == 2]
            root_est = root_node.in_estimate if root_node is not None else True
            any_tier1_est = (
                any(n.in_estimate for n in tier1_nodes) if tier1_nodes else True
            )
            include_subtasks_in_timeline = any(n.show for n in tier2_nodes)
            include_subtasks = (
                any(n.in_estimate for n in tier2_nodes) and any_tier1_est and root_est
            )

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
            issue = self._parse_child_issue(
                raw,
                sp_field,
                start_date_field,
                due_date_field,
                sprint_field,
                timeline_start_field,
                timeline_end_field,
            )
            # The view-model treats any non-empty chain as custom and keys child
            # icons on issue_type_id; set it here (as the chain path does) so a
            # non-custom chain's Story/Sub-task rows get icons too.
            issue.issue_type_id = self._issue_type_id_of(raw)
            return issue

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
                # Mirror the migrated chain's Story tier-1 node (same reason the
                # subtask phase mirrors tier-2): a migrated chain makes the
                # view-model treat this as "custom" and read child.show /
                # display_tier directly, so direct children must carry the
                # migrated flags instead of the JiraIssue defaults — otherwise a
                # migrated profile with show_epic_stories_on_timeline=False still
                # renders story bars + nested summary rows.
                issue.display_tier = 1
                issue.show = tier1_show
                issue.in_estimate = tier1_estimate
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
                    # Mirror the migrated chain's Sub-task tier so the metrics +
                    # timeline-date layers can gate purely on display_tier/show
                    # instead of the include_subtasks* flags (default path stays
                    # byte-for-byte identical: show drives timeline pooling).
                    issue.display_tier = 2
                    issue.show = include_subtasks_in_timeline
                    issue.in_estimate = include_subtasks
                    # Record the real parent so apply_hierarchy's cascade can reach
                    # the tier-1 node above (a non-empty chain re-resolves the flags).
                    issue.hierarchy_parent_key = issue.parent_key
                    seen_children.add(issue.key)
                    subtasks[owner].append(issue)

        # Assemble each epic: direct children (created-ASC from the per-epic
        # query) followed by subtasks; expand epic dates; optionally drop the
        # timeline-only subtasks so metrics treat their parents as leaves.
        for key, epic in epics.items():
            epic.children = direct_children[key] + subtasks[key]
            if chain:
                # The chain is authoritative: drop off-chain issue types and
                # re-resolve display_tier + the show/estimate cascade per type
                # (mirrors the link-edge BFS). The default all-types chain keeps
                # every type; the Exclude pool removes one everywhere.
                self.apply_hierarchy(epic, chain)
            self._fill_epic_dates_from_children(epic)
            if not chain and not include_subtasks and include_subtasks_in_timeline:
                epic.children = _drop_subtasks(epic.children)
            logger.debug("Assembled epic %s: %d children", key, len(epic.children))

        return epics

    def enrich_trend_history(self, epics: dict[str, EpicData], sp_field: str) -> None:
        """Populate in-estimate children's SP/done history from their changelog.

        Called once by the report generator after the fetch (kept out of the
        structure-assembly fetch so it adds no query there). The trend chart's
        burnup is reconstructed from these event lists, mirroring Jira: a story
        estimated at 3 then bumped to 8 steps the scope line twice, and completion
        is dated by the resolution event. Only the ``in_estimate`` children that
        feed the chart are fetched, de-duplicated across epics. Best-effort: on any
        error (or a child with no relevant events) the issue keeps empty histories
        and the metrics layer falls back to the created/resolved approximation.
        """
        if not self._jira:
            return
        by_key: dict[str, JiraIssue] = {}
        for epic in epics.values():
            for c in epic.children:
                if c.in_estimate and c.created is not None:
                    by_key.setdefault(c.key, c)
        if not by_key:
            return
        try:
            for batch in _chunks(list(by_key), _CHANGELOG_BATCH_SIZE):
                result = self._jira.search_issues(
                    f"key in ({', '.join(batch)})",
                    maxResults=_CHANGELOG_BATCH_SIZE,
                    expand="changelog",
                    fields="created",
                    json_result=True,
                )
                for issue in result.get("issues", []):
                    child = by_key.get(issue.get("key", ""))
                    if child is None:
                        continue
                    histories = issue.get("changelog", {}).get("histories", [])
                    child.sp_history, child.done_history = self._parse_changelog(
                        histories, child.created, sp_field
                    )
        except Exception as exc:  # noqa: BLE001 - best-effort; trend falls back
            logger.warning("Changelog enrichment failed (trend falls back): %s", exc)

    @staticmethod
    def _parse_changelog(
        histories: list[dict[str, Any]], created: datetime | None, sp_field: str
    ) -> tuple[list[tuple[datetime, float | None]], list[tuple[datetime, bool]]]:
        """Reconstruct (sp_history, done_history) from a raw changelog.

        ``sp_history`` is the story-point estimate over time — only built when the
        changelog actually records an estimate change, with a synthesized initial
        entry (the value *before* the first change) at the issue's creation. Its
        last value is the current estimate. ``done_history`` is the resolution
        set/cleared timeline (``to`` non-null = resolved/done). Either is empty
        when the changelog carries no such event, so the caller falls back.
        """
        sp_changes: list[tuple[datetime, float | None, float | None]] = []
        done_changes: list[tuple[datetime, bool]] = []
        for h in histories:
            dt = JiraClient._parse_dt(h.get("created"))
            if dt is None:
                continue
            for it in h.get("items", []):
                fid = it.get("fieldId") or ""
                fname = it.get("field") or ""
                if fid == sp_field or fname == "Story Points":
                    sp_changes.append(
                        (dt, _to_float(it.get("toString")), _to_float(it.get("fromString")))
                    )
                elif fname == "resolution":
                    done_changes.append((dt, it.get("to") is not None))
        sp_changes.sort(key=lambda e: e[0])
        done_changes.sort(key=lambda e: e[0])

        sp_history: list[tuple[datetime, float | None]] = []
        if sp_changes and created is not None:
            sp_history = [(created, sp_changes[0][2])]
            sp_history += [(dt, to) for dt, to, _ in sp_changes]
        return sp_history, done_changes

    def _fetch_epics_chain(
        self,
        epic_keys: list[str],
        chain: list[HierarchyNode],
        *,
        sp_field: str,
        epic_link_field: str,
        start_date_field: str,
        due_date_field: str,
        sprint_field: str,
        timeline_start_field: str,
        timeline_end_field: str,
    ) -> dict[str, EpicData]:
        """Fetch epics and their descendants by walking a custom *chain*.

        BFS, one tier per chain node (node[0] is the epic tier itself):
        ``parent`` edges via a batched ``parent in (...)`` query; ``link`` edges
        by reading each frontier issue's ``issuelinks`` and batch-fetching the
        matching targets by key.  A cross-tier ``seen`` set and the chain length
        bound cycles and fan-out.  Each child records its ``hierarchy_parent_key``
        and ``issue_type_id``; :meth:`apply_hierarchy` then assigns display tiers
        and AND-resolves the show/estimate cascade.
        """
        if not self._jira or not epic_keys:
            return {}

        unique_keys = list(dict.fromkeys(epic_keys))
        fields = self._build_field_list(
            sp_field,
            epic_link_field,
            start_date_field,
            due_date_field,
            timeline_start_field,
            timeline_end_field,
            sprint_field,
        )
        if "issuelinks" not in fields:
            fields = [*fields, "issuelinks"]

        def parse_child(raw: Any) -> JiraIssue:
            issue = self._parse_child_issue(
                raw,
                sp_field,
                start_date_field,
                due_date_field,
                sprint_field,
                timeline_start_field,
                timeline_end_field,
            )
            issue.issue_type_id = self._issue_type_id_of(raw)
            return issue

        # Phase 0: the requested epics themselves (tier 0); keep their raw rows
        # as the first BFS frontier (link edges read their ``issuelinks``).
        epics: dict[str, EpicData] = {}
        frontier: list[Any] = []
        epic_set = set(unique_keys)
        for batch in _chunks(unique_keys, _COMBINED_BATCH_SIZE):
            csv = ", ".join(batch)
            rows = self._search_with_retry(
                f"key in ({csv})", max_results=False, fields=fields, use_post=True
            )
            for raw in rows:
                if raw.key in epic_set and raw.key not in epics:
                    epics[raw.key] = self._parse_epic_from_raw(
                        raw,
                        start_date_field,
                        due_date_field,
                        timeline_start_field,
                        timeline_end_field,
                    )
                    frontier.append(raw)

        children_by_epic: dict[str, list[JiraIssue]] = {k: [] for k in epics}
        owner_of: dict[str, str] = {k: k for k in epics}  # issue key -> epic key
        seen: set[str] = set(epics)
        resolver = HierarchyResolver(chain)

        # Walk the chain by display TIER, not node-by-node. Several issue types can
        # share a tier (Story + Bug at tier 1; Task + Sub-task at tier 2), and a
        # child tier maps MANY-TO-MANY onto the tier above (a Task hangs off any
        # tier-1 item via a link, a Sub-task off any of them via parent). The old
        # node-by-node walk reassigned `frontier` after every node, so a second
        # same-tier node (Bug) overwrote the first node's frontier (Story) with its
        # own — usually empty — children, and any deeper tier then broke on
        # `if not frontier`. Grouping by tier builds each tier's frontier from the
        # UNION of all preceding-tier matches, mirroring the customize dialog's
        # `_chain_tier_summaries`.
        child_tiers = sorted({n.display_tier for n in chain if n.display_tier > 0})
        for tier in child_tiers:
            if not frontier:
                break
            tier_nodes = [n for n in chain if n.display_tier == tier]
            next_frontier: list[Any] = []
            for raw_child, parent_key in self._chain_tier_children(
                frontier, tier_nodes, fields
            ):
                if raw_child.key in seen:
                    continue
                owner = owner_of.get(parent_key)
                if owner is None:
                    continue
                issue = parse_child(raw_child)
                # Keep only types that resolve to THIS tier (a parent-edge
                # `parent in (...)` query returns every child type; a deeper-tier
                # type pulled in here would otherwise leak in and advance under a
                # parent apply_hierarchy later drops). Mark `seen` only once a node
                # actually CLAIMS the child — else the tier-1 parent query would
                # consume a tier-2 Task and the tier-2 link query would then skip it.
                matched = resolver.node_of_issue(issue)
                if matched is None or matched.display_tier != tier:
                    continue
                seen.add(raw_child.key)
                issue.hierarchy_parent_key = parent_key
                children_by_epic[owner].append(issue)
                owner_of[raw_child.key] = owner
                next_frontier.append(raw_child)
            frontier = next_frontier

        for key, epic in epics.items():
            epic.children = children_by_epic[key]
            self.apply_hierarchy(epic, chain)
            self._fill_epic_dates_from_children(epic)
            logger.debug(
                "Assembled chain epic %s: %d children", key, len(epic.children)
            )
        return epics

    def _chain_tier_children(
        self, frontier: list[Any], nodes: list[HierarchyNode], fields: list[str]
    ) -> list[tuple[Any, str]]:
        """Fetch one tier's children for *frontier*, as ``(raw, parent_key)`` pairs.

        *nodes* are every chain node at this display tier (a tier maps many-to-many
        onto the tier above). All parent-edge nodes share a single
        ``parent in (...)`` query — it returns every child type regardless of node,
        so running it per-node would just duplicate it — while each link-edge node
        adds one ``issuelinks`` read. Rows are de-duplicated by issue key (first
        parent wins); the caller filters each row to the tier it resolves to.
        """
        out: list[tuple[Any, str]] = []
        seen_keys: set[str] = set()

        def _emit(raw: Any, parent_key: str) -> None:
            if raw.key not in seen_keys:
                seen_keys.add(raw.key)
                out.append((raw, parent_key))

        # Parent edges: one combined `parent in (frontier)` query for all of them.
        if any(n.edge == "parent" for n in nodes):
            parent_keys = [r.key for r in frontier]
            for batch in _chunks(parent_keys, _JQL_IN_BATCH_SIZE):
                csv = ", ".join(batch)
                rows = self._search_with_retry(
                    f"parent in ({csv}) ORDER BY created ASC",
                    max_results=False,
                    fields=fields,
                    use_post=True,
                )
                batch_set = set(batch)
                for raw in rows:
                    parent_key = self._parent_key_of(raw)
                    if parent_key in batch_set:
                        _emit(raw, parent_key)

        # Link edges: read each frontier issue's issuelinks once per link node.
        for node in nodes:
            if node.edge != "link":
                continue
            targets = _link_targets(frontier, node.link_types)
            if not targets:
                continue
            for batch in _chunks(list(targets), _JQL_IN_BATCH_SIZE):
                csv = ", ".join(batch)
                rows = self._search_with_retry(
                    f"key in ({csv})", max_results=False, fields=fields, use_post=True
                )
                for raw in rows:
                    parent_key = targets.get(raw.key)
                    if parent_key:
                        _emit(raw, parent_key)
        return out

    @staticmethod
    def apply_hierarchy(epic: EpicData, chain: list[HierarchyNode]) -> None:
        """Assign display tiers and resolve the show / estimate axes.

        Each child's ``display_tier`` comes from its chain node (matched by
        issue-type id, then name).

        Both axes **AND-cascade** up the ``hierarchy_parent_key`` ancestry plus
        the tier-0 (epic) node — a child is shown / estimated only when its own
        node *and* every ancestor node (and the epic root) are:

        * ``show`` (visibility) — a hidden parent hides its descendants, so they
          never render orphaned (a Sub-task whose Story parent is hidden drops
          off the timeline / nested rows with it).
        * ``in_estimate`` (metrics) — a parent dropped from the metrics also
          drops its descendants, so their weight isn't double-counted into an
          excluded parent.
        """
        resolver = HierarchyResolver(chain)
        node_of = resolver.node_of_issue
        root = next((n for n in chain if n.display_tier == 0), None)

        # Drop off-chain issue types (the Exclude pane, or types a parent-edge
        # tier's untyped `parent in (...)` query pulled in): with no matching
        # node they'd keep JiraIssue defaults (shown + estimated) and leak into
        # the report.
        epic.children = [c for c in epic.children if node_of(c) is not None]

        issues_by_key = {c.key: c for c in epic.children}
        for c in epic.children:
            node = node_of(c)
            if node is not None:
                c.display_tier = node.display_tier

        for c in epic.children:
            show = True
            est = True
            cur: JiraIssue | None = c
            guard = 0
            while cur is not None and guard <= len(epic.children):
                node = node_of(cur)
                if node is not None:
                    show = show and node.show
                    est = est and node.in_estimate
                pk = cur.hierarchy_parent_key
                cur = issues_by_key.get(pk) if pk else None
                guard += 1
            if root is not None:
                show = show and root.show
                est = est and root.in_estimate
            c.show = show
            c.in_estimate = est

    @staticmethod
    def _issue_type_id_of(raw: Any) -> str:
        """Return the issue-type id from a raw Jira row (``""`` when absent)."""
        it = JiraClient._get_raw_field(raw, "issuetype")
        if isinstance(it, dict):
            return str(it.get("id", ""))
        return str(getattr(it, "id", "")) if it is not None else ""

    @staticmethod
    def _issue_type_name_of(raw: Any) -> str:
        """Return the issue-type display name from a raw Jira row (``""`` absent)."""
        it = JiraClient._get_raw_field(raw, "issuetype")
        if isinstance(it, dict):
            return str(it.get("name", ""))
        return str(getattr(it, "name", "")) if it is not None else ""

    @staticmethod
    def _parent_key_of(raw: Any) -> str | None:
        """Return the ``parent`` field's issue key from a raw Jira row."""
        parent_obj = getattr(getattr(raw, "fields", None), "parent", None)
        if parent_obj is not None:
            key = getattr(parent_obj, "key", None)
            if key is None and isinstance(parent_obj, dict):
                key = parent_obj.get("key")
            if key:
                return key
        pf = JiraClient._get_raw_field(raw, "parent")
        if isinstance(pf, dict):
            return pf.get("key")
        return getattr(pf, "key", None) if pf is not None else None

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
