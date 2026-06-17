"""Reusable QThread task runner shared across UI panels.

Encapsulates the worker/thread lifecycle (creation, signal wiring, cleanup)
that was previously duplicated in every panel running a blocking operation.

Result and progress callbacks are always delivered on the **main (GUI) thread**:
the worker emits its signals from the background thread, but they are connected
to bound slots of the main-thread :class:`ThreadedTask`, so the cross-thread
``AutoConnection`` becomes a queued connection. Callbacks may therefore safely
touch widgets (update labels, open dialogs, etc.).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QThread, Signal

logger = logging.getLogger(__name__)


class _Worker(QObject):
    """Runs a callable in a background thread and emits its result.

    The user callbacks are carried *through* the signal payload so the
    receiving slots live on :class:`ThreadedTask` (main thread); connecting a
    bare Python callable directly would run it on this worker thread instead.
    """

    finished = Signal(object, object)  # (result, on_result)
    progress = Signal(object, str, int)  # (on_progress, message, percent)

    def __init__(
        self,
        fn: Callable[..., Any],
        on_result: Callable[[Any], None],
        on_progress: Callable[[str, int], None] | None,
        capture_exceptions: bool,
    ) -> None:
        super().__init__()
        self._fn = fn
        self._on_result = on_result
        self._on_progress = on_progress
        self._capture = capture_exceptions
        self._wants_progress = on_progress is not None

    def run(self) -> None:
        """Invoke the callable and emit ``finished`` with its return value."""
        if self._capture:
            try:
                result: Any = self._call()
            except Exception as exc:  # noqa: BLE001 - surfaced to caller as result
                logger.exception("Background task failed")
                result = exc
        else:
            result = self._call()
        self.finished.emit(result, self._on_result)

    def _call(self) -> Any:
        if self._wants_progress:
            return self._fn(self._emit_progress)
        return self._fn()

    def _emit_progress(self, message: str, percent: int) -> None:
        """Forward progress through the signal so it reaches the main thread."""
        self.progress.emit(self._on_progress, message, percent)


class ThreadedTask(QObject):
    """Owns the lifecycle of background QThread tasks for a UI component.

    A single instance can run several tasks concurrently; it keeps strong
    references to each live ``(QThread, _Worker)`` pair to prevent premature
    garbage collection and cleans them up automatically on completion.
    """

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._live: set[tuple[QThread, _Worker]] = set()

    def start(
        self,
        fn: Callable[..., Any],
        on_result: Callable[[Any], None],
        *,
        on_progress: Callable[[str, int], None] | None = None,
        capture_exceptions: bool = False,
    ) -> None:
        """Run *fn* in a background thread, delivering its result to *on_result*.

        When *on_progress* is given, *fn* is called with a single
        ``progress(message, percent)`` callable it can invoke to report
        progress. When *capture_exceptions* is True, an exception raised by
        *fn* is delivered to *on_result* as the result instead of crashing
        the thread.

        Both *on_result* and *on_progress* run on the main (GUI) thread.
        """
        thread = QThread()
        worker = _Worker(fn, on_result, on_progress, capture_exceptions)
        worker.moveToThread(thread)
        pair = (thread, worker)
        self._live.add(pair)

        thread.started.connect(worker.run)
        # Connect to ThreadedTask's own (main-thread) slots so the user
        # callbacks are dispatched via a queued, cross-thread connection.
        worker.progress.connect(self._deliver_progress)
        worker.finished.connect(self._deliver_result)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda: self._live.discard(pair))
        thread.start()

    def _deliver_result(self, result: Any, on_result: Callable[[Any], None]) -> None:
        """Invoke a finished callback on the main thread."""
        on_result(result)

    def _deliver_progress(
        self, on_progress: Callable[[str, int], None], message: str, percent: int
    ) -> None:
        """Invoke a progress callback on the main thread."""
        on_progress(message, percent)

    @property
    def is_busy(self) -> bool:
        """Return True while any started task is still running."""
        return any(thread.isRunning() for thread, _ in self._live)

    def wait(self) -> None:
        """Quit and join all running tasks (use on shutdown)."""
        for thread, _ in list(self._live):
            if thread.isRunning():
                thread.quit()
                thread.wait()
