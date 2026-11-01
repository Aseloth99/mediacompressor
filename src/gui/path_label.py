"""Klasör yolunu sığdığı kadar gösteren etiket: sığmazsa ortasını "…" ile kısaltır, tamamı ipucunda durur."""

from __future__ import annotations

from PyQt6.QtCore import QEvent, Qt, pyqtSignal
from PyQt6.QtWidgets import QLabel, QSizePolicy


# Kısaltmada bırakılan pay (px): son harfin çıkıntısı ("ş", "ç" kuyrukları) 150% ölçekte kutudan taşıyor ve
# metin sınırda sığdığında son harf yarım görünüyordu ("sıkıştırılmı" + yarım "ş").
ELIDE_SLACK = 4


class ElidedPathLabel(QLabel):
    clicked = pyqtSignal()

    def __init__(self, text: str = "", parent=None):
        super().__init__(parent)
        self._full = ""
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(40)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        self.setText(text)

    def full_text(self) -> str:
        return self._full

    def setText(self, text: str) -> None:  # noqa: N802 (Qt adı)
        self._full = text or ""
        self.setToolTip(self._full)
        self._apply()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._apply()

    def changeEvent(self, event) -> None:  # noqa: N802
        super().changeEvent(event)
        # tema/yazı tipi değişince eski yazı tipiyle yapılmış kısaltma taşabilir
        if event.type() in (QEvent.Type.FontChange, QEvent.Type.StyleChange):
            self._apply()

    def _apply(self) -> None:
        width = max(0, self.contentsRect().width() - ELIDE_SLACK)
        shown = self.fontMetrics().elidedText(self._full, Qt.TextElideMode.ElideMiddle, width) if width else self._full
        if shown != self.text():
            super().setText(shown)
