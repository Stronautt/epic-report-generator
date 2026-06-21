"""JSON-based configuration persistence via platformdirs."""

from __future__ import annotations

import copy
import json
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
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
        "include_subtasks_in_timeline",
        "timeline_start_field",
        "timeline_end_field",
        "timeline_hard_start",
        "timeline_hard_end",
        "show_epic_stories_on_timeline",
        "show_subtasks_on_timeline",
        "expand_label_details",
        "show_additional_metrics",
        "show_timeline_chart",
        "report_force_light",
        "confidential",
    }
)

_LEGACY_TIMESTAMP = "2000-01-01T00:00:00+00:00"


def _now_iso() -> str:
    """Return the current UTC time as an ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()


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
    # "light", "dark", or "system" (follow the OS colour scheme).
    "theme": "system",
    # Appearance customization (NFR-05) — global, like `theme`.
    # accent_color: "" = built-in blue, else "#rrggbb".
    # font_source: "" = default font, "file", or "google".
    # font_value: file path (file) or family name (google).
    # font_family: resolved family name applied to the UI and the report.
    "accent_color": "",
    "font_source": "",
    "font_value": "",
    "font_family": "",
    # Last directory the user exported a PDF to. "" = none yet; the export
    # dialog falls back to the cross-platform Downloads folder.
    "last_export_dir": "",
    # Last window size (global). Restored on launch, clamped to a safe range
    # (see MainWindow._safe_window_size) so a stale value can't strand the
    # window off-screen or too small to use.
    "window_width": 1280,
    "window_height": 900,
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
    "include_subtasks_in_timeline": False,
    "timeline_start_field": "",
    "timeline_end_field": "",
    "timeline_hard_start": "",
    "timeline_hard_end": "",
    "show_epic_stories_on_timeline": False,
    "show_subtasks_on_timeline": False,
    "expand_label_details": True,
    "show_additional_metrics": True,
    "show_timeline_chart": True,
    # Force the generated report to the light theme regardless of the app theme.
    "report_force_light": True,
    "confidential": False,
}


class ConfigManager:
    """Read/write JSON configuration stored in the platform config directory."""

    # Class-level defaults so instances built via __new__ (e.g. in tests that
    # bypass __init__) still have the deferred-save flags available.
    _dirty: bool = False
    _deferred: bool = False
    _profile_names_cache: list[str] | None = None

    def __init__(self) -> None:
        self._dir = Path(user_config_dir(APP_NAME, appauthor=False))
        self._path = self._dir / CONFIG_FILENAME
        self._data: dict[str, Any] = copy.deepcopy(_DEFAULTS)
        self._dir_created = False
        self._dirty = False
        self._deferred = False
        self._profile_names_cache = None
        self._load()
        logger.debug("Config loaded from %s", self._path)

    @contextmanager
    def batch(self) -> Iterator[None]:
        """Defer disk writes until the block exits, then flush once if dirty.

        Useful when applying many ``set()`` calls in a row; the default is to
        write eagerly on every change so headless callers need no event loop.
        """
        self._deferred = True
        try:
            yield
        finally:
            self._deferred = False
            self.flush()

    def flush(self) -> None:
        """Write buffered changes to disk if any are pending."""
        if self._dirty:
            self._write()

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
        name = self.active_profile_name
        profiles = self._profiles_dict()
        old_created = profiles.get(name, {}).get("_created_at")
        profiles[name] = dict(self._default_profile_values())
        if old_created:
            profiles[name]["_created_at"] = old_created
        self._save()

    # -- profile management ---------------------------------------------------

    @property
    def active_profile_name(self) -> str:
        """Return the name of the currently active profile."""
        return self._data.get("active_profile", DEFAULT_PROFILE_NAME)

    @property
    def profile_names(self) -> list[str]:
        """Return profile names in sorted order, with Default always first.

        Memoized; the cache is invalidated whenever config is saved or loaded.
        """
        if self._profile_names_cache is not None:
            return self._profile_names_cache
        profiles: dict = self._data.get("profiles", {})
        names = sorted(
            profiles.keys(),
            key=lambda n: profiles[n].get("_created_at", ""),
            reverse=True,
        )
        if DEFAULT_PROFILE_NAME in names:
            names.remove(DEFAULT_PROFILE_NAME)
            names.insert(0, DEFAULT_PROFILE_NAME)
        elif not names:
            # Ensure at least Default exists
            self._active_profile_data()
            names = [DEFAULT_PROFILE_NAME]
        self._profile_names_cache = names
        return names

    def switch_profile(self, name: str) -> None:
        """Switch to the named profile, creating it with defaults if missing."""
        profiles = self._profiles_dict()
        if name not in profiles:
            profiles[name] = dict(self._default_profile_values())
            profiles[name]["_created_at"] = _now_iso()
        self._data["active_profile"] = name
        self._save()
        logger.info("Switched to profile %r", name)

    def create_profile(self, name: str, clone_from: str | None = None) -> None:
        """Create a new profile, optionally cloning values from another profile."""
        profiles = self._profiles_dict()
        if clone_from and clone_from in profiles:
            profiles[name] = copy.deepcopy(profiles[clone_from])
        else:
            profiles[name] = dict(self._default_profile_values())
        profiles[name]["_created_at"] = _now_iso()
        self._data["active_profile"] = name
        self._save()
        logger.info("Created profile %r (cloned from %r)", name, clone_from)

    def rename_profile(self, old_name: str, new_name: str) -> None:
        """Rename a profile. Cannot rename the Default profile."""
        if old_name == DEFAULT_PROFILE_NAME:
            return
        profiles = self._profiles_dict()
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
        profiles = self._profiles_dict()
        profiles.pop(name, None)
        if self._data.get("active_profile") == name:
            self._data["active_profile"] = DEFAULT_PROFILE_NAME
        self._save()
        logger.info("Deleted profile %r", name)

    # -- internals ------------------------------------------------------------

    def _profiles_dict(self) -> dict[str, Any]:
        """Return the profiles container, creating it if missing."""
        return self._data.setdefault("profiles", {})

    def _default_profile_values(self) -> dict[str, Any]:
        """Return default values for a new profile."""
        return {k: copy.deepcopy(_DEFAULTS[k]) for k in PROFILE_KEYS if k in _DEFAULTS}

    def _active_profile_data(self) -> dict[str, Any]:
        """Return the dict for the current active profile, creating if missing."""
        profiles = self._profiles_dict()
        name = self.active_profile_name
        if name not in profiles:
            profiles[name] = dict(self._default_profile_values())
            profiles[name]["_created_at"] = _now_iso()
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
            self._profiles_dict()[DEFAULT_PROFILE_NAME] = profile_values
            self._data.setdefault("active_profile", DEFAULT_PROFILE_NAME)
            self._save()
            logger.info("Migrated existing config into Default profile")

    def _migrate_profile_timestamps(self) -> None:
        """Ensure every profile has a ``_created_at`` timestamp."""
        profiles: dict = self._data.get("profiles", {})
        changed = False
        for prof in profiles.values():
            if "_created_at" not in prof:
                prof["_created_at"] = _LEGACY_TIMESTAMP
                changed = True
        if changed:
            self._save()

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
        self._migrate_profile_timestamps()
        self._profile_names_cache = None

    def _save(self) -> None:
        self._dirty = True
        self._profile_names_cache = None
        if not self._deferred:
            self._write()

    def _write(self) -> None:
        try:
            if not self._dir_created:
                self._dir.mkdir(parents=True, exist_ok=True)
                self._dir_created = True
            with open(self._path, "w", encoding="utf-8") as fh:
                json.dump(self._data, fh, indent=2, default=str)
            self._dirty = False
        except OSError as exc:
            logger.warning("Failed to save config to %s: %s", self._path, exc)
