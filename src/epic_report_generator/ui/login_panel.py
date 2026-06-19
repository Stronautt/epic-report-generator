"""Login panel — API Token (default) + OAuth 2.0 (optional) authentication."""

from __future__ import annotations

import logging
from collections.abc import Callable

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import (
    QLabel,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from epic_report_generator.core.jira_client import JiraClient
from epic_report_generator.services.auth_manager import AuthManager
from epic_report_generator.services.config_manager import ConfigManager
from epic_report_generator.ui._threading import ThreadedTask
from epic_report_generator.ui.widgets import (
    GuideStep,
    LabelledField,
    StatusIndicator,
    make_scroll_content,
)

logger = logging.getLogger(__name__)

_API_TOKEN_URL = "https://id.atlassian.com/manage-profile/security/api-tokens"

# Height of the primary call-to-action buttons (Connect / Login with Atlassian).
_PRIMARY_BTN_HEIGHT = 44


class LoginPanel(QWidget):
    """Panel for Jira connection via API Token or OAuth 2.0 (3LO).

    Emits ``login_state_changed(bool)`` on auth state change.
    Emits ``login_succeeded(str, str)`` with (display_name, site_name) after a
    successful login so the main window can populate the sidebar user info.
    Emits ``avatar_loaded(QPixmap)`` once the avatar image has been downloaded.
    """

    login_state_changed = Signal(bool)
    login_succeeded = Signal(str, str)  # display_name, site_name
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
        self._tasks = ThreadedTask(self)
        self._nam = QNetworkAccessManager(self)

        self._build_ui()

    # -- UI construction ------------------------------------------------------

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll, root = make_scroll_content()
        # Reserve the scrollbar gutter so expanding/collapsing the guide steps
        # never reflows the page width (see CollapseAnimator._capture_scroll).
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        outer.addWidget(scroll)

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
        step1.add_text("Go to the Atlassian API tokens page in your account settings.")
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
        step4.add_text("Enable the following classic scopes (recommended):")
        step4.add_bullet(
            "read:jira-work — read issues, epics, " "projects, fields, and JQL search"
        )
        step4.add_bullet(
            "read:jira-user — read user profiles " "and assignee information"
        )
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
            "Copy the generated key immediately — "
            "you won't be able to see it again. "
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
        self._connect_btn.setFixedHeight(_PRIMARY_BTN_HEIGHT)
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
            "Open the Atlassian Developer Console and click "
            '"Create" → "OAuth 2.0 integration".'
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
            3,
            "Permissions → Jira API → read:jira-work, read:jira-user",
        )
        step3.add_text(
            'In the left sidebar click "Permissions". '
            'Find "Jira API" and click "Add".'
        )
        step3.add_separator()
        step3.add_text(
            'Click "Configure" next to "Jira API". '
            'Under "Jira platform REST API" → "Classic Scopes", '
            'click "Edit Scopes" and enable:'
        )
        step3.add_bullet("read:jira-work")
        step3.add_bullet("read:jira-user")
        guide_layout.addWidget(step3)

        step4 = GuideStep(
            4,
            "Authorization → OAuth 2.0 (3LO) → localhost:18492",
        )
        step4.add_text(
            'In the left sidebar click "Authorization". '
            'Next to "OAuth 2.0 (3LO)" click "Add". '
            "Set the callback URL to:"
        )
        step4.add_code("http://localhost:18492/callback")
        guide_layout.addWidget(step4)

        step5 = GuideStep(5, "Settings → copy Client ID and Secret below")
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
            tooltip="From Atlassian Developer Console → Your App → Settings",
        )
        self._client_secret_field = LabelledField(
            "Client Secret",
            placeholder="Paste your OAuth Client Secret",
            tooltip="From Atlassian Developer Console → Your App → Settings",
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
        self._login_btn.setFixedHeight(_PRIMARY_BTN_HEIGHT)
        self._login_btn.clicked.connect(self._start_login)
        layout.addWidget(self._login_btn)

        layout.addStretch()
        self._tabs.addTab(tab, "OAuth 2.0")

    def _toggle_guide(self) -> None:
        """Show or hide the inline OAuth setup guide."""
        self._toggle_widget(
            self._guide, self._guide_toggle_btn, "How do I create an OAuth app?"
        )

    def _toggle_api_guide(self) -> None:
        """Show or hide the inline API token guide."""
        self._toggle_widget(
            self._api_guide, self._api_guide_btn, "How do I get an API token?"
        )

    @staticmethod
    def _toggle_widget(body: QWidget, btn: QPushButton, show_text: str) -> None:
        """Toggle *body*'s visibility and flip *btn* between Hide / *show_text*."""
        visible = not body.isVisible()
        body.setVisible(visible)
        btn.setText("Hide guide" if visible else show_text)

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
            self._status.set_connected(False, "Restoring session…")

            def _restore_api() -> bool:
                # keyring read + Jira handshake — both blocking, run off the
                # UI thread so the window stays responsive during restore.
                api_token = self._auth.get_api_token()
                return bool(api_token) and self._jira.connect_basic(
                    saved_url, saved_email, api_token
                )

            self._tasks.start(
                _restore_api, self._on_api_restore_done, capture_exceptions=True
            )
            return

        if method == "oauth":
            logger.debug("Restoring OAuth session")
            if not self._auth.is_configured:
                logger.info("OAuth not configured — showing setup section")
                self._setup_section.show()
                self._login_btn.setEnabled(False)
                self._tabs.setCurrentIndex(1)
                return

            self._setup_section.hide()
            self._status.set_connected(False, "Restoring session…")

            def _restore_oauth() -> bool:
                # Token refresh + handshake are blocking network calls.
                token = self._auth.get_access_token()
                if not token or not self._jira.connect():
                    return False
                # Warm the myself() cache here so the main-thread success path
                # (which reuses it) issues no further network call.
                self._jira.get_myself()
                return True

            self._tasks.start(
                _restore_oauth, self._on_oauth_restore_done, capture_exceptions=True
            )
            return

        # No auth_method set — fresh install, show tabs
        logger.debug("No previous session found")

    def _on_api_restore_done(self, result: object) -> None:
        """Handle the threaded API-token restore result (on the UI thread)."""
        self._handle_restore_result(
            result,
            method="API-token",
            fail_log="API-token session restore failed",
            status_text="Token expired or revoked — please generate a new one",
            tab_index=0,
            on_failure=lambda: self._show_api_token_error(
                "Your API token has expired or been revoked. "
                f'<a href="{_API_TOKEN_URL}">Generate a new token</a> and reconnect.'
            ),
        )

    def _on_oauth_restore_done(self, result: object) -> None:
        """Handle the threaded OAuth restore result (on the UI thread)."""
        self._handle_restore_result(
            result,
            method="OAuth",
            fail_log="OAuth session expired — user must log in again",
            status_text="Session expired — please log in again",
            tab_index=1,
        )

    def _handle_restore_result(
        self,
        result: object,
        *,
        method: str,
        fail_log: str,
        status_text: str,
        tab_index: int,
        on_failure: Callable[[], None] | None = None,
    ) -> None:
        """Shared session-restore result handler for both auth methods."""
        if result is True:
            logger.info("%s session restored successfully", method)
            self._on_login_success()
            return
        if isinstance(result, Exception):
            logger.warning("%s session restore errored: %s", method, result)
        else:
            logger.warning(fail_log)
        self._status.set_connected(False, status_text)
        if on_failure is not None:
            on_failure()
        self._tabs.setCurrentIndex(tab_index)

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
                self,
                "Missing Fields",
                "Please fill in URL, Email, and API Token.",
            )
            return

        # Basic URL validation
        if not url.startswith(("http://", "https://")):
            url = f"https://{url}"
            self._url_field.text = url

        self._api_error_label.hide()
        self._connect_btn.setEnabled(False)
        self._connect_btn.setText("Connecting…")

        # Validate the credentials with a live handshake off the UI thread so the
        # window stays responsive; persist them only once it actually succeeds.
        self._tasks.start(
            lambda: self._jira.connect_basic(url, email, token),
            lambda result: self._on_api_connect_done(result, url, email, token),
            capture_exceptions=True,
        )

    def _on_api_connect_done(
        self, result: object, url: str, email: str, token: str
    ) -> None:
        """Finish API-token login on the UI thread once the handshake returns."""
        if result is True:
            # Persist credentials only after a confirmed connection so a failed
            # attempt never leaves bad creds in keyring/config.
            self._auth.login_api_token(url, email, token)
            logger.info("API-token login successful")
            self._on_login_success()
            return
        if isinstance(result, Exception):
            logger.warning("API-token connection errored: %s", result)
        self._connect_btn.setEnabled(True)
        self._connect_btn.setText("Connect")
        self._show_api_token_error(
            "Could not connect to Jira. Check your URL, email, "
            "and API token and try again."
        )

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
            logger.warning(
                "OAuth credentials incomplete — both Client ID and Secret required"
            )
            QMessageBox.warning(
                self, "Missing Fields", "Please enter both Client ID and Client Secret."
            )
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
        self._login_btn.setText("Waiting for browser…")

        self._tasks.start(self._auth.start_login, self._on_login_finished)

    def shutdown(self) -> None:
        """Wait for the login thread to finish before closing."""
        self._tasks.wait()

    def _on_login_finished(self, result: dict | None) -> None:
        if result is None:
            self._reset_login_button()
            logger.error("Login failed — authorization timed out or was denied")
            QMessageBox.warning(
                self,
                "Login Failed",
                "Authorization failed or timed out. Please try again.",
            )
            return

        # Handle multiple sites
        if "sites" in result:
            sites = result["sites"]
            if not sites:
                self._reset_login_button()
                logger.error("OAuth succeeded but no accessible Jira sites returned")
                QMessageBox.warning(
                    self,
                    "No Jira Sites",
                    "Your Atlassian account has no Jira sites accessible to this app.",
                )
                return
            # Use the first accessible site — single-site is the common case and a
            # multi-site picker is out of scope.
            self._auth.select_site(sites[0])

        # Establish the connection and fetch the profile off the UI thread — both
        # are blocking network calls and must never run on the main loop.
        self._login_btn.setText("Connecting…")

        def _connect_and_identify() -> tuple[bool, dict | None]:
            if not self._jira.connect():
                return (False, None)
            return (True, self._jira.get_myself())

        self._tasks.start(
            _connect_and_identify, self._on_oauth_connected, capture_exceptions=True
        )

    def _on_oauth_connected(self, result: object) -> None:
        """Finish OAuth login on the UI thread once the handshake returns."""
        self._reset_login_button()
        if isinstance(result, Exception):
            logger.error("Jira connection failed after OAuth login: %s", result)
            QMessageBox.warning(self, "Connection Failed", "Could not connect to Jira.")
            return
        ok, me = result  # type: ignore[misc]
        if not ok:
            logger.error("Jira connection failed after OAuth login")
            QMessageBox.warning(self, "Connection Failed", "Could not connect to Jira.")
            return
        logger.info("OAuth login successful")
        self._on_login_success(me)

    def _reset_login_button(self) -> None:
        """Restore the OAuth login button to its idle state."""
        self._login_btn.setEnabled(True)
        self._login_btn.setText("Login with Atlassian")

    # -- shared success path --------------------------------------------------

    def _on_login_success(self, me: dict | None = None) -> None:
        # *me* is the pre-fetched profile from a worker thread (OAuth login). The
        # API-token and session-restore callers pass nothing; for them
        # get_myself() returns the payload cached during the (threaded) connect,
        # so this stays off the network on the main loop.
        if me is None:
            me = self._jira.get_myself()
        display_name = me.get("displayName", "User") if me else "User"
        avatar_url = me.get("avatarUrl", "") if me else ""
        site = self._auth.site_name or "Jira Cloud"

        self._status.set_connected(True, f"Connected as {display_name}")
        self._tabs.hide()

        # Emit signals for main window / sidebar
        self.login_succeeded.emit(display_name, site)

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
