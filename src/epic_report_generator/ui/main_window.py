"""Main window with sidebar navigation, login overlay, and stacked panels."""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import (
    QCloseEvent,
    QKeySequence,
    QPixmap,
    QResizeEvent,
    QShortcut,
)
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)
from qt_material import apply_stylesheet

from epic_report_generator import __version__
from epic_report_generator.core import theming
from epic_report_generator.core.jira_client import JiraClient
from epic_report_generator.services import install_source
from epic_report_generator.services.auth_manager import AuthManager
from epic_report_generator.services.config_manager import ConfigManager
from epic_report_generator.services.font_manager import FontManager
from epic_report_generator.services.update_checker import (
    RELEASES_URL,
    UpdateChecker,
    UpdateInfo,
)
from epic_report_generator.ui._threading import ThreadedTask
from epic_report_generator.ui.animations import fade_in, pulse, stop_pulse
from epic_report_generator.ui.help_panel import HelpPanel
from epic_report_generator.ui.log_panel import LogPanel
from epic_report_generator.ui.login_panel import LoginPanel
from epic_report_generator.ui.report_panel import ReportPanel
from epic_report_generator.ui.settings_panel import SettingsPanel
from epic_report_generator.ui.styles import COMMON_THEME, dark_theme, light_theme
from epic_report_generator.ui.widgets import SidebarUserInfo

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    """Single-window application with login overlay and sidebar navigation."""

    # Window-size safety net (see _safe_window_size / resizeEvent). A restored
    # size is clamped to at least the minimum usable layout and at most the
    # current screen, so a stale/oversized saved value can never strand the
    # window off-screen (title bar + resize handles unreachable) or shrink it
    # below the point where it can be operated — an unrecoverable state.
    _MIN_WINDOW_WIDTH = 480
    _MIN_WINDOW_HEIGHT = 300
    _DEFAULT_WINDOW_WIDTH = 1280
    _DEFAULT_WINDOW_HEIGHT = 900
    # Coalesce the burst of resizeEvents during a drag into a single disk write.
    _GEOMETRY_SAVE_DEBOUNCE_MS = 400
    # Class default so a resizeEvent fired before __init__ completes (e.g. from
    # setMinimumSize) is a safe no-op rather than an AttributeError.
    _geometry_restored: bool = False

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
        # Update-notification state (see _setup_update_check). The accent hex is
        # refreshed by _apply_theme and embedded in the hyperlink's inline style.
        self._update_info: UpdateInfo | None = None
        self._accent_hex = theming.DEFAULT_ACCENT

        self.setWindowTitle("Epic Report Generator")
        self.setMinimumSize(self._MIN_WINDOW_WIDTH, self._MIN_WINDOW_HEIGHT)

        # Remember the user's last window size across launches. Resizes are
        # debounced (a drag fires many resizeEvents) into one config write; the
        # restore runs before show() and is clamped by _safe_window_size.
        self._geometry_save_timer = QTimer(self)
        self._geometry_save_timer.setSingleShot(True)
        self._geometry_save_timer.setInterval(self._GEOMETRY_SAVE_DEBOUNCE_MS)
        self._geometry_save_timer.timeout.connect(self._persist_window_size)
        self._restore_window_size()

        self._build_ui()
        self._setup_shortcuts()
        self._apply_theme(self._config.get("theme", "light"))
        self._setup_update_check()

        # Restore the previous session *after* the window is shown and the
        # event loop is running, so the UI paints immediately instead of
        # blocking on keyring + the Jira handshake.  The restore itself runs
        # on a worker thread (see LoginPanel.try_restore_session).
        QTimer.singleShot(0, self._login_panel.try_restore_session)

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
            ("User Guide", 2),
            ("Logs", 3),
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

        # Footer pinned to the bottom of the sidebar: version above a
        # subtle author signature, grouped as one tight block.
        footer = QWidget()
        footer.setObjectName("sidebarFooter")
        footer_layout = QVBoxLayout(footer)
        footer_layout.setContentsMargins(0, 0, 0, 0)
        footer_layout.setSpacing(1)

        self._version_label = QLabel(f"v{__version__}")
        self._version_label.setObjectName("sidebarVersion")
        footer_layout.addWidget(self._version_label)

        # Update CTA, directly below the version — a blinking accent hyperlink
        # (not a button) hidden until the hourly check finds a newer GitHub
        # release. Rich text so the <a> reads as a real link (accent colour +
        # underline come from its inline style); clicking opens the latest-
        # release page in the browser (setOpenExternalLinks). See
        # _render_update_link for the show/blink logic.
        self._update_link = QLabel()
        self._update_link.setObjectName("sidebarUpdateLink")
        self._update_link.setTextFormat(Qt.TextFormat.RichText)
        self._update_link.setOpenExternalLinks(True)
        self._update_link.setCursor(Qt.CursorShape.PointingHandCursor)
        self._update_link.setToolTip("A newer version is available — click to download")
        self._update_link.hide()
        self._update_url = RELEASES_URL
        footer_layout.addWidget(self._update_link)

        self._copyright_label = QLabel("© Olha & Pavlo")
        self._copyright_label.setObjectName("sidebarCopyright")
        footer_layout.addWidget(self._copyright_label)

        sidebar_layout.addWidget(footer)

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
        self._help_panel = HelpPanel(self._config)
        self._log_panel = LogPanel()

        self._inner_stack.addWidget(self._report_panel)  # index 0
        self._inner_stack.addWidget(self._settings_panel)  # index 1
        self._inner_stack.addWidget(self._help_panel)  # index 2
        self._inner_stack.addWidget(self._log_panel)  # index 3

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
        # Session restore is scheduled from __init__ (deferred to after show())
        # so login_state_changed is still caught here — signals are wired above.

        # Fade the destination widget in on every panel switch (sidebar nav and
        # login↔content). Connected last, after the initial indices are set, so
        # the first paint isn't animated.
        self._inner_stack.currentChanged.connect(self._fade_inner)
        self._outer_stack.currentChanged.connect(self._fade_outer)

    # -- transitions ----------------------------------------------------------

    def _fade_inner(self, _index: int) -> None:
        """Fade in the newly selected sidebar panel."""
        widget = self._inner_stack.currentWidget()
        if widget is not None:
            fade_in(widget)

    def _fade_outer(self, _index: int) -> None:
        """Fade in the login overlay or the main content on switch."""
        widget = self._outer_stack.currentWidget()
        if widget is not None:
            fade_in(widget)

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

    # -- window geometry ------------------------------------------------------

    def _restore_window_size(self) -> None:
        """Restore the last saved window size, clamped to a safe range."""
        width = self._config.get("window_width", self._DEFAULT_WINDOW_WIDTH)
        height = self._config.get("window_height", self._DEFAULT_WINDOW_HEIGHT)
        width, height = self._safe_window_size(width, height)
        self.resize(width, height)
        self._geometry_restored = True

    def _safe_window_size(self, width: object, height: object) -> tuple[int, int]:
        """Clamp a (possibly stale or corrupt) size to a usable, on-screen range.

        The safety net against an unrecoverable window: the lower bound is the
        minimum usable layout, the upper bound is the current screen's available
        area. A non-numeric or otherwise unusable value falls back to the
        defaults. This catches both a saved size larger than the screen (e.g.
        after moving from a big external monitor to a laptop, which would leave
        the title bar and resize handles off-screen) and one too small to
        operate.
        """
        try:
            safe_width = int(width)
            safe_height = int(height)
        except (TypeError, ValueError):
            return self._DEFAULT_WINDOW_WIDTH, self._DEFAULT_WINDOW_HEIGHT

        safe_width = max(safe_width, self._MIN_WINDOW_WIDTH)
        safe_height = max(safe_height, self._MIN_WINDOW_HEIGHT)

        screen = QApplication.primaryScreen()
        if screen is not None:
            available = screen.availableGeometry()
            safe_width = min(safe_width, available.width())
            safe_height = min(safe_height, available.height())

        return safe_width, safe_height

    def _persist_window_size(self) -> None:
        """Save the current windowed size as the size to restore next launch."""
        size = self.size()
        self._config.update(
            {"window_width": size.width(), "window_height": size.height()}
        )

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        """Remember genuine user resizes (debounced); ignore programmatic ones.

        Only spontaneous, windowed resizes are persisted: the programmatic
        restore in ``__init__`` and any maximized/fullscreen state are skipped so
        the remembered value is always a real, restorable windowed size.
        """
        super().resizeEvent(event)
        if (
            self._geometry_restored
            and event.spontaneous()
            and not self.isMaximized()
            and not self.isFullScreen()
        ):
            self._geometry_save_timer.start()

    # -- cleanup --------------------------------------------------------------

    def closeEvent(self, event: QCloseEvent) -> None:
        """Shut down background threads before the window is destroyed."""
        # Flush a window size that was resized within the debounce window just
        # before closing, so the very last size is still remembered.
        if self._geometry_save_timer.isActive():
            self._geometry_save_timer.stop()
            self._persist_window_size()
        if self._update_timer is not None:
            self._update_timer.stop()
        if self._update_task is not None:
            self._update_task.wait()
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

        # The accent hex used by the update hyperlink's inline <a> colour — the
        # same shade the QSS @ACCENT@ token resolves to, so the link matches the
        # rest of the accented UI under both stock and custom accents.
        self._accent_hex = (
            shades or theming.qt_shades(theming.DEFAULT_ACCENT, is_dark)
        )["accent"]

        theme_xml = self._MATERIAL_THEMES.get(theme, self._MATERIAL_THEMES["light"])

        # ``apply_stylesheet`` re-polishes the entire widget tree (~0.5s on a
        # built-out window).  Skip the whole re-apply when nothing that affects
        # appearance changed — e.g. re-selecting the current accent/font.
        signature = (theme_xml, accent, extra["font_family"])
        if signature == getattr(self, "_applied_appearance", None):
            logger.debug("Appearance unchanged; skipping theme re-apply")
            return
        self._applied_appearance = signature

        apply_stylesheet(app, theme=theme_xml, extra=extra)

        # Apply app-specific overrides at the window level:
        # structural (COMMON_THEME) first, then the color overrides.  The
        # QComboBox padding tweak rides along with the window overlay (it
        # cascades to every child combo) instead of forcing a second
        # app-wide ``setStyleSheet`` that would re-polish the whole widget
        # tree — a ~0.5s hit at startup on a fully-built window.
        overlay = dark_theme(shades) if is_dark else light_theme(shades)
        self.setStyleSheet(
            COMMON_THEME + overlay + "\nQComboBox { padding-left: 4px; }\n"
        )

        self._log_panel.set_dark(is_dark)
        self._report_panel.set_dark(is_dark)
        self._help_panel.set_dark(is_dark)

        # Re-tint the update hyperlink (if shown) for the new accent — its colour
        # lives in inline HTML, so a QSS re-apply alone wouldn't update it.
        self._render_update_link()

    def _on_appearance_changed(self) -> None:
        """Re-apply the current theme after accent/font customization."""
        self._apply_theme(self._config.get("theme", "light"))

    # -- update check ---------------------------------------------------------

    # Poll GitHub for a newer release once an hour. Each check hits GitHub
    # fresh — there is no local cache.
    _UPDATE_CHECK_INTERVAL_MS = 60 * 60 * 1000
    # Hold the first network check until well after the window has painted and
    # session restore is under way, so the background poll never adds to startup
    # latency. (The work is already off-thread; this just keeps t=0 quiet.)
    _UPDATE_CHECK_STARTUP_DELAY_MS = 3000

    def _setup_update_check(self) -> None:
        """Check for updates shortly after launch, then hourly — never blocking.

        There is no cache: the only network call (``UpdateChecker.fetch``) runs
        on a worker thread, kicked off via a delayed timer after the UI is
        interactive, so every launch reflects GitHub's current state.

        Skipped entirely for store installs (Mac App Store / Microsoft Store /
        Snap / Flatpak), which manage updates themselves — no checker, no timer,
        no link. The attributes stay ``None`` so the lifecycle hooks no-op.
        """
        self._update_checker: UpdateChecker | None = None
        self._update_task: ThreadedTask | None = None
        self._update_timer: QTimer | None = None

        store = install_source.store_source()
        if store:
            logger.info("Installed via %s — self-update check disabled", store)
            return

        self._update_checker = UpdateChecker(__version__)
        self._update_task = ThreadedTask(self)
        self._update_timer = QTimer(self)
        self._update_timer.setInterval(self._UPDATE_CHECK_INTERVAL_MS)
        self._update_timer.timeout.connect(self._check_for_updates)

        # Defer the first check so it never competes with the first paint /
        # session restore, then repeat hourly. Each call hits GitHub fresh.
        QTimer.singleShot(self._UPDATE_CHECK_STARTUP_DELAY_MS, self._check_for_updates)
        self._update_timer.start()

    def _check_for_updates(self) -> None:
        """Run a fresh update check on a worker thread (no caching, no blocking)."""
        if self._update_checker is None or self._update_task is None:
            return  # store install — update checks disabled
        self._update_task.start(
            self._update_checker.fetch,
            self._on_update_fetched,
            capture_exceptions=True,
        )

    def _on_update_fetched(self, info: object) -> None:
        """Apply a finished fetch on the main thread.

        A definitive :class:`UpdateInfo` updates the UI — showing the link when
        an update is available, hiding it otherwise (incl. the 404 "no published
        release" case). A transient failure (``None`` / an exception) is ignored
        so the link doesn't flap; the next check (hourly or next launch) retries.
        """
        if isinstance(info, UpdateInfo):
            self._apply_update_info(info)

    def _apply_update_info(self, info: UpdateInfo) -> None:
        """Store a finished update check and refresh the hyperlink."""
        self._update_info = info
        self._render_update_link()

    def _render_update_link(self) -> None:
        """Show (and slowly blink) or hide the Update hyperlink for the state.

        The link text carries the accent colour and the release URL inline, so
        this is also the single place that re-tints it after an accent change.
        The blink is started only on the hidden→shown transition so a theme
        re-apply doesn't restart it.
        """
        info = self._update_info
        if info is not None and info.update_available and info.html_url:
            self._update_url = info.html_url
            self._update_link.setText(
                f'<a href="{info.html_url}" '
                f'style="color:{self._accent_hex}; text-decoration:underline;">'
                f"Update available</a>"
            )
            self._update_link.setToolTip(
                f"Version {info.latest_version} is available — click to download"
            )
            if self._update_link.isHidden():
                self._update_link.show()
                # Slow, gentle pulse so it draws the eye without nagging.
                pulse(self._update_link, duration=2200, min_opacity=0.2)
        elif not self._update_link.isHidden():
            stop_pulse(self._update_link)
            self._update_link.hide()
