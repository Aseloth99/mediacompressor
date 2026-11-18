"""Ana pencere — bırak, profil, başlat."""

from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

from PyQt6.QtCore import QCoreApplication, QEvent, QSize, Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices, QIcon
from PyQt6.QtWidgets import (
    QApplication, QButtonGroup, QCheckBox, QComboBox, QDialog, QFileDialog, QFrame, QHBoxLayout,
    QLabel, QMainWindow, QProgressBar, QPushButton,
    QScrollArea, QSizeGrip, QSizePolicy, QSplitter, QTextEdit, QVBoxLayout, QWidget,
)

from ..core.app_info import APP_ID, APP_NAME, BITRATE_AUTO, CUSTOM_RES, VERSION, normalize_bitrate
from ..core.eta import JobEta, file_eta
from ..core.ffmpeg_manager import FFmpegManager
from ..core.gpu_detector import GpuDetector
from ..core.image_compressor import IMAGE_EXTS
from ..core.job_manager import JobWorker, collect_files
from ..core.video_compressor import VIDEO_EXTS, VideoCompressor
from ..core.workers import DaemonWorker, shutdown_workers
from ..utils.config import (
    Config, FILE_TYPE_ALL, FILE_TYPE_IMAGES, FILE_TYPE_VIDEOS, normalize_file_type,
)
from ..utils.helpers import (
    default_output_dir, format_bytes, format_duration, norm_path,
    resource_path, reveal_in_file_manager,
)
from ..utils.locales import AUTO_LANGUAGE, get_active_language, get_app_name, install_qt_translations, t
from ..utils.logger import log_error, log_info
from ..utils.theme_manager import DEFAULT_ACCENT, ThemeManager, fit_text_widgets
from ..utils import self_update
from ..utils.update_installer import normalize_checksum, should_install_pending, should_show_pending_update
from ..utils.notify import Notifier
from . import icons
from .about_dialog import AboutDialog
from .advanced_dialog import AdvancedDialog
from .drop_zone import DropZone
from .message_box import InputDialog, MessageBox, configure as configure_message_box
from .path_label import ElidedPathLabel
from .preview_dialog import PreviewDialog
from .queue_panel import QueuePanel, override_values, trim_fraction
from .settings_dialog import SettingsDialog
from .title_bar import TitleBar
from .trim_dialog import TrimDialog
from .tray import TrayIcon
from .res_combo import find_res, mark_original, res_value, select_res
from .update_dialog import UpdateDialog

# Kapanışta işçilerin iptal bayrağına yanıt vermesi için toplam bekleme (ms).
SHUTDOWN_WAIT_MS = 8000
# Genel ilerleme çubuğunun çözünürlüğü (iş payı binde bir adımlarla; yüzde olarak gösterilir).
OVERALL_STEPS = 1000

VIDEO_RES = {"720p": 1280, "1080p": 1920, "1440p": 2560, "Orijinal": None}
# Kalıcı seçimler: profile bağlı olanlar yalnızca "Özel" profilde geri yüklenir (diğer profiller kendi
# değerlerini kurar); hız, GPU, alt klasör, otomatik resim kalitesi ve ses kaldırma her zaman.
PROFILE_CHOICE_KEYS = ("codec", "bitrate", "crf", "video_res", "image_res", "audio_bitrate", "image_quality", "fps")
IMAGE_RES = {"1920px": 1920, "2400px": 2400, "3840px": 3840, "Orijinal": None}


def _parse_custom_res(text: str) -> int | None:
    if text == "Orijinal":
        return None
    if text in IMAGE_RES:
        return IMAGE_RES[text]
    digits = "".join(c for c in str(text) if c.isdigit())
    return int(digits) if digits else None


def _parse_video_res(text: str) -> int | None:
    if text == "Orijinal":
        return None
    if text in VIDEO_RES:
        return VIDEO_RES[text]
    digits = "".join(c for c in str(text) if c.isdigit())
    return int(digits) if digits else None

PROFILES = {
    "balanced": {
        "label": "Dengeli",
        "codec": "h264",
        "bitrate": BITRATE_AUTO,
        "video_res": "1080p",
        "image_res": "2400px",
        "image_quality": 80,
        "crf": 24,
        "audio": "128k",
    },
    "fast": {
        "label": "Hızlı Paylaşım",
        "codec": "h264",
        "bitrate": BITRATE_AUTO,
        "video_res": "1080p",
        "image_res": "1920px",
        "image_quality": 80,
        "crf": 26,
        "audio": "128k",
    },
    "quality": {
        "label": "Yüksek Kalite",
        "codec": "h264",
        "bitrate": BITRATE_AUTO,
        "video_res": "Orijinal",
        "image_res": "3840px",
        "image_quality": 90,
        "crf": 20,
        "audio": "192k",
    },
    "custom": {"label": "Özel"},
}

CODEC_KEYS = [
    ("h264", "codec_h264_desc"),
    ("hevc", "codec_hevc_desc"),
    ("av1", "codec_av1_desc"),
]
BITRATE_KEYS = [
    (BITRATE_AUTO, "bitrate_auto_desc"),
    ("1500k", "bitrate_1500k_desc"),
    ("2000k", "bitrate_2000k_desc"),
    ("2500k", "bitrate_2500k_desc"),
    ("4000k", "bitrate_4000k_desc"),
]

def _codec_labels(lang: str):
    return [(cid, t(key, lang)) for cid, key in CODEC_KEYS]

def _bitrate_labels(lang: str):
    return [(bid, t(key, lang)) for bid, key in BITRATE_KEYS]

FILE_TYPE_IDS = (FILE_TYPE_ALL, FILE_TYPE_IMAGES, FILE_TYPE_VIDEOS)
TYPE_LABEL_KEYS = {
    FILE_TYPE_ALL: "type_all",
    FILE_TYPE_IMAGES: "type_images",
    FILE_TYPE_VIDEOS: "type_videos",
}


class PrepareWorker(DaemonWorker):
    log = pyqtSignal(str)
    progress = pyqtSignal(float)
    done = pyqtSignal(object, object)  # ffmpeg manager, gpu detector
    failed = pyqtSignal(str)

    def __init__(self, manager: FFmpegManager, download: bool = False, lang: str = "tr"):
        super().__init__()
        self.manager = manager
        self.download = download
        self.lang = lang
        self.cancel_event = threading.Event()

    def stop(self):
        self.cancel_event.set()

    def run(self):
        try:
            path = self.manager.find()
            if not path and self.download:
                self.log.emit(t("log_ffmpeg_downloading", self.lang))
                path = self.manager.download(lambda p: self.progress.emit(p), cancel_event=self.cancel_event)
            gpu = None
            if path:
                self.log.emit(t("log_ffmpeg_ready", self.lang).format(path))
                gpu = GpuDetector(path).detect()
                gpu.compute_av1_routes()  # AV1 uyarısı için (sondajlar burada, arayüz iş parçacığında değil)
                self.log.emit("GPU: " + gpu.status_text())
            else:
                self.log.emit(self.manager.missing_hint(self.lang))
            self.done.emit(self.manager, gpu)
        except Exception as exc:
            log_error("Hazırlık hatası", exc)
            self.failed.emit(str(exc))


class DownloadThread(DaemonWorker):
    def __init__(self, installer, url, size, checksum):
        super().__init__()
        self.installer = installer
        self.url = url
        self.size = size
        self.checksum = checksum

    def stop(self):
        self.installer.cancel_download()

    def run(self):
        self.installer.download_update(self.url, self.size, self.checksum)


class _AutoHideLabel(QLabel):
    """A hint line that takes no room while it is empty."""

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self.setVisible(bool(text))

    def setText(self, text: str) -> None:
        super().setText(text)
        self.setVisible(bool(text))


class MainWindow(QMainWindow):
    raise_requested = pyqtSignal()

    def __init__(self, config: Config, theme: ThemeManager, updater, installer):
        super().__init__()
        self.config = config
        self.theme = theme
        self.updater = updater
        self.installer = installer
        self.ffmpeg = FFmpegManager()
        self.gpu: GpuDetector | None = None
        self.sources: list[str] = []
        self.skip_paths: set[str] = set()
        self.lang = get_active_language(self.config)
        install_qt_translations(self.lang)
        # Özel hata/bilgi/soru kutuları (ve içerik pencereleri) uygulamanın temasını, simgesini ve dilini buradan alır.
        configure_message_box(
            palette_provider=lambda: self.theme.get_palette(),
            app_icon_provider=lambda: self.windowIcon(),
            lang_provider=lambda: self.lang,
        )
        self.notifier = Notifier(
            APP_ID,
            tray_provider=lambda: self.tray,
            icon_provider=lambda: self.windowIcon(),
            enabled_provider=lambda: self.config.get("show_notifications", True),
        )
        try:  # follow Windows light/dark while the app is open (only matters when the theme is "system")
            QApplication.styleHints().colorSchemeChanged.connect(self._on_system_scheme_changed)
        except (AttributeError, TypeError):
            pass
        self.output_dir = default_output_dir(self.lang)
        self.output_manual = False
        self.worker: JobWorker | None = None
        self.prepare: PrepareWorker | None = None
        self._dl_thread: DownloadThread | None = None
        self.tray: TrayIcon | None = None
        self.update_dialog: UpdateDialog | None = None
        self._pending_update = None          # (sürüm, adres, notlar, zorunlu, boyut, sağlama toplamı): sunulmuş, kurulmamış
        self._auto_update_timer = None
        self._pending_install = None         # indirilmiş paket: sıkıştırma bitince kurulacak
        self._pending_install_mandatory = False
        self._upd = None                     # (adres, boyut, sağlama toplamı) — indirilecek güncelleme
        self._upd_mandatory = False
        self._download_wanted = False        # indirme istendi (iptalde False: biten indirme habersiz kurulmasın)
        self._installing = False             # kurulum başladı: yeni iş başlamasın, kapanışta beklenir
        self._quitting = False
        self._applying_profile = False
        self._restoring = True  # kurulum ve geri yükleme sırasında seçimler diske yazılmaz
        self._gpu_menu_ready = False  # GPU listesi gelmeden "Otomatik" kaydedilip asıl seçimi ezmesin
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(400)
        self._save_timer.timeout.connect(self._save_choices)
        self._log_has_content = False
        self._file_t0 = 0.0
        self._job_t0 = 0.0
        self._eta: JobEta | None = None
        self._progress_done = 0
        self._progress_total = 0
        self._file_ratio = 0.0

        self.setWindowTitle(get_app_name(self.lang))
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Window
            | Qt.WindowType.WindowMinMaxButtonsHint
            | Qt.WindowType.WindowSystemMenuHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.resize(*self._default_window_size())
        self.setMinimumSize(860, 560)  # while a job runs the content needs ~545 px of height

        icon = QIcon(resource_path("assets", "icons", "app_icon.png"))
        if not icon.isNull():
            self.setWindowIcon(icon)
        self._icon = icon

        self._build_ui()
        self.theme.theme_changed.connect(lambda *_: self._repolish())
        self._restore_settings()
        self._set_left_collapsed(bool(self.config.get("left_panel_collapsed")), save=False)
        self._retranslate_ui()
        self._update_queue_actions()
        self._bind_updater()
        self.raise_requested.connect(self._bring_to_front)
        QTimer.singleShot(200, lambda: self._prepare_ffmpeg(False))

    @staticmethod
    def _default_window_size() -> tuple[int, int]:
        """İlk açılış boyutu ekrana göre: geniş ekranda geniş (kuyruk tablosu ve sol panel rahat sığsın)."""
        screen = QApplication.primaryScreen()
        if screen is None:
            return 1280, 760
        avail = screen.availableGeometry()
        width = max(980, min(1440, int(avail.width() * 0.72)))
        height = max(640, min(900, int(avail.height() * 0.80)))
        return min(width, avail.width()), min(height, avail.height())

    def _build_ui(self):
        chrome = QFrame()
        chrome.setObjectName("app_chrome")
        chrome.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.chrome = chrome
        self.setCentralWidget(chrome)

        self.title_bar = TitleBar(self, self._icon)
        self.title_bar.theme_selected.connect(self._set_theme)
        self.title_bar.accent_selected.connect(self._set_accent)
        self.title_bar.language_selected.connect(self._set_language)
        self.title_bar.settings_clicked.connect(self._open_settings)
        self.title_bar.add_files_clicked.connect(self._pick_files)
        self.title_bar.add_folder_clicked.connect(self._pick_folder)
        self.title_bar.exit_clicked.connect(self.force_quit)
        self.title_bar.minimize_clicked.connect(self.showMinimized)
        self.title_bar.maximize_clicked.connect(self._toggle_max)
        self.title_bar.close_clicked.connect(self.close)
        self.title_bar.update_clicked.connect(self.show_pending_update)  # ↑: Ayarlar düğmesi/tepsi satırıyla aynı pencere

        chrome_l = QVBoxLayout(chrome)
        chrome_l.setContentsMargins(0, 0, 0, 0)
        chrome_l.setSpacing(0)
        chrome_l.addWidget(self.title_bar)

        # Uzaktan duyuru satırı (sunucu bir duyuru verene kadar gizli)
        from .notice_bar import NoticeBar
        self.notice_bar = NoticeBar()
        self.notice_bar.dismissed.connect(self._on_notice_dismissed)
        notice_wrap = QHBoxLayout()
        notice_wrap.setContentsMargins(16, 8, 16, 0)
        notice_wrap.addWidget(self.notice_bar)
        chrome_l.addLayout(notice_wrap)

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(16, 12, 16, 14)
        body_layout.setSpacing(10)
        chrome_l.addWidget(body, 1)

        self.banner = QFrame()
        self.banner.setFrameShape(QFrame.Shape.StyledPanel)
        banner_row = QHBoxLayout(self.banner)
        banner_row.setContentsMargins(10, 8, 10, 8)
        self.banner_label = QLabel()
        self.banner_label.setObjectName("banner_error")
        self.banner_label.setWordWrap(True)
        self.ffmpeg_btn = QPushButton(self._ffmpeg_button_text())
        self.ffmpeg_btn.setProperty("class", "primary")
        self.ffmpeg_btn.clicked.connect(lambda: self._prepare_ffmpeg(True))
        banner_row.addWidget(self.banner_label, 1)
        banner_row.addWidget(self.ffmpeg_btn)
        self.banner.hide()
        body_layout.addWidget(self.banner)

        chips = QHBoxLayout()
        chips.setSpacing(8)
        chips.setContentsMargins(0, 0, 0, 0)
        chips.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        self.profile_group = QButtonGroup(self)
        self.profile_group.setExclusive(True)
        self.profile_buttons = {}
        profile_keys = {
            "balanced": "profile_balanced",
            "fast": "profile_fast",
            "quality": "profile_quality",
            "custom": "profile_custom",
        }
        profile_tooltips = {
            "balanced": "profile_balanced_tip",
            "fast": "profile_fast_tip",
            "quality": "profile_quality_tip",
            "custom": "profile_custom_tip",
        }
        for key, spec in PROFILES.items():
            btn_text = t(profile_keys[key], self.lang) if key in profile_keys else spec["label"]
            btn = QPushButton(btn_text)
            btn.setCheckable(True)
            btn.setProperty("class", "chip")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            if key in profile_tooltips:
                btn.setToolTip(t(profile_tooltips[key], self.lang))
            btn.clicked.connect(lambda checked, k=key: self._apply_profile(k))
            self.profile_group.addButton(btn)
            self.profile_buttons[key] = btn
            chips.addWidget(btn)
        chips.addStretch()
        body_layout.addLayout(chips)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(16)
        body_layout.addWidget(self.splitter, 1)

        left = QWidget()
        left.setObjectName("left_content")
        left.setMinimumWidth(280)
        left.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        left_l = QVBoxLayout(left)
        left_l.setContentsMargins(12, 12, 12, 8)
        left_l.setSpacing(10)

        self._captions: dict[str, QLabel] = {}
        left_l.addWidget(self._caption("section_source"))
        self.drop = DropZone()
        self.drop.files_dropped.connect(self._add_sources)
        self.drop.select_files.connect(self._pick_files)
        self.drop.select_folder.connect(self._pick_folder)
        self.drop.open_folder.connect(self._open_source_folder)
        left_l.addWidget(self.drop)

        out_card, out_lay = self._group_card("section_output")
        left_l.addWidget(out_card)
        out_row = QHBoxLayout()
        out_row.setSpacing(8)
        self.out_label = ElidedPathLabel(self.output_dir)
        self.out_label.setObjectName("path_box")
        self.out_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self.out_label.clicked.connect(self._pick_output)  # yol kutusuna tıklamak da klasörü seçtirir
        self.out_btn = QPushButton(t("output_change", self.lang))
        self.out_btn.setProperty("class", "ghost-mini")
        self.out_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.out_btn.clicked.connect(self._pick_output)
        out_row.addWidget(self.out_label, 1)
        out_row.addWidget(self.out_btn)
        out_lay.addLayout(out_row)

        self.type_card = QFrame()
        self.type_card.setObjectName("group_card")
        type_card_lay = QVBoxLayout(self.type_card)
        type_card_lay.setContentsMargins(12, 10, 12, 12)
        type_card_lay.setSpacing(8)
        self.type_lab = QLabel(t("file_type", self.lang))
        self.type_lab.setObjectName("section_caption")
        type_card_lay.addWidget(self.type_lab)
        left_l.addWidget(self.type_card)
        self.type_wrap = QWidget()
        self.type_wrap.setObjectName("plain_box")
        type_row = QHBoxLayout(self.type_wrap)
        type_row.setContentsMargins(0, 0, 0, 0)
        type_row.setSpacing(8)
        self.type_group = QButtonGroup(self)
        self.type_group.setExclusive(True)
        self.type_buttons = {}
        for ft_id in FILE_TYPE_IDS:
            b = QPushButton(t(TYPE_LABEL_KEYS[ft_id], self.lang))
            b.setCheckable(True)
            b.setProperty("class", "segment")
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            self.type_group.addButton(b)
            self.type_buttons[ft_id] = b
            type_row.addWidget(b)
        self.type_buttons[FILE_TYPE_ALL].setChecked(True)
        for b in self.type_buttons.values():
            b.clicked.connect(lambda *_: self._preview_queue(False))
        type_card_lay.addWidget(self.type_wrap)
        self.type_card.hide()  # yalnızca kuyrukta hem resim hem video varken görünür

        res_card, res_lay = self._group_card("section_quality")
        left_l.addWidget(res_card)
        res_row = QHBoxLayout()
        res_row.setSpacing(12)
        self.video_box = QWidget()
        self.video_box.setObjectName("plain_box")
        vbox = QVBoxLayout(self.video_box)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(6)
        self.video_label_hdr = QLabel(t("video", self.lang))
        self.video_label_hdr.setObjectName("field_label")
        self.video_label_hdr.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        vbox.addWidget(self.video_label_hdr)
        self.video_res = QComboBox()
        self.video_res.addItems(list(VIDEO_RES.keys()) + [t("custom_option", self.lang)])
        self.video_res.setItemData(self.video_res.count() - 1, CUSTOM_RES, Qt.ItemDataRole.UserRole)
        mark_original(self.video_res, t("res_original", self.lang))
        self.video_res.setCurrentText("1080p")
        self._last_video_res = "1080p"
        self.video_res.activated.connect(self._on_video_res_activated)
        self.video_res.setToolTip(t("video_res_tip", self.lang))
        vbox.addWidget(self.video_res)
        self.image_box = QWidget()
        self.image_box.setObjectName("plain_box")
        ibox = QVBoxLayout(self.image_box)
        ibox.setContentsMargins(0, 0, 0, 0)
        ibox.setSpacing(6)
        self.image_label_hdr = QLabel(t("image", self.lang))
        self.image_label_hdr.setObjectName("field_label")
        self.image_label_hdr.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        ibox.addWidget(self.image_label_hdr)
        self.image_res = QComboBox()
        self.image_res.addItems(list(IMAGE_RES.keys()) + [t("custom_option", self.lang)])
        self.image_res.setItemData(self.image_res.count() - 1, CUSTOM_RES, Qt.ItemDataRole.UserRole)
        mark_original(self.image_res, t("res_original", self.lang))
        self.image_res.setCurrentText("2400px")
        self._last_image_res = "2400px"
        self.image_res.activated.connect(self._on_image_res_activated)
        self.image_res.setToolTip(t("image_res_tip", self.lang))
        ibox.addWidget(self.image_res)
        res_row.addWidget(self.video_box)
        res_row.addWidget(self.image_box)
        res_lay.addLayout(res_row)

        self.gpu_label = QLabel(t("gpu_detecting", self.lang))
        self.gpu_label.setObjectName("hint_label")  # sarı uyarı rengi yalnızca gerçekten sorun varsa
        self.gpu_label.setWordWrap(True)
        self.gpu_label.setContentsMargins(0, 0, 0, 0)
        left_l.addWidget(self.gpu_label)

        self.adv_dialog = AdvancedDialog(_codec_labels, _bitrate_labels, self, lang=self.lang)
        self.codec = self.adv_dialog.codec
        # Video kodeği ana ekranda (çözünürlüğün altında); yalnızca kuyrukta video varken görünür.
        self.codec_box = QWidget()
        self.codec_box.setObjectName("plain_box")
        cbox = QVBoxLayout(self.codec_box)
        cbox.setContentsMargins(0, 4, 0, 0)
        cbox.setSpacing(6)
        cbox.addWidget(self.adv_dialog.codec_lab)
        cbox.addWidget(self.codec)
        cbox.addWidget(self.adv_dialog.codec_hint)
        res_lay.addWidget(self.codec_box)
        self.bitrate = self.adv_dialog.bitrate
        self.crf = self.adv_dialog.crf
        self.preset = self.adv_dialog.preset
        self.audio = self.adv_dialog.audio
        self.img_auto = self.adv_dialog.img_auto
        self.img_quality = self.adv_dialog.img_quality
        self.subfolders = self.adv_dialog.subfolders
        self.gpu_menu = self.adv_dialog.gpu_menu
        self.subfolders.toggled.connect(lambda *_: self._preview_queue(False))

        self.adv_btn = QPushButton(t("adv_settings", self.lang))
        self.adv_btn.setProperty("class", "ghost")
        self.adv_btn.clicked.connect(self.adv_dialog.exec)

        self.preview_btn = QPushButton(t("preview_btn", self.lang))
        self.preview_btn.setProperty("class", "ghost")
        self.preview_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.preview_btn.setToolTip(t("preview_tooltip", self.lang))
        self.preview_btn.clicked.connect(self._open_preview_from_button)
        self.preview_btn.setIconSize(QSize(18, 18))

        left_l.addStretch(1)
        # Kartlar kısa pencerede kaydırılır (eskiden üst üste biniyor, düğmeler kırpılıyordu); Gelişmiş ve
        # Önizleme düğmeleri kaydırılan alanın altına sabitlenir: 1280×760'ta da kaydırmadan görünürler.
        left_scroll = QScrollArea()
        left_scroll.setObjectName("left_scroll")
        left_scroll.setWidgetResizable(True)
        left_scroll.setFrameShape(QFrame.Shape.NoFrame)
        left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        left_scroll.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        left_scroll.viewport().setAutoFillBackground(False)
        left_scroll.setStyleSheet("QScrollArea#left_scroll { background: transparent; border: none; }")
        left_scroll.setWidget(left)
        self.left_scroll = left_scroll

        footer = QFrame()
        footer.setObjectName("left_footer")
        footer_l = QVBoxLayout(footer)
        footer_l.setContentsMargins(12, 10, 12, 12)
        footer_l.setSpacing(8)
        footer_l.addWidget(self.adv_btn)
        footer_l.addWidget(self.preview_btn)
        self.left_footer = footer

        self.left_panel = QFrame()
        self.left_panel.setObjectName("left_panel")
        self.left_panel.setMinimumWidth(left.minimumWidth() + 14)  # dikey kaydırma çubuğu için pay
        self.left_panel.setMaximumWidth(380 + 14)
        self.left_panel.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        panel_l = QVBoxLayout(self.left_panel)
        panel_l.setContentsMargins(1, 1, 1, 1)  # kenarlık çizgisinin içinde kalsın
        panel_l.setSpacing(0)
        panel_l.addWidget(left_scroll, 1)
        panel_l.addWidget(footer)
        self.splitter.addWidget(self.left_panel)

        # Profilin belirlediği bir değer değişince profil "Özel"e geçer (ses ve resim kalitesi de: eskiden
        # Dengeli'de sesi 192k yapmak yeniden açılışta 128k'ye dönüyordu).
        for w in (self.codec, self.bitrate, self.video_res, self.image_res, self.crf, self.adv_dialog.fps,
                  self.audio, self.img_quality):
            if hasattr(w, "currentIndexChanged"):
                w.currentIndexChanged.connect(self._mark_custom)
            elif hasattr(w, "valueChanged"):
                w.valueChanged.connect(self._mark_custom)
        for combo in (self.codec, self.bitrate, self.video_res, self.image_res, self.audio, self.preset,
                      self.adv_dialog.fps, self.gpu_menu):
            combo.currentIndexChanged.connect(self._schedule_save_choices)
        self.codec.currentIndexChanged.connect(self._refresh_codec_hint)
        self.gpu_menu.currentIndexChanged.connect(self._refresh_codec_hint)
        for slider in (self.crf, self.img_quality):
            slider.valueChanged.connect(self._schedule_save_choices)
        for box in (self.img_auto, self.subfolders, self.adv_dialog.remove_audio):
            box.toggled.connect(self._schedule_save_choices)

        right = QFrame()
        right.setObjectName("right_panel")
        right_l = QVBoxLayout(right)
        right_l.setContentsMargins(12, 12, 12, 12)
        right_l.setSpacing(10)
        head = QHBoxLayout()
        head.setSpacing(8)
        # Ayar panelini gizle/göster: kuyruk tüm genişliği alır; durum ayarlarda saklanır.
        self.panel_toggle = QPushButton()
        self.panel_toggle.setObjectName("panel_toggle")
        self.panel_toggle.setProperty("class", "ghost-mini")
        self.panel_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.panel_toggle.setFixedSize(32, 28)
        self.panel_toggle.setIconSize(QSize(18, 18))
        self.panel_toggle.clicked.connect(lambda: self._set_left_collapsed(not self._left_collapsed))
        head.addWidget(self.panel_toggle)
        self.queue_title = QLabel(t("queue", self.lang))
        self.queue_title.setObjectName("section_header")
        head.addWidget(self.queue_title)
        head.addStretch()
        self.clear_btn = QPushButton(t("clear_queue", self.lang))
        self.clear_btn.setProperty("class", "ghost-mini")
        self.clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clear_btn.clicked.connect(self._clear_queue)
        self.clear_btn.hide()
        self.remove_btn = QPushButton(t("remove", self.lang))
        self.remove_btn.setProperty("class", "ghost-mini")
        self.remove_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.remove_btn.setToolTip(t("queue_remove_tooltip", self.lang))
        self.remove_btn.clicked.connect(self._remove_selected)
        self.remove_btn.hide()
        self.retry_btn = QPushButton(t("retry_failed", self.lang))
        self.retry_btn.setProperty("class", "ghost-mini")
        self.retry_btn.clicked.connect(self._retry_failed)
        self.retry_btn.hide()
        # İş kaydı kuyruğun altında açılır: düğmesi de kuyruğun başlığında (eskiden profil satırının sağındaydı).
        self.log_toggle = QPushButton(t("log", self.lang))
        self.log_toggle.setCheckable(True)
        self.log_toggle.setProperty("class", "ghost-mini")
        self.log_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.log_toggle.toggled.connect(self._toggle_log)
        for mini in (self.remove_btn, self.clear_btn, self.retry_btn, self.log_toggle, self.panel_toggle):
            mini.style().unpolish(mini)
            mini.style().polish(mini)
        head.addWidget(self.remove_btn)
        head.addWidget(self.clear_btn)
        head.addWidget(self.log_toggle)
        right_l.addLayout(head)
        # Özet satırı ("8 dosya · toplam 2.8 GB") ve iş bitince "Hatalıları Tekrar Dene": başlık en küçük
        # pencerede de sığsın diye bu düğme özetin sağında durur.
        self.queue_sub = QWidget()
        self.queue_sub.setObjectName("plain_box")
        sub_l = QHBoxLayout(self.queue_sub)
        sub_l.setContentsMargins(0, 0, 0, 0)
        sub_l.setSpacing(8)
        self.queue_summary = QLabel("")
        self.queue_summary.setObjectName("hint_label")
        self.queue_summary.hide()
        sub_l.addWidget(self.queue_summary, 1)
        sub_l.addWidget(self.retry_btn)
        self.queue_sub.hide()
        right_l.addWidget(self.queue_sub)
        self.queue = QueuePanel(lang=self.lang)
        self.queue.remove_requested.connect(self._remove_from_queue)
        self.queue.reveal_requested.connect(self._reveal_source)
        self.queue.open_requested.connect(self._open_source_file)
        self.queue.preview_requested.connect(self._open_preview)
        self.queue.trim_requested.connect(self._open_trim)
        self.queue.selection_count_changed.connect(lambda *_: self._update_queue_actions())
        self.queue.overrides_changed.connect(self._on_overrides_changed)
        right_l.addWidget(self.queue, 1)
        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setMaximumHeight(120)
        self.log_box.hide()
        right_l.addWidget(self.log_box)
        right_col = QWidget()
        right_col.setObjectName("right_col")
        right_col.setMinimumWidth(420)
        right_col_l = QVBoxLayout(right_col)
        right_col_l.setContentsMargins(0, 0, 0, 10)
        right_col_l.setSpacing(8)
        right_col_l.addWidget(right, 1)

        action = QFrame()
        action.setObjectName("action_bar")
        action_l = QHBoxLayout(action)
        action_l.setContentsMargins(12, 10, 12, 10)
        action_l.setSpacing(12)
        self.start_btn = QPushButton(t("start_compression", self.lang))
        self.start_btn.setProperty("class", "primary")
        self.start_btn.setMinimumHeight(42)
        self.start_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.start_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.start_btn.clicked.connect(self._start_stop)
        self.open_btn = QPushButton(t("open_output", self.lang))
        self.open_btn.setProperty("class", "ghost")
        self.open_btn.setMinimumHeight(42)
        self.open_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.open_btn.clicked.connect(self._open_output)
        self.open_when_done = QCheckBox(t("open_when_done", self.lang))
        self.open_when_done.setToolTip(t("open_when_done_tip", self.lang))
        self.open_when_done.setChecked(bool(self.config.get("open_output_when_done")))
        self.open_when_done.toggled.connect(
            lambda on: self.config.set("open_output_when_done", bool(on))
        )
        self.open_when_done.hide()
        action_l.addWidget(self.start_btn, 1)
        action_l.addWidget(self.open_btn)
        action_l.addWidget(self.open_when_done)
        right_col_l.addWidget(action)

        # Progress rows only exist while there is something to report (running job / its summary).
        # Compact: one text line ("5/8 files · 62%") over a slim bar. Each file's own progress is drawn in its
        # queue row, so the old second (video) bar is gone and the queue keeps its height.
        self.prog_box = QWidget()
        prog = QVBoxLayout(self.prog_box)
        prog.setContentsMargins(4, 0, 4, 0)
        prog.setSpacing(5)

        self.overall_label = QLabel(t("ready", self.lang))
        self.overall_label.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        self.overall_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.overall = QProgressBar()
        self.overall.setObjectName("slim_bar")
        self.overall.setValue(0)
        self.overall.setTextVisible(False)
        self.overall.setFixedHeight(6)
        self.overall.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        prog.addWidget(self.overall_label)
        prog.addWidget(self.overall)

        right_col_l.addWidget(self.prog_box)
        self.prog_box.hide()

        self.stats = _AutoHideLabel("")
        self.stats.setObjectName("hint_label")
        self.stats.setContentsMargins(4, 0, 4, 0)  # ilerleme satırlarıyla aynı sol hiza (prog_box kenar boşluğu)
        right_col_l.addWidget(self.stats)

        self.splitter.addWidget(right_col)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([340, 1100])

        self._grip = QSizeGrip(chrome)
        self._grip.setFixedSize(14, 14)
        self._setup_shortcuts()
        self._apply_round_mask()
        fit_text_widgets(self)

    def _group_card(self, caption_key: str) -> tuple[QFrame, QVBoxLayout]:
        """Sol paneldeki bölüm: başlık + içerik tek bir kabartmalı kutuda (grup olduğu belli olsun)."""
        card = QFrame()
        card.setObjectName("group_card")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(12, 10, 12, 12)
        lay.setSpacing(8)
        lay.addWidget(self._caption(caption_key))
        return card, lay

    def _caption(self, key: str) -> QLabel:
        """Sol paneldeki bölüm başlığı (KAYNAK / ÇIKIŞ KLASÖRÜ / ÇÖZÜNÜRLÜK); dil değişince yenilenir."""
        label = QLabel(t(key, self.lang))
        label.setObjectName("section_caption")
        self._captions[key] = label
        return label

    def _show_progress(self, visible: bool = True) -> None:
        """The overall progress line exists only while there is something to report; none at all when idle."""
        self.prog_box.setVisible(visible)

    def _set_left_collapsed(self, collapsed: bool, save: bool = True) -> None:
        """Ayar panelini gizler/gösterir (kuyruk tüm genişliği alır); durum sonraki açılışa kalır."""
        self._left_collapsed = bool(collapsed)
        self.left_panel.setVisible(not self._left_collapsed)
        self._refresh_panel_toggle()
        if save:
            self.config.set("left_panel_collapsed", self._left_collapsed)

    def _refresh_panel_toggle(self) -> None:
        collapsed = getattr(self, "_left_collapsed", False)
        color = icons.accent_color_for(self.theme.get_palette())
        self.panel_toggle.setIcon(icons.sidebar_icon(color, collapsed))
        self.panel_toggle.setToolTip(t("panel_show" if collapsed else "panel_hide", self.lang))
        self.panel_toggle.setAccessibleName(self.panel_toggle.toolTip())

    def _setup_shortcuts(self):
        from PyQt6.QtGui import QShortcut, QKeySequence
        def bind(key, slot):
            sc = QShortcut(QKeySequence(key), self)
            sc.setContext(Qt.ShortcutContext.WindowShortcut)
            sc.activated.connect(slot)
            return sc

        bind("Ctrl+,", self._open_settings)
        bind("Ctrl+Q", self.force_quit)  # gerçekten çık (X / Alt+F4 tepsiye gizler)
        bind("Alt+F4", self.close)
        bind("Ctrl+O", self._pick_files)
        bind("Ctrl+Shift+O", self._pick_folder)
        bind("F1", self._show_about)
        bind("F5", lambda: self._prepare_ffmpeg(download=False))

    def _show_about(self):
        AboutDialog(self, lang=self.lang).exec()

    def _restore_settings(self):
        profile = self.config.get("profile", "balanced")
        if profile in ("whatsapp", "balanced"):
            profile = "balanced"
        elif profile in ("instagram", "fast"):
            profile = "fast"
        if profile in self.profile_buttons:
            self.profile_buttons[profile].setChecked(True)
            self._apply_profile(profile)
        self._restore_choices(profile)
        ft = normalize_file_type(self.config.get("file_type"))
        if ft in self.type_buttons:
            self.type_buttons[ft].setChecked(True)
        last_out = self.config.get("last_output")
        if last_out:
            self.output_dir = last_out
            self.output_manual = True
            self.out_label.setText(last_out)
        else:
            self.output_dir = default_output_dir()
            self.output_manual = False
            self.out_label.setText(self.output_dir)
        self.title_bar.set_theme_choice(self.config.get("theme", "system"))
        self.title_bar.set_accent_choice(self.config.get("accent", DEFAULT_ACCENT))
        self.title_bar.set_language_choice(self.config.get("language", AUTO_LANGUAGE))
        if TrayIcon.isSystemTrayAvailable():  # tepsi simgesi her zaman vardır (ayarlarda açma/kapama yok)
            self._ensure_tray()
        self._repolish()

    # ------------------------------------------------------------------ kalıcı seçimler
    def _choices(self) -> dict:
        choices = {
            "codec": CODEC_KEYS[self.codec.currentIndex()][0],
            "bitrate": BITRATE_KEYS[self.bitrate.currentIndex()][0],
            "crf": int(self.crf.value()),
            "video_res": res_value(self.video_res),
            "image_res": res_value(self.image_res),
            "audio_bitrate": self.audio.currentText(),
            "image_quality": int(self.img_quality.value()),
            "fps": self.adv_dialog.fps_value(),
            "preset": self.preset.currentData() or "slow",
            "image_quality_auto": self.img_auto.isChecked(),
            "scan_subfolders": self.subfolders.isChecked(),
            "remove_audio": self.adv_dialog.remove_audio.isChecked(),
        }
        if self._gpu_menu_ready:
            choices["gpu_mode"] = self.adv_dialog.gpu_choice()
        return choices

    def _schedule_save_choices(self, *_):
        if not self._restoring:
            self._save_timer.start()

    def _save_choices(self) -> None:
        """Seçimleri config.json'a yaz (yalnızca değişenler varsa diske dokunulur)."""
        self._save_timer.stop()
        changed = False
        for key, value in self._choices().items():
            if self.config.data.get(key) != value:
                self.config.data[key] = value
                changed = True
        if changed:
            self.config.save()

    def _restore_res(self, combo: QComboBox, value, video: bool) -> None:
        """Kayıtlı çözünürlüğü seç; özel değer ("1600px") listede yoksa eklenir."""
        if not isinstance(value, str) or not value:
            return
        if find_res(combo, value) < 0:
            digits = "".join(c for c in value if c.isdigit())
            if not digits or not value.endswith("px"):
                return
            combo.insertItem(max(0, combo.count() - 1), value)  # "Özel…" hep sonda kalır
            if video:
                VIDEO_RES[value] = int(digits)
        select_res(combo, value)
        if video:
            self._last_video_res = value
        else:
            self._last_image_res = value

    def _restore_choices(self, profile: str) -> None:
        """Yeniden açılışta seçimler unutulmasın (ör. seçilen resim boyutu)."""
        cfg = self.config.get
        self._restoring = True
        self._applying_profile = True
        try:
            if profile == "custom":
                codec_idx = next((i for i, (cid, _) in enumerate(CODEC_KEYS) if cid == cfg("codec")), None)
                if codec_idx is not None:
                    self.codec.setCurrentIndex(codec_idx)
                bitrate = normalize_bitrate(cfg("bitrate"))
                br_idx = next((i for i, (bid, _) in enumerate(BITRATE_KEYS) if bid == bitrate), None)
                if br_idx is not None:
                    self.bitrate.setCurrentIndex(br_idx)
                self.crf.setValue(int(cfg("crf")))
                self._restore_res(self.video_res, cfg("video_res"), video=True)
                self._restore_res(self.image_res, cfg("image_res"), video=False)
                if self.audio.findText(str(cfg("audio_bitrate"))) >= 0:
                    self.audio.setCurrentText(str(cfg("audio_bitrate")))
                self.img_quality.setValue(int(cfg("image_quality")))
                self.adv_dialog.set_fps(cfg("fps"))
            preset_idx = self.preset.findData(cfg("preset"))
            if preset_idx >= 0:
                self.preset.setCurrentIndex(preset_idx)
            self.img_auto.setChecked(bool(cfg("image_quality_auto")))
            self.subfolders.setChecked(bool(cfg("scan_subfolders")))
            self.adv_dialog.remove_audio.setChecked(bool(cfg("remove_audio")))
        except (TypeError, ValueError) as exc:  # elle bozulmuş config.json: kalan seçimler varsayılan kalır
            log_error("Kayıtlı seçimler geri yüklenemedi", exc)
        finally:
            self._applying_profile = False
            self._restoring = False

    def _ensure_tray(self) -> bool:
        """Tepsi simgesini oluştur. Sistem tepsisi yoksa (ör. eklentisiz GNOME) False döner ve
        simge oluşturulmaz; çağıran pencereyi gizlememelidir (kullanıcı ona ulaşamazdı)."""
        if self.tray is None:
            if not TrayIcon.isSystemTrayAvailable():
                return False
            icon = self._icon if self._icon and not self._icon.isNull() else self.windowIcon()
            self.tray = TrayIcon(self, icon, self, lang=self.lang)
            self.tray.show()
        return True

    def show_notice(self, notice):
        """Sunucudan gelen duyuruyu göster (kullanıcı bu duyuruyu daha önce kapattıysa gösterme)."""
        if self.config.get("dismissed_notice", "") == notice.id:
            return
        self.notice_bar.show_notice(notice)

    def _on_notice_dismissed(self, notice_id: str):
        self.config.set("dismissed_notice", notice_id)

    def _bind_updater(self):
        self.updater.update_available.connect(self._on_update_available)
        self.updater.notice_received.connect(self.show_notice)
        self.installer.lang = self.lang
        self.installer.download_progress.connect(self._on_dl_progress)
        self.installer.download_complete.connect(self._on_dl_complete)
        self.installer.download_failed.connect(self._on_dl_failed)
        self.installer.install_started.connect(self._on_install_started)
        self.installer.install_complete.connect(self._on_install_complete)
        self.installer.install_failed.connect(self._on_install_failed)

    def _set_theme(self, key: str):
        self.config.set("theme", key)
        self.theme.apply_from_setting(key, self.config.get("accent", DEFAULT_ACCENT))
        self.title_bar.set_theme_choice(key)

    def _set_accent(self, key: str):
        self.config.set("accent", key)
        self.theme.apply_from_setting(self.config.get("theme", "system"), key)
        self.title_bar.set_accent_choice(key)
        self._repolish()

    def _set_language(self, lang_choice: str):
        self.config.set("language", lang_choice)
        self.title_bar.set_language_choice(lang_choice)
        new_lang = get_active_language(self.config)
        self.lang = new_lang
        self._retranslate_ui()

    def _on_system_scheme_changed(self, *_):
        if self.config.get("theme", "system") == "system":
            self.theme.apply_from_setting("system", self.config.get("accent", DEFAULT_ACCENT))
            self._repolish()

    def _repolish(self):
        for w in self.findChildren(QWidget):
            w.style().unpolish(w)
            w.style().polish(w)
        fit_text_widgets(self)
        palette = self.theme.get_palette()
        self.queue.set_status_palette(palette)
        self.title_bar.apply_palette(palette)  # menü/düğme simgeleri seçilen vurguya uysun
        self.preview_btn.setIcon(icons.eye_icon(icons.accent_color_for(palette)))
        self._refresh_panel_toggle()
        self.update()

    def _open_settings(self):
        dlg = SettingsDialog(
            self.config,
            self.ffmpeg.ffmpeg_path or "",
            self.gpu.status_text() if self.gpu else "",
            self,
            updater=self.updater,
            theme=self.theme,
        )
        if dlg.exec():
            new_lang = get_active_language(self.config)
            if new_lang != self.lang:
                self.lang = new_lang
                self._retranslate_ui()
            self.theme.apply_from_setting(
                self.config.get("theme", "system"),
                self.config.get("accent", DEFAULT_ACCENT),
            )
            self._ensure_tray()
            self.title_bar.set_theme_choice(self.config.get("theme", "system"))
            self.title_bar.set_accent_choice(self.config.get("accent", DEFAULT_ACCENT))
            self.title_bar.set_language_choice(self.config.get("language", AUTO_LANGUAGE))

    def _retranslate_ui(self):
        install_qt_translations(self.lang)
        for combo in (self.video_res, self.image_res):
            combo.setItemText(combo.count() - 1, t("custom_option", self.lang))
            mark_original(combo, t("res_original", self.lang))
        title = get_app_name(self.lang)
        self.setWindowTitle(title)
        self.installer.lang = self.lang  # güncelleme hata iletileri arayüz dilinde
        self.title_bar.retranslate(self.lang)
        self.title_bar.set_language_choice(self.config.get("language", AUTO_LANGUAGE))
        self.drop.retranslate(self.lang)
        self.queue.retranslate(self.lang)
        self._update_queue_actions()
        if self.tray:
            self.tray.retranslate(self.lang)
        self.out_btn.setText(t("output_change", self.lang))
        for key, label in self._captions.items():
            label.setText(t(key, self.lang))
        if not self.output_manual:
            self.output_dir = default_output_dir(self.lang)
            self.out_label.setText(self.output_dir)
        self.type_lab.setText(t("file_type", self.lang))
        if hasattr(self, 'video_label_hdr'):
            self.video_label_hdr.setText(t("video", self.lang))
        if hasattr(self, 'image_label_hdr'):
            self.image_label_hdr.setText(t("image", self.lang))
        if hasattr(self, 'video_res'):
            self.video_res.setToolTip(t("video_res_tip", self.lang))
        if hasattr(self, 'image_res'):
            self.image_res.setToolTip(t("image_res_tip", self.lang))
        if hasattr(self, 'preview_btn'):
            self.preview_btn.setText(t("preview_btn", self.lang))
            self.preview_btn.setToolTip(t("preview_tooltip", self.lang))
        if hasattr(self, 'ffmpeg_btn'):
            self.ffmpeg_btn.setText(self._ffmpeg_button_text())
        if hasattr(self, 'remove_btn'):
            self.remove_btn.setToolTip(t("queue_remove_tooltip", self.lang))
        if hasattr(self, 'open_when_done'):
            self.open_when_done.setToolTip(t("open_when_done_tip", self.lang))
        profile_keys = {
            "balanced": "profile_balanced",
            "fast": "profile_fast",
            "quality": "profile_quality",
            "custom": "profile_custom",
        }
        profile_tooltips = {
            "balanced": "profile_balanced_tip",
            "fast": "profile_fast_tip",
            "quality": "profile_quality_tip",
            "custom": "profile_custom_tip",
        }
        for key, btn in getattr(self, 'profile_buttons', {}).items():
            pkey = profile_keys.get(key)
            if pkey:
                btn.setText(t(pkey, self.lang))
            if key in profile_tooltips:
                btn.setToolTip(t(profile_tooltips[key], self.lang))
        for ft_id, btn in self.type_buttons.items():
            label_key = TYPE_LABEL_KEYS.get(ft_id)
            if label_key:
                btn.setText(t(label_key, self.lang))
        self.adv_btn.setText(t("adv_settings", self.lang))
        self.adv_dialog.retranslate(self.lang)
        self._refresh_codec_hint()
        self.queue_title.setText(t("queue", self.lang))
        self.clear_btn.setText(t("clear_queue", self.lang))
        self.remove_btn.setText(t("remove", self.lang))
        self.retry_btn.setText(t("retry_failed", self.lang))
        if self.worker:
            self.start_btn.setText(t("stop_compression", self.lang))
        else:
            self.start_btn.setText(t("start_compression", self.lang))
        self.open_btn.setText(t("open_output", self.lang))
        self.open_when_done.setText(t("open_when_done", self.lang))
        self.log_toggle.setText(t("log", self.lang))
        self._refresh_panel_toggle()
        fit_text_widgets(self)

    def _apply_round_mask(self) -> None:
        host = getattr(self, "chrome", None)
        if self.isMaximized() or self.isFullScreen():
            self.clearMask()
            if host is not None:
                host.clearMask()
            return
        if self.width() < 8 or self.height() < 8:
            return
        from PyQt6.QtCore import QRectF
        from PyQt6.QtGui import QPainterPath, QRegion

        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), 12.0, 12.0)
        self.setMask(QRegion(path.toFillPolygon().toPolygon()))
        if host is not None and host.width() >= 8 and host.height() >= 8:
            cpath = QPainterPath()
            cpath.addRoundedRect(QRectF(host.rect()), 12.0, 12.0)
            host.setMask(QRegion(cpath.toFillPolygon().toPolygon()))

    def _toggle_max(self):
        if self.isMaximized():
            self.showNormal()
            self.title_bar.set_maximized(False)
        else:
            self.showMaximized()
            self.title_bar.set_maximized(True)
        if hasattr(self, "_grip"):
            self._grip.setVisible(not self.isMaximized())
        self._apply_round_mask()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange and hasattr(self, "title_bar"):
            self.title_bar.set_maximized(self.isMaximized())
            if hasattr(self, "_grip"):
                self._grip.setVisible(not self.isMaximized())
            self._apply_round_mask()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_round_mask()
        if hasattr(self, "_grip"):
            self._grip.move(self.width() - 16, self.height() - 16)

    def _toggle_log(self, on: bool):
        self.log_box.setVisible(on)

    def _apply_profile(self, key: str):
        self._applying_profile = True
        spec = PROFILES.get(key, {})
        if key != "custom":
            codec = spec.get("codec", "h264")
            for i, (cid, _) in enumerate(CODEC_KEYS):
                if cid == codec:
                    self.codec.setCurrentIndex(i)
                    break
            br = normalize_bitrate(spec.get("bitrate", "2000k"))
            for i, (bid, _) in enumerate(BITRATE_KEYS):
                if bid == br:
                    self.bitrate.setCurrentIndex(i)
                    break
            select_res(self.video_res, spec.get("video_res", "1080p"))
            self._last_video_res = res_value(self.video_res)
            if spec.get("audio"):
                self.audio.setCurrentText(spec["audio"])
            select_res(self.image_res, spec.get("image_res", "2400px"))
            self._last_image_res = res_value(self.image_res)
            if spec.get("image_quality"):
                self.img_quality.setValue(int(spec["image_quality"]))
            self.crf.setValue(int(spec.get("crf", 24)))
            self.adv_dialog.set_fps(spec.get("fps"))
        self.config.set("profile", key)
        self._applying_profile = False

    def _mark_custom(self, *_):
        if self._applying_profile:
            return
        btn = self.profile_buttons.get("custom")
        if btn:
            btn.setChecked(True)
            self.config.set("profile", "custom")

    def _open_preview_from_button(self):
        self._open_preview(None)

    def _open_preview(self, path: str | None = None):
        all_exts = IMAGE_EXTS | VIDEO_EXTS
        if not path:
            sel = self.queue.selected_paths()
            for p in sel:
                if Path(p).suffix.lower() in all_exts:
                    path = p
                    break
        if not path:
            for p in self.queue.paths():
                if Path(p).suffix.lower() in all_exts:
                    path = p
                    break

        is_vid = bool(path and Path(path).suffix.lower() in VIDEO_EXTS)
        init_res = res_value(self.video_res) if is_vid else res_value(self.image_res)
        dlg = PreviewDialog(
            file_path=path,
            initial_quality=int(self.img_quality.value()),
            initial_res=init_res,
            parent=self,
            lang=self.lang,
        )
        dlg.settings_applied.connect(self._on_preview_settings_applied)
        dlg.exec()

    def _open_trim(self, path: str) -> None:
        """Sağ tık > Kırp…: başlangıç-bitiş seçimi (yalnızca bu aralık sıkıştırılır)."""
        if not self.ffmpeg.is_ready():
            MessageBox.warning(self, APP_NAME, self.ffmpeg.needed_message(self.lang))
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            duration = VideoCompressor(self.ffmpeg.ffmpeg_path, self.ffmpeg.ffprobe_path).duration(path)
        finally:
            QApplication.restoreOverrideCursor()
        if duration <= 0:
            MessageBox.warning(self, APP_NAME, t("trim_no_duration", self.lang))
            return
        current = self.queue.overrides_for(path).get("trim")
        dlg = TrimDialog(path, duration, current, parent=self, lang=self.lang)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        values = dlg.values()
        self.queue.set_override([path], "trim", None if values is None else (values[0], values[1], duration))

    def _refresh_codec_hint(self, *_):
        """Seçilen kodeğin kısa açıklaması. AV1'de bu bilgisayarda nasıl kodlanacağı da yazılır: AV1
        kodlayamayan bir ekran kartı + programın indirdiği FFmpeg (SVT-AV1 yok) olursa AV1 libaom'a düşer ve video
        süresinin ~10 katı sürer; o zaman açıklamanın yerine uyarı gösterilir."""
        codec = CODEC_KEYS[self.codec.currentIndex()][0] if self.codec.currentIndex() >= 0 else "h264"
        route = ""
        if codec == "av1" and self.gpu is not None:
            family = self.gpu.resolve_mode(self.adv_dialog.gpu_choice())
            route = (getattr(self.gpu, "av1_routes", {}) or {}).get(family, "")
        if route in ("aom", "none"):
            self.adv_dialog.set_codec_hint(t("av1_slow_hint" if route == "aom" else "av1_none_hint", self.lang), warn=True)
            return
        text = t(f"codec_{codec}_hint", self.lang)
        if route == "svt":
            text += " " + t("av1_cpu_hint", self.lang)
        self.adv_dialog.set_codec_hint(text)

    def _eta_weight(self, path: str) -> int:
        """Kalan süre tahmininde dosyanın ağırlığı: boyut, kırpılmışsa kalan payı kadar."""
        size = self.queue.size_of(path)
        fraction = trim_fraction(self.queue.overrides_for(path))
        return max(1, int(size * fraction)) if size and fraction < 1.0 else size

    def _on_video_res_activated(self, index: int):
        text = res_value(self.video_res, index)
        if self.video_res.itemData(index, Qt.ItemDataRole.UserRole) == CUSTOM_RES:
            prev_val = 1920
            try:
                if hasattr(self, "_last_video_res") and self._last_video_res:
                    clean = self._last_video_res.replace("px", "").replace("p", "").strip()
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
                val -= val % 2  # video genişliği çift olmalı (4:2:0); 1285 -> 1284
                custom_label = f"{val}px"
                VIDEO_RES[custom_label] = val
                idx = self.video_res.findText(custom_label)
                if idx < 0:
                    insert_pos = max(0, self.video_res.count() - 1)
                    self.video_res.insertItem(insert_pos, custom_label)
                    idx = insert_pos
                self.video_res.setCurrentIndex(idx)
                self._last_video_res = custom_label
                self._mark_custom()
            else:
                prev_idx = find_res(self.video_res, getattr(self, "_last_video_res", "1080p"))
                if prev_idx >= 0:
                    self.video_res.setCurrentIndex(prev_idx)
                else:
                    self.video_res.setCurrentIndex(0)
                return
        else:
            self._last_video_res = text
            self._mark_custom()

    def _on_image_res_activated(self, index: int):
        text = res_value(self.image_res, index)
        if self.image_res.itemData(index, Qt.ItemDataRole.UserRole) == CUSTOM_RES:
            prev_val = 1600
            try:
                if hasattr(self, "_last_image_res") and self._last_image_res and self._last_image_res.endswith("px"):
                    prev_val = int(self._last_image_res.replace("px", ""))
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
                idx = self.image_res.findText(custom_label)
                if idx < 0:
                    insert_pos = max(0, self.image_res.count() - 1)
                    self.image_res.insertItem(insert_pos, custom_label)
                    idx = insert_pos
                self.image_res.setCurrentIndex(idx)
                self._last_image_res = custom_label
                self._mark_custom()
            else:
                prev_idx = find_res(self.image_res, getattr(self, "_last_image_res", "2400px"))
                if prev_idx >= 0:
                    self.image_res.setCurrentIndex(prev_idx)
                else:
                    self.image_res.setCurrentIndex(0)
                return
        else:
            self._last_image_res = text
            self._mark_custom()

    def _on_preview_settings_applied(self, quality: int, res: str, is_video: bool):
        self.img_quality.setValue(quality)
        self.img_auto.setChecked(False)
        combo = self.video_res if is_video else self.image_res
        if find_res(combo, res) < 0:
            combo.insertItem(max(0, combo.count() - 1), res)
        select_res(combo, res)
        if is_video:
            self._last_video_res = res
        else:
            self._last_image_res = res
        self._mark_custom()

    def _add_sources(self, paths: list[str], replace: bool = False):
        if replace:
            self.sources = []
            self.skip_paths.clear()
        added = []
        for p in paths:
            p = os.path.abspath(p)
            if p not in self.sources and os.path.exists(p):
                self.sources.append(p)
                added.append(p)
        if not added and not replace:
            return
        self._refresh_source_ui()
        if self.sources:
            first = self.sources[0]
            folder = first if os.path.isdir(first) else os.path.dirname(first)
            self.config.set("last_input", folder)
            self.config.add_recent_folder(folder)

    def _refresh_source_ui(self):
        if not self.sources:
            self.drop.set_status(t("not_selected", self.lang))
            self.drop.set_folder_open_visible(False)
            self._preview_queue()
            self._update_queue_actions()
            return
        names = [os.path.basename(p.rstrip("\\/")) or p for p in self.sources]
        if len(names) == 1:
            self.drop.set_status(names[0])
        elif len(names) <= 3:
            self.drop.set_status(" · ".join(names))
        else:
            self.drop.set_status(f"{names[0]} · {names[1]} +{len(names) - 2}")
        self.drop.set_folder_open_visible(any(os.path.isdir(p) for p in self.sources))
        self._preview_queue(reset_type=True)
        self._update_queue_actions()

    def _preview_queue(self, reset_type: bool = False):
        if not self.sources:
            self.queue.set_files([])
            self._sync_media_controls(False, False)
            self._update_queue_actions()
            return
        _, all_files = collect_files(
            self.sources, self._effective_output(), FILE_TYPE_ALL, self.subfolders.isChecked(),
        )
        has_img = any(Path(p).suffix.lower() in IMAGE_EXTS for p in all_files)
        has_vid = any(Path(p).suffix.lower() in VIDEO_EXTS for p in all_files)
        self._sync_media_controls(has_img, has_vid, prefer_all=reset_type)
        ft = self._file_type()
        if ft == FILE_TYPE_IMAGES:
            files = [p for p in all_files if Path(p).suffix.lower() in IMAGE_EXTS]
        elif ft == FILE_TYPE_VIDEOS:
            files = [p for p in all_files if Path(p).suffix.lower() in VIDEO_EXTS]
        else:
            files = all_files
        files = [p for p in files if norm_path(p) not in self.skip_paths]
        self.queue.set_files(files)
        self._update_queue_actions()

    def _sync_media_controls(self, has_img: bool, has_vid: bool, prefer_all: bool = False):
        mixed = has_img and has_vid
        self.type_card.setVisible(mixed)
        self.type_buttons[FILE_TYPE_ALL].setVisible(mixed)
        self.type_buttons[FILE_TYPE_IMAGES].setVisible(mixed)
        self.type_buttons[FILE_TYPE_VIDEOS].setVisible(mixed)
        if mixed:
            if prefer_all or self._file_type() not in FILE_TYPE_IDS:
                self.type_buttons[FILE_TYPE_ALL].setChecked(True)
        elif has_img:
            self.type_buttons[FILE_TYPE_IMAGES].setChecked(True)
        elif has_vid:
            self.type_buttons[FILE_TYPE_VIDEOS].setChecked(True)
        self.video_box.setVisible(has_vid)
        self.codec_box.setVisible(has_vid)
        self.image_box.setVisible(has_img)

    def _open_source_folder(self):
        folders = [p for p in self.sources if os.path.isdir(p)]
        if not folders:
            return
        path = folders[0]
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(path)):
            MessageBox.warning(self, APP_NAME, t("msg_open_folder_failed", self.lang).format(path))

    def _update_queue_actions(self):
        running = bool(self.worker and self.worker.isRunning())
        has_queue = self.queue.rowCount() > 0
        selected = len(self.queue.selected_paths()) if has_queue else 0
        n = self.queue.rowCount()
        queue_label = t("queue", self.lang)
        self.queue_title.setText(queue_label if n == 0 else f"{queue_label}  ·  {n}")
        total = self.queue.total_bytes()
        if n and total:
            self.queue_summary.setText(t("queue_summary", self.lang).format(n=n, size=format_bytes(total)))
        self.queue_summary.setVisible(bool(n and total) and not running)
        self.queue_sub.setVisible(not self.queue_summary.isHidden() or not self.retry_btn.isHidden())
        if not running:
            # Boş kuyrukta başlatılacak bir şey yok: düğme pasif kalır, nedenini ipucu söyler.
            self.start_btn.setEnabled(has_queue)
            self.start_btn.setToolTip("" if has_queue else t("start_needs_files", self.lang))
        self.clear_btn.setVisible(has_queue)
        self.clear_btn.setEnabled(not running)
        self.remove_btn.setVisible(has_queue)
        self.remove_btn.setEnabled(not running and selected > 0)
        self.queue.set_locked(running)

    def _remove_selected(self):
        self._remove_from_queue(self.queue.selected_paths())

    def _remove_from_queue(self, paths: list[str]):
        if self.worker and self.worker.isRunning():
            return
        if not paths:
            return
        removed = {norm_path(p) for p in paths}
        self.skip_paths |= removed
        self.sources = [
            s for s in self.sources
            if os.path.isdir(s) or norm_path(s) not in removed
        ]
        remaining = [p for p in self.queue.paths() if norm_path(p) not in removed]
        if not self.sources:
            self._clear_queue()
            return
        self.queue.set_files(remaining)
        self._update_queue_actions()

    def _reveal_source(self, path: str):
        if not reveal_in_file_manager(path):
            MessageBox.warning(self, APP_NAME, t("msg_open_location_failed", self.lang).format(path))

    def _open_source_file(self, path: str):
        if not os.path.exists(path) or not QDesktopServices.openUrl(QUrl.fromLocalFile(path)):
            MessageBox.warning(self, APP_NAME, t("msg_open_file_failed", self.lang).format(path))

    def _clear_queue(self):
        if self.worker and self.worker.isRunning():
            return
        self.sources = []
        self.skip_paths.clear()
        self.queue.set_files([])
        self.drop.set_status(t("not_selected", self.lang))
        self.drop.set_folder_open_visible(False)
        self.retry_btn.hide()
        self._show_progress(False)
        self.stats.setText("")
        self._sync_media_controls(False, False)
        self._update_queue_actions()

    def _pick_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, t("choose_file", self.lang),
            self.config.get("last_input") or "",
            f"{t('image', self.lang)}/{t('video', self.lang)} (*.jpg *.jpeg *.png *.mp4 *.mov *.mkv *.avi *.m4v);;{t('type_all', self.lang)} (*.*)",
        )
        if files:
            self._add_sources(files, replace=True)

    def _pick_folder(self):
        folder = QFileDialog.getExistingDirectory(self, t("choose_folder", self.lang), self.config.get("last_input") or "")
        if folder:
            self._add_sources([folder], replace=True)

    def _pick_output(self):
        folder = QFileDialog.getExistingDirectory(self, t("output_folder", self.lang), self.output_dir or default_output_dir())
        if folder:
            self.output_dir = folder
            self.output_manual = True
            self.out_label.setText(folder)
            self.config.set("last_output", folder)
            self._preview_queue()

    def _file_type(self) -> str:
        for name, btn in self.type_buttons.items():
            if btn.isChecked():
                return name
        return FILE_TYPE_ALL

    def _append_log(self, text: str, show_button: bool = True):
        self.log_box.append(text)
        log_info(text)
        if show_button:
            self._log_has_content = True
            self._update_queue_actions()

    def _ffmpeg_button_text(self) -> str:
        return t("download_ffmpeg" if self.ffmpeg.can_download() else "ffmpeg_recheck", self.lang)

    def _prepare_ffmpeg(self, download: bool):
        if self.prepare and self.prepare.isRunning():
            return
        self.gpu_label.setText(t("gpu_detecting", self.lang))
        self.gpu_label.setObjectName("hint_label")
        self.gpu_label.style().unpolish(self.gpu_label)
        self.gpu_label.style().polish(self.gpu_label)
        self.prepare = PrepareWorker(self.ffmpeg, download=download, lang=self.lang)
        self.prepare.log.connect(lambda t: self._append_log(t, show_button=False))
        self.prepare.progress.connect(self._on_prepare_progress)
        self.prepare.done.connect(self._on_prepared)
        self.prepare.failed.connect(lambda m: self._append_log(t("log_prepare_error", self.lang).format(m)))
        self.prepare.start()

    def _on_prepare_progress(self, p: float) -> None:
        if not self.worker:
            self.overall_label.setText("FFmpeg  ·  " + t("update_downloading", self.lang))
            self._show_progress(True)
        self.overall.setValue(int(p * 100))

    def _on_prepared(self, manager: FFmpegManager, gpu):
        self.ffmpeg = manager
        self.gpu = gpu
        if manager.is_ready():
            self.banner.hide()
        else:
            self.banner_label.setText(manager.missing_hint(self.lang))
            # Windows: "FFmpeg İndir"; macOS/Linux: indirme yok, kurulumdan sonra "Yeniden Tara".
            self.ffmpeg_btn.setText(self._ffmpeg_button_text())
            self.ffmpeg_btn.setVisible(True)
            self.banner.show()
        if gpu:
            self.gpu_label.setText(gpu.status_text())
            self.gpu_label.setObjectName("gpu_ok" if gpu.is_ok() else "gpu_warn")
            self.gpu_label.style().unpolish(self.gpu_label)
            self.gpu_label.style().polish(self.gpu_label)
            applying, restoring = self._applying_profile, self._restoring
            self._applying_profile = self._restoring = True
            self.adv_dialog.set_gpu_families(gpu.available_families())
            self.adv_dialog.set_gpu_choice(self.config.get("gpu_mode", "auto"))
            self._applying_profile, self._restoring = applying, restoring
            self._gpu_menu_ready = True
            self._refresh_codec_hint()
        else:
            self.gpu_label.setText(t("gpu_none_hint", self.lang))
        if not self.worker:
            self.overall.setValue(0)
            self._show_progress(False)

    def _collect_settings(self) -> dict | None:
        queued = self.queue.paths()
        if not queued:
            if not self.sources:
                self._append_log(t("no_files", self.lang))
            else:
                self._append_log(t("no_files", self.lang))
            return None
        output = self._effective_output()
        codec = CODEC_KEYS[self.codec.currentIndex()][0]
        bitrate = BITRATE_KEYS[self.bitrate.currentIndex()][0]
        gpu_mode = self.gpu.resolve_mode(self.adv_dialog.gpu_choice()) if self.gpu else "cpu"
        img_q = None if self.img_auto.isChecked() else int(self.img_quality.value())
        return {
            "sources": queued,
            "output_dir": output,
            "file_type": self._file_type(),
            "scan_subfolders": False,
            "ffmpeg_path": self.ffmpeg.ffmpeg_path,
            "ffprobe_path": self.ffmpeg.ffprobe_path,
            "gpu_mode": gpu_mode,
            "codec": codec,
            "bitrate": bitrate,
            "crf": int(self.crf.value()),
            "preset": self.preset.currentData() or "slow",
            "audio_bitrate": self.audio.currentText(),
            "video_res": _parse_video_res(res_value(self.video_res)),
            "image_res": _parse_custom_res(res_value(self.image_res)),
            "image_quality": img_q,
            "fps": self.adv_dialog.fps_value(),
            "remove_audio": self.adv_dialog.remove_audio.isChecked(),
            # Dosyaya özel istisnalar (sağ tık > İstisna uygula); iş sürerken de güncellenir.
            "overrides": {p: override_values(ov) for p, ov in self.queue.overrides().items()},
            "keep_order": True,
            "lang": self.lang,
        }

    def _start_stop(self):
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.start_btn.setText(t("stopping", self.lang))
            self.start_btn.setEnabled(False)
            return
        if self._installing:
            return  # güncelleme kuruluyor: uygulama birkaç saniye içinde yeniden başlayacak
        settings = self._collect_settings()
        if not settings:
            return
        need_video = self._file_type() in (FILE_TYPE_VIDEOS, FILE_TYPE_ALL)
        if need_video and not self.ffmpeg.is_ready():
            MessageBox.warning(
                self, APP_NAME,
                self.ffmpeg.needed_message(self.lang),
            )
            return
        self.output_dir = settings["output_dir"]
        files = settings["sources"]
        self.queue.set_files(files)
        self.retry_btn.hide()
        self.overall.setValue(0)
        self._show_progress(True)
        self._job_t0 = time.time()
        self._eta = JobEta([(p, self._eta_weight(p)) for p in files], self._job_t0)
        self.overall.setMaximum(OVERALL_STEPS)
        self._file_t0 = 0.0
        self._progress_done = 0
        self._progress_total = len(files)
        self.overall_label.setText(t("files_progress", self.lang).format(done=0, total=len(files)))
        self._file_ratio = 0.0
        self.stats.setText(t("stats_elapsed", self.lang).format(elapsed=f"0 {t('dur_s', self.lang)}"))
        self.open_when_done.show()
        self.start_btn.setText(t("stop_compression", self.lang))
        self.start_btn.setProperty("class", "danger")
        self.start_btn.style().unpolish(self.start_btn)
        self.start_btn.style().polish(self.start_btn)
        self._append_log(
            t("log_started", self.lang).format(
                codec=settings['codec'].upper(), bitrate=settings['bitrate'], gpu=settings['gpu_mode'],
            )
        )
        self.worker = JobWorker(settings)
        self.worker.log.connect(self._append_log)
        self.worker.progress.connect(self._on_progress)
        self.worker.file_started.connect(self._on_file_started)
        self.worker.file_progress.connect(self._on_file_progress)
        self.worker.file_done.connect(self._on_file_done)
        self.worker.finished_job.connect(self._on_job_finished)
        self.worker.start()
        self._update_queue_actions()

    def _on_progress(self, done: int, total: int):
        self._progress_done = done
        self._progress_total = total
        self.overall_label.setText(t("files_progress", self.lang).format(done=done, total=total))
        self._refresh_job_stats()

    def _on_file_started(self, path: str):
        self.queue.mark(path, "run")
        self._file_t0 = time.time()
        self._file_ratio = 0.0
        if self._eta is not None:
            self._eta.started(path, self._file_t0)
        if Path(path).suffix.lower() in VIDEO_EXTS:
            self.queue.set_progress(path, 0.0)  # satırda "%0" ve boş çizgi; resimlerde oran yok
        self._show_progress(True)

    def _on_file_progress(self, path: str, ratio: float):
        self._file_ratio = max(0.0, min(1.0, ratio))
        now = time.time()
        if self._eta is not None:
            self._eta.progress(path, self._file_ratio, now)
        remain = file_eta(now - self._file_t0, self._file_ratio) if self._file_t0 else None
        eta = format_duration(remain, self.lang) if remain is not None else ""  # ilk %1'den sonra
        if self.queue.status_of(path) == "run":  # bitiş sinyalinden sonra gelen 1.0 satırı yeniden açmasın
            self.queue.set_progress(path, self._file_ratio, eta)
        self._refresh_job_stats()

    def _refresh_job_stats(self):
        if not self._job_t0:
            return
        elapsed = time.time() - self._job_t0
        elapsed_str = format_duration(elapsed, self.lang)
        # Genel çubuk ve kalan süre iş miktarına göre (dosya sayısına göre değil): 4 küçük resim + 8 GB
        # videonun %33'ü "%5 bitti, kalan 3,5 saat" değil "%28 bitti, kalan ~30 dk" (bkz. core/eta.py).
        remain = None
        if self._eta is not None:
            if self.overall.maximum() != OVERALL_STEPS:
                self.overall.setMaximum(OVERALL_STEPS)
            fraction = self._eta.fraction()
            self.overall.setValue(int(fraction * OVERALL_STEPS))
            remain = self._eta.remaining()
            # ince çubukta yazı yok: yüzde, dosya sayısının yanında ("5/8 dosya · %62")
            files = t("files_progress", self.lang).format(done=self._progress_done, total=self._progress_total)
            self.overall_label.setText(f"{files}  ·  {t('pct', self.lang).format(int(fraction * 100))}")
        if remain is not None:
            remain_str = format_duration(max(0.0, remain), self.lang)
            self.stats.setText(
                t("stats_elapsed_remaining", self.lang).format(elapsed=elapsed_str, remaining=remain_str)
            )
        else:
            self.stats.setText(t("stats_elapsed", self.lang).format(elapsed=elapsed_str))

    def _on_overrides_changed(self) -> None:
        """Sağ tıkla verilen istisna, iş sürerken henüz başlamamış dosyalara da uygulanır."""
        if self.worker and self.worker.isRunning():
            self.worker.settings["overrides"] = {
                p: override_values(ov) for p, ov in self.queue.overrides().items()
            }

    def _on_file_done(self, path: str, status: str, extra):
        self.queue.mark(path, status, extra)
        if self._eta is not None:
            self._eta.finished(path, status, time.time())
            self._refresh_job_stats()

    def _on_job_finished(self, info: dict):
        self.start_btn.setEnabled(True)
        self.start_btn.setText(t("start_compression", self.lang))
        self.start_btn.setProperty("class", "primary")
        self.start_btn.style().unpolish(self.start_btn)
        self.start_btn.style().polish(self.start_btn)
        self._show_progress(True)
        if not info.get("cancelled") and self._eta is not None:
            self.overall.setValue(OVERALL_STEPS)
        self._job_t0 = 0.0
        self._eta = None
        self._file_t0 = 0.0
        self._file_ratio = 0.0
        cancelled = info.get("cancelled")
        ok, skip, fail = info.get("ok", 0), info.get("skip", 0), info.get("fail", 0)
        title = t("summary_cancelled", self.lang) if cancelled else t("summary_completed", self.lang)
        self.overall_label.setText(t("job_summary", self.lang).format(title=title, ok=ok, skip=skip, fail=fail))
        b_in, b_out = info.get("bytes_in", 0), info.get("bytes_out", 0)
        elapsed = info.get("elapsed", 0) or 0
        elapsed_txt = format_duration(elapsed, self.lang) if elapsed else ""
        if b_in > 0 and ok > 0:
            saved = b_in - b_out
            pct = (saved / b_in) * 100
            # "·" ayıracı ve dile göre yüzde ("-%74.5" / "-74.5%"): iş sürerken gösterilen satırla aynı biçim
            line = (
                f"{format_bytes(b_in)} → {format_bytes(b_out)}  ·  "
                f"{t('saved', self.lang)} {format_bytes(saved)} (-{t('pct', self.lang).format(f'{pct:.1f}')})"
            )
            if elapsed_txt:
                line += f"  ·  {t('duration', self.lang)} {elapsed_txt}"
            self.stats.setText(line)
            self._append_log(self.stats.text())
        elif elapsed_txt:
            self.stats.setText(f"{t('duration', self.lang)} {elapsed_txt}")
        else:
            self.stats.setText("")
        if fail:
            self.retry_btn.show()
        self._update_queue_actions()
        if self.open_when_done.isChecked():
            self._open_output()
        self.open_when_done.hide()
        # Ayar (show_notifications) Notifier'ın enabled_provider'ında gözetilir; tek yol Qt'nin tepsi bildirimi (+ macOS/Linux yedekleri)
        self.notifier.notify(get_app_name(self.lang), self.overall_label.text())
        # Zorunlu güncelleme, iş iptal edilmiş olsa bile atlanmaz (eskiden `not cancelled`
        # koşulu zorunlu kurulumu/diyaloğu sessizce atlıyordu).
        pending_install = getattr(self, "_pending_install", None)
        if should_install_pending(bool(pending_install), bool(cancelled), self._pending_install_mandatory):
            self._pending_install = None
            self._pending_install_mandatory = False
            self._begin_install(pending_install, check_busy=False)  # iş az önce bitti (işçi iş parçacığı henüz çıkmamış olabilir)
            return
        if getattr(self, "_pending_install", None) and self.update_dialog is not None:
            # İsteğe bağlı paket inmiş, iş iptal edildi: kendiliğinden kurulmaz; pencere "bekliyor"da kalıp kullanıcıyı
            # çıkışsız bırakmasın ("Şimdi Güncelle" yeniden indirmeden kurar, "Daha Sonra" erteler).
            self.update_dialog.show_ready()
        pending_mandatory = bool(self._pending_update and self._pending_update[3])
        # İsteğe bağlı güncelleme için pop-up yok: Ayarlar'daki düğme ve tepsi satırı durur; zorunlu olan arka planda indirilip
        # kurulur. `_pending_update` SİLİNMEZ: indirme başarısız olursa düğme/tepsi satırı yeniden denemek için çalışsın.
        if pending_mandatory and should_show_pending_update(bool(self._pending_update), bool(cancelled), pending_mandatory):
            self._begin_silent_update(self._pending_update, mandatory=True)

    def _retry_failed(self):
        failed = self.queue.failed_paths()
        if not failed:
            return
        self.skip_paths.clear()
        self.sources = failed
        self.output_manual = True
        self._start_stop()

    def _effective_output(self) -> str:
        return self.output_dir or default_output_dir()

    def _open_output(self):
        path = self._effective_output()
        try:
            os.makedirs(path, exist_ok=True)
        except OSError as exc:
            MessageBox.warning(self, APP_NAME, t("msg_create_folder_failed", self.lang).format(path, exc))
            return
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(path)):
            MessageBox.warning(self, APP_NAME, t("msg_open_folder_failed", self.lang).format(path))

    def pending_update_version(self) -> str:
        """Bekleyen (sunulmuş, henüz kurulmamış) güncellemenin sürümü; yoksa boş. Tepsi satırı menü her açıldığında buradan okur."""
        pending = self._pending_update
        return str(pending[0]) if pending else ""

    def _sync_update_indicators(self) -> None:
        """Başlıktaki ↑, açık Ayarlar penceresindeki "Güncelle · vX" düğmesi ve tepsi satırı bekleyen güncellemeyle
        aynı durumda olsun."""
        version = self.pending_update_version()
        self.title_bar.set_update_available(version)
        for dialog in self.findChildren(SettingsDialog):
            dialog.show_pending_update(version)
        if self.tray:
            self.tray.set_update_available(bool(version), version)

    def _job_running(self) -> bool:
        return bool(self.worker and self.worker.isRunning())

    def _on_update_available(self, version, url, notes, mandatory, size, checksum):
        """Sessiz denetim yeni sürüm buldu: pop-up AÇILMAZ. Sürüm Ayarlar'daki "Güncelle" düğmesinde ve
        tepside görünür; "otomatik kur" açıksa uygulama kullanılmıyorken kendiliğinden kurulur."""
        payload = (version, url, notes, mandatory, size, checksum)
        self._pending_update = payload
        self._sync_update_indicators()
        if mandatory:
            if self._job_running():
                return  # iş bitince (_on_job_finished) arka planda indirilip kurulur
            self._begin_silent_update(payload, mandatory=True)
            return
        self._schedule_auto_update()

    # ------------------------------------------------------------------ otomatik kurulum (kullanılmıyorken)
    AUTO_UPDATE_POLL_MS = 30_000

    @staticmethod
    def update_is_idle(job_running: bool, window_shown: bool, modal_open: bool, queue_count: int) -> bool:
        """Uygulama "kullanılmıyor" mu: iş sürüyorsa, kuyrukta dosya varsa, diyalog açıksa ya da pencere
        ekrandaysa (gizli/simge durumunda değilse) değil (kurulum uygulamayı kısa süre yeniden başlatır)."""
        if job_running or modal_open or queue_count > 0:
            return False
        return not window_shown

    def _is_idle_for_update(self) -> bool:
        return self.update_is_idle(
            self._job_running(),
            self.isVisible() and not self.isMinimized(),
            QApplication.activeModalWidget() is not None or self.update_dialog is not None,
            self.queue.rowCount(),
        )

    def _auto_update_enabled(self) -> bool:
        return bool(self.config.get("auto_update_check", True) and self.config.get("auto_update_install", True))

    def _schedule_auto_update(self):
        if not self._auto_update_enabled():
            return
        if self._auto_update_timer is None:
            self._auto_update_timer = QTimer(self)
            self._auto_update_timer.timeout.connect(self._try_auto_update)
        if not self._auto_update_timer.isActive():
            self._auto_update_timer.start(self.AUTO_UPDATE_POLL_MS)
        QTimer.singleShot(3000, self._try_auto_update)

    def _stop_auto_update_timer(self):
        if self._auto_update_timer is not None:
            self._auto_update_timer.stop()

    def _try_auto_update(self):
        payload = self._pending_update
        if not payload:
            return
        if not self._auto_update_enabled():
            self._stop_auto_update_timer()
            return
        if self._update_busy():
            return
        if not payload[3] and self.config.get("declined_update_version") == payload[0]:
            # Kullanıcı bu sürüme "Sonra" dedi (ya da indirmeyi iptal etti): kendiliğinden kurulmaz.
            # Satır/pill kalır, elle kurulabilir; daha yeni bir sürüm yine otomatik kurulur.
            log_info("Kullanıcı bu güncellemeyi erteledi: otomatik kurulmayacak (düğmeyle elle kurulabilir)")
            self._stop_auto_update_timer()
            return
        if normalize_checksum(payload[5]) is None:
            # Onaysız kurulumu kimse görmeden yapma: sunucu sağlama toplamı vermediyse yalnızca düğmeyle kurulur.
            log_info("Güncelleme sağlama toplamı içermiyor: otomatik kurulmayacak (düğmeyle elle kurulabilir)")
            self._stop_auto_update_timer()
            return
        if not self.installer.install_support()[0]:
            log_info("Otomatik kurulum bu çalışmada desteklenmiyor (paketlenmiş Windows uygulaması değil)")
            self._stop_auto_update_timer()
            return
        if not self._is_idle_for_update():
            return
        self._stop_auto_update_timer()
        log_info("Uygulama kullanılmıyor: güncelleme sessizce kuruluyor")
        self._start_silent_update()

    def _start_silent_update(self):
        payload = self._pending_update
        if payload:
            self._begin_silent_update(payload, mandatory=False)

    def _begin_silent_update(self, payload, mandatory: bool):
        """Pencere açmadan indir + kur: zorunlu güncelleme ve "otomatik kur". Hata olursa tepsi balonu (pill/satır kalır)."""
        version, url, _notes, _mandatory, size, checksum = payload
        self._upd = (url, size, checksum)
        self._upd_mandatory = bool(mandatory)
        self._start_download()

    def _notify_silent_failure(self, err: str):
        """Arka plan güncellemesi başarısız: pop-up yok; günlük + tepsi balonu (düğme yeniden denemek için durur)."""
        log_info(f"Sessiz güncelleme başarısız: {err}")
        if self.tray:
            self.tray.notify(get_app_name(self.lang), t("update_auto_failed", self.lang))

    # ------------------------------------------------------------------ güncelleme penceresi
    def _show_update_dialog(self, version, url, notes, mandatory, size, checksum):
        """Kullanıcı istedi (tepsi satırı / Ayarlar'daki düğme): sürüm, boyut ve notları göster. Doğrudan kurmaz."""
        self._upd = (url, size, checksum)
        self._upd_mandatory = bool(mandatory)
        dialog = UpdateDialog(version, notes, bool(mandatory), self, lang=self.lang, size=size)
        dialog.update_accepted.connect(self._start_download)
        dialog.update_deferred.connect(self._on_update_declined)
        dialog.update_cancelled.connect(self._cancel_update_download)
        dialog.finished.connect(lambda *_args, d=dialog: self._on_update_dialog_closed(d))
        self.update_dialog = dialog
        # Pencere, arka planda (sessiz) sürmekte olan bir indirme/kurulumun ortasında açılmış olabilir.
        if self._installing:
            dialog.show_installing()
        elif self._pending_install:
            if self._job_running():
                dialog.show_waiting_for_job()
            # iş yok ama paket inmiş (iptal edilen işten sonra): pencere hazır durumda açılır, "Şimdi Güncelle" kurar
        elif self._download_active():
            dialog.show_downloading()
        dialog.open()
        self._raise_update_dialog(dialog)

    def _raise_update_dialog(self, dialog) -> None:
        """Ana pencere gizli (tepside) olsa da güncelleme penceresi öne gelsin."""
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _on_update_dialog_closed(self, dialog) -> None:
        if self.update_dialog is dialog:
            self.update_dialog = None
        dialog.deleteLater()

    def show_pending_update(self):
        """Tepsi satırı / Ayarlar'daki düğme: bekleyen güncellemenin penceresini aç (zaten açıksa öne getir)."""
        if not self._pending_update:
            return
        if self.update_dialog is not None:
            self._raise_update_dialog(self.update_dialog)
            return
        self._show_update_dialog(*self._pending_update)

    # ------------------------------------------------------------------ indirme
    def _download_active(self) -> bool:
        thread = self._dl_thread
        return bool(self._download_wanted and thread is not None and thread.isRunning())

    def _update_busy(self) -> bool:
        """İndirme ya da kurulum sürüyor: ikinci bir başlatma yapılmaz."""
        return bool(self._installing or self._download_active())

    def _start_download(self):
        """Güncellemeyi indirmeye başla (Şimdi Güncelle / Tekrar dene / otomatik). Aynı anda tek indirme."""
        if self._update_busy() or not self._upd:
            return
        if self._pending_install:
            # Paket zaten inmiş (sıkıştırma sürerken): yeniden indirmeden, iş yoksa şimdi kur.
            if self._job_running():
                if self.update_dialog is not None:
                    self.update_dialog.show_waiting_for_job()
            else:
                path, self._pending_install = self._pending_install, None
                self._pending_install_mandatory = False
                self._begin_install(path)
            return
        ok, message = self.installer.preflight()  # yazılamayan klasör / kaynaktan çalışma: indirme boşa gitmesin
        if not ok:
            self._update_failed(message)
            return
        url, size, checksum = self._upd
        self._download_wanted = True
        self._dl_thread = DownloadThread(self.installer, url, size, checksum)
        self._dl_thread.start()

    def _on_dl_progress(self, downloaded, total, speed):
        if self.update_dialog:
            self.update_dialog.update_download_progress(downloaded, total, speed)

    def _on_dl_complete(self, path: str):
        if not self._download_wanted:
            # Kullanıcı iptal etti (sinyal geç kalmış olabilir): habersiz kurulmasın.
            self.installer.cleanup()
            return
        self._download_wanted = False
        if self._job_running():
            self._pending_install = path
            self._pending_install_mandatory = self._upd_mandatory
            if self.update_dialog:
                self.update_dialog.show_waiting_for_job()
            return
        self._begin_install(path)

    def _begin_install(self, path: str, check_busy: bool = True):
        """Paket hazır: kurulumu arka planda başlat. Kurulumdan hemen önce meşguliyet YENİDEN denetlenir (sıkıştırma
        başladıysa kurma, bitmesini bekle). `check_busy=False`: iş az önce bittiği bilinen çağıran (işçi iş parçacığı
        sinyali yayınladıktan hemen sonra hâlâ "çalışıyor" görünebilir)."""
        if check_busy and self._job_running():
            self._pending_install = path
            self._pending_install_mandatory = self._upd_mandatory
            if self.update_dialog:
                self.update_dialog.show_waiting_for_job()
            return
        self._installing = True
        visible = self.isVisible() and not self.isMinimized()
        self.installer.install_update(path, visible=visible, old_version=VERSION)

    def _on_dl_failed(self, err: str):
        if err == "cancelled":
            return
        self._update_failed(err)

    def _on_install_started(self):
        if self.update_dialog:
            self.update_dialog.show_installing()

    def _on_install_complete(self):
        """Yeni sürüm başlatıldı ve bizi bekliyor (--wait-pid): zorla öldürme yok, TEMİZ çıkış."""
        QTimer.singleShot(0, self._quit_for_update)

    def _quit_for_update(self):
        """Temiz çıkış (kapanış işleri + aboutToQuit). Kurulum sırasında açık "Güncelleme" penceresi kapanmayı reddeder ve Qt 6'da
        `quit()` görünür pencereleri kapatmayı dener: reddeden olursa çıkış İPTAL olur (E2E'de eski süreç sonsuza dek yaşadı).
        `exit(0)` pencerelerden bağımsızdır; çıkış yine de takılırsa sert çıkış (yeni sürüm bizi bekliyor)."""
        self.force_quit()
        QCoreApplication.exit(0)
        if getattr(sys, "frozen", False):
            self_update.arm_exit_watchdog()

    def _on_install_failed(self, err: str):
        self._installing = False
        self._update_failed(err)

    def _update_failed(self, message: str):
        """Güncelleme başarısız: pencere açıksa hata ORADA (satır içi + Tekrar dene, QMessageBox yok); arka planda
        sürüyorsa tepsi balonu. Bekleyen güncelleme silinmez: düğme/satır yeniden denemek için çalışır."""
        log_info(f"Güncelleme başarısız: {message}")
        self._download_wanted = False
        if self.update_dialog is not None:
            self.update_dialog.show_error(message)
        else:
            self._notify_silent_failure(message)

    def _on_update_declined(self):
        """Kullanıcı "Sonra" dedi ya da pencereyi kapattı (indirme sırasında iptal bu sayılmaz)."""
        self._defer_update()

    def _defer_update(self):
        if self._pending_update:
            self.config.set("declined_update_version", self._pending_update[0])
            self._sync_update_indicators()

    def _cancel_update_download(self):
        """Pencere kapatıldı/İptal: indirme durur ve dosyası silinir; iptal edilen indirme sonradan kurulmaz."""
        self._download_wanted = False
        self._defer_update()
        self.installer.cancel_download()
        self.installer.cleanup()

    def show_updated_notice(self, old_version: str = ""):
        """Güncellemeden sonra yeni sürüm açıldı (`--updated <eski>`): "vX sürümüne güncellendi" bildirimi."""
        if not self.config.get("show_notifications", True) or (old_version and old_version == VERSION):
            return
        title = get_app_name(self.lang)
        text = t("update_installed_toast", self.lang).format(app=title, version=VERSION)
        self.notifier.notify(title, text)

    def _bring_to_front(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _hide_tray(self):
        if not self.tray:
            return
        self.tray.hide()
        self.tray.setContextMenu(None)
        self.tray.deleteLater()
        self.tray = None

    def _shutdown_background(self):
        """Güvenli kapanış: önce hepsine iptal bayrağı, sonra ortak süre bütçesiyle bekle.

        İşçiler daemon thread'dir; süre dolsa bile süreç QThread yıkım çökmesi olmadan
        çıkar, ffmpeg çocukları ise Job Object ile (Windows) süreçle birlikte ölür.
        """
        entries = []
        if self.worker is not None:
            entries.append(("iş", self.worker, self.worker.stop))
        if self.prepare is not None:
            entries.append(("ffmpeg hazırlığı", self.prepare, self.prepare.stop))
        if self._dl_thread is not None:
            entries.append(("güncelleme indirme", self._dl_thread, self._dl_thread.stop))
        installing = getattr(self.installer, "_install_worker", None)
        if installing is not None:  # exe değiştirilirken çıkılırsa dosya yarım kalabilir: bitmesi beklenir (durdurulmaz)
            entries.append(("güncelleme kurulumu", installing, lambda: None))
        still = shutdown_workers(entries, timeout_ms=SHUTDOWN_WAIT_MS)
        if still:
            log_info("Kapanışta hâlâ çalışan işçiler (daemon, süreçle sonlanacak): " + ", ".join(still))

    def force_quit(self):
        if self._quitting:
            return
        self._quitting = True
        self._hide_tray()
        self.hide()  # bekleme sırasında pencere donmuş görünmesin
        self._shutdown_background()
        try:
            self._save_choices()
            self.config.set("file_type", self._file_type())
        except Exception:
            pass
        app = QApplication.instance()
        if app:
            app.quit()

    def showEvent(self, event):
        super().showEvent(event)
        if sys.platform == "win32":
            try:
                import ctypes
                hwnd = int(self.winId())
                ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, 33, ctypes.byref(ctypes.c_int(2)), ctypes.sizeof(ctypes.c_int)
                )
            except Exception:
                pass

    def closeEvent(self, event):
        from PyQt6.QtGui import QGuiApplication
        gui_app = QGuiApplication.instance()
        saving_session = bool(gui_app is not None and gui_app.isSavingSession())  # Windows kapanıyor
        if (
            not self._quitting and not saving_session
            and self.tray and TrayIcon.isSystemTrayAvailable()
        ):
            event.ignore()
            self.hide()
            return
        already = self._quitting
        self._quitting = True
        self._hide_tray()
        if not already:
            self.hide()
            self._shutdown_background()
            try:
                self._save_choices()
                self.config.set("file_type", self._file_type())
            except Exception:
                pass
        event.accept()
        if not already:
            app = QApplication.instance()
            if app:
                QTimer.singleShot(0, app.quit)
