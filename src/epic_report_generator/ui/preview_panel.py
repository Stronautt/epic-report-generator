"""Preview & Export panel — generate reports, preview, and save as PDF."""

from __future__ import annotations

import copy
import logging
import re
from collections import OrderedDict
from collections.abc import Callable
from pathlib import Path

from platformdirs import user_downloads_dir
from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt, QTimer
from PySide6.QtGui import QPixmap, QResizeEvent
from PySide6.QtWidgets import (
    QFileDialog,
    QGraphicsOpacityEffect,
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
    MONTHS_ABBR,
    EpicData,
    EpicMetrics,
    ReportConfig,
    ReportData,
    ReportItem,
    average_certainty,
)
from epic_report_generator.core.jira_client import JiraClient
from epic_report_generator.core.metrics import calculate_metrics, merge_metrics
from epic_report_generator.core.pdf_generator import generate_pdf
from epic_report_generator.services.config_manager import ConfigManager
from epic_report_generator.ui._threading import ThreadedTask

logger = logging.getLogger(__name__)

# 16:9 landscape aspect ratio (height / width)
_PAGE_ASPECT_RATIO = 9 / 16

_PREVIEW_BG_DARK = "#121212"
_PREVIEW_BG_LIGHT = "#E0E0E0"
_PREVIEW_BORDER_DARK = "#333"
_PREVIEW_BORDER_LIGHT = "#ccc"

# Maximum number of viewport-width entries to keep in the pixmap cache.
# Prevents memory bloat when resizing, while avoiding re-renders on
# common back-and-forth resize patterns.
_PIXMAP_CACHE_MAX_ENTRIES = 2


def _project_prefix(key: str) -> str | None:
    """Return the Jira project prefix (text before the last '-'), or None."""
    return key.rsplit("-", 1)[0] if "-" in key else None


def _generate_report(
    jira: JiraClient,
    config: ReportConfig,
    report_progress: Callable[[str, int], None],
) -> tuple[bytes | None, list[str], int]:
    """Fetch Jira data and build the PDF (runs in a background thread).

    Returns ``(pdf_bytes | None, errors, epic_count)``.
    """
    report = ReportData(config=config)
    items = config.items
    # Fall back to epic_keys if no items provided (backward compat)
    if not items and config.epic_keys:
        items = [ReportItem(kind="epic", key=k) for k in config.epic_keys]

    total = len(items) or 1
    logger.info("Worker started: fetching %d item(s)", len(items))

    project_keys: set[str] = set()

    # Pass 1 — resolve every epic the report needs.
    report_progress("Fetching Jira data…", 10)
    epic_item_keys = [it.key for it in items if it.kind == "epic"]
    label_names = [it.key for it in items if it.kind == "label"]
    try:
        epics_by_key, label_to_keys = jira.fetch_report_epics(
            epic_item_keys,
            label_names,
            sp_field=config.story_points_field,
            epic_link_field=config.epic_link_field,
            start_date_field=config.start_date_field,
            due_date_field=config.due_date_field,
            include_subtasks=config.include_subtasks,
            include_subtasks_in_timeline=config.include_subtasks_in_timeline,
            timeline_start_field=config.timeline_start_field,
            timeline_end_field=config.timeline_end_field,
        )
    except Exception as exc:  # noqa: BLE001 - surfaced to the user as an error
        logger.exception("Jira fetch failed in worker")
        report.errors.append(f"Failed to fetch Jira data: {exc}")
        epics_by_key, label_to_keys = {}, {}

    # Pass 2 — build per-item metrics/overrides from the fetched data.  Each
    # EpicData is deep-copied before mutation because dedup means one instance
    # may back several items (e.g. an epic that is also a label member).
    for i, item in enumerate(items, 1):
        report_progress(f"Processing {item.key}…", 10 + int(i / total * 60))

        if item.kind == "epic":
            epic = epics_by_key.get(item.key)
            if epic is None:
                logger.warning("Epic %s not found or inaccessible", item.key)
                report.errors.append(f"Epic {item.key} not found.")
                continue
            epic = copy.deepcopy(epic)
            metrics = calculate_metrics(
                epic,
                estimation_method=config.estimation_method,
                progress_method=config.progress_method,
            )
            # Per-child (story/task) display-name overrides — visible on the
            # timeline when child bars are shown.
            for child in epic.children:
                ov = item.child_overrides.get(child.key)
                if ov and ov.display_name:
                    child.summary = ov.display_name
            # Scope certainty: explicit parent value wins; otherwise consolidate
            # the per-child overrides into an average (FR-13).
            if item.scope_certainty:
                metrics.scope_certainty = item.scope_certainty
            else:
                metrics.scope_certainty = average_certainty(
                    [
                        ov.scope_certainty
                        for c in epic.children
                        if (ov := item.child_overrides.get(c.key)) is not None
                    ]
                )
            # Use display_name override if set
            if item.display_name:
                epic.summary = item.display_name
            report.epics.append(epic)
            report.metrics.append(metrics)
            report.resolved_items.append((item, epic, metrics))
            # Collect project key
            if (prefix := _project_prefix(item.key)) is not None:
                project_keys.add(prefix)

        elif item.kind == "label":
            keys = label_to_keys.get(item.key, [])
            label_epics = [
                copy.deepcopy(epics_by_key[k]) for k in keys if k in epics_by_key
            ]
            if not label_epics:
                report.errors.append(f"No epics found for label '{item.key}'.")
                continue
            # Collect per-epic metrics during merge to avoid recomputing
            per_epic_metrics: list[EpicMetrics] = []
            synthetic, metrics = merge_metrics(
                label_epics,
                estimation_method=config.estimation_method,
                progress_method=config.progress_method,
                include_subtask_timeline=config.include_subtasks_in_timeline,
                source_metrics_out=per_epic_metrics,
            )
            # Set display name for label group
            display = item.display_name or item.key
            synthetic.summary = display
            report.epics.append(synthetic)
            report.metrics.append(metrics)
            report.resolved_items.append((item, synthetic, metrics))
            # Store source epics with pre-computed metrics for timeline.
            # Per-epic overrides apply only in consolidated mode (parent "--");
            # an explicit parent certainty wins for every child epic (FR-13).
            source_pairs: list[tuple[EpicData, EpicMetrics]] = []
            for e, em in zip(label_epics, per_epic_metrics):
                ov = item.child_overrides.get(e.key)
                if ov and ov.display_name:
                    e.summary = ov.display_name
                if item.scope_certainty:
                    em.scope_certainty = item.scope_certainty
                else:
                    em.scope_certainty = ov.scope_certainty if ov else None
                source_pairs.append((e, em))
                if (prefix := _project_prefix(e.key)) is not None:
                    project_keys.add(prefix)
            report.label_source_epics[item.key] = source_pairs
            # Group certainty: explicit parent value, else average of children.
            if item.scope_certainty:
                metrics.scope_certainty = item.scope_certainty
            else:
                metrics.scope_certainty = average_certainty(
                    [em.scope_certainty for _, em in source_pairs]
                )

    # Collect unique sprints from all children across all epics
    seen_sprints: set[str] = set()
    for epic in report.epics:
        for child in epic.children:
            for sp in child.sprints:
                if sp.name not in seen_sprints:
                    seen_sprints.add(sp.name)
                    report.sprints.append(sp)

    # Auto-fill project display name when it wasn't derivable at config
    # time (e.g. label-only reports where no epic keys are configured).
    if config.project_display_name in ("Report", "") and project_keys:
        pk_first = sorted(project_keys)[0]
        resolved = jira.get_project_name(pk_first)
        config.project_display_name = resolved or pk_first
        logger.debug(
            "Auto-filled project_display_name from fetched data: %s",
            config.project_display_name,
        )

    # Fetch fix version dates
    report_progress("Fetching fix versions…", 75)
    for pk in project_keys:
        try:
            versions = jira.fetch_fix_version_dates(pk)
            report.fix_version_dates.update(versions)
        except Exception as exc:  # noqa: BLE001 - non-fatal, continue with others
            logger.warning("Failed to fetch versions for %s: %s", pk, exc)

    # Generate PDF in the worker thread (off UI thread)
    pdf_bytes: bytes | None = None
    if report.epics:
        report_progress("Generating PDF…", 85)
        try:
            pdf_bytes = generate_pdf(report)
        except Exception as exc:  # noqa: BLE001 - surfaced to the user as an error
            logger.exception("PDF generation failed in worker")
            report.errors.append(f"PDF generation failed: {exc}")

    logger.info(
        "Worker finished: %d item(s) fetched, %d error(s)",
        len(report.epics),
        len(report.errors),
    )
    return pdf_bytes, report.errors, len(report.epics)


class PreviewPanel(QWidget):
    """Panel for generating, previewing, and exporting PDF reports.

    Designed to be embedded inside ReportPanel — no heading or generate button.
    """

    def __init__(
        self,
        jira: JiraClient,
        config_mgr: ConfigManager,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._jira = jira
        self._config_mgr = config_mgr
        self._pdf_bytes: bytes | None = None
        self._config: ReportConfig | None = None
        self._tasks = ThreadedTask(self)
        self._dark = False
        # LRU pixmap cache: (pdf_id, width, dpr) -> list[QPixmap]
        self._pixmap_cache: OrderedDict[tuple[int, int, float], list[QPixmap]] = (
            OrderedDict()
        )
        # Parsed PDF document (+ its backing buffer) reused across resize
        # re-renders, keyed by the bytes' identity, so changing only the scale
        # doesn't re-parse the whole PDF each time.
        self._pdf_doc: object | None = None
        self._pdf_buf: object | None = None
        self._pdf_doc_id: int | None = None
        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(150)
        self._resize_timer.timeout.connect(self._on_resize_debounced)
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
        self._apply_preview_bg()
        root.addWidget(self._scroll, 1)

        # Fade-in for freshly generated previews — masks the abrupt flicker
        # when pages first appear. The effect stays disabled (so it adds no
        # rendering cost during normal scrolling / resize re-renders) and is
        # only enabled for the duration of the animation.
        self._fade_effect = QGraphicsOpacityEffect(self._preview_container)
        self._fade_effect.setEnabled(False)
        self._preview_container.setGraphicsEffect(self._fade_effect)
        self._fade_anim = QPropertyAnimation(self._fade_effect, b"opacity", self)
        self._fade_anim.setDuration(280)
        self._fade_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._fade_anim.finished.connect(lambda: self._fade_effect.setEnabled(False))

    def _apply_preview_bg(self) -> None:
        """Set the preview container background for the current theme."""
        bg = _PREVIEW_BG_DARK if self._dark else _PREVIEW_BG_LIGHT
        self._preview_container.setStyleSheet(f"background: {bg};")

    # -- public API -----------------------------------------------------------

    def shutdown(self) -> None:
        """Wait for the generation thread to finish before closing."""
        self._tasks.wait()
        self._dispose_pdf_doc()

    def show_busy(self, message: str) -> None:
        """Show an indeterminate progress bar with *message*.

        Surfaces a pre-generation step — currently report-item validation —
        before the generation worker starts reporting its own determinate
        progress. The marquee (range 0–0) makes clear that work is happening
        even though no percentage is available yet.
        """
        self.clear_preview()
        self._progress_bar.setRange(0, 0)
        self._progress_bar.show()
        self._status_label.setText(message)

    def trigger_export(self) -> None:
        """Public entry point to export the generated PDF (used by ReportPanel)."""
        self._export_pdf()

    def set_dark(self, dark: bool) -> None:
        """Update the theme flag for preview rendering."""
        self._dark = dark
        self._apply_preview_bg()
        # Re-render if we already have PDF content
        if self._pdf_bytes:
            self._render_preview()

    def generate(self, config: ReportConfig) -> None:
        """Start report generation with the given config."""
        if not self._jira.connected:
            logger.warning("Generate called but Jira is not connected")
            QMessageBox.warning(self, "Not Connected", "Connect to Jira first.")
            return

        if self._tasks.is_busy:
            logger.warning("Generate called while a previous run is still active")
            return

        # Work on a private copy: the worker thread mutates fields on the config
        # (e.g. project_display_name auto-fill) while the caller still holds the
        # original — the copy avoids a cross-thread data race and is what the UI
        # keeps for the export filename.
        config = copy.deepcopy(config)

        item_count = len(config.items) or len(config.epic_keys)
        self._config = config
        logger.info("Starting report generation for %d item(s)", item_count)
        self.clear_preview()
        # Reset to determinate mode in case a busy (validation) bar was showing.
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        self._progress_bar.show()

        self._tasks.start(
            lambda report_progress: _generate_report(
                self._jira, config, report_progress
            ),
            self._on_generate_finished,
            on_progress=self._on_progress,
            capture_exceptions=True,
        )

    def clear_preview(self) -> None:
        """Public method to clear the preview and reset state."""
        self._clear_preview()
        self._pdf_bytes = None
        self._pixmap_cache.clear()
        self._dispose_pdf_doc()
        self._export_btn.setEnabled(False)
        self._status_label.clear()
        self._progress_bar.hide()

    # -- slots ----------------------------------------------------------------

    def _on_progress(self, message: str, pct: int) -> None:
        self._progress_bar.setValue(pct)
        self._status_label.setText(message)

    def _on_generate_finished(
        self,
        result: tuple[bytes | None, list[str], int] | Exception,
    ) -> None:
        if isinstance(result, Exception):
            logger.error("Report generation failed", exc_info=result)
            self._progress_bar.hide()
            self._status_label.setText("Report generation failed.")
            QMessageBox.critical(self, "Generation Failed", str(result))
            return

        pdf_bytes, errors, epic_count = result
        self._progress_bar.setValue(100)

        if epic_count == 0:
            self._progress_bar.hide()
            logger.warning("No epics returned — nothing to generate")
            self._status_label.setText("No data to generate a report.")
            if errors:
                QMessageBox.warning(
                    self,
                    "Errors",
                    "\n".join(errors),
                )
            return

        # Show non-fatal errors (e.g. some epics failed)
        pdf_errors = [e for e in errors if e.startswith("PDF generation failed")]
        fetch_errors = [e for e in errors if e not in pdf_errors]
        if fetch_errors:
            QMessageBox.warning(
                self,
                "Some Epics Failed",
                "The following errors occurred:\n" + "\n".join(fetch_errors),
            )

        if pdf_bytes is None:
            self._progress_bar.hide()
            logger.error("PDF generation failed in worker")
            msg = pdf_errors[0] if pdf_errors else "PDF generation failed."
            QMessageBox.critical(self, "PDF Error", msg)
            self._status_label.setText("PDF generation failed.")
            return

        self._pdf_bytes = pdf_bytes
        self._pixmap_cache.clear()
        self._dispose_pdf_doc()  # force a fresh parse for the new document
        self._progress_bar.hide()
        logger.info(
            "PDF generated: %d epic(s), %d bytes",
            epic_count,
            len(self._pdf_bytes),
        )
        self._status_label.setText(
            f"Report ready — {epic_count} epic(s), " f"{len(self._pdf_bytes):,} bytes"
        )
        self._export_btn.setEnabled(True)
        # Start the fade from fully transparent *before* rendering so the pages
        # never flash at full opacity for a frame, then animate up to opaque.
        self._fade_effect.setEnabled(True)
        self._fade_effect.setOpacity(0.0)
        self._render_preview()
        self._start_fade_in()

    def _start_fade_in(self) -> None:
        """Animate the freshly rendered preview from transparent to opaque."""
        self._fade_anim.stop()
        self._fade_anim.setStartValue(0.0)
        self._fade_anim.setEndValue(1.0)
        self._fade_anim.start()

    def _export_pdf(self) -> None:
        if not self._pdf_bytes:
            return
        default_name = "epic_report.pdf"
        if self._config is not None:
            # Strip non-alphanumeric chars (keep hyphens), collapse runs of hyphens
            title_slug = re.sub(r"[^\w-]", "-", self._config.title.strip())
            title_slug = re.sub(r"-{2,}", "-", title_slug).strip("-") or "epic-report"
            rd = self._config.report_date
            date_str = f"{rd.day}-{MONTHS_ABBR[rd.month - 1]}-{rd.strftime('%y')}"
            default_name = f"{title_slug}-{date_str}.pdf"
        initial = str(self._initial_export_dir() / default_name)
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Report", initial, "PDF Files (*.pdf)"
        )
        if path:
            Path(path).write_bytes(self._pdf_bytes)
            self._config_mgr.set("last_export_dir", str(Path(path).parent))
            logger.info("PDF exported to %s", path)
            self._status_label.setText(f"Exported to {path}")

    def _initial_export_dir(self) -> Path:
        """Resolve the directory to open the export dialog in.

        Prefers the directory of the user's last export (persisted across
        sessions). Falls back to the cross-platform Downloads folder when no
        directory has been saved yet or the saved one no longer exists, and
        finally to the home directory if Downloads is unavailable.
        """
        saved = self._config_mgr.get("last_export_dir", "")
        if saved and Path(saved).is_dir():
            return Path(saved)
        downloads = Path(user_downloads_dir())
        if downloads.is_dir():
            return downloads
        return Path.home()

    # -- preview rendering ----------------------------------------------------

    def resizeEvent(self, event: QResizeEvent) -> None:
        """Re-render preview when panel is resized so pages scale to fit.

        Debounced via a 150ms timer so rapid resize events don't trigger
        expensive re-renders on every frame.
        """
        super().resizeEvent(event)
        # Keep the preview area at least one 16:9 page tall
        w = self._scroll.viewport().width()
        if w > 0:
            self._scroll.setMinimumHeight(int(w * _PAGE_ASPECT_RATIO))
        if self._pdf_bytes:
            self._resize_timer.start()

    def _on_resize_debounced(self) -> None:
        """Called after the resize debounce timer fires."""
        if self._pdf_bytes:
            self._render_preview()

    def _clear_preview(self) -> None:
        # Remove from the end so QLayout doesn't re-index the remaining items
        # on every take (front removal is O(n²)).
        while self._preview_layout.count():
            item = self._preview_layout.takeAt(self._preview_layout.count() - 1)
            if item is not None:
                w = item.widget()
                if w is not None:
                    w.deleteLater()

    def _ensure_pdf_doc(self) -> object | None:
        """Return a parsed ``QPdfDocument`` for the current bytes, reused on resize.

        The document (and the buffer it reads from) is kept alive and re-parsed
        only when the underlying bytes change. Returns ``None`` when
        PySide6-QtPdf is unavailable.
        """
        if not self._pdf_bytes:
            return None
        pdf_id = id(self._pdf_bytes)
        if self._pdf_doc is not None and self._pdf_doc_id == pdf_id:
            return self._pdf_doc
        try:
            from PySide6.QtCore import QBuffer, QIODevice
            from PySide6.QtPdf import QPdfDocument
        except ImportError:
            return None

        self._dispose_pdf_doc()
        buf = QBuffer(self)
        buf.setData(self._pdf_bytes)
        buf.open(QIODevice.OpenModeFlag.ReadOnly)
        doc = QPdfDocument(self)
        doc.load(buf)
        # Keep the backing buffer alive — QPdfDocument reads from it lazily.
        self._pdf_doc = doc
        self._pdf_buf = buf
        self._pdf_doc_id = pdf_id
        return doc

    def _dispose_pdf_doc(self) -> None:
        """Release the cached PDF document and its backing buffer."""
        if self._pdf_doc is not None:
            self._pdf_doc.close()
            self._pdf_doc = None
        if self._pdf_buf is not None:
            self._pdf_buf.close()
            self._pdf_buf = None
        self._pdf_doc_id = None

    def _render_preview(self) -> None:
        """Render PDF pages as QPixmap images scaled to fit the panel width.

        Caches rendered pixmaps keyed by (pdf_id, available_width, dpr).
        On cache hit, reuses existing QLabels without re-rendering.
        """
        if not self._pdf_bytes:
            self._clear_preview()
            return

        available_width = self._scroll.viewport().width() - 16
        dpr = self.devicePixelRatio() or 1.0
        pdf_id = id(self._pdf_bytes)
        cache_key = (pdf_id, available_width, dpr)

        # Check LRU pixmap cache
        cached_pixmaps: list[QPixmap] | None = self._pixmap_cache.get(cache_key)
        if cached_pixmaps is not None:
            # Move to end (most recently used)
            self._pixmap_cache.move_to_end(cache_key)
        else:
            # Render from the (reused) parsed PDF document.
            from PySide6.QtCore import QSize

            doc = self._ensure_pdf_doc()
            if doc is None:
                self._clear_preview()
                lbl = QLabel(
                    "PDF preview requires PySide6-QtPdf.\n"
                    "Use 'Export as PDF' to view the report."
                )
                lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                self._preview_layout.addWidget(lbl)
                return

            cached_pixmaps = []
            for i in range(doc.pageCount()):
                page_size = doc.pagePointSize(i)
                if page_size.width() > 0:
                    scale = available_width / page_size.width()
                else:
                    scale = 1.5
                scale = max(0.5, min(scale, 3.0))
                render_size = QSize(
                    int(page_size.width() * scale * dpr),
                    int(page_size.height() * scale * dpr),
                )
                image = doc.render(i, render_size)
                pixmap = QPixmap.fromImage(image)
                pixmap.setDevicePixelRatio(dpr)
                cached_pixmaps.append(pixmap)

            # Store in LRU cache, evict oldest if at capacity
            self._pixmap_cache[cache_key] = cached_pixmaps
            while len(self._pixmap_cache) > _PIXMAP_CACHE_MAX_ENTRIES:
                self._pixmap_cache.popitem(last=False)

        self._show_pixmaps(cached_pixmaps)

    def _show_pixmaps(self, pixmaps: list[QPixmap]) -> None:
        """Display *pixmaps*, reusing existing QLabels when the count matches."""
        border_color = _PREVIEW_BORDER_DARK if self._dark else _PREVIEW_BORDER_LIGHT
        border_style = (
            f"border: 1px solid {border_color}; background: transparent; padding: 2px;"
        )
        # Reuse labels when the page count is unchanged; rebuild otherwise.
        if self._preview_layout.count() != len(pixmaps):
            self._clear_preview()
            for _ in pixmaps:
                label = QLabel()
                label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                self._preview_layout.addWidget(label)
        for i, pixmap in enumerate(pixmaps):
            label = self._preview_layout.itemAt(i).widget()
            if label is None:
                continue
            label.setPixmap(pixmap)
            label.setStyleSheet(border_style)
