"""Application settings panel."""

from __future__ import annotations

import logging

from PySide6.QtCore import Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QColorDialog,
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from epic_report_generator.core import theming
from epic_report_generator.core.jira_client import JiraClient
from epic_report_generator.services.auth_manager import AuthManager
from epic_report_generator.services.config_manager import _DEFAULTS, ConfigManager
from epic_report_generator.services.font_manager import FontError, FontManager
from epic_report_generator.ui._threading import ThreadedTask
from epic_report_generator.ui.widgets import (
    LabelledField,
    make_scroll_content,
    no_scroll_wheel,
)

logger = logging.getLogger(__name__)


class SettingsPanel(QWidget):
    """Application settings: connection info, theme, defaults, logout."""

    theme_changed = Signal(str)  # "light" or "dark"
    appearance_changed = Signal()  # accent/font customization changed
    logout_requested = Signal()

    def __init__(
        self,
        config: ConfigManager,
        auth: AuthManager,
        jira: JiraClient,
        font_manager: FontManager,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._config = config
        self._auth = auth
        self._jira = jira
        self._font_manager = font_manager
        self._tasks = ThreadedTask(self)
        self._loading = False
        self._build_ui()
        self._load_values()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll, self._root = make_scroll_content(spacing=12)
        outer.addWidget(scroll)

        title = QLabel("Settings")
        title.setProperty("heading", "true")
        self._root.addWidget(title)

        # -- Auth-method-aware connection section -----------------------------
        self._build_connection_section()

        # Defaults
        defaults = QGroupBox("Default Values")
        defaults_layout = QVBoxLayout(defaults)
        self._default_title = LabelledField(
            "Default Report Title", placeholder="Epic Progress Report"
        )
        defaults_layout.addWidget(self._default_title)
        self._default_author = LabelledField(
            "Default Author Name", placeholder="Your name"
        )
        defaults_layout.addWidget(self._default_author)
        self._default_company = LabelledField(
            "Default Company Name", placeholder="ACME Corp"
        )
        defaults_layout.addWidget(self._default_company)
        self._root.addWidget(defaults)

        # Appearance: theme + accent colour + font (NFR-05)
        self._build_appearance_section()

        # Save + Cache + Logout
        save_btn = QPushButton("Save Settings")
        save_btn.clicked.connect(self._save)
        self._root.addWidget(save_btn)

        cache_btn = QPushButton("Invalidate Cache")
        cache_btn.setProperty("secondary", "true")
        cache_btn.setToolTip(
            "Clear cached Jira field metadata so it is re-fetched on next use"
        )
        cache_btn.clicked.connect(self._invalidate_cache)
        self._root.addWidget(cache_btn)

        logout_btn = QPushButton("Logout")
        logout_btn.setProperty("danger", "true")
        logout_btn.setToolTip("Clear stored session and disconnect")
        logout_btn.clicked.connect(self._logout)
        self._root.addWidget(logout_btn)

        self._root.addStretch()

    def _build_connection_section(self) -> None:
        """Build the auth-method-aware connection group box."""
        # -- API Token connection info ----------------------------------------
        self._api_token_group = QGroupBox("Connection")
        api_layout = QVBoxLayout(self._api_token_group)
        self._info_url = LabelledField("Jira URL")
        self._info_url.field.setReadOnly(True)
        api_layout.addWidget(self._info_url)
        self._info_email = LabelledField("Email")
        self._info_email.field.setReadOnly(True)
        api_layout.addWidget(self._info_email)
        self._root.addWidget(self._api_token_group)

        # -- OAuth App Configuration ------------------------------------------
        self._oauth_group = QGroupBox("OAuth App Configuration")
        oauth_layout = QVBoxLayout(self._oauth_group)
        self._client_id = LabelledField(
            "Client ID",
            tooltip="OAuth Client ID from Atlassian Developer Console",
        )
        oauth_layout.addWidget(self._client_id)
        self._client_secret = LabelledField(
            "Client Secret",
            tooltip="OAuth Client Secret from Atlassian Developer Console",
            password=True,
        )
        oauth_layout.addWidget(self._client_secret)

        port_lbl = QLabel("Callback Port")
        port_lbl.setProperty("subheading", "true")
        oauth_layout.addWidget(port_lbl)
        self._port_spin = QSpinBox()
        no_scroll_wheel(self._port_spin)
        self._port_spin.setRange(1024, 65535)
        self._port_spin.setValue(int(_DEFAULTS["callback_port"]))
        self._port_spin.setToolTip("Local port for the OAuth callback server")
        oauth_layout.addWidget(self._port_spin)
        self._root.addWidget(self._oauth_group)

        self._update_connection_visibility()

    def _update_connection_visibility(self) -> None:
        """Show/hide connection groups based on the active auth method."""
        method = self._auth.auth_method
        self._api_token_group.setVisible(method == "api_token")
        self._oauth_group.setVisible(method == "oauth")

    def refresh_connection_section(self) -> None:
        """Re-read auth method and update connection group visibility + values.

        Call this after login/logout to keep the settings panel in sync.
        """
        self._update_connection_visibility()
        self._load_connection_values()

    def _load_connection_values(self) -> None:
        """Populate connection fields from config."""
        self._info_url.text = self._config.get("jira_url", "")
        self._info_email.text = self._config.get("jira_email", "")
        self._client_id.text = self._config.get("client_id", "")
        self._client_secret.text = self._config.get("client_secret", "")
        self._port_spin.setValue(
            int(self._config.get("callback_port", _DEFAULTS["callback_port"]))
        )

    # -- appearance section ---------------------------------------------------

    def _build_appearance_section(self) -> None:
        """Build the Appearance group: theme, accent colour, font, reset."""
        group = QGroupBox("Appearance")
        layout = QVBoxLayout(group)

        # Theme
        theme_lbl = QLabel("Theme")
        theme_lbl.setProperty("subheading", "true")
        layout.addWidget(theme_lbl)
        self._theme_combo = QComboBox()
        no_scroll_wheel(self._theme_combo)
        self._theme_combo.addItems(["Light", "Dark"])
        self._theme_combo.currentTextChanged.connect(self._on_theme_changed)
        layout.addWidget(self._theme_combo)

        # Accent colour
        accent_lbl = QLabel("Accent Color")
        accent_lbl.setProperty("subheading", "true")
        layout.addWidget(accent_lbl)
        self._accent_btn = QPushButton()
        self._accent_btn.setToolTip(
            "Choose the accent colour for the app and the report"
        )
        self._accent_btn.clicked.connect(self._on_accent_clicked)
        layout.addWidget(self._accent_btn)

        # Font
        font_lbl = QLabel("Font")
        font_lbl.setProperty("subheading", "true")
        layout.addWidget(font_lbl)
        self._font_source_combo = QComboBox()
        no_scroll_wheel(self._font_source_combo)
        self._font_source_combo.addItem("Default", "")
        self._font_source_combo.addItem("From File…", "file")
        self._font_source_combo.addItem("Google Fonts", "google")
        self._font_source_combo.currentIndexChanged.connect(
            self._on_font_source_changed
        )
        layout.addWidget(self._font_source_combo)

        font_row = QHBoxLayout()
        self._font_input = QLineEdit()
        self._font_input.setPlaceholderText("e.g. Roboto")
        self._font_input.returnPressed.connect(self._on_font_apply)
        font_row.addWidget(self._font_input)
        self._font_browse_btn = QPushButton("Browse…")
        self._font_browse_btn.setProperty("secondary", "true")
        self._font_browse_btn.clicked.connect(self._on_font_browse)
        font_row.addWidget(self._font_browse_btn)
        self._font_apply_btn = QPushButton("Apply")
        self._font_apply_btn.setProperty("secondary", "true")
        self._font_apply_btn.clicked.connect(self._on_font_apply)
        font_row.addWidget(self._font_apply_btn)
        layout.addLayout(font_row)

        self._font_current_lbl = QLabel()
        self._font_current_lbl.setProperty("hint", "true")
        layout.addWidget(self._font_current_lbl)

        # Indeterminate busy bar shown while a Google font downloads.
        self._font_progress = QProgressBar()
        self._font_progress.setRange(0, 0)  # 0..0 → animated "busy" state
        self._font_progress.setTextVisible(False)
        self._font_progress.setVisible(False)
        layout.addWidget(self._font_progress)

        # Reset to defaults
        reset_btn = QPushButton("Reset Appearance to Defaults")
        reset_btn.setProperty("secondary", "true")
        reset_btn.setToolTip("Restore the default accent colour and font")
        reset_btn.clicked.connect(self._on_reset_appearance)
        layout.addWidget(reset_btn)

        self._root.addWidget(group)

    def _update_accent_swatch(self, hex_value: str) -> None:
        """Reflect *hex_value* (or default) on the accent swatch button."""
        display = (
            hex_value if theming.is_valid_hex(hex_value) else theming.DEFAULT_ACCENT
        )
        fg = theming.on_color(display)
        self._accent_btn.setText(hex_value.upper() if hex_value else "Default")
        self._accent_btn.setStyleSheet(
            f"background-color: {display}; color: {fg};"
            " border: 1px solid #888; border-radius: 4px; padding: 8px;"
        )

    def _update_font_controls(self, source: str) -> None:
        """Show the input/browse/apply controls appropriate for *source*."""
        is_file = source == "file"
        is_google = source == "google"
        self._font_input.setVisible(is_file or is_google)
        self._font_input.setReadOnly(is_file)
        self._font_browse_btn.setVisible(is_file)
        self._font_apply_btn.setVisible(is_google)
        if is_google:
            self._font_input.setPlaceholderText("e.g. Roboto")

    def _update_font_label(self, family: str) -> None:
        self._font_current_lbl.setText(f"Current font: {family or 'Default (Inter)'}")

    def _on_accent_clicked(self) -> None:
        current = self._config.get("accent_color", "") or theming.DEFAULT_ACCENT
        color = QColorDialog.getColor(QColor(current), self, "Choose Accent Color")
        if not color.isValid():
            return
        hex_value = color.name()  # "#rrggbb"
        logger.info("Accent colour set to %s", hex_value)
        self._config.set("accent_color", hex_value)
        self._update_accent_swatch(hex_value)
        self.appearance_changed.emit()

    def _on_font_source_changed(self, _index: int) -> None:
        if self._loading:
            return
        source = self._font_source_combo.currentData()
        self._update_font_controls(source)
        if source == "":
            logger.info("Font reset to default")
            self._config.update(
                {"font_source": "", "font_value": "", "font_family": ""}
            )
            self._font_input.clear()
            self._update_font_label("")
            self.appearance_changed.emit()

    def _on_font_browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Font File", "", "Fonts (*.ttf *.otf *.ttc)"
        )
        if not path:
            return
        try:
            family = self._font_manager.set_font_file(path)
        except FontError as exc:
            QMessageBox.warning(self, "Font Error", str(exc))
            return
        logger.info("Font file applied: %s (%s)", path, family)
        self._config.update(
            {"font_source": "file", "font_value": path, "font_family": family}
        )
        self._font_input.setText(path)
        self._update_font_label(family)
        self.appearance_changed.emit()

    def _on_font_apply(self) -> None:
        if self._font_source_combo.currentData() != "google":
            return
        name = self._font_input.text().strip()
        if not name:
            QMessageBox.warning(self, "Font Error", "Enter a Google Fonts family name.")
            return
        # Download off the GUI thread so the window stays responsive; the busy
        # bar animates meanwhile. Registration with Qt happens back on the main
        # thread in the result callback.
        self._set_font_busy(True, f"Downloading {name}…")
        self._tasks.start(
            lambda: self._font_manager.download_google_font(name),
            on_result=lambda res: self._on_font_downloaded(name, res),
            capture_exceptions=True,
        )

    def _on_font_downloaded(self, name: str, result: object) -> None:
        """Finish a Google-font download started on a background thread."""
        self._set_font_busy(False)
        if isinstance(result, FontError):
            QMessageBox.warning(self, "Font Error", str(result))
            return
        if isinstance(result, Exception):
            logger.warning("Google font download failed: %s", result)
            QMessageBox.warning(
                self,
                "Font Error",
                f"Could not download '{name}'. Check your internet connection.",
            )
            return
        # result is the cache directory; register on the GUI thread.
        family = self._font_manager.register_font_dir(str(result), fallback=name)
        logger.info("Google font applied: %s (%s)", name, family)
        self._config.update(
            {"font_source": "google", "font_value": name, "font_family": family}
        )
        self._update_font_label(family)
        self.appearance_changed.emit()

    def _set_font_busy(self, busy: bool, message: str = "") -> None:
        """Toggle the downloading state: disable inputs and animate the bar."""
        self._font_progress.setVisible(busy)
        self._font_apply_btn.setEnabled(not busy)
        self._font_browse_btn.setEnabled(not busy)
        self._font_input.setEnabled(not busy)
        self._font_source_combo.setEnabled(not busy)
        if busy and message:
            self._font_current_lbl.setText(message)

    def _on_reset_appearance(self) -> None:
        logger.info("Resetting appearance to defaults")
        self._config.update(
            {"accent_color": "", "font_source": "", "font_value": "", "font_family": ""}
        )
        self._loading = True
        self._font_source_combo.setCurrentIndex(0)
        self._loading = False
        self._update_accent_swatch("")
        self._update_font_controls("")
        self._font_input.clear()
        self._update_font_label("")
        self.appearance_changed.emit()

    def _load_appearance_values(self) -> None:
        """Populate the appearance controls from config without side effects."""
        self._loading = True
        try:
            self._update_accent_swatch(self._config.get("accent_color", ""))
            source = self._config.get("font_source", "")
            idx = self._font_source_combo.findData(source)
            self._font_source_combo.setCurrentIndex(idx if idx >= 0 else 0)
            self._update_font_controls(source)
            if source in ("file", "google"):
                self._font_input.setText(self._config.get("font_value", ""))
            self._update_font_label(self._config.get("font_family", ""))
        finally:
            self._loading = False

    def _load_values(self) -> None:
        self._load_connection_values()
        self._default_title.text = self._config.get(
            "default_title", _DEFAULTS["default_title"]
        )
        self._default_author.text = self._config.get(
            "default_author", _DEFAULTS["default_author"]
        )
        self._default_company.text = self._config.get(
            "default_company", _DEFAULTS["default_company"]
        )
        theme = self._config.get("theme", "light")
        self._theme_combo.setCurrentText(theme.capitalize())
        self._load_appearance_values()

    def _save(self) -> None:
        logger.info("Saving settings")
        values: dict = {
            "default_title": self._default_title.text.strip(),
            "default_author": self._default_author.text.strip(),
            "default_company": self._default_company.text.strip(),
        }
        # Only persist OAuth fields when using OAuth auth method
        if self._auth.auth_method == "oauth":
            values.update(
                {
                    "client_id": self._client_id.text.strip(),
                    "client_secret": self._client_secret.text.strip(),
                    "callback_port": self._port_spin.value(),
                }
            )
        self._config.update(values)
        logger.info("Settings saved successfully")
        QMessageBox.information(self, "Saved", "Settings saved successfully.")

    def _on_theme_changed(self, text: str) -> None:
        theme = text.lower()
        logger.info("Theme changed to %s", theme)
        self._config.set("theme", theme)
        self.theme_changed.emit(theme)

    def _invalidate_cache(self) -> None:
        """Clear all Jira client caches."""
        self._jira.invalidate_caches()
        logger.info("Caches invalidated")
        QMessageBox.information(self, "Cache Cleared", "Jira caches have been cleared.")

    def _logout(self) -> None:
        # Confirmation and the actual auth.logout() are owned by MainWindow so
        # both logout entry points (here and the sidebar) share one code path.
        self.logout_requested.emit()

    def shutdown(self) -> None:
        """Join any in-flight background task (e.g. a font download)."""
        self._tasks.wait()
