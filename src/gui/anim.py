"""Kısa ve sade arayüz animasyonları (150-250 ms): bilgi/duyuru satırlarının kayarak açılıp kapanması, toast'un
belirip kaybolması.

Windows'ta "Windows'ta animasyonları göster" kapalıysa (smooth_progress._system_animations_enabled) ya da pencere
ekranda değilse her şey anında olur. Animasyon bitince geçici efekt/sınır kaldırılır: widget eski hâline döner.
"""

from __future__ import annotations

from typing import Callable

from PyQt6.QtCore import QAbstractAnimation, QEasingCurve, QParallelAnimationGroup, QPropertyAnimation
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import QGraphicsOpacityEffect, QWidget

from .smooth_progress import _system_animations_enabled

DURATION_MS = 200
_QWIDGETSIZE_MAX = 16777215
_RUNNING = "_mc_anim"  # widget üzerinde süren animasyon (aynı widget'ta ikincisi başlarken eskisi durdurulur)


def animations_enabled() -> bool:
    """Windows'un "animasyonları göster" ayarı; ekransız Qt platformlarında (offscreen/minimal) hiç animasyon yok."""
    if QGuiApplication.platformName() in ("offscreen", "minimal"):
        return False
    return _system_animations_enabled()


def _can_animate(widget: QWidget) -> bool:
    try:
        window = widget.window()
        return bool(window is not None and window.isVisible() and animations_enabled())
    except RuntimeError:
        return False


def _stop(widget: QWidget) -> None:
    running = getattr(widget, _RUNNING, None)
    if running is not None:
        setattr(widget, _RUNNING, None)
        running.stop()


def _opacity_effect(widget: QWidget, start: float) -> QGraphicsOpacityEffect:
    effect = QGraphicsOpacityEffect(widget)
    effect.setOpacity(start)
    widget.setGraphicsEffect(effect)
    return effect


def is_animating(widget: QWidget) -> bool:
    running = getattr(widget, _RUNNING, None)
    return running is not None and running.state() == QAbstractAnimation.State.Running


def finish(widget: QWidget) -> None:
    """Süren animasyonu hemen son hâline getirir (testler ve kapanış için)."""
    running = getattr(widget, _RUNNING, None)
    if running is not None and running.state() == QAbstractAnimation.State.Running:
        running.setCurrentTime(running.totalDuration())


def _run(widget: QWidget, group: QParallelAnimationGroup, done: Callable[[], None]) -> None:
    def finished() -> None:
        if getattr(widget, _RUNNING, None) is group:
            setattr(widget, _RUNNING, None)
        done()

    group.finished.connect(finished)
    setattr(widget, _RUNNING, group)
    group.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)


def slide_in(widget: QWidget, duration: int = DURATION_MS) -> None:
    """Gizli satırı yüksekliği 0'dan doğal boyuna açarak (ve belirerek) gösterir."""
    _stop(widget)
    if not _can_animate(widget):
        widget.setGraphicsEffect(None)
        widget.setMaximumHeight(_QWIDGETSIZE_MAX)
        widget.show()
        return
    widget.setMaximumHeight(0)
    widget.show()
    target = max(1, widget.sizeHint().height())
    if widget.hasHeightForWidth() and widget.width() > 0:
        target = max(target, widget.heightForWidth(widget.width()))
    effect = _opacity_effect(widget, 0.0)
    group = QParallelAnimationGroup(widget)
    height = QPropertyAnimation(widget, b"maximumHeight", group)
    height.setDuration(duration)
    height.setStartValue(0)
    height.setEndValue(target)
    height.setEasingCurve(QEasingCurve.Type.OutCubic)
    fade = QPropertyAnimation(effect, b"opacity", group)
    fade.setDuration(duration)
    fade.setStartValue(0.0)
    fade.setEndValue(1.0)
    group.addAnimation(height)
    group.addAnimation(fade)

    def done() -> None:
        widget.setMaximumHeight(_QWIDGETSIZE_MAX)
        widget.setGraphicsEffect(None)

    _run(widget, group, done)


def slide_out(widget: QWidget, on_done: Callable[[], None] | None = None, duration: int = DURATION_MS) -> None:
    """Satırı yüksekliğini 0'a indirerek (ve solarak) gizler; bitince `on_done`."""
    _stop(widget)

    def done() -> None:
        widget.hide()
        widget.setMaximumHeight(_QWIDGETSIZE_MAX)
        widget.setGraphicsEffect(None)
        if on_done is not None:
            on_done()

    if widget.isHidden() or not _can_animate(widget):
        done()
        return
    effect = _opacity_effect(widget, 1.0)
    group = QParallelAnimationGroup(widget)
    height = QPropertyAnimation(widget, b"maximumHeight", group)
    height.setDuration(duration)
    height.setStartValue(max(1, widget.height()))
    height.setEndValue(0)
    height.setEasingCurve(QEasingCurve.Type.InCubic)
    fade = QPropertyAnimation(effect, b"opacity", group)
    fade.setDuration(duration)
    fade.setStartValue(1.0)
    fade.setEndValue(0.0)
    group.addAnimation(height)
    group.addAnimation(fade)
    _run(widget, group, done)


def fade_in(widget: QWidget, duration: int = DURATION_MS) -> None:
    _stop(widget)
    if not _can_animate(widget):
        widget.setGraphicsEffect(None)
        widget.show()
        return
    effect = _opacity_effect(widget, 0.0)
    widget.show()
    group = QParallelAnimationGroup(widget)
    fade = QPropertyAnimation(effect, b"opacity", group)
    fade.setDuration(duration)
    fade.setStartValue(0.0)
    fade.setEndValue(1.0)
    fade.setEasingCurve(QEasingCurve.Type.OutCubic)
    group.addAnimation(fade)
    _run(widget, group, lambda: widget.setGraphicsEffect(None))


def fade_out(widget: QWidget, on_done: Callable[[], None] | None = None, duration: int = DURATION_MS) -> None:
    _stop(widget)

    def done() -> None:
        widget.hide()
        widget.setGraphicsEffect(None)
        if on_done is not None:
            on_done()

    if widget.isHidden() or not _can_animate(widget):
        done()
        return
    effect = _opacity_effect(widget, 1.0)
    group = QParallelAnimationGroup(widget)
    fade = QPropertyAnimation(effect, b"opacity", group)
    fade.setDuration(duration)
    fade.setStartValue(1.0)
    fade.setEndValue(0.0)
    fade.setEasingCurve(QEasingCurve.Type.InCubic)
    group.addAnimation(fade)
    _run(widget, group, done)
