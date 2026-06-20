"""Tests for the privacy-policy document, its URL constant, and the sidebar link.

Covers:

* ``PRIVACY_POLICY_URL`` points at the published privacy-policy gist.
* ``MainWindow`` renders an always-visible "Privacy Policy" sidebar link that
  carries the URL and re-tints (muted) across a theme switch.
* ``docs/privacy-policy.md`` exists and covers the required headings, the contact
  email, and the local-first / no-analytics / Jira-own-instance language.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtWidgets import QLabel

from epic_report_generator.services.update_checker import PRIVACY_POLICY_URL
from epic_report_generator.ui.main_window import MainWindow

_POLICY_PATH = (
    Path(__file__).resolve().parent.parent / "docs" / "privacy-policy.md"
)

_GIST_URL = "https://gist.github.com/Stronautt/ff26be326e9736d3652d377e0dab25ba"


# ── URL constant ────────────────────────────────────────────────────────────


def test_privacy_url_is_the_gist() -> None:
    assert PRIVACY_POLICY_URL == _GIST_URL


# ── Sidebar link ────────────────────────────────────────────────────────────


def _bare_window(qtbot, muted: str = "#aeb1b8") -> MainWindow:
    """A MainWindow with only the privacy-link collaborators wired up.

    Mirrors test_main_window_updates: ``__new__`` plus the few attributes
    ``_render_privacy_link`` touches, so there is no full-window construction.
    """
    w = MainWindow.__new__(MainWindow)
    link = QLabel()
    qtbot.addWidget(link)
    w._privacy_link = link
    w._muted_hex = muted
    return w


def test_sidebar_privacy_link_carries_url(qtbot) -> None:
    w = _bare_window(qtbot)
    w._render_privacy_link()

    assert PRIVACY_POLICY_URL in w._privacy_link.text()
    assert "Privacy Policy" in w._privacy_link.text()


def test_sidebar_privacy_link_retints_on_theme_switch(qtbot) -> None:
    w = _bare_window(qtbot, muted="#aeb1b8")
    w._render_privacy_link()
    light_html = w._privacy_link.text()

    w._muted_hex = "#65686c"
    w._render_privacy_link()
    dark_html = w._privacy_link.text()

    # The URL survives the re-tint; the inline muted colour changes with theme.
    assert PRIVACY_POLICY_URL in light_html
    assert PRIVACY_POLICY_URL in dark_html
    assert light_html != dark_html


# ── Policy document ─────────────────────────────────────────────────────────


def test_policy_file_exists() -> None:
    assert _POLICY_PATH.is_file()


@pytest.mark.parametrize(
    "heading",
    [
        "## Overview",
        "## Information You Provide",
        "## How Your Data Is Used",
        "## Data Storage",
        "## Network Connections",
        "## Data Sharing",
        "## Mac App Store Builds",
        "## Permissions",
        "## Children's Privacy",
        "## Changes",
        "## Contact",
    ],
)
def test_policy_has_required_heading(heading: str) -> None:
    text = _POLICY_PATH.read_text(encoding="utf-8")
    # "## Changes" matches "## Changes to This Policy"; the rest match verbatim.
    assert heading in text


def test_policy_has_effective_date() -> None:
    text = _POLICY_PATH.read_text(encoding="utf-8")
    assert "Effective Date:" in text
    assert "2026-06-20" in text


def test_policy_has_contact_email() -> None:
    text = _POLICY_PATH.read_text(encoding="utf-8")
    assert "pavlo.o.hrytsenko@gmail.com" in text


def test_policy_states_no_third_party_analytics() -> None:
    text = _POLICY_PATH.read_text(encoding="utf-8").lower()
    assert "analytics" in text
    # No third-party analytics / tracking SDKs.
    assert "tracking" in text or "third-party analytics" in text


def test_policy_describes_jira_own_instance() -> None:
    text = _POLICY_PATH.read_text(encoding="utf-8").lower()
    # Data flows only to the user's own Jira/Atlassian, not the developer.
    assert "your own jira" in text
    assert "local-first" in text
    assert "developer never receives" in text
