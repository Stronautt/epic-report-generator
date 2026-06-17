"""Regression tests for the application-wide pointing-hand cursor filter.

The global ``_CursorEventFilter`` must reach the ``Ok``/``Cancel`` buttons of
modal dialogs.  Those buttons are created inside ``QDialogButtonBox``'s own C++
constructor, so their ``ChildAdded`` event never passes through the application
filter — only the ``Polish`` event does.  These tests guard that the filter
applies the pointing-hand cursor to such buttons.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QPushButton, QVBoxLayout

from epic_report_generator.app import _CursorEventFilter
from epic_report_generator.ui.widgets import ChildCustomizeDialog

_POINTER = Qt.CursorShape.PointingHandCursor


@pytest.fixture
def cursor_filter(qapp, request):
    """Install the application-wide cursor filter for the duration of a test."""
    filt = _CursorEventFilter(qapp)
    qapp.installEventFilter(filt)
    request.addfinalizer(lambda: qapp.removeEventFilter(filt))
    return filt


def test_dialog_buttonbox_buttons_get_pointer_cursor(qtbot, qapp, cursor_filter):
    """Ok/Cancel buttons of a QDialogButtonBox must get the pointer cursor."""
    dialog = QDialog()
    qtbot.addWidget(dialog)
    layout = QVBoxLayout(dialog)
    buttons = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
    )
    layout.addWidget(buttons)

    dialog.show()
    qapp.processEvents()  # deliver the Polish events that drive the filter

    assert buttons.buttons(), "button box should expose its standard buttons"
    for button in buttons.buttons():
        assert button.cursor().shape() == _POINTER


def test_plain_button_still_gets_pointer_cursor(qtbot, qapp, cursor_filter):
    """The original ChildAdded path keeps working for hand-built buttons."""
    dialog = QDialog()
    qtbot.addWidget(dialog)
    layout = QVBoxLayout(dialog)
    plain = QPushButton("Go")
    layout.addWidget(plain)

    assert plain.cursor().shape() == _POINTER


def test_child_customize_dialog_buttons_get_pointer_cursor(qtbot, qapp, cursor_filter):
    """The real report-item settings dialog gets pointer cursors on Ok/Cancel."""
    dialog = ChildCustomizeDialog(
        kind="epic",
        parent_key="PROJ-1",
        parent_certainty="",
        children=[("PROJ-2", "Story A"), ("PROJ-3", "Task B")],
        overrides={},
    )
    qtbot.addWidget(dialog)

    dialog.show()
    qapp.processEvents()

    box = dialog.findChild(QDialogButtonBox)
    assert box is not None
    for button in box.buttons():
        assert button.cursor().shape() == _POINTER
