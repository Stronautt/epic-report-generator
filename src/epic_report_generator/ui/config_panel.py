"""Report configuration panel."""

from __future__ import annotations

import html
import logging
from collections.abc import Callable
from datetime import date

from PySide6.QtCore import QDate, QEvent, QObject, Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from epic_report_generator.core.data_models import ReportConfig
from epic_report_generator.core.jira_client import JiraClient
from epic_report_generator.services.config_manager import _DEFAULTS, ConfigManager
from epic_report_generator.ui._threading import ThreadedTask
from epic_report_generator.ui.widgets import (
    RE_EPIC_KEY,
    ChildCustomizeDialog,
    CollapsibleSection,
    LabelledField,
    ProfileBar,
    ReportItemTable,
    exec_dialog,
    make_dialog_button_box,
    no_scroll_wheel,
)

logger = logging.getLogger(__name__)


def _qdate_to_date(qd: QDate) -> date:
    """Convert a Qt ``QDate`` to a stdlib ``date``."""
    return date(qd.year(), qd.month(), qd.day())


class _EmptyAwareDateEdit(QDateEdit):
    """A ``QDateEdit`` whose calendar popup opens on today's month when empty.

    The fixed-date pickers use ``setSpecialValueText`` together with
    ``setDate(minimumDate())`` to represent an *unset* field. Without this,
    opening the popup while empty navigates the calendar to the minimum date
    (~1752), which is awkward to scroll away from. When the field is empty we
    instead show the current month so picking a date starts near today.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCalendarPopup(True)
        self.calendarWidget().installEventFilter(self)

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if (
            obj is self.calendarWidget()
            and event.type() == QEvent.Type.Show
            and self.date() == self.minimumDate()
        ):
            today = QDate.currentDate()
            self.calendarWidget().setCurrentPage(today.year(), today.month())
        return super().eventFilter(obj, event)


def _populate_field_combo(
    combo: QComboBox, candidates: list[dict], current: str | None
) -> None:
    """Fill *combo* with field candidates, pre-selecting *current* by id.

    When there are no candidates the combo shows a disabled placeholder.
    """
    if candidates:
        for f in candidates:
            combo.addItem(f"{f['name']}  —  {f['id']}", userData=f["id"])
        if current:
            idx = combo.findData(current)
            if idx >= 0:
                combo.setCurrentIndex(idx)
    else:
        combo.addItem("(No matches found)")
        combo.setEnabled(False)


def _field_value(combo: QComboBox) -> str | None:
    """Return the combo's selected field id, or None when it is disabled."""
    return combo.currentData() if combo.isEnabled() else None


def _make_field_combo(candidates: list[dict], current: str | None) -> QComboBox:
    """Build a no-scroll field-picker combo populated with *candidates*."""
    combo = QComboBox()
    no_scroll_wheel(combo)
    _populate_field_combo(combo, candidates, current)
    return combo


class FieldPickerDialog(QDialog):
    """Dialog letting the user choose from detected Jira field candidates."""

    def __init__(
        self,
        sp_candidates: list[dict],
        epic_candidates: list[dict],
        parent: QWidget | None = None,
        *,
        estimation_method: str = "story_points",
        start_date_candidates: list[dict] | None = None,
        due_date_candidates: list[dict] | None = None,
        timeline_start_candidates: list[dict] | None = None,
        timeline_end_candidates: list[dict] | None = None,
        current_values: dict[str, str] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Select Jira Fields")
        self.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.CustomizeWindowHint
            | Qt.WindowType.WindowTitleHint
            | Qt.WindowType.WindowCloseButtonHint
            | Qt.WindowType.WindowSystemMenuHint
        )
        self.setMinimumWidth(420)

        layout = QFormLayout(self)

        cv = current_values or {}

        # Combos are built (and populated) up front; visibility is controlled by
        # which rows are added below. A hidden, populated combo is harmless — its
        # selected_* getter is only read for the matching estimation method.

        # Story Points field (only shown for story_points method)
        self._sp_combo = _make_field_combo(sp_candidates, cv.get("story_points_field"))
        if estimation_method == "story_points":
            layout.addRow("Story Points Field:", self._sp_combo)

        # Date fields (only shown for time_days method)
        self._start_date_combo = _make_field_combo(
            start_date_candidates or [], cv.get("start_date_field")
        )
        self._due_date_combo = _make_field_combo(
            due_date_candidates or [], cv.get("due_date_field")
        )
        if estimation_method == "time_days":
            layout.addRow("Start Date Field:", self._start_date_combo)
            layout.addRow("Due Date Field:", self._due_date_combo)

        self._epic_combo = _make_field_combo(epic_candidates, cv.get("epic_link_field"))
        layout.addRow("Epic Link Field:", self._epic_combo)

        # Timeline fields (always shown)
        self._timeline_start_combo = _make_field_combo(
            timeline_start_candidates or [], cv.get("timeline_start_field")
        )
        layout.addRow("Timeline Start Field:", self._timeline_start_combo)

        self._timeline_end_combo = _make_field_combo(
            timeline_end_candidates or [], cv.get("timeline_end_field")
        )
        layout.addRow("Timeline End Field:", self._timeline_end_combo)

        layout.addRow(make_dialog_button_box(self, "Apply"))

    @property
    def selected_sp_field(self) -> str | None:
        """Return the selected Story Points field ID, or None if unavailable."""
        return _field_value(self._sp_combo)

    @property
    def selected_epic_field(self) -> str | None:
        """Return the selected Epic Link field ID, or None if unavailable."""
        return _field_value(self._epic_combo)

    @property
    def selected_start_date_field(self) -> str | None:
        """Return the selected Start Date field ID, or None if unavailable."""
        return _field_value(self._start_date_combo)

    @property
    def selected_due_date_field(self) -> str | None:
        """Return the selected Due Date field ID, or None if unavailable."""
        return _field_value(self._due_date_combo)

    @property
    def selected_timeline_start_field(self) -> str | None:
        """Return the selected Timeline Start field ID, or None if unavailable."""
        return _field_value(self._timeline_start_combo)

    @property
    def selected_timeline_end_field(self) -> str | None:
        """Return the selected Timeline End field ID, or None if unavailable."""
        return _field_value(self._timeline_end_combo)


class ConfigPanel(QWidget):
    """Report configuration UI with epic key tags, metadata, and field mapping."""

    def __init__(
        self,
        config: ConfigManager,
        jira: JiraClient,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._config = config
        self._jira = jira
        self._persisting = False  # guard against saves during init/restore
        self._labels_fetched = False
        self._tasks = ThreadedTask(self)
        # Debounce timer: delay config writes while the user types
        self._persist_timer = QTimer(self)
        self._persist_timer.setSingleShot(True)
        self._persist_timer.setInterval(300)
        self._persist_timer.timeout.connect(self._do_persist)
        self._build_ui()
        self._restore_values()
        self._persisting = True

    def _build_hard_date_column(
        self, label: str, validate_key: str
    ) -> tuple[QVBoxLayout, QDateEdit]:
        """Build a labelled fixed-date picker column with a clear (×) button.

        Returns ``(column_layout, date_edit)``.
        """
        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(4)
        lbl = QLabel(label)
        lbl.setProperty("subheading", "true")
        col.addWidget(lbl)

        input_row = QHBoxLayout()
        input_row.setSpacing(4)
        edit = _EmptyAwareDateEdit()
        no_scroll_wheel(edit)
        edit.setCalendarPopup(True)
        edit.setDisplayFormat("yyyy-MM-dd")
        edit.setSpecialValueText(" ")
        edit.setDate(edit.minimumDate())
        edit.dateChanged.connect(lambda _: self._validate_hard_dates(validate_key))
        input_row.addWidget(edit, 1)

        clear_btn = QPushButton("×")
        clear_btn.setFixedSize(18, 18)
        clear_btn.setObjectName("epicKeyChipClose")
        clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        clear_btn.clicked.connect(lambda: edit.setDate(edit.minimumDate()))
        input_row.addWidget(clear_btn)
        col.addLayout(input_row)
        return col, edit

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)

        # ── Profile selector ────────────────────────────────────────────
        self._profile_bar = ProfileBar(self._config)
        self._profile_bar.profile_changed.connect(self._on_profile_switched)
        root.addWidget(self._profile_bar)
        root.addWidget(
            self._hint(
                "Profiles store report settings separately \u2014 use them for "
                "different projects, audiences (customer-facing vs. internal), "
                "or project phases."
            )
        )

        # ── Report Items (always visible, not collapsible) ──────────────
        items_header = QHBoxLayout()
        items_header.setContentsMargins(0, 0, 0, 0)
        items_header.setSpacing(12)

        # Title + subtitle stacked in one container so the Validate button sits
        # beside the whole block (vertically centred) instead of floating at the
        # top-right with a large empty gap above the subtitle.
        header_text = QVBoxLayout()
        header_text.setContentsMargins(0, 0, 0, 0)
        header_text.setSpacing(0)
        lbl = QLabel("Report Items")
        lbl.setProperty("sectionTitle", "true")
        # Anchor scrolled into view when Generate surfaces validation errors.
        self._report_items_anchor = lbl
        header_text.addWidget(lbl)
        header_text.addWidget(
            self._hint(
                "Add Jira Epics or labels to include in the report. "
                "Labels automatically pull in all epics tagged with that label."
            )
        )
        items_header.addLayout(header_text, 1)

        self._validate_btn = QPushButton("Validate")
        self._validate_btn.setProperty("secondary", "true")
        self._validate_btn.setToolTip(
            "Check every epic and label in the table against Jira"
        )
        self._validate_btn.clicked.connect(lambda: self.validate_items())
        items_header.addWidget(self._validate_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        root.addLayout(items_header)

        self._item_table = ReportItemTable()
        root.addWidget(self._item_table)

        # Validation summary — hidden until a validation run surfaces problems.
        self._validation_summary = QLabel("")
        self._validation_summary.setObjectName("validationSummary")
        self._validation_summary.setWordWrap(True)
        self._validation_summary.setTextFormat(Qt.TextFormat.RichText)
        self._validation_summary.setVisible(False)
        root.addWidget(self._validation_summary)

        # ── Advanced Settings heading (labels the nested collapsible group) ─
        advanced_settings_lbl = QLabel("Advanced Settings")
        advanced_settings_lbl.setProperty("sectionTitle", "true")
        root.addWidget(advanced_settings_lbl)
        root.addWidget(
            self._hint(
                "Optional sections — tune the title page, progress, report "
                "content, and Jira field mapping."
            )
        )

        # ── Title Page (collapsible, collapsed) ─────────────────────────
        self._title_section = CollapsibleSection("Title Page", expanded=False)
        title = self._title_section.body_layout

        self._title_field = LabelledField(
            "Report Title",
            placeholder="Epic Progress Report",
            description="Displayed prominently on the report cover page",
        )
        title.addWidget(self._title_field)

        self._author_field = LabelledField(
            "Author",
            placeholder="Your name",
            description="Shown on the cover page as the report creator",
        )
        title.addWidget(self._author_field)

        self._project_name_field = LabelledField(
            "Project Name",
            placeholder="Auto-filled from Jira if left blank",
            description="Overrides the Jira project name shown on the cover page",
        )
        title.addWidget(self._project_name_field)

        date_lbl = QLabel("Report Date")
        date_lbl.setProperty("subheading", "true")
        title.addWidget(date_lbl)
        self._date_edit = QDateEdit()
        no_scroll_wheel(self._date_edit)
        self._date_edit.setCalendarPopup(True)
        self._date_edit.setDate(QDate.currentDate())
        title.addWidget(self._date_edit)
        title.addWidget(self._hint("Date printed on the report cover page"))

        self._conf_check = QCheckBox("Include confidentiality notice")
        title.addWidget(self._conf_check)
        title.addWidget(
            self._hint("Adds a confidentiality statement to the cover page footer")
        )

        self._company_field = LabelledField(
            "Company Name",
            placeholder="ACME Corp",
            description="Referenced in the confidentiality notice text",
        )
        title.addWidget(self._company_field)

        root.addWidget(self._title_section)

        # ── Estimation & Progress (collapsible, collapsed) ──────────────
        self._estimation_section = CollapsibleSection(
            "Estimation & Progress",
            expanded=False,
        )
        est = self._estimation_section.body_layout

        est_lbl = QLabel("Estimation Method")
        est_lbl.setProperty("subheading", "true")
        est.addWidget(est_lbl)
        self._estimation_combo = QComboBox()
        no_scroll_wheel(self._estimation_combo)
        self._estimation_combo.addItem("Story Points", "story_points")
        self._estimation_combo.addItem("Time — Days", "time_days")
        # Signals connected after the field widgets exist (end of _build_ui).
        est.addWidget(self._estimation_combo)
        est.addWidget(
            self._hint(
                "Story Points reads a numeric field on each issue. "
                "Time — Days uses the gap between start and due dates."
            )
        )

        progress_lbl = QLabel("Progress Calculation")
        progress_lbl.setProperty("subheading", "true")
        est.addWidget(progress_lbl)
        self._progress_method_combo = QComboBox()
        no_scroll_wheel(self._progress_method_combo)
        self._progress_method_combo.addItem(
            "Combined (Estimates × Issues)",
            "combined",
        )
        self._progress_method_combo.addItem("Issues Only", "issues_only")
        self._progress_method_combo.addItem(
            "Estimates Only",
            "estimates_only",
        )
        self._progress_method_combo.currentIndexChanged.connect(
            lambda _: self._persist_values()
        )
        est.addWidget(self._progress_method_combo)
        est.addWidget(
            self._hint(
                "Combined uses estimate-weighted averages multiplied by the "
                "issue-count ratio. Issues Only counts open vs done items "
                "with equal weight. Estimates Only uses estimate weights "
                "without the issue-count ratio and excludes unestimated items."
            )
        )

        self._include_subtasks_progress_check = QCheckBox(
            "Include subtasks into progress calculation"
        )
        self._include_subtasks_progress_check.setChecked(True)
        self._include_subtasks_progress_check.stateChanged.connect(
            lambda _: self._persist_values()
        )
        est.addWidget(self._include_subtasks_progress_check)
        est.addWidget(
            self._hint(
                "Fetch sub-tasks linked via the parent field and include them "
                "in progress calculations"
            )
        )

        root.addWidget(self._estimation_section)

        # ── Report Content (collapsible, collapsed) ─────────────────────
        self._content_section = CollapsibleSection("Report Content", expanded=False)
        content = self._content_section.body_layout

        self._force_light_report_check = QCheckBox("Always use light theme for report")
        self._force_light_report_check.setChecked(True)
        self._force_light_report_check.stateChanged.connect(
            lambda _: self._persist_values()
        )
        content.addWidget(self._force_light_report_check)
        content.addWidget(
            self._hint(
                "Generate the PDF with the light theme regardless of the app's theme"
            )
        )

        self._show_additional_metrics_check = QCheckBox("Show detailed metrics")
        self._show_additional_metrics_check.setChecked(True)
        self._show_additional_metrics_check.stateChanged.connect(
            lambda _: self._persist_values()
        )
        content.addWidget(self._show_additional_metrics_check)
        content.addWidget(
            self._hint(
                "Display cycle time, velocity, scope change, and completion forecast "
                "on each epic's detail page"
            )
        )

        self._expand_label_details_check = QCheckBox("Expand label epics")
        self._expand_label_details_check.setChecked(True)
        self._expand_label_details_check.stateChanged.connect(
            lambda _: self._persist_values()
        )
        content.addWidget(self._expand_label_details_check)
        content.addWidget(
            self._hint(
                "Show a separate detail page for each epic found under a label, "
                "instead of a single aggregated page"
            )
        )

        # -- Timeline subsection --
        tl_lbl = QLabel("Timeline")
        tl_lbl.setProperty("subheading", "true")
        content.addWidget(tl_lbl)

        self._show_timeline_check = QCheckBox("Include timeline page")
        self._show_timeline_check.setChecked(True)
        self._show_timeline_check.stateChanged.connect(lambda _: self._persist_values())
        content.addWidget(self._show_timeline_check)
        content.addWidget(self._hint("Add a Gantt-style timeline page to the report"))

        self._show_children_timeline_check = QCheckBox("Show stories/tasks on timeline")
        self._show_children_timeline_check.setChecked(False)
        self._show_children_timeline_check.stateChanged.connect(
            lambda _: self._persist_values()
        )
        content.addWidget(self._show_children_timeline_check)
        content.addWidget(
            self._hint(
                "Display each epic's direct stories and tasks as individual "
                "bars on the Gantt chart (not recursive subtasks)"
            )
        )

        self._include_subtasks_timeline_check = QCheckBox(
            "Include subtask dates in timeline ranges"
        )
        self._include_subtasks_timeline_check.setChecked(False)
        self._include_subtasks_timeline_check.stateChanged.connect(
            lambda _: self._persist_values()
        )
        content.addWidget(self._include_subtasks_timeline_check)
        content.addWidget(
            self._hint("Expand epic timeline ranges using subtask start/due dates")
        )

        self._show_subtasks_timeline_check = QCheckBox("Show subtasks on timeline")
        self._show_subtasks_timeline_check.setChecked(False)
        self._show_subtasks_timeline_check.stateChanged.connect(
            lambda _: self._persist_values()
        )
        content.addWidget(self._show_subtasks_timeline_check)
        content.addWidget(
            self._hint(
                "Display subtasks as individual bars on the Gantt chart "
                "alongside their parent issues"
            )
        )

        # Hard start/end dates for timeline x-axis
        hard_dates_row = QHBoxLayout()
        hard_dates_row.setSpacing(12)

        start_col, self._hard_start_edit = self._build_hard_date_column(
            "Fixed Start Date", "start"
        )
        hard_dates_row.addLayout(start_col, 1)

        end_col, self._hard_end_edit = self._build_hard_date_column(
            "Fixed End Date", "end"
        )
        hard_dates_row.addLayout(end_col, 1)

        content.addLayout(hard_dates_row)
        content.addWidget(
            self._hint(
                "Lock the timeline axis to specific dates. "
                "Leave empty to auto-scale from data."
            )
        )

        root.addWidget(self._content_section)

        # ── Jira Field Mapping (collapsible, collapsed) ─────────────────
        self._field_mapping_section = CollapsibleSection(
            "Jira Field Mapping",
            expanded=False,
        )
        fm = self._field_mapping_section.body_layout

        fm.addWidget(
            self._hint(
                "Override the Jira custom field IDs used to fetch data. "
                "Most users can leave these at their default values."
            )
        )

        self._sp_field = LabelledField(
            "Story Points Field",
            placeholder="story_points or customfield_XXXXX",
            description="Jira field ID that holds the story point value for each issue",
        )
        fm.addWidget(self._sp_field)

        est_date_fields_row = QHBoxLayout()
        est_date_fields_row.setSpacing(12)
        self._start_date_field_input = LabelledField(
            "Estimation Start Date Field",
            placeholder="startdate or customfield_XXXXX",
            description="Jira field ID for issue start date (estimation)",
        )
        est_date_fields_row.addWidget(self._start_date_field_input, 1)
        self._due_date_field_input = LabelledField(
            "Estimation Due Date Field",
            placeholder="duedate or customfield_XXXXX",
            description="Jira field ID for issue due date (estimation)",
        )
        est_date_fields_row.addWidget(self._due_date_field_input, 1)
        fm.addLayout(est_date_fields_row)

        timeline_row = QHBoxLayout()
        timeline_row.setSpacing(12)
        self._timeline_start_field = LabelledField(
            "Timeline Start Date Field",
            placeholder="startdate or customfield_XXXXX",
            description="Jira field for epic start date on the timeline",
        )
        timeline_row.addWidget(self._timeline_start_field, 1)
        self._timeline_end_field = LabelledField(
            "Timeline End Date Field",
            placeholder="duedate or customfield_XXXXX",
            description="Jira field for epic end date on the timeline",
        )
        timeline_row.addWidget(self._timeline_end_field, 1)
        fm.addLayout(timeline_row)

        self._epic_link_field = LabelledField(
            "Epic Link Field",
            placeholder="customfield_10014",
            description="Jira field ID that links child issues to their parent epic",
        )
        fm.addWidget(self._epic_link_field)

        self._detect_btn = QPushButton("Detect Fields")
        self._detect_btn.setProperty("secondary", "true")
        self._detect_btn.setToolTip("Query Jira for available fields")
        self._detect_btn.clicked.connect(self._detect_fields)
        fm.addWidget(self._detect_btn)
        fm.addWidget(
            self._hint(
                "Scan your Jira instance to find and auto-fill the correct field IDs"
            )
        )

        root.addWidget(self._field_mapping_section)

        # Connect estimation combo signals now that field widgets exist
        self._estimation_combo.currentIndexChanged.connect(
            self._on_estimation_method_changed
        )
        self._estimation_combo.currentIndexChanged.connect(
            lambda _: self._persist_values()
        )

        # Initial visibility state
        self._on_estimation_method_changed()

        # Auto-save on any change + lazy label fetch
        self._item_table.items_changed.connect(self._persist_values)
        self._item_table.items_changed.connect(self._ensure_labels_fetched)
        self._customize_busy = False  # guards against stacked customize fetches
        self._child_settings_busy = False  # guards nested per-epic settings fetches
        self._item_table.edit_requested.connect(self._on_customize_item)
        for _signal in (
            self._sp_field.field.textChanged,
            self._epic_link_field.field.textChanged,
            self._start_date_field_input.field.textChanged,
            self._due_date_field_input.field.textChanged,
            self._timeline_start_field.field.textChanged,
            self._timeline_end_field.field.textChanged,
            self._title_field.field.textChanged,
            self._author_field.field.textChanged,
            self._company_field.field.textChanged,
            self._conf_check.stateChanged,
        ):
            _signal.connect(lambda *_: self._persist_values())

    def _hint(self, text: str) -> QLabel:
        """Create a small descriptive hint label."""
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        lbl.setProperty("hint", "true")
        lbl.setContentsMargins(0, 0, 0, 8)
        return lbl

    # -- estimation method toggling -------------------------------------------

    def _on_estimation_method_changed(self) -> None:
        """Show/hide fields based on the selected estimation method."""
        method = self._estimation_combo.currentData()
        is_sp = method != "time_days"
        self._sp_field.setVisible(is_sp)
        self._start_date_field_input.setVisible(not is_sp)
        self._due_date_field_input.setVisible(not is_sp)

    # -- profile switching ----------------------------------------------------

    def _on_profile_switched(self, _name: str) -> None:
        """Reload all widgets from the newly active profile."""
        self._persisting = False
        self._restore_values()
        self._persisting = True

    # -- value persistence ----------------------------------------------------

    def _restore_values(self) -> None:
        # Migrate from old last_epic_keys to last_report_items
        saved_items = self._config.get("last_report_items", [])
        if saved_items:
            self._item_table.set_items(saved_items)
        else:
            keys = self._config.get("last_epic_keys", [])
            if keys:
                self._item_table.set_from_epic_keys(keys)

        self._title_field.text = self._config.get(
            "default_title", _DEFAULTS["default_title"]
        )
        self._author_field.text = self._config.get(
            "default_author", _DEFAULTS["default_author"]
        )
        self._company_field.text = self._config.get(
            "default_company", _DEFAULTS["default_company"]
        )
        self._conf_check.setChecked(
            self._config.get("confidential", _DEFAULTS["confidential"])
        )
        self._sp_field.text = self._config.get(
            "story_points_field", _DEFAULTS["story_points_field"]
        )
        self._epic_link_field.text = self._config.get(
            "epic_link_field", _DEFAULTS["epic_link_field"]
        )
        self._start_date_field_input.text = self._config.get(
            "start_date_field", _DEFAULTS["start_date_field"]
        )
        self._due_date_field_input.text = self._config.get(
            "due_date_field", _DEFAULTS["due_date_field"]
        )

        self._include_subtasks_progress_check.setChecked(
            self._config.get("include_subtasks", True)
        )
        self._include_subtasks_timeline_check.setChecked(
            self._config.get("include_subtasks_in_timeline", True)
        )

        # Restore estimation method (block signals so the change handler and
        # persist callback don't fire mid-restore; apply visibility once below).
        method = self._config.get("estimation_method", _DEFAULTS["estimation_method"])
        idx = self._estimation_combo.findData(method)
        if idx >= 0:
            blocked = self._estimation_combo.blockSignals(True)
            self._estimation_combo.setCurrentIndex(idx)
            self._estimation_combo.blockSignals(blocked)
        self._on_estimation_method_changed()

        # Restore progress method (backward compat: story_points_only → issues_only)
        progress_method = self._config.get(
            "progress_method", _DEFAULTS["progress_method"]
        )
        if progress_method == "story_points_only":
            progress_method = "issues_only"
        pidx = self._progress_method_combo.findData(progress_method)
        if pidx >= 0:
            self._progress_method_combo.setCurrentIndex(pidx)

        # Restore timeline fields
        self._timeline_start_field.text = self._config.get("timeline_start_field", "")
        self._timeline_end_field.text = self._config.get("timeline_end_field", "")

        # Restore hard timeline dates
        self._restore_hard_date(self._hard_start_edit, "timeline_hard_start")
        self._restore_hard_date(self._hard_end_edit, "timeline_hard_end")

        # Restore show children / subtasks on timeline
        self._show_children_timeline_check.setChecked(
            self._config.get("show_epic_stories_on_timeline", False)
        )
        self._show_subtasks_timeline_check.setChecked(
            self._config.get("show_subtasks_on_timeline", False)
        )

        # Restore expand label details
        self._expand_label_details_check.setChecked(
            self._config.get("expand_label_details", True)
        )

        # Restore show additional metrics
        self._show_additional_metrics_check.setChecked(
            self._config.get("show_additional_metrics", True)
        )

        # Restore show timeline chart
        self._show_timeline_check.setChecked(
            self._config.get("show_timeline_chart", True)
        )

        # Restore force-light report theme
        self._force_light_report_check.setChecked(
            self._config.get("report_force_light", True)
        )

    _MIN_HARD_DATE_GAP_DAYS = 5

    def _restore_hard_date(self, widget: QDateEdit, config_key: str) -> None:
        date_str = self._config.get(config_key, "")
        if date_str:
            qd = QDate.fromString(date_str, "yyyy-MM-dd")
            widget.setDate(qd if qd.isValid() else widget.minimumDate())
        else:
            widget.setDate(widget.minimumDate())

    def _validate_hard_dates(self, changed: str) -> None:
        """Ensure hard start < hard end with a minimum gap.

        When the user changes one date, the *other* date is auto-corrected if
        the constraint is violated.  Dates at the widget minimum are treated as
        "unset" and are not validated.
        """
        s_date = self._hard_start_edit.date()
        e_date = self._hard_end_edit.date()
        s_min = self._hard_start_edit.minimumDate()
        e_min = self._hard_end_edit.minimumDate()

        # If either is unset (at minimum), nothing to validate
        if s_date == s_min or e_date == e_min:
            self._persist_values()
            return

        gap = s_date.daysTo(e_date)
        if gap >= self._MIN_HARD_DATE_GAP_DAYS:
            self._persist_values()
            return

        # Auto-correct the *other* widget so user's latest choice is kept
        self._hard_start_edit.blockSignals(True)
        self._hard_end_edit.blockSignals(True)
        try:
            if changed == "start":
                self._hard_end_edit.setDate(
                    s_date.addDays(self._MIN_HARD_DATE_GAP_DAYS)
                )
            else:
                self._hard_start_edit.setDate(
                    e_date.addDays(-self._MIN_HARD_DATE_GAP_DAYS)
                )
        finally:
            self._hard_start_edit.blockSignals(False)
            self._hard_end_edit.blockSignals(False)

        self._persist_values()

    def _persist_values(self) -> None:
        """Schedule a debounced config save (300ms)."""
        if not self._persisting:
            return
        self._persist_timer.start()

    def _do_persist(self) -> None:
        """Actually write config values to disk."""
        if not self._persisting:
            return
        self._config.update(
            {
                "default_title": self._title_field.text.strip()
                or _DEFAULTS["default_title"],
                "default_author": self._author_field.text.strip(),
                "default_company": self._company_field.text.strip(),
                "confidential": self._conf_check.isChecked(),
                "last_report_items": self._item_table.get_items_as_dicts(),
                "estimation_method": self._estimation_combo.currentData()
                or _DEFAULTS["estimation_method"],
                "progress_method": self._progress_method_combo.currentData()
                or _DEFAULTS["progress_method"],
                "story_points_field": self._sp_field.text.strip()
                or _DEFAULTS["story_points_field"],
                "epic_link_field": self._epic_link_field.text.strip()
                or _DEFAULTS["epic_link_field"],
                "start_date_field": self._start_date_field_input.text.strip()
                or _DEFAULTS["start_date_field"],
                "due_date_field": self._due_date_field_input.text.strip()
                or _DEFAULTS["due_date_field"],
                "include_subtasks": self._include_subtasks_progress_check.isChecked(),
                "include_subtasks_in_timeline": (
                    self._include_subtasks_timeline_check.isChecked()
                ),
                "timeline_start_field": self._timeline_start_field.text.strip(),
                "timeline_end_field": self._timeline_end_field.text.strip(),
                "timeline_hard_start": (
                    self._hard_start_edit.date().toString("yyyy-MM-dd")
                    if self._hard_start_edit.date()
                    != self._hard_start_edit.minimumDate()
                    else ""
                ),
                "timeline_hard_end": (
                    self._hard_end_edit.date().toString("yyyy-MM-dd")
                    if self._hard_end_edit.date() != self._hard_end_edit.minimumDate()
                    else ""
                ),
                "show_epic_stories_on_timeline": (
                    self._show_children_timeline_check.isChecked()
                ),
                "show_subtasks_on_timeline": (
                    self._show_subtasks_timeline_check.isChecked()
                ),
                "expand_label_details": (self._expand_label_details_check.isChecked()),
                "show_additional_metrics": (
                    self._show_additional_metrics_check.isChecked()
                ),
                "show_timeline_chart": self._show_timeline_check.isChecked(),
                "report_force_light": self._force_light_report_check.isChecked(),
            }
        )

    # -- public API -----------------------------------------------------------

    @property
    def report_items_anchor(self) -> QWidget:
        """Widget to scroll into view when surfacing item-validation errors."""
        return self._report_items_anchor

    def get_report_config(self) -> ReportConfig | None:
        """Build and return a ReportConfig, or None if validation fails."""
        items = self._item_table.get_items()
        if not items:
            logger.warning("No report items provided")
            QMessageBox.warning(self, "No Items", "Add at least one Epic key or Label.")
            return None

        # Validate epic keys
        epic_items = [it for it in items if it.kind == "epic"]
        invalid = [it.key for it in epic_items if not RE_EPIC_KEY.match(it.key)]
        if invalid:
            logger.warning("Invalid epic key format: %s", ", ".join(invalid))
            QMessageBox.warning(
                self,
                "Invalid Epic Keys",
                f"These keys are invalid: {', '.join(invalid)}",
            )
            return None

        # Derive epic_keys for backward compat
        epic_keys = [it.key for it in epic_items]

        # Derive project key from epic key prefixes (relaxed: labels can span projects)
        prefixes = {k.rsplit("-", 1)[0] for k in epic_keys}
        project_key = (
            prefixes.pop()
            if len(prefixes) == 1
            else (sorted(prefixes)[0] if prefixes else "")
        )

        report_date = _qdate_to_date(self._date_edit.date())

        # Project name: use the user's value if given; otherwise leave it for the
        # background generation worker to resolve from Jira off the UI thread
        # (see _generate_report's auto-fill, gated on "Report"/"" placeholders).
        project_name = self._project_name_field.text.strip()
        logger.debug(
            "build_config: project_name_field=%r, project_key=%r, epic_keys=%r",
            project_name,
            project_key,
            epic_keys,
        )

        # Timeline field overrides (fall back to the date fields used for estimation)
        tl_start_raw = self._timeline_start_field.text.strip()
        tl_end_raw = self._timeline_end_field.text.strip()
        est_start_raw = self._start_date_field_input.text.strip()
        est_end_raw = self._due_date_field_input.text.strip()
        timeline_start = tl_start_raw or est_start_raw or "startdate"
        timeline_end = tl_end_raw or est_end_raw or "duedate"
        logger.debug(
            "build_config: timeline_start_input=%r → %r, "
            "timeline_end_input=%r → %r, "
            "estimation_start=%r, estimation_end=%r",
            tl_start_raw,
            timeline_start,
            tl_end_raw,
            timeline_end,
            est_start_raw or "startdate",
            est_end_raw or "duedate",
        )

        # Hard timeline date overrides (None when at minimum = unset)
        hard_start_qd = self._hard_start_edit.date()
        hard_start = (
            _qdate_to_date(hard_start_qd)
            if hard_start_qd != self._hard_start_edit.minimumDate()
            else None
        )
        hard_end_qd = self._hard_end_edit.date()
        hard_end = (
            _qdate_to_date(hard_end_qd)
            if hard_end_qd != self._hard_end_edit.minimumDate()
            else None
        )

        cfg = ReportConfig(
            epic_keys=epic_keys,
            items=items,
            title=self._title_field.text.strip() or _DEFAULTS["default_title"],
            author=self._author_field.text.strip(),
            project_display_name=project_name or "Report",
            report_date=report_date,
            confidential=self._conf_check.isChecked(),
            company_name=self._company_field.text.strip(),
            estimation_method=self._estimation_combo.currentData()
            or _DEFAULTS["estimation_method"],
            progress_method=self._progress_method_combo.currentData()
            or _DEFAULTS["progress_method"],
            story_points_field=self._sp_field.text.strip()
            or _DEFAULTS["story_points_field"],
            epic_link_field=self._epic_link_field.text.strip()
            or _DEFAULTS["epic_link_field"],
            start_date_field=self._start_date_field_input.text.strip()
            or _DEFAULTS["start_date_field"],
            due_date_field=self._due_date_field_input.text.strip()
            or _DEFAULTS["due_date_field"],
            timeline_start_field=timeline_start,
            timeline_end_field=timeline_end,
            timeline_hard_start=hard_start,
            timeline_hard_end=hard_end,
            include_subtasks=(self._include_subtasks_progress_check.isChecked()),
            include_subtasks_in_timeline=(
                self._include_subtasks_timeline_check.isChecked()
            ),
            show_epic_stories_on_timeline=(
                self._show_children_timeline_check.isChecked()
            ),
            show_subtasks_on_timeline=(self._show_subtasks_timeline_check.isChecked()),
            expand_label_details=self._expand_label_details_check.isChecked(),
            show_additional_metrics=self._show_additional_metrics_check.isChecked(),
            show_timeline_chart=self._show_timeline_check.isChecked(),
        )

        self._persist_values()
        logger.info(
            "Report config built: project=%s, items=%d", project_key, len(items)
        )
        return cfg

    def reset(self) -> None:
        """Clear all fields back to defaults."""
        self._item_table.clear()
        self._title_field.text = self._config.get(
            "default_title", _DEFAULTS["default_title"]
        )
        self._author_field.text = self._config.get(
            "default_author", _DEFAULTS["default_author"]
        )
        self._project_name_field.text = ""
        self._date_edit.setDate(QDate.currentDate())
        self._conf_check.setChecked(False)
        self._company_field.text = self._config.get(
            "default_company", _DEFAULTS["default_company"]
        )
        self._estimation_combo.setCurrentIndex(0)
        self._progress_method_combo.setCurrentIndex(0)
        self._sp_field.text = self._config.get(
            "story_points_field", _DEFAULTS["story_points_field"]
        )
        self._epic_link_field.text = self._config.get(
            "epic_link_field", _DEFAULTS["epic_link_field"]
        )
        self._start_date_field_input.text = self._config.get(
            "start_date_field", _DEFAULTS["start_date_field"]
        )
        self._due_date_field_input.text = self._config.get(
            "due_date_field", _DEFAULTS["due_date_field"]
        )
        self._timeline_start_field.text = ""
        self._timeline_end_field.text = ""
        self._hard_start_edit.setDate(self._hard_start_edit.minimumDate())
        self._hard_end_edit.setDate(self._hard_end_edit.minimumDate())
        self._include_subtasks_progress_check.setChecked(True)
        self._include_subtasks_timeline_check.setChecked(False)
        self._show_timeline_check.setChecked(True)
        self._show_children_timeline_check.setChecked(False)
        self._show_subtasks_timeline_check.setChecked(False)
        self._expand_label_details_check.setChecked(True)
        self._show_additional_metrics_check.setChecked(True)
        self._force_light_report_check.setChecked(True)
        self._clear_validation_ui()
        self._on_estimation_method_changed()
        # Collapse optional sections
        self._title_section.set_expanded(False)
        self._estimation_section.set_expanded(False)
        self._content_section.set_expanded(False)
        self._field_mapping_section.set_expanded(False)

    def refresh_label_completions(self) -> None:
        """Fetch labels from Jira and update the autocomplete list.

        Call this after a successful login to pre-populate suggestions.
        """
        self._labels_fetched = False
        self._ensure_labels_fetched()

    def _ensure_labels_fetched(self) -> None:
        """Lazily fetch Jira labels once when any label row exists."""
        if self._labels_fetched or not self._jira.connected:
            return
        self._labels_fetched = True

        def _on_labels(result: object) -> None:
            if isinstance(result, Exception):
                logger.warning("Failed to fetch labels: %s", result)
                return
            labels: list[str] = result  # type: ignore[assignment]
            if labels:
                self._item_table.set_label_completions(labels)
                logger.debug("Set %d label completions", len(labels))

        self._tasks.start(self._jira.fetch_labels, _on_labels, capture_exceptions=True)

    # -- background Jira helpers -----------------------------------------------

    def shutdown(self) -> None:
        """Wait for all background threads to finish."""
        self._tasks.wait()

    # -- helpers --------------------------------------------------------------

    def _require_connected(self) -> bool:
        """Show a 'Not Connected' notice and return ``False`` when offline."""
        if not self._jira.connected:
            QMessageBox.information(self, "Not Connected", "Connect to Jira first.")
            return False
        return True

    def validate_items(
        self, on_complete: Callable[[bool, bool], None] | None = None
    ) -> None:
        """Validate every epic and label row against Jira.

        Each non-empty row is checked: epics for key format + existence, labels
        for existence (at least one epic carries the label), and — for rows with
        per-child overrides — that every overridden child still exists. A label
        with no display name raises a (non-blocking) warning, since it falls back
        to the raw label text in the report. Problems highlight the offending row
        (red = error, amber = warning) and are listed in row order in the summary
        callout; no per-item success list is shown.

        *on_complete* (used by the Generate flow) is invoked once the check
        settles with ``(has_errors, has_warnings)`` so the caller can block on
        errors while letting warnings through. It is called for every exit path,
        including the early returns below, so callers can rely on it firing.
        """
        if not self._require_connected():
            if on_complete is not None:
                on_complete(True, False)  # cannot validate offline → block
            return

        # Snapshot each row's data on the UI thread; the worker never touches widgets.
        specs: list[dict] = []
        for row in self._item_table.rows:
            key = row.key
            if not key:
                continue
            specs.append(
                {
                    "row": row,
                    "kind": row.kind,
                    "key": key,
                    "name": row.name_edit.text().strip(),
                    "override_keys": list(row.get_child_overrides().keys()),
                }
            )

        self._clear_validation_ui()
        if not specs:
            if on_complete is not None:
                on_complete(False, False)  # nothing to validate, nothing to block
            else:
                QMessageBox.information(
                    self, "Nothing to Validate", "Add an epic or label row first."
                )
            return

        epic_link_field = (
            self._epic_link_field.text.strip() or _DEFAULTS["epic_link_field"]
        )
        logger.info("Validating %d report item(s) against Jira", len(specs))
        self._validate_btn.setEnabled(False)
        self._validate_btn.setText("Validating…")

        def _do_validate() -> list[tuple[object, str, str]]:
            # (row, severity, message) tuples, accumulated in row order.
            findings: list[tuple[object, str, str]] = []
            for spec in specs:
                kind, key, name = spec["kind"], spec["key"], spec["name"]
                override_keys = spec["override_keys"]
                children: set[str] | None = None

                if kind == "epic":
                    ekey = key.upper()
                    if not RE_EPIC_KEY.match(ekey):
                        findings.append(
                            (
                                spec["row"],
                                "error",
                                f"Epic '{key}' has an invalid key format",
                            )
                        )
                        continue
                    if not self._jira.validate_epic_key(ekey):
                        findings.append(
                            (spec["row"], "error", f"Epic '{ekey}' is not found")
                        )
                        continue
                    display = name or ekey
                    if override_keys:
                        children = {
                            k
                            for k, _ in self._jira.fetch_child_summaries(
                                ekey, epic_link_field
                            )
                        }
                else:  # label
                    epics = self._jira.fetch_epic_summaries_by_label(key)
                    if not epics:
                        findings.append(
                            (
                                spec["row"],
                                "error",
                                f"Label '{key}' is invalid (no epics carry it)",
                            )
                        )
                        continue
                    display = name or key
                    if not name:
                        findings.append(
                            (
                                spec["row"],
                                "warning",
                                f"Label '{key}' has no display name — it will "
                                f"appear as '{key}' in the report",
                            )
                        )
                    if override_keys:
                        children = {k for k, _ in epics}

                if override_keys and children is not None:
                    missing = [k for k in override_keys if k not in children]
                    if missing:
                        verb = "exists" if len(missing) == 1 else "exist"
                        findings.append(
                            (
                                spec["row"],
                                "warning",
                                f"{kind.capitalize()} '{display}' has stale child "
                                f"overrides ({', '.join(missing)} no longer {verb})",
                            )
                        )
            return findings

        def _on_validated(result: object) -> None:
            self._validate_btn.setEnabled(True)
            self._validate_btn.setText("Validate")
            if isinstance(result, Exception):
                logger.warning("Validation failed: %s", result)
                self._show_validation_message("error", f"Validation failed: {result}")
                if on_complete is not None:
                    on_complete(True, False)  # errored → block to be safe
                return
            findings: list[tuple[object, str, str]] = result  # type: ignore[assignment]
            problems: list[tuple[str, str]] = []
            state_by_row: dict[object, str] = {}
            for row, severity, message in findings:
                problems.append((severity, message))
                if state_by_row.get(row) != "error":  # error outranks warning
                    state_by_row[row] = severity
            for row, state in state_by_row.items():
                row.set_validation(state)  # type: ignore[attr-defined]
            self._show_validation_summary(problems)
            if on_complete is not None:
                has_errors = any(sev == "error" for sev, _ in problems)
                has_warnings = any(sev == "warning" for sev, _ in problems)
                on_complete(has_errors, has_warnings)

        self._tasks.start(_do_validate, _on_validated, capture_exceptions=True)

    def _clear_validation_ui(self) -> None:
        """Reset row highlights and hide the validation summary callout."""
        self._item_table.clear_validation()
        self._validation_summary.clear()
        self._validation_summary.setVisible(False)

    def _show_validation_summary(self, problems: list[tuple[str, str]]) -> None:
        """Render the validation callout from ``(severity, message)`` items.

        Problems are listed in the given (row) order; with none, a brief success
        confirmation is shown instead of any per-item list.
        """
        if not problems:
            self._show_validation_message("ok", "✓ All items are valid.")
            return
        has_error = any(sev == "error" for sev, _ in problems)
        count = len(problems)
        lines = [f"<b>⚠ {count} problem{'' if count == 1 else 's'} found</b>"]
        for severity, message in problems:
            color = "#e53935" if severity == "error" else "#ff8f00"
            tag = "Error" if severity == "error" else "Warning"
            lines.append(
                f"• <span style='color:{color};'><b>{tag}:</b></span> "
                f"{html.escape(message)}"
            )
        self._apply_summary_style("error" if has_error else "warning")
        self._validation_summary.setText("<br>".join(lines))
        self._validation_summary.setVisible(True)

    def _show_validation_message(self, severity: str, text: str) -> None:
        """Show a single styled line in the validation callout."""
        self._apply_summary_style(severity)
        self._validation_summary.setText(html.escape(text))
        self._validation_summary.setVisible(True)

    def _apply_summary_style(self, severity: str) -> None:
        """Colour the validation callout's border/background by *severity*."""
        palette = {
            "error": ("#e53935", "rgba(229, 57, 53, 0.08)"),
            "warning": ("#ff8f00", "rgba(255, 143, 0, 0.10)"),
            "ok": ("#43a047", "rgba(67, 160, 71, 0.10)"),
        }
        accent, background = palette.get(severity, palette["error"])
        self._validation_summary.setStyleSheet(
            f"#validationSummary {{ border: 1px solid {accent}; "
            f"background: {background}; border-radius: 4px; padding: 8px 10px; }}"
        )

    def _on_customize_item(self, row: object) -> None:
        """Open the per-item customize dialog (FR-13).

        Fetches the item's children fresh from Jira on every click, then shows
        the dialog pre-filled with any existing overrides.  Accepting writes the
        overrides back onto the row, which persists via ``items_changed``.
        """
        if not self._require_connected():
            return

        kind = row.kind  # type: ignore[attr-defined]
        key = row.key  # type: ignore[attr-defined]
        if not key:
            QMessageBox.information(
                self, "No Key", "Enter an Epic key or label before customizing."
            )
            return
        if kind == "epic" and not RE_EPIC_KEY.match(key.upper()):
            QMessageBox.warning(
                self, "Invalid Epic Key", f"'{key}' is not a valid epic key."
            )
            return

        if self._customize_busy:
            logger.debug("Customize already in progress; ignoring repeat click")
            return
        parent_certainty = row.scope_certainty  # type: ignore[attr-defined]
        overrides = row.get_child_overrides()  # type: ignore[attr-defined]
        child_order = row.get_child_order()  # type: ignore[attr-defined]
        epic_link_field = (
            self._epic_link_field.text.strip() or _DEFAULTS["epic_link_field"]
        )
        logger.info("Customizing %s item %s", kind, key)

        def _fetch() -> list[tuple[str, str]]:
            if kind == "label":
                return self._jira.fetch_epic_summaries_by_label(key)
            return self._jira.fetch_child_summaries(key.upper(), epic_link_field)

        def _on_fetched(result: object) -> None:
            self._customize_busy = False
            if isinstance(result, Exception):
                QMessageBox.warning(
                    self, "Error", f"Failed to load child items: {result}"
                )
                return
            children: list[tuple[str, str]] = result  # type: ignore[assignment]
            dialog = ChildCustomizeDialog(
                kind=kind,
                parent_key=key,
                parent_certainty=parent_certainty,
                children=children,
                overrides=overrides,
                child_order=child_order,
                parent=self,
            )
            # For label items the children are epics — wire the per-epic gear so
            # the user can drill into each epic's own stories/tasks.
            dialog.child_settings_requested.connect(
                lambda child_row: self._on_child_epic_settings(dialog, child_row)
            )
            if exec_dialog(dialog) == QDialog.DialogCode.Accepted:
                new_overrides = dialog.get_overrides()
                row.set_child_overrides(new_overrides)  # type: ignore[attr-defined]
                row.set_child_order(dialog.get_child_order())  # type: ignore[attr-defined]
                logger.info(
                    "Saved %d child override(s) for %s", len(new_overrides), key
                )

        self._customize_busy = True
        self._tasks.start(_fetch, _on_fetched, capture_exceptions=True)

    def _on_child_epic_settings(
        self, parent_dialog: QDialog, child_row: object
    ) -> None:
        """Open a nested customize dialog for an epic child's stories/tasks.

        Reached from the gear on an epic row inside a *label* item's customize
        dialog. Mirrors :meth:`_on_customize_item`: the epic's children are
        fetched fresh from Jira on every open, the dialog is pre-filled with the
        row's nested overrides, and accepting writes them back onto the row (so
        they persist when the outer dialog is saved).
        """
        if self._child_settings_busy:
            logger.debug("Child settings fetch already in progress; ignoring click")
            return
        epic_key = child_row.key  # type: ignore[attr-defined]
        if not RE_EPIC_KEY.match(epic_key.upper()):
            QMessageBox.warning(
                parent_dialog,
                "Invalid Epic Key",
                f"'{epic_key}' is not a valid epic key.",
            )
            return
        epic_link_field = (
            self._epic_link_field.text.strip() or _DEFAULTS["epic_link_field"]
        )
        parent_certainty = child_row.effective_certainty()  # type: ignore[attr-defined]
        overrides = child_row.get_nested_overrides()  # type: ignore[attr-defined]
        child_order = child_row.nested_order()  # type: ignore[attr-defined]
        logger.info("Customizing stories/tasks of epic child %s", epic_key)

        def _fetch() -> list[tuple[str, str]]:
            return self._jira.fetch_child_summaries(epic_key.upper(), epic_link_field)

        def _on_fetched(result: object) -> None:
            self._child_settings_busy = False
            if isinstance(result, Exception):
                QMessageBox.warning(
                    parent_dialog, "Error", f"Failed to load child items: {result}"
                )
                return
            grandchildren: list[tuple[str, str]] = result  # type: ignore[assignment]
            nested = ChildCustomizeDialog(
                kind="epic",
                parent_key=epic_key,
                parent_certainty=parent_certainty,
                children=grandchildren,
                overrides=overrides,
                child_order=child_order,
                parent=parent_dialog,
            )
            if exec_dialog(nested) == QDialog.DialogCode.Accepted:
                child_row.set_nested(  # type: ignore[attr-defined]
                    nested.get_overrides(), nested.get_child_order()
                )
                logger.info("Saved nested overrides for epic child %s", epic_key)

        self._child_settings_busy = True
        self._tasks.start(_fetch, _on_fetched, capture_exceptions=True)

    def _detect_fields(self) -> None:
        if not self._require_connected():
            return
        logger.info("Detecting Jira custom fields")
        self._detect_btn.setEnabled(False)
        self._detect_btn.setText("Detecting…")

        def _on_fields_fetched(result: object) -> None:
            self._detect_btn.setEnabled(True)
            self._detect_btn.setText("Detect Fields")
            if isinstance(result, Exception):
                QMessageBox.warning(self, "Error", f"Failed to fetch fields: {result}")
                return
            fields: list[dict[str, str]] = result  # type: ignore[assignment]
            method = self._estimation_combo.currentData() or "story_points"

            # Classify each field once into every bucket it matches (a single
            # field can be e.g. both a start-date and a timeline-start candidate).
            sp_candidates: list[dict[str, str]] = []
            epic_candidates: list[dict[str, str]] = []
            start_date_candidates: list[dict[str, str]] = []
            due_date_candidates: list[dict[str, str]] = []
            timeline_start_candidates: list[dict[str, str]] = []
            timeline_end_candidates: list[dict[str, str]] = []
            for f in fields:
                name = f["name"].lower()
                if "point" in name or "story" in name:
                    sp_candidates.append(f)
                if "epic" in name and "link" in name:
                    epic_candidates.append(f)
                if "start" in name and "date" in name:
                    start_date_candidates.append(f)
                if "due" in name or ("end" in name and "date" in name):
                    due_date_candidates.append(f)
                if "start" in name and ("date" in name or "target" in name):
                    timeline_start_candidates.append(f)
                if ("due" in name or "target end" in name) or (
                    "end" in name and "date" in name
                ):
                    timeline_end_candidates.append(f)

            has_any = (
                sp_candidates
                or epic_candidates
                or start_date_candidates
                or due_date_candidates
                or timeline_start_candidates
                or timeline_end_candidates
            )
            if not has_any:
                QMessageBox.information(
                    self,
                    "No Fields Detected",
                    "No matching fields were found.\n"
                    "You may need to set them manually.",
                )
                return

            dialog = FieldPickerDialog(
                sp_candidates,
                epic_candidates,
                parent=self,
                estimation_method=method,
                start_date_candidates=start_date_candidates,
                due_date_candidates=due_date_candidates,
                timeline_start_candidates=timeline_start_candidates,
                timeline_end_candidates=timeline_end_candidates,
                current_values={
                    "story_points_field": self._sp_field.text.strip(),
                    "epic_link_field": self._epic_link_field.text.strip(),
                    "start_date_field": self._start_date_field_input.text.strip(),
                    "due_date_field": self._due_date_field_input.text.strip(),
                    "timeline_start_field": self._timeline_start_field.text.strip(),
                    "timeline_end_field": self._timeline_end_field.text.strip(),
                },
            )
            if exec_dialog(dialog) == QDialog.DialogCode.Accepted:
                if method == "story_points":
                    sp_id = dialog.selected_sp_field
                    if sp_id:
                        self._sp_field.text = sp_id
                else:
                    start_id = dialog.selected_start_date_field
                    if start_id:
                        self._start_date_field_input.text = start_id
                    due_id = dialog.selected_due_date_field
                    if due_id:
                        self._due_date_field_input.text = due_id
                epic_id = dialog.selected_epic_field
                if epic_id:
                    self._epic_link_field.text = epic_id
                tl_start_id = dialog.selected_timeline_start_field
                if tl_start_id:
                    self._timeline_start_field.text = tl_start_id
                tl_end_id = dialog.selected_timeline_end_field
                if tl_end_id:
                    self._timeline_end_field.text = tl_end_id
                logger.info("Fields applied (method=%s)", method)

        self._tasks.start(
            self._jira.fetch_fields, _on_fields_fetched, capture_exceptions=True
        )
