"""Reusable QThread task runner shared across UI panels.

Runs a blocking callable on a background thread and delivers its result on the
main (GUI) thread. Result and progress callbacks are always dispatched on the
main thread (the worker emits from the background thread; the receiving slots
live on :class:`ThreadedTask`, so the cross-thread ``AutoConnection`` becomes a
queued connection). Callbacks may therefore safely touch widgets.

**Why a QThread subclass instead of moveToThread(worker).** With PySide6 the
moved worker is a QObject whose *affinity is the background thread*, so Qt
destroys it there (``deleteLater``) when the task finishes. Destroying a shiboken
QObject runs Python — ``~QObject`` calls ``PyGILState_Ensure`` — while Qt holds
that object's signal-slot mutex. If the main thread is meanwhile holding the GIL
and building widgets (e.g. opening a dialog from the result callback) it blocks
acquiring a signal-slot mutex of its own (``QObject::connectImpl``). Qt hashes
objects onto a small fixed pool of signal-slot mutexes, so the two eventually
collide and the threads deadlock: main holds GIL ⇒ wants mutex, worker holds
mutex ⇒ wants GIL. The freeze is intermittent (collision is pointer-hash based)
and platform-independent (observed on Linux and macOS).

Subclassing :class:`QThread` and doing the work in ``run()`` keeps the only
QObject — the thread itself — on the **main** thread (it is created here), so it
is constructed and destroyed on the main thread and *nothing is ever destroyed
on the background thread*. That removes the GIL ⇄ signal-slot-mutex inversion at
its source. ``run()`` needs no event loop, so no child QObjects live on the
background thread either.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QThread, Signal
from shiboken6 import isValid

logger = logging.getLogger(__name__)


class _Worker(QThread):
    """Runs a callable on a background thread and emits its result.

    The user callbacks are carried *through* the signal payload so the receiving
    slots live on :class:`ThreadedTask` (main thread); connecting a bare Python
    callable directly would run it on this worker thread instead.
    """

    completed = Signal(object, object)  # (result, on_result)
    progressed = Signal(object, str, int)  # (on_progress, message, percent)

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
        """Invoke the callable on this thread and emit ``completed``.

        Runs on the background OS thread; creates no QObjects, so the thread's
        teardown destroys nothing here.
        """
        if self._capture:
            try:
                result: Any = self._call()
            except Exception as exc:  # noqa: BLE001 - surfaced to caller as result
                logger.exception("Background task failed")
                result = exc
        else:
            result = self._call()
        self.completed.emit(result, self._on_result)

    def _call(self) -> Any:
        if self._wants_progress:
            return self._fn(self._emit_progress)
        return self._fn()

    def _emit_progress(self, message: str, percent: int) -> None:
        """Forward progress through the signal so it reaches the main thread."""
        self.progressed.emit(self._on_progress, message, percent)


class ThreadedTask(QObject):
    """Owns the lifecycle of background QThread tasks for a UI component.

    A single instance can run several tasks concurrently; it keeps strong
    references to each live worker to prevent premature garbage collection and
    cleans them up automatically on completion.
    """

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._live: set[_Worker] = set()

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
        # Created on the main thread, so the worker's QObject affinity — and
        # therefore its destruction — stays on the main thread (see module docs).
        worker = _Worker(fn, on_result, on_progress, capture_exceptions)
        self._live.add(worker)

        # Connect to ThreadedTask's own (main-thread) slots so the user callbacks
        # are dispatched via a queued, cross-thread connection.
        worker.progressed.connect(self._deliver_progress)
        worker.completed.connect(self._deliver_result)
        # QThread.finished is emitted from the background thread, but this slot
        # lives on the main thread → queued → the worker's deleteLater() is
        # invoked on the main thread (its affinity), so ~_Worker runs there too.
        worker.finished.connect(self._retire)
        worker.start()

    def _retire(self) -> None:
        """Delete a finished worker on the main thread and drop its reference."""
        worker = self.sender()
        if isinstance(worker, _Worker):
            worker.deleteLater()
            self._live.discard(worker)

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
        return any(_is_running(worker) for worker in self._live)

    def wait(self) -> None:
        """Join all running tasks (use on shutdown)."""
        for worker in list(self._live):
            if _is_running(worker):
                worker.wait()


def _is_running(thread: QThread) -> bool:
    """Return True if *thread* is alive and still running.

    A finished worker awaiting its queued ``deleteLater`` can have its underlying
    C++ object destroyed while its Python wrapper lingers briefly in ``_live``;
    calling ``isRunning()`` on that dangling wrapper raises ``RuntimeError:
    Internal C++ object already deleted``. A deleted thread has by definition
    finished, so guard with ``shiboken6.isValid`` and treat it as not running.
    """
    return isValid(thread) and thread.isRunning()
