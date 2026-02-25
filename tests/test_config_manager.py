"""Tests for epic_report_generator.services.config_manager."""

from __future__ import annotations

import json
import time
from pathlib import Path

from epic_report_generator.services.config_manager import (
    _LEGACY_TIMESTAMP,
    ConfigManager,
    DEFAULT_PROFILE_NAME,
)


def _make_manager(tmp_path: Path) -> ConfigManager:
    """Create a ConfigManager pointing at *tmp_path* for isolation."""
    mgr = ConfigManager.__new__(ConfigManager)
    mgr._dir = tmp_path
    mgr._path = tmp_path / "config.json"
    mgr._dir_created = False
    import copy

    from epic_report_generator.services.config_manager import _DEFAULTS

    mgr._data = copy.deepcopy(_DEFAULTS)
    return mgr


class TestDefaults:
    """Config should ship with sensible defaults."""

    def test_callback_port(self, tmp_path: Path) -> None:
        mgr = _make_manager(tmp_path)
        assert mgr.get("callback_port") == 18492

    def test_theme(self, tmp_path: Path) -> None:
        mgr = _make_manager(tmp_path)
        assert mgr.get("theme") == "light"

    def test_auth_method_empty(self, tmp_path: Path) -> None:
        mgr = _make_manager(tmp_path)
        assert mgr.get("auth_method") == ""

    def test_story_points_field(self, tmp_path: Path) -> None:
        mgr = _make_manager(tmp_path)
        assert mgr.get("story_points_field") == "story_points"

    def test_missing_key_returns_default(self, tmp_path: Path) -> None:
        mgr = _make_manager(tmp_path)
        assert mgr.get("nonexistent", "fallback") == "fallback"


class TestSetAndGet:
    """Setting values should persist and be retrievable."""

    def test_set_single(self, tmp_path: Path) -> None:
        mgr = _make_manager(tmp_path)
        mgr.set("theme", "dark")
        assert mgr.get("theme") == "dark"

    def test_update_bulk(self, tmp_path: Path) -> None:
        mgr = _make_manager(tmp_path)
        mgr.update({"jira_url": "https://x.atlassian.net", "jira_email": "a@b.com"})
        assert mgr.get("jira_url") == "https://x.atlassian.net"
        assert mgr.get("jira_email") == "a@b.com"

    def test_data_property_returns_copy(self, tmp_path: Path) -> None:
        mgr = _make_manager(tmp_path)
        data = mgr.data
        data["theme"] = "dark"
        assert mgr.get("theme") == "light"  # original unchanged


class TestPersistence:
    """Config should persist to and load from disk."""

    def test_round_trip(self, tmp_path: Path) -> None:
        mgr = _make_manager(tmp_path)
        mgr.set("theme", "dark")
        mgr.set("jira_url", "https://company.atlassian.net")

        # Create a fresh manager reading from the same file
        mgr2 = _make_manager(tmp_path)
        mgr2._load()
        assert mgr2.get("theme") == "dark"
        assert mgr2.get("jira_url") == "https://company.atlassian.net"

    def test_reset_restores_defaults(self, tmp_path: Path) -> None:
        mgr = _make_manager(tmp_path)
        # Use a profile-scoped key since reset() only affects the active profile
        mgr.set("estimation_method", "time_days")
        assert mgr.get("estimation_method") == "time_days"
        mgr.reset()
        assert mgr.get("estimation_method") == "story_points"

    def test_corrupt_file_does_not_crash(self, tmp_path: Path) -> None:
        config_path = tmp_path / "config.json"
        config_path.write_text("NOT JSON {{{", encoding="utf-8")

        mgr = _make_manager(tmp_path)
        mgr._load()
        # Should not raise; defaults survive corrupt file
        assert mgr.get("theme") == "light"

    def test_list_values_persist(self, tmp_path: Path) -> None:
        mgr = _make_manager(tmp_path)
        mgr.set("last_epic_keys", ["PROJ-1", "PROJ-2"])

        raw = json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))
        assert raw["last_epic_keys"] == ["PROJ-1", "PROJ-2"]


class TestProfileTimestamps:
    """Profile _created_at timestamps and sort order."""

    def test_create_profile_stamps_created_at(self, tmp_path: Path) -> None:
        mgr = _make_manager(tmp_path)
        mgr.create_profile("Alpha")
        profiles = mgr._data["profiles"]
        assert "_created_at" in profiles["Alpha"]

    def test_clone_gets_own_timestamp(self, tmp_path: Path) -> None:
        mgr = _make_manager(tmp_path)
        mgr.create_profile("Source")
        source_ts = mgr._data["profiles"]["Source"]["_created_at"]
        time.sleep(0.01)
        mgr.create_profile("Clone", clone_from="Source")
        clone_ts = mgr._data["profiles"]["Clone"]["_created_at"]
        assert clone_ts >= source_ts  # clone is same or newer

    def test_rename_preserves_timestamp(self, tmp_path: Path) -> None:
        mgr = _make_manager(tmp_path)
        mgr.create_profile("OldName")
        ts = mgr._data["profiles"]["OldName"]["_created_at"]
        mgr.rename_profile("OldName", "NewName")
        assert mgr._data["profiles"]["NewName"]["_created_at"] == ts

    def test_profile_names_default_first_then_newest(self, tmp_path: Path) -> None:
        mgr = _make_manager(tmp_path)
        # Trigger Default profile creation
        mgr.get("estimation_method")
        # Create profiles with increasing timestamps
        mgr.create_profile("First")
        time.sleep(0.01)
        mgr.create_profile("Second")
        time.sleep(0.01)
        mgr.create_profile("Third")
        names = mgr.profile_names
        assert names[0] == DEFAULT_PROFILE_NAME
        # Remaining should be newest first
        assert names[1] == "Third"
        assert names[2] == "Second"
        assert names[3] == "First"

    def test_migration_adds_legacy_timestamp(self, tmp_path: Path) -> None:
        mgr = _make_manager(tmp_path)
        # Manually add a profile without _created_at
        mgr._data.setdefault("profiles", {})["Legacy"] = {"estimation_method": "story_points"}
        mgr._migrate_profile_timestamps()
        assert mgr._data["profiles"]["Legacy"]["_created_at"] == _LEGACY_TIMESTAMP

    def test_reset_preserves_timestamp(self, tmp_path: Path) -> None:
        mgr = _make_manager(tmp_path)
        mgr.create_profile("Resettable")
        ts = mgr._data["profiles"]["Resettable"]["_created_at"]
        mgr.reset()
        assert mgr._data["profiles"]["Resettable"]["_created_at"] == ts
