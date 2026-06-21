"""Report panel — config (Step 1) + preview (Step 2) in collapsible sections."""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from epic_report_generator.core.jira_client import JiraClient
from epic_report_generator.services.config_manager import ConfigManager
from epic_report_generator.services.font_manager import FontManager
from epic_report_generator.ui._theme import resolve_theme
from epic_report_generator.ui.config_panel import ConfigPanel
from epic_report_generator.ui.preview_panel import PreviewPanel
from epic_report_generator.ui.widgets import CollapsibleSection, make_scroll_content

logger = logging.getLogger(__name__)


class ReportPanel(QWidget):
    """Single page combining configuration and preview as collapsible steps."""

    def __init__(
        self,
        config: ConfigManager,
        jira: JiraClient,
        font_manager: FontManager,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._config_mgr = config
        self._jira = jira
        self._font_manager = font_manager
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll, root = make_scroll_content()
        # Pin the vertical scrollbar on. With AsNeeded it pops in the instant an
        # expanding section overflows the viewport, narrowing the content by the
        # bar's width and re-wrapping labels a few px taller — surfacing as a
        # small flicker at the very end of the expand animation (the height was
        # measured before the bar existed). A constant gutter keeps the content
        # width fixed so the animation lands exactly where the layout settles.
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self._scroll = scroll
        outer.addWidget(scroll)

        # Heading
        title = QLabel("Report")
        title.setProperty("heading", "true")
        root.addWidget(title)

        # Step 1: Configuration
        self._step1 = CollapsibleSection(
            "Step 1 · Configuration", expanded=True, variant="step", number=1
        )
        self._config_panel = ConfigPanel(self._config_mgr, self._jira)
        self._step1.body_layout.addWidget(self._config_panel)
        root.addWidget(self._step1)

        # Step 2: Preview & Export. The preview body fills available height
        # (stretch + an expanding scroll area), so it shows/hides instantly
        # (animate_height=False) and lets Step 1's collapse animation carry the
        # transition while the preview fills in — a height animation here would
        # land on the wrong value and jump when the clamp releases.
        self._step2 = CollapsibleSection(
            "Step 2 · Preview & Export",
            expanded=False,
            variant="step",
            number=2,
            animate_height=False,
        )
        self._preview_panel = PreviewPanel(self._jira, self._config_mgr)
        self._step2.body_layout.addWidget(self._preview_panel)
        root.addWidget(self._step2)

        # Bottom spacer pushes content to the top when sections are collapsed.
        # When Step 2 is expanded the spacer shrinks so the preview fills the
        # available height instead.
        self._root = root
        root.addStretch(1)
        self._step2.toggled.connect(self._on_step2_toggled)
        # Apply initial stretch state
        self._on_step2_toggled(self._step2.is_expanded())

        # Action bar pinned below the scroll area. Keeping Generate out of
        # Step 1's scrolling body means it never reads as part of the last
        # config section ("Jira Field Mapping") and stays reachable no matter
        # how far the user has scrolled through the config sections.
        self._action_bar = self._build_action_bar()
        outer.addWidget(self._action_bar)
        # Step 1 / Step 2 behave as an accordion: opening one collapses the
        # other (see _on_step1_toggled / _on_step2_toggled). The action bar is
        # shown only while Step 1 is expanded — collapsing Step 1 for the
        # preview hides the now-orphaned Generate button and reclaims its
        # vertical space so the preview fits without an extra scrollbar.
        self._step1.toggled.connect(self._on_step1_toggled)
        self._action_bar.setVisible(self._step1.is_expanded())

    def _build_action_bar(self) -> QWidget:
        """Build the persistent footer holding the primary Generate action.

        A motivating hint on the left nudges the user toward the filled,
        accent-coloured primary button on the right; Reset stays a quiet
        secondary action beside it.
        """
        bar = QWidget()
        bar.setObjectName("stepActionBar")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(16, 10, 16, 10)
        lay.setSpacing(12)

        hint = QLabel(
            "All set? Generate fetches your latest Jira data and builds the "
            "PDF preview."
        )
        hint.setProperty("actionHint", "true")
        hint.setWordWrap(True)
        lay.addWidget(hint, 1)

        self._reset_btn = QPushButton("Reset")
        self._reset_btn.setProperty("secondary", "true")
        self._reset_btn.setToolTip("Clear configuration and start over")
        self._reset_btn.clicked.connect(self._on_reset)
        lay.addWidget(self._reset_btn)

        self._generate_btn = QPushButton("Generate Report")
        self._generate_btn.setProperty("primary", "true")
        self._generate_btn.setToolTip("Fetch data from Jira and build the PDF (Ctrl+G)")
        self._generate_btn.clicked.connect(self._on_generate)
        lay.addWidget(self._generate_btn)
        return bar

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
        self._preview_panel.trigger_export()

    def set_dark(self, dark: bool) -> None:
        """Pass dark mode flag to the preview panel."""
        self._preview_panel.set_dark(dark)

    # -- slots ----------------------------------------------------------------

    def _on_step1_toggled(self, expanded: bool) -> None:
        """Accordion + action-bar visibility for Step 1.

        Opening Step 1 collapses Step 2 (the two sections are mutually
        exclusive); the action bar tracks Step 1's expanded state. Collapsing
        leaves Step 2 untouched, so both sections may be closed at once.
        """
        self._action_bar.setVisible(expanded)
        if expanded:
            self._step2.set_expanded(False)

    def _on_step2_toggled(self, expanded: bool) -> None:
        """Accordion + stretch handling for Step 2.

        Opening Step 2 collapses Step 1; the stretch swap lets the preview fill
        the height when open and the bottom spacer take over when closed.
        """
        if expanded:
            self._step1.set_expanded(False)
        # Step 2 is at index 2 (heading=0, step1=1, step2=2), spacer is at 3
        self._root.setStretch(2, 1 if expanded else 0)  # step2
        self._root.setStretch(3, 0 if expanded else 1)  # bottom spacer

    def _on_generate(self) -> None:
        # Validate every item against Jira first. Errors block generation and
        # send the user back to the highlighted rows; warnings are surfaced but
        # let generation proceed.
        self._generate_btn.setEnabled(False)
        # Switch straight to the preview step in a single transition: collapse
        # the configuration and expand the preview with a busy progress bar.
        # Validation runs there as the first step (it hits Jira and can take a
        # few seconds), so on the common success path nothing else moves. Only
        # validation errors send the user back to the configuration step.
        self._step1.set_expanded(False)
        self._step2.set_expanded(True)
        self._preview_panel.show_busy("Validating report items…")
        self._config_panel.validate_items(on_complete=self._on_validated_for_generate)

    def _on_validated_for_generate(self, has_errors: bool, _has_warnings: bool) -> None:
        """Continue (or abort) report generation once validation settles."""
        self._generate_btn.setEnabled(True)
        if has_errors:
            # Validation failed: drop the busy bar, collapse the (empty) preview
            # pane, and send the user back to the flagged rows in the config step.
            self._preview_panel.clear_preview()
            self._step2.set_expanded(False)
            self._step1.set_expanded(True)
            QTimer.singleShot(0, self._scroll_to_report_items)
            return

        cfg = self._config_panel.get_report_config()
        if cfg is None:
            # Nothing to generate (e.g. no items): clear the busy bar.
            self._preview_panel.clear_preview()
            return

        # The report is light by default ("Always use light theme for report" in
        # Step 1). Only when that's unticked does the app theme carry over —
        # resolving "system" to the OS scheme just like the UI does.
        force_light = self._config_mgr.get("report_force_light", True)
        app_is_dark = resolve_theme(self._config_mgr.get("theme", "system")) == "dark"
        cfg.dark_mode = app_is_dark and not force_light

        # Appearance customization (NFR-05): carry the configured accent and the
        # resolved custom font (family + provisioned dir) into the renderer.
        cfg.report_accent = self._config_mgr.get("accent_color", "")
        cfg.report_font_family, cfg.report_font_dir = (
            self._font_manager.resolve_for_report()
        )

        logger.info(
            "Starting report generation: %d epic(s), dark_mode=%s, accent=%s, font=%s",
            len(cfg.epic_keys),
            cfg.dark_mode,
            cfg.report_accent or "default",
            cfg.report_font_family or "Inter",
        )

        # Show the preview. Step 1 and Step 2 form an accordion, so opening the
        # preview collapses the configuration; any non-blocking warnings remain
        # in the Step 1 validation callout, visible when the user reopens Step 1.
        self._step2.set_expanded(True)

        self._preview_panel.generate(cfg)

    def _scroll_to_report_items(self) -> None:
        """Bring the Report Items section into view after a blocking error."""
        self._scroll.ensureWidgetVisible(self._config_panel.report_items_anchor, 0, 40)

    def _on_reset(self) -> None:
        self._config_panel.reset()
        self._step1.set_expanded(True)
        self._step2.set_expanded(False)
        self._preview_panel.clear_preview()
