"""Tests for ThreadedTask — callbacks must be delivered on the main thread.

This guards the regression that segfaulted when a result callback (opening a
QDialog) ran on the background worker thread instead of the GUI thread.
"""

from __future__ import annotations

import threading

from epic_report_generator.ui._threading import ThreadedTask


def test_result_callback_runs_on_main_thread(qtbot):
    task = ThreadedTask()
    main_tid = threading.get_ident()
    seen: dict = {}

    def work() -> int:
        return threading.get_ident()  # the worker thread's id

    def on_result(result: int) -> None:
        seen["worker_tid"] = result
        seen["callback_tid"] = threading.get_ident()

    task.start(work, on_result)
    qtbot.waitUntil(lambda: "callback_tid" in seen, timeout=3000)

    assert seen["callback_tid"] == main_tid  # callback delivered on GUI thread
    assert seen["worker_tid"] != main_tid  # work ran off the main thread
    task.wait()


def test_progress_callback_runs_on_main_thread(qtbot):
    task = ThreadedTask()
    main_tid = threading.get_ident()
    seen: dict = {"progress": []}

    def work(progress) -> str:
        progress("step", 50)
        return "done"

    def on_progress(message: str, percent: int) -> None:
        seen["progress"].append((message, percent))
        seen["progress_tid"] = threading.get_ident()

    def on_result(result: str) -> None:
        seen["result"] = result

    task.start(work, on_result, on_progress=on_progress)
    qtbot.waitUntil(lambda: "result" in seen, timeout=3000)

    assert seen["progress"] == [("step", 50)]
    assert seen["progress_tid"] == main_tid
    assert seen["result"] == "done"
    task.wait()


def test_widget_building_in_callback_does_not_deadlock(qtbot):
    """Building widgets in the result callback must not deadlock the GUI thread.

    Regression for the GIL ⇄ Qt signal-slot-mutex inversion: the worker thread
    destroying a shiboken QObject (``~QObject`` → ``PyGILState_Ensure``) while
    the main thread held the GIL and created QLabels (``QObject::connectImpl``)
    froze the whole app. Many rapid rounds, each constructing QLabels (which
    build a QWidgetTextControl and run connectImpl) in the callback, exercise the
    window where worker teardown overlaps main-thread widget creation. With the
    fix nothing is destroyed on the worker thread, so this always completes; a
    regression would hang and trip the timeout.
    """
    from PySide6.QtWidgets import QLabel

    task = ThreadedTask()
    done = {"n": 0}
    rounds = 40

    def work() -> str:
        return "<b>payload</b>"

    def on_result(result: object) -> None:
        # QLabel(text) → QWidgetTextControl ctor → QObject::connectImpl: the exact
        # main-thread side of the deadlock.
        holder = [QLabel(str(result)) for _ in range(8)]
        for lbl in holder:
            qtbot.addWidget(lbl)
        done["n"] += 1
        if done["n"] < rounds:
            task.start(work, on_result)

    task.start(work, on_result)
    qtbot.waitUntil(lambda: done["n"] >= rounds, timeout=10000)
    assert done["n"] == rounds
    task.wait()


def test_capture_exceptions_delivers_exception(qtbot):
    task = ThreadedTask()
    seen: dict = {}

    def work() -> None:
        raise ValueError("boom")

    def on_result(result: object) -> None:
        seen["result"] = result

    task.start(work, on_result, capture_exceptions=True)
    qtbot.waitUntil(lambda: "result" in seen, timeout=3000)

    assert isinstance(seen["result"], ValueError)
    task.wait()
