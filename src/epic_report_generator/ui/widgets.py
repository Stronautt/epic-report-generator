"""Reusable widgets: status indicators, labelled fields, guide steps, etc."""

from __future__ import annotations

import re

from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QBrush, QGuiApplication, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLayoutItem,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QStyle,
    QVBoxLayout,
    QWidget,
    QWidgetItem,
)


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

    @property
    def text(self) -> str:
        """Return the current field text."""
        return self.field.text()

    @text.setter
    def text(self, value: str) -> None:
        self.field.setText(value)


class CopyField(QWidget):
    """Read-only text field with a copy-to-clipboard button."""

    def __init__(
        self, value: str, *, parent: QWidget | None = None
    ) -> None:
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
        from PySide6.QtCore import QTimer
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
        lbl = QLabel(f"  \u2022  {text}")
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
        text = text.lstrip(" \u25B6\u25BC")
        arrow = "\u25BC" if self._expanded else "\u25B6"
        self._header.setText(f"{arrow}  {text.strip()}")


# ---------------------------------------------------------------------------
# FlowLayout — wrapping layout for tag chips
# ---------------------------------------------------------------------------

class FlowLayout(QLayout):
    """A flow layout that arranges child widgets left-to-right, wrapping to the next row."""

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
            self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        else:
            self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)

    def _update_arrow(self) -> None:
        arrow = "\u25BC" if self._expanded else "\u25B6"
        self._header.setText(f"{arrow}  {self._title}")


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

        close_btn = QPushButton("\u00d7")
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

    def mousePressEvent(self, event: object) -> None:
        """Focus the line edit when clicking anywhere in the container."""
        self._line_edit.setFocus()
        super().mousePressEvent(event)

    def eventFilter(self, obj: object, event: object) -> bool:
        """Handle Tab/comma for tag creation and paste for multi-value input."""
        from PySide6.QtCore import QEvent
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
        for part in parts:
            part = part.strip().upper()
            if not part:
                continue
            if RE_EPIC_KEY.match(part) and part not in {c.key for c in self._chips}:
                self._add_chip(part)
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
            size, size,
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
