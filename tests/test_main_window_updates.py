"""Update-check decision-logic tests for MainWindow.

These exercise ``_check_for_updates`` / ``_on_update_fetched`` directly on a
lightweight ``MainWindow.__new__`` instance — only the few attributes those
methods touch are wired up (a real ``QLabel`` plus a mocked worker), so there is
no full-window construction, thread, network, or event loop.

Behaviour under test (no caching): every check spawns a fresh fetch; a definitive
result shows/hides the link; a transient failure (``None``) is ignored so the
link never flaps.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from PySide6.QtWidgets import QLabel

from epic_report_generator.services.update_checker import (
    RELEASES_URL,
    UpdateChecker,
    UpdateInfo,
)
from epic_report_generator.ui.main_window import MainWindow


@pytest.fixture
def win(qtbot):
    """A MainWindow with only the update-check collaborators wired up."""
    w = MainWindow.__new__(MainWindow)
    label = QLabel()
    qtbot.addWidget(label)
    w._update_link = label
    w._update_info = None
    w._accent_hex = "#2979ff"
    w._update_url = RELEASES_URL
    w._update_task = MagicMock()
    w._update_timer = None
    w._update_checker = UpdateChecker("1.0.1")
    return w


class TestCheckForUpdates:
    def test_spawns_worker_with_fetch(self, win: MainWindow) -> None:
        win._check_for_updates()
        win._update_task.start.assert_called_once()
        # The worker runs the network fetch.
        assert win._update_task.start.call_args.args[0] == win._update_checker.fetch

    def test_disabled_install_is_a_safe_noop(self, win: MainWindow) -> None:
        # Store install leaves _update_checker / _update_task as None.
        win._update_checker = None
        win._update_task = None
        win._check_for_updates()  # must not raise
        assert win._update_link.isHidden()


class TestApplyFetchResult:
    def test_update_available_shows_link(self, win: MainWindow) -> None:
        win._on_update_fetched(UpdateInfo("1.0.1", "2.0.0", "https://gh/rel", True))
        assert not win._update_link.isHidden()
        assert win._update_url == "https://gh/rel"
        assert win._update_info.latest_version == "2.0.0"

    def test_no_update_result_hides_link(self, win: MainWindow) -> None:
        # First an update is shown...
        win._on_update_fetched(UpdateInfo("1.0.1", "2.0.0", "https://gh/rel", True))
        assert not win._update_link.isHidden()
        # ...then a definitive "no update" (e.g. a 404 / up-to-date) hides it.
        win._on_update_fetched(UpdateInfo("1.0.1", "", RELEASES_URL, False))
        assert win._update_link.isHidden()

    def test_transient_failure_does_not_flap_a_shown_link(
        self, win: MainWindow
    ) -> None:
        win._on_update_fetched(UpdateInfo("1.0.1", "2.0.0", "https://gh/rel", True))
        assert not win._update_link.isHidden()
        win._on_update_fetched(None)  # transient (offline/5xx) — leave as-is
        assert not win._update_link.isHidden()

    def test_transient_failure_leaves_hidden_link_hidden(
        self, win: MainWindow
    ) -> None:
        win._on_update_fetched(None)
        assert win._update_link.isHidden()
        assert win._update_info is None
