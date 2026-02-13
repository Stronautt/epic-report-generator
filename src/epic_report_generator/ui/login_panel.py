"""Login panel — API Token (default) + OAuth 2.0 (optional) authentication."""

from __future__ import annotations

import logging
from typing import Any

from PySide6.QtCore import QObject, QThread, QUrl, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import (
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from epic_report_generator.core.jira_client import JiraClient
from epic_report_generator.services.auth_manager import AuthManager
from epic_report_generator.services.config_manager import ConfigManager
from epic_report_generator.ui.widgets import GuideStep, LabelledField, StatusIndicator

logger = logging.getLogger(__name__)

_API_TOKEN_URL = "https://id.atlassian.com/manage-profile/security/api-tokens"


class _LoginWorker(QObject):
    """Runs the blocking OAuth flow in a background thread."""

    finished = Signal(object)  # dict | None

    def __init__(self, auth: AuthManager) -> None:
        super().__init__()
        self._auth = auth

    def run(self) -> None:
        """Execute the OAuth login flow."""
        result = self._auth.start_login()
        self.finished.emit(result)


class LoginPanel(QWidget):
    """Panel for Jira connection via API Token or OAuth 2.0 (3LO).

    Emits ``login_state_changed(bool)`` on auth state change.
    Emits ``login_succeeded(str, str, str)`` with (display_name, site_name, avatar_url)
    after a successful login so the main window can populate the sidebar user info.
    Emits ``avatar_loaded(QPixmap)`` once the avatar image has been downloaded.
    """

    login_state_changed = Signal(bool)
    login_succeeded = Signal(str, str, str)  # display_name, site_name, avatar_url
    avatar_loaded = Signal(object)  # QPixmap

    def __init__(
        self,
        config: ConfigManager,
        auth: AuthManager,
        jira: JiraClient,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._config = config
        self._auth = auth
        self._jira = jira
        self._thread: QThread | None = None
        self._worker: _LoginWorker | None = None
        self._nam = QNetworkAccessManager(self)

        self._build_ui()

    # -- UI construction ------------------------------------------------------

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        outer.addWidget(scroll)

        content = QWidget()
        scroll.setWidget(content)
        root = QVBoxLayout(content)
        root.setContentsMargins(32, 32, 32, 32)
        root.setSpacing(16)

        title = QLabel("Jira Connection")
        title.setProperty("heading", "true")
        root.addWidget(title)

        self._status = StatusIndicator()
        root.addWidget(self._status)

        # --- Tab widget with two auth methods --------------------------------
        self._tabs = QTabWidget()
        root.addWidget(self._tabs)

        self._build_api_token_tab()
        self._build_oauth_tab()

        root.addStretch()

    # -- Tab 0: API Token (default, recommended) ------------------------------

    def _build_api_token_tab(self) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(0, 16, 0, 0)
        layout.setSpacing(12)

        hint = QLabel("Connect using an Atlassian API token.")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        # Collapsible guide
        self._api_guide_btn = QPushButton("How do I get an API token?")
        self._api_guide_btn.setProperty("secondary", "true")
        self._api_guide_btn.clicked.connect(self._toggle_api_guide)
        layout.addWidget(self._api_guide_btn)

        self._api_guide = QWidget()
        api_guide_layout = QVBoxLayout(self._api_guide)
        api_guide_layout.setContentsMargins(0, 4, 0, 4)
        api_guide_layout.setSpacing(2)

        step1 = GuideStep(1, "Open the API key management portal")
        step1.add_text(
            "Go to the Atlassian API tokens page in your account settings."
        )
        step1.add_code(_API_TOKEN_URL)
        api_guide_layout.addWidget(step1)

        step2 = GuideStep(2, 'Choose "Create API key with specific permissions"')
        step2.add_text(
            'Click "Create API key", then select '
            '"Create API key with specific permissions" '
            "to create a key with only the access this app needs."
        )
        api_guide_layout.addWidget(step2)

        step3 = GuideStep(3, "Select Jira as the authorized application")
        step3.add_text(
            "In the application selection step, choose "
            '"Jira" as the product this key will have access to.'
        )
        api_guide_layout.addWidget(step3)

        step4 = GuideStep(4, "Assign the required permissions")
        step4.add_text(
            "Enable the following classic scopes (recommended):"
        )
        step4.add_bullet("read:jira-work \u2014 read issues, epics, "
                         "projects, fields, and JQL search")
        step4.add_bullet("read:jira-user \u2014 read user profiles "
                         "and assignee information")
        step4.add_separator()
        step4.add_text(
            "Alternatively, if your instance offers granular scopes, "
            "enable these instead:"
        )
        step4.add_bullet("read:issue-details:jira")
        step4.add_bullet("read:jql:jira")
        step4.add_bullet("read:field:jira")
        step4.add_bullet("read:project:jira")
        step4.add_bullet("read:jira-user")
        step4.add_separator()
        step4.add_text(
            "Do not grant any write or delete scopes. "
            "This app only reads data from Jira."
        )
        api_guide_layout.addWidget(step4)

        step5 = GuideStep(5, "Copy the API key and paste it below")
        step5.add_text(
            "Review your choices, then create the key. "
            "Copy the generated key immediately \u2014 "
            "you won\u2019t be able to see it again. "
            "Paste it into the API Token field below."
        )
        api_guide_layout.addWidget(step5)

        self._api_guide.hide()
        layout.addWidget(self._api_guide)

        self._url_field = LabelledField(
            "Jira Cloud URL",
            placeholder="https://company.atlassian.net",
            tooltip="Your Jira Cloud instance URL (e.g. https://company.atlassian.net)",
        )
        layout.addWidget(self._url_field)

        self._email_field = LabelledField(
            "Email",
            placeholder="you@company.com",
            tooltip="The email address associated with your Atlassian account",
        )
        layout.addWidget(self._email_field)

        self._token_field = LabelledField(
            "API Token",
            placeholder="Paste your API token",
            tooltip="Generate a token at Atlassian account settings",
            password=True,
        )
        layout.addWidget(self._token_field)

        self._connect_btn = QPushButton("Connect")
        self._connect_btn.setFixedHeight(44)
        self._connect_btn.clicked.connect(self._connect_api_token)
        layout.addWidget(self._connect_btn)

        # Error label for token expiry / auth failures (hidden by default)
        self._api_error_label = QLabel()
        self._api_error_label.setWordWrap(True)
        self._api_error_label.setStyleSheet("color: #DE350B;")
        self._api_error_label.hide()
        layout.addWidget(self._api_error_label)

        layout.addStretch()
        self._tabs.addTab(tab, "API Token (Recommended)")

    # -- Tab 1: OAuth 2.0 -----------------------------------------------------

    def _build_oauth_tab(self) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(0, 16, 0, 0)
        layout.setSpacing(12)

        # OAuth setup section
        self._setup_section = QWidget()
        setup_layout = QVBoxLayout(self._setup_section)
        setup_layout.setContentsMargins(0, 0, 0, 0)

        setup_hint = QLabel("Enter your Atlassian OAuth app credentials.")
        setup_hint.setWordWrap(True)
        setup_layout.addWidget(setup_hint)

        self._guide_toggle_btn = QPushButton("How do I create an OAuth app?")
        self._guide_toggle_btn.setProperty("secondary", "true")
        self._guide_toggle_btn.clicked.connect(self._toggle_guide)
        setup_layout.addWidget(self._guide_toggle_btn)

        self._guide = QWidget()
        guide_layout = QVBoxLayout(self._guide)
        guide_layout.setContentsMargins(0, 4, 0, 4)
        guide_layout.setSpacing(2)

        step1 = GuideStep(1, "Create OAuth 2.0 app at developer.atlassian.com")
        step1.add_text(
            'Open the Atlassian Developer Console and click '
            '"Create" \u2192 "OAuth 2.0 integration".'
        )
        step1.add_code("https://developer.atlassian.com/console/myapps/")
        guide_layout.addWidget(step1)

        step2 = GuideStep(2, 'Name it "Epic Report Generator" and accept terms')
        step2.add_text(
            "Enter a name for your integration, "
            "accept the developer terms, and click Create."
        )
        guide_layout.addWidget(step2)

        step3 = GuideStep(
            3, "Permissions \u2192 Jira API \u2192 read:jira-work, read:jira-user",
        )
        step3.add_text(
            'In the left sidebar click "Permissions". '
            'Find "Jira API" and click "Add".'
        )
        step3.add_separator()
        step3.add_text(
            'Click "Configure" next to "Jira API". '
            'Under "Jira platform REST API" \u2192 "Classic Scopes", '
            'click "Edit Scopes" and enable:'
        )
        step3.add_bullet("read:jira-work")
        step3.add_bullet("read:jira-user")
        guide_layout.addWidget(step3)

        step4 = GuideStep(
            4, "Authorization \u2192 OAuth 2.0 (3LO) \u2192 localhost:18492",
        )
        step4.add_text(
            'In the left sidebar click "Authorization". '
            'Next to "OAuth 2.0 (3LO)" click "Add". '
            "Set the callback URL to:"
        )
        step4.add_code("http://localhost:18492/callback")
        guide_layout.addWidget(step4)

        step5 = GuideStep(5, "Settings \u2192 copy Client ID and Secret below")
        step5.add_text(
            'In the left sidebar click "Settings". '
            "Copy the Client ID and Secret, then paste them "
            "into the fields below."
        )
        guide_layout.addWidget(step5)

        self._guide.hide()
        setup_layout.addWidget(self._guide)

        self._client_id_field = LabelledField(
            "Client ID",
            placeholder="Paste your OAuth Client ID",
            tooltip="From Atlassian Developer Console \u2192 Your App \u2192 Settings",
        )
        self._client_secret_field = LabelledField(
            "Client Secret",
            placeholder="Paste your OAuth Client Secret",
            tooltip="From Atlassian Developer Console \u2192 Your App \u2192 Settings",
            password=True,
        )
        setup_layout.addWidget(self._client_id_field)
        setup_layout.addWidget(self._client_secret_field)

        save_btn = QPushButton("Save Credentials")
        save_btn.setProperty("secondary", "true")
        save_btn.clicked.connect(self._save_oauth_config)
        setup_layout.addWidget(save_btn)
        layout.addWidget(self._setup_section)

        # Login button
        self._login_btn = QPushButton("Login with Atlassian")
        self._login_btn.setFixedHeight(44)
        self._login_btn.clicked.connect(self._start_login)
        layout.addWidget(self._login_btn)

        layout.addStretch()
        self._tabs.addTab(tab, "OAuth 2.0")

    def _toggle_guide(self) -> None:
        """Show or hide the inline OAuth setup guide."""
        visible = not self._guide.isVisible()
        self._guide.setVisible(visible)
        self._guide_toggle_btn.setText(
            "Hide guide" if visible else "How do I create an OAuth app?"
        )

    def _toggle_api_guide(self) -> None:
        """Show or hide the inline API token guide."""
        visible = not self._api_guide.isVisible()
        self._api_guide.setVisible(visible)
        self._api_guide_btn.setText(
            "Hide guide" if visible else "How do I get an API token?"
        )

    # -- session restore ------------------------------------------------------

    def try_restore_session(self) -> None:
        """Attempt to restore a previous session from keyring."""
        logger.debug("Attempting to restore previous session")

        # Pre-fill OAuth config fields
        cid = self._config.get("client_id", "")
        csec = self._config.get("client_secret", "")
        if cid:
            self._client_id_field.text = cid
        if csec:
            self._client_secret_field.text = csec

        # Pre-fill API token fields
        saved_url = self._config.get("jira_url", "")
        saved_email = self._config.get("jira_email", "")
        if saved_url:
            self._url_field.text = saved_url
        if saved_email:
            self._email_field.text = saved_email

        method = self._auth.auth_method

        if method == "api_token":
            logger.debug("Restoring API-token session")
            api_token = self._auth.get_api_token()
            if api_token and self._jira.connect_basic(saved_url, saved_email, api_token):
                logger.info("API-token session restored successfully")
                self._on_login_success()
                return
            # Token likely expired or revoked
            logger.warning("API-token session restore failed")
            self._status.set_connected(
                False,
                "Token expired or revoked \u2014 please generate a new one",
            )
            self._show_api_token_error(
                'Your API token has expired or been revoked. '
                f'<a href="{_API_TOKEN_URL}">Generate a new token</a> and reconnect.'
            )
            self._tabs.setCurrentIndex(0)
            return

        if method == "oauth":
            logger.debug("Restoring OAuth session")
            if not self._auth.is_configured:
                logger.info("OAuth not configured \u2014 showing setup section")
                self._setup_section.show()
                self._login_btn.setEnabled(False)
                self._tabs.setCurrentIndex(1)
                return

            self._setup_section.hide()
            token = self._auth.get_access_token()
            if token and self._jira.connect():
                logger.info("OAuth session restored successfully")
                self._on_login_success()
            else:
                logger.warning("OAuth session expired \u2014 user must log in again")
                self._status.set_connected(
                    False, "Session expired \u2014 please log in again",
                )
                self._tabs.setCurrentIndex(1)
            return

        # No auth_method set — fresh install, show tabs
        logger.debug("No previous session found")

    # -- public API -----------------------------------------------------------

    def reset_to_logged_out(self) -> None:
        """Reset the panel to the logged-out state."""
        self._status.set_connected(False)
        self._api_error_label.hide()

        # Reset API Token tab
        self._connect_btn.setEnabled(True)
        self._connect_btn.setText("Connect")

        # Reset OAuth tab
        self._login_btn.setText("Login with Atlassian")
        self._login_btn.setEnabled(True)
        self._login_btn.show()

        if not self._auth.is_configured:
            self._setup_section.show()
            self._login_btn.setEnabled(False)

        # Show tabs again
        self._tabs.show()

    # -- API Token slots ------------------------------------------------------

    def _connect_api_token(self) -> None:
        """Validate fields and connect using API token."""
        url = self._url_field.text.strip().rstrip("/")
        email = self._email_field.text.strip()
        token = self._token_field.text.strip()

        if not url or not email or not token:
            QMessageBox.warning(
                self, "Missing Fields",
                "Please fill in URL, Email, and API Token.",
            )
            return

        # Basic URL validation
        if not url.startswith("http"):
            url = f"https://{url}"
            self._url_field.text = url

        self._api_error_label.hide()
        self._connect_btn.setEnabled(False)
        self._connect_btn.setText("Connecting\u2026")

        # Store credentials first
        self._auth.login_api_token(url, email, token)

        # Try to connect (validates credentials internally via myself())
        if not self._jira.connect_basic(url, email, token):
            self._connect_btn.setEnabled(True)
            self._connect_btn.setText("Connect")
            self._show_api_token_error(
                'Could not connect to Jira. Check your URL, email, '
                'and API token and try again.'
            )
            return

        logger.info("API-token login successful")
        self._on_login_success()

    def _show_api_token_error(self, message: str) -> None:
        """Display an error message below the API Token connect button."""
        self._api_error_label.setText(message)
        self._api_error_label.setOpenExternalLinks(True)
        self._api_error_label.show()

    # -- OAuth slots ----------------------------------------------------------

    def _save_oauth_config(self) -> None:
        cid = self._client_id_field.text.strip()
        csec = self._client_secret_field.text.strip()
        if not cid or not csec:
            logger.warning("OAuth credentials incomplete \u2014 both Client ID and Secret required")
            QMessageBox.warning(self, "Missing Fields", "Please enter both Client ID and Client Secret.")
            return
        self._config.update({"client_id": cid, "client_secret": csec})
        logger.info("OAuth credentials saved")
        self._setup_section.hide()
        self._login_btn.setEnabled(True)

    def _start_login(self) -> None:
        if not self._auth.is_configured:
            self._setup_section.show()
            return

        logger.info("Starting browser login flow")
        self._login_btn.setEnabled(False)
        self._login_btn.setText("Waiting for browser\u2026")

        self._thread = QThread()
        self._worker = _LoginWorker(self._auth)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_login_finished)
        self._worker.finished.connect(self._thread.quit)
        self._worker.finished.connect(self._cleanup_worker)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.start()

    def _cleanup_worker(self) -> None:
        """Release the worker reference after the login flow completes."""
        if self._worker is not None:
            self._worker.deleteLater()
            self._worker = None

    def _on_login_finished(self, result: dict[str, Any] | None) -> None:
        self._login_btn.setEnabled(True)
        self._login_btn.setText("Login with Atlassian")

        if result is None:
            logger.error("Login failed \u2014 authorization timed out or was denied")
            QMessageBox.warning(
                self, "Login Failed",
                "Authorization failed or timed out. Please try again.",
            )
            return

        # Handle multiple sites
        if "sites" in result:
            sites = result["sites"]
            # For now, pick the first site; a future enhancement can show a picker
            self._auth.select_site(sites[0])

        if self._jira.connect():
            logger.info("OAuth login successful")
            self._on_login_success()
        else:
            logger.error("Jira connection failed after OAuth login")
            QMessageBox.warning(self, "Connection Failed", "Could not connect to Jira.")

    # -- shared success path --------------------------------------------------

    def _on_login_success(self) -> None:
        me = self._jira.get_myself()
        display_name = me.get("displayName", "User") if me else "User"
        avatar_url = me.get("avatarUrl", "") if me else ""
        site = self._auth.site_name or "Jira Cloud"

        self._status.set_connected(True, f"Connected as {display_name}")
        self._tabs.hide()

        # Emit signals for main window / sidebar
        self.login_succeeded.emit(display_name, site, avatar_url)

        if avatar_url:
            self._load_avatar(avatar_url)

        self.login_state_changed.emit(True)

    def _load_avatar(self, url: str) -> None:
        req = QNetworkRequest(QUrl(url))
        # Attach the access token for Atlassian avatar URLs (OAuth only)
        if self._auth.auth_method == "oauth":
            token = self._auth.get_access_token()
            if token:
                req.setRawHeader(b"Authorization", f"Bearer {token}".encode())
        reply = self._nam.get(req)
        reply.finished.connect(lambda: self._on_avatar_loaded(reply))

    def _on_avatar_loaded(self, reply: QNetworkReply) -> None:
        if reply.error() == QNetworkReply.NetworkError.NoError:
            data = reply.readAll()
            pixmap = QPixmap()
            pixmap.loadFromData(data.data())
            self.avatar_loaded.emit(pixmap)
        reply.deleteLater()
