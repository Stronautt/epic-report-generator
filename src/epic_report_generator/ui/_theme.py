"""Shared theme resolution: map a configured theme to a concrete light/dark."""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

logger = logging.getLogger(__name__)


def resolve_theme(theme: str) -> str:
    """Resolve a configured theme value to a concrete ``"light"`` or ``"dark"``.

    ``"dark"`` and ``"light"`` map to themselves; ``"system"`` follows the OS
    colour scheme via Qt's ``QStyleHints`` (Qt 6.5+), falling back to ``"light"``
    whenever the scheme can't be determined — an older Qt with no
    ``colorScheme()``, no running ``QApplication``, or an ``Unknown`` scheme.
    Any unrecognised value also falls back to ``"light"`` (and is logged).
    """
    if theme == "dark":
        return "dark"
    if theme == "system":
        app = QApplication.instance()
        hints = app.styleHints() if app is not None else None
        try:
            if hints is not None and hints.colorScheme() == Qt.ColorScheme.Dark:
                return "dark"
        except AttributeError:  # Qt < 6.5: no colorScheme()/ColorScheme enum
            pass
        return "light"
    if theme != "light":
        logger.warning("Unknown theme %r; falling back to light", theme)
    return "light"
