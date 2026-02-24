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
    QGroupBox,
    QTabBar,
)

from epic_report_generator.core.jira_client import JiraClient
from epic_report_generator.services.auth_manager import AuthManager
from epic_report_generator.services.config_manager import ConfigManager
from epic_report_generator.ui.main_window import MainWindow

logger = logging.getLogger(__name__)

# Widget types that should show a pointing-hand cursor
_POINTER_TYPES = (QAbstractButton, QComboBox, QAbstractSpinBox, QTabBar, QGroupBox)


class _JsonCursorFilter(QObject):
    """Application-wide event filter that sets PointingHandCursor on controls."""

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:  # noqa: N802
        if event.type() == QEvent.Type.ChildAdded:
            child = event.child()  # type: ignore[union-attr]
            if isinstance(child, _POINTER_TYPES) and not child.testAttribute(
                Qt.WidgetAttribute.WA_SetCursor
            ):
                child.setCursor(Qt.CursorShape.PointingHandCursor)
        return False


def run_app(argv: list[str] | None = None) -> int:
    """Create and run the application, returning the exit code."""
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    # Silence noisy matplotlib font manager debug logs
    logging.getLogger("matplotlib.font_manager").setLevel(logging.WARNING)

    logger.info("Starting Epic Report Generator")

    app = QApplication(argv or sys.argv)
    app.setApplicationName("Epic Report Generator")
    app.setOrganizationName("EpicReportGenerator")

    try:
        from epic_report_generator.resources_util import get_resource_path

        app.setWindowIcon(QIcon(str(get_resource_path("logo.png"))))
    except FileNotFoundError:
        logger.warning("logo.png not found; running without a window icon")

    _install_signal_handlers(app)
    app.installEventFilter(_JsonCursorFilter(app))

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

    # Wake up the Python interpreter periodically so signals are processed
    timer = QTimer(app)
    timer.setInterval(200)
    timer.timeout.connect(lambda: None)
    timer.start()
