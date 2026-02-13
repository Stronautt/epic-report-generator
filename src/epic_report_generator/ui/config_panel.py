"""Report configuration panel."""

from __future__ import annotations

import logging
from datetime import date

from PySide6.QtCore import QDate, Signal
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
    CollapsibleSection,
    EpicKeyTagInput,
    LabelledField,
    RE_EPIC_KEY,
)

logger = logging.getLogger(__name__)


class FieldPickerDialog(QDialog):
    """Dialog letting the user choose from detected Jira field candidates."""

    def __init__(
        self,
        sp_candidates: list[dict],
        epic_candidates: list[dict],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Select Jira Fields")
        self.setMinimumWidth(420)

        layout = QFormLayout(self)

        self._sp_combo = QComboBox()
        if sp_candidates:
            for f in sp_candidates:
                self._sp_combo.addItem(f"{f['name']}  \u2014  {f['id']}", userData=f["id"])
        else:
            self._sp_combo.addItem("(No matches found)")
            self._sp_combo.setEnabled(False)
        layout.addRow("Story Points Field:", self._sp_combo)

        self._epic_combo = QComboBox()
        if epic_candidates:
            for f in epic_candidates:
                self._epic_combo.addItem(f"{f['name']}  \u2014  {f['id']}", userData=f["id"])
        else:
            self._epic_combo.addItem("(No matches found)")
            self._epic_combo.setEnabled(False)
        layout.addRow("Epic Link Field:", self._epic_combo)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

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
        self._build_ui()
        self._restore_values()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)

        # Epic Keys — tag input
        lbl = QLabel("Epic Keys")
        lbl.setProperty("subheading", "true")
        root.addWidget(lbl)
        self._epic_tag_input = EpicKeyTagInput()
        self._epic_tag_input.setToolTip(
            "Type a Jira Epic key (e.g. PROJ-101) and press Enter to add it"
        )
        root.addWidget(self._epic_tag_input)

        btn_row = QHBoxLayout()
        validate_btn = QPushButton("Validate All")
        validate_btn.setProperty("secondary", "true")
        validate_btn.setToolTip("Check each Epic key against Jira")
        validate_btn.clicked.connect(self._validate_epics)
        btn_row.addWidget(validate_btn)
        btn_row.addStretch()
        root.addLayout(btn_row)

        self._validation_label = QLabel("")
        self._validation_label.setWordWrap(True)
        root.addWidget(self._validation_label)

        # Report Metadata (collapsible)
        self._meta_section = CollapsibleSection("Report Metadata", expanded=False)
        meta = self._meta_section.body_layout

        self._title_field = LabelledField(
            "Report Title",
            placeholder="Epic Progress Report",
            tooltip="Title shown on the first page",
        )
        meta.addWidget(self._title_field)

        self._author_field = LabelledField(
            "Author Name",
            placeholder="Your name",
            tooltip="Author name shown on title page",
        )
        meta.addWidget(self._author_field)

        self._project_name_field = LabelledField(
            "Project Display Name",
            placeholder="Will be pre-filled from Jira if available",
            tooltip="Human-readable project name",
        )
        meta.addWidget(self._project_name_field)

        date_lbl = QLabel("Report Date")
        date_lbl.setProperty("subheading", "true")
        meta.addWidget(date_lbl)
        self._date_edit = QDateEdit()
        self._date_edit.setCalendarPopup(True)
        self._date_edit.setDate(QDate.currentDate())
        self._date_edit.setToolTip("Date shown on the title page")
        meta.addWidget(self._date_edit)

        root.addWidget(self._meta_section)

        # Confidentiality Notice (collapsible)
        self._conf_section = CollapsibleSection("Confidentiality Notice", expanded=False)
        conf = self._conf_section.body_layout
        self._conf_check = QCheckBox("Include confidentiality warning")
        self._conf_check.setToolTip("Adds a notice to the title page footer")
        conf.addWidget(self._conf_check)
        self._company_field = LabelledField(
            "Company Name",
            placeholder="ACME Corp",
            tooltip="Company name used in the confidentiality notice",
        )
        conf.addWidget(self._company_field)
        root.addWidget(self._conf_section)

        # Custom Field Mapping (collapsible)
        self._fields_section = CollapsibleSection("Custom Field Mapping", expanded=False)
        fields = self._fields_section.body_layout
        self._sp_field = LabelledField(
            "Story Points Field",
            placeholder="story_points or customfield_XXXXX",
            tooltip="The Jira field ID for story points",
        )
        fields.addWidget(self._sp_field)
        self._epic_link_field = LabelledField(
            "Epic Link Field",
            placeholder="customfield_10014",
            tooltip="The Jira field ID used to link issues to Epics",
        )
        fields.addWidget(self._epic_link_field)

        detect_btn = QPushButton("Detect Fields")
        detect_btn.setProperty("secondary", "true")
        detect_btn.setToolTip("Query Jira for available fields")
        detect_btn.clicked.connect(self._detect_fields)
        fields.addWidget(detect_btn)
        root.addWidget(self._fields_section)

    # -- value persistence ----------------------------------------------------

    def _restore_values(self) -> None:
        keys = self._config.get("last_epic_keys", [])
        if keys:
            self._epic_tag_input.set_keys(keys)
        self._title_field.text = self._config.get("default_title", "Epic Progress Report")
        self._author_field.text = self._config.get("default_author", "")
        self._company_field.text = self._config.get("default_company", "")
        self._sp_field.text = self._config.get("story_points_field", "story_points")
        self._epic_link_field.text = self._config.get("epic_link_field", "customfield_10014")

    def _persist_values(self) -> None:
        self._config.update({
            "last_epic_keys": self._epic_tag_input.get_keys(),
            "story_points_field": self._sp_field.text.strip() or "story_points",
            "epic_link_field": self._epic_link_field.text.strip() or "customfield_10014",
        })

    # -- public API -----------------------------------------------------------

    def get_report_config(self) -> ReportConfig | None:
        """Build and return a ReportConfig, or None if validation fails."""
        epic_keys = self._epic_tag_input.get_keys()
        if not epic_keys:
            logger.warning("No epic keys provided")
            QMessageBox.warning(self, "No Epics", "Enter at least one Epic key.")
            return None

        invalid = [k for k in epic_keys if not RE_EPIC_KEY.match(k)]
        if invalid:
            logger.warning("Invalid epic key format: %s", ", ".join(invalid))
            QMessageBox.warning(
                self, "Invalid Epic Keys",
                f"These keys are invalid: {', '.join(invalid)}",
            )
            return None

        # Derive project key from epic key prefixes
        prefixes = {k.rsplit("-", 1)[0] for k in epic_keys}
        if len(prefixes) != 1:
            logger.warning("Mixed project prefixes: %s", prefixes)
            QMessageBox.warning(
                self, "Mixed Projects",
                "All epic keys must share the same project prefix.\n"
                f"Found: {', '.join(sorted(prefixes))}",
            )
            return None
        project_key = prefixes.pop()

        qdate = self._date_edit.date()
        report_date = date(qdate.year(), qdate.month(), qdate.day())

        # Attempt to pre-fill project name from Jira
        project_name = self._project_name_field.text.strip()
        if not project_name and self._jira.connected:
            project_name = self._jira.get_project_name(project_key) or project_key

        cfg = ReportConfig(
            project_key=project_key,
            epic_keys=epic_keys,
            title=self._title_field.text.strip() or "Epic Progress Report",
            author=self._author_field.text.strip(),
            project_display_name=project_name or project_key,
            report_date=report_date,
            confidential=self._conf_check.isChecked(),
            company_name=self._company_field.text.strip(),
            story_points_field=self._sp_field.text.strip() or "story_points",
            epic_link_field=self._epic_link_field.text.strip() or "customfield_10014",
        )

        self._persist_values()
        logger.info("Report config built: project=%s, epics=%s", project_key, epic_keys)
        return cfg

    def reset(self) -> None:
        """Clear all fields back to defaults."""
        self._epic_tag_input.clear()
        self._title_field.text = self._config.get("default_title", "Epic Progress Report")
        self._author_field.text = self._config.get("default_author", "")
        self._project_name_field.text = ""
        self._date_edit.setDate(QDate.currentDate())
        self._conf_check.setChecked(False)
        self._company_field.text = self._config.get("default_company", "")
        self._sp_field.text = self._config.get("story_points_field", "story_points")
        self._epic_link_field.text = self._config.get("epic_link_field", "customfield_10014")
        self._validation_label.clear()
        # Collapse optional sections
        self._meta_section.set_expanded(False)
        self._conf_section.set_expanded(False)
        self._fields_section.set_expanded(False)

    # -- helpers --------------------------------------------------------------

    def _validate_epics(self) -> None:
        if not self._jira.connected:
            QMessageBox.information(self, "Not Connected", "Connect to Jira first.")
            return
        keys = self._epic_tag_input.get_keys()
        logger.info("Validating %d epic key(s) against Jira", len(keys))
        results: list[str] = []
        for k in keys:
            if not RE_EPIC_KEY.match(k):
                results.append(f"\u2717 {k} \u2014 invalid format")
            elif self._jira.validate_epic_key(k):
                results.append(f"\u2713 {k}")
            else:
                results.append(f"\u2717 {k} \u2014 not found")
        self._validation_label.setText("<br>".join(results))

    def _detect_fields(self) -> None:
        if not self._jira.connected:
            QMessageBox.information(self, "Not Connected", "Connect to Jira first.")
            return
        logger.info("Detecting Jira custom fields")
        fields = self._jira.fetch_fields()
        sp_candidates = [
            f for f in fields if "point" in f["name"].lower() or "story" in f["name"].lower()
        ]
        epic_candidates = [
            f for f in fields if "epic" in f["name"].lower() and "link" in f["name"].lower()
        ]

        if not sp_candidates and not epic_candidates:
            QMessageBox.information(
                self, "No Fields Detected",
                "No matching Story Points or Epic Link fields were found.\n"
                "You may need to set them manually.",
            )
            return

        dialog = FieldPickerDialog(sp_candidates, epic_candidates, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            sp_id = dialog.selected_sp_field
            if sp_id:
                self._sp_field.text = sp_id
            epic_id = dialog.selected_epic_field
            if epic_id:
                self._epic_link_field.text = epic_id
            logger.info("Fields applied: sp=%s, epic_link=%s", sp_id, epic_id)
