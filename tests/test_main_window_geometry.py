"""Window-size persistence + safety-net tests for MainWindow.

These exercise the geometry helpers directly on a lightweight
``MainWindow.__new__`` instance — ``_safe_window_size`` only reads class-level
constants and ``QApplication.primaryScreen()``, so no full-window construction,
thread, or event loop is needed. ``primaryScreen`` is monkeypatched so the
upper-bound clamp is deterministic regardless of the test host's display.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QRect

from epic_report_generator.ui.main_window import MainWindow


@pytest.fixture
def win() -> MainWindow:
    """A bare MainWindow instance — no Qt C++ window, just the Python methods."""
    return MainWindow.__new__(MainWindow)


def _fake_screen(width: int, height: int) -> MagicMock:
    screen = MagicMock()
    screen.availableGeometry.return_value = QRect(0, 0, width, height)
    return screen


@pytest.fixture
def big_screen(monkeypatch) -> None:
    """Patch the primary screen large enough that the upper bound never bites."""
    monkeypatch.setattr(
        "epic_report_generator.ui.main_window.QApplication.primaryScreen",
        lambda: _fake_screen(10000, 10000),
    )


class TestSafeWindowSize:
    def test_in_range_size_passes_through(self, win: MainWindow, big_screen) -> None:
        assert win._safe_window_size(1280, 900) == (1280, 900)

    def test_too_small_is_raised_to_minimum(self, win: MainWindow, big_screen) -> None:
        assert win._safe_window_size(100, 50) == (
            MainWindow._MIN_WINDOW_WIDTH,
            MainWindow._MIN_WINDOW_HEIGHT,
        )

    def test_too_large_is_clamped_to_screen(
        self, win: MainWindow, monkeypatch
    ) -> None:
        # Simulates restoring a size saved on a bigger external monitor onto a
        # smaller laptop screen — the window must fit, not float off-screen.
        monkeypatch.setattr(
            "epic_report_generator.ui.main_window.QApplication.primaryScreen",
            lambda: _fake_screen(1366, 768),
        )
        assert win._safe_window_size(5000, 4000) == (1366, 768)

    def test_garbage_falls_back_to_defaults(
        self, win: MainWindow, big_screen
    ) -> None:
        assert win._safe_window_size("oops", None) == (
            MainWindow._DEFAULT_WINDOW_WIDTH,
            MainWindow._DEFAULT_WINDOW_HEIGHT,
        )

    def test_no_screen_still_enforces_minimum(
        self, win: MainWindow, monkeypatch
    ) -> None:
        monkeypatch.setattr(
            "epic_report_generator.ui.main_window.QApplication.primaryScreen",
            lambda: None,
        )
        assert win._safe_window_size(10, 10) == (
            MainWindow._MIN_WINDOW_WIDTH,
            MainWindow._MIN_WINDOW_HEIGHT,
        )


class TestPersistWindowSize:
    def test_saves_current_size_to_config(self, win: MainWindow) -> None:
        win._config = MagicMock()
        win.size = MagicMock(return_value=MagicMock(width=lambda: 1100, height=lambda: 720))
        win._persist_window_size()
        win._config.update.assert_called_once_with(
            {"window_width": 1100, "window_height": 720}
        )
