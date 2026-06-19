"""Check GitHub for a newer published release.

Queries the GitHub Releases API for the project's latest *full* release (the
``releases/latest`` endpoint excludes pre-releases and drafts) and compares its
tag with the running version. There is **no persistent cache**: every check hits
the network fresh, so a stale result can never resurface across restarts, and at
~1 call/launch + 1 call/hour we stay far inside GitHub's unauthenticated 60/hour
per-IP limit.

`fetch()` is the single networked call and the **worker-thread** entry point —
it holds no shared state and never raises. It distinguishes two outcomes:

* a **definitive** answer → an :class:`UpdateInfo` (HTTP 200 with a tag, or a
  404 meaning *no published full release exists* — e.g. only pre-releases — which
  is reported as "no update", ``update_available=False``); and
* a **transient** failure (timeout, connection error, 5xx, rate-limit, bad JSON)
  → ``None``, so the caller can leave the current UI untouched rather than
  flapping or showing wrong data.

Every request carries an explicit connect+read timeout; a missing one lets a
stale keep-alive socket hang forever (see the Jira client, same failure mode).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

import requests

logger = logging.getLogger(__name__)

# Repository the installers are published from. The owner/name pair builds the
# API endpoint; ``RELEASES_URL`` is the stable "latest release" page the Update
# link points to (GitHub redirects it to the newest release).
GITHUB_OWNER = "Stronautt"
GITHUB_REPO = "epic-report-generator"
_LATEST_RELEASE_API = (
    f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
)
RELEASES_URL = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"

# GitHub requires a User-Agent; the API version header pins the response shape.
_HEADERS = {
    "User-Agent": GITHUB_OWNER,
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}
# (connect, read) seconds — bounded so a hung socket can't block the worker.
_TIMEOUT = (5, 10)


def _parse_version(value: str) -> tuple[int, ...]:
    """Parse a version/tag string into a comparable tuple of integers.

    Strips a leading ``v``/``V`` and any pre-release/build metadata
    (``1.2.0-rc1`` → ``(1, 2, 0)``), then reads the leading run of numeric
    dot-separated components. Returns ``()`` for an unparseable value.
    """
    core = re.split(r"[-+ ]", value.strip().lstrip("vV"), maxsplit=1)[0]
    parts: list[int] = []
    for chunk in core.split("."):
        match = re.match(r"\d+", chunk)
        if not match:
            break
        parts.append(int(match.group()))
    return tuple(parts)


def is_newer(latest: str, current: str) -> bool:
    """Return True when *latest* is a strictly higher version than *current*.

    Comparison is numeric and length-tolerant (``1.1`` vs ``1.1.0`` are equal).
    An unparseable or empty *latest* never counts as newer, so a malformed tag
    can't surface a spurious update prompt.
    """
    latest_parts = _parse_version(latest)
    if not latest_parts:
        return False
    current_parts = _parse_version(current)
    width = max(len(latest_parts), len(current_parts))
    latest_parts += (0,) * (width - len(latest_parts))
    current_parts += (0,) * (width - len(current_parts))
    return latest_parts > current_parts


@dataclass(frozen=True)
class UpdateInfo:
    """A definitive update-check outcome.

    *update_available* is computed against the *current* running version.
    ``latest_version == ""`` means "no published full release", which is a valid
    "no update" answer (e.g. the repo has only pre-releases).
    """

    current_version: str
    latest_version: str
    html_url: str
    update_available: bool


class UpdateChecker:
    """Fetches the latest GitHub release and compares it to the running version."""

    def __init__(self, current_version: str) -> None:
        self._current = current_version

    def _no_update(self) -> UpdateInfo:
        """A definitive "you are up to date" result."""
        return UpdateInfo(self._current, "", RELEASES_URL, False)

    def fetch(self) -> UpdateInfo | None:
        """Query GitHub for the latest release; the only networked call.

        Runs on a **worker thread** and never raises. Returns an
        :class:`UpdateInfo` for a definitive answer (including a 404, which means
        no published full release → no update) or ``None`` for a transient
        failure the caller should ignore (leaving the UI as-is).
        """
        try:
            response = requests.get(
                _LATEST_RELEASE_API, headers=_HEADERS, timeout=_TIMEOUT
            )
        except requests.RequestException as exc:
            logger.warning("Update check failed (network): %s", exc)
            return None

        # 404 = the repo has no published *full* release (only pre-releases or
        # drafts). That is a definitive "nothing to update to", not a failure.
        if response.status_code == 404:
            logger.info("Update check: no published release — treating as up to date")
            return self._no_update()

        try:
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            logger.warning("Update check failed (response): %s", exc)
            return None

        # Normalise a leading "v" (``v1.2.0`` → ``1.2.0``) so the tag reads
        # cleanly; comparison strips it anyway. An empty/missing tag → no update.
        latest = str(payload.get("tag_name") or "").strip().lstrip("vV")
        if not latest:
            return self._no_update()
        html_url = str(payload.get("html_url") or "").strip() or RELEASES_URL
        logger.info("Update check: latest=%s current=%s", latest, self._current)
        return UpdateInfo(
            current_version=self._current,
            latest_version=latest,
            html_url=html_url,
            update_available=is_newer(latest, self._current),
        )
