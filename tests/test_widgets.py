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
    from epic_report_generator.core.data_models import order_by_keys

    children = [("A", "a"), ("B", "b"), ("C", "c")]
    # empty = untouched
    assert order_by_keys(children, [], key=lambda c: c[0]) == children
    assert order_by_keys(children, ["C", "A"], key=lambda c: c[0]) == [
        ("C", "c"),
        ("A", "a"),
        ("B", "b"),
    ]


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


def test_settings_gear_gated_by_tier(qtbot):
    """The drill-in gear shows while children sit above Sub-task (tier < 2).

    Strict tier nesting: an Epic's Story rows (tier 1) and a label's Epic rows
    (tier 0) are drillable; a Story's Sub-task rows (tier 2) are leaves.
    """
    epic_dlg = ChildCustomizeDialog(  # epic item → Story children (tier 1)
        kind="epic",
        parent_key="PROJ-1",
        parent_certainty="",
        children=[("PROJ-2", "Login")],
        overrides={},
    )
    qtbot.addWidget(epic_dlg)
    assert epic_dlg.children_tier == 1
    assert _child_row(epic_dlg, "PROJ-2").settings_btn is not None

    subtask_dlg = ChildCustomizeDialog(  # story → Sub-task children (tier 2)
        kind="epic",
        parent_key="PROJ-2",
        parent_certainty="",
        children=[("PROJ-3", "Write test")],
        overrides={},
        children_tier=2,
    )
    qtbot.addWidget(subtask_dlg)
    assert _child_row(subtask_dlg, "PROJ-3").settings_btn is None


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


# -- Task 7: IssueHierarchyEditor --------------------------------------------

from epic_report_generator.core.data_models import HierarchyNode
from epic_report_generator.ui.widgets import IssueHierarchyEditor, cascade_flags

_TYPES = [
    {"id": "10000", "name": "Epic", "subtask": False, "hierarchyLevel": 1},
    {"id": "10001", "name": "Story", "subtask": False, "hierarchyLevel": 0},
    {"id": "10002", "name": "Sub-task", "subtask": True, "hierarchyLevel": -1},
    {"id": "10003", "name": "Bug", "subtask": False, "hierarchyLevel": 0},
]
_LINKS = [{"id": "1", "name": "Blocks", "inward": "is blocked by", "outward": "blocks"}]


def _editor(qtbot) -> IssueHierarchyEditor:
    ed = IssueHierarchyEditor()
    qtbot.addWidget(ed)
    ed.set_types(_TYPES, _LINKS, {})
    return ed


def _all_cards(ed: IssueHierarchyEditor) -> list:
    """Every card across the three silos, in tier-then-position order."""
    return [c for silo in ed._silos for c in silo.cards]


def test_cascade_flags_pure_helper():
    assert cascade_flags([], []) == []
    # All on → all enabled.
    assert cascade_flags([True, True, True], [0, 1, 2]) == [True, True, True]
    # A whole ancestor tier off greys every deeper tier (tier 0 off → 1 & 2).
    assert cascade_flags([False, True, True], [0, 1, 2]) == [True, False, False]
    # Same-tier siblings never gate each other: one tier-1 node off, the other on
    # → nothing below greys (tier 1 still has a shown node).
    assert cascade_flags([True, True, False, True], [0, 1, 1, 2]) == [
        True,
        True,
        True,
        True,
    ]
    # Both tier-1 nodes off → tier-1 stays editable, only the deeper tier-2 greys.
    assert cascade_flags([True, False, False, True], [0, 1, 1, 2]) == [
        True,
        True,
        True,
        False,
    ]


def test_hierarchy_estimate_cascade_is_tier_based_not_positional(qtbot):
    """Unchecking one tier-1 Estimate must not grey its same-tier siblings."""
    ed = _editor(qtbot)
    ed.set_hierarchy(
        [
            HierarchyNode("10000", "Epic", display_tier=0),
            HierarchyNode("10001", "Story", display_tier=1),
            HierarchyNode("10003", "Bug", display_tier=1),
            HierarchyNode("10002", "Sub-task", display_tier=2),
        ]
    )
    story = ed._silos[1].cards[0]
    bug = ed._silos[1].cards[1]
    sub = ed._silos[2].cards[0]
    # Uncheck Story's Estimate — Bug (same tier) and Sub-task (tier 1 still
    # estimated via Bug) stay enabled. Positionally Bug/Sub are "below" Story.
    story.est_check.setChecked(False)
    assert bug.est_check.isEnabled()
    assert sub.est_check.isEnabled()
    # Uncheck Bug too — the whole Standard tier is now unestimated, so the deeper
    # Sub-task greys, but the tier-1 nodes themselves stay editable (re-checkable).
    bug.est_check.setChecked(False)
    assert not sub.est_check.isEnabled()
    assert story.est_check.isEnabled() and bug.est_check.isEnabled()
    # Every tier is still shown (Show defaults checked), so no Show toggle greys.
    assert all(c.show_check.isEnabled() for c in (story, bug, sub))


def test_hierarchy_editor_roundtrip(qtbot):
    """set_hierarchy → to_hierarchy preserves every node field."""
    ed = _editor(qtbot)
    chain = [
        HierarchyNode("10000", "Epic", display_tier=0),
        HierarchyNode(
            "10001", "Story", edge="link", link_types=["Blocks"], display_tier=1
        ),
        HierarchyNode("10002", "Sub-task", display_tier=2, show=False),
    ]
    ed.set_hierarchy(chain)
    out = ed.to_hierarchy()
    assert [
        (n.issue_type_id, n.edge, n.link_types, n.display_tier, n.show, n.in_estimate)
        for n in out
    ] == [
        ("10000", "parent", [], 0, True, True),
        ("10001", "link", ["Blocks"], 1, True, True),
        ("10002", "parent", [], 2, False, True),
    ]


# A valid 1×1 transparent PNG (PNG support is built into Qt, no plugin needed),
# so _pixmap_icon().isNull() is False and the leading icon actually attaches.
_PNG_1x1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000a49444154789c63000100000500010d0a2db40000000049454e44ae426082"
)


def test_report_item_row_epic_type_icon(qtbot):
    """An epic row shows the resolved type icon and clears when type unknown."""
    from epic_report_generator.ui.widgets import _ReportItemRow

    row = _ReportItemRow(kind="epic", key="HHP-1")
    qtbot.addWidget(row)
    assert row.type_icon_lbl.pixmap().isNull()
    row.set_type_icon(_PNG_1x1)
    assert not row.type_icon_lbl.pixmap().isNull()
    row.set_type_icon(None)  # type unknown again → icon cleared
    assert row.type_icon_lbl.pixmap().isNull()


def test_report_item_row_epic_display_name(qtbot):
    """Epic rows carry an editable display name that flows to the ReportItem."""
    from epic_report_generator.ui.widgets import _ReportItemRow

    row = _ReportItemRow(kind="epic", key="HHP-1", display_name="My Epic")
    qtbot.addWidget(row)
    assert row.name_edit.isEnabled()  # editable for epics (was disabled before)
    assert row.display_name == "My Epic"
    assert row.to_report_item().display_name == "My Epic"
    assert row.to_dict()["display_name"] == "My Epic"


def test_report_item_row_jira_summary_placeholder(qtbot):
    """An epic's Jira summary shows as the name placeholder, not a saved override."""
    from epic_report_generator.ui.widgets import _ReportItemRow

    row = _ReportItemRow(kind="epic", key="HHP-1")
    qtbot.addWidget(row)
    row.set_jira_summary("Alpha test")
    assert row.name_edit.placeholderText() == "Alpha test"
    assert row.display_name == ""  # placeholder only — no override persisted
    assert row.to_dict()["display_name"] == ""
    # The dialog title falls back to the summary when there's no override...
    assert row.effective_name == "Alpha test"
    row.name_edit.setText("Custom")  # ...and prefers a typed override
    assert row.effective_name == "Custom"


def test_report_item_row_label_tag_and_empty(qtbot):
    """A label row shows the tag glyph; an empty key shows nothing."""
    from epic_report_generator.ui.widgets import _ReportItemRow

    row = _ReportItemRow(kind="label", key="mobile")
    qtbot.addWidget(row)
    row.set_type_icon(None)  # labels ignore bytes — always the tag glyph
    assert not row.type_icon_lbl.pixmap().isNull()
    row.key_edit.setText("")  # no key → no icon
    row.set_type_icon(None)
    assert row.type_icon_lbl.pixmap().isNull()


def test_child_row_prepends_type_icon(qtbot):
    """A child row paints its issue-type icon when bytes are supplied."""
    from epic_report_generator.ui.widgets import _ChildRow

    with_icon = _ChildRow(
        "HHP-1", "Sum", None, cert_locked=False, parent_certainty="",
        icon_bytes=_PNG_1x1,
    )
    qtbot.addWidget(with_icon)
    assert not with_icon._icon_lbl.pixmap().isNull()
    without = _ChildRow("HHP-2", "Sum", None, cert_locked=False, parent_certainty="")
    qtbot.addWidget(without)
    assert without._icon_lbl.pixmap().isNull()


def test_node_lands_in_silo_matching_tier(qtbot):
    """Each node is placed in the silo whose tier matches its display_tier,
    and to_hierarchy emits them tier-then-position."""
    ed = _editor(qtbot)
    ed.set_hierarchy(
        [
            HierarchyNode("10000", "Epic", display_tier=0),
            HierarchyNode("10001", "Story", display_tier=1),
            HierarchyNode("10003", "Bug", display_tier=1),
            HierarchyNode("10002", "Sub-task", display_tier=2),
        ]
    )
    assert [c.type_id for c in ed._silos[0].cards] == ["10000"]
    assert [c.type_id for c in ed._silos[1].cards] == ["10001", "10003"]
    assert [c.type_id for c in ed._silos[2].cards] == ["10002"]
    assert [n.issue_type for n in ed.to_hierarchy()] == [
        "Epic",
        "Story",
        "Bug",
        "Sub-task",
    ]


def test_tier0_card_hides_relationship_selector(qtbot):
    """An Epic-tier card has no relationship selector (no tier above it); a
    deeper-tier card does."""
    from epic_report_generator.ui.widgets import _HierarchyItemCard

    epic = _HierarchyItemCard(
        HierarchyNode("10000", "Epic", display_tier=0), ["Blocks"], None
    )
    qtbot.addWidget(epic)
    assert not epic.rel.isVisibleTo(epic)
    story = _HierarchyItemCard(
        HierarchyNode("10001", "Story", display_tier=1), ["Blocks"], None
    )
    qtbot.addWidget(story)
    assert story.rel.isVisibleTo(story)


def test_card_show_estimate_round_trip(qtbot):
    """The Show / Estimate toggles flow back through to_node()."""
    from epic_report_generator.ui.widgets import _HierarchyItemCard

    card = _HierarchyItemCard(
        HierarchyNode("10001", "Story", display_tier=1), ["Blocks"], None
    )
    qtbot.addWidget(card)
    card.show_check.setChecked(False)
    card.est_check.setChecked(False)
    out = card.to_node()
    assert out.show is False and out.in_estimate is False


def test_relationship_button_parent_link_exclusive(qtbot):
    """Parent and link types are mutually exclusive; the last-link unselect
    falls back to Parent."""
    from epic_report_generator.ui.widgets import _RelationshipButton

    rel = _RelationshipButton()
    qtbot.addWidget(rel)
    rel.set_link_types(["Blocks", "Relates"])
    rel.set_from_node("parent", [])
    assert rel.edge == "parent" and rel.link_types() == []
    rel.set_from_node("link", ["Blocks"])
    assert rel.edge == "link" and rel.link_types() == ["Blocks"]
    # Picking a link clears Parent; picking Parent clears links.
    rel._toggle("Relates")
    assert rel.edge == "link" and rel.link_types() == ["Blocks", "Relates"]
    rel._toggle(rel._PARENT)
    assert rel.edge == "parent" and rel.link_types() == []
    rel._toggle("Relates")  # one link → link mode
    assert rel.edge == "link"
    rel._toggle("Relates")  # unselect the last link → back to Parent
    assert rel.edge == "parent"


def test_cross_silo_drag_changes_tier(qtbot):
    """Dropping a card into another silo retiers it (and keeps its toggles)."""
    ed = _editor(qtbot)
    ed.set_hierarchy(
        [
            HierarchyNode("10000", "Epic", display_tier=0),
            HierarchyNode("10001", "Story", display_tier=1, in_estimate=False),
            HierarchyNode("10002", "Sub-task", display_tier=2),
        ]
    )
    story = ed._silos[1].cards[0]
    ed._drag_card = story
    ed._drag_source = ed._silos[1]
    ed._handle_drop(ed._silos[2], 0)  # move Story into the Sub-task silo
    assert all(c.type_id != "10001" for c in ed._silos[1].cards)
    assert any(c.type_id == "10001" for c in ed._silos[2].cards)
    moved = next(n for n in ed.to_hierarchy() if n.issue_type_id == "10001")
    assert moved.display_tier == 2
    assert moved.in_estimate is False  # state preserved across the move


def test_default_node_tiers_from_hierarchy_level(qtbot):
    """A dragged type defaults to the right tier for real Jira levels.

    Standard Jira Cloud Epic is hierarchyLevel 1, so it must land on the
    Epic display tier (0), not Story.
    """
    ed = _editor(qtbot)
    assert ed._default_node("10000", "Epic").display_tier == 0  # level 1
    assert ed._default_node("10001", "Story").display_tier == 1  # level 0
    sub = ed._default_node("10002", "Sub-task")  # level -1, subtask
    assert sub.display_tier == 2 and sub.show is False


def test_hierarchy_editor_estimate_cascade_greys_downstream(qtbot):
    """Unchecking a tier's Estimate greys the Estimate toggle of every deeper
    tier; Show toggles stay editable while every tier is still shown."""
    ed = _editor(qtbot)
    ed.set_hierarchy(
        [
            HierarchyNode("10000", "Epic", display_tier=0),
            HierarchyNode("10001", "Story", display_tier=1),
            HierarchyNode("10002", "Sub-task", display_tier=2),
        ]
    )
    rows = _all_cards(ed)
    assert all(r.est_check.isEnabled() for r in rows)
    rows[0].est_check.setChecked(False)  # Epic tier not estimated
    assert rows[0].est_check.isEnabled()  # the Epic tier is always editable
    assert not rows[1].est_check.isEnabled()
    assert not rows[2].est_check.isEnabled()
    # Estimate and Show cascade independently: Show stays editable here.
    assert all(r.show_check.isEnabled() for r in rows)


def test_hierarchy_editor_show_cascade_greys_downstream(qtbot):
    """Unchecking a tier's Show greys the Show toggle of every deeper tier
    (mirrors the Estimate cascade and apply_hierarchy's show cascade)."""
    ed = _editor(qtbot)
    ed.set_hierarchy(
        [
            HierarchyNode("10000", "Epic", display_tier=0),
            HierarchyNode("10001", "Story", display_tier=1),
            HierarchyNode("10002", "Sub-task", display_tier=2),
        ]
    )
    rows = _all_cards(ed)
    assert all(r.show_check.isEnabled() for r in rows)
    rows[1].show_check.setChecked(False)  # Story tier hidden
    assert rows[1].show_check.isEnabled()  # the Story tier itself stays editable
    assert not rows[2].show_check.isEnabled()  # Sub-task (deeper) greys
    assert rows[0].show_check.isEnabled()  # Epic tier (above) unaffected
    # Estimate axis is untouched by hiding a tier.
    assert all(r.est_check.isEnabled() for r in rows)


def test_hierarchy_add_excludes_used_and_remove_reoffers(qtbot):
    """The "+ Add" picker offers only unused types; removing a card re-offers it."""
    ed = _editor(qtbot)
    # First load lists every type at its tier → nothing left to add anywhere.
    assert [n.issue_type for n in ed.to_hierarchy()] == [
        "Epic",
        "Story",
        "Bug",
        "Sub-task",
    ]
    assert all(s._available == [] for s in ed._silos)

    # Drop Bug from the chain → it becomes available in every silo's picker.
    ed.set_hierarchy(
        [
            HierarchyNode("10000", "Epic", display_tier=0),
            HierarchyNode("10001", "Story", display_tier=1),
            HierarchyNode("10002", "Sub-task", display_tier=2),
        ]
    )
    assert {t["id"] for t in ed._silos[0]._available} == {"10003"}

    # Add Bug into the Standard silo (as its "+ Add" picker would) → used again.
    ed._add_type(1, "10003")
    assert any(c.type_id == "10003" for c in ed._silos[1].cards)
    assert all(s._available == [] for s in ed._silos)

    # Remove it via its card → re-offered in the pickers.
    card = next(c for c in ed._silos[1].cards if c.type_id == "10003")
    ed._remove_card(card)
    assert {t["id"] for t in ed._silos[1]._available} == {"10003"}


def test_within_silo_drop_no_overshoot(qtbot):
    """A lower-half same-silo drop lands the card where dropped, not one past.

    The live ``dragMoveEvent`` settles the dragged card at its compensated
    position; ``dropEvent`` then recomputes the *raw* insertion index (which
    counts the dragged card's own slot). Without matching compensation in
    ``_handle_drop`` the card overshoots by one on a lower-half drop.
    """
    ed = _editor(qtbot)
    # Three cards in the Standard silo so the reorder is meaningful.
    ed.set_hierarchy(
        [
            HierarchyNode("10001", "Story", display_tier=1),
            HierarchyNode("10003", "Bug", display_tier=1),
            HierarchyNode("10002", "Sub-task", display_tier=1),
        ]
    )
    silo = ed._silos[1]
    card = silo.cards[0]  # Story
    ed._drag_card = card
    ed._drag_source = silo
    silo.move_within(card, 2)  # live drag settled it at index 2
    ed._handle_drop(silo, 3)  # raw lower-half index
    assert silo.cards.index(card) == 2  # stays put, does not slip to 3
    assert [c.type_id for c in silo.cards] == ["10003", "10002", "10001"]


def test_hierarchy_editor_guard_messages(qtbot):
    """Empty chain = default (no guards); a chain needs a tier-0 type."""
    ed = _editor(qtbot)
    assert ed.guard_messages() == []  # empty chain → use default, never block
    ed.set_hierarchy([HierarchyNode("10001", "Story", display_tier=1)])
    assert any("Epic-tier" in m for m in ed.guard_messages())
    ed.set_hierarchy([HierarchyNode("10000", "Epic", display_tier=0)])
    assert ed.guard_messages() == []
    # Migrated-offline chain: all nodes carry empty ids (backfill on next Refresh).
    # Empty ids must not self-collide into a false-positive duplicate that blocks.
    offline = IssueHierarchyEditor()  # no types loaded (offline restore)
    qtbot.addWidget(offline)
    chain = [
        HierarchyNode("", "Epic", display_tier=0),
        HierarchyNode("", "Story", display_tier=1),
        HierarchyNode("", "Sub-task", display_tier=2),
    ]
    offline.set_hierarchy(chain)
    assert offline.guard_messages() == []
    # …and the type names survive the round-trip (not blanked to an empty combo).
    assert [n.issue_type for n in offline.to_hierarchy()] == [
        "Epic",
        "Story",
        "Sub-task",
    ]


def test_hierarchy_editor_stale_warning(qtbot):
    """A chain node whose type is missing from Jira raises a (non-blocking) warning."""
    ed = _editor(qtbot)
    ed.set_hierarchy([HierarchyNode("99999", "Ghost", display_tier=0)])
    assert any("Ghost" in w for w in ed.stale_warnings())


# -- epic key autocomplete (Task 8) ------------------------------------------


def test_epic_query_emitted_on_key_typing(qtbot):
    """Typing into an epic row's key field requests autocomplete suggestions."""
    table = ReportItemTable()
    qtbot.addWidget(table)
    row = table.add_row(kind="epic")
    with qtbot.waitSignal(table.epic_query_changed, timeout=1000) as blocker:
        row.key_edit.setText("PRO")
    assert blocker.args[0] is row
    assert blocker.args[1] == "PRO"


def test_label_row_does_not_emit_epic_query(qtbot):
    """A label row never triggers epic autocomplete."""
    table = ReportItemTable()
    qtbot.addWidget(table)
    row = table.add_row(kind="label")
    received: list[str] = []
    table.epic_query_changed.connect(lambda _r, q: received.append(q))
    row.key_edit.setText("backend")
    assert received == []


def test_set_epic_completions_shows_key_and_summary(qtbot):
    """Suggestions display ``KEY — summary`` (or bare key when summary empty)."""
    table = ReportItemTable()
    qtbot.addWidget(table)
    row = table.add_row(kind="epic")
    row.set_epic_completions([("PROJ-1", "Login flow"), ("PROJ-2", "")])
    completer = row.key_edit.completer()
    assert completer is not None
    model = completer.model()
    shown = [model.index(i, 0).data() for i in range(model.rowCount())]
    assert shown == ["PROJ-1 — Login flow", "PROJ-2"]


def test_set_epic_completions_noop_for_label_row(qtbot):
    """Epic suggestions are ignored once a row is a label (completer unchanged)."""
    table = ReportItemTable()
    qtbot.addWidget(table)
    row = table.add_row(kind="label")
    row.set_epic_completions([("PROJ-1", "Login flow")])
    assert row.key_edit.completer() is None


def test_picking_epic_completion_sets_only_key(qtbot):
    """Activating a ``KEY — summary`` suggestion writes just the key, no re-fetch."""
    table = ReportItemTable()
    qtbot.addWidget(table)
    row = table.add_row(kind="epic")
    requeried: list[str] = []
    table.epic_query_changed.connect(lambda _r, q: requeried.append(q))
    row.set_epic_completions([("PROJ-7", "Checkout")])
    row._on_epic_completion("PROJ-7 — Checkout")
    qtbot.waitUntil(lambda: row.key == "PROJ-7", timeout=1000)
    assert row.key == "PROJ-7"
    assert row.key_edit.completer() is None
    assert requeried == []  # the programmatic key write must not re-query


def test_late_completions_after_pick_do_not_reopen_popup(qtbot):
    """A pending/in-flight picker result arriving after a pick must not re-open
    the popup; typing again re-enables suggestions."""
    table = ReportItemTable()
    qtbot.addWidget(table)
    row = table.add_row(kind="epic")
    row.set_epic_completions([("PROJ-7", "Checkout")])
    row._on_epic_completion("PROJ-7 — Checkout")
    qtbot.waitUntil(lambda: row.key == "PROJ-7", timeout=1000)
    # A late result for the just-typed query lands after the pick → ignored.
    row.set_epic_completions([("PROJ-7", "Checkout")])
    assert row.key_edit.completer() is None
    # The user edits again → the latch clears and suggestions show once more.
    row.key_edit.setText("PROJ-8")
    row.set_epic_completions([("PROJ-8", "Cart")])
    assert row.key_edit.completer() is not None


def test_empty_completions_dismiss_stale_popup(qtbot):
    """A no-match result clears a previously shown popup instead of leaving it up."""
    table = ReportItemTable()
    qtbot.addWidget(table)
    row = table.add_row(kind="epic")
    row.set_epic_completions([("HHP-410", "Login")])
    assert row.key_edit.completer() is not None
    # Query retyped to something with no matches → the stale popup is dismissed.
    row.set_epic_completions([])
    assert row.key_edit.completer() is None


def test_suggestion_display_string_fires_no_query(qtbot):
    """Picking a suggestion inserts 'KEY — summary'; that must not re-query Jira."""
    table = ReportItemTable()
    qtbot.addWidget(table)
    row = table.add_row(kind="epic")
    requeried: list[str] = []
    table.epic_query_changed.connect(lambda _r, q: requeried.append(q))
    # The completer inserting the full display string must not trigger a fetch.
    row.key_edit.setText("HHP-281 — Alpha test / αテスト")
    assert requeried == []
    # A plain key the user types still queries normally.
    row.key_edit.setText("HHP-2")
    assert requeried == ["HHP-2"]
