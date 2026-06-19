"""Reusable widgets: status indicators, labelled fields, guide steps, etc."""

from __future__ import annotations

import re

from PySide6.QtCore import (
    QEvent,
    QMimeData,
    QObject,
    QPoint,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QDrag,
    QDragEnterEvent,
    QDragMoveEvent,
    QDropEvent,
    QGuiApplication,
    QIcon,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPixmap,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QCompleter,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from epic_report_generator.core.data_models import ChildOverride, ReportItem
from epic_report_generator.services.config_manager import (
    DEFAULT_PROFILE_NAME,
    ConfigManager,
)
from epic_report_generator.ui.animations import (
    CollapseAnimator,
    flash_highlight,
    grow_in,
    lifted_card_pixmap,
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


def make_scroll_content(
    *,
    spacing: int = 16,
    margins: tuple[int, int, int, int] = (32, 32, 32, 32),
) -> tuple[QScrollArea, QVBoxLayout]:
    """Return a frameless, resizable scroll area and its content layout.

    The returned ``QScrollArea`` wraps an inner content ``QWidget`` whose
    ``QVBoxLayout`` (configured with *margins* and *spacing*) is returned so
    callers can add their widgets directly.
    """
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QScrollArea.Shape.NoFrame)

    content = QWidget()
    scroll.setWidget(content)
    layout = QVBoxLayout(content)
    layout.setContentsMargins(*margins)
    layout.setSpacing(spacing)
    return scroll, layout


def make_dialog_button_box(dialog: QDialog, ok_text: str) -> QDialogButtonBox:
    """Return the app-styled Ok/Cancel button box wired to *dialog*.

    *ok_text* labels the primary button (e.g. ``"Save"`` / ``"Apply"``). Icons
    are cleared and the ``dialogPrimary``/``dialogCancel`` properties set so
    ``styles.py`` can theme them; ``accepted``/``rejected`` drive the dialog.
    """
    box = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
    )
    box.setObjectName("dialogButtons")
    ok_btn = box.button(QDialogButtonBox.StandardButton.Ok)
    ok_btn.setText(ok_text)
    ok_btn.setIcon(QIcon())
    ok_btn.setProperty("dialogPrimary", "true")
    cancel_btn = box.button(QDialogButtonBox.StandardButton.Cancel)
    cancel_btn.setIcon(QIcon())
    cancel_btn.setProperty("dialogCancel", "true")
    box.accepted.connect(dialog.accept)
    box.rejected.connect(dialog.reject)
    return box


def _icon_btn(glyph: str, tooltip: str, hover: str, pressed: str) -> QPushButton:
    """Return a flat 22×22 icon button (grey glyph that tints on hover/press)."""
    btn = QPushButton(glyph)
    btn.setFixedSize(22, 22)
    btn.setToolTip(tooltip)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    btn.setStyleSheet(
        "QPushButton { background: transparent; border: none; color: #999;"
        " font-size: 14px; padding: 0; border-radius: 0; }"
        f"QPushButton:hover {{ background: transparent; color: {hover}; }}"
        f"QPushButton:pressed {{ background: transparent; color: {pressed}; }}"
    )
    return btn


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
            desc_lbl.setProperty("hint", "true")
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
        root.addWidget(self._body)
        self._animator = CollapseAnimator(self._body)
        self._animator.set_collapsed_initial()

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
        self._animator.animate(self._expanded)
        self._update_arrow()

    def _update_arrow(self) -> None:
        text = self._header.text()
        # Strip any existing arrow prefix
        text = text.lstrip(" ▶▼")
        arrow = "▼" if self._expanded else "▶"
        self._header.setText(f"{arrow}  {text.strip()}")


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
        variant: str = "section",
        number: int | None = None,
        animate_height: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        """Create a collapsible section.

        *variant* selects the visual tier: ``"step"`` renders a prominent
        top-level banner (accent bar, optional ``number`` badge, large title);
        ``"section"`` (default) renders a quieter, indented nested header so
        sub-sections read as children of a step rather than peers of it.

        *animate_height* drives whether the body's height is animated on
        expand/collapse. Leave it ``True`` for content-sized bodies. Set it
        ``False`` for a body that *fills* available space (stretch / an
        expanding child): its final height depends on sibling and stretch
        state, so a height animation would land on the wrong value and snap.
        Such a body shows/hides instantly and lets an animated sibling carry
        the motion while it fills in reactively.
        """
        super().__init__(parent)
        self._expanded = expanded
        self._title = title
        self._variant = variant
        is_step = variant == "step"
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # The header is a full-width checkable button. Its content — an optional
        # number badge, the title, and a right-aligned chevron — lives in an
        # inner layout; the child labels ignore mouse events so a click anywhere
        # along the row still reaches the button and toggles the section.
        self._header = QPushButton()
        self._header.setCheckable(True)
        self._header.setChecked(expanded)
        self._header.setObjectName(
            "collapsibleStepHeader" if is_step else "collapsibleHeader"
        )
        self._header.setCursor(Qt.CursorShape.PointingHandCursor)
        self._header.clicked.connect(self._toggle)

        header_layout = QHBoxLayout(self._header)
        header_layout.setContentsMargins(
            *((14, 8, 14, 8) if is_step else (12, 8, 8, 8))
        )
        header_layout.setSpacing(10)
        vcenter = Qt.AlignmentFlag.AlignVCenter

        def _passive_label(text: str, name: str) -> QLabel:
            """A header label that lets clicks reach the button but still shows
            the pointing-hand cursor (mouse-transparent children otherwise
            surface their own default arrow over the clickable header)."""
            lbl = QLabel(text)
            lbl.setObjectName(name)
            lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            lbl.setCursor(Qt.CursorShape.PointingHandCursor)
            return lbl

        if is_step and number is not None:
            badge = _passive_label(str(number), "stepBadge")
            badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            badge.setFixedSize(QSize(22, 22))
            header_layout.addWidget(badge, 0, vcenter)

        self._title_label = _passive_label(
            title, "stepTitle" if is_step else "sectionLabel"
        )
        header_layout.addWidget(self._title_label, 0, vcenter)
        header_layout.addStretch(1)

        self._arrow = _passive_label("", "collapsibleArrow")
        header_layout.addWidget(self._arrow, 0, vcenter)

        root.addWidget(self._header)

        self._body = QWidget()
        if not is_step:
            # Object name lets the QSS draw a left rail continuing the header's,
            # reinforcing that the body belongs to a nested section.
            self._body.setObjectName("nestedBody")
        self._body_layout = QVBoxLayout(self._body)
        # Nested sections indent their body so content aligns under the title
        # and inside the left rail; steps keep a flush body.
        self._body_layout.setContentsMargins(0 if is_step else 14, 8, 0, 8)
        self._body_layout.setSpacing(8)
        self._body.setVisible(expanded)
        root.addWidget(self._body, 1)

        # Animated reveal on expand/collapse (instant height + content fade,
        # see CollapseAnimator). Fill bodies (animate_height=False) skip it.
        self._animator: CollapseAnimator | None
        if animate_height:
            self._animator = CollapseAnimator(self._body)
            if not expanded:
                self._animator.set_collapsed_initial()
        else:
            self._animator = None
            self._body.setVisible(expanded)  # instant, no height clamp

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
        self._apply_expanded(expanded)

    def is_expanded(self) -> bool:
        return self._expanded

    def _toggle(self) -> None:
        self._apply_expanded(not self._expanded)

    def _apply_expanded(self, expanded: bool) -> None:
        """Shared expand/collapse path: sync header, arrow, and animate body."""
        self._expanded = expanded
        self._header.setChecked(expanded)
        self._update_arrow()
        self._update_size_policy()
        if self._animator is not None:
            self._animator.animate(expanded)
        else:
            self._body.setVisible(expanded)
        self.toggled.emit(expanded)

    def _update_size_policy(self) -> None:
        if self._expanded:
            self.setSizePolicy(
                QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred
            )
        else:
            self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)

    def _update_arrow(self) -> None:
        self._arrow.setText("▼" if self._expanded else "▶")


# ---------------------------------------------------------------------------
# RE_EPIC_KEY — canonical epic-key validation regex (used by config_panel)
# ---------------------------------------------------------------------------

RE_EPIC_KEY = re.compile(r"^[A-Z][A-Z0-9_]+-\d+$")

# Scope-certainty dropdown entries: (display label, stored data value). Shared by
# the per-row Cert. combo and the per-child override combos.
_CERT_ITEMS = [("--", ""), ("Low", "Low"), ("Med", "Medium"), ("High", "High")]


def _coerce_overrides(raw: dict | None) -> dict[str, ChildOverride]:
    """Normalise persisted/in-memory override data into ``ChildOverride`` objects.

    Accepts either a mapping of key → ``ChildOverride`` or key → plain dict
    (as stored in config JSON), dropping entries with no actual override. Nested
    ``child_overrides`` (an epic child's own story/task customisation) are
    coerced recursively. ``include`` defaults to ``True`` for older configs.
    """
    result: dict[str, ChildOverride] = {}
    for key, value in (raw or {}).items():
        if isinstance(value, ChildOverride):
            display_name = value.display_name
            certainty = value.scope_certainty
            include = value.include
            nested = _coerce_overrides(value.child_overrides)
            order = list(value.child_order)
        else:
            value = value or {}
            display_name = value.get("display_name", "")
            certainty = value.get("scope_certainty") or None
            include = bool(value.get("include", True))
            nested = _coerce_overrides(value.get("child_overrides"))
            order = list(value.get("child_order") or [])
        display_name = (display_name or "").strip()
        if display_name or certainty or not include or nested or order:
            result[key] = ChildOverride(
                display_name=display_name,
                scope_certainty=certainty,
                include=include,
                child_overrides=nested,
                child_order=order,
            )
    return result


def _serialize_override(ov: ChildOverride) -> dict:
    """Serialize a ``ChildOverride`` to a compact JSON-able dict for persistence.

    Default-valued fields are omitted so the stored shape stays minimal (and
    backward-compatible with the original ``display_name``/``scope_certainty``
    pair). Nested overrides are serialized recursively.
    """
    d: dict = {
        "display_name": ov.display_name,
        "scope_certainty": ov.scope_certainty or "",
    }
    if not ov.include:
        d["include"] = False
    if ov.child_overrides:
        d["child_overrides"] = {
            k: _serialize_override(v) for k, v in ov.child_overrides.items()
        }
    if ov.child_order:
        d["child_order"] = list(ov.child_order)
    return d


# ---------------------------------------------------------------------------
# ReportItemTable — row-based input for epic keys and labels
# ---------------------------------------------------------------------------


class _DragHandle(QLabel):
    """Grip handle that initiates a drag once the cursor moves far enough.

    Emits ``drag_requested`` so the owning row can ask the table to start an
    internal-move drag. Confining drag initiation to this handle keeps the
    row's line edits and combo boxes fully interactive.
    """

    drag_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("⠇", parent)  # ⠿ braille grip
        self.setObjectName("dragHandle")
        self.setFixedWidth(18)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setToolTip("Drag to reorder")
        self.setStyleSheet(
            "QLabel#dragHandle { color: #999; font-size: 15px; }"
            "QLabel#dragHandle:hover { color: #555; }"
        )
        self._press_pos: QPoint | None = None

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_pos = event.position().toPoint()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self._press_pos = None
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        super().mouseReleaseEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._press_pos is None or not (event.buttons() & Qt.MouseButton.LeftButton):
            super().mouseMoveEvent(event)
            return
        moved = (event.position().toPoint() - self._press_pos).manhattanLength()
        if moved >= QApplication.startDragDistance():
            self._press_pos = None
            self.drag_requested.emit()  # blocks for the duration of the drag
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        super().mouseMoveEvent(event)


class _ReportItemRow(QWidget):
    """A single row in the ReportItemTable."""

    removed = Signal(object)  # emits self
    changed = Signal()  # emits on any field change
    drag_started = Signal(object)  # emits self when the drag handle is dragged
    edit_requested = Signal(object)  # emits self when the customize button is clicked

    # Field-outline colours used to flag a validation problem on the row.
    _VALIDATION_COLOR = {"error": "#e53935", "warning": "#ff8f00"}

    def __init__(
        self,
        kind: str = "epic",
        key: str = "",
        display_name: str = "",
        scope_certainty: str = "",
        child_overrides: dict | None = None,
        child_order: list[str] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        # Object name + styled background let the drop-highlight flash paint a
        # tint scoped to this row (see ReportItemTable._start_drag).
        self.setObjectName("reportItemRow")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        # Per-child overrides keyed by child Jira key (see ChildOverride).
        self._child_overrides: dict[str, ChildOverride] = _coerce_overrides(
            child_overrides
        )
        # User-chosen child display order (child keys); see ReportItem.child_order.
        self._child_order: list[str] = list(child_order or [])
        self._initialised = False
        self._validation_state = ""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(4)

        self.drag_handle = _DragHandle()
        self.drag_handle.drag_requested.connect(lambda: self.drag_started.emit(self))
        layout.addWidget(self.drag_handle)

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
        for label, data in _CERT_ITEMS:
            self.certainty_combo.addItem(label, data)
        cert_idx = self.certainty_combo.findData(scope_certainty or "")
        if cert_idx >= 0:
            self.certainty_combo.setCurrentIndex(cert_idx)
        self.certainty_combo.setFixedWidth(70)
        self.certainty_combo.currentIndexChanged.connect(lambda: self.changed.emit())
        layout.addWidget(self.certainty_combo)

        edit_btn = _icon_btn(
            "⚙", "Customize the epics/stories within this item", "#0052CC", "#003C99"
        )
        edit_btn.clicked.connect(lambda: self.edit_requested.emit(self))
        layout.addWidget(edit_btn)

        remove_btn = _icon_btn("✕", "Remove this row", "#DE350B", "#BF2600")
        remove_btn.clicked.connect(lambda: self.removed.emit(self))
        layout.addWidget(remove_btn)

        self._label_completions: list[str] = []

        # Drop stale per-child overrides when the user switches epic↔label.
        self.kind_combo.currentIndexChanged.connect(self._on_kind_toggled)

        # Editing the identifying fields clears any stale validation highlight.
        self.key_edit.textChanged.connect(self._clear_validation)
        self.name_edit.textChanged.connect(self._clear_validation)
        self.kind_combo.currentIndexChanged.connect(self._clear_validation)

        # Apply initial kind-based state
        self._on_kind_changed()
        self._initialised = True

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
            self.name_edit.setPlaceholderText("Display name (recommended)")
            self.key_edit.setPlaceholderText("label-name")
            if self._label_completions:
                self._apply_completer(self._label_completions)
        else:
            self.name_edit.setPlaceholderText("(auto from Jira)")
            self.name_edit.setEnabled(False)
            self.name_edit.clear()
            self.key_edit.setPlaceholderText("PROJ-123")
            self.key_edit.setCompleter(None)  # type: ignore[arg-type]

    def _on_kind_toggled(self) -> None:
        """Discard per-child overrides when the user switches the item kind.

        Stale overrides keyed by the previous kind's child keys would never
        match the new kind's children, so clear them on a genuine user toggle
        (skipped during construction/restore where kind is set silently).
        """
        if self._initialised and (self._child_overrides or self._child_order):
            self._child_overrides = {}
            self._child_order = []

    def set_validation(self, state: str) -> None:
        """Flag (or clear) a validation problem on this row.

        *state* is ``""`` to clear, ``"error"`` (red) or ``"warning"`` (amber).
        The colour outlines the key/label field so the offending row stands out.
        """
        self._validation_state = state
        color = self._VALIDATION_COLOR.get(state)
        if color:
            self.key_edit.setStyleSheet(
                f"QLineEdit {{ border: 1px solid {color}; border-radius: 2px; }}"
            )
        else:
            self.key_edit.setStyleSheet("")

    def _clear_validation(self) -> None:
        """Drop the validation highlight as soon as the user edits the row."""
        if self._validation_state:
            self.set_validation("")

    @property
    def kind(self) -> str:
        """Current item kind (``"epic"`` or ``"label"``)."""
        return self.kind_combo.currentData() or "epic"

    @property
    def key(self) -> str:
        """Current trimmed key/label text."""
        return self.key_edit.text().strip()

    @property
    def scope_certainty(self) -> str:
        """Current parent certainty data value (``""`` when unset / consolidated)."""
        return self.certainty_combo.currentData() or ""

    def get_child_overrides(self) -> dict[str, ChildOverride]:
        """Return a deep copy of the per-child overrides (incl. include + nested)."""
        return _coerce_overrides(self._child_overrides)

    def set_child_overrides(self, overrides: dict[str, ChildOverride]) -> None:
        """Replace the per-child overrides and signal a change for persistence."""
        self._child_overrides = _coerce_overrides(overrides)
        self.changed.emit()

    def get_child_order(self) -> list[str]:
        """Return a copy of the user-chosen child display order (child keys)."""
        return list(self._child_order)

    def set_child_order(self, order: list[str]) -> None:
        """Replace the child display order and signal a change for persistence."""
        self._child_order = list(order)
        self.changed.emit()

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
            kind=kind,
            key=key,
            display_name=display_name,
            scope_certainty=certainty,
            child_overrides=self.get_child_overrides(),
            child_order=list(self._child_order),
        )

    def to_dict(self) -> dict:
        """Serialize to a dict for config persistence."""
        kind = self.kind_combo.currentData() or "epic"
        return {
            "kind": kind,
            "key": self.key_edit.text().strip(),
            "display_name": self.name_edit.text().strip() if kind == "label" else "",
            "scope_certainty": self.certainty_combo.currentData() or "",
            "child_overrides": {
                k: _serialize_override(ov) for k, ov in self._child_overrides.items()
            },
            "child_order": list(self._child_order),
        }


class ReportItemTable(QWidget):
    """Row-based input widget for report items (epics and labels)."""

    items_changed = Signal()
    edit_requested = Signal(object)  # emits the _ReportItemRow to customize

    _MIME_TYPE = "application/x-erg-report-row"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._rows: list[_ReportItemRow] = []
        self._label_completions: list[str] = []
        self._drag_row: _ReportItemRow | None = None
        self._drag_order: list[int] = []
        self.setAcceptDrops(True)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)

        # Header row
        header = QHBoxLayout()
        header.setSpacing(4)
        for text, width in [
            ("", 18),  # drag handle column
            ("Type", 70),
            ("Key / Label", 0),
            ("Display Name", 0),
            ("Cert.", 70),
            ("", 22),  # customize button column
            ("", 22),  # remove button column
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
        child_overrides: dict | None = None,
        child_order: list[str] | None = None,
    ) -> _ReportItemRow:
        """Add a new row to the table."""
        row = _ReportItemRow(
            kind, key, display_name, scope_certainty, child_overrides, child_order
        )
        if self._label_completions:
            row.set_label_completions(self._label_completions)
        row.removed.connect(self._remove_row)
        row.changed.connect(self.items_changed.emit)
        row.drag_started.connect(self._start_drag)
        row.edit_requested.connect(self.edit_requested.emit)
        self._rows.append(row)
        self._rows_layout.addWidget(row)
        # Animate a grow-in for interactive "+ Add Row" insertions, but not
        # during bulk restore (signals blocked) where many rows appear at once.
        if not self.signalsBlocked():
            grow_in(row)
        self.items_changed.emit()
        return row

    def _remove_row(self, row: _ReportItemRow) -> None:
        if row in self._rows:
            self._rows.remove(row)
            self._rows_layout.removeWidget(row)
            row.deleteLater()
            self.items_changed.emit()

    # -- drag-to-reorder ------------------------------------------------------

    def move_row(self, from_index: int, to_index: int) -> None:
        """Reorder a row and persist the change (keyboard/programmatic API)."""
        before = list(self._rows)
        self._reposition(from_index, to_index)
        if self._rows != before:
            self.items_changed.emit()

    def _reposition(self, from_index: int, to_index: int) -> None:
        """Move a row to a new index and re-lay out, without signalling."""
        if not 0 <= from_index < len(self._rows):
            return
        to_index = max(0, min(to_index, len(self._rows) - 1))
        if from_index == to_index:
            return
        # Move only the dragged widget: the layout holds rows exclusively, so
        # removing it then inserting at *to_index* leaves every other row in
        # place (no full teardown/rebuild on each drag-move event).
        row = self._rows.pop(from_index)
        self._rows.insert(to_index, row)
        self._rows_layout.removeWidget(row)
        self._rows_layout.insertWidget(to_index, row)

    def _row_insertion_index(self, y: int) -> int:
        """Insertion index for a drop at vertical position *y* (table coords)."""
        for i, row in enumerate(self._rows):
            top = row.mapTo(self, row.rect().topLeft()).y()
            if y < top + row.height() / 2:
                return i
        return len(self._rows)

    def _start_drag(self, row: _ReportItemRow) -> None:
        if row not in self._rows:
            return
        self._drag_row = row
        self._drag_order = [id(r) for r in self._rows]

        drag = QDrag(row)
        mime = QMimeData()
        mime.setData(self._MIME_TYPE, b"row")
        drag.setMimeData(mime)

        # Grab the row at full opacity first, then render it as a lifted card
        # (rounded, accent-bordered, translucent) for the floating drag cursor.
        accent = row.palette().highlight().color()
        pixmap = row.grab()
        drag.setPixmap(lifted_card_pixmap(pixmap, accent))
        drag.setHotSpot(QPoint(12, pixmap.height() // 2))

        # Dim the in-list row to a ghost placeholder while it is carried around;
        # the live reposition (dragMoveEvent) slides this faint row into place.
        ghost = QGraphicsOpacityEffect(row)
        ghost.setOpacity(0.4)
        row.setGraphicsEffect(ghost)

        drag.exec(Qt.DropAction.MoveAction)  # blocks until the drop completes

        # Restore the row and flash a fading highlight where it landed.
        row.setGraphicsEffect(None)
        flash_highlight(row, accent, selector="#reportItemRow")

        self._drag_row = None
        # Persist once, covering both in-widget drops and drops released
        # outside the table after the rows were already shuffled live.
        if [id(r) for r in self._rows] != self._drag_order:
            self.items_changed.emit()

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if self._drag_row is not None and event.mimeData().hasFormat(self._MIME_TYPE):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:  # noqa: N802
        if self._drag_row is None:
            event.ignore()
            return
        event.acceptProposedAction()
        current = self._rows.index(self._drag_row)
        insert_at = self._row_insertion_index(event.position().toPoint().y())
        target = insert_at - 1 if insert_at > current else insert_at
        if target != current:
            self._reposition(current, target)  # live feedback, no signal yet

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        if self._drag_row is not None:
            event.acceptProposedAction()
        else:
            event.ignore()

    def get_items(self) -> list[ReportItem]:
        """Return all valid ReportItems from the table."""
        items = []
        for row in self._rows:
            item = row.to_report_item()
            if item:
                items.append(item)
        return items

    @property
    def rows(self) -> list[_ReportItemRow]:
        """The row widgets in display order (read-only snapshot)."""
        return list(self._rows)

    def clear_validation(self) -> None:
        """Remove validation highlighting from every row."""
        for row in self._rows:
            row.set_validation("")

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
                child_overrides=d.get("child_overrides"),
                child_order=d.get("child_order"),
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


# ---------------------------------------------------------------------------
# ChildCustomizeDialog — per-child display-name & scope-certainty overrides
# ---------------------------------------------------------------------------


# Per-row column geometry, shared by the header and every _ChildRow so they line
# up: drag-handle width, key min-width, include-checkbox width, certainty combo
# width, settings (gear) button width.
_CHILD_HANDLE_W = 18
_CHILD_KEY_W = 90
_CHILD_INCL_W = 44
_CHILD_CERT_W = 70
_CHILD_SETTINGS_W = 22


def _order_children(
    children: list[tuple[str, str]], child_order: list[str]
) -> list[tuple[str, str]]:
    """Return *children* sorted by *child_order* (saved drag order).

    Children whose key appears in *child_order* come first, in that order; any
    child not listed (e.g. newly added in Jira since the order was saved) keeps
    its fetched position and is appended after the ordered ones. An empty
    *child_order* leaves the fetched order untouched.
    """
    if not child_order:
        return list(children)
    rank = {key: i for i, key in enumerate(child_order)}
    known = sorted((c for c in children if c[0] in rank), key=lambda c: rank[c[0]])
    unknown = [c for c in children if c[0] not in rank]
    return [*known, *unknown]


class _ChildRow(QWidget):
    """A single reorderable row in :class:`ChildCustomizeDialog`.

    Carries a drag handle, the child's key + summary (read-only), an always-
    visible display-name editor (placeholder = the Jira summary), an **Include**
    checkbox (default on; unchecking excludes the child from the report) and a
    certainty combo. When *show_settings* is set (epic children of a label item)
    a **gear** button opens a nested customize dialog for that epic's own
    stories/tasks; the nested overrides ride along on this row. Drag initiation
    is confined to the handle so the line edit and combo stay interactive.
    """

    drag_started = Signal(object)  # emits self when the drag handle is dragged
    settings_requested = Signal(object)  # emits self when the gear is clicked

    def __init__(
        self,
        key: str,
        summary: str,
        override: ChildOverride | None,
        *,
        cert_locked: bool,
        parent_certainty: str,
        show_settings: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.key = key
        self.summary = summary
        self._cert_locked = cert_locked
        self._parent_certainty = parent_certainty
        # Nested per-story/task customisation for an epic child (see ChildOverride).
        self._nested_overrides: dict[str, ChildOverride] = (
            _coerce_overrides(override.child_overrides) if override else {}
        )
        self._nested_order: list[str] = list(override.child_order) if override else []
        self.setObjectName("childRow")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(8)

        self.drag_handle = _DragHandle()
        self.drag_handle.drag_requested.connect(lambda: self.drag_started.emit(self))
        layout.addWidget(self.drag_handle)

        self._key_lbl = QLabel(key)
        self._key_lbl.setMinimumWidth(_CHILD_KEY_W)
        self._key_lbl.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        layout.addWidget(self._key_lbl)

        self._sum_lbl = QLabel(summary or "")
        self._sum_lbl.setToolTip(summary or "")
        # Ignored width lets a long summary clip to its column instead of widening
        # the dialog; the full text stays available via tooltip + the placeholder.
        self._sum_lbl.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        self._sum_lbl.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        layout.addWidget(self._sum_lbl, 1)

        self.name_edit = QLineEdit(override.display_name if override else "")
        self.name_edit.setPlaceholderText(summary or "Display name")
        layout.addWidget(self.name_edit, 1)

        # Include checkbox — on by default; unchecking excludes this child.
        self.include_check = QCheckBox()
        self.include_check.setChecked(override.include if override else True)
        self.include_check.setToolTip("Include this item in the report")
        self.include_check.setFixedWidth(_CHILD_INCL_W)
        self.include_check.toggled.connect(self._sync_enabled)
        layout.addWidget(self.include_check, 0, Qt.AlignmentFlag.AlignCenter)

        self.cert_combo = QComboBox()
        no_scroll_wheel(self.cert_combo)
        for label, data in _CERT_ITEMS:
            self.cert_combo.addItem(label, data)
        self.cert_combo.setFixedWidth(_CHILD_CERT_W)
        if cert_locked:
            idx = self.cert_combo.findData(parent_certainty)
            self.cert_combo.setCurrentIndex(idx if idx >= 0 else 0)
            self.cert_combo.setEnabled(False)
        elif override and override.scope_certainty:
            idx = self.cert_combo.findData(override.scope_certainty)
            if idx >= 0:
                self.cert_combo.setCurrentIndex(idx)
        layout.addWidget(self.cert_combo)

        # Per-epic settings gear (label items only) — opens a nested dialog for
        # this epic's stories/tasks, mirroring the main item's customize button.
        self.settings_btn: QPushButton | None = None
        if show_settings:
            self.settings_btn = _icon_btn(
                "⚙",
                "Customize the stories/tasks within this epic",
                "#0052CC",
                "#003C99",
            )
            self.settings_btn.clicked.connect(
                lambda: self.settings_requested.emit(self)
            )
            layout.addWidget(self.settings_btn)

        self._sync_enabled(self.include_check.isChecked())

    def _sync_enabled(self, included: bool) -> None:
        """Mute the row and lock its controls when it is excluded from the report."""
        self.name_edit.setEnabled(included)
        if not self._cert_locked:
            self.cert_combo.setEnabled(included)
        if self.settings_btn is not None:
            self.settings_btn.setEnabled(included)
        # Mute the key/summary text and disable dragging so an excluded row reads
        # plainly as "left out" rather than as a normal, reorderable entry.
        muted = "QLabel { color: #999; }" if not included else ""
        self._key_lbl.setStyleSheet(muted)
        self._sum_lbl.setStyleSheet(muted)
        self.drag_handle.setEnabled(included)

    def effective_certainty(self) -> str:
        """Certainty that governs this row's own children (for a nested dialog).

        A locked row hands down the parent's value; otherwise its own combo
        selection wins (``""`` when left at "--", i.e. consolidated).
        """
        if self._cert_locked:
            return self._parent_certainty
        return self.cert_combo.currentData() or ""

    def get_nested_overrides(self) -> dict[str, ChildOverride]:
        """Return a copy of this epic child's per-story/task overrides."""
        return _coerce_overrides(self._nested_overrides)

    def nested_order(self) -> list[str]:
        """Return this epic child's chosen story/task display order."""
        return list(self._nested_order)

    def set_nested(self, overrides: dict[str, ChildOverride], order: list[str]) -> None:
        """Store nested story/task overrides + order from the nested dialog."""
        self._nested_overrides = _coerce_overrides(overrides)
        self._nested_order = list(order)

    def override(self) -> ChildOverride | None:
        """The row's override, or None when it carries no customisation at all."""
        name = self.name_edit.text().strip()
        # When certainty is locked by the parent it is not a per-child override.
        certainty = (
            None if self._cert_locked else (self.cert_combo.currentData() or None)
        )
        include = self.include_check.isChecked()
        nested = _coerce_overrides(self._nested_overrides)
        order = list(self._nested_order)
        if name or certainty or not include or nested or order:
            return ChildOverride(
                display_name=name,
                scope_certainty=certainty,
                include=include,
                child_overrides=nested,
                child_order=order,
            )
        return None


class _ChildRowList(QWidget):
    """Vertical list of :class:`_ChildRow`s with drag-to-reorder.

    Mirrors :class:`ReportItemTable`'s internal-move drag: a row's drag handle
    starts a ``QDrag`` and ``dragMoveEvent`` slides rows live via ``_reposition``
    while the dragged row shows as a ghost. The chosen order is read on Save via
    :meth:`order`.
    """

    _MIME_TYPE = "application/x-erg-child-row"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self._rows: list[_ChildRow] = []
        self._drag_row: _ChildRow | None = None
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(6)
        self._layout.addStretch(1)  # trailing stretch keeps rows packed at top

    def add_row(self, row: _ChildRow) -> None:
        """Append *row* before the trailing stretch and wire its drag handle."""
        row.drag_started.connect(self._start_drag)
        self._rows.append(row)
        self._layout.insertWidget(self._layout.count() - 1, row)

    @property
    def rows(self) -> list[_ChildRow]:
        """The rows in current (possibly reordered) display order."""
        return list(self._rows)

    def order(self) -> list[str]:
        """Child keys in current display order."""
        return [row.key for row in self._rows]

    def _reposition(self, from_index: int, to_index: int) -> None:
        """Move a row to a new index and re-lay out (the stretch stays last)."""
        if not 0 <= from_index < len(self._rows):
            return
        to_index = max(0, min(to_index, len(self._rows) - 1))
        if from_index == to_index:
            return
        row = self._rows.pop(from_index)
        self._rows.insert(to_index, row)
        self._layout.removeWidget(row)
        self._layout.insertWidget(to_index, row)

    def _row_insertion_index(self, y: int) -> int:
        """Insertion index for a drop at vertical position *y* (list coords)."""
        for i, row in enumerate(self._rows):
            top = row.mapTo(self, row.rect().topLeft()).y()
            if y < top + row.height() / 2:
                return i
        return len(self._rows)

    def _start_drag(self, row: _ChildRow) -> None:
        if row not in self._rows:
            return
        self._drag_row = row

        drag = QDrag(row)
        mime = QMimeData()
        mime.setData(self._MIME_TYPE, b"row")
        drag.setMimeData(mime)

        accent = row.palette().highlight().color()
        pixmap = row.grab()
        drag.setPixmap(lifted_card_pixmap(pixmap, accent))
        drag.setHotSpot(QPoint(12, pixmap.height() // 2))

        ghost = QGraphicsOpacityEffect(row)
        ghost.setOpacity(0.4)
        row.setGraphicsEffect(ghost)

        drag.exec(Qt.DropAction.MoveAction)  # blocks until the drop completes

        row.setGraphicsEffect(None)
        flash_highlight(row, accent, selector="#childRow")
        self._drag_row = None

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if self._drag_row is not None and event.mimeData().hasFormat(self._MIME_TYPE):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:  # noqa: N802
        if self._drag_row is None:
            event.ignore()
            return
        event.acceptProposedAction()
        current = self._rows.index(self._drag_row)
        insert_at = self._row_insertion_index(event.position().toPoint().y())
        target = insert_at - 1 if insert_at > current else insert_at
        if target != current:
            self._reposition(current, target)  # live feedback

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        if self._drag_row is not None:
            event.acceptProposedAction()
        else:
            event.ignore()


class _AutoSizeScrollArea(QScrollArea):
    """Scroll area whose size hint tracks its content up to a maximum height.

    A plain ``QScrollArea``'s size hint stops following the content past a small
    default, so a dialog around it never grows to fit more rows. Reporting the
    content's own height (clamped to *max_height*) lets the dialog auto-size with
    the number of children and only start scrolling once it would exceed the cap.
    """

    def __init__(self, max_height: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._max_height = max_height
        self.setMaximumHeight(max_height)

    def sizeHint(self) -> QSize:  # noqa: N802
        widget = self.widget()
        if widget is None:
            return super().sizeHint()
        frame = 2 * self.frameWidth()
        hint = widget.sizeHint()
        return QSize(hint.width() + frame, min(hint.height() + frame, self._max_height))


class ChildCustomizeDialog(QDialog):
    """Modal for overriding display name & scope certainty of an item's children.

    The children are the epics under a label item, or the stories/tasks under an
    epic item.  When the parent row already has a scope certainty selected, the
    per-child certainty selectors are disabled (the parent value wins for all
    children).  When the parent is left at ``"--"`` the children may each set
    their own certainty and the report shows the average (FR-13, consolidated).

    Each child also carries an **Include** checkbox (default on) — unchecking it
    drops the child from the report. For a label item every child is an epic, so
    each row gets a **gear** button (``child_settings_requested``) that opens a
    nested dialog for that epic's own stories/tasks.
    """

    # Emits the _ChildRow whose per-epic settings gear was clicked. The owner
    # (config panel) fetches the epic's stories/tasks, opens a nested dialog, and
    # writes the result back via _ChildRow.set_nested().
    child_settings_requested = Signal(object)

    def __init__(
        self,
        *,
        kind: str,
        parent_key: str,
        parent_certainty: str,
        children: list[tuple[str, str]],
        overrides: dict[str, ChildOverride],
        child_order: list[str] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        # A label's children are epics (drillable via the gear); an epic's
        # children are stories/tasks (leaf, no gear).
        self._show_settings = kind == "label"
        child_noun = "Epic" if kind == "label" else "Story / Task"
        self.setWindowTitle(f"Customize “{parent_key}”")
        # Modal dialog — only show a title bar + close button. CustomizeWindowHint
        # is required for the absence of the minimize/maximize hints to take effect
        # (without it Qt keeps default decorations and the WM adds min/max itself).
        self.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.CustomizeWindowHint
            | Qt.WindowType.WindowTitleHint
            | Qt.WindowType.WindowCloseButtonHint
            | Qt.WindowType.WindowSystemMenuHint
        )
        self.setMinimumWidth(740 if self._show_settings else 700)
        self._cert_locked = bool(parent_certainty)
        self._parent_certainty = parent_certainty
        self._list: _ChildRowList | None = None

        root = QVBoxLayout(self)
        root.setSpacing(10)

        include_hint = " Untick <b>Include</b> to leave an item out of the report" + (
            "; use the gear to customise an epic's own stories/tasks."
            if self._show_settings
            else "."
        )
        if self._cert_locked:
            note = QLabel(
                f"Scope certainty is fixed to <b>{parent_certainty}</b> on the parent "
                "item, so per-child certainty is disabled. Set the parent certainty "
                "to “--” to edit each child and show their average." + include_hint
            )
        else:
            note = QLabel(
                "Override the display name and scope certainty for each child, and "
                "drag the handle to reorder. Leave certainty at “--” to exclude it "
                "from the average." + include_hint
            )
        note.setWordWrap(True)
        note.setProperty("hint", "true")
        root.addWidget(note)

        if not children:
            empty = QLabel("No child items were found for this report item.")
            empty.setWordWrap(True)
            root.addWidget(empty)
        else:
            root.addWidget(
                self._build_body(child_noun, children, overrides, child_order)
            )

        root.addWidget(make_dialog_button_box(self, "Save"))

    def _build_body(
        self,
        child_noun: str,
        children: list[tuple[str, str]],
        overrides: dict[str, ChildOverride],
        child_order: list[str] | None,
    ) -> QScrollArea:
        # Header + reorderable rows share one vertical layout inside the scroll
        # content, so the column headings stay aligned with the row widgets (and
        # scroll together) regardless of any vertical scrollbar.
        content = QWidget()
        body = QVBoxLayout(content)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(6)
        body.addWidget(self._build_header(child_noun))

        self._list = _ChildRowList()
        for key, summary in _order_children(children, child_order or []):
            child_row = _ChildRow(
                key,
                summary,
                overrides.get(key),
                cert_locked=self._cert_locked,
                parent_certainty=self._parent_certainty,
                show_settings=self._show_settings,
            )
            child_row.settings_requested.connect(self.child_settings_requested.emit)
            self._list.add_row(child_row)
        body.addWidget(self._list)

        # No minimum: a short list keeps the dialog compact. The scroll area's
        # size hint follows its content (see _AutoSizeScrollArea), so the dialog
        # auto-grows with the number of children — capped to most of the screen
        # so a long list scrolls instead of overflowing the display.
        screen = self.screen() or QApplication.primaryScreen()
        avail = screen.availableGeometry().height() if screen is not None else 900
        scroll = _AutoSizeScrollArea(max(240, avail - 180))
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(content)
        return scroll

    def _build_header(self, child_noun: str) -> QWidget:
        """A non-scrolling-away column header aligned with the _ChildRow columns."""
        header = QWidget()
        row = QHBoxLayout(header)
        row.setContentsMargins(0, 2, 0, 2)
        row.setSpacing(8)
        spacer = QLabel("")
        spacer.setFixedWidth(_CHILD_HANDLE_W)  # aligns under the drag handles
        row.addWidget(spacer)
        key_lbl = QLabel(f"<b>{child_noun}</b>")
        key_lbl.setMinimumWidth(_CHILD_KEY_W)
        row.addWidget(key_lbl)
        sum_lbl = QLabel("<b>Summary</b>")
        sum_lbl.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        row.addWidget(sum_lbl, 1)
        row.addWidget(QLabel("<b>Display Name</b>"), 1)
        incl_lbl = QLabel("<b>Incl.</b>")
        incl_lbl.setFixedWidth(_CHILD_INCL_W)
        incl_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row.addWidget(incl_lbl)
        cert_lbl = QLabel("<b>Cert.</b>")
        cert_lbl.setFixedWidth(_CHILD_CERT_W)
        row.addWidget(cert_lbl)
        if self._show_settings:
            settings_spacer = QLabel("")
            settings_spacer.setFixedWidth(_CHILD_SETTINGS_W)
            row.addWidget(settings_spacer)
        return header

    def get_overrides(self) -> dict[str, ChildOverride]:
        """Return the per-child overrides, omitting children with no override."""
        if self._list is None:
            return {}
        result: dict[str, ChildOverride] = {}
        for row in self._list.rows:
            ov = row.override()
            if ov is not None:
                result[row.key] = ov
        return result

    def get_child_order(self) -> list[str]:
        """Return the child keys in the user's chosen (dragged) order."""
        return self._list.order() if self._list is not None else []


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
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        lbl = QLabel("Profile:")
        layout.addWidget(lbl)

        self._combo = QComboBox()
        self._combo.setEditable(True)
        self._combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        no_scroll_wheel(self._combo)
        self._combo.setMinimumWidth(140)

        completer = QCompleter(self)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self._combo.setCompleter(completer)
        completer.setModel(self._combo.model())

        self._combo.activated.connect(self._on_combo_activated)
        self._combo.lineEdit().editingFinished.connect(  # type: ignore[union-attr]
            self._on_editing_finished
        )
        layout.addWidget(self._combo, 1)

        self._save_as_btn = QPushButton("Clone as...")
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

    def _on_combo_activated(self, index: int) -> None:
        name = self._combo.itemText(index)
        if not name:
            return
        self._config.switch_profile(name)
        self._update_button_state()
        self.profile_changed.emit(name)

    def _on_editing_finished(self) -> None:
        """Revert to the active profile if the user typed an invalid name."""
        text = self._combo.currentText()
        if text not in self._config.profile_names:
            idx = self._combo.findText(self._config.active_profile_name)
            if idx >= 0:
                self._combo.setCurrentIndex(idx)

    def _save_as(self) -> None:
        current = self._config.active_profile_name
        name, ok = QInputDialog.getText(
            self,
            "Clone Profile",
            f"Enter a name for the new profile.\n"
            f'The current profile "{current}" will be used as a basis.',
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
