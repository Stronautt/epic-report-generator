"""Log panel — displays application log output in real time."""

from __future__ import annotations

import logging
import sys
from collections import deque

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QTextCharFormat
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class _QtLogHandler(logging.Handler, QObject):
    """Logging handler that emits a Qt signal for each log record.

    Inherits from both ``logging.Handler`` and ``QObject`` so it can
    live in the logging system while emitting cross-thread signals.
    """

    message_logged = Signal(str, int)  # formatted message, log level

    def __init__(self) -> None:
        logging.Handler.__init__(self)
        QObject.__init__(self)
        self.setFormatter(
            logging.Formatter(
                "%(asctime)s [%(levelname)s] %(name)s: %(message)s", datefmt="%H:%M:%S"
            )
        )

    def emit(self, record: logging.LogRecord) -> None:  # type: ignore[override]
        """Format the record and emit via the Qt signal."""
        try:
            msg = self.format(record)
            self.message_logged.emit(msg, record.levelno)
        except Exception:
            self.handleError(record)


_LEVEL_COLORS: dict[int, str] = {
    logging.DEBUG: "#8C9CB8",
    logging.INFO: "#172B4D",
    logging.WARNING: "#FF8B00",
    logging.ERROR: "#DE350B",
    logging.CRITICAL: "#DE350B",
}

_LEVEL_COLORS_DARK: dict[int, str] = {
    logging.DEBUG: "#6B778C",
    logging.INFO: "#B8C7E0",
    logging.WARNING: "#FFAB00",
    logging.ERROR: "#FF5630",
    logging.CRITICAL: "#FF5630",
}

_MAX_BUFFER = 5000


def _make_fmt_cache(colors: dict[int, str]) -> dict[int, QTextCharFormat]:
    """Build a mapping of log level → QTextCharFormat from a color palette."""
    cache: dict[int, QTextCharFormat] = {}
    for level, color in colors.items():
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color))
        if level >= logging.WARNING:
            fmt.setFontWeight(QFont.Weight.Bold)
        cache[level] = fmt
    return cache


_FMT_LIGHT = _make_fmt_cache(_LEVEL_COLORS)
_FMT_DARK = _make_fmt_cache(_LEVEL_COLORS_DARK)


class LogPanel(QWidget):
    """Panel that displays live application log output."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._dark = False
        self._buffer: deque[tuple[str, int]] = deque(maxlen=_MAX_BUFFER)
        self._active_levels: set[int] = {
            logging.DEBUG,
            logging.INFO,
            logging.WARNING,
            logging.ERROR,
            logging.CRITICAL,
        }
        # Batch buffer for high-frequency log messages
        self._pending_messages: list[tuple[str, int]] = []
        self._build_ui()

        self._flush_timer = QTimer(self)
        self._flush_timer.setInterval(50)
        self._flush_timer.timeout.connect(self._flush_pending)

        # Install the Qt log handler on the root logger
        self._handler = _QtLogHandler()
        self._handler.setLevel(logging.DEBUG)
        self._handler.message_logged.connect(self._on_message)
        logging.getLogger().addHandler(self._handler)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 32, 32, 32)
        root.setSpacing(12)

        # Header row
        header = QHBoxLayout()
        title = QLabel("Logs")
        title.setProperty("heading", "true")
        header.addWidget(title)
        header.addStretch()

        self._clear_btn = QPushButton("Clear")
        self._clear_btn.setProperty("secondary", "true")
        self._clear_btn.clicked.connect(self._clear)
        header.addWidget(self._clear_btn)
        root.addLayout(header)

        # Filter row
        filter_row = QHBoxLayout()
        filter_label = QLabel("Filter:")
        filter_label.setProperty("subheading", "true")
        filter_row.addWidget(filter_label)

        self._filter_btns: dict[int, QPushButton] = {}
        for level, label in [
            (logging.DEBUG, "Debug"),
            (logging.INFO, "Info"),
            (logging.WARNING, "Warning"),
            (logging.ERROR, "Error"),
        ]:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setChecked(True)
            btn.setObjectName("logFilterBtn")
            btn.setProperty("level", label.lower())
            btn.clicked.connect(
                lambda checked, lvl=level: self._on_filter_toggled(lvl, checked)
            )
            self._filter_btns[level] = btn
            filter_row.addWidget(btn)

        filter_row.addStretch()
        root.addLayout(filter_row)

        # Log output
        self._log_view = QPlainTextEdit()
        self._log_view.setReadOnly(True)
        self._log_view.setMaximumBlockCount(_MAX_BUFFER)
        self._log_view.setFont(
            QFont("Consolas", 10) if sys.platform == "win32" else QFont("Monospace", 10)
        )
        self._log_view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        root.addWidget(self._log_view)

    def set_dark(self, dark: bool) -> None:
        """Switch between light/dark colour palettes for log text."""
        self._dark = dark

    def _on_message(self, text: str, level: int) -> None:
        """Store the message and queue it for batched display."""
        self._buffer.append((text, level))
        if self._is_visible(level):
            self._pending_messages.append((text, level))
            if not self._flush_timer.isActive():
                self._flush_timer.start()

    def _write_messages_to_view(
        self, messages: list[tuple[str, int]], *, clear: bool = False
    ) -> None:
        """Append ``(text, level)`` messages to the view with per-level formatting."""
        fmt_cache = _FMT_DARK if self._dark else _FMT_LIGHT
        default_fmt = fmt_cache[logging.INFO]

        self._log_view.setUpdatesEnabled(False)
        if clear:
            self._log_view.clear()
        cursor = self._log_view.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        for text, level in messages:
            fmt = fmt_cache.get(level, default_fmt)
            cursor.insertText(text + "\n", fmt)
        self._log_view.setTextCursor(cursor)
        self._log_view.setUpdatesEnabled(True)
        self._log_view.ensureCursorVisible()

    def _flush_pending(self) -> None:
        """Flush all pending messages to the view in a single batch."""
        if not self._pending_messages:
            self._flush_timer.stop()
            return
        messages = self._pending_messages
        self._pending_messages = []
        self._flush_timer.stop()
        self._write_messages_to_view(messages)

    def _on_filter_toggled(self, level: int, checked: bool) -> None:
        """Update active levels and rebuild the visible log."""
        # CRITICAL follows ERROR
        if checked:
            self._active_levels.add(level)
            if level == logging.ERROR:
                self._active_levels.add(logging.CRITICAL)
        else:
            self._active_levels.discard(level)
            if level == logging.ERROR:
                self._active_levels.discard(logging.CRITICAL)
        self._rebuild_view()

    def _is_visible(self, level: int) -> bool:
        return level in self._active_levels

    def _rebuild_view(self) -> None:
        """Re-render all buffered messages with the current filter."""
        visible = [(t, lvl) for t, lvl in self._buffer if self._is_visible(lvl)]
        self._write_messages_to_view(visible, clear=True)

    def _clear(self) -> None:
        self._buffer.clear()
        self._pending_messages.clear()
        self._flush_timer.stop()
        self._log_view.clear()
