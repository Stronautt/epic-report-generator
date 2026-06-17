"""Tests for reusable UI widgets (FR-13 customize, FR-14 re-ordering)."""

from __future__ import annotations

from epic_report_generator.core.data_models import ChildOverride
from epic_report_generator.ui.widgets import ChildCustomizeDialog, ReportItemTable


def _make_table(qtbot, *keys: str) -> ReportItemTable:
    table = ReportItemTable()
    qtbot.addWidget(table)
    table.set_items(
        [
            {"kind": "epic", "key": k, "display_name": "", "scope_certainty": ""}
            for k in keys
        ]
    )
    return table


def _keys(table: ReportItemTable) -> list[str]:
    return [d["key"] for d in table.get_items_as_dicts()]


def test_move_row_reorders_and_persists(qtbot):
    """Moving a row changes the persisted/report order and emits the signal."""
    table = _make_table(qtbot, "PROJ-1", "PROJ-2", "PROJ-3")
    assert _keys(table) == ["PROJ-1", "PROJ-2", "PROJ-3"]

    with qtbot.waitSignal(table.items_changed, timeout=1000):
        table.move_row(0, 2)  # drag PROJ-1 to the bottom

    assert _keys(table) == ["PROJ-2", "PROJ-3", "PROJ-1"]
    # get_items() drives the report, so its order must match too.
    assert [item.key for item in table.get_items()] == ["PROJ-2", "PROJ-3", "PROJ-1"]


def test_move_row_to_top(qtbot):
    table = _make_table(qtbot, "PROJ-1", "PROJ-2", "PROJ-3")
    table.move_row(2, 0)  # drag PROJ-3 to the top
    assert _keys(table) == ["PROJ-3", "PROJ-1", "PROJ-2"]


def test_move_row_noop_when_index_unchanged(qtbot):
    table = _make_table(qtbot, "PROJ-1", "PROJ-2")
    received: list[int] = []
    table.items_changed.connect(lambda: received.append(1))
    table.move_row(0, 0)
    assert _keys(table) == ["PROJ-1", "PROJ-2"]
    assert received == []  # no spurious persist


def test_move_row_clamps_out_of_range_index(qtbot):
    table = _make_table(qtbot, "PROJ-1", "PROJ-2", "PROJ-3")
    table.move_row(0, 99)  # clamped to the last position
    assert _keys(table) == ["PROJ-2", "PROJ-3", "PROJ-1"]
    table.move_row(5, 0)  # invalid source index: ignored
    assert _keys(table) == ["PROJ-2", "PROJ-3", "PROJ-1"]


# -- FR-13: per-child overrides ----------------------------------------------


def test_child_overrides_round_trip(qtbot):
    """Per-child overrides survive set_items → get_items / get_items_as_dicts."""
    table = ReportItemTable()
    qtbot.addWidget(table)
    table.set_items(
        [
            {
                "kind": "label",
                "key": "team-x",
                "display_name": "Team X",
                "scope_certainty": "",
                "child_overrides": {
                    "PROJ-1": {"display_name": "Auth", "scope_certainty": "High"}
                },
            }
        ]
    )

    persisted = table.get_items_as_dicts()[0]["child_overrides"]
    assert persisted == {"PROJ-1": {"display_name": "Auth", "scope_certainty": "High"}}

    item = table.get_items()[0]
    assert item.child_overrides["PROJ-1"].display_name == "Auth"
    assert item.child_overrides["PROJ-1"].scope_certainty == "High"


def test_set_child_overrides_persists(qtbot):
    """Writing overrides back onto a row emits items_changed for persistence."""
    table = _make_table(qtbot, "PROJ-1")
    row = table._rows[0]
    with qtbot.waitSignal(table.items_changed, timeout=1000):
        row.set_child_overrides({"PROJ-1-1": ChildOverride("Login", "Low")})
    stored = table.get_items_as_dicts()[0]["child_overrides"]
    assert stored["PROJ-1-1"] == {"display_name": "Login", "scope_certainty": "Low"}


def test_edit_requested_propagates(qtbot):
    """A row's edit request bubbles up through the table signal with the row."""
    table = _make_table(qtbot, "PROJ-1")
    row = table._rows[0]
    with qtbot.waitSignal(table.edit_requested, timeout=1000) as blocker:
        row.edit_requested.emit(row)
    assert blocker.args == [row]


def test_kind_toggle_clears_stale_overrides(qtbot):
    """Switching epic↔label drops overrides keyed by the old kind's children."""
    table = ReportItemTable()
    qtbot.addWidget(table)
    table.set_items(
        [
            {
                "kind": "label",
                "key": "team-x",
                "display_name": "Team X",
                "scope_certainty": "",
                "child_overrides": {
                    "PROJ-1": {"display_name": "Auth", "scope_certainty": "High"}
                },
            }
        ]
    )
    row = table._rows[0]
    assert row.get_child_overrides()  # populated by set_items, no clear on restore

    row.kind_combo.setCurrentIndex(row.kind_combo.findData("epic"))
    assert row.get_child_overrides() == {}


def test_customize_dialog_collects_overrides(qtbot):
    dlg = ChildCustomizeDialog(
        kind="label",
        parent_key="team-x",
        parent_certainty="",
        children=[("PROJ-1", "Auth"), ("PROJ-2", "Billing")],
        overrides={},
    )
    qtbot.addWidget(dlg)
    dlg._name_edits["PROJ-1"].setText("Authentication")
    combo = dlg._cert_combos["PROJ-2"]
    combo.setCurrentIndex(combo.findData("High"))

    out = dlg.get_overrides()
    assert out["PROJ-1"].display_name == "Authentication"
    assert out["PROJ-1"].scope_certainty is None
    assert out["PROJ-2"].scope_certainty == "High"


def test_customize_dialog_locks_certainty_when_parent_set(qtbot):
    dlg = ChildCustomizeDialog(
        kind="label",
        parent_key="team-x",
        parent_certainty="Medium",
        children=[("PROJ-1", "Auth")],
        overrides={},
    )
    qtbot.addWidget(dlg)
    assert not dlg._cert_combos["PROJ-1"].isEnabled()
    dlg._name_edits["PROJ-1"].setText("Auth v2")

    out = dlg.get_overrides()
    # Certainty is owned by the parent, so it is never recorded as a child override.
    assert out["PROJ-1"].scope_certainty is None
    assert out["PROJ-1"].display_name == "Auth v2"


def test_customize_dialog_summary_is_selectable(qtbot):
    """Child summaries must be selectable so they can be copied into a name."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QLabel

    dlg = ChildCustomizeDialog(
        kind="epic",
        parent_key="PROJ-1",
        parent_certainty="",
        children=[("PROJ-1-1", "Implement login flow")],
        overrides={},
    )
    qtbot.addWidget(dlg)

    summary_labels = [
        lbl for lbl in dlg.findChildren(QLabel) if lbl.text() == "Implement login flow"
    ]
    assert summary_labels, "summary label not found"
    flags = summary_labels[0].textInteractionFlags()
    assert flags & Qt.TextInteractionFlag.TextSelectableByMouse


def test_customize_dialog_prefills_existing(qtbot):
    dlg = ChildCustomizeDialog(
        kind="epic",
        parent_key="PROJ-1",
        parent_certainty="",
        children=[("PROJ-1-1", "Login")],
        overrides={"PROJ-1-1": ChildOverride("Sign in", "Low")},
    )
    qtbot.addWidget(dlg)
    assert dlg._name_edits["PROJ-1-1"].text() == "Sign in"
    assert dlg._cert_combos["PROJ-1-1"].currentData() == "Low"
