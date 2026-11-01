"""Canlı Resim Sıkıştırma Önizleme ve Karşılaştırma Penceresi (Space tuşu ve canlı format/kalite karşılaştırma)."""

from __future__ import annotations

import io
import os
from pathlib import Path
import subprocess
from typing import Optional

from PIL import Image, ImageOps

try:
    import pillow_heif
    pillow_heif.register_heif_opener()
except ImportError:
    pass

try:
    import pillow_avif
except ImportError:
    pass

try:
    import imagecodecs
except ImportError:
    imagecodecs = None

from PyQt6 import sip
from PyQt6.QtCore import QEvent, QRect, QRectF, QSize, Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QFont,
    QImage,
    QLinearGradient,
    QPainter,
    QPaintEvent,
    QPen,
    QPixmap,
)
from PyQt6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from ..core.app_info import CUSTOM_RES
from . import icons
from .chrome_dialog import ChromeDialog
from .message_box import InputDialog, MessageBox
from .res_combo import find_res, mark_original, res_value, select_res
from ..core.image_compressor import ImageCompressor
from ..core.ffmpeg_manager import FFmpegManager
from ..core.video_compressor import VIDEO_EXTS, build_frame_extract_cmd
from ..utils.helpers import format_bytes
from ..utils.locales import t
from ..utils.process import kill_process_tree, popen_hidden

# LOAD_TRUNCATED_IMAGES bilerek ayarlanmaz: işlem-genelindeki bu bayrak sıkıştırıcıya da sızıp
# bozuk dosyaları "başarılı" gösteriyordu (bkz. image_compressor).


PREVIEW_IMAGE_RES = {
    "Orijinal": None,
    "3840px": 3840,
    "2400px": 2400,
    "1920px": 1920,
    "1440px": 1440,
    "1080px": 1080,
    "720px": 720,
}

PREVIEW_VIDEO_RES = {
    "Orijinal": None,
    "1440p": 2560,
    "1080p": 1920,
    "720p": 1280,
}


def _parse_res_value(text: str) -> Optional[int]:
    if not text or text == "Orijinal":
        return None
    if text in PREVIEW_VIDEO_RES:
        return PREVIEW_VIDEO_RES[text]
    if text in PREVIEW_IMAGE_RES:
        return PREVIEW_IMAGE_RES[text]
    clean = text.replace("px", "").replace("p", "").strip()
    try:
        return int(clean)
    except Exception:
        return None


class _ImageCanvas(QWidget):
    """Resmi ekrana tam hizalı çizen, sağ üstte durum rozeti ve spinner gösteren tuval."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pixmap: Optional[QPixmap] = None
        self.is_original: bool = False
        self.badge_text: str = ""
        self.is_loading: bool = False
        self.loading_text: str = ""
        self.spinner_angle: int = 0
        self.shimmer_pos: float = 0.0

        self.orig_w: int = 1
        self.orig_h: int = 1
        self.lang: str = "tr"
        self.setMinimumSize(320, 240)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self._anim_timer = QTimer(self)
        self._anim_timer.setInterval(40)  # 25 FPS
        self._anim_timer.timeout.connect(self._on_anim_tick)

    def set_reference_dimensions(self, w: int, h: int):
        self.orig_w = max(1, w)
        self.orig_h = max(1, h)

    def set_loading(self, loading: bool, text: str = ""):
        self.is_loading = loading
        self.loading_text = text
        if loading:
            if not self._anim_timer.isActive():
                self._anim_timer.start()
        else:
            if self._anim_timer.isActive():
                self._anim_timer.stop()
        self.update()

    def _on_anim_tick(self):
        self.spinner_angle = (self.spinner_angle + 24) % 360
        self.shimmer_pos = (self.shimmer_pos + 0.04) % 1.0
        self.update()

    def set_image(self, pixmap: Optional[QPixmap], is_original: bool, badge_text: str):
        self.pixmap = pixmap
        self.is_original = is_original
        self.badge_text = badge_text
        self.update()

    def paintEvent(self, event: QPaintEvent):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        pal = self.palette()
        bg_color = pal.color(self.backgroundRole())
        light_bg = bg_color.lightness() > 200
        bg_color = QColor("#d8d8d8") if light_bg else QColor("#121418")
        painter.fillRect(self.rect(), bg_color)

        w = self.width()
        h = self.height()

        # Resim yüklü değilse ve yükleme de yoksa: Boş Durum (Empty State)
        if (not self.pixmap or self.pixmap.isNull()) and not self.is_loading:
            card_w = min(460, w - 40)
            card_h = 130
            cx = (w - card_w) // 2
            cy = (h - card_h) // 2
            card_rect = QRect(cx, cy, card_w, card_h)

            # the empty-state card/text were drawn for the dark canvas only (white on #d8d8d8 vanished)
            painter.setPen(QPen(QColor(0, 0, 0, 40) if light_bg else QColor(255, 255, 255, 20), 1))
            painter.setBrush(QColor(0, 0, 0, 10) if light_bg else QColor(255, 255, 255, 6))
            painter.drawRoundedRect(card_rect, 10, 10)

            font = QFont(self.font().family(), 13, QFont.Weight.Bold)
            painter.setFont(font)
            painter.setPen(QColor("#1e293b") if light_bg else QColor("#e2e8f0"))
            t_rect = QRect(cx + 16, cy + 24, card_w - 32, 28)
            painter.drawText(t_rect, Qt.AlignmentFlag.AlignCenter, t("preview_empty_title", self.lang))

            font2 = QFont(self.font().family(), 10)
            painter.setFont(font2)
            painter.setPen(QColor("#475569") if light_bg else QColor("#94a3b8"))
            s_rect = QRect(cx + 16, cy + 60, card_w - 32, 40)
            painter.drawText(
                s_rect,
                Qt.AlignmentFlag.AlignCenter,
                t("preview_empty_hint", self.lang),
            )
            return

        # Resim yüklü değil ama yükleniyor ise: Shimmering placeholder
        if (not self.pixmap or self.pixmap.isNull()) and self.is_loading:
            shimmer_grad = QLinearGradient(0, 0, w, h)
            shift = self.shimmer_pos
            shimmer_grad.setColorAt(max(0.0, shift - 0.2), QColor(25, 30, 40))
            shimmer_grad.setColorAt(shift, QColor(45, 55, 75))
            shimmer_grad.setColorAt(min(1.0, shift + 0.2), QColor(25, 30, 40))
            painter.fillRect(self.rect(), shimmer_grad)

        # Resim yüklüyse: En-boy oranı kilitli çiz
        if self.pixmap and not self.pixmap.isNull():
            aspect = self.orig_w / max(1, self.orig_h)
            canvas_aspect = w / max(1, h)

            if canvas_aspect > aspect:
                target_h = h
                target_w = int(round(h * aspect))
            else:
                target_w = w
                target_h = int(round(w / aspect))

            target_x = (w - target_w) // 2
            target_y = (h - target_h) // 2
            target_rect = QRect(target_x, target_y, target_w, target_h)

            painter.drawPixmap(target_rect, self.pixmap)

            # Yükleme esnasında resim üzerinde hafif parıltılı gölge efekti
            if self.is_loading:
                painter.fillRect(target_rect, QColor(0, 0, 0, 45))

        # Sağ üst köşeye durum rozeti veya dönen spinner çiz
        if self.is_loading:
            text = self.loading_text or t("preview_calculating", self.lang)
            font = QFont(self.font().family(), 10, QFont.Weight.Bold)
            painter.setFont(font)
            fm = painter.fontMetrics()
            tw = fm.horizontalAdvance(text) + 44
            th = fm.height() + 14

            bx = w - tw - 16
            by = 16
            badge_rect = QRect(bx, by, tw, th)

            painter.setPen(QPen(QColor(56, 189, 248, 200), 1.5))
            painter.setBrush(QColor(15, 23, 42, 235))
            painter.drawRoundedRect(badge_rect, 7, 7)

            # Dönen animasyonlu spinner çemberi
            spinner_cx = bx + 20
            spinner_cy = by + th // 2
            sr = 7
            s_rect = QRectF(spinner_cx - sr, spinner_cy - sr, sr * 2, sr * 2)

            pen_bg = QPen(QColor(255, 255, 255, 40), 2.2)
            pen_bg.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen_bg)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(s_rect)

            pen_active = QPen(QColor("#38bdf8"), 2.2)
            pen_active.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen_active)
            painter.drawArc(s_rect, int(-self.spinner_angle * 16), int(260 * 16))

            # Metin
            painter.setPen(QColor("#f8fafc"))
            text_rect = QRect(bx + 34, by, tw - 38, th)
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text)

        elif self.badge_text:
            font = QFont(self.font().family(), 10, QFont.Weight.Bold)
            painter.setFont(font)
            fm = painter.fontMetrics()
            tw = fm.horizontalAdvance(self.badge_text) + 24
            th = fm.height() + 12

            bx = w - tw - 16
            by = 16
            badge_rect = QRect(bx, by, tw, th)

            if self.is_original:
                bg = QColor(33, 150, 243, 230)
                border = QColor(144, 202, 249, 255)
            else:
                bg = QColor(16, 160, 115, 230)
                border = QColor(110, 231, 183, 255)

            painter.setPen(QPen(border, 1.5))
            painter.setBrush(bg)
            painter.drawRoundedRect(badge_rect, 6, 6)

            painter.setPen(QColor(255, 255, 255))
            painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, self.badge_text)


# ================= Arka Plan Async Kodlama Worker =================
class _RecompressWorker(QThread):
    finished_recompress = pyqtSignal(int, bytes, int, int, QImage)  # req_id, bytes, w, h, qimage
    failed_recompress = pyqtSignal(int, str)

    def __init__(self, req_id: int, pil_img: Image.Image, quality: int, max_edge: Optional[int], fmt: str):
        super().__init__()
        self.req_id = req_id
        self.pil_img = pil_img.copy()
        self.quality = quality
        self.max_edge = max_edge
        self.fmt = fmt.upper()
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    def run(self):
        try:
            if self._is_cancelled:
                return
            img = self.pil_img
            orig_w, orig_h = img.width, img.height

            # Upscaling guard: asla büyütme yapma
            if self.max_edge:
                ratio = min(self.max_edge / orig_w, self.max_edge / orig_h, 1.0)
                if ratio < 1.0:
                    new_w = max(1, int(round(orig_w * ratio)))
                    new_h = max(1, int(round(orig_h * ratio)))
                    img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)

            buf = io.BytesIO()
            has_alpha = False
            if img.mode in ("RGBA", "LA", "P"):
                try:
                    has_alpha = ImageCompressor.has_transparency(img)
                except Exception:
                    has_alpha = img.mode == "RGBA"

            qimg: Optional[QImage] = None

            if self.fmt == "WEBP":
                img.save(buf, format="WEBP", quality=self.quality, method=4)
                comp_bytes = buf.getvalue()
                qimg = QImage()
                qimg.loadFromData(comp_bytes)
            elif self.fmt == "AVIF":
                rgb_img = img.convert("RGB") if img.mode not in ("RGB", "RGBA") else img
                try:
                    rgb_img.save(buf, format="AVIF", quality=self.quality)
                    comp_bytes = buf.getvalue()
                    dec = Image.open(io.BytesIO(comp_bytes))
                    dec_rgb = dec.convert("RGBA")
                    data = dec_rgb.tobytes("raw", "RGBA")
                    qimg = QImage(data, dec_rgb.width, dec_rgb.height, QImage.Format.Format_RGBA8888).copy()
                except Exception:
                    buf = io.BytesIO()
                    img.save(buf, format="WEBP", quality=self.quality, method=4)
                    comp_bytes = buf.getvalue()
                    qimg = QImage()
                    qimg.loadFromData(comp_bytes)
            elif self.fmt == "JXL":
                try:
                    import numpy as np
                    if imagecodecs is not None:
                        rgb_img = img.convert("RGB") if img.mode not in ("RGB", "RGBA") else img
                        arr = np.array(rgb_img)
                        jxl_bytes = imagecodecs.jpegxl_encode(arr, level=self.quality, effort=7)
                        comp_bytes = jxl_bytes
                        dec_arr = imagecodecs.jpegxl_decode(jxl_bytes)
                        dec = Image.fromarray(dec_arr).convert("RGBA")
                        data = dec.tobytes("raw", "RGBA")
                        qimg = QImage(data, dec.width, dec.height, QImage.Format.Format_RGBA8888).copy()
                    else:
                        raise RuntimeError("imagecodecs not available")
                except Exception:
                    buf = io.BytesIO()
                    img.save(buf, format="WEBP", quality=self.quality, method=4)
                    comp_bytes = buf.getvalue()
                    qimg = QImage()
                    qimg.loadFromData(comp_bytes)
            else:  # JPEG
                if has_alpha:
                    img.save(buf, format="WEBP", quality=self.quality, method=4)
                else:
                    if img.mode != "RGB":
                        img = img.convert("RGB")
                    img.save(buf, format="JPEG", quality=self.quality, optimize=True)
                comp_bytes = buf.getvalue()
                qimg = QImage()
                qimg.loadFromData(comp_bytes)

            if self._is_cancelled:
                return
            self.finished_recompress.emit(self.req_id, comp_bytes, img.width, img.height, qimg)
        except Exception as e:
            if not self._is_cancelled:
                self.failed_recompress.emit(self.req_id, str(e))


# ================= Arka Plan Video Kare Ayıklama Worker =================
class _ExtractFrameWorker(QThread):
    frame_ready = pyqtSignal(int, bytes, float)  # req_id, png_bytes, seconds
    frame_failed = pyqtSignal(int, str)

    def __init__(self, req_id: int, file_path: str, seconds: float):
        super().__init__()
        self.req_id = req_id
        self.file_path = file_path
        self.seconds = max(0.0, seconds)
        self._is_cancelled = False
        self._proc = None

    def cancel(self):
        self._is_cancelled = True
        if self._proc:
            kill_process_tree(self._proc)

    def run(self):
        try:
            if self._is_cancelled:
                return
            ff_path = FFmpegManager().find()
            if not ff_path:
                # Eskiden "ffmpeg" göreli adına düşülüyordu (CWD'den çalıştırma riski).
                self.frame_failed.emit(self.req_id, "FFmpeg bulunamadı")
                return
            cmd = build_frame_extract_cmd(ff_path, self.file_path, self.seconds)
            self._proc = popen_hidden(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, kill_on_parent_exit=True,
            )
            try:
                out, _ = self._proc.communicate(timeout=6)
            except Exception:
                try:
                    if self._proc:
                        kill_process_tree(self._proc)
                        out, _ = self._proc.communicate()
                    else:
                        out = None
                except Exception:
                    out = None

            if self._is_cancelled:
                return
            if out:
                self.frame_ready.emit(self.req_id, out, self.seconds)
            else:
                self.frame_failed.emit(self.req_id, "Kare ayıklanamadı")
        except Exception as e:
            if not self._is_cancelled:
                self.frame_failed.emit(self.req_id, str(e))


class PreviewDialog(ChromeDialog):
    """Canlı Kalite Önizleme ve Anlık Karşılaştırma Penceresi."""

    settings_applied = pyqtSignal(int, str, bool)  # quality, resolution value, is_video

    def __init__(
        self,
        file_path: Optional[str] = None,
        initial_quality: int = 80,
        initial_res: str = "2400px",
        parent=None,
        lang: str = "tr",
    ):
        super().__init__(parent, resizable=True)
        self.lang = lang
        self.file_path: Optional[str] = file_path
        self._is_video: bool = bool(file_path and Path(file_path).suffix.lower() in VIDEO_EXTS)
        self._initial_quality = initial_quality
        self._initial_res = initial_res or ("1080p" if self._is_video else "2400px")

        self._pil_img: Optional[Image.Image] = None
        self._orig_size_bytes: int = 0
        self._orig_dims: tuple[int, int] = (0, 0)
        self._orig_pixmap: Optional[QPixmap] = None

        self._comp_bytes: bytes = b""
        self._comp_dims: tuple[int, int] = (0, 0)
        self._comp_pixmap: Optional[QPixmap] = None

        self._video_file_size: int = 0
        self._ref_frame_bytes: int = 0
        self._video_timestamp: float = 1.0

        self._is_holding_original: bool = False
        self._is_toggle_original: bool = False

        # Asenkron worker yöneticileri ve sayaçları
        self._recomp_req_id: int = 0
        self._recomp_worker: Optional[_RecompressWorker] = None

        self._frame_req_id: int = 0
        self._frame_worker: Optional[_ExtractFrameWorker] = None
        self._active_workers: set[QThread] = set()
        self._last_res_text: str = self._initial_res

        # Debounce timer for smooth slider dragging
        self._slider_timer = QTimer(self)
        self._slider_timer.setSingleShot(True)
        self._slider_timer.setInterval(40)
        self._slider_timer.timeout.connect(self._recompress_async)

        # Video hızlı sarma debounce timer
        self._frame_debounce_timer = QTimer(self)
        self._frame_debounce_timer.setSingleShot(True)
        self._frame_debounce_timer.setInterval(70)
        self._frame_debounce_timer.timeout.connect(self._launch_frame_extraction)

        # Büyütme/geri alma ve kenardan boyutlandırma ChromeDialog'dan gelir (resizable=True)
        self.setWindowTitle(t("preview_dialog_title", self.lang))
        self.resize(1020, 720)
        self.setMinimumSize(780, 520)

        # Tuş yakalama için güçlü odak politikası ve eventFilter
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.installEventFilter(self)

        self._build_ui()

        if self.file_path and os.path.isfile(self.file_path):
            self.load_image(self.file_path)
        else:
            self._update_picker_buttons()
            self._update_stats()

    def _build_ui(self):
        main_layout = QVBoxLayout(self.body_host)
        main_layout.setContentsMargins(16, 14, 16, 14)
        main_layout.setSpacing(10)

        # Üst Bilgi Başlığı ve Butonlar
        top_bar = QHBoxLayout()
        top_bar.setSpacing(10)

        self.info_header = QLabel(t("preview_hint", self.lang))
        self.info_header.setObjectName("hint_label")
        self.info_header.setStyleSheet("font-size: 13px; font-weight: bold;")
        top_bar.addWidget(self.info_header, 1)

        # Video Kare Seçici (Sadece video yüklendiğinde görünür)
        self.frame_box = QFrame()
        self.frame_box.setObjectName("frame_box")  # styled by id in the theme sheet (a bare sheet here cascaded to the buttons)
        fb_l = QHBoxLayout(self.frame_box)
        fb_l.setContentsMargins(4, 2, 4, 2)
        fb_l.setSpacing(4)
        self.frame_caption = QLabel(t("preview_frame_label", self.lang))
        fb_l.addWidget(self.frame_caption)

        self.btn_prev_frame = QPushButton("◀ -1s")
        self.btn_prev_frame.setProperty("class", "ghost-mini")
        self.btn_prev_frame.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_prev_frame.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_prev_frame.clicked.connect(lambda: self._step_video_frame(-1.0))
        fb_l.addWidget(self.btn_prev_frame)

        self.frame_time_label = QLabel("00:01")
        self.frame_time_label.setStyleSheet("font-weight: bold; min-width: 44px;")
        self.frame_time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        fb_l.addWidget(self.frame_time_label)

        self.btn_next_frame = QPushButton("+1s ▶")
        self.btn_next_frame.setProperty("class", "ghost-mini")
        self.btn_next_frame.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_next_frame.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_next_frame.clicked.connect(lambda: self._step_video_frame(1.0))
        fb_l.addWidget(self.btn_next_frame)

        self.frame_box.hide()
        top_bar.addWidget(self.frame_box)

        # Akıllı Video Seç Butonu (Solda)
        self.pick_vid_btn = QPushButton(t("preview_pick_video", self.lang))
        self.pick_vid_btn.setIconSize(QSize(16, 16))
        self.pick_vid_btn.setProperty("class", "ghost-mini")
        self.pick_vid_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.pick_vid_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.pick_vid_btn.clicked.connect(self._browse_video)
        top_bar.addWidget(self.pick_vid_btn)

        # Akıllı Resim Seç Butonu (Sağda)
        self.pick_img_btn = QPushButton(t("preview_pick_image", self.lang))
        self.pick_img_btn.setIconSize(QSize(16, 16))
        self.pick_img_btn.setProperty("class", "ghost-mini")
        self.pick_img_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.pick_img_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.pick_img_btn.clicked.connect(self._browse_image)
        top_bar.addWidget(self.pick_img_btn)

        main_layout.addLayout(top_bar)

        # Kontrol Çubuğu (Kalite Slider, Çözünürlük, Format, Karşılaştır Butonu)
        controls_frame = QFrame()
        controls_frame.setObjectName("control_bar")
        ctrl_l = QHBoxLayout(controls_frame)
        ctrl_l.setContentsMargins(10, 6, 10, 6)
        ctrl_l.setSpacing(12)

        # Kalite Slider
        self.quality_title = QLabel(t("preview_quality_label", self.lang).format(self._initial_quality))
        self.quality_title.setStyleSheet("font-weight: bold; min-width: 85px;")
        ctrl_l.addWidget(self.quality_title)

        self.quality_slider = QSlider(Qt.Orientation.Horizontal)
        self.quality_slider.setRange(10, 100)
        self.quality_slider.setValue(self._initial_quality if self._initial_quality is not None else 80)
        self.quality_slider.setSingleStep(1)
        self.quality_slider.setPageStep(5)
        self.quality_slider.setCursor(Qt.CursorShape.PointingHandCursor)
        self.quality_slider.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.quality_slider.valueChanged.connect(self._on_quality_change)
        ctrl_l.addWidget(self.quality_slider, 1)

        # Maksimum Çözünürlük Seçici
        self.res_label = QLabel(t("preview_res_label", self.lang))
        ctrl_l.addWidget(self.res_label)

        self.res_combo = QComboBox()
        self.res_combo.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.res_combo.activated.connect(self._on_res_activated)
        self.res_combo.setToolTip(t("image_res_tip", self.lang))
        ctrl_l.addWidget(self.res_combo)

        # Format Seçici (JPEG varsayılan, WebP, AVIF, JXL)
        self.format_lbl = QLabel(t("preview_format_label", self.lang))
        ctrl_l.addWidget(self.format_lbl)
        self.format_combo = QComboBox()
        self.format_combo.addItems(["JPEG", "WebP", "AVIF", "JXL"])
        self.format_combo.setCurrentText("JPEG")
        self.format_combo.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.format_combo.setToolTip(t("preview_format_tip", self.lang))
        self.format_combo.currentIndexChanged.connect(self._on_format_change)
        ctrl_l.addWidget(self.format_combo)

        self._sync_res_combo_mode()
        if self._is_video:
            self.format_lbl.hide()
            self.format_combo.hide()

        # Karşılaştırma / Orijinal Butonu
        self.toggle_btn = QPushButton(t("preview_toggle_btn", self.lang))
        self.toggle_btn.setIconSize(QSize(16, 16))
        self.toggle_btn.setProperty("class", "primary")
        self.toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.toggle_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.toggle_btn.setToolTip(t("preview_toggle_tip", self.lang))
        self.toggle_btn.pressed.connect(lambda: self._set_hold_original(True))
        self.toggle_btn.released.connect(lambda: self._set_hold_original(False))
        ctrl_l.addWidget(self.toggle_btn)

        main_layout.addWidget(controls_frame)

        # Resim Tuvali (Scroll Area içinde)
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.scroll_area.setObjectName("preview_scroll")
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_area.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self.canvas = _ImageCanvas(self)
        self.canvas.lang = self.lang
        self.scroll_area.setWidget(self.canvas)
        main_layout.addWidget(self.scroll_area, 1)

        # Alt Bilgi ve Buton Çubuğu
        bottom_bar = QHBoxLayout()
        bottom_bar.setSpacing(12)

        self.stats_label = QLabel()
        self.stats_label.setObjectName("hint_label")
        self.stats_label.setStyleSheet("font-size: 12px; font-weight: bold;")
        bottom_bar.addWidget(self.stats_label, 1)

        self.apply_btn = QPushButton(t("preview_apply_btn", self.lang))
        self.apply_btn.setProperty("class", "primary")
        self.apply_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.apply_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.apply_btn.clicked.connect(self._apply_settings)
        bottom_bar.addWidget(self.apply_btn)

        self.save_btn = QPushButton(t("preview_save_btn", self.lang))
        self.save_btn.setProperty("class", "ghost")
        self.save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.save_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.save_btn.clicked.connect(self._save_preview_file)
        bottom_bar.addWidget(self.save_btn)

        self.close_btn = QPushButton(t("cancel", self.lang))
        self.close_btn.setProperty("class", "ghost")
        self.close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.close_btn.clicked.connect(self.reject)
        bottom_bar.addWidget(self.close_btn)

        main_layout.addLayout(bottom_bar)
        self._apply_icons()

    def _sync_res_combo_mode(self):
        if not hasattr(self, "res_combo"):
            return
        current = res_value(self.res_combo) if self.res_combo.count() > 0 else getattr(self, "_initial_res", "")
        self.res_combo.blockSignals(True)
        self.res_combo.clear()
        if self._is_video:
            keys = list(PREVIEW_VIDEO_RES.keys())
            self.res_combo.addItems(keys + [t("custom_option", self.lang)])
            self.res_combo.setItemData(self.res_combo.count() - 1, CUSTOM_RES, Qt.ItemDataRole.UserRole)
            mark_original(self.res_combo, t("res_original", self.lang))
            if current in keys:
                select_res(self.res_combo, current)
            elif current and ("px" in current or "p" in current):
                self.res_combo.insertItem(max(0, self.res_combo.count() - 1), current)
                select_res(self.res_combo, current)
            else:
                select_res(self.res_combo, "1080p")
        else:
            keys = list(PREVIEW_IMAGE_RES.keys())
            self.res_combo.addItems(keys + [t("custom_option", self.lang)])
            self.res_combo.setItemData(self.res_combo.count() - 1, CUSTOM_RES, Qt.ItemDataRole.UserRole)
            mark_original(self.res_combo, t("res_original", self.lang))
            if current in keys:
                select_res(self.res_combo, current)
            elif current and current.endswith("px"):
                self.res_combo.insertItem(max(0, self.res_combo.count() - 1), current)
                select_res(self.res_combo, current)
            else:
                select_res(self.res_combo, "2400px")
        self._last_res_text = res_value(self.res_combo)
        self.res_combo.blockSignals(False)

    def _apply_icons(self) -> None:
        """Düğme simgeleri (emoji yerine vektör) seçilen vurguya uyar."""
        color = icons.accent_color_for(self._pal)
        self.pick_vid_btn.setIcon(icons.film_icon(color))
        self.pick_img_btn.setIcon(icons.image_icon(color))
        self.toggle_btn.setIcon(icons.eye_icon("#ffffff"))  # birincil (vurgu dolgulu) düğme: beyaz simge

    def _palette_refreshed(self) -> None:
        self._apply_icons()

    def _update_picker_buttons(self):
        """Kullanıcının seçili medyasına göre buton metinlerini dinamik günceller."""
        image = t("preview_pick_image", self.lang)
        other_image = t("preview_change_img", self.lang)
        video = t("preview_pick_video", self.lang)
        other_video = t("preview_pick_other_video", self.lang)
        if not self.file_path:
            self.pick_img_btn.setText(image)
            self.pick_vid_btn.setText(video)
        elif self._is_video:
            self.pick_img_btn.setText(image)
            self.pick_vid_btn.setText(other_video)
        else:
            self.pick_img_btn.setText(other_image)
            self.pick_vid_btn.setText(video)
        # nothing to adjust, apply or save until a file is loaded
        has_file = bool(self.file_path)
        for control in (self.quality_slider, self.res_combo, self.format_combo, self.apply_btn, self.save_btn, self.toggle_btn):
            control.setEnabled(has_file)

    def load_image(self, path: str):
        """Yeni bir resim veya video dosyasını yükler ve in-memory sıkıştırma başlatır."""
        if not path or not os.path.isfile(path):
            self.file_path = None
            self._pil_img = None
            self._orig_pixmap = None
            self._comp_pixmap = None
            self._comp_bytes = b""
            self.canvas.set_image(None, False, "")
            self._update_picker_buttons()
            self._update_stats()
            return

        self.file_path = path
        ext = Path(path).suffix.lower()

        if ext in VIDEO_EXTS:
            self._is_video = True
            self._video_file_size = os.path.getsize(path)
            self._orig_size_bytes = self._video_file_size
            self.frame_box.show()
            if hasattr(self, "format_lbl"):
                self.format_lbl.hide()
            if hasattr(self, "format_combo"):
                self.format_combo.hide()
            self._video_timestamp = 1.0
            self._sync_res_combo_mode()
            self._update_picker_buttons()
            self._step_video_frame(0.0)
        else:
            self._is_video = False
            self.frame_box.hide()
            if hasattr(self, "format_lbl"):
                self.format_lbl.show()
            if hasattr(self, "format_combo"):
                self.format_combo.show()
            self._sync_res_combo_mode()
            self._orig_size_bytes = os.path.getsize(path)
            try:
                raw = Image.open(path)
                raw = ImageOps.exif_transpose(raw)
                self._pil_img = raw
                self._orig_dims = (raw.width, raw.height)
                self.canvas.set_reference_dimensions(raw.width, raw.height)
                self._orig_pixmap = QPixmap.fromImage(self._pil_to_qimage(raw))
                self._update_picker_buttons()
                self._recompress_async()
            except Exception as e:
                MessageBox.warning(self, t("preview_error_title", self.lang), t("preview_open_failed", self.lang).format(e))
                self.file_path = None
                self._update_picker_buttons()

        self.setFocus()

    def _pil_to_qimage(self, img: Image.Image) -> QImage:
        """PIL Image nesnesini QImage formatına dönüştürür."""
        rgb_img = img.convert("RGBA")
        data = rgb_img.tobytes("raw", "RGBA")
        return QImage(data, rgb_img.width, rgb_img.height, QImage.Format.Format_RGBA8888).copy()

    def _step_video_frame(self, delta: float):
        """Video karesini delta kadar ileri/geri alır (Anında tepki, async yükleme)."""
        if not self._is_video or not self.file_path:
            return

        self._video_timestamp = max(0.0, self._video_timestamp + delta)
        mins = int(self._video_timestamp // 60)
        secs = int(self._video_timestamp % 60)
        self.frame_time_label.setText(f"{mins:02d}:{secs:02d}")

        self._frame_req_id += 1
        self.canvas.set_loading(True, t("preview_loading_frame", self.lang).format(time=f"{mins:02d}:{secs:02d}"))

        # Hızlı art arda tıklamalar için debounce
        self._frame_debounce_timer.start()

    def _launch_frame_extraction(self):
        if not self._is_video or not self.file_path:
            return

        req_id = self._frame_req_id
        if self._frame_worker is not None:
            try:
                if not sip.isdeleted(self._frame_worker) and self._frame_worker.isRunning():
                    self._frame_worker.cancel()
                    try:
                        self._frame_worker.frame_ready.disconnect()
                        self._frame_worker.frame_failed.disconnect()
                    except Exception:
                        pass
            except Exception:
                pass
            self._frame_worker = None

        worker = _ExtractFrameWorker(req_id, self.file_path, self._video_timestamp)
        self._frame_worker = worker
        self._active_workers.add(worker)
        worker.frame_ready.connect(self._on_frame_ready)
        worker.frame_failed.connect(self._on_frame_failed)

        def _cleanup_frame(w=worker):
            self._active_workers.discard(w)
            if self._frame_worker is w:
                self._frame_worker = None
            try:
                if not sip.isdeleted(w):
                    w.deleteLater()
            except Exception:
                pass

        worker.finished.connect(_cleanup_frame)
        worker.start()

    def _on_frame_ready(self, req_id: int, png_bytes: bytes, seconds: float):
        if req_id != self._frame_req_id:
            return
        try:
            raw = Image.open(io.BytesIO(png_bytes))
            self._ref_frame_bytes = len(png_bytes)
            self._pil_img = raw
            self._orig_dims = (raw.width, raw.height)
            self.canvas.set_reference_dimensions(raw.width, raw.height)
            self._orig_pixmap = QPixmap.fromImage(self._pil_to_qimage(raw))
            self.canvas.set_loading(False)
            self._recompress_async()
        except Exception:
            self.canvas.set_loading(False)

    def _on_frame_failed(self, req_id: int, msg: str):
        if req_id == self._frame_req_id:
            self.canvas.set_loading(False)
            self.stats_label.setText(t("preview_frame_failed", self.lang))

    def _browse_image(self):
        filters = (
            f"{t('preview_filter_images', self.lang)} (*.jpg *.jpeg *.png *.webp *.heic *.heif *.avif *.jxl);;"
            f"{t('preview_filter_all', self.lang)} (*.*)"
        )
        path, _ = QFileDialog.getOpenFileName(self, t("choose_file", self.lang), "", filters)
        if path:
            self.load_image(path)
        self.setFocus()

    def _browse_video(self):
        filters = (
            f"{t('preview_filter_videos', self.lang)} (*.mov *.mp4 *.mkv *.avi *.m4v *.webm);;"
            f"{t('preview_filter_all', self.lang)} (*.*)"
        )
        path, _ = QFileDialog.getOpenFileName(self, t("choose_file", self.lang), "", filters)
        if path:
            self.load_image(path)
        self.setFocus()

    def _on_quality_change(self, value: int):
        self.quality_title.setText(t("preview_quality_label", self.lang).format(value))
        self._slider_timer.start()

    def _on_res_activated(self, index: int):
        text = res_value(self.res_combo, index)
        if self.res_combo.itemData(index, Qt.ItemDataRole.UserRole) == CUSTOM_RES:
            if self._is_video:
                prev_val = 1920
                try:
                    if hasattr(self, "_last_res_text") and self._last_res_text:
                        clean = self._last_res_text.replace("px", "").replace("p", "").strip()
                        prev_val = int(clean)
                except Exception:
                    pass
                val, ok = InputDialog.getInt(
                    self,
                    t("custom_res_title_video", self.lang),
                    t("custom_res_prompt_video", self.lang),
                    value=prev_val,
                    min=240,
                    max=7680,
                    step=10,
                )
                if ok and val > 0:
                    custom_label = f"{val}px"
                    PREVIEW_VIDEO_RES[custom_label] = val
                    idx = self.res_combo.findText(custom_label)
                    if idx < 0:
                        insert_pos = max(0, self.res_combo.count() - 1)
                        self.res_combo.insertItem(insert_pos, custom_label)
                        idx = insert_pos
                    self.res_combo.setCurrentIndex(idx)
                    self._last_res_text = custom_label
                else:
                    prev_idx = find_res(self.res_combo, self._last_res_text)
                    self.res_combo.setCurrentIndex(prev_idx if prev_idx >= 0 else 0)
                    return
            else:
                prev_val = 2400
                try:
                    if hasattr(self, "_last_res_text") and self._last_res_text and self._last_res_text.endswith("px"):
                        prev_val = int(self._last_res_text.replace("px", ""))
                except Exception:
                    pass
                val, ok = InputDialog.getInt(
                    self,
                    t("custom_res_title_image", self.lang),
                    t("custom_res_prompt_image", self.lang),
                    value=prev_val,
                    min=100,
                    max=10000,
                    step=50,
                )
                if ok and val > 0:
                    custom_label = f"{val}px"
                    PREVIEW_IMAGE_RES[custom_label] = val
                    idx = self.res_combo.findText(custom_label)
                    if idx < 0:
                        insert_pos = max(0, self.res_combo.count() - 1)
                        self.res_combo.insertItem(insert_pos, custom_label)
                        idx = insert_pos
                    self.res_combo.setCurrentIndex(idx)
                    self._last_res_text = custom_label
                else:
                    prev_idx = find_res(self.res_combo, self._last_res_text)
                    self.res_combo.setCurrentIndex(prev_idx if prev_idx >= 0 else 0)
                    return
        else:
            self._last_res_text = text

        self._slider_timer.start()

    def _on_format_change(self):
        self._slider_timer.start()

    def _recompress_async(self):
        """Arka planda Pillow / imagecodecs ile sıkıştırır (Asenkron, GUI donmaz)."""
        if not self._pil_img:
            self.canvas.set_loading(False)
            return

        quality = self.quality_slider.value()
        res_key = res_value(self.res_combo)
        max_edge = _parse_res_value(res_key)
        fmt = self.format_combo.currentText().upper() if not self._is_video else "JPEG"

        self._recomp_req_id += 1
        req_id = self._recomp_req_id

        if self._is_video:
            self.canvas.set_loading(True, t("preview_calculating_frame", self.lang))
        else:
            self.canvas.set_loading(True, t("preview_calculating_fmt", self.lang).format(fmt=fmt))

        if self._recomp_worker is not None:
            try:
                if not sip.isdeleted(self._recomp_worker) and self._recomp_worker.isRunning():
                    self._recomp_worker.cancel()
                    try:
                        self._recomp_worker.finished_recompress.disconnect()
                        self._recomp_worker.failed_recompress.disconnect()
                    except Exception:
                        pass
            except Exception:
                pass
            self._recomp_worker = None

        worker = _RecompressWorker(req_id, self._pil_img, quality, max_edge, fmt)
        self._recomp_worker = worker
        self._active_workers.add(worker)
        worker.finished_recompress.connect(self._on_recompress_done)
        worker.failed_recompress.connect(self._on_recompress_failed)

        def _cleanup_recomp(w=worker):
            self._active_workers.discard(w)
            if self._recomp_worker is w:
                self._recomp_worker = None
            try:
                if not sip.isdeleted(w):
                    w.deleteLater()
            except Exception:
                pass

        worker.finished.connect(_cleanup_recomp)
        worker.start()

    def _on_recompress_done(self, req_id: int, comp_bytes: bytes, w: int, h: int, qimg: QImage):
        if req_id != self._recomp_req_id:
            return
        self._comp_bytes = comp_bytes
        self._comp_dims = (w, h)
        if qimg and not qimg.isNull():
            self._comp_pixmap = QPixmap.fromImage(qimg)
        self.canvas.set_loading(False)
        self._update_display()
        self._update_stats()

    def _on_recompress_failed(self, req_id: int, err: str):
        if req_id == self._recomp_req_id:
            self.canvas.set_loading(False)

    def _is_showing_original(self) -> bool:
        return self._is_holding_original or self._is_toggle_original

    def _set_hold_original(self, hold: bool):
        if self._is_holding_original != hold:
            self._is_holding_original = hold
            self._update_display()

    def _update_display(self):
        if not self._orig_pixmap:
            self.canvas.set_image(None, False, "")
            return

        show_orig = self._is_showing_original()
        if show_orig:
            badge = t("preview_badge_orig", self.lang)
            self.canvas.set_image(self._orig_pixmap, is_original=True, badge_text=badge)
        else:
            if self._is_video:
                savings = 0.0
                if self._ref_frame_bytes > 0 and self._comp_bytes:
                    savings = max(0.0, (1.0 - len(self._comp_bytes) / self._ref_frame_bytes) * 100.0)
                badge = f"{t('preview_badge_frame', self.lang)} (-%{savings:.0f})"
            else:
                fmt = self.format_combo.currentText()
                savings = 0.0
                if self._orig_size_bytes > 0 and self._comp_bytes:
                    savings = max(0.0, (1.0 - len(self._comp_bytes) / self._orig_size_bytes) * 100.0)
                badge = f"{fmt} {t('preview_badge_comp', self.lang)} (-%{savings:.0f})"
            self.canvas.set_image(self._comp_pixmap or self._orig_pixmap, is_original=False, badge_text=badge)

    def _update_stats(self):
        if not self._orig_pixmap:
            self.stats_label.setText(t("preview_no_file", self.lang))
            return

        comp_str = format_bytes(len(self._comp_bytes))
        comp_dim_str = f"{self._comp_dims[0]}×{self._comp_dims[1]}"

        orig_ext = Path(self.file_path).suffix.lstrip(".").upper() if self.file_path else ""
        if self._is_video:
            orig_vid_str = format_bytes(self._video_file_size)
            ref_frame_str = format_bytes(self._ref_frame_bytes) if self._ref_frame_bytes > 0 else "—"
            savings = 0.0
            if self._ref_frame_bytes > 0 and self._comp_bytes:
                savings = max(0.0, (1.0 - len(self._comp_bytes) / self._ref_frame_bytes) * 100.0)

            orig_dim_str = f"{self._orig_dims[0]}×{self._orig_dims[1]}"
            lbl_video = t("preview_lbl_video", self.lang)
            lbl_orig_frame = t("preview_lbl_orig_frame", self.lang)
            vid_label = f"{lbl_video} ({orig_ext})" if orig_ext else lbl_video
            orig_frame_label = f"{lbl_orig_frame} ({orig_ext})" if orig_ext else lbl_orig_frame
            txt = (
                f"{vid_label}: {orig_vid_str} ({orig_dim_str})  |  "
                f"{orig_frame_label}: {ref_frame_str}  →  {t('preview_lbl_comp_frame', self.lang)}: {comp_str} ({comp_dim_str})  |  "
                f"{t('preview_lbl_frame_savings', self.lang)}: %{savings:.1f}"
            )
        else:
            fmt = self.format_combo.currentText()
            orig_str = format_bytes(self._orig_size_bytes)
            savings = max(0.0, (1.0 - len(self._comp_bytes) / max(1, self._orig_size_bytes)) * 100.0)
            orig_dim_str = f"{self._orig_dims[0]}×{self._orig_dims[1]}"
            lbl_orig = t("preview_lbl_orig", self.lang)
            orig_label = f"{lbl_orig} ({orig_ext})" if orig_ext else lbl_orig
            txt = (
                f"{orig_label}: {orig_str} ({orig_dim_str})  →  "
                f"{fmt}: {comp_str} ({comp_dim_str})  |  "
                f"{t('preview_lbl_savings', self.lang)}: %{savings:.1f}"
            )

        self.stats_label.setText(txt)

    def _apply_settings(self):
        """Kullanıcının belirlediği kalite ve çözünürlüğü ana pencereye aktarır."""
        quality = self.quality_slider.value()
        res_key = res_value(self.res_combo)
        self.settings_applied.emit(quality, res_key, self._is_video)
        self.accept()

    def _save_preview_file(self):
        """Sıkıştırılmış önizlemeyi doğrudan dosya olarak kaydeder."""
        if not self._comp_bytes:
            return
        orig_p = Path(self.file_path) if self.file_path else Path("preview.jpg")
        fmt = self.format_combo.currentText().lower()
        ext_map = {"jpeg": "jpg", "webp": "webp", "avif": "avif", "jxl": "jxl"}
        ext = ext_map.get(fmt, "jpg")
        default_name = f"{orig_p.stem}_compressed.{ext}"
        save_path, _ = QFileDialog.getSaveFileName(
            self, t("preview_save_btn", self.lang), default_name, f"{fmt.upper()} (*.{ext});;{t('preview_filter_all', self.lang)} (*.*)"
        )
        if save_path:
            try:
                with open(save_path, "wb") as f:
                    f.write(self._comp_bytes)
                MessageBox.information(self, t("preview_saved_title", self.lang), t("preview_saved_text", self.lang).format(save_path))
            except Exception as e:
                MessageBox.warning(self, t("preview_error_title", self.lang), t("preview_save_failed", self.lang).format(e))
        self.setFocus()

    # ================= Boşluk (Space) Karşılaştırma Tuşu (Sadece Space) =================
    def eventFilter(self, obj, event):
        """Boşluk tuşunun herhangi bir buton tarafından tetiklenmesini engeller ve orijinali gösterir."""
        if event.type() == QEvent.Type.KeyPress:
            if event.key() == Qt.Key.Key_Space and not event.isAutoRepeat():
                self._set_hold_original(True)
                return True
        elif event.type() == QEvent.Type.KeyRelease:
            if event.key() == Qt.Key.Key_Space and not event.isAutoRepeat():
                self._set_hold_original(False)
                return True
        return super().eventFilter(obj, event)

    def keyPressEvent(self, event):
        if not event.isAutoRepeat() and event.key() == Qt.Key.Key_Space:
            self._set_hold_original(True)
            event.accept()
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if not event.isAutoRepeat() and event.key() == Qt.Key.Key_Space:
            self._set_hold_original(False)
            event.accept()
            return
        super().keyReleaseEvent(event)

    def closeEvent(self, event):
        self._slider_timer.stop()
        self._frame_debounce_timer.stop()
        for w in list(self._active_workers):
            try:
                if not sip.isdeleted(w):
                    if hasattr(w, "cancel"):
                        w.cancel()
                    w.wait(200)
            except Exception:
                pass
        self._active_workers.clear()
        self._frame_worker = None
        self._recomp_worker = None
        super().closeEvent(event)
