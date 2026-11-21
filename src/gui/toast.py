"""Pencere içi kısa bildirim (toast): "2 dosya kuyruktan çıkarıldı  [Geri al]" ya da "Tamamlandı · 2.0 GB kazanıldı".

Ana pencerenin içinde, verilen çapa widget'ının (kuyruk) alt ortasında yüzer; yerleşimde yer kaplamaz. Birkaç saniye
sonra kendiliğinden solar (fare üstündeyken süre durur). Yeni ileti eskisinin yerini alır. Renkler temanın tersidir
(koyu temada açık, açık temada koyu kutu): kuyruk satırlarının üstünde her iki temada da seçilir. Stil
theme_manager'daki `QFrame#toast` kurallarından gelir.

Geri çağrılar (on_action/on_click) bağlı yöntemse zayıf referansla tutulur: toast pencerenin çocuğudur; pencerenin
yöntemini güçlü tutsaydı Python tarafında döngü oluşur, pencere ancak çöp toplayıcının keyfi bir anında (ör. bir
QApplication.setStyle döngüsünün ortasında) silinir ve Qt çökebilirdi. Bu yüzden pencereyi yakalayan lambda yerine
bağlı yöntem verin.
"""

from __future__ import annotations

import inspect
import weakref
from typing import Callable

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QWidget

from . import anim

DEFAULT_TIMEOUT_MS = 6000
_MARGIN = 16


def _hold(callback: Callable[[], object] | None) -> Callable[[], Callable[[], object] | None] | None:
    """Geri çağrıyı saklanacak biçime çevirir: bağlı yöntem → WeakMethod; diğerleri olduğu gibi."""
    if callback is None:
        return None
    if inspect.ismethod(callback):
        return weakref.WeakMethod(callback)
    return lambda: callback


def _resolve(held) -> Callable[[], object] | None:
    return held() if held is not None else None


class Toast(QFrame):
    action_triggered = pyqtSignal()
    clicked = pyqtSignal()
    closed = pyqtSignal()

    def __init__(self, host: QWidget, anchor: QWidget | None = None):
        super().__init__(host)
        self.setObjectName("toast")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self._host = host
        self._anchor = anchor
        self._on_action = None  # _hold(...) sonucu
        self._on_click = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.dismiss)
        self._timeout = DEFAULT_TIMEOUT_MS

        row = QHBoxLayout(self)
        row.setContentsMargins(14, 8, 8, 8)
        row.setSpacing(10)
        self.label = QLabel(self)
        self.label.setObjectName("toast_text")
        self.label.setTextFormat(Qt.TextFormat.PlainText)
        self.label.setWordWrap(False)
        row.addWidget(self.label, 1)
        self.action_btn = QPushButton(self)
        self.action_btn.setObjectName("toast_action")
        self.action_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.action_btn.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.action_btn.clicked.connect(self._action)
        self.action_btn.hide()
        row.addWidget(self.action_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        self.close_btn = QPushButton("✕", self)
        self.close_btn.setObjectName("toast_close")
        self.close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.close_btn.setFixedSize(24, 24)
        self.close_btn.clicked.connect(self.dismiss)
        row.addWidget(self.close_btn, 0, Qt.AlignmentFlag.AlignVCenter)

        # Konum, pencere boyutu değişince ana pencereden `reposition()` ile güncellenir. Başka widget'lara Python olay
        # süzgeci (eventFilter) takılmaz: pencere silinirken/QApplication.setStyle sırasında süzgeç çağrısı çöküyordu.
        self.hide()

    # ------------------------------------------------------------------ genel
    def show_message(self, text: str, action_text: str = "", on_action: Callable[[], object] | None = None, *,
                     on_click: Callable[[], object] | None = None, timeout_ms: int = DEFAULT_TIMEOUT_MS,
                     tooltip: str = "") -> None:
        """İletiyi gösterir (önceki toast varsa yerini alır; onun geri al işlemi artık sunulmaz)."""
        self._on_action = _hold(on_action)
        self._on_click = _hold(on_click)
        self._timeout = max(1000, int(timeout_ms))
        self.label.setText(str(text))
        self.action_btn.setText(action_text or "")
        self.action_btn.setVisible(bool(action_text))
        if on_click is not None:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        else:
            self.unsetCursor()
        self.setToolTip(tooltip or "")
        self.label.setToolTip(tooltip or "")
        self.adjustSize()
        self._place()
        self.raise_()
        if self.isHidden() or anim.is_animating(self):
            anim.fade_in(self)
        self._timer.start(self._timeout)

    def text(self) -> str:
        return self.label.text()

    def is_showing(self) -> bool:
        return not self.isHidden()

    def dismiss(self) -> None:
        self._timer.stop()
        if self.isHidden():
            return
        self._on_action = self._on_click = None
        anim.fade_out(self, self.closed.emit)

    # ------------------------------------------------------------------ etkileşim
    def _action(self) -> None:
        callback = _resolve(self._on_action)
        self.dismiss()
        self.action_triggered.emit()
        if callback is not None:
            callback()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self._on_click is not None \
                and self.rect().contains(event.position().toPoint()):
            callback = _resolve(self._on_click)
            self.dismiss()
            self.clicked.emit()
            if callback is not None:
                callback()
            return
        super().mouseReleaseEvent(event)

    def enterEvent(self, event) -> None:  # noqa: N802
        self._timer.stop()  # okunurken kaybolmasın
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        if not self.isHidden():
            self._timer.start(min(self._timeout, 3000))  # fare çekilince kısa bir süre daha kalır
        super().leaveEvent(event)

    # ------------------------------------------------------------------ yerleşim
    def reposition(self) -> None:
        """Pencere/çapa boyutu değişti: görünüyorsa yeniden ortala."""
        if not self.isHidden():
            self._place()

    def _place(self) -> None:
        host = self._host
        hint = self.sizeHint()
        anchor = self._anchor if self._anchor is not None and self._anchor.isVisible() else host
        top_left = anchor.mapTo(host, anchor.rect().topLeft()) if anchor is not host else host.rect().topLeft()
        area_w, area_h = anchor.width(), anchor.height()
        width = min(hint.width(), max(160, area_w - 2 * _MARGIN))
        self.resize(width, hint.height())
        x = top_left.x() + (area_w - width) // 2
        y = top_left.y() + area_h - hint.height() - _MARGIN
        self.move(max(0, x), max(0, y))
