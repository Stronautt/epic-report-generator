"""Tests for the shared theme resolver (ui._theme.resolve_theme)."""

from __future__ import annotations

import pytest
from PySide6.QtCore import Qt

from epic_report_generator.ui import _theme
from epic_report_generator.ui._theme import resolve_theme

_HAS_COLOR_SCHEME = hasattr(Qt, "ColorScheme")


def _fake_qapplication(scheme: object) -> type:
    """A QApplication stand-in whose styleHints().colorScheme() returns *scheme*."""

    class _Hints:
        def colorScheme(self) -> object:  # noqa: N802 - mirrors the Qt API
            return scheme

    class _App:
        def styleHints(self) -> _Hints:
            return _Hints()

    class _FakeQApplication:
        @staticmethod
        def instance() -> _App:
            return _App()

    return _FakeQApplication


class TestResolveTheme:
    """Configured theme values map to a concrete light/dark."""

    def test_light_passthrough(self) -> None:
        assert resolve_theme("light") == "light"

    def test_dark_passthrough(self) -> None:
        assert resolve_theme("dark") == "dark"

    def test_unknown_value_falls_back_to_light(self) -> None:
        assert resolve_theme("nonsense") == "light"

    def test_system_falls_back_to_light_without_qapplication(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # No running QApplication → scheme is undeterminable → light.
        monkeypatch.setattr(_theme.QApplication, "instance", staticmethod(lambda: None))
        assert resolve_theme("system") == "light"

    @pytest.mark.skipif(not _HAS_COLOR_SCHEME, reason="Qt < 6.5 has no ColorScheme")
    def test_system_resolves_dark_when_os_is_dark(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            _theme, "QApplication", _fake_qapplication(Qt.ColorScheme.Dark)
        )
        assert resolve_theme("system") == "dark"

    @pytest.mark.skipif(not _HAS_COLOR_SCHEME, reason="Qt < 6.5 has no ColorScheme")
    def test_system_resolves_light_when_os_is_light(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            _theme, "QApplication", _fake_qapplication(Qt.ColorScheme.Light)
        )
        assert resolve_theme("system") == "light"

    @pytest.mark.skipif(not _HAS_COLOR_SCHEME, reason="Qt < 6.5 has no ColorScheme")
    def test_system_falls_back_to_light_on_unknown_scheme(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            _theme, "QApplication", _fake_qapplication(Qt.ColorScheme.Unknown)
        )
        assert resolve_theme("system") == "light"
