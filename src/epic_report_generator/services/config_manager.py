"""JSON-based configuration persistence via platformdirs."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from platformdirs import user_config_dir

logger = logging.getLogger(__name__)

APP_NAME = "epic-report-generator"
CONFIG_FILENAME = "config.json"

_DEFAULTS: dict[str, Any] = {
    "auth_method": "",        # "api_token" or "oauth" — empty = not logged in yet
    "jira_url": "",           # e.g. "https://company.atlassian.net"
    "jira_email": "",         # user's Jira email for basic auth
    "client_id": "",
    "client_secret": "",
    "callback_port": 18492,
    "cloud_id": "",
    "site_name": "",
    "theme": "light",
    "default_title": "Epic Progress Report",
    "default_author": "",
    "default_company": "",
    "last_epic_keys": [],
    "story_points_field": "story_points",
    "epic_link_field": "customfield_10014",
}


class ConfigManager:
    """Read/write JSON configuration stored in the platform config directory."""

    def __init__(self) -> None:
        self._dir = Path(user_config_dir(APP_NAME, appauthor=False))
        self._path = self._dir / CONFIG_FILENAME
        self._data: dict[str, Any] = dict(_DEFAULTS)
        self._load()
        logger.debug("Config loaded from %s", self._path)

    # -- public API -----------------------------------------------------------

    def get(self, key: str, default: Any = None) -> Any:
        """Return a config value, falling back to *default*."""
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Set a config value and persist to disk."""
        self._data[key] = value
        self._save()

    def update(self, values: dict[str, Any]) -> None:
        """Bulk-update config values and persist."""
        self._data.update(values)
        self._save()

    def reset(self) -> None:
        """Reset all values to defaults and persist."""
        logger.info("Resetting config to defaults")
        self._data = dict(_DEFAULTS)
        self._save()

    @property
    def data(self) -> dict[str, Any]:
        """Return a shallow copy of all configuration."""
        return dict(self._data)

    # -- internals ------------------------------------------------------------

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            with open(self._path, encoding="utf-8") as fh:
                stored = json.load(fh)
            if isinstance(stored, dict):
                self._data.update(stored)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to load config from %s: %s", self._path, exc)

    def _save(self) -> None:
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            with open(self._path, "w", encoding="utf-8") as fh:
                json.dump(self._data, fh, indent=2, default=str)
        except OSError as exc:
            logger.warning("Failed to save config to %s: %s", self._path, exc)
