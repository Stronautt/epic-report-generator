"""Tests for epic_report_generator.services.update_checker.

The checker is stateless and does no caching: ``fetch()`` is the only call and
either returns a definitive :class:`UpdateInfo` (including a 404 "no published
release" → no update) or ``None`` for a transient failure the caller ignores.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
import requests

from epic_report_generator.services.update_checker import (
    RELEASES_URL,
    UpdateChecker,
    UpdateInfo,
    is_newer,
)


class _FakeResponse:
    """Minimal stand-in for a ``requests`` response."""

    def __init__(
        self, payload: dict, status: int = 200, *, json_error: bool = False
    ) -> None:
        self._payload = payload
        self.status_code = status
        self._json_error = json_error

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"status {self.status_code}")

    def json(self) -> dict:
        if self._json_error:
            raise ValueError("bad json")
        return self._payload


def _patch_get(response=None, side_effect=None):
    return patch(
        "epic_report_generator.services.update_checker.requests.get",
        return_value=response,
        side_effect=side_effect,
    )


class TestIsNewer:
    @pytest.mark.parametrize(
        ("latest", "current", "expected"),
        [
            ("1.2.0", "1.1.0", True),
            ("1.2.0", "1.2.0", False),
            ("v1.2.0", "1.2.0", False),  # leading v stripped
            ("1.1", "1.1.0", False),  # length-tolerant equality
            ("2.0.0", "1.9.9", True),
            ("1.0.0", "1.0.1", False),
            ("1.2.0-rc1", "1.1.0", True),  # pre-release core compared
            ("", "1.0.0", False),  # empty never newer
            ("not-a-version", "1.0.0", False),  # unparseable never newer
            ("1.10.0", "1.9.0", True),  # numeric, not lexicographic
        ],
    )
    def test_is_newer(self, latest: str, current: str, expected: bool) -> None:
        assert is_newer(latest, current) is expected


class TestFetch:
    def test_newer_release_reports_update(self) -> None:
        checker = UpdateChecker("1.0.0")
        payload = {"tag_name": "v1.2.0", "html_url": "https://example.com/r/1.2.0"}
        with _patch_get(_FakeResponse(payload)) as mock_get:
            info = checker.fetch()
        mock_get.assert_called_once()
        assert info == UpdateInfo("1.0.0", "1.2.0", "https://example.com/r/1.2.0", True)

    def test_same_version_reports_no_update(self) -> None:
        checker = UpdateChecker("1.2.0")
        with _patch_get(_FakeResponse({"tag_name": "1.2.0", "html_url": "u"})):
            info = checker.fetch()
        assert info is not None
        assert info.update_available is False

    def test_missing_html_url_falls_back_to_releases_url(self) -> None:
        checker = UpdateChecker("1.0.0")
        with _patch_get(_FakeResponse({"tag_name": "1.3.0"})):
            info = checker.fetch()
        assert info is not None
        assert info.html_url == RELEASES_URL

    def test_empty_tag_is_no_update(self) -> None:
        checker = UpdateChecker("1.0.0")
        with _patch_get(_FakeResponse({"html_url": "u"})):
            info = checker.fetch()
        assert info == UpdateInfo("1.0.0", "", RELEASES_URL, False)

    def test_404_no_published_release_is_definitive_no_update(self) -> None:
        # The repo has only pre-releases/drafts → releases/latest 404s. That is
        # "nothing to update to", NOT a failure: a definitive no-update result.
        checker = UpdateChecker("1.0.0")
        with _patch_get(_FakeResponse({}, status=404)) as mock_get:
            info = checker.fetch()
        mock_get.assert_called_once()
        assert info == UpdateInfo("1.0.0", "", RELEASES_URL, False)

    def test_connection_error_is_transient_none(self) -> None:
        checker = UpdateChecker("1.0.0")
        with _patch_get(side_effect=requests.ConnectionError("boom")):
            assert checker.fetch() is None

    def test_timeout_is_transient_none(self) -> None:
        checker = UpdateChecker("1.0.0")
        with _patch_get(side_effect=requests.Timeout("slow")):
            assert checker.fetch() is None

    def test_server_error_is_transient_none(self) -> None:
        checker = UpdateChecker("1.0.0")
        with _patch_get(_FakeResponse({}, status=500)):
            assert checker.fetch() is None

    def test_bad_json_is_transient_none(self) -> None:
        checker = UpdateChecker("1.0.0")
        with _patch_get(_FakeResponse({}, json_error=True)):
            assert checker.fetch() is None
