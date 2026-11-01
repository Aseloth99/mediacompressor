"""Sıkıştırma profillerinin gelişmiş paneli — ayrı pencere, sol kolon şişmez."""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QFrame, QHBoxLayout, QLabel, QPushButton,
    QSlider, QVBoxLayout,
)

from ..core.app_info import is_auto_bitrate
from ..utils.locales import t
from ..utils.theme_manager import fit_text_widgets
from .chrome_dialog import ChromeDialog

PRESETS = [
    ("superfast", "preset_superfast"),
    ("veryfast", "preset_veryfast"),
    ("faster", "preset_faster"),
    ("fast", "preset_fast"),
    ("medium", "preset_medium"),
    ("slow", "preset_slow"),
    ("slower", "preset_slower"),
]


FPS_VALUES = [None, 60, 30, 25, 24]  # None = Orijinal

# GPU menüsü öğe verisi = aile kimliği; görünen ad dile göre (eskiden metin eşleşmesiyle çözülüyordu ve dil
# değişince 2. öğe — ör. "NVIDIA NVENC" — yanlışlıkla "CPU" diye yeniden adlandırılıyordu).
GPU_FAMILY_LABELS = {
    "nvenc": "NVIDIA NVENC", "amf": "AMD AMF", "qsv": "Intel QSV", "vaapi": "VAAPI", "videotoolbox": "VideoToolbox",
}


def _crf_caption(value: int, lang: str) -> str:
    if value <= 20:
        return t("crf_very_high", lang).format(value)
    if value <= 24:
        return t("crf_balanced", lang).format(value)
    if value <= 28:
        return t("crf_smaller", lang).format(value)
    return t("crf_smallest", lang).format(value)


class AdvancedDialog(ChromeDialog):
    def __init__(self, codec_labels_fn, bitrate_labels_fn, parent=None, lang: str = "tr"):
        super().__init__(parent, scroll=True)
        self.lang = lang
        self._codec_labels = codec_labels_fn if callable(codec_labels_fn) else (lambda l: codec_labels_fn)
        self._bitrate_labels = bitrate_labels_fn if callable(bitrate_labels_fn) else (lambda l: bitrate_labels_fn)
        self.setWindowTitle(t("adv_settings", self.lang))
        self.setMinimumWidth(860)
        outer = QVBoxLayout(self.body_host)
        outer.setSpacing(12)
        outer.setContentsMargins(22, 18, 22, 18)

        self.hint = QLabel(t("adv_hint", self.lang))
        self.hint.setObjectName("hint_label")
        self.hint.setWordWrap(True)
        outer.addWidget(self.hint)

        # İki sütun, her sütunda başlıklı kartlar: tek uzun sütun (≈900 px) küçük ekrana sığmıyordu
        columns = QHBoxLayout()
        columns.setSpacing(14)
        left = QVBoxLayout()
        left.setSpacing(12)
        right = QVBoxLayout()
        right.setSpacing(12)
        columns.addLayout(left, 1)
        columns.addLayout(right, 1)
        outer.addLayout(columns)

        self._captions: dict[str, QLabel] = {}

        def card(title_key: str) -> tuple[QFrame, QVBoxLayout]:
            frame = QFrame()
            frame.setObjectName("adv_card")
            lay = QVBoxLayout(frame)
            lay.setContentsMargins(14, 10, 14, 14)
            lay.setSpacing(8)
            caption = QLabel(t(title_key, self.lang))
            caption.setObjectName("section_caption")
            lay.addWidget(caption)
            self._captions[title_key] = caption
            return frame, lay

        # --- Video kodlama: kodek, bitrate, kalite
        video_card, layout = card("adv_group_video")
        left.addWidget(video_card)

        # Kodek seçimi ana pencerede durur (burada gözden kaçıyordu); öğeler burada kurulur, ana pencere yerleştirir.
        self.codec = QComboBox()
        for _, label in self._codec_labels(self.lang):
            self.codec.addItem(label)
        self.codec_lab = QLabel(t("video_codec", self.lang))
        self.codec_lab.setObjectName("field_label")
        # Seçilen kodeğin kısa açıklaması; AV1 bu bilgisayarda yavaşsa uyarı.
        self.codec_hint = QLabel()
        self.codec_hint.setObjectName("hint_label")
        self.codec_hint.setWordWrap(True)
        self.codec_hint.hide()

        self.bitrate = QComboBox()
        for _, label in self._bitrate_labels(self.lang):
            self.bitrate.addItem(label)
        self.br_lab = QLabel(t("adv_bitrate", self.lang))
        self.br_lab.setObjectName("field_label")
        layout.addWidget(self.br_lab)
        layout.addWidget(self.bitrate)

        self.bitrate_hint = QLabel()
        self.bitrate_hint.setObjectName("hint_label")
        self.bitrate_hint.setWordWrap(True)
        layout.addWidget(self.bitrate_hint)

        crf_row = QHBoxLayout()
        self.crf_lab = QLabel(t("adv_quality_crf", self.lang))
        self.crf_lab.setObjectName("field_label")
        crf_row.addWidget(self.crf_lab)
        self.crf_value = QLabel(_crf_caption(24, self.lang))
        self.crf_value.setObjectName("hint_label")
        crf_row.addWidget(self.crf_value, 1)
        layout.addLayout(crf_row)
        self.crf = QSlider(Qt.Orientation.Horizontal)
        self.crf.setRange(18, 32)
        self.crf.setValue(24)
        self.crf.setToolTip(t("crf_tooltip", self.lang))
        self.crf.valueChanged.connect(self._on_crf)
        layout.addWidget(self.crf)

        self.crf_hint = QLabel()
        self.crf_hint.setObjectName("hint_label")
        self.crf_hint.setWordWrap(True)
        layout.addWidget(self.crf_hint)

        # Kare hızı: varsayılan Orijinal (kaynağınki korunur); yalnızca düşürür, asla artırmaz.
        self.fps_lab = QLabel(t("adv_fps", self.lang))
        self.fps_lab.setObjectName("field_label")
        layout.addWidget(self.fps_lab)
        self.fps = QComboBox()
        for value in FPS_VALUES:
            self.fps.addItem(self._fps_text(value), value)
        self.fps.setCurrentIndex(0)
        layout.addWidget(self.fps)
        self.fps_hint = QLabel(t("fps_hint", self.lang))
        self.fps_hint.setObjectName("hint_label")
        self.fps_hint.setWordWrap(True)
        layout.addWidget(self.fps_hint)
        left.addStretch(1)

        # --- Hız ve ses
        speed_card, layout = card("adv_group_speed")
        right.addWidget(speed_card)

        self.preset = QComboBox()
        for value, label_key in PRESETS:
            self.preset.addItem(t(label_key, self.lang), value)
        slow = self.preset.findData("slow")
        self.preset.setCurrentIndex(slow if slow >= 0 else 5)
        self.speed_lab = QLabel(t("adv_processing_speed", self.lang))
        self.speed_lab.setObjectName("field_label")
        layout.addWidget(self.speed_lab)
        layout.addWidget(self.preset)
        self.preset_hint = QLabel(t("preset_hint", self.lang))
        self.preset_hint.setObjectName("hint_label")
        self.preset_hint.setWordWrap(True)
        layout.addWidget(self.preset_hint)

        self.audio = QComboBox()
        self.audio.addItems(["96k", "128k", "192k"])
        self.audio.setCurrentText("128k")
        self.audio_lab = QLabel(t("adv_audio", self.lang))
        self.audio_lab.setObjectName("field_label")
        layout.addWidget(self.audio_lab)
        layout.addWidget(self.audio)
        self.audio_hint = QLabel(t("audio_hint", self.lang))
        self.audio_hint.setObjectName("hint_label")
        self.audio_hint.setWordWrap(True)
        layout.addWidget(self.audio_hint)
        # Sesi tamamen kaldır (tek tek dosyalar için sağ tık > İstisna > Ses).
        self.remove_audio = QCheckBox(t("adv_remove_audio", self.lang))
        self.remove_audio.toggled.connect(lambda on: self.audio.setEnabled(not on))
        layout.addWidget(self.remove_audio)

        # --- Resim
        image_card, layout = card("image")
        right.addWidget(image_card)
        self.img_auto = QCheckBox(t("adv_img_auto", self.lang))
        self.img_auto.setChecked(True)
        layout.addWidget(self.img_auto)
        self.img_quality = QSlider(Qt.Orientation.Horizontal)
        self.img_quality.setRange(50, 95)
        self.img_quality.setValue(80)
        self.img_quality.setEnabled(False)
        self.img_auto.toggled.connect(lambda on: self.img_quality.setEnabled(not on))
        layout.addWidget(self.img_quality)

        # --- Genel
        general_card, layout = card("adv_group_general")
        right.addWidget(general_card)
        self.subfolders = QCheckBox(t("adv_subfolders", self.lang))
        self.subfolders.setChecked(True)
        layout.addWidget(self.subfolders)

        self.gpu_menu = QComboBox()
        self.set_gpu_families([])
        self.gpu_lab = QLabel(t("adv_gpu", self.lang))
        self.gpu_lab.setObjectName("field_label")
        layout.addWidget(self.gpu_lab)
        layout.addWidget(self.gpu_menu)
        right.addStretch(1)

        self.close_btn = QPushButton(t("ok", self.lang))
        self.close_btn.setProperty("class", "primary")
        self.close_btn.setMinimumWidth(160)
        self.close_btn.clicked.connect(self.accept)
        outer.addWidget(self.close_btn, 0, Qt.AlignmentFlag.AlignRight)

        self.bitrate.currentIndexChanged.connect(self._refresh_mode_hints)
        self._refresh_mode_hints()
        fit_text_widgets(self)

    def retranslate(self, lang: str):
        self.lang = lang
        self.setWindowTitle(t("adv_settings", lang))
        self.hint.setText(t("adv_hint", lang))
        for key, caption in self._captions.items():
            caption.setText(t(key, lang))
        self.codec_lab.setText(t("video_codec", lang))
        for i, (_, label) in enumerate(self._codec_labels(lang)):
            if i < self.codec.count():
                self.codec.setItemText(i, label)
        self.br_lab.setText(t("adv_bitrate", lang))
        for i, (_, label) in enumerate(self._bitrate_labels(lang)):
            if i < self.bitrate.count():
                self.bitrate.setItemText(i, label)
        self.crf_lab.setText(t("adv_quality_crf", lang))
        self.crf.setToolTip(t("crf_tooltip", lang))
        self.crf_value.setText(_crf_caption(self.crf.value(), lang))
        self.speed_lab.setText(t("adv_processing_speed", lang))
        for i, (_, label_key) in enumerate(PRESETS):
            self.preset.setItemText(i, t(label_key, lang))
        self.preset_hint.setText(t("preset_hint", lang))
        self.audio_lab.setText(t("adv_audio", lang))
        self.audio_hint.setText(t("audio_hint", lang))
        self.remove_audio.setText(t("adv_remove_audio", lang))
        self.img_auto.setText(t("adv_img_auto", lang))
        self.subfolders.setText(t("adv_subfolders", lang))
        self.gpu_lab.setText(t("adv_gpu", lang))
        for key, label_key in (("auto", "adv_gpu_auto"), ("cpu", "adv_gpu_cpu")):
            idx = self.gpu_menu.findData(key)
            if idx >= 0:
                self.gpu_menu.setItemText(idx, t(label_key, lang))
        self.close_btn.setText(t("ok", lang))
        self.fps_lab.setText(t("adv_fps", lang))
        for i in range(self.fps.count()):
            self.fps.setItemText(i, self._fps_text(self.fps.itemData(i)))
        self.fps_hint.setText(t("fps_hint", lang))
        self._refresh_mode_hints()

    def set_codec_hint(self, text: str, warn: bool = False) -> None:
        self.codec_hint.setText(text)
        name = "gpu_warn" if warn else "hint_label"  # uyarı rengi temada tanımlı
        if self.codec_hint.objectName() != name:
            self.codec_hint.setObjectName(name)
            self.codec_hint.style().unpolish(self.codec_hint)
            self.codec_hint.style().polish(self.codec_hint)
        self.codec_hint.setVisible(bool(text))
        fit_text_widgets(self.codec_hint)

    def set_gpu_families(self, families: list[str]) -> None:
        """Menü: Otomatik, bulunan donanım aileleri, CPU. Seçili aile (varsa) korunur."""
        current = self.gpu_choice() if self.gpu_menu.count() else "auto"
        self.gpu_menu.blockSignals(True)
        self.gpu_menu.clear()
        self.gpu_menu.addItem(t("adv_gpu_auto", self.lang), "auto")
        for family in families:
            if family != "cpu":
                self.gpu_menu.addItem(GPU_FAMILY_LABELS.get(family, family.upper()), family)
        self.gpu_menu.addItem(t("adv_gpu_cpu", self.lang), "cpu")
        self.gpu_menu.blockSignals(False)
        self.set_gpu_choice(current)

    def gpu_choice(self) -> str:
        """Seçili aile kimliği: "auto", "nvenc", "amf", ..., "cpu"."""
        return self.gpu_menu.currentData() or "auto"

    def set_gpu_choice(self, key: str) -> None:
        idx = self.gpu_menu.findData(key or "auto")
        self.gpu_menu.setCurrentIndex(idx if idx >= 0 else 0)

    def _fps_text(self, value) -> str:
        return t("fps_orig_option", self.lang) if value is None else t("fps_value", self.lang).format(value)

    def fps_value(self):
        """Seçili kare hızı (None = orijinal)."""
        idx = self.fps.currentIndex()
        return FPS_VALUES[idx] if 0 <= idx < len(FPS_VALUES) else None

    def set_fps(self, value) -> None:
        idx = FPS_VALUES.index(value) if value in FPS_VALUES else 0  # öğe sırası FPS_VALUES ile aynı
        self.fps.setCurrentIndex(idx)

    def _on_crf(self, value: int):
        self.crf_value.setText(_crf_caption(int(value), self.lang))

    def _is_auto_bitrate(self) -> bool:
        idx = self.bitrate.currentIndex()
        labels = self._bitrate_labels(self.lang)
        if 0 <= idx < len(labels):
            return is_auto_bitrate(labels[idx][0])
        return False

    def _refresh_mode_hints(self):
        auto = self._is_auto_bitrate()
        self.crf.setEnabled(auto)
        self.crf_value.setEnabled(auto)
        if auto:
            self.bitrate_hint.setText(t("bitrate_auto_hint", self.lang))
            self.crf_hint.setText(t("crf_mode_hint", self.lang))
        else:
            self.bitrate_hint.setText(t("bitrate_fixed_hint", self.lang))
            self.crf_hint.setText(t("crf_disabled_hint", self.lang))
