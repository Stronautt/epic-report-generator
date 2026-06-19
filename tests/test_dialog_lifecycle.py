"""Regression tests for modal-dialog memory lifecycle.

Assert that :class:`ChildCustomizeDialog` and :class:`FieldPickerDialog` do not
accumulate under their parent across repeated open/close cycles;
``findChildren`` is the probe. The mechanism is :func:`exec_dialog` — see its
docstring for the ownership rationale.
"""

from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QDialog, QWidget

from epic_report_generator.ui.config_panel import FieldPickerDialog
from epic_report_generator.ui.widgets import ChildCustomizeDialog, exec_dialog


def _make_child_dialog(parent: QWidget) -> ChildCustomizeDialog:
    return ChildCustomizeDialog(
        kind="label",
        parent_key="PROJ-1",
        parent_certainty="",
        children=[("PROJ-2", "Epic A"), ("PROJ-3", "Epic B")],
        overrides={},
        parent=parent,
    )


def test_exec_dialog_returns_result_and_schedules_delete(qtbot):
    """exec_dialog returns the dialog code and frees the dialog afterwards."""
    parent = QWidget()
    qtbot.addWidget(parent)

    dialog = _make_child_dialog(parent)
    # The dialog is a live child of its parent until it is destroyed.
    assert dialog in parent.findChildren(ChildCustomizeDialog)

    QTimer.singleShot(0, dialog.accept)  # close the modal from the event loop
    assert exec_dialog(dialog) == QDialog.DialogCode.Accepted

    # deleteLater is deferred; once events run, the dialog leaves the child tree.
    qtbot.waitUntil(lambda: not parent.findChildren(ChildCustomizeDialog), timeout=2000)


def test_child_customize_dialog_does_not_accumulate(qtbot):
    """Opening/closing the customize dialog many times leaves no survivors."""
    parent = QWidget()
    qtbot.addWidget(parent)

    for _ in range(20):
        dialog = _make_child_dialog(parent)
        QTimer.singleShot(0, dialog.reject)  # mix accept/reject paths is fine
        exec_dialog(dialog)

    qtbot.waitUntil(lambda: not parent.findChildren(ChildCustomizeDialog), timeout=2000)


def test_field_picker_dialog_does_not_accumulate(qtbot):
    """The Detect-Fields picker is freed the same way across repeated opens."""
    parent = QWidget()
    qtbot.addWidget(parent)

    for _ in range(20):
        dialog = FieldPickerDialog(
            [{"id": "customfield_1", "name": "Story Points"}],
            [{"id": "customfield_2", "name": "Epic Link"}],
            parent=parent,
        )
        QTimer.singleShot(0, dialog.accept)
        exec_dialog(dialog)

    qtbot.waitUntil(lambda: not parent.findChildren(FieldPickerDialog), timeout=2000)
