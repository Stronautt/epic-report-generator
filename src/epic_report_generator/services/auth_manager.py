"""OAuth 2.0 (3LO) flow orchestration and keyring token storage."""

from __future__ import annotations

import json
import logging
import secrets
import time
import webbrowser
from typing import Any
from urllib.parse import urlencode

import keyring
import requests

from epic_report_generator.services.config_manager import ConfigManager
from epic_report_generator.services.oauth_server import wait_for_callback

logger = logging.getLogger(__name__)

KEYRING_SERVICE = "epic-report-generator"
_AUTH_URL = "https://auth.atlassian.com/authorize"
_TOKEN_URL = "https://auth.atlassian.com/oauth/token"
_RESOURCES_URL = "https://api.atlassian.com/oauth/token/accessible-resources"
_SCOPES = "read:jira-work read:jira-user offline_access"


class AuthManager:
    """Manage the Atlassian OAuth 2.0 three-legged flow.

    Tokens are stored/retrieved via the OS keyring.  The ``ConfigManager``
    is used for non-secret data (client_id, cloud_id, site_name, etc.).
    """

    def __init__(self, config: ConfigManager) -> None:
        self._config = config
        self._access_token: str | None = None
        self._token_expiry: float = 0.0

    # -- public helpers -------------------------------------------------------

    @property
    def is_configured(self) -> bool:
        """Return True when client_id and client_secret are set."""
        return bool(self._config.get("client_id")) and bool(
            self._config.get("client_secret")
        )

    @property
    def cloud_id(self) -> str:
        """Return the stored Jira Cloud ID."""
        return str(self._config.get("cloud_id", ""))

    @property
    def site_name(self) -> str:
        """Return the stored Jira site display name."""
        return str(self._config.get("site_name", ""))

    @property
    def auth_method(self) -> str:
        """Return the active auth method: ``"api_token"``, ``"oauth"``, or ``""``."""
        return str(self._config.get("auth_method", ""))

    @property
    def jira_url(self) -> str:
        """Return the stored Jira instance URL (API-token auth)."""
        return str(self._config.get("jira_url", ""))

    @property
    def jira_email(self) -> str:
        """Return the stored Jira email (API-token auth)."""
        return str(self._config.get("jira_email", ""))

    def set_cloud_id(self, cloud_id: str) -> None:
        """Persist a cloud_id discovered during connection."""
        self._config.set("cloud_id", cloud_id)

    # -- API-token auth -------------------------------------------------------

    def login_api_token(self, url: str, email: str, token: str) -> None:
        """Store API-token credentials and persist config.

        The token is saved in keyring under the ``"api_token"`` key (separate
        from the OAuth ``"tokens"`` entry).  Non-secret fields go to config.
        """
        keyring.set_password(KEYRING_SERVICE, "api_token", token)

        # Derive a friendly site name from the URL
        site_name = url.rstrip("/").removeprefix("https://").removeprefix("http://")
        site_name = site_name.removesuffix(".atlassian.net")

        self._config.update({
            "auth_method": "api_token",
            "jira_url": url.rstrip("/"),
            "jira_email": email,
            "site_name": site_name,
        })
        logger.info("API-token credentials stored (site=%s)", site_name)

    def get_api_token(self) -> str | None:
        """Retrieve the API token from the OS keyring."""
        return keyring.get_password(KEYRING_SERVICE, "api_token")

    # -- token access ---------------------------------------------------------

    def get_access_token(self) -> str | None:
        """Return a valid access token, refreshing if necessary."""
        if self._access_token and time.time() < self._token_expiry:
            logger.debug("Using cached access token (expires in %.0fs)", self._token_expiry - time.time())
            return self._access_token

        # Try to restore from keyring
        stored = self._load_tokens()
        if not stored:
            logger.debug("No stored tokens found in keyring")
            return None

        access = stored.get("access_token", "")
        expiry = stored.get("expiry", 0.0)

        if access and time.time() < expiry:
            logger.info("Restored access token from keyring (expires in %.0fs)", expiry - time.time())
            self._access_token = access
            self._token_expiry = expiry
            return access

        # Token expired — attempt refresh
        refresh = stored.get("refresh_token", "")
        if refresh:
            logger.info("Access token expired, refreshing")
            return self._refresh_token(refresh)

        logger.warning("No refresh token available, re-login required")
        return None

    # -- login flow -----------------------------------------------------------

    def start_login(self) -> dict[str, Any] | None:
        """Run the full browser-based OAuth login flow (blocking).

        Returns a dict with the first accessible Jira site's
        ``cloud_id`` and ``name``, or ``None`` on failure.  When
        multiple sites are available the full list is returned under
        the ``sites`` key so the caller can present a picker.
        """
        if not self.is_configured:
            logger.error("OAuth client_id / client_secret not configured")
            return None

        logger.info("Starting OAuth login flow")
        state = secrets.token_urlsafe(32)
        port = int(self._config.get("callback_port", 18492))
        redirect_uri = f"http://localhost:{port}/callback"
        logger.debug("OAuth redirect URI: %s", redirect_uri)

        params = {
            "audience": "api.atlassian.com",
            "client_id": self._config.get("client_id"),
            "scope": _SCOPES,
            "redirect_uri": redirect_uri,
            "state": state,
            "response_type": "code",
            "prompt": "consent",
        }
        auth_url = f"{_AUTH_URL}?{urlencode(params)}"

        logger.debug("Opening browser for Atlassian consent")
        webbrowser.open(auth_url)
        logger.debug("Waiting for OAuth callback on port %d", port)
        result = wait_for_callback(port, state)

        if not result or "error" in result:
            logger.error("OAuth callback failed: %s", result)
            return None

        code = result["code"]
        logger.debug("Received authorization code, exchanging for tokens")
        tokens = self._exchange_code(code, redirect_uri)
        if not tokens:
            return None

        self._store_tokens(tokens)
        self._config.set("auth_method", "oauth")
        logger.info("OAuth tokens stored in keyring")

        # Fetch accessible resources
        sites = self._fetch_accessible_resources(tokens["access_token"])
        if not sites:
            return None

        logger.info("Found %d accessible Jira site(s)", len(sites))
        if len(sites) == 1:
            self._select_site(sites[0])
            return sites[0]

        return {"sites": sites}

    def select_site(self, site: dict[str, str]) -> None:
        """Persist the user's chosen Jira site."""
        self._select_site(site)

    def logout(self) -> None:
        """Clear all stored tokens and site information for both auth methods."""
        logger.info("Logging out — clearing tokens and site data")
        for key in ("tokens", "api_token"):
            try:
                keyring.delete_password(KEYRING_SERVICE, key)
            except keyring.errors.PasswordDeleteError:
                pass
        self._access_token = None
        self._token_expiry = 0.0
        self._config.update({
            "auth_method": "",
            "jira_url": "",
            "jira_email": "",
            "cloud_id": "",
            "site_name": "",
        })

    # -- internals ------------------------------------------------------------

    def _exchange_code(self, code: str, redirect_uri: str) -> dict[str, Any] | None:
        logger.debug("Exchanging authorization code for tokens")
        try:
            resp = requests.post(
                _TOKEN_URL,
                json={
                    "grant_type": "authorization_code",
                    "client_id": self._config.get("client_id"),
                    "client_secret": self._config.get("client_secret"),
                    "code": code,
                    "redirect_uri": redirect_uri,
                },
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            data["expiry"] = time.time() + data.get("expires_in", 3600)
            self._access_token = data["access_token"]
            self._token_expiry = data["expiry"]
            logger.info("Token exchange successful (expires_in=%ds)", data.get("expires_in", 3600))
            return data
        except requests.RequestException as exc:
            logger.error("Token exchange failed: %s", exc)
            return None

    def _refresh_token(self, refresh_token: str) -> str | None:
        logger.debug("Refreshing access token")
        try:
            resp = requests.post(
                _TOKEN_URL,
                json={
                    "grant_type": "refresh_token",
                    "client_id": self._config.get("client_id"),
                    "client_secret": self._config.get("client_secret"),
                    "refresh_token": refresh_token,
                },
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            data["expiry"] = time.time() + data.get("expires_in", 3600)

            # Store the new rotating refresh token immediately
            self._store_tokens(data)
            self._access_token = data["access_token"]
            self._token_expiry = data["expiry"]
            logger.info("Token refreshed successfully (expires_in=%ds)", data.get("expires_in", 3600))
            return data["access_token"]
        except requests.RequestException as exc:
            logger.error("Token refresh failed: %s", exc)
            self._access_token = None
            self._token_expiry = 0.0
            return None

    def _fetch_accessible_resources(
        self, access_token: str
    ) -> list[dict[str, str]] | None:
        try:
            resp = requests.get(
                _RESOURCES_URL,
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=30,
            )
            resp.raise_for_status()
            sites = resp.json()
            return [
                {"cloud_id": s["id"], "name": s.get("name", s["id"]), "url": s.get("url", "")}
                for s in sites
            ]
        except requests.RequestException as exc:
            logger.error("Failed to fetch accessible resources: %s", exc)
            return None

    def _select_site(self, site: dict[str, str]) -> None:
        logger.info("Selected Jira site: %s (cloud_id=%s)", site.get("name", ""), site["cloud_id"])
        self._config.update(
            {"cloud_id": site["cloud_id"], "site_name": site.get("name", "")}
        )

    def _store_tokens(self, tokens: dict[str, Any]) -> None:
        payload = {
            "access_token": tokens.get("access_token", ""),
            "refresh_token": tokens.get("refresh_token", ""),
            "expiry": tokens.get("expiry", 0.0),
        }
        keyring.set_password(KEYRING_SERVICE, "tokens", json.dumps(payload))

    def _load_tokens(self) -> dict[str, Any] | None:
        raw = keyring.get_password(KEYRING_SERVICE, "tokens")
        if not raw:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None
