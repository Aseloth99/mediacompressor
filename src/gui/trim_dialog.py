"""Videoyu kırp: başlangıç ve bitiş seçilir, iki uçtaki kare önizlenir; yalnızca bu aralık sıkıştırılır."""

from __future__ import annotations

import os
import re
from typing import Optional

from PyQt6.QtCore import Qt, QThread, QTimer
from PyQt6.QtGui import QPixmap, QValidator
from PyQt6.QtWidgets import (
    QDoubleSpinBox, QGridLayout, QHBoxLayout, QLabel, QPushButton, QSlider, QVBoxLayout,
)

from ..utils.locales import t
from ..utils.timecode import clock, parse_clock
from ..utils.theme_manager import fit_text_widgets
from .chrome_dialog import ChromeDialog
from .preview_dialog import _ExtractFrameWorker

MIN_LENGTH = 0.5  # en kısa parça (sn)
STEP = 0.1  # kaydırıcı / alan adımı (sn)
FRAME_W, FRAME_H = 400, 225


class TimeSpin(QDoubleSpinBox):
    """Saniyeyi "dakika:saniye.onda" olarak gösteren / okuyan alan."""

    def __init__(self, maximum: float, parent=None):
        super().__init__(parent)
        self.setDecimals(1)
        self.setSingleStep(STEP)
        self.setRange(0.0, maximum)
        self.setKeyboardTracking(False)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumWidth(self.fontMetrics().horizontalAdvance(clock(max(maximum, 3600), True)) + 56)

    def textFromValue(self, value: float) -> str:  # noqa: N802
        return clock(value, tenths=True)

    def valueFromText(self, text: str) -> float:  # noqa: N802
        value = parse_clock(text)
        return self.value() if value is None else value

    def validate(self, text: str, pos: int):
        value = parse_clock(text)
        if value is None:
            ok = re.fullmatch(r"[\d:.,]*", text.strip()) is not None
            return (QValidator.State.Intermediate if ok else QValidator.State.Invalid), text, pos
        state = QValidator.State.Acceptable if self.minimum() <= value <= self.maximum() else QValidator.State.Intermediate
        return state, text, pos


class TrimDialog(ChromeDialog):
    """``values()`` -> (başlangıç, bitiş | None) ya da kırpma yoksa None."""

    def __init__(self, path: str, duration: float, trim=None, parent=None, lang: str = "tr"):
        super().__init__(parent)
        self.lang = lang
        self.path = path
        self.duration = max(0.1, float(duration))
        self._workers: set[QThread] = set()
        self._req = {"start": 0, "end": 0}
        self.setWindowTitle(t("trim_title", lang))

        outer = QVBoxLayout(self.body_host)
        outer.setContentsMargins(22, 18, 22, 18)
        outer.setSpacing(12)
        name = QLabel(os.path.basename(path))
        name.setObjectName("dialog_header")
        outer.addWidget(name)
        hint = QLabel(t("trim_hint", lang))
        hint.setObjectName("hint_label")
        hint.setWordWrap(True)
        outer.addWidget(hint)

        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(8)
        outer.addLayout(grid)
        self.frames: dict[str, QLabel] = {}
        self.sliders: dict[str, QSlider] = {}
        self.spins: dict[str, TimeSpin] = {}
        self._timers: dict[str, QTimer] = {}
        steps = int(round(self.duration / STEP))
        for col, side in enumerate(("start", "end")):
            caption = QLabel(t(f"trim_{side}", lang))
            caption.setObjectName("field_label")
            grid.addWidget(caption, 0, col)
            frame = QLabel(t("trim_loading", lang))
            frame.setObjectName("trim_frame")
            frame.setAlignment(Qt.AlignmentFlag.AlignCenter)
            frame.setFixedSize(FRAME_W, FRAME_H)
            grid.addWidget(frame, 1, col)
            row = QHBoxLayout()
            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setRange(0, steps)
            spin = TimeSpin(self.duration)
            row.addWidget(slider, 1)
            row.addWidget(spin)
            grid.addLayout(row, 2, col)
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.setInterval(150)
            timer.timeout.connect(lambda s=side: self._extract(s))
            self.frames[side], self.sliders[side], self.spins[side], self._timers[side] = frame, slider, spin, timer

        self.info = QLabel()
        self.info.setObjectName("hint_label")
        outer.addWidget(self.info)

        buttons = QHBoxLayout()
        self.reset_btn = QPushButton(t("trim_reset", lang))
        self.reset_btn.setProperty("class", "ghost")
        self.reset_btn.clicked.connect(self._reset)
        buttons.addWidget(self.reset_btn)
        buttons.addStretch(1)
        cancel = QPushButton(t("cancel", lang))
        cancel.setProperty("class", "ghost")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        self.apply_btn = QPushButton(t("trim_apply", lang))
        self.apply_btn.setProperty("class", "primary")
        self.apply_btn.setDefault(True)
        self.apply_btn.clicked.connect(self.accept)
        buttons.addWidget(self.apply_btn)
        outer.addLayout(buttons)

        start, end = (trim[0], trim[1]) if trim else (0.0, None)
        self._set("start", float(start or 0.0))
        self._set("end", self.duration if end is None else min(float(end), self.duration))
        for side in ("start", "end"):
            self.sliders[side].valueChanged.connect(lambda v, s=side: self._on_slider(s, v))
            self.spins[side].valueChanged.connect(lambda v, s=side: self._on_spin(s, v))
        self._refresh_info()
        fit_text_widgets(self)
        self._extract("start")
        self._extract("end")

    # ------------------------------------------------------------------ değerler
    def _set(self, side: str, seconds: float) -> None:
        slider, spin = self.sliders[side], self.spins[side]
        slider.blockSignals(True)
        spin.blockSignals(True)
        slider.setValue(int(round(seconds / STEP)))
        spin.setValue(seconds)
        slider.blockSignals(False)
        spin.blockSignals(False)

    def _value(self, side: str) -> float:
        return float(self.spins[side].value())

    def _apply(self, side: str, seconds: float) -> None:
        """Bir ucu değiştir; diğer uçla arada en az MIN_LENGTH kalsın (gerekirse diğeri itilir)."""
        seconds = max(0.0, min(self.duration, seconds))
        gap = min(MIN_LENGTH, self.duration)
        if side == "start":
            seconds = min(seconds, self.duration - gap)
            if self._value("end") < seconds + gap:
                self._set("end", seconds + gap)
                self._timers["end"].start()
        else:
            seconds = max(seconds, gap)
            if self._value("start") > seconds - gap:
                self._set("start", seconds - gap)
                self._timers["start"].start()
        self._set(side, seconds)
        self._timers[side].start()
        self._refresh_info()

    def _on_slider(self, side: str, value: int) -> None:
        self._apply(side, value * STEP)

    def _on_spin(self, side: str, value: float) -> None:
        self._apply(side, value)

    def _reset(self) -> None:
        self._set("start", 0.0)
        self._set("end", self.duration)
        self._refresh_info()
        self._timers["start"].start()
        self._timers["end"].start()

    def _refresh_info(self) -> None:
        length = self._value("end") - self._value("start")
        self.info.setText(t("trim_info", self.lang).format(
            new=clock(length, tenths=True), total=clock(self.duration, tenths=True),
        ))

    def values(self):
        start, end = round(self._value("start"), 1), round(self._value("end"), 1)
        if end >= self.duration - 0.05:
            end = None
        if start < 0.05 and end is None:
            return None
        return start, end

    # ------------------------------------------------------------------ kareler
    def _extract(self, side: str) -> None:
        self._req[side] += 1
        seconds = self._value(side)
        if side == "end":  # son karenin tam sınırında kare çıkmayabilir
            seconds = max(0.0, min(seconds, self.duration - 0.1))
        worker = _ExtractFrameWorker(self._req[side] * 2 + (side == "end"), self.path, seconds)
        worker.frame_ready.connect(self._on_frame)
        worker.frame_failed.connect(self._on_frame_failed)
        worker.finished.connect(lambda w=worker: self._workers.discard(w))
        self._workers.add(worker)
        worker.start()

    def _side_of(self, req_id: int) -> Optional[str]:
        side = "end" if req_id % 2 else "start"
        return side if req_id // 2 == self._req[side] else None  # eski istek: yok say

    def _on_frame(self, req_id: int, png: bytes, _seconds: float) -> None:
        side = self._side_of(req_id)
        if side is None:
            return
        pix = QPixmap()
        if not pix.loadFromData(png):
            self.frames[side].setText(t("trim_no_frame", self.lang))
            return
        label = self.frames[side]
        label.setPixmap(pix.scaled(label.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                   Qt.TransformationMode.SmoothTransformation))

    def _on_frame_failed(self, req_id: int, _msg: str) -> None:
        side = self._side_of(req_id)
        if side is not None:
            self.frames[side].setPixmap(QPixmap())
            self.frames[side].setText(t("trim_no_frame", self.lang))

    def done(self, result: int) -> None:  # noqa: D401 — kapanırken kare işçileri beklenir
        for timer in self._timers.values():
            timer.stop()
        for worker in list(self._workers):
            worker.cancel()
            worker.wait(3000)
        super().done(result)
