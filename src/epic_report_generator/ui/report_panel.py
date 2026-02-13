"""Combined Report panel — config (Step 1) + preview (Step 2) in collapsible sections."""

from __future__ import annotations

import logging

from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from epic_report_generator.core.jira_client import JiraClient
from epic_report_generator.services.config_manager import ConfigManager
from epic_report_generator.ui.config_panel import ConfigPanel
from epic_report_generator.ui.preview_panel import PreviewPanel
from epic_report_generator.ui.widgets import CollapsibleSection

logger = logging.getLogger(__name__)


class ReportPanel(QWidget):
    """Single page combining configuration and preview as collapsible steps."""

    def __init__(
        self,
        config: ConfigManager,
        jira: JiraClient,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._config_mgr = config
        self._jira = jira
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        outer.addWidget(scroll)

        content = QWidget()
        scroll.setWidget(content)
        root = QVBoxLayout(content)
        root.setContentsMargins(32, 32, 32, 32)
        root.setSpacing(16)

        # Heading
        title = QLabel("Report")
        title.setProperty("heading", "true")
        root.addWidget(title)

        # Step 1: Configuration
        self._step1 = CollapsibleSection("Step 1: Configuration", expanded=True)
        self._config_panel = ConfigPanel(self._config_mgr, self._jira)
        self._step1.body_layout.addWidget(self._config_panel)

        # Generate / Reset buttons
        btn_row = QHBoxLayout()
        self._generate_btn = QPushButton("Generate Report")
        self._generate_btn.setToolTip("Fetch data from Jira and build the PDF (Ctrl+G)")
        self._generate_btn.clicked.connect(self._on_generate)
        btn_row.addWidget(self._generate_btn)

        self._reset_btn = QPushButton("Reset")
        self._reset_btn.setProperty("secondary", "true")
        self._reset_btn.setToolTip("Clear configuration and start over")
        self._reset_btn.clicked.connect(self._on_reset)
        btn_row.addWidget(self._reset_btn)
        btn_row.addStretch()
        self._step1.body_layout.addLayout(btn_row)

        root.addWidget(self._step1)

        # Step 2: Preview & Export
        self._step2 = CollapsibleSection("Step 2: Preview & Export", expanded=False)
        self._preview_panel = PreviewPanel(self._jira)
        self._step2.body_layout.addWidget(self._preview_panel)
        root.addWidget(self._step2)

        # Bottom spacer pushes content to the top when sections are collapsed.
        # When Step 2 is expanded the spacer shrinks so the preview fills the
        # available height instead.
        self._root = root
        root.addStretch(1)
        self._step2.toggled.connect(self._on_step2_toggled)
        # Apply initial stretch state
        self._on_step2_toggled(self._step2._expanded)

    # -- public API -----------------------------------------------------------

    @property
    def config_panel(self) -> ConfigPanel:
        return self._config_panel

    @property
    def preview_panel(self) -> PreviewPanel:
        return self._preview_panel

    def trigger_generate(self) -> None:
        """Public method for keyboard shortcut (Ctrl+G)."""
        self._on_generate()

    def trigger_export(self) -> None:
        """Public method for keyboard shortcut (Ctrl+E)."""
        self._preview_panel._export_pdf()

    def set_dark(self, dark: bool) -> None:
        """Pass dark mode flag to the preview panel."""
        self._preview_panel.set_dark(dark)

    # -- slots ----------------------------------------------------------------

    def _on_step2_toggled(self, expanded: bool) -> None:
        """Swap stretch so preview fills height when open, spacer fills when closed."""
        # Step 2 is at index 2 (heading=0, step1=1, step2=2), spacer is at 3
        self._root.setStretch(2, 1 if expanded else 0)  # step2
        self._root.setStretch(3, 0 if expanded else 1)  # bottom spacer

    def _on_generate(self) -> None:
        cfg = self._config_panel.get_report_config()
        if cfg is None:
            return

        cfg.dark_mode = self._config_mgr.get("theme", "light") == "dark"
        logger.info(
            "Starting report generation: %d epic(s), dark_mode=%s",
            len(cfg.epic_keys), cfg.dark_mode,
        )

        # Collapse config, expand preview
        self._step1.set_expanded(False)
        self._step2.set_expanded(True)

        self._preview_panel.generate(cfg)

    def _on_reset(self) -> None:
        self._config_panel.reset()
        self._step1.set_expanded(True)
        self._step2.set_expanded(False)
        self._preview_panel.clear_preview()
