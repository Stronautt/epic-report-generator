"""Reusable UI animation helpers for a modern, fluid feel.

These helpers are intentionally dependency-free (PySide6 only) so they can be
shared by any widget.  The motion primitives cover the whole app:

* :class:`CollapseAnimator` — smoothly animates a body widget's height for the
  expand/collapse of :class:`~epic_report_generator.ui.widgets.CollapsibleSection`
  and :class:`~epic_report_generator.ui.widgets.GuideStep`.
* :func:`fade_in` / :func:`grow_in` — one-shot transitions for panel switches
  and freshly inserted rows.
* :func:`pulse` / :func:`stop_pulse` — a looping opacity blink that draws
  attention to a control (e.g. the sidebar "Update available" button).
* :func:`flash_highlight` / :func:`lifted_card_pixmap` — drag-and-drop feedback:
  a fading highlight when a row settles, and a lifted "card" image under the
  cursor while it is being dragged.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import (
    QEasingCurve,
    QPropertyAnimation,
    QRectF,
    Qt,
    QTimer,
    QVariantAnimation,
)
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QAbstractScrollArea, QGraphicsOpacityEffect, QWidget

# Qt's QWIDGETSIZE_MAX sentinel — restores an unbounded maximum height so a body
# can grow/shrink freely once a height animation has settled.
_WIDGET_MAX = 16777215


class CollapseAnimator:
    """Reveal a body widget with an instant height change and an opacity fade.

    The body reaches its full height in a single layout pass, so the enclosing
    scroll area never resizes frame-by-frame — which is what made a height
    *slide* flicker the page ("scrolls down and returns"). The content fades in
    (and out) instead for a smooth feel, while the scroll offset is held so the
    one-shot resize keeps the viewport steady.
    """

    def __init__(self, body: QWidget, *, duration: int = 160) -> None:
        self._body = body
        self._expanded = body.isVisible()
        self._scroll_area: QAbstractScrollArea | None = None
        self._saved_scroll: int | None = None
        # A persistent opacity effect, enabled only while a fade runs so it
        # adds no rendering cost when idle.
        self._effect = QGraphicsOpacityEffect(body)
        self._effect.setOpacity(1.0)
        self._effect.setEnabled(False)
        body.setGraphicsEffect(self._effect)
        self._anim = QPropertyAnimation(self._effect, b"opacity", body)
        self._anim.setDuration(duration)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.finished.connect(self._on_finished)

    def set_collapsed_initial(self) -> None:
        """Put the body in the collapsed state without animating (for setup)."""
        self._body.setVisible(False)
        self._expanded = False

    def animate(self, expanded: bool) -> None:
        """Reveal (``expanded``) or hide the body.

        Both directions change the body's height in a single layout pass with
        the scroll offset held steady — the flicker-free path. Expand then fades
        its content in; collapse is instant (a fade-*out* would keep the body in
        the layout and defer the shrink to the fade's end, which is exactly what
        reintroduces the collapse flicker).
        """
        self._expanded = expanded
        self._anim.stop()
        if expanded:
            self._effect.setEnabled(True)
            self._capture_scroll()
            self._effect.setOpacity(0.0)
            self._body.setVisible(True)
            self._restore_scroll()
            QTimer.singleShot(0, self._body, self._restore_scroll)
            self._anim.setStartValue(0.0)
            self._anim.setEndValue(1.0)
            self._anim.start()
        else:
            self._effect.setEnabled(False)
            self._effect.setOpacity(1.0)
            self._capture_scroll()
            self._body.setVisible(False)
            self._restore_scroll()
            QTimer.singleShot(0, self._body, self._restore_scroll)

    def _capture_scroll(self) -> None:
        """Find the enclosing scroll area, reserve its gutter, and note its offset.

        Pinning the vertical scrollbar on keeps the page width constant when the
        content crosses the scrollable↔fits boundary. Otherwise the scrollbar
        appears/disappears as the last section is expanded/collapsed, the
        viewport widens/narrows by the bar's width, and the wrapped content
        reflows — the flicker seen specifically when a collapse makes the whole
        page fit (no scrollbar left).
        """
        if self._scroll_area is None:
            sa = self._body.parentWidget()
            while sa is not None and not isinstance(sa, QAbstractScrollArea):
                sa = sa.parentWidget()
            self._scroll_area = sa
        sa = self._scroll_area
        if sa is None:
            self._saved_scroll = None
            return
        sa.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self._saved_scroll = sa.verticalScrollBar().value()

    def _restore_scroll(self) -> None:
        """Snap the offset back to the captured value if the resize moved it."""
        sa = self._scroll_area
        if sa is None or self._saved_scroll is None:
            return
        vbar = sa.verticalScrollBar()
        if vbar.value() != self._saved_scroll:
            vbar.setValue(self._saved_scroll)

    def _on_finished(self) -> None:
        # The expand fade finished (collapse is instant and never starts the
        # animation). Drop the effect to idle so the body renders at full
        # fidelity and zero cost until the next toggle.
        self._effect.setOpacity(1.0)
        self._effect.setEnabled(False)


def fade_in(widget: QWidget, *, duration: int = 180) -> QPropertyAnimation:
    """Fade *widget* from transparent to opaque, then drop the effect.

    A transient :class:`QGraphicsOpacityEffect` wraps the widget only for the
    duration of the transition; it is removed on completion so complex children
    (PDF view, scroll areas) render normally afterwards.
    """
    prev = getattr(widget, "_fade_anim", None)
    if prev is not None:
        prev.stop()

    effect = QGraphicsOpacityEffect(widget)
    widget.setGraphicsEffect(effect)

    anim = QPropertyAnimation(effect, b"opacity", widget)
    anim.setDuration(duration)
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    anim.setEasingCurve(QEasingCurve.Type.OutCubic)
    anim.finished.connect(lambda: widget.setGraphicsEffect(None))
    # Keep a reference so the animation isn't garbage-collected mid-flight.
    widget._fade_anim = anim  # type: ignore[attr-defined]
    anim.start()
    return anim


def pulse(
    widget: QWidget,
    *,
    duration: int = 850,
    min_opacity: float = 0.3,
) -> QPropertyAnimation:
    """Make *widget* blink by looping its opacity, to draw attention.

    A persistent :class:`QGraphicsOpacityEffect` fades the widget between full
    and *min_opacity* and back, forever (``setLoopCount(-1)``). The animation is
    stored on the widget so it survives garbage collection; call
    :func:`stop_pulse` to end it and restore full opacity. Calling ``pulse``
    again first stops any existing pulse, so it is idempotent.
    """
    stop_pulse(widget)

    effect = QGraphicsOpacityEffect(widget)
    widget.setGraphicsEffect(effect)

    anim = QPropertyAnimation(effect, b"opacity", widget)
    anim.setDuration(duration)
    anim.setStartValue(1.0)
    anim.setKeyValueAt(0.5, min_opacity)
    anim.setEndValue(1.0)
    anim.setEasingCurve(QEasingCurve.Type.InOutSine)
    anim.setLoopCount(-1)
    # Keep references so neither the animation nor its effect is collected.
    widget._pulse_anim = anim  # type: ignore[attr-defined]
    widget._pulse_effect = effect  # type: ignore[attr-defined]
    anim.start()
    return anim


def stop_pulse(widget: QWidget) -> None:
    """Stop a running :func:`pulse` on *widget* and restore full opacity."""
    anim = getattr(widget, "_pulse_anim", None)
    if anim is not None:
        anim.stop()
        widget._pulse_anim = None  # type: ignore[attr-defined]
    if getattr(widget, "_pulse_effect", None) is not None:
        widget.setGraphicsEffect(None)
        widget._pulse_effect = None  # type: ignore[attr-defined]


def grow_in(
    widget: QWidget,
    *,
    duration: int = 160,
    on_finished: Callable[[], None] | None = None,
) -> QPropertyAnimation | None:
    """Grow *widget* from zero to its natural height (e.g. a newly added row)."""
    target = max(widget.sizeHint().height(), 0)
    if target == 0:
        return None
    widget.setMaximumHeight(0)

    anim = QPropertyAnimation(widget, b"maximumHeight", widget)
    anim.setDuration(duration)
    anim.setEasingCurve(QEasingCurve.Type.OutCubic)
    anim.setStartValue(0)
    anim.setEndValue(target)

    def _done() -> None:
        widget.setMaximumHeight(_WIDGET_MAX)
        if on_finished is not None:
            on_finished()

    anim.finished.connect(_done)
    widget._grow_anim = anim  # type: ignore[attr-defined]
    anim.start()
    return anim


def flash_highlight(
    widget: QWidget,
    color: QColor,
    *,
    selector: str = "",
    duration: int = 480,
) -> QVariantAnimation:
    """Briefly tint *widget*'s background with *color*, fading it back out.

    Used to draw the eye to a row that has just been dropped into place. The
    tint is applied as a transient stylesheet (scoped to *selector*, e.g.
    ``"#reportItemRow"``, so it does not cascade onto child controls) and
    cleared once the fade completes.
    """
    anim = QVariantAnimation(widget)
    anim.setDuration(duration)
    start = QColor(color)
    start.setAlpha(150)
    end = QColor(color)
    end.setAlpha(0)
    anim.setStartValue(start)
    anim.setEndValue(end)
    anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    def _apply(value: QColor) -> None:
        css = (
            f"background-color: rgba({value.red()},{value.green()},"
            f"{value.blue()},{value.alpha() / 255:.3f}); border-radius: 4px;"
        )
        widget.setStyleSheet(f"{selector} {{ {css} }}" if selector else css)

    anim.valueChanged.connect(_apply)
    anim.finished.connect(lambda: widget.setStyleSheet(""))
    widget._flash_anim = anim  # type: ignore[attr-defined]
    anim.start()
    return anim


def lifted_card_pixmap(
    source: QPixmap,
    border_color: QColor,
    *,
    radius: float = 6.0,
    opacity: float = 0.92,
) -> QPixmap:
    """Return *source* re-rendered as a lifted card for a drag cursor.

    Rounds the corners, paints a thin *border_color* outline, and applies a
    slight translucency so the floating row reads as picked up off the list.
    Returns *source* unchanged if it has no paintable area.
    """
    if source.isNull() or source.width() <= 0 or source.height() <= 0:
        return source
    dpr = source.devicePixelRatio() or 1.0
    logical_w = source.width() / dpr
    logical_h = source.height() / dpr

    result = QPixmap(source.size())
    result.setDevicePixelRatio(dpr)
    result.fill(Qt.GlobalColor.transparent)

    painter = QPainter(result)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    rect = QRectF(0.75, 0.75, logical_w - 1.5, logical_h - 1.5)
    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)

    painter.setOpacity(opacity)
    painter.setClipPath(path)
    painter.drawPixmap(0, 0, source)
    painter.setClipping(False)

    painter.setOpacity(1.0)
    pen = QPen(border_color)
    pen.setWidthF(1.5)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawPath(path)
    painter.end()
    return result
