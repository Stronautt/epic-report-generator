"""QApplication setup and main window launch."""

from __future__ import annotations

import logging
import signal
import sys

from PySide6.QtCore import QEvent, QObject, Qt, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QAbstractButton,
    QAbstractSpinBox,
    QApplication,
    QComboBox,
    QTabBar,
)

from epic_report_generator.core.jira_client import JiraClient
from epic_report_generator.services.auth_manager import AuthManager
from epic_report_generator.services.config_manager import ConfigManager
from epic_report_generator.ui.main_window import MainWindow

logger = logging.getLogger(__name__)

_POINTER_TYPES = (QAbstractButton, QComboBox, QAbstractSpinBox, QTabBar)

# Interval for the signal-wakeup timer that lets Python process SIGINT/SIGTERM
_SIGNAL_WAKEUP_INTERVAL_MS = 200


class _CursorEventFilter(QObject):
    """Application-wide event filter that sets PointingHandCursor on controls.

    Two event types are handled so every interactive control is covered:

    * ``ChildAdded`` catches widgets reparented into the hierarchy (the common
      case for hand-built panels and custom dialog buttons).
    * ``Polish`` catches controls created inside a widget's own C++ constructor
      whose ``ChildAdded`` never passes through this filter — most notably the
      ``Ok``/``Cancel`` buttons of ``QDialogButtonBox`` and ``QMessageBox``,
      which would otherwise keep the default arrow cursor inside modal dialogs.
    """

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:  # noqa: N802
        event_type = event.type()
        if event_type == QEvent.Type.ChildAdded:
            self._apply_pointer(event.child())  # type: ignore[union-attr]
        elif event_type == QEvent.Type.Polish:
            self._apply_pointer(obj)
        return False

    @staticmethod
    def _apply_pointer(obj: QObject) -> None:
        """Set the pointing-hand cursor on interactive controls, once each."""
        if isinstance(obj, _POINTER_TYPES) and not obj.testAttribute(
            Qt.WidgetAttribute.WA_SetCursor
        ):
            obj.setCursor(Qt.CursorShape.PointingHandCursor)


def run_app(argv: list[str] | None = None) -> int:
    """Create and run the application, returning the exit code."""
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    logger.info("Starting Epic Report Generator")

    app = QApplication(argv or sys.argv)
    app.setApplicationName("Epic Report Generator")
    app.setOrganizationName("EpicReportGenerator")

    try:
        from epic_report_generator.resources_util import get_resource_path

        app.setWindowIcon(QIcon(str(get_resource_path("logo.png"))))
    except (FileNotFoundError, ModuleNotFoundError):
        logger.warning("logo.png not found; running without a window icon")

    _install_signal_handlers(app)
    app.installEventFilter(_CursorEventFilter(app))

    # Shared services
    config = ConfigManager()
    auth = AuthManager(config)
    jira = JiraClient(auth)

    logger.debug("Services initialised, launching main window")
    window = MainWindow(config, auth, jira)
    window.show()

    return app.exec()


def _install_signal_handlers(app: QApplication) -> None:
    """Allow SIGINT/SIGTERM to gracefully quit the Qt event loop.

    Python signal handlers only run between bytecode instructions, but
    the Qt event loop blocks in C.  A periodic zero-length timer forces
    Python to regain control so the signal handler can fire.
    """

    def _shutdown(signum: int, _frame: object) -> None:
        sig_name = signal.Signals(signum).name
        logger.info("Received %s, shutting down…", sig_name)
        app.closeAllWindows()
        app.quit()

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    timer = QTimer(app)
    timer.setInterval(_SIGNAL_WAKEUP_INTERVAL_MS)
    timer.timeout.connect(lambda: None)
    timer.start()
