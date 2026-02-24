"""JSON-based configuration persistence via platformdirs."""

from __future__ import annotations

import copy
import json
import logging
from pathlib import Path
from typing import Any

from platformdirs import user_config_dir

logger = logging.getLogger(__name__)

APP_NAME = "epic-report-generator"
CONFIG_FILENAME = "config.json"

DEFAULT_PROFILE_NAME = "Default"

# Keys that live inside each profile (everything else is global).
PROFILE_KEYS: frozenset[str] = frozenset(
    {
        "last_report_items",
        "default_title",
        "default_author",
        "default_company",
        "estimation_method",
        "progress_method",
        "story_points_field",
        "epic_link_field",
        "start_date_field",
        "due_date_field",
        "include_subtasks",
        "timeline_start_field",
        "timeline_end_field",
        "timeline_hard_start",
        "timeline_hard_end",
        "show_children_on_timeline",
        "expand_label_details",
        "show_additional_metrics",
        "confidential",
    }
)

_DEFAULTS: dict[str, Any] = {
    # Global keys
    "auth_method": "",  # "api_token" or "oauth" — empty = not logged in yet
    "jira_url": "",  # e.g. "https://company.atlassian.net"
    "jira_email": "",  # user's Jira email for basic auth
    "client_id": "",
    "client_secret": "",
    "callback_port": 18492,
    "cloud_id": "",
    "site_name": "",
    "theme": "light",
    "last_epic_keys": [],
    # Profile infrastructure
    "active_profile": DEFAULT_PROFILE_NAME,
    "profiles": {},
    # Profile-scoped keys (used as defaults for new profiles)
    "default_title": "Epic Progress Report",
    "default_author": "",
    "default_company": "",
    "last_report_items": [],
    "estimation_method": "story_points",
    "progress_method": "combined",
    "story_points_field": "story_points",
    "epic_link_field": "customfield_10014",
    "start_date_field": "startdate",
    "due_date_field": "duedate",
    "include_subtasks": True,
    "timeline_start_field": "",
    "timeline_end_field": "",
    "timeline_hard_start": "",
    "timeline_hard_end": "",
    "show_children_on_timeline": False,
    "expand_label_details": True,
    "show_additional_metrics": True,
    "confidential": False,
}


class ConfigManager:
    """Read/write JSON configuration stored in the platform config directory."""

    def __init__(self) -> None:
        self._dir = Path(user_config_dir(APP_NAME, appauthor=False))
        self._path = self._dir / CONFIG_FILENAME
        self._data: dict[str, Any] = copy.deepcopy(_DEFAULTS)
        self._dir_created = False
        self._load()
        logger.debug("Config loaded from %s", self._path)

    # -- public API -----------------------------------------------------------

    def get(self, key: str, default: Any = None) -> Any:
        """Return a config value, falling back to *default*.

        Profile-scoped keys are transparently read from the active profile.
        """
        if key in PROFILE_KEYS:
            profile = self._active_profile_data()
            if key in profile:
                return profile[key]
            # Fall back to caller-supplied default or _DEFAULTS
            return default if default is not None else _DEFAULTS.get(key)
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Set a config value and persist to disk.

        Profile-scoped keys are transparently written to the active profile.
        """
        if key in PROFILE_KEYS:
            self._active_profile_data()[key] = value
        else:
            self._data[key] = value
        self._save()

    def update(self, values: dict[str, Any]) -> None:
        """Bulk-update config values and persist.

        Profile-scoped keys are written to the active profile; global keys
        go to the top level.
        """
        profile = self._active_profile_data()
        for key, value in values.items():
            if key in PROFILE_KEYS:
                profile[key] = value
            else:
                self._data[key] = value
        self._save()

    def reset(self) -> None:
        """Reset the active profile to defaults and persist."""
        logger.info("Resetting active profile to defaults")
        name = self._data.get("active_profile", DEFAULT_PROFILE_NAME)
        profiles = self._data.setdefault("profiles", {})
        profiles[name] = dict(self._default_profile_values())
        self._save()

    @property
    def data(self) -> dict[str, Any]:
        """Return a shallow copy of all configuration.

        Profile-scoped keys are merged from the active profile so callers
        see a flat view.
        """
        flat = dict(self._data)
        flat.update(self._active_profile_data())
        return flat

    # -- profile management ---------------------------------------------------

    @property
    def active_profile_name(self) -> str:
        """Return the name of the currently active profile."""
        return self._data.get("active_profile", DEFAULT_PROFILE_NAME)

    @property
    def profile_names(self) -> list[str]:
        """Return profile names in sorted order, with Default always first."""
        profiles: dict = self._data.get("profiles", {})
        names = sorted(profiles.keys())
        if DEFAULT_PROFILE_NAME in names:
            names.remove(DEFAULT_PROFILE_NAME)
            names.insert(0, DEFAULT_PROFILE_NAME)
        elif not names:
            # Ensure at least Default exists
            self._active_profile_data()
            names = [DEFAULT_PROFILE_NAME]
        return names

    def switch_profile(self, name: str) -> None:
        """Switch to the named profile, creating it with defaults if missing."""
        profiles = self._data.setdefault("profiles", {})
        if name not in profiles:
            profiles[name] = dict(self._default_profile_values())
        self._data["active_profile"] = name
        self._save()
        logger.info("Switched to profile %r", name)

    def create_profile(self, name: str, clone_from: str | None = None) -> None:
        """Create a new profile, optionally cloning values from another profile."""
        profiles = self._data.setdefault("profiles", {})
        if clone_from and clone_from in profiles:
            profiles[name] = copy.deepcopy(profiles[clone_from])
        else:
            profiles[name] = dict(self._default_profile_values())
        self._data["active_profile"] = name
        self._save()
        logger.info("Created profile %r (cloned from %r)", name, clone_from)

    def rename_profile(self, old_name: str, new_name: str) -> None:
        """Rename a profile. Cannot rename the Default profile."""
        if old_name == DEFAULT_PROFILE_NAME:
            return
        profiles = self._data.setdefault("profiles", {})
        if old_name not in profiles:
            return
        profiles[new_name] = profiles.pop(old_name)
        if self._data.get("active_profile") == old_name:
            self._data["active_profile"] = new_name
        self._save()
        logger.info("Renamed profile %r → %r", old_name, new_name)

    def delete_profile(self, name: str) -> None:
        """Delete a profile. Cannot delete the Default profile."""
        if name == DEFAULT_PROFILE_NAME:
            return
        profiles = self._data.setdefault("profiles", {})
        profiles.pop(name, None)
        if self._data.get("active_profile") == name:
            self._data["active_profile"] = DEFAULT_PROFILE_NAME
        self._save()
        logger.info("Deleted profile %r", name)

    # -- internals ------------------------------------------------------------

    def _default_profile_values(self) -> dict[str, Any]:
        """Return default values for a new profile."""
        return {k: copy.deepcopy(_DEFAULTS[k]) for k in PROFILE_KEYS if k in _DEFAULTS}

    def _active_profile_data(self) -> dict[str, Any]:
        """Return the dict for the current active profile, creating if missing."""
        profiles = self._data.setdefault("profiles", {})
        name = self._data.get("active_profile", DEFAULT_PROFILE_NAME)
        if name not in profiles:
            profiles[name] = dict(self._default_profile_values())
        return profiles[name]

    def _migrate_to_profiles(self) -> None:
        """One-time migration: move profile-scoped keys from top-level into Default."""
        if self._data.get("profiles"):
            return  # Already migrated
        profile_values: dict[str, Any] = {}
        for key in PROFILE_KEYS:
            if key in self._data:
                profile_values[key] = self._data.pop(key)
        if profile_values:
            self._data.setdefault("profiles", {})[DEFAULT_PROFILE_NAME] = profile_values
            self._data.setdefault("active_profile", DEFAULT_PROFILE_NAME)
            self._save()
            logger.info("Migrated existing config into Default profile")

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
        self._migrate_to_profiles()

    def _save(self) -> None:
        try:
            if not self._dir_created:
                self._dir.mkdir(parents=True, exist_ok=True)
                self._dir_created = True
            with open(self._path, "w", encoding="utf-8") as fh:
                json.dump(self._data, fh, indent=2, default=str)
        except OSError as exc:
            logger.warning("Failed to save config to %s: %s", self._path, exc)
