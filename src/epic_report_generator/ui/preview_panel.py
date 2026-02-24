"""Preview & Export panel — generate reports, preview, and save as PDF."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtGui import QPixmap, QResizeEvent
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from epic_report_generator.core.data_models import (
    EpicData,
    EpicMetrics,
    ReportConfig,
    ReportData,
    ReportItem,
)
from epic_report_generator.core.jira_client import JiraClient
from epic_report_generator.core.metrics import calculate_metrics, merge_metrics
from epic_report_generator.core.pdf_generator import generate_pdf

logger = logging.getLogger(__name__)


class _GenerateWorker(QObject):
    """Fetch Jira data and build PDF in a background thread."""

    progress = Signal(str, int)  # message, percent
    finished = Signal(object)  # ReportData | None

    def __init__(self, jira: JiraClient, config: ReportConfig) -> None:
        super().__init__()
        self._jira = jira
        self._config = config

    def run(self) -> None:
        """Execute the data fetch and PDF generation."""
        report = ReportData(config=self._config)
        items = self._config.items
        # Fall back to epic_keys if no items provided (backward compat)
        if not items and self._config.epic_keys:
            items = [ReportItem(kind="epic", key=k) for k in self._config.epic_keys]

        total = len(items) or 1
        logger.info("Worker started: fetching %d item(s)", len(items))

        project_keys: set[str] = set()

        for i, item in enumerate(items, 1):
            self.progress.emit(f"Fetching {item.key}…", int(i / total * 70))

            if item.kind == "epic":
                logger.debug("Fetching epic %d/%d: %s", i, total, item.key)
                epic = self._jira.fetch_epic(
                    item.key,
                    sp_field=self._config.story_points_field,
                    epic_link_field=self._config.epic_link_field,
                    start_date_field=self._config.start_date_field,
                    due_date_field=self._config.due_date_field,
                    include_subtasks=self._config.include_subtasks,
                )
                if epic is None:
                    logger.warning("Epic %s not found or inaccessible", item.key)
                    report.errors.append(f"Epic {item.key} not found.")
                    continue
                metrics = calculate_metrics(
                    epic,
                    estimation_method=self._config.estimation_method,
                    progress_method=self._config.progress_method,
                )
                metrics.scope_certainty = item.scope_certainty
                # Use display_name override if set
                if item.display_name:
                    epic.summary = item.display_name
                report.epics.append(epic)
                report.metrics.append(metrics)
                report.resolved_items.append((item, epic, metrics))
                # Collect project key
                if "-" in item.key:
                    project_keys.add(item.key.rsplit("-", 1)[0])

            elif item.kind == "label":
                logger.debug("Fetching epics by label %d/%d: %s", i, total, item.key)
                label_epics = self._jira.fetch_epics_by_label(
                    item.key,
                    sp_field=self._config.story_points_field,
                    epic_link_field=self._config.epic_link_field,
                    start_date_field=self._config.start_date_field,
                    due_date_field=self._config.due_date_field,
                    include_subtasks=self._config.include_subtasks,
                )
                if not label_epics:
                    report.errors.append(f"No epics found for label '{item.key}'.")
                    continue
                synthetic, metrics = merge_metrics(
                    label_epics,
                    estimation_method=self._config.estimation_method,
                    progress_method=self._config.progress_method,
                )
                metrics.scope_certainty = item.scope_certainty
                # Set display name for label group
                display = item.display_name or item.key
                synthetic.summary = display
                report.epics.append(synthetic)
                report.metrics.append(metrics)
                report.resolved_items.append((item, synthetic, metrics))
                # Store source epics with individual metrics for timeline
                source_pairs: list[tuple[EpicData, EpicMetrics]] = []
                for e in label_epics:
                    em = calculate_metrics(
                        e,
                        estimation_method=self._config.estimation_method,
                        progress_method=self._config.progress_method,
                    )
                    source_pairs.append((e, em))
                    if "-" in e.key:
                        project_keys.add(e.key.rsplit("-", 1)[0])
                report.label_source_epics[item.key] = source_pairs

        # Collect unique sprints from all children across all epics
        seen_sprints: set[str] = set()
        for epic in report.epics:
            for child in epic.children:
                for sp in child.sprints:
                    if sp.name not in seen_sprints:
                        seen_sprints.add(sp.name)
                        report.sprints.append(sp)

        # Fetch fix version dates
        self.progress.emit("Fetching fix versions…", 75)
        for pk in project_keys:
            try:
                versions = self._jira.fetch_fix_version_dates(pk)
                report.fix_version_dates.update(versions)
            except Exception as exc:
                logger.warning("Failed to fetch versions for %s: %s", pk, exc)

        if report.epics:
            self.progress.emit("Generating PDF…", 85)

        logger.info(
            "Worker finished: %d item(s) fetched, %d error(s)",
            len(report.epics),
            len(report.errors),
        )
        self.finished.emit(report)


class PreviewPanel(QWidget):
    """Panel for generating, previewing, and exporting PDF reports.

    Designed to be embedded inside ReportPanel — no heading or generate button.
    """

    def __init__(self, jira: JiraClient, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._jira = jira
        self._pdf_bytes: bytes | None = None
        self._thread: QThread | None = None
        self._worker: _GenerateWorker | None = None
        self._dark = False
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)

        # Export button row
        btn_row = QHBoxLayout()
        self._export_btn = QPushButton("Export as PDF")
        self._export_btn.setToolTip("Save the generated report to a file (Ctrl+E)")
        self._export_btn.setProperty("secondary", "true")
        self._export_btn.setEnabled(False)
        self._export_btn.clicked.connect(self._export_pdf)
        btn_row.addWidget(self._export_btn)
        btn_row.addStretch()
        root.addLayout(btn_row)

        # Progress
        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        self._progress_bar.hide()
        root.addWidget(self._progress_bar)

        self._status_label = QLabel("")
        root.addWidget(self._status_label)

        # Scrollable preview area (vertical only)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._preview_container = QWidget()
        self._preview_layout = QVBoxLayout(self._preview_container)
        self._preview_layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self._preview_layout.setContentsMargins(0, 0, 0, 0)
        self._preview_layout.setSpacing(8)
        self._scroll.setWidget(self._preview_container)
        root.addWidget(self._scroll, 1)

    # -- public API -----------------------------------------------------------

    def set_dark(self, dark: bool) -> None:
        """Update the theme flag for preview rendering."""
        self._dark = dark
        # Re-render if we already have PDF content
        if self._pdf_bytes:
            self._render_preview()

    def generate(self, config: ReportConfig) -> None:
        """Start report generation with the given config."""
        if not self._jira.connected:
            logger.warning("Generate called but Jira is not connected")
            QMessageBox.warning(self, "Not Connected", "Connect to Jira first.")
            return

        item_count = len(config.items) or len(config.epic_keys)
        logger.info("Starting report generation for %d item(s)", item_count)
        self._export_btn.setEnabled(False)
        self._progress_bar.setValue(0)
        self._progress_bar.show()
        self._clear_preview()

        self._thread = QThread()
        self._worker = _GenerateWorker(self._jira, config)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_generate_finished)
        self._worker.finished.connect(self._thread.quit)
        self._worker.finished.connect(self._cleanup_worker)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.start()

    def clear_preview(self) -> None:
        """Public method to clear the preview and reset state."""
        self._clear_preview()
        self._pdf_bytes = None
        self._export_btn.setEnabled(False)
        self._status_label.clear()
        self._progress_bar.hide()

    # -- slots ----------------------------------------------------------------

    def _cleanup_worker(self) -> None:
        """Release the worker reference after generation completes."""
        if self._worker is not None:
            self._worker.deleteLater()
            self._worker = None

    def _on_progress(self, message: str, pct: int) -> None:
        self._progress_bar.setValue(pct)
        self._status_label.setText(message)

    def _on_generate_finished(self, report: ReportData | None) -> None:
        self._progress_bar.setValue(100)

        if report is None or not report.epics:
            self._progress_bar.hide()
            logger.warning("No epics returned — nothing to generate")
            self._status_label.setText("No data to generate a report.")
            if report and report.errors:
                QMessageBox.warning(
                    self,
                    "Errors",
                    "\n".join(report.errors),
                )
            return

        if report.errors:
            QMessageBox.warning(
                self,
                "Some Epics Failed",
                "The following errors occurred:\n" + "\n".join(report.errors),
            )

        logger.info("Building PDF from %d epic(s)", len(report.epics))
        self._status_label.setText("Building PDF…")
        try:
            self._pdf_bytes = generate_pdf(report)
        except Exception as exc:
            logger.exception("PDF generation failed")
            QMessageBox.critical(self, "PDF Error", f"Failed to generate PDF: {exc}")
            self._progress_bar.hide()
            self._status_label.setText("PDF generation failed.")
            return

        self._progress_bar.hide()
        logger.info(
            "PDF generated: %d epic(s), %s bytes",
            len(report.epics),
            f"{len(self._pdf_bytes):,}",
        )
        self._status_label.setText(
            f"Report ready — {len(report.epics)} epic(s), "
            f"{len(self._pdf_bytes):,} bytes"
        )
        self._export_btn.setEnabled(True)
        self._render_preview()

    def _export_pdf(self) -> None:
        if not self._pdf_bytes:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Report", "epic_report.pdf", "PDF Files (*.pdf)"
        )
        if path:
            Path(path).write_bytes(self._pdf_bytes)
            logger.info("PDF exported to %s", path)
            self._status_label.setText(f"Exported to {path}")

    # -- preview rendering ----------------------------------------------------

    def resizeEvent(self, event: QResizeEvent) -> None:
        """Re-render preview when panel is resized so pages scale to fit."""
        super().resizeEvent(event)
        # Keep the preview area at least one 16:9 page tall
        w = self._scroll.viewport().width()
        if w > 0:
            self._scroll.setMinimumHeight(int(w * 9 / 16))
        if self._pdf_bytes:
            self._render_preview()

    def _clear_preview(self) -> None:
        while self._preview_layout.count():
            item = self._preview_layout.takeAt(0)
            if item is not None:
                w = item.widget()
                if w is not None:
                    w.deleteLater()

    def _render_preview(self) -> None:
        """Render PDF pages as QPixmap images scaled to fit the panel width."""
        self._clear_preview()
        if not self._pdf_bytes:
            return

        # Set preview container background based on theme
        if self._dark:
            self._preview_container.setStyleSheet("background: #121212;")
        else:
            self._preview_container.setStyleSheet("background: #E0E0E0;")

        try:
            from PySide6.QtCore import QBuffer, QIODevice, QSize
            from PySide6.QtPdf import QPdfDocument

            buf = QBuffer(self)
            buf.setData(self._pdf_bytes)
            buf.open(QIODevice.OpenModeFlag.ReadOnly)

            doc = QPdfDocument(self)
            doc.load(buf)

            # Available width for rendering (scroll area viewport minus small margin)
            available_width = self._scroll.viewport().width() - 16
            dpr = self.devicePixelRatio() or 1.0

            for i in range(doc.pageCount()):
                page_size = doc.pagePointSize(i)
                # Scale page to fit available width
                if page_size.width() > 0:
                    scale = available_width / page_size.width()
                else:
                    scale = 1.5
                # Ensure minimum reasonable scale and cap at 3x
                scale = max(0.5, min(scale, 3.0))
                # Render at device-pixel-ratio resolution for sharp HiDPI output
                render_size = QSize(
                    int(page_size.width() * scale * dpr),
                    int(page_size.height() * scale * dpr),
                )
                image = doc.render(i, render_size)

                pixmap = QPixmap.fromImage(image)
                pixmap.setDevicePixelRatio(dpr)

                label = QLabel()
                label.setPixmap(pixmap)
                label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                # Add subtle shadow/border around each page
                if self._dark:
                    label.setStyleSheet(
                        "border: 1px solid #333; background: transparent; padding: 2px;"
                    )
                else:
                    label.setStyleSheet(
                        "border: 1px solid #ccc; background: transparent; padding: 2px;"
                    )
                self._preview_layout.addWidget(label)

            doc.close()
            buf.close()
        except ImportError:
            # QtPdf not available — show a simple message
            lbl = QLabel(
                "PDF preview requires PySide6-QtPdf.\n"
                "Use 'Export as PDF' to view the report."
            )
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._preview_layout.addWidget(lbl)
