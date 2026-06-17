"""Main window with sidebar navigation, login overlay, and stacked panels."""

from __future__ import annotations

import logging

from PySide6.QtGui import QCloseEvent, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QHBoxLayout,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)
from qt_material import apply_stylesheet

from epic_report_generator.core import theming
from epic_report_generator.core.jira_client import JiraClient
from epic_report_generator.services.auth_manager import AuthManager
from epic_report_generator.services.config_manager import ConfigManager
from epic_report_generator.services.font_manager import FontManager
from epic_report_generator.ui.log_panel import LogPanel
from epic_report_generator.ui.login_panel import LoginPanel
from epic_report_generator.ui.report_panel import ReportPanel
from epic_report_generator.ui.settings_panel import SettingsPanel
from epic_report_generator.ui.styles import COMMON_THEME, dark_theme, light_theme
from epic_report_generator.ui.widgets import SidebarUserInfo

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    """Single-window application with login overlay and sidebar navigation."""

    def __init__(
        self,
        config: ConfigManager,
        auth: AuthManager,
        jira: JiraClient,
    ) -> None:
        super().__init__()
        self._config = config
        self._auth = auth
        self._jira = jira
        self._font_manager = FontManager(config)
        self._logged_in = False
        self._user_display_name = ""
        self._user_site_name = ""

        self.setWindowTitle("Epic Report Generator")
        self.setMinimumSize(960, 600)
        self.resize(1280, 900)

        self._build_ui()
        self._setup_shortcuts()
        self._apply_theme(self._config.get("theme", "light"))

    # -- UI construction ------------------------------------------------------

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Sidebar
        self._sidebar = QWidget()
        self._sidebar.setObjectName("sidebar")
        self._sidebar.setFixedWidth(200)
        sidebar_layout = QVBoxLayout(self._sidebar)
        sidebar_layout.setContentsMargins(8, 16, 8, 16)
        sidebar_layout.setSpacing(4)

        self._btn_group = QButtonGroup(self)
        self._btn_group.setExclusive(True)
        nav_items = [
            ("Report", 0),
            ("Settings", 1),
            ("Logs", 2),
        ]

        self._nav_buttons: list[QPushButton] = []
        for label, idx in nav_items:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setObjectName("sidebar")
            self._btn_group.addButton(btn, idx)
            sidebar_layout.addWidget(btn)
            self._nav_buttons.append(btn)

        sidebar_layout.addStretch()

        # Sidebar user info (hidden until login)
        self._sidebar_user_info = SidebarUserInfo()
        sidebar_layout.addWidget(self._sidebar_user_info)

        layout.addWidget(self._sidebar)

        # Two-level stacked widget:
        # outer_stack index 0 = login overlay
        # outer_stack index 1 = inner content (sidebar-driven panels)
        self._outer_stack = QStackedWidget()

        # Login panel (overlay)
        self._login_panel = LoginPanel(self._config, self._auth, self._jira)
        self._outer_stack.addWidget(self._login_panel)

        # Inner content
        self._inner_stack = QStackedWidget()
        self._report_panel = ReportPanel(self._config, self._jira, self._font_manager)
        self._settings_panel = SettingsPanel(
            self._config, self._auth, self._jira, self._font_manager
        )
        self._log_panel = LogPanel()

        self._inner_stack.addWidget(self._report_panel)  # index 0
        self._inner_stack.addWidget(self._settings_panel)  # index 1
        self._inner_stack.addWidget(self._log_panel)  # index 2

        self._outer_stack.addWidget(self._inner_stack)

        layout.addWidget(self._outer_stack)

        self._btn_group.idClicked.connect(self._inner_stack.setCurrentIndex)
        self._btn_group.button(0).setChecked(True)

        # Start in login overlay; sidebar disabled
        self._set_sidebar_enabled(False)
        self._outer_stack.setCurrentIndex(0)

        # Wire signals
        self._login_panel.login_state_changed.connect(self._on_login_state)
        self._login_panel.login_succeeded.connect(self._on_login_succeeded)
        self._login_panel.avatar_loaded.connect(self._on_avatar_loaded)
        self._settings_panel.theme_changed.connect(self._apply_theme)
        self._settings_panel.appearance_changed.connect(self._on_appearance_changed)
        self._settings_panel.logout_requested.connect(self._confirm_and_logout)
        self._sidebar_user_info.logout_requested.connect(self._confirm_and_logout)

        # Restore session AFTER signals are wired so login_state_changed is caught
        self._login_panel.try_restore_session()

    # -- shortcuts ------------------------------------------------------------

    def _setup_shortcuts(self) -> None:
        QShortcut(QKeySequence("Ctrl+G"), self, self._shortcut_generate)
        QShortcut(QKeySequence("Ctrl+E"), self, self._shortcut_export)
        QShortcut(QKeySequence("Ctrl+,"), self, lambda: self._go_to_panel(1))

    def _shortcut_generate(self) -> None:
        if self._logged_in:
            self._go_to_panel(0)
            self._report_panel.trigger_generate()

    def _shortcut_export(self) -> None:
        if self._logged_in:
            self._report_panel.trigger_export()

    # -- slots ----------------------------------------------------------------

    def _on_login_state(self, connected: bool) -> None:
        logger.info("Login state changed: connected=%s", connected)
        self._logged_in = connected
        if connected:
            self._set_sidebar_enabled(True)
            self._outer_stack.setCurrentIndex(1)
            self._settings_panel.refresh_connection_section()
            self._report_panel.config_panel.refresh_label_completions()
            self._go_to_panel(0)  # Report panel

    def _on_login_succeeded(self, display_name: str, site_name: str) -> None:
        """Populate sidebar user info after successful login."""
        self._user_display_name = display_name
        self._user_site_name = site_name
        self._sidebar_user_info.set_user(
            display_name,
            site_name,
            auth_method=self._auth.auth_method,
        )

    def _on_avatar_loaded(self, pixmap: QPixmap) -> None:
        """Update sidebar user info avatar once downloaded."""
        if pixmap and not pixmap.isNull():
            self._sidebar_user_info.set_user(
                self._user_display_name,
                self._user_site_name,
                pixmap,
                auth_method=self._auth.auth_method,
            )

    def _confirm_and_logout(self) -> None:
        """Confirm, clear the Jira session, and return to the login overlay.

        Single logout path shared by the sidebar and the settings panel.
        """
        reply = QMessageBox.question(
            self,
            "Confirm Logout",
            "This will clear your stored Jira session. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        logger.info("User confirmed logout")
        self._auth.logout()
        self._on_logout()

    def _on_logout(self) -> None:
        logger.info("User logged out, switching to login overlay")
        self._logged_in = False
        self._set_sidebar_enabled(False)
        self._outer_stack.setCurrentIndex(0)
        self._sidebar_user_info.clear()
        self._login_panel.reset_to_logged_out()
        self._settings_panel.refresh_connection_section()

    def _go_to_panel(self, index: int) -> None:
        if self._logged_in:
            self._outer_stack.setCurrentIndex(1)
        self._inner_stack.setCurrentIndex(index)
        btn = self._btn_group.button(index)
        if btn:
            btn.setChecked(True)

    def _set_sidebar_enabled(self, enabled: bool) -> None:
        """Enable or disable sidebar navigation buttons."""
        for btn in self._nav_buttons:
            btn.setEnabled(enabled)

    # -- cleanup --------------------------------------------------------------

    def closeEvent(self, event: QCloseEvent) -> None:
        """Shut down background threads before the window is destroyed."""
        self._login_panel.shutdown()
        self._report_panel.preview_panel.shutdown()
        self._report_panel.config_panel.shutdown()
        self._settings_panel.shutdown()
        super().closeEvent(event)

    # -- theming --------------------------------------------------------------

    # Material Design theme names
    _MATERIAL_THEMES = {"light": "light_blue.xml", "dark": "dark_blue.xml"}

    _MATERIAL_EXTRA = {
        "font_family": '"Segoe UI", "SF Pro Display", "Helvetica Neue", sans-serif',
        "density_scale": "-1",
    }

    def _apply_theme(self, theme: str) -> None:
        logger.info("Applying theme: %s", theme)
        is_dark = theme == "dark"

        # Apply Material Design base theme at the application level
        app = QApplication.instance()
        if not isinstance(app, QApplication):
            raise RuntimeError("No QApplication instance available")

        extra = dict(self._MATERIAL_EXTRA)

        # Custom font (NFR-05): register it with Qt and prepend it to the
        # qt-material font stack so the whole UI picks it up.
        font_family = self._font_manager.apply_to_app()
        if font_family:
            extra["font_family"] = (
                f'"{font_family}", ' + self._MATERIAL_EXTRA["font_family"]
            )

        # Custom accent (NFR-05): override the material primary colour family
        # and derive the overlay shades.  Empty/invalid → stock blue palette.
        accent = self._config.get("accent_color", "")
        shades = None
        if accent and theming.is_valid_hex(accent):
            extra.update(theming.qt_material_extra(accent, is_dark))
            shades = theming.qt_shades(accent, is_dark)

        theme_xml = self._MATERIAL_THEMES.get(theme, self._MATERIAL_THEMES["light"])
        apply_stylesheet(app, theme=theme_xml, extra=extra)

        # Patch the generated stylesheet to reduce QComboBox dropdown
        # spacing — the popup is a top-level widget so window-level
        # overrides cannot reach it.
        css = app.styleSheet()
        css += "\nQComboBox { padding-left: 4px; }\n"
        app.setStyleSheet(css)

        # Apply app-specific overrides at the window level:
        # structural (COMMON_THEME) first, then the color overrides.
        overlay = dark_theme(shades) if is_dark else light_theme(shades)
        self.setStyleSheet(COMMON_THEME + overlay)

        self._log_panel.set_dark(is_dark)
        self._report_panel.set_dark(is_dark)

    def _on_appearance_changed(self) -> None:
        """Re-apply the current theme after accent/font customization."""
        self._apply_theme(self._config.get("theme", "light"))
