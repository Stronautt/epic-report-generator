"""Report configuration panel."""

from __future__ import annotations

import logging
from datetime import date

from PySide6.QtCore import QDate, QObject, Qt, QThread, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
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
from epic_report_generator.services.config_manager import ConfigManager
from epic_report_generator.ui.widgets import (
    RE_EPIC_KEY,
    CollapsibleSection,
    LabelledField,
    ProfileBar,
    ReportItemTable,
    no_scroll_wheel,
)

logger = logging.getLogger(__name__)


class _JiraCallWorker(QObject):
    """Run a callable in a background QThread and emit the result."""

    finished = Signal(object)  # result of the callable

    def __init__(self, fn: object) -> None:
        super().__init__()
        self._fn = fn

    def run(self) -> None:
        """Execute the callable and emit the result."""
        try:
            result = self._fn()  # type: ignore[operator]
        except Exception as exc:
            logger.warning("Background Jira call failed: %s", exc)
            result = exc
        self.finished.emit(result)


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
        self.setMinimumWidth(420)

        layout = QFormLayout(self)

        self._estimation_method = estimation_method
        cv = current_values or {}

        # Story Points field (only shown for story_points method)
        self._sp_combo = QComboBox()
        no_scroll_wheel(self._sp_combo)
        if estimation_method == "story_points":
            if sp_candidates:
                for f in sp_candidates:
                    self._sp_combo.addItem(
                        f"{f['name']}  —  {f['id']}", userData=f["id"]
                    )
                self._select_current(self._sp_combo, cv.get("story_points_field"))
            else:
                self._sp_combo.addItem("(No matches found)")
                self._sp_combo.setEnabled(False)
            layout.addRow("Story Points Field:", self._sp_combo)

        # Date fields (only shown for time_days method)
        self._start_date_combo = QComboBox()
        no_scroll_wheel(self._start_date_combo)
        self._due_date_combo = QComboBox()
        no_scroll_wheel(self._due_date_combo)
        if estimation_method == "time_days":
            start_candidates = start_date_candidates or []
            due_candidates = due_date_candidates or []
            if start_candidates:
                for f in start_candidates:
                    self._start_date_combo.addItem(
                        f"{f['name']}  —  {f['id']}", userData=f["id"]
                    )
                self._select_current(self._start_date_combo, cv.get("start_date_field"))
            else:
                self._start_date_combo.addItem("(No matches found)")
                self._start_date_combo.setEnabled(False)
            layout.addRow("Start Date Field:", self._start_date_combo)

            if due_candidates:
                for f in due_candidates:
                    self._due_date_combo.addItem(
                        f"{f['name']}  —  {f['id']}", userData=f["id"]
                    )
                self._select_current(self._due_date_combo, cv.get("due_date_field"))
            else:
                self._due_date_combo.addItem("(No matches found)")
                self._due_date_combo.setEnabled(False)
            layout.addRow("Due Date Field:", self._due_date_combo)

        self._epic_combo = QComboBox()
        no_scroll_wheel(self._epic_combo)
        if epic_candidates:
            for f in epic_candidates:
                self._epic_combo.addItem(f"{f['name']}  —  {f['id']}", userData=f["id"])
            self._select_current(self._epic_combo, cv.get("epic_link_field"))
        else:
            self._epic_combo.addItem("(No matches found)")
            self._epic_combo.setEnabled(False)
        layout.addRow("Epic Link Field:", self._epic_combo)

        # Timeline fields (always shown)
        tl_start = timeline_start_candidates or []
        tl_end = timeline_end_candidates or []

        self._timeline_start_combo = QComboBox()
        no_scroll_wheel(self._timeline_start_combo)
        if tl_start:
            for f in tl_start:
                self._timeline_start_combo.addItem(
                    f"{f['name']}  —  {f['id']}", userData=f["id"]
                )
            self._select_current(
                self._timeline_start_combo, cv.get("timeline_start_field")
            )
        else:
            self._timeline_start_combo.addItem("(No matches found)")
            self._timeline_start_combo.setEnabled(False)
        layout.addRow("Timeline Start Field:", self._timeline_start_combo)

        self._timeline_end_combo = QComboBox()
        no_scroll_wheel(self._timeline_end_combo)
        if tl_end:
            for f in tl_end:
                self._timeline_end_combo.addItem(
                    f"{f['name']}  —  {f['id']}", userData=f["id"]
                )
            self._select_current(self._timeline_end_combo, cv.get("timeline_end_field"))
        else:
            self._timeline_end_combo.addItem("(No matches found)")
            self._timeline_end_combo.setEnabled(False)
        layout.addRow("Timeline End Field:", self._timeline_end_combo)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    @staticmethod
    def _select_current(combo: QComboBox, value: str | None) -> None:
        """Pre-select the combo item matching *value* (by userData)."""
        if not value:
            return
        idx = combo.findData(value)
        if idx >= 0:
            combo.setCurrentIndex(idx)

    @property
    def selected_sp_field(self) -> str | None:
        """Return the selected Story Points field ID, or None if unavailable."""
        if not self._sp_combo.isEnabled():
            return None
        return self._sp_combo.currentData()

    @property
    def selected_epic_field(self) -> str | None:
        """Return the selected Epic Link field ID, or None if unavailable."""
        if not self._epic_combo.isEnabled():
            return None
        return self._epic_combo.currentData()

    @property
    def selected_start_date_field(self) -> str | None:
        """Return the selected Start Date field ID, or None if unavailable."""
        if not self._start_date_combo.isEnabled():
            return None
        return self._start_date_combo.currentData()

    @property
    def selected_due_date_field(self) -> str | None:
        """Return the selected Due Date field ID, or None if unavailable."""
        if not self._due_date_combo.isEnabled():
            return None
        return self._due_date_combo.currentData()

    @property
    def selected_timeline_start_field(self) -> str | None:
        """Return the selected Timeline Start field ID, or None if unavailable."""
        if not self._timeline_start_combo.isEnabled():
            return None
        return self._timeline_start_combo.currentData()

    @property
    def selected_timeline_end_field(self) -> str | None:
        """Return the selected Timeline End field ID, or None if unavailable."""
        if not self._timeline_end_combo.isEnabled():
            return None
        return self._timeline_end_combo.currentData()


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
        self._bg_threads: list[QThread] = []
        # Debounce timer for config persistence (300ms)
        self._persist_timer = QTimer(self)
        self._persist_timer.setSingleShot(True)
        self._persist_timer.setInterval(300)
        self._persist_timer.timeout.connect(self._do_persist)
        self._build_ui()
        self._restore_values()
        self._persisting = True

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)

        # ── Profile selector ────────────────────────────────────────────
        self._profile_bar = ProfileBar(self._config)
        self._profile_bar.profile_changed.connect(self._on_profile_switched)
        root.addWidget(self._profile_bar)

        # ── Report Items (always visible, not collapsible) ──────────────
        lbl = QLabel("Report Items")
        lbl.setProperty("subheading", "true")
        root.addWidget(lbl)
        root.addWidget(
            self._hint(
                "Add Jira Epics or labels to include in the report. "
                "Labels automatically pull in all epics tagged with that label."
            )
        )
        self._item_table = ReportItemTable()
        root.addWidget(self._item_table)

        btn_row = QHBoxLayout()
        validate_btn = QPushButton("Validate Epics")
        validate_btn.setProperty("secondary", "true")
        validate_btn.setToolTip("Check each Epic key against Jira")
        validate_btn.clicked.connect(self._validate_epics)
        btn_row.addWidget(validate_btn)
        btn_row.addStretch()
        root.addLayout(btn_row)

        self._validation_label = QLabel("")
        self._validation_label.setWordWrap(True)
        root.addWidget(self._validation_label)

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
        self._estimation_combo.currentIndexChanged.connect(
            self._on_estimation_method_changed
        )
        self._estimation_combo.currentIndexChanged.connect(
            lambda _: self._persist_values()
        )
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
        self._progress_method_combo.addItem("Estimates Only", "story_points_only")
        self._progress_method_combo.currentIndexChanged.connect(
            lambda _: self._persist_values()
        )
        est.addWidget(self._progress_method_combo)
        est.addWidget(
            self._hint(
                "Combined multiplies the estimate ratio by the issue-count ratio. "
                "Estimates Only uses the estimate ratio alone."
            )
        )

        self._sp_field = LabelledField(
            "Story Points Field",
            placeholder="story_points or customfield_XXXXX",
            description="Jira field ID that holds the story point value for each issue",
        )
        est.addWidget(self._sp_field)

        date_fields_row = QHBoxLayout()
        date_fields_row.setSpacing(12)
        self._start_date_field_input = LabelledField(
            "Start Date Field",
            placeholder="startdate or customfield_XXXXX",
            description="Jira field ID for issue start date",
        )
        date_fields_row.addWidget(self._start_date_field_input, 1)
        self._due_date_field_input = LabelledField(
            "Due Date Field",
            placeholder="duedate or customfield_XXXXX",
            description="Jira field ID for issue due date",
        )
        date_fields_row.addWidget(self._due_date_field_input, 1)
        est.addLayout(date_fields_row)

        self._include_subtasks_check = QCheckBox("Include subtasks")
        self._include_subtasks_check.setChecked(True)
        self._include_subtasks_check.stateChanged.connect(
            lambda _: self._persist_values()
        )
        est.addWidget(self._include_subtasks_check)
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

        root.addWidget(self._content_section)

        # ── Timeline Chart (collapsible, collapsed) ─────────────────────
        self._timeline_section = CollapsibleSection("Timeline Chart", expanded=False)
        tl = self._timeline_section.body_layout

        self._show_children_timeline_check = QCheckBox("Show child issues on timeline")
        self._show_children_timeline_check.setChecked(False)
        self._show_children_timeline_check.stateChanged.connect(
            lambda _: self._persist_values()
        )
        tl.addWidget(self._show_children_timeline_check)
        tl.addWidget(
            self._hint(
                "Display each child issue as an individual bar on the Gantt chart "
                "alongside epics"
            )
        )

        timeline_row = QHBoxLayout()
        timeline_row.setSpacing(12)
        self._timeline_start_field = LabelledField(
            "Start Date Field",
            placeholder="startdate or customfield_XXXXX",
            description="Jira field for epic start date on the timeline",
        )
        timeline_row.addWidget(self._timeline_start_field, 1)
        self._timeline_end_field = LabelledField(
            "End Date Field",
            placeholder="duedate or customfield_XXXXX",
            description="Jira field for epic end date on the timeline",
        )
        timeline_row.addWidget(self._timeline_end_field, 1)
        tl.addLayout(timeline_row)

        # Hard start/end dates for timeline x-axis
        hard_dates_row = QHBoxLayout()
        hard_dates_row.setSpacing(12)

        # -- Start date column --
        start_col = QVBoxLayout()
        start_col.setContentsMargins(0, 0, 0, 0)
        start_col.setSpacing(4)
        start_lbl = QLabel("Fixed Start Date")
        start_lbl.setProperty("subheading", "true")
        start_col.addWidget(start_lbl)
        start_input_row = QHBoxLayout()
        start_input_row.setSpacing(4)
        self._hard_start_edit = QDateEdit()
        no_scroll_wheel(self._hard_start_edit)
        self._hard_start_edit.setCalendarPopup(True)
        self._hard_start_edit.setDisplayFormat("yyyy-MM-dd")
        self._hard_start_edit.setSpecialValueText(" ")
        self._hard_start_edit.setDate(self._hard_start_edit.minimumDate())
        self._hard_start_edit.dateChanged.connect(
            lambda _: self._validate_hard_dates("start")
        )
        start_input_row.addWidget(self._hard_start_edit, 1)
        clear_start_btn = QPushButton("×")
        clear_start_btn.setFixedSize(18, 18)
        clear_start_btn.setObjectName("epicKeyChipClose")
        clear_start_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        clear_start_btn.clicked.connect(
            lambda: self._hard_start_edit.setDate(self._hard_start_edit.minimumDate())
        )
        start_input_row.addWidget(clear_start_btn)
        start_col.addLayout(start_input_row)
        hard_dates_row.addLayout(start_col, 1)

        # -- End date column --
        end_col = QVBoxLayout()
        end_col.setContentsMargins(0, 0, 0, 0)
        end_col.setSpacing(4)
        end_lbl = QLabel("Fixed End Date")
        end_lbl.setProperty("subheading", "true")
        end_col.addWidget(end_lbl)
        end_input_row = QHBoxLayout()
        end_input_row.setSpacing(4)
        self._hard_end_edit = QDateEdit()
        no_scroll_wheel(self._hard_end_edit)
        self._hard_end_edit.setCalendarPopup(True)
        self._hard_end_edit.setDisplayFormat("yyyy-MM-dd")
        self._hard_end_edit.setSpecialValueText(" ")
        self._hard_end_edit.setDate(self._hard_end_edit.minimumDate())
        self._hard_end_edit.dateChanged.connect(
            lambda _: self._validate_hard_dates("end")
        )
        end_input_row.addWidget(self._hard_end_edit, 1)
        clear_end_btn = QPushButton("×")
        clear_end_btn.setFixedSize(18, 18)
        clear_end_btn.setObjectName("epicKeyChipClose")
        clear_end_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        clear_end_btn.clicked.connect(
            lambda: self._hard_end_edit.setDate(self._hard_end_edit.minimumDate())
        )
        end_input_row.addWidget(clear_end_btn)
        end_col.addLayout(end_input_row)
        hard_dates_row.addLayout(end_col, 1)

        tl.addLayout(hard_dates_row)
        tl.addWidget(
            self._hint(
                "Lock the timeline axis to specific dates. "
                "Leave empty to auto-scale from data."
            )
        )

        root.addWidget(self._timeline_section)

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

        self._epic_link_field = LabelledField(
            "Epic Link Field",
            placeholder="customfield_10014",
            description="Jira field ID that links child issues to their parent epic",
        )
        fm.addWidget(self._epic_link_field)

        detect_btn = QPushButton("Detect Fields")
        detect_btn.setProperty("secondary", "true")
        detect_btn.setToolTip("Query Jira for available fields")
        detect_btn.clicked.connect(self._detect_fields)
        fm.addWidget(detect_btn)
        fm.addWidget(
            self._hint(
                "Scan your Jira instance to find and auto-fill the correct field IDs"
            )
        )

        root.addWidget(self._field_mapping_section)

        # Initial visibility state
        self._on_estimation_method_changed()

        # Auto-save on any change + lazy label fetch
        self._item_table.items_changed.connect(self._persist_values)
        self._item_table.items_changed.connect(self._ensure_labels_fetched)
        self._sp_field.field.textChanged.connect(lambda _: self._persist_values())
        self._epic_link_field.field.textChanged.connect(
            lambda _: self._persist_values()
        )
        self._start_date_field_input.field.textChanged.connect(
            lambda _: self._persist_values()
        )
        self._due_date_field_input.field.textChanged.connect(
            lambda _: self._persist_values()
        )
        self._timeline_start_field.field.textChanged.connect(
            lambda _: self._persist_values()
        )
        self._timeline_end_field.field.textChanged.connect(
            lambda _: self._persist_values()
        )
        self._title_field.field.textChanged.connect(lambda _: self._persist_values())
        self._author_field.field.textChanged.connect(lambda _: self._persist_values())
        self._company_field.field.textChanged.connect(lambda _: self._persist_values())
        self._conf_check.stateChanged.connect(lambda _: self._persist_values())

    def _hint(self, text: str) -> QLabel:
        """Create a small descriptive hint label."""
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        lbl.setProperty("subheading", "true")
        lbl.setContentsMargins(0, 0, 0, 4)
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
            "default_title", "Epic Progress Report"
        )
        self._author_field.text = self._config.get("default_author", "")
        self._company_field.text = self._config.get("default_company", "")
        self._conf_check.setChecked(self._config.get("confidential", False))
        self._sp_field.text = self._config.get("story_points_field", "story_points")
        self._epic_link_field.text = self._config.get(
            "epic_link_field", "customfield_10014"
        )
        self._start_date_field_input.text = self._config.get(
            "start_date_field", "startdate"
        )
        self._due_date_field_input.text = self._config.get("due_date_field", "duedate")

        self._include_subtasks_check.setChecked(
            self._config.get("include_subtasks", True)
        )

        # Restore estimation method
        method = self._config.get("estimation_method", "story_points")
        idx = self._estimation_combo.findData(method)
        if idx >= 0:
            self._estimation_combo.setCurrentIndex(idx)
        self._on_estimation_method_changed()

        # Restore progress method
        progress_method = self._config.get("progress_method", "combined")
        pidx = self._progress_method_combo.findData(progress_method)
        if pidx >= 0:
            self._progress_method_combo.setCurrentIndex(pidx)

        # Restore timeline fields
        self._timeline_start_field.text = self._config.get("timeline_start_field", "")
        self._timeline_end_field.text = self._config.get("timeline_end_field", "")

        # Restore hard timeline dates
        self._restore_hard_date(self._hard_start_edit, "timeline_hard_start")
        self._restore_hard_date(self._hard_end_edit, "timeline_hard_end")

        # Restore show children on timeline
        self._show_children_timeline_check.setChecked(
            self._config.get("show_children_on_timeline", False)
        )

        # Restore expand label details
        self._expand_label_details_check.setChecked(
            self._config.get("expand_label_details", True)
        )

        # Restore show additional metrics
        self._show_additional_metrics_check.setChecked(
            self._config.get("show_additional_metrics", True)
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
        """Ensure hard start < hard end with at least 5 days between them.

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
                or "Epic Progress Report",
                "default_author": self._author_field.text.strip(),
                "default_company": self._company_field.text.strip(),
                "confidential": self._conf_check.isChecked(),
                "last_report_items": self._item_table.get_items_as_dicts(),
                "estimation_method": self._estimation_combo.currentData()
                or "story_points",
                "progress_method": self._progress_method_combo.currentData()
                or "combined",
                "story_points_field": self._sp_field.text.strip() or "story_points",
                "epic_link_field": self._epic_link_field.text.strip()
                or "customfield_10014",
                "start_date_field": self._start_date_field_input.text.strip()
                or "startdate",
                "due_date_field": self._due_date_field_input.text.strip() or "duedate",
                "include_subtasks": self._include_subtasks_check.isChecked(),
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
                "show_children_on_timeline": (
                    self._show_children_timeline_check.isChecked()
                ),
                "expand_label_details": (self._expand_label_details_check.isChecked()),
                "show_additional_metrics": (
                    self._show_additional_metrics_check.isChecked()
                ),
            }
        )

    # -- public API -----------------------------------------------------------

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

        qdate = self._date_edit.date()
        report_date = date(qdate.year(), qdate.month(), qdate.day())

        # Attempt to pre-fill project name from Jira
        project_name = self._project_name_field.text.strip()
        if not project_name and project_key and self._jira.connected:
            project_name = self._jira.get_project_name(project_key) or project_key

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
            date(hard_start_qd.year(), hard_start_qd.month(), hard_start_qd.day())
            if hard_start_qd != self._hard_start_edit.minimumDate()
            else None
        )
        hard_end_qd = self._hard_end_edit.date()
        hard_end = (
            date(hard_end_qd.year(), hard_end_qd.month(), hard_end_qd.day())
            if hard_end_qd != self._hard_end_edit.minimumDate()
            else None
        )

        cfg = ReportConfig(
            project_key=project_key,
            epic_keys=epic_keys,
            items=items,
            title=self._title_field.text.strip() or "Epic Progress Report",
            author=self._author_field.text.strip(),
            project_display_name=project_name or project_key or "Report",
            report_date=report_date,
            confidential=self._conf_check.isChecked(),
            company_name=self._company_field.text.strip(),
            estimation_method=self._estimation_combo.currentData() or "story_points",
            progress_method=self._progress_method_combo.currentData() or "combined",
            story_points_field=self._sp_field.text.strip() or "story_points",
            epic_link_field=self._epic_link_field.text.strip() or "customfield_10014",
            start_date_field=self._start_date_field_input.text.strip() or "startdate",
            due_date_field=self._due_date_field_input.text.strip() or "duedate",
            timeline_start_field=timeline_start,
            timeline_end_field=timeline_end,
            timeline_hard_start=hard_start,
            timeline_hard_end=hard_end,
            include_subtasks=self._include_subtasks_check.isChecked(),
            show_children_on_timeline=self._show_children_timeline_check.isChecked(),
            expand_label_details=self._expand_label_details_check.isChecked(),
            show_additional_metrics=self._show_additional_metrics_check.isChecked(),
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
            "default_title", "Epic Progress Report"
        )
        self._author_field.text = self._config.get("default_author", "")
        self._project_name_field.text = ""
        self._date_edit.setDate(QDate.currentDate())
        self._conf_check.setChecked(False)
        self._company_field.text = self._config.get("default_company", "")
        self._estimation_combo.setCurrentIndex(0)
        self._progress_method_combo.setCurrentIndex(0)
        self._sp_field.text = self._config.get("story_points_field", "story_points")
        self._epic_link_field.text = self._config.get(
            "epic_link_field", "customfield_10014"
        )
        self._start_date_field_input.text = self._config.get(
            "start_date_field", "startdate"
        )
        self._due_date_field_input.text = self._config.get("due_date_field", "duedate")
        self._timeline_start_field.text = ""
        self._timeline_end_field.text = ""
        self._hard_start_edit.setDate(self._hard_start_edit.minimumDate())
        self._hard_end_edit.setDate(self._hard_end_edit.minimumDate())
        self._include_subtasks_check.setChecked(True)
        self._show_children_timeline_check.setChecked(False)
        self._expand_label_details_check.setChecked(True)
        self._show_additional_metrics_check.setChecked(True)
        self._validation_label.clear()
        self._on_estimation_method_changed()
        # Collapse optional sections
        self._title_section.set_expanded(False)
        self._estimation_section.set_expanded(False)
        self._content_section.set_expanded(False)
        self._timeline_section.set_expanded(False)
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

        self._run_background(self._jira.fetch_labels, _on_labels)

    # -- background Jira helpers -----------------------------------------------

    def _run_background(self, fn: object, callback: object) -> None:
        """Run *fn* in a background thread and call *callback* with the result."""
        thread = QThread(self)
        worker = _JiraCallWorker(fn)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(callback)  # type: ignore[arg-type]
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        self._bg_threads.append(thread)

        def _on_finished(t: QThread = thread) -> None:
            if t in self._bg_threads:
                self._bg_threads.remove(t)

        thread.finished.connect(_on_finished)
        thread.finished.connect(thread.deleteLater)
        thread.start()

    def shutdown(self) -> None:
        """Wait for all background threads to finish."""
        for thread in list(self._bg_threads):
            thread.quit()
            thread.wait()
        self._bg_threads.clear()

    # -- helpers --------------------------------------------------------------

    def _validate_epics(self) -> None:
        if not self._jira.connected:
            QMessageBox.information(self, "Not Connected", "Connect to Jira first.")
            return
        items = self._item_table.get_items()
        epic_keys = [it.key for it in items if it.kind == "epic"]
        logger.info("Validating %d epic key(s) against Jira", len(epic_keys))
        if not epic_keys:
            self._validation_label.setText(
                "No epic keys to validate (labels are not validated)"
            )
            return

        self._validation_label.setText("Validating…")

        def _do_validate() -> list[str]:
            results: list[str] = []
            for k in epic_keys:
                if not RE_EPIC_KEY.match(k):
                    results.append(f"✗ {k} — invalid format")
                elif self._jira.validate_epic_key(k):
                    results.append(f"✓ {k}")
                else:
                    results.append(f"✗ {k} — not found")
            return results

        def _on_validated(result: object) -> None:
            if isinstance(result, Exception):
                self._validation_label.setText(f"Validation error: {result}")
                return
            lines: list[str] = result  # type: ignore[assignment]
            self._validation_label.setText("<br>".join(lines))

        self._run_background(_do_validate, _on_validated)

    def _detect_fields(self) -> None:
        if not self._jira.connected:
            QMessageBox.information(self, "Not Connected", "Connect to Jira first.")
            return
        logger.info("Detecting Jira custom fields")

        def _on_fields_fetched(result: object) -> None:
            if isinstance(result, Exception):
                QMessageBox.warning(self, "Error", f"Failed to fetch fields: {result}")
                return
            fields: list[dict[str, str]] = result  # type: ignore[assignment]
            method = self._estimation_combo.currentData() or "story_points"

            sp_candidates = [
                f
                for f in fields
                if "point" in f["name"].lower() or "story" in f["name"].lower()
            ]
            epic_candidates = [
                f
                for f in fields
                if "epic" in f["name"].lower() and "link" in f["name"].lower()
            ]
            start_date_candidates = [
                f
                for f in fields
                if "start" in f["name"].lower() and "date" in f["name"].lower()
            ]
            due_date_candidates = [
                f
                for f in fields
                if "due" in f["name"].lower()
                or ("end" in f["name"].lower() and "date" in f["name"].lower())
            ]
            timeline_start_candidates = [
                f
                for f in fields
                if "start" in f["name"].lower()
                and ("date" in f["name"].lower() or "target" in f["name"].lower())
            ]
            timeline_end_candidates = [
                f
                for f in fields
                if ("due" in f["name"].lower() or "target end" in f["name"].lower())
                or ("end" in f["name"].lower() and "date" in f["name"].lower())
            ]

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
            if dialog.exec() == QDialog.DialogCode.Accepted:
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

        self._run_background(self._jira.fetch_fields, _on_fields_fetched)
