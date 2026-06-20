"""Tests for LoginPanel — OAuth tab gating in managed-store (MAS) builds.

MAS v1 is API-Token-only: the OAuth tab (and its signal wiring) must be absent
in store builds, present otherwise, and every session-restore / reset path must
tolerate the missing OAuth widgets without raising.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from epic_report_generator.ui import login_panel as login_panel_module
from epic_report_generator.ui.login_panel import LoginPanel


def _tab_titles(panel: LoginPanel) -> list[str]:
    tabs = panel._tabs
    return [tabs.tabText(i) for i in range(tabs.count())]


def _make_mocks() -> tuple[MagicMock, MagicMock, MagicMock]:
    """Config/auth/jira mocks that keep ``try_restore_session`` thread-free."""
    config = MagicMock()
    config.get.return_value = ""  # no saved url/email/oauth creds
    auth = MagicMock()
    auth.auth_method = ""  # neither "api_token" nor "oauth" → no worker started
    auth.is_configured = False
    jira = MagicMock()
    return config, auth, jira


@pytest.fixture
def store_build(monkeypatch) -> None:
    monkeypatch.setattr(
        login_panel_module.install_source, "is_store_install", lambda: True
    )


@pytest.fixture
def direct_build(monkeypatch) -> None:
    monkeypatch.setattr(
        login_panel_module.install_source, "is_store_install", lambda: False
    )


def test_store_build_hides_oauth_tab(qtbot, store_build) -> None:
    panel = LoginPanel(*_make_mocks())
    qtbot.addWidget(panel)

    assert panel._oauth_enabled is False
    titles = _tab_titles(panel)
    assert len(titles) == 1
    assert titles[0] == "API Token (Recommended)"
    assert "OAuth 2.0" not in titles
    # OAuth-only widgets were never built.
    assert not hasattr(panel, "_login_btn")
    assert not hasattr(panel, "_client_id_field")
    assert not hasattr(panel, "_setup_section")


def test_direct_build_shows_both_tabs(qtbot, direct_build) -> None:
    panel = LoginPanel(*_make_mocks())
    qtbot.addWidget(panel)

    assert panel._oauth_enabled is True
    titles = _tab_titles(panel)
    assert titles == ["API Token (Recommended)", "OAuth 2.0"]
    # API-Token tab remains index 0.
    assert panel._tabs.tabText(0) == "API Token (Recommended)"
    # OAuth-only widgets exist in the non-store build.
    assert hasattr(panel, "_login_btn")
    assert hasattr(panel, "_client_id_field")


def test_store_build_restore_session_does_not_raise(qtbot, store_build) -> None:
    panel = LoginPanel(*_make_mocks())
    qtbot.addWidget(panel)

    # No OAuth widgets: restore must not touch _client_id_field etc.
    panel.try_restore_session()


def test_store_build_restore_oauth_method_falls_through(qtbot, store_build) -> None:
    """An "oauth" auth_method carried over into a store build is ignored, not crashed."""
    config, auth, jira = _make_mocks()
    auth.auth_method = "oauth"
    auth.is_configured = True
    panel = LoginPanel(config, auth, jira)
    qtbot.addWidget(panel)

    # The oauth branch is gated on _oauth_enabled, so this must be a no-op (no
    # _setup_section / _login_btn access, no worker started).
    panel.try_restore_session()
    jira.connect.assert_not_called()


def test_store_build_reset_to_logged_out_does_not_raise(qtbot, store_build) -> None:
    panel = LoginPanel(*_make_mocks())
    qtbot.addWidget(panel)

    panel.reset_to_logged_out()  # must not touch OAuth-only widgets


def test_store_build_tab_selection_tolerates_single_tab(qtbot, store_build) -> None:
    panel = LoginPanel(*_make_mocks())
    qtbot.addWidget(panel)

    # Restore handlers may request index 1 (OAuth); a one-tab widget ignores it.
    panel._tabs.setCurrentIndex(1)
    assert panel._tabs.currentIndex() == 0
