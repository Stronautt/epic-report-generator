"""Tests for epic_report_generator.services.config_manager."""

from __future__ import annotations

import json
from pathlib import Path

from epic_report_generator.services.config_manager import ConfigManager


def _make_manager(tmp_path: Path) -> ConfigManager:
    """Create a ConfigManager pointing at *tmp_path* for isolation."""
    mgr = ConfigManager()
    mgr._dir = tmp_path
    mgr._path = tmp_path / "config.json"
    mgr.reset()
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
        mgr2 = ConfigManager()
        mgr2._dir = tmp_path
        mgr2._path = tmp_path / "config.json"
        mgr2._data = {}
        mgr2._load()
        assert mgr2.get("theme") == "dark"
        assert mgr2.get("jira_url") == "https://company.atlassian.net"

    def test_reset_restores_defaults(self, tmp_path: Path) -> None:
        mgr = _make_manager(tmp_path)
        mgr.set("theme", "dark")
        mgr.reset()
        assert mgr.get("theme") == "light"

    def test_corrupt_file_does_not_crash(self, tmp_path: Path) -> None:
        config_path = tmp_path / "config.json"
        config_path.write_text("NOT JSON {{{", encoding="utf-8")

        mgr = ConfigManager()
        mgr._dir = tmp_path
        mgr._path = config_path
        mgr._data = {"theme": "light"}
        mgr._load()
        # Should not raise; data stays at prior state
        assert mgr.get("theme") == "light"

    def test_list_values_persist(self, tmp_path: Path) -> None:
        mgr = _make_manager(tmp_path)
        mgr.set("last_epic_keys", ["PROJ-1", "PROJ-2"])

        raw = json.loads((tmp_path / "config.json").read_text())
        assert raw["last_epic_keys"] == ["PROJ-1", "PROJ-2"]
