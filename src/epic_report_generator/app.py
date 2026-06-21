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


def _set_windows_app_id() -> None:
    """Give Windows an explicit AppUserModelID for correct taskbar identity.

    Without this, Windows does not unify the running process with its pinned /
    Start-menu shortcut (duplicate taskbar buttons) and jump lists do not work.
    Must run before the first window is created. No-op off Windows; never raises.
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes

        from epic_report_generator.desktop import BUNDLE_ID

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(BUNDLE_ID)
    except Exception:  # pragma: no cover - best-effort cosmetic taskbar fix
        logger.debug("Could not set Windows AppUserModelID", exc_info=True)


def run_app(argv: list[str] | None = None) -> int:
    """Create and run the application, returning the exit code."""
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    logger.info("Starting Epic Report Generator")

    _set_windows_app_id()
    app = QApplication(argv or sys.argv)
    app.setApplicationName("Epic Report Generator")
    app.setOrganizationName("EpicReportGenerator")
    # Tie the window to its .desktop entry so the Linux dock/taskbar (esp.
    # GNOME/Wayland, which ignores setWindowIcon) shows the app icon instead of
    # a generic one. Sets the Wayland app_id / X11 WM_CLASS; must match the
    # .desktop basename and its StartupWMClass.
    from epic_report_generator.desktop import APP_ID

    app.setDesktopFileName(APP_ID)

    # macOS resolves the running app's Dock icon from the bundle
    # (CFBundleIconName -> Assets.car on Tahoe, CFBundleIconFile -> logo.icns on
    # 12-15). Calling setWindowIcon there OVERRIDES it at runtime with the
    # full-bleed logo.png — which is why the running app showed the wrong icon no
    # matter what icon the bundle carried. Set the window icon only on
    # Windows/Linux, where the taskbar reads it (Linux also via setDesktopFileName
    # for GNOME/Wayland, which ignores setWindowIcon).
    if sys.platform != "darwin":
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
