"""Tests for epic_report_generator.services.auth_manager."""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from epic_report_generator.services.auth_manager import KEYRING_SERVICE, AuthManager
from epic_report_generator.services.config_manager import ConfigManager


def _make_config(tmp_path: Path) -> ConfigManager:
    """Isolated ConfigManager backed by *tmp_path*."""
    mgr = ConfigManager()
    mgr._dir = tmp_path
    mgr._path = tmp_path / "config.json"
    mgr.reset()
    return mgr


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------


class TestProperties:
    """Property helpers should reflect config state."""

    def test_is_configured_false_when_empty(self, tmp_path: Path) -> None:
        auth = AuthManager(_make_config(tmp_path))
        assert auth.is_configured is False

    def test_is_configured_true(self, tmp_path: Path) -> None:
        cfg = _make_config(tmp_path)
        cfg.update({"client_id": "cid", "client_secret": "csec"})
        auth = AuthManager(cfg)
        assert auth.is_configured is True

    def test_cloud_id(self, tmp_path: Path) -> None:
        cfg = _make_config(tmp_path)
        cfg.set("cloud_id", "abc123")
        auth = AuthManager(cfg)
        assert auth.cloud_id == "abc123"

    def test_auth_method(self, tmp_path: Path) -> None:
        cfg = _make_config(tmp_path)
        cfg.set("auth_method", "oauth")
        auth = AuthManager(cfg)
        assert auth.auth_method == "oauth"


# ---------------------------------------------------------------------------
# API-token auth
# ---------------------------------------------------------------------------


class TestApiTokenAuth:
    """API-token login stores token in keyring and config."""

    @patch("epic_report_generator.services.auth_manager.keyring")
    def test_login_api_token_stores_credentials(
        self, mock_keyring: MagicMock, tmp_path: Path,
    ) -> None:
        cfg = _make_config(tmp_path)
        auth = AuthManager(cfg)
        auth.login_api_token("https://company.atlassian.net", "a@b.com", "tok123")

        mock_keyring.set_password.assert_called_once_with(
            KEYRING_SERVICE, "api_token", "tok123",
        )
        assert cfg.get("auth_method") == "api_token"
        assert cfg.get("jira_url") == "https://company.atlassian.net"
        assert cfg.get("jira_email") == "a@b.com"
        # site_name should derive from URL
        assert cfg.get("site_name") == "company"

    @patch("epic_report_generator.services.auth_manager.keyring")
    def test_get_api_token_delegates_to_keyring(
        self, mock_keyring: MagicMock, tmp_path: Path,
    ) -> None:
        mock_keyring.get_password.return_value = "secret-tok"
        auth = AuthManager(_make_config(tmp_path))
        assert auth.get_api_token() == "secret-tok"
        mock_keyring.get_password.assert_called_with(KEYRING_SERVICE, "api_token")


# ---------------------------------------------------------------------------
# OAuth token access
# ---------------------------------------------------------------------------


class TestGetAccessToken:
    """get_access_token should use cache, restore from keyring, or refresh."""

    def test_returns_cached_token(self, tmp_path: Path) -> None:
        auth = AuthManager(_make_config(tmp_path))
        auth._access_token = "cached-tok"
        auth._token_expiry = time.time() + 3600
        assert auth.get_access_token() == "cached-tok"

    @patch("epic_report_generator.services.auth_manager.keyring")
    def test_returns_none_when_no_tokens(
        self, mock_keyring: MagicMock, tmp_path: Path,
    ) -> None:
        mock_keyring.get_password.return_value = None
        auth = AuthManager(_make_config(tmp_path))
        assert auth.get_access_token() is None

    @patch("epic_report_generator.services.auth_manager.keyring")
    def test_restores_valid_token_from_keyring(
        self, mock_keyring: MagicMock, tmp_path: Path,
    ) -> None:
        stored = {
            "access_token": "restored",
            "refresh_token": "rt",
            "expiry": time.time() + 3600,
        }
        mock_keyring.get_password.return_value = json.dumps(stored)
        auth = AuthManager(_make_config(tmp_path))
        assert auth.get_access_token() == "restored"

    @patch("epic_report_generator.services.auth_manager.requests")
    @patch("epic_report_generator.services.auth_manager.keyring")
    def test_refreshes_expired_token(
        self,
        mock_keyring: MagicMock,
        mock_requests: MagicMock,
        tmp_path: Path,
    ) -> None:
        stored = {
            "access_token": "old",
            "refresh_token": "rt",
            "expiry": time.time() - 100,  # expired
        }
        mock_keyring.get_password.return_value = json.dumps(stored)

        resp = MagicMock()
        resp.json.return_value = {
            "access_token": "new-tok",
            "refresh_token": "new-rt",
            "expires_in": 3600,
        }
        mock_requests.post.return_value = resp

        cfg = _make_config(tmp_path)
        cfg.update({"client_id": "cid", "client_secret": "csec"})
        auth = AuthManager(cfg)

        assert auth.get_access_token() == "new-tok"
        # New rotating refresh token should be stored immediately
        mock_keyring.set_password.assert_called()
        stored_payload = json.loads(mock_keyring.set_password.call_args[0][2])
        assert stored_payload["refresh_token"] == "new-rt"


# ---------------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------------


class TestLogout:
    """Logout should clear keyring entries and config."""

    @patch("epic_report_generator.services.auth_manager.keyring")
    def test_logout_clears_state(
        self, mock_keyring: MagicMock, tmp_path: Path,
    ) -> None:
        cfg = _make_config(tmp_path)
        cfg.update({"auth_method": "oauth", "cloud_id": "cid", "site_name": "x"})
        auth = AuthManager(cfg)
        auth._access_token = "tok"
        auth._token_expiry = time.time() + 3600

        auth.logout()

        assert auth._access_token is None
        assert auth._token_expiry == 0.0
        assert cfg.get("auth_method") == ""
        assert cfg.get("cloud_id") == ""
        assert cfg.get("site_name") == ""
        # keyring.delete_password called for both keys
        assert mock_keyring.delete_password.call_count == 2


# ---------------------------------------------------------------------------
# set_cloud_id
# ---------------------------------------------------------------------------


class TestSetCloudId:
    def test_persists_to_config(self, tmp_path: Path) -> None:
        cfg = _make_config(tmp_path)
        auth = AuthManager(cfg)
        auth.set_cloud_id("my-cloud")
        assert cfg.get("cloud_id") == "my-cloud"
