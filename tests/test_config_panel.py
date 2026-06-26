"""Tests for epic_report_generator.ui.config_panel (issue-type metadata cache)."""

from __future__ import annotations

import base64
import copy
from pathlib import Path

from epic_report_generator.core.jira_client import JiraClient
from epic_report_generator.services.auth_manager import AuthManager
from epic_report_generator.services.config_manager import _DEFAULTS, ConfigManager
from epic_report_generator.ui.config_panel import ConfigPanel


def _manager(tmp_path: Path) -> ConfigManager:
    """A ConfigManager isolated to *tmp_path* (mirrors test_config_manager)."""
    mgr = ConfigManager.__new__(ConfigManager)
    mgr._dir = tmp_path
    mgr._path = tmp_path / "config.json"
    mgr._dir_created = False
    mgr._data = copy.deepcopy(_DEFAULTS)
    return mgr


def _panel(qtbot, cfg: ConfigManager) -> ConfigPanel:
    panel = ConfigPanel(cfg, JiraClient(AuthManager(cfg)))
    qtbot.addWidget(panel)
    return panel


_TYPES = [
    {"id": "10000", "name": "Epic", "subtask": False, "hierarchyLevel": 1},
    {"id": "10001", "name": "Story", "subtask": False, "hierarchyLevel": 0},
    {"id": "10002", "name": "Sub-task", "subtask": True, "hierarchyLevel": -1},
]


def test_hierarchy_type_cache_roundtrip(qtbot, tmp_path):
    """A persisted cache populates the editor with icon bytes intact (no fetch)."""
    cfg = _manager(tmp_path)
    cfg.set("cloud_id", "CID")
    cfg.set(
        "issue_type_cache",
        {
            "cloud_id": "CID",
            "types": _TYPES,
            "link_types": [{"id": "1", "name": "Blocks"}],
            "icons": {"10000": base64.b64encode(b"<svg/>").decode()},
        },
    )
    panel = _panel(qtbot, cfg)
    assert panel._load_cached_hierarchy_types() is True
    assert panel._hierarchy_types_loaded is True
    ed = panel._hierarchy_editor
    assert ed.has_types()
    assert ed._icons["10000"] == b"<svg/>"  # base64 → bytes round-trip


def test_hierarchy_type_cache_skips_other_site(qtbot, tmp_path):
    """A cache stamped with a different cloud_id is ignored when connected."""
    cfg = _manager(tmp_path)
    cfg.set("cloud_id", "NEW")
    cfg.set(
        "issue_type_cache",
        {"cloud_id": "OLD", "types": _TYPES, "link_types": [], "icons": {}},
    )
    panel = _panel(qtbot, cfg)
    assert panel._load_cached_hierarchy_types() is False
    assert panel._hierarchy_types_loaded is False


def test_hierarchy_type_cache_absent(qtbot, tmp_path):
    """No cache → nothing loaded (caller then fetches when connected)."""
    panel = _panel(qtbot, _manager(tmp_path))
    assert panel._load_cached_hierarchy_types() is False


_PNG_1x1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000a49444154789c63000100000500010d0a2db40000000049454e44ae426082"
)


def test_apply_item_icons_epic_and_label(qtbot, tmp_path):
    """Cached icons + resolved type ids paint epic rows; labels get the tag."""
    cfg = _manager(tmp_path)
    cfg.set(
        "issue_type_cache",
        {
            "cloud_id": "",
            "types": _TYPES,
            "link_types": [],
            "icons": {"10000": base64.b64encode(_PNG_1x1).decode()},
        },
    )
    panel = _panel(qtbot, cfg)
    panel._item_table.set_items(
        [{"kind": "epic", "key": "HHP-1"}, {"kind": "label", "key": "mobile"}]
    )
    panel._item_type_ids["HHP-1"] = "10000"  # pretend the lookup resolved
    panel._apply_item_icons()
    rows = panel._item_table.rows
    assert not rows[0].type_icon_lbl.pixmap().isNull()  # epic → resolved type icon
    assert not rows[1].type_icon_lbl.pixmap().isNull()  # label → tag glyph


# Child tier-filtering moved from config_panel._included_children into the
# tier-aware JiraClient.fetch_child_summaries — see test_jira_client.py
# (TestChainAwareChildSummaries).
