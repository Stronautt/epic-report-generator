"""Application settings panel."""

from __future__ import annotations

import logging
from typing import Any

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QGroupBox,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from epic_report_generator.services.auth_manager import AuthManager
from epic_report_generator.services.config_manager import ConfigManager
from epic_report_generator.ui.widgets import LabelledField

logger = logging.getLogger(__name__)


class SettingsPanel(QWidget):
    """Application settings: connection info, theme, defaults, logout."""

    theme_changed = Signal(str)  # "light" or "dark"
    logged_out = Signal()

    def __init__(
        self,
        config: ConfigManager,
        auth: AuthManager,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._config = config
        self._auth = auth
        self._build_ui()
        self._load_values()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        outer.addWidget(scroll)

        content = QWidget()
        scroll.setWidget(content)
        self._root = QVBoxLayout(content)
        self._root.setContentsMargins(32, 32, 32, 32)
        self._root.setSpacing(12)

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

        # Theme
        theme_group = QGroupBox("Appearance")
        theme_layout = QVBoxLayout(theme_group)
        theme_lbl = QLabel("Theme")
        theme_lbl.setProperty("subheading", "true")
        theme_layout.addWidget(theme_lbl)
        self._theme_combo = QComboBox()
        self._theme_combo.addItems(["Light", "Dark"])
        self._theme_combo.currentTextChanged.connect(self._on_theme_changed)
        theme_layout.addWidget(self._theme_combo)
        self._root.addWidget(theme_group)

        # Save + Logout
        save_btn = QPushButton("Save Settings")
        save_btn.clicked.connect(self._save)
        self._root.addWidget(save_btn)

        logout_btn = QPushButton("Logout")
        logout_btn.setProperty("danger", "true")
        logout_btn.setToolTip("Clear stored session and disconnect")
        logout_btn.clicked.connect(self._logout)
        self._root.addWidget(logout_btn)

        self._root.addStretch()

    def _build_connection_section(self) -> None:
        """Build the auth-method-aware connection group box."""
        method = self._auth.auth_method

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
        self._port_spin.setRange(1024, 65535)
        self._port_spin.setValue(18492)
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
        self._port_spin.setValue(int(self._config.get("callback_port", 18492)))

    def _load_values(self) -> None:
        self._load_connection_values()
        self._default_title.text = self._config.get("default_title", "Epic Progress Report")
        self._default_author.text = self._config.get("default_author", "")
        self._default_company.text = self._config.get("default_company", "")
        theme = self._config.get("theme", "light")
        self._theme_combo.setCurrentText(theme.capitalize())

    def _save(self) -> None:
        logger.info("Saving settings")
        values: dict[str, Any] = {
            "default_title": self._default_title.text.strip(),
            "default_author": self._default_author.text.strip(),
            "default_company": self._default_company.text.strip(),
        }
        # Only persist OAuth fields when using OAuth auth method
        if self._auth.auth_method == "oauth":
            values.update({
                "client_id": self._client_id.text.strip(),
                "client_secret": self._client_secret.text.strip(),
                "callback_port": self._port_spin.value(),
            })
        self._config.update(values)
        logger.info("Settings saved successfully")
        QMessageBox.information(self, "Saved", "Settings saved successfully.")

    def _on_theme_changed(self, text: str) -> None:
        theme = text.lower()
        logger.info("Theme changed to %s", theme)
        self._config.set("theme", theme)
        self.theme_changed.emit(theme)

    def _logout(self) -> None:
        reply = QMessageBox.question(
            self,
            "Confirm Logout",
            "This will clear your stored Jira session. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            logger.info("User confirmed logout")
            self._auth.logout()
            self._update_connection_visibility()
            self.logged_out.emit()
