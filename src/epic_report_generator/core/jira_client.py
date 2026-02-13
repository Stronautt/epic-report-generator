"""Jira Cloud API client using the ``jira`` library."""

from __future__ import annotations

import logging
import time
from typing import Any

import requests as _requests
from jira import JIRA, JIRAError

from epic_report_generator.core.data_models import EpicData, JiraIssue
from epic_report_generator.services.auth_manager import AuthManager

logger = logging.getLogger(__name__)

_MAX_RESULTS = 100
_MAX_RETRIES = 4
_BACKOFF_BASE = 1.0  # seconds


class JiraClient:
    """High-level wrapper around the ``jira`` library for Epic data."""

    def __init__(self, auth: AuthManager) -> None:
        self._auth = auth
        self._jira: JIRA | None = None

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
                logger.debug("Basic auth returned 401, trying scoped token via cloud API")
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
                self._auth.jira_url, self._auth.jira_email, api_token,
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
        self, epic_key: str, sp_field: str = "story_points", epic_link_field: str = "customfield_10014"
    ) -> EpicData | None:
        """Fetch a single Epic and all its child issues.

        Returns ``None`` if the Epic cannot be found.
        """
        if not self._jira:
            return None

        logger.info("Fetching epic %s", epic_key)
        try:
            issue = self._search_with_retry(f"key = {epic_key}", max_results=1)
            if not issue:
                logger.warning("Epic %s not found", epic_key)
                return None
            raw = issue[0]
        except JIRAError as exc:
            logger.error("Failed to fetch epic %s: %s", epic_key, exc)
            return None

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
            fix_versions=[
                v.name
                for v in (getattr(fields, "fixVersions", []) or [])
            ],
        )

        # Fetch children with pagination
        epic.children = self._fetch_children(epic_key, sp_field, epic_link_field)
        logger.info(
            "Fetched epic %s: %d children, status=%s",
            epic_key, len(epic.children), epic.status,
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
        """Return all Jira fields (for custom field mapping UI)."""
        if not self._jira:
            return []
        logger.debug("Fetching Jira fields")
        try:
            result = [
                {"id": f["id"], "name": f["name"], "custom": f.get("custom", False)}
                for f in self._jira.fields()
            ]
            logger.info("Fetched %d Jira fields", len(result))
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

    # -- internals ------------------------------------------------------------

    def _fetch_children(
        self, epic_key: str, sp_field: str, epic_link_field: str
    ) -> list[JiraIssue]:
        jql = f'"{epic_link_field}" = {epic_key} ORDER BY created ASC'
        logger.debug("Fetching children for %s (field=%s)", epic_key, epic_link_field)
        children: list[JiraIssue] = []
        start = 0

        while True:
            results = self._search_with_retry(jql, start_at=start, max_results=_MAX_RESULTS)
            if not results:
                break
            for raw in results:
                fields: Any = raw.fields
                sp_val = getattr(fields, sp_field, None)
                if sp_val is None:
                    # Try common custom field names
                    sp_val = getattr(fields, "customfield_10016", None)

                children.append(
                    JiraIssue(
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
                    )
                )
            if len(results) < _MAX_RESULTS:
                break
            start += _MAX_RESULTS

        return children

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
    def _parse_dt(value: Any) -> "datetime | None":
        if value is None:
            return None
        from dateutil.parser import parse as dt_parse

        try:
            return dt_parse(str(value))
        except (ValueError, TypeError):
            return None
