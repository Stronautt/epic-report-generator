"""Reusable widgets: status indicators, labelled fields, guide steps, etc."""

from __future__ import annotations

import re

from PySide6.QtCore import (
    QEvent,
    QObject,
    QPoint,
    QRect,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QGuiApplication,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPixmap,
)
from PySide6.QtWidgets import (
    QComboBox,
    QCompleter,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLayout,
    QLayoutItem,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
    QWidgetItem,
)

from epic_report_generator.core.data_models import ReportItem
from epic_report_generator.services.config_manager import (
    DEFAULT_PROFILE_NAME,
    ConfigManager,
)


class _IgnoreScrollFilter(QObject):
    """Event filter that swallows wheel events to prevent accidental value changes."""

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:  # noqa: N802
        if event.type() == QEvent.Type.Wheel:
            event.ignore()
            return True
        return super().eventFilter(obj, event)


def no_scroll_wheel(widget: QWidget) -> None:
    """Ignore mouse-wheel events on *widget* (combo boxes, date edits).

    For QComboBox widgets, also removes the icon/decoration space that
    Qt reserves in the dropdown popup.
    """
    widget.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    widget.installEventFilter(_IgnoreScrollFilter(widget))
    if isinstance(widget, QComboBox):
        widget.view().setIconSize(QSize(0, 0))


class StatusIndicator(QWidget):
    """Green/red dot with a text label showing connection state."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._dot = QLabel("●")
        self._dot.setFixedWidth(16)
        self._label = QLabel("Disconnected")
        self._label.setProperty("status", "disconnected")

        layout.addWidget(self._dot)
        layout.addWidget(self._label)
        layout.addStretch()
        self.set_connected(False)

    def set_connected(self, connected: bool, text: str = "") -> None:
        """Update the indicator state."""
        if connected:
            self._dot.setStyleSheet("color: #36B37E; font-size: 16px;")
            self._label.setText(text or "Connected")
            self._label.setProperty("status", "connected")
        else:
            self._dot.setStyleSheet("color: #DE350B; font-size: 16px;")
            self._label.setText(text or "Disconnected")
            self._label.setProperty("status", "disconnected")
        self._label.style().unpolish(self._label)
        self._label.style().polish(self._label)


class LabelledField(QWidget):
    """A label + line-edit pair with optional tooltip."""

    def __init__(
        self,
        label: str,
        *,
        placeholder: str = "",
        tooltip: str = "",
        description: str = "",
        password: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 8)
        layout.setSpacing(4)

        lbl = QLabel(label)
        lbl.setProperty("subheading", "true")
        layout.addWidget(lbl)

        self.field = QLineEdit()
        if placeholder:
            self.field.setPlaceholderText(placeholder)
        if tooltip:
            self.field.setToolTip(tooltip)
            lbl.setToolTip(tooltip)
        if password:
            self.field.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addWidget(self.field)

        if description:
            desc_lbl = QLabel(description)
            desc_lbl.setWordWrap(True)
            desc_lbl.setProperty("subheading", "true")
            layout.addWidget(desc_lbl)

    @property
    def text(self) -> str:
        """Return the current field text."""
        return self.field.text()

    @text.setter
    def text(self, value: str) -> None:
        self.field.setText(value)


class CopyField(QWidget):
    """Read-only text field with a copy-to-clipboard button."""

    def __init__(self, value: str, *, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self._field = QLineEdit(value)
        self._field.setReadOnly(True)
        layout.addWidget(self._field, 1)

        self._btn = QPushButton("Copy")
        self._btn.setMinimumWidth(72)
        self._btn.setProperty("secondary", "true")
        self._btn.clicked.connect(self._copy)
        layout.addWidget(self._btn, 0)

    def _copy(self) -> None:
        """Copy the field value to the system clipboard."""
        clipboard = QGuiApplication.clipboard()
        if clipboard:
            clipboard.setText(self._field.text())
        self._btn.setText("Copied!")
        QTimer.singleShot(1500, lambda: self._btn.setText("Copy"))


class GuideStep(QWidget):
    """A single collapsible step in an instructional guide.

    Displays a numbered header that expands/collapses the body content.
    """

    def __init__(
        self,
        number: int,
        title: str,
        *,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._expanded = False

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Header — clickable step title
        self._header = QPushButton(f"  Step {number}: {title}")
        self._header.setCheckable(True)
        self._header.setObjectName("guideStepHeader")
        self._header.clicked.connect(self._toggle)
        root.addWidget(self._header)

        # Body — hidden by default
        self._body = QWidget()
        self._body_layout = QVBoxLayout(self._body)
        self._body_layout.setContentsMargins(28, 4, 8, 12)
        self._body_layout.setSpacing(8)
        self._body.hide()
        root.addWidget(self._body)

        self._update_arrow()

    @property
    def body_layout(self) -> QVBoxLayout:
        """Return the layout to add step content into."""
        return self._body_layout

    def add_text(self, text: str) -> QLabel:
        """Add a descriptive text paragraph to the step body."""
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        self._body_layout.addWidget(lbl)
        return lbl

    def add_code(self, value: str) -> CopyField:
        """Add a copyable code/value field to the step body."""
        field = CopyField(value)
        self._body_layout.addWidget(field)
        return field

    def add_bullet(self, text: str) -> QLabel:
        """Add a bullet-point line to the step body."""
        lbl = QLabel(f"  •  {text}")
        lbl.setWordWrap(True)
        self._body_layout.addWidget(lbl)
        return lbl

    def add_separator(self) -> QFrame:
        """Add a thin horizontal line."""
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        self._body_layout.addWidget(line)
        return line

    def _toggle(self) -> None:
        self._expanded = not self._expanded
        self._body.setVisible(self._expanded)
        self._update_arrow()

    def _update_arrow(self) -> None:
        text = self._header.text()
        # Strip any existing arrow prefix
        text = text.lstrip(" ▶▼")
        arrow = "▼" if self._expanded else "▶"
        self._header.setText(f"{arrow}  {text.strip()}")


# ---------------------------------------------------------------------------
# FlowLayout — wrapping layout for tag chips
# ---------------------------------------------------------------------------


class FlowLayout(QLayout):
    """Flow layout that arranges widgets left-to-right, wrapping rows."""

    def __init__(self, parent: QWidget | None = None, spacing: int = 6) -> None:
        super().__init__(parent)
        self._items: list[QLayoutItem] = []
        self._spacing = spacing

    def addItem(self, item: QLayoutItem) -> None:  # noqa: N802
        self._items.append(item)

    def insertWidget(self, index: int, widget: QWidget) -> None:  # noqa: N802
        """Insert a widget at a specific position in the flow."""
        self.addChildWidget(widget)
        item = QWidgetItem(widget)
        self._items.insert(index, item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int) -> QLayoutItem | None:  # noqa: N802
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index: int) -> QLayoutItem | None:  # noqa: N802
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self) -> Qt.Orientation:  # noqa: N802
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect: QRect) -> None:  # noqa: N802
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self) -> QSize:  # noqa: N802
        return self.minimumSize()

    def minimumSize(self) -> QSize:  # noqa: N802
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        size += QSize(m.left() + m.right(), m.top() + m.bottom())
        return size

    def _do_layout(self, rect: QRect, test_only: bool) -> int:
        m = self.contentsMargins()
        effective = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        x = effective.x()
        y = effective.y()
        row_height = 0

        for item in self._items:
            sz = item.sizeHint()
            next_x = x + sz.width() + self._spacing
            if next_x - self._spacing > effective.right() and row_height > 0:
                x = effective.x()
                y += row_height + self._spacing
                next_x = x + sz.width() + self._spacing
                row_height = 0

            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), sz))

            x = next_x
            row_height = max(row_height, sz.height())

        return y + row_height - rect.y() + m.bottom()


# ---------------------------------------------------------------------------
# CollapsibleSection — reusable expand/collapse section
# ---------------------------------------------------------------------------


class CollapsibleSection(QWidget):
    """A section with a clickable header that expands/collapses a body area."""

    toggled = Signal(bool)

    def __init__(
        self,
        title: str,
        *,
        expanded: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._expanded = expanded
        self._title = title
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._header = QPushButton()
        self._header.setCheckable(True)
        self._header.setChecked(expanded)
        self._header.setObjectName("collapsibleHeader")
        self._header.clicked.connect(self._toggle)
        root.addWidget(self._header)

        self._body = QWidget()
        self._body_layout = QVBoxLayout(self._body)
        self._body_layout.setContentsMargins(0, 8, 0, 8)
        self._body_layout.setSpacing(8)
        self._body.setVisible(expanded)
        root.addWidget(self._body, 1)

        self._update_arrow()
        self._update_size_policy()

    @property
    def body_layout(self) -> QVBoxLayout:
        """Layout to add content into."""
        return self._body_layout

    def set_expanded(self, expanded: bool) -> None:
        """Programmatically expand or collapse."""
        if expanded == self._expanded:
            return
        self._expanded = expanded
        self._header.setChecked(expanded)
        self._body.setVisible(expanded)
        self._update_arrow()
        self._update_size_policy()
        self.toggled.emit(expanded)

    def is_expanded(self) -> bool:
        return self._expanded

    def _toggle(self) -> None:
        self._expanded = not self._expanded
        self._body.setVisible(self._expanded)
        self._update_arrow()
        self._update_size_policy()
        self.toggled.emit(self._expanded)

    def _update_size_policy(self) -> None:
        if self._expanded:
            self.setSizePolicy(
                QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred
            )
        else:
            self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)

    def _update_arrow(self) -> None:
        arrow = "▼" if self._expanded else "▶"
        escaped = self._title.replace("&", "&&")
        self._header.setText(f"{arrow}  {escaped}")


# ---------------------------------------------------------------------------
# EpicKeyTagInput — tag/chip input for epic keys
# ---------------------------------------------------------------------------

RE_EPIC_KEY = re.compile(r"^[A-Z][A-Z0-9_]+-\d+$")


class _EpicKeyChip(QWidget):
    """A single removable chip representing an epic key."""

    removed = Signal(str)

    def __init__(self, key: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.key = key
        self.setObjectName("epicKeyChip")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 2, 4, 2)
        layout.setSpacing(4)

        label = QLabel(key)
        label.setStyleSheet("background: transparent; border: none; padding: 0;")
        layout.addWidget(label)

        close_btn = QPushButton("×")
        close_btn.setFixedSize(18, 18)
        close_btn.setObjectName("epicKeyChipClose")
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.clicked.connect(lambda: self.removed.emit(self.key))
        layout.addWidget(close_btn)

        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)


class EpicKeyTagInput(QWidget):
    """Tag/chip input widget for entering Jira epic keys."""

    tags_changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("epicKeyTagInput")
        self.setCursor(Qt.CursorShape.IBeamCursor)

        self._chips: list[_EpicKeyChip] = []

        self._flow = FlowLayout(self, spacing=6)
        self._flow.setContentsMargins(6, 6, 6, 6)

        self._line_edit = QLineEdit()
        self._line_edit.setPlaceholderText("Type epic key and press Enter")
        self._line_edit.setFrame(False)
        self._line_edit.setStyleSheet(
            "border: none; background: transparent; padding: 4px 2px;"
        )
        self._line_edit.setMinimumWidth(180)
        self._line_edit.returnPressed.connect(self._commit_text)
        self._line_edit.installEventFilter(self)
        self._flow.addWidget(self._line_edit)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Focus the line edit when clicking anywhere in the container."""
        self._line_edit.setFocus()
        super().mousePressEvent(event)

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        """Handle Tab/comma for tag creation and paste for multi-value input."""
        from PySide6.QtGui import QKeyEvent

        if obj is self._line_edit and isinstance(event, QKeyEvent):
            if event.type() == QEvent.Type.KeyPress:
                if event.key() in (Qt.Key.Key_Tab, Qt.Key.Key_Comma):
                    self._commit_text()
                    return True
        return super().eventFilter(obj, event)

    def get_keys(self) -> list[str]:
        """Return all current epic keys."""
        return [chip.key for chip in self._chips]

    def set_keys(self, keys: list[str]) -> None:
        """Replace all chips with the given keys."""
        self.clear()
        for key in keys:
            self._add_chip(key)

    def clear(self) -> None:
        """Remove all chips and clear the input."""
        for chip in list(self._chips):
            self._remove_chip(chip.key)
        self._line_edit.clear()

    def _commit_text(self) -> None:
        """Parse input text and create chips for valid keys."""
        raw = self._line_edit.text()
        # Split on commas, newlines, whitespace for paste support
        parts = re.split(r"[,\n\s]+", raw)
        any_added = False
        existing_keys = {c.key for c in self._chips}
        for part in parts:
            part = part.strip().upper()
            if not part:
                continue
            if RE_EPIC_KEY.match(part) and part not in existing_keys:
                self._add_chip(part)
                existing_keys.add(part)
                any_added = True
        self._line_edit.clear()
        if any_added:
            self.tags_changed.emit()

    def _add_chip(self, key: str) -> None:
        chip = _EpicKeyChip(key)
        chip.removed.connect(self._remove_chip)
        self._chips.append(chip)
        # Insert chip before the line edit
        idx = self._flow.count() - 1  # line edit is last
        self._flow.insertWidget(idx, chip)

    def _remove_chip(self, key: str) -> None:
        for chip in self._chips:
            if chip.key == key:
                self._chips.remove(chip)
                self._flow.removeWidget(chip)
                chip.deleteLater()
                self.tags_changed.emit()
                break


# ---------------------------------------------------------------------------
# ReportItemTable — row-based input for epic keys and labels
# ---------------------------------------------------------------------------


class _ReportItemRow(QWidget):
    """A single row in the ReportItemTable."""

    removed = Signal(object)  # emits self
    changed = Signal()  # emits on any field change

    def __init__(
        self,
        kind: str = "epic",
        key: str = "",
        display_name: str = "",
        scope_certainty: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(4)

        self.kind_combo = QComboBox()
        no_scroll_wheel(self.kind_combo)
        self.kind_combo.addItem("Epic", "epic")
        self.kind_combo.addItem("Label", "label")
        idx = self.kind_combo.findData(kind)
        if idx >= 0:
            self.kind_combo.setCurrentIndex(idx)
        self.kind_combo.setFixedWidth(70)
        self.kind_combo.currentIndexChanged.connect(self._on_kind_changed)
        self.kind_combo.currentIndexChanged.connect(lambda: self.changed.emit())
        layout.addWidget(self.kind_combo)

        self.key_edit = QLineEdit(key)
        self.key_edit.setPlaceholderText("PROJ-123")
        self.key_edit.setMinimumWidth(90)
        self.key_edit.textChanged.connect(lambda _: self.changed.emit())
        layout.addWidget(self.key_edit, 2)

        self.name_edit = QLineEdit(display_name)
        self.name_edit.setPlaceholderText("Display name")
        self.name_edit.setMinimumWidth(90)
        self.name_edit.textChanged.connect(lambda _: self.changed.emit())
        layout.addWidget(self.name_edit, 2)

        self.certainty_combo = QComboBox()
        no_scroll_wheel(self.certainty_combo)
        self.certainty_combo.addItem("--", "")
        self.certainty_combo.addItem("Low", "Low")
        self.certainty_combo.addItem("Med", "Medium")
        self.certainty_combo.addItem("High", "High")
        cert_idx = self.certainty_combo.findData(scope_certainty or "")
        if cert_idx >= 0:
            self.certainty_combo.setCurrentIndex(cert_idx)
        self.certainty_combo.setFixedWidth(70)
        self.certainty_combo.currentIndexChanged.connect(lambda: self.changed.emit())
        layout.addWidget(self.certainty_combo)

        remove_btn = QPushButton("✕")
        remove_btn.setFixedSize(22, 22)
        remove_btn.setToolTip("Remove this row")
        remove_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        remove_btn.setStyleSheet(
            "QPushButton { background: transparent; border: none; color: #999;"
            " font-size: 14px; padding: 0; border-radius: 0; }"
            "QPushButton:hover { background: transparent; color: #DE350B; }"
            "QPushButton:pressed { background: transparent; color: #BF2600; }"
        )
        remove_btn.clicked.connect(lambda: self.removed.emit(self))
        layout.addWidget(remove_btn)

        self._label_completions: list[str] = []

        # Apply initial kind-based state
        self._on_kind_changed()

    def set_label_completions(self, labels: list[str]) -> None:
        """Set autocomplete suggestions for the key field when kind is label."""
        self._label_completions = labels
        if self.kind_combo.currentData() == "label" and self._label_completions:
            self._apply_completer(self._label_completions)

    def _apply_completer(self, labels: list[str]) -> None:
        """Attach a QCompleter with the given label list to key_edit."""
        completer = QCompleter(labels, self)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self.key_edit.setCompleter(completer)

    def _on_kind_changed(self) -> None:
        """Toggle display name enabled/placeholder based on kind."""
        is_label = self.kind_combo.currentData() == "label"
        if is_label:
            self.name_edit.setEnabled(True)
            self.name_edit.setPlaceholderText("Display name (required)")
            self.key_edit.setPlaceholderText("label-name")
            if self._label_completions:
                self._apply_completer(self._label_completions)
        else:
            self.name_edit.setPlaceholderText("(auto from Jira)")
            self.name_edit.setEnabled(False)
            self.name_edit.clear()
            self.key_edit.setPlaceholderText("PROJ-123")
            self.key_edit.setCompleter(None)  # type: ignore[arg-type]

    def to_report_item(self) -> ReportItem | None:
        """Build a ReportItem from the row, or None if key is empty."""
        kind = self.kind_combo.currentData() or "epic"
        key = self.key_edit.text().strip()
        if not key:
            return None
        if kind == "epic":
            key = key.upper()
        display_name = self.name_edit.text().strip() if kind == "label" else ""
        certainty = self.certainty_combo.currentData() or None
        return ReportItem(
            kind=kind, key=key, display_name=display_name, scope_certainty=certainty
        )

    def to_dict(self) -> dict:
        """Serialize to a dict for config persistence."""
        kind = self.kind_combo.currentData() or "epic"
        return {
            "kind": kind,
            "key": self.key_edit.text().strip(),
            "display_name": self.name_edit.text().strip() if kind == "label" else "",
            "scope_certainty": self.certainty_combo.currentData() or "",
        }


class ReportItemTable(QWidget):
    """Row-based input widget for report items (epics and labels)."""

    items_changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._rows: list[_ReportItemRow] = []
        self._label_completions: list[str] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)

        # Header row
        header = QHBoxLayout()
        header.setSpacing(4)
        for text, width in [
            ("Type", 70),
            ("Key / Label", 0),
            ("Display Name", 0),
            ("Cert.", 70),
            ("", 22),
        ]:
            lbl = QLabel(f"<b>{text}</b>") if text else QLabel("")
            if width:
                lbl.setFixedWidth(width)
            header.addWidget(lbl, 0 if width else 2)
        root.addLayout(header)

        self._rows_layout = QVBoxLayout()
        self._rows_layout.setSpacing(2)
        root.addLayout(self._rows_layout)

        add_btn = QPushButton("+ Add Row")
        add_btn.setProperty("secondary", "true")
        add_btn.clicked.connect(lambda: self.add_row())
        root.addWidget(add_btn)

    def set_label_completions(self, labels: list[str]) -> None:
        """Set autocomplete suggestions for label rows."""
        self._label_completions = labels
        for row in self._rows:
            row.set_label_completions(labels)

    def add_row(
        self,
        kind: str = "epic",
        key: str = "",
        display_name: str = "",
        scope_certainty: str = "",
    ) -> _ReportItemRow:
        """Add a new row to the table."""
        row = _ReportItemRow(kind, key, display_name, scope_certainty)
        if self._label_completions:
            row.set_label_completions(self._label_completions)
        row.removed.connect(self._remove_row)
        row.changed.connect(self.items_changed.emit)
        self._rows.append(row)
        self._rows_layout.addWidget(row)
        self.items_changed.emit()
        return row

    def _remove_row(self, row: _ReportItemRow) -> None:
        if row in self._rows:
            self._rows.remove(row)
            self._rows_layout.removeWidget(row)
            row.deleteLater()
            self.items_changed.emit()

    def get_items(self) -> list[ReportItem]:
        """Return all valid ReportItems from the table."""
        items = []
        for row in self._rows:
            item = row.to_report_item()
            if item:
                items.append(item)
        return items

    def get_items_as_dicts(self) -> list[dict]:
        """Return all rows serialized as dicts for config persistence."""
        return [row.to_dict() for row in self._rows if row.key_edit.text().strip()]

    def set_items(self, items: list[dict]) -> None:
        """Restore rows from a list of dicts."""
        self.blockSignals(True)
        self.clear()
        for d in items:
            self.add_row(
                kind=d.get("kind", "epic"),
                key=d.get("key", ""),
                display_name=d.get("display_name", ""),
                scope_certainty=d.get("scope_certainty", ""),
            )
        self.blockSignals(False)
        self.items_changed.emit()

    def set_from_epic_keys(self, keys: list[str]) -> None:
        """Migration helper: convert old epic key list to rows."""
        self.blockSignals(True)
        self.clear()
        for key in keys:
            self.add_row(kind="epic", key=key)
        self.blockSignals(False)
        self.items_changed.emit()

    def clear(self) -> None:
        """Remove all rows without per-row signal emission."""
        for row in self._rows:
            self._rows_layout.removeWidget(row)
            row.deleteLater()
        self._rows.clear()
        if not self.signalsBlocked():
            self.items_changed.emit()

    def row_count(self) -> int:
        """Return the number of rows."""
        return len(self._rows)


# ---------------------------------------------------------------------------
# SidebarUserInfo — compact user info for sidebar
# ---------------------------------------------------------------------------


class SidebarUserInfo(QWidget):
    """Sidebar block showing avatar, user name, site, auth method, and logout."""

    logout_requested = Signal()

    _AVATAR_SIZE = 32

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("sidebarUserInfo")
        self.hide()

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        # Row 1: avatar + name/site
        top_row = QHBoxLayout()
        top_row.setSpacing(10)

        self._avatar = QLabel()
        self._avatar.setFixedSize(self._AVATAR_SIZE, self._AVATAR_SIZE)
        self._avatar.setObjectName("sidebarAvatar")
        top_row.addWidget(self._avatar, 0, Qt.AlignmentFlag.AlignTop)

        text_col = QVBoxLayout()
        text_col.setSpacing(1)
        self._name_label = QLabel()
        self._name_label.setObjectName("sidebarUserName")
        self._name_label.setWordWrap(False)
        self._name_label.setTextFormat(Qt.TextFormat.PlainText)
        text_col.addWidget(self._name_label)

        self._site_label = QLabel()
        self._site_label.setObjectName("sidebarSiteName")
        self._site_label.setWordWrap(False)
        self._site_label.setTextFormat(Qt.TextFormat.PlainText)
        text_col.addWidget(self._site_label)
        top_row.addLayout(text_col, 1)

        root.addLayout(top_row)

        # Row 2: auth method + logout on one line
        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(0)

        self._auth_label = QLabel()
        self._auth_label.setObjectName("sidebarAuthBadge")
        self._auth_label.setTextFormat(Qt.TextFormat.PlainText)
        bottom_row.addWidget(self._auth_label)

        bottom_row.addStretch()

        self._logout_btn = QPushButton("Log out")
        self._logout_btn.setObjectName("sidebarLogoutBtn")
        self._logout_btn.setToolTip("Clear stored session and disconnect")
        self._logout_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._logout_btn.clicked.connect(self.logout_requested.emit)
        bottom_row.addWidget(self._logout_btn)

        root.addLayout(bottom_row)

    @staticmethod
    def _circular_pixmap(source: QPixmap, size: int) -> QPixmap:
        """Return *source* cropped and scaled into a circle of *size* px."""
        scaled = source.scaled(
            size,
            size,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        # Centre-crop to exact size
        x = (scaled.width() - size) // 2
        y = (scaled.height() - size) // 2
        cropped = scaled.copy(x, y, size, size)

        result = QPixmap(size, size)
        result.fill(Qt.GlobalColor.transparent)
        painter = QPainter(result)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addEllipse(0.0, 0.0, float(size), float(size))
        painter.setClipPath(path)
        painter.drawPixmap(0, 0, cropped)
        painter.end()
        return result

    def set_user(
        self,
        name: str,
        site: str,
        avatar_pixmap: QPixmap | None = None,
        auth_method: str = "",
    ) -> None:
        """Populate user info and show the widget."""
        self._name_label.setText(name)
        self._site_label.setText(site)
        if avatar_pixmap and not avatar_pixmap.isNull():
            self._avatar.setPixmap(
                self._circular_pixmap(avatar_pixmap, self._AVATAR_SIZE)
            )
        else:
            # Plain-text fallback initial
            self._avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._avatar.setText(name[:1].upper() if name else "?")
        if auth_method == "api_token":
            self._auth_label.setText("API Token")
        elif auth_method == "oauth":
            self._auth_label.setText("OAuth 2.0")
        else:
            self._auth_label.setText("")
        self.show()

    def clear(self) -> None:
        """Reset and hide."""
        self._name_label.clear()
        self._site_label.clear()
        self._auth_label.clear()
        self._avatar.clear()
        self.hide()


# ---------------------------------------------------------------------------
# ProfileBar — profile selector bar for the config panel
# ---------------------------------------------------------------------------


class ProfileBar(QWidget):
    """Always-visible bar for switching between configuration profiles."""

    profile_changed = Signal(str)

    def __init__(self, config: ConfigManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._config = config
        self.setObjectName("profileBar")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 8)
        layout.setSpacing(6)

        lbl = QLabel("Profile:")
        layout.addWidget(lbl)

        self._combo = QComboBox()
        no_scroll_wheel(self._combo)
        self._combo.setMinimumWidth(140)
        self._combo.currentTextChanged.connect(self._on_combo_changed)
        layout.addWidget(self._combo, 1)

        self._save_as_btn = QPushButton("Save As...")
        self._save_as_btn.setProperty("secondary", "true")
        self._save_as_btn.setToolTip("Clone current settings into a new named profile")
        self._save_as_btn.clicked.connect(self._save_as)
        layout.addWidget(self._save_as_btn)

        self._rename_btn = QPushButton("Rename")
        self._rename_btn.setProperty("secondary", "true")
        self._rename_btn.setToolTip("Rename the current profile")
        self._rename_btn.clicked.connect(self._rename)
        layout.addWidget(self._rename_btn)

        self._delete_btn = QPushButton("Delete")
        self._delete_btn.setProperty("danger", "true")
        self._delete_btn.setToolTip("Delete the current profile")
        self._delete_btn.clicked.connect(self._delete)
        layout.addWidget(self._delete_btn)

        self.refresh()

    def refresh(self) -> None:
        """Re-sync the combo box from ConfigManager."""
        self._combo.blockSignals(True)
        self._combo.clear()
        for name in self._config.profile_names:
            self._combo.addItem(name)
        active = self._config.active_profile_name
        idx = self._combo.findText(active)
        if idx >= 0:
            self._combo.setCurrentIndex(idx)
        self._combo.blockSignals(False)
        self._update_button_state()

    def _update_button_state(self) -> None:
        """Disable Rename/Delete for the Default profile."""
        is_default = self._combo.currentText() == DEFAULT_PROFILE_NAME
        self._rename_btn.setEnabled(not is_default)
        self._delete_btn.setEnabled(not is_default)

    def _on_combo_changed(self, name: str) -> None:
        if not name:
            return
        self._config.switch_profile(name)
        self._update_button_state()
        self.profile_changed.emit(name)

    def _save_as(self) -> None:
        name, ok = QInputDialog.getText(
            self,
            "Save Profile As",
            "Profile name:",
        )
        name = name.strip()
        if not ok or not name:
            return
        if name in self._config.profile_names:
            QMessageBox.warning(
                self,
                "Duplicate Name",
                f'A profile named "{name}" already exists.',
            )
            return
        self._config.create_profile(name, clone_from=self._config.active_profile_name)
        self.refresh()
        self.profile_changed.emit(name)

    def _rename(self) -> None:
        old_name = self._combo.currentText()
        if old_name == DEFAULT_PROFILE_NAME:
            return
        new_name, ok = QInputDialog.getText(
            self,
            "Rename Profile",
            "New name:",
            text=old_name,
        )
        new_name = new_name.strip()
        if not ok or not new_name or new_name == old_name:
            return
        if new_name in self._config.profile_names:
            QMessageBox.warning(
                self,
                "Duplicate Name",
                f'A profile named "{new_name}" already exists.',
            )
            return
        self._config.rename_profile(old_name, new_name)
        self.refresh()

    def _delete(self) -> None:
        name = self._combo.currentText()
        if name == DEFAULT_PROFILE_NAME:
            return
        reply = QMessageBox.question(
            self,
            "Delete Profile",
            f'Delete profile "{name}"?\n\nThis cannot be undone.',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._config.delete_profile(name)
        self.refresh()
        self.profile_changed.emit(self._config.active_profile_name)
