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


def _child_row(dlg: ChildCustomizeDialog, key: str):
    """Return the dialog's _ChildRow for *key*."""
    return next(r for r in dlg._list.rows if r.key == key)


def _set_cert(row, data: str) -> None:
    """Select the certainty whose data value is *data* on a row's combo."""
    row.cert_combo.setCurrentIndex(row.cert_combo.findData(data))


def test_customize_dialog_collects_overrides(qtbot):
    dlg = ChildCustomizeDialog(
        kind="label",
        parent_key="team-x",
        parent_certainty="",
        children=[("PROJ-1", "Auth"), ("PROJ-2", "Billing")],
        overrides={},
    )
    qtbot.addWidget(dlg)
    _child_row(dlg, "PROJ-1").name_edit.setText("Authentication")
    _set_cert(_child_row(dlg, "PROJ-2"), "High")

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
    row = _child_row(dlg, "PROJ-1")
    # Certainty is owned by the parent: the combo is disabled and preset to it.
    assert not row.cert_combo.isEnabled()
    assert row.cert_combo.currentData() == "Medium"
    row.name_edit.setText("Auth v2")

    out = dlg.get_overrides()
    # Locked certainty is never recorded as a child override.
    assert out["PROJ-1"].scope_certainty is None
    assert out["PROJ-1"].display_name == "Auth v2"


def test_customize_dialog_name_placeholder_shows_summary(qtbot):
    """The display-name editor shows the Jira summary as inactive placeholder."""
    dlg = ChildCustomizeDialog(
        kind="epic",
        parent_key="PROJ-1",
        parent_certainty="",
        children=[("PROJ-1-1", "Implement login flow")],
        overrides={},
    )
    qtbot.addWidget(dlg)
    row = _child_row(dlg, "PROJ-1-1")
    assert row.name_edit.text() == ""  # no override yet
    assert row.name_edit.placeholderText() == "Implement login flow"


def test_customize_dialog_prefills_existing(qtbot):
    dlg = ChildCustomizeDialog(
        kind="epic",
        parent_key="PROJ-1",
        parent_certainty="",
        children=[("PROJ-1-1", "Login")],
        overrides={"PROJ-1-1": ChildOverride("Sign in", "Low")},
    )
    qtbot.addWidget(dlg)
    row = _child_row(dlg, "PROJ-1-1")
    assert row.name_edit.text() == "Sign in"
    assert row.cert_combo.currentData() == "Low"
    # And it round-trips back out unchanged.
    assert dlg.get_overrides() == {"PROJ-1-1": ChildOverride("Sign in", "Low")}


def test_customize_dialog_consolidated_per_child_certainty(qtbot):
    """With no parent certainty, each child's certainty is recorded individually."""
    dlg = ChildCustomizeDialog(
        kind="label",
        parent_key="team-x",
        parent_certainty="",
        children=[("PROJ-1", "A"), ("PROJ-2", "B")],
        overrides={},
    )
    qtbot.addWidget(dlg)
    _child_row(dlg, "PROJ-1").name_edit.setText("Renamed")
    _set_cert(_child_row(dlg, "PROJ-2"), "High")

    out = dlg.get_overrides()
    assert out["PROJ-1"] == ChildOverride(display_name="Renamed", scope_certainty=None)
    assert out["PROJ-2"] == ChildOverride(display_name="", scope_certainty="High")


def test_customize_dialog_empty_children(qtbot):
    dlg = ChildCustomizeDialog(
        kind="label",
        parent_key="team-x",
        parent_certainty="",
        children=[],
        overrides={},
    )
    qtbot.addWidget(dlg)
    assert dlg.get_overrides() == {}
    assert dlg.get_child_order() == []


def test_customize_dialog_opens_in_saved_child_order(qtbot):
    """A saved child_order rearranges the rows; unknown keys fall to the end."""
    dlg = ChildCustomizeDialog(
        kind="label",
        parent_key="team-x",
        parent_certainty="",
        children=[("PROJ-1", "A"), ("PROJ-2", "B"), ("PROJ-3", "C")],
        overrides={},
        child_order=["PROJ-3", "PROJ-1"],  # PROJ-2 not listed → appended last
    )
    qtbot.addWidget(dlg)
    assert dlg.get_child_order() == ["PROJ-3", "PROJ-1", "PROJ-2"]


def test_customize_dialog_reorder_updates_child_order(qtbot):
    """Reordering rows changes get_child_order while overrides stay keyed right."""
    dlg = ChildCustomizeDialog(
        kind="label",
        parent_key="team-x",
        parent_certainty="",
        children=[("PROJ-1", "A"), ("PROJ-2", "B"), ("PROJ-3", "C")],
        overrides={},
    )
    qtbot.addWidget(dlg)
    _child_row(dlg, "PROJ-1").name_edit.setText("Alpha")
    # Simulate a drag that moves the first row to the bottom.
    dlg._list._reposition(0, 2)

    assert dlg.get_child_order() == ["PROJ-2", "PROJ-3", "PROJ-1"]
    # Override still attached to its key after the move.
    assert dlg.get_overrides() == {"PROJ-1": ChildOverride("Alpha", None)}


def test_order_children_helper():
    from epic_report_generator.ui.widgets import _order_children

    children = [("A", "a"), ("B", "b"), ("C", "c")]
    assert _order_children(children, []) == children  # empty = untouched
    assert _order_children(children, ["C", "A"]) == [("C", "c"), ("A", "a"), ("B", "b")]


# -- Include checkbox + per-epic nested settings -----------------------------


def test_child_rows_default_to_included(qtbot):
    """Every child row starts with Include ticked (kept in the report)."""
    dlg = ChildCustomizeDialog(
        kind="epic",
        parent_key="PROJ-1",
        parent_certainty="",
        children=[("PROJ-1-1", "Login")],
        overrides={},
    )
    qtbot.addWidget(dlg)
    assert _child_row(dlg, "PROJ-1-1").include_check.isChecked()
    # A default-included row with no other edits records no override at all.
    assert dlg.get_overrides() == {}


def test_unticking_include_records_exclusion(qtbot):
    """Unchecking Include records an override even with no name/certainty set."""
    dlg = ChildCustomizeDialog(
        kind="epic",
        parent_key="PROJ-1",
        parent_certainty="",
        children=[("PROJ-1-1", "Login")],
        overrides={},
    )
    qtbot.addWidget(dlg)
    row = _child_row(dlg, "PROJ-1-1")
    row.include_check.setChecked(False)
    out = dlg.get_overrides()
    assert out["PROJ-1-1"].include is False
    # Excluding greys out the row's other controls, mutes its text, and locks drag.
    assert not row.name_edit.isEnabled()
    assert not row.drag_handle.isEnabled()
    assert "color" in row._key_lbl.styleSheet()
    assert "color" in row._sum_lbl.styleSheet()
    # Re-including restores everything.
    row.include_check.setChecked(True)
    assert row.name_edit.isEnabled()
    assert row.drag_handle.isEnabled()
    assert row._key_lbl.styleSheet() == ""


def test_include_prefilled_from_override(qtbot):
    dlg = ChildCustomizeDialog(
        kind="label",
        parent_key="team-x",
        parent_certainty="",
        children=[("PROJ-1", "A")],
        overrides={"PROJ-1": ChildOverride(include=False)},
    )
    qtbot.addWidget(dlg)
    assert not _child_row(dlg, "PROJ-1").include_check.isChecked()


def test_include_serialization_round_trip(qtbot):
    """include=False survives the to_dict / set_items round-trip; True is omitted."""
    table = ReportItemTable()
    qtbot.addWidget(table)
    table.set_items(
        [
            {
                "kind": "epic",
                "key": "PROJ-1",
                "display_name": "",
                "scope_certainty": "",
                "child_overrides": {
                    "PROJ-1-1": {
                        "display_name": "",
                        "scope_certainty": "",
                        "include": False,
                    }
                },
            }
        ]
    )
    stored = table.get_items_as_dicts()[0]["child_overrides"]
    assert stored["PROJ-1-1"]["include"] is False
    item = table.get_items()[0]
    assert item.child_overrides["PROJ-1-1"].include is False


def test_settings_gear_only_for_label_children(qtbot):
    """The per-epic settings gear appears for label children (epics) only."""
    label_dlg = ChildCustomizeDialog(
        kind="label",
        parent_key="team-x",
        parent_certainty="",
        children=[("PROJ-1", "A")],
        overrides={},
    )
    qtbot.addWidget(label_dlg)
    assert _child_row(label_dlg, "PROJ-1").settings_btn is not None

    epic_dlg = ChildCustomizeDialog(
        kind="epic",
        parent_key="PROJ-1",
        parent_certainty="",
        children=[("PROJ-1-1", "Login")],
        overrides={},
    )
    qtbot.addWidget(epic_dlg)
    assert _child_row(epic_dlg, "PROJ-1-1").settings_btn is None


def test_child_settings_requested_emits_row(qtbot):
    """Clicking an epic row's gear emits child_settings_requested with that row."""
    dlg = ChildCustomizeDialog(
        kind="label",
        parent_key="team-x",
        parent_certainty="",
        children=[("PROJ-1", "A")],
        overrides={},
    )
    qtbot.addWidget(dlg)
    row = _child_row(dlg, "PROJ-1")
    with qtbot.waitSignal(dlg.child_settings_requested, timeout=1000) as blocker:
        row.settings_btn.click()
    assert blocker.args == [row]


def test_effective_certainty(qtbot):
    """A locked row hands down the parent value; an open one its own selection."""
    locked = ChildCustomizeDialog(
        kind="label",
        parent_key="team-x",
        parent_certainty="High",
        children=[("PROJ-1", "A")],
        overrides={},
    )
    qtbot.addWidget(locked)
    assert _child_row(locked, "PROJ-1").effective_certainty() == "High"

    free = ChildCustomizeDialog(
        kind="label",
        parent_key="team-x",
        parent_certainty="",
        children=[("PROJ-1", "A")],
        overrides={},
    )
    qtbot.addWidget(free)
    row = _child_row(free, "PROJ-1")
    assert row.effective_certainty() == ""  # "--"
    _set_cert(row, "Low")
    assert row.effective_certainty() == "Low"


def test_child_row_nested_overrides_round_trip(qtbot):
    """set_nested rides along on the row's ChildOverride through get_overrides."""
    dlg = ChildCustomizeDialog(
        kind="label",
        parent_key="team-x",
        parent_certainty="",
        children=[("PROJ-1", "A")],
        overrides={},
    )
    qtbot.addWidget(dlg)
    row = _child_row(dlg, "PROJ-1")
    row.set_nested({"PROJ-1-1": ChildOverride("Login", "Low")}, ["PROJ-1-2", "PROJ-1-1"])
    out = dlg.get_overrides()
    assert out["PROJ-1"].child_overrides["PROJ-1-1"] == ChildOverride("Login", "Low")
    assert out["PROJ-1"].child_order == ["PROJ-1-2", "PROJ-1-1"]


def test_nested_overrides_persist_through_table(qtbot):
    """Nested per-epic overrides survive the table to_dict / set_items round-trip."""
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
                    "PROJ-1": {
                        "display_name": "Auth",
                        "scope_certainty": "",
                        "child_overrides": {
                            "PROJ-1-1": {"display_name": "Login", "scope_certainty": "High"}
                        },
                        "child_order": ["PROJ-1-2", "PROJ-1-1"],
                    }
                },
            }
        ]
    )
    stored = table.get_items_as_dicts()[0]["child_overrides"]["PROJ-1"]
    assert stored["child_overrides"] == {
        "PROJ-1-1": {"display_name": "Login", "scope_certainty": "High"}
    }
    assert stored["child_order"] == ["PROJ-1-2", "PROJ-1-1"]

    item = table.get_items()[0]
    nested = item.child_overrides["PROJ-1"]
    assert nested.child_overrides["PROJ-1-1"].display_name == "Login"
    assert nested.child_overrides["PROJ-1-1"].scope_certainty == "High"
    assert nested.child_order == ["PROJ-1-2", "PROJ-1-1"]


def test_report_item_child_order_persists(qtbot):
    """child_order survives the to_dict / set_items round-trip and reaches ReportItem."""
    table = ReportItemTable()
    qtbot.addWidget(table)
    table.set_items(
        [
            {
                "kind": "label",
                "key": "team-x",
                "display_name": "Team X",
                "scope_certainty": "",
                "child_overrides": {},
                "child_order": ["PROJ-3", "PROJ-1", "PROJ-2"],
            }
        ]
    )
    dumped = table.get_items_as_dicts()
    assert dumped[0]["child_order"] == ["PROJ-3", "PROJ-1", "PROJ-2"]
    assert table.get_items()[0].child_order == ["PROJ-3", "PROJ-1", "PROJ-2"]
