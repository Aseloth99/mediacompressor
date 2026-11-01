"""Güncelleme penceresi: sürüm, boyut, sürüm notları -> indirme -> kurulum; hata pencerede satır içi gösterilir.

Durumlar: IDLE (Daha Sonra / Şimdi Güncelle) -> DOWNLOADING (ilerleme + hız + İptal) -> INSTALLING (Kuruluyor…) ya da
WAITING (sıkıştırma sürüyor, bitince kurulacak); hata olursa ERROR (kırmızı satır + Tekrar dene), pencere AÇIK kalır.
İndirme sürerken Esc/X = indirmeyi iptal et ve kapat; kurulum başladıktan sonra pencere kapatılamaz.
"""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QProgressBar, QPushButton, QSizePolicy, QTextEdit, QVBoxLayout,
)

from ..core.app_info import VERSION
from ..utils.helpers import format_bytes, format_speed
from ..utils.locales import get_app_name, t
from .chrome_dialog import ChromeDialog


def _set_notes(box, notes: str, default: str) -> None:
    """Sürüm notları HTML ise HTML olarak, düz metinse satır sonları korunarak gösterilir (setHtml satırları birleştirirdi)."""
    import re

    from PyQt6.QtCore import Qt as _Qt
    text = notes or ""
    # PyQt6 Qt.mightBeRichText'i ad alanına yalnızca bazı yükleme sıralarında ekliyor (testlerde
    # AttributeError); yoksa aynı kaba kontrol: metinde bir HTML etiketi var mı.
    might_be_rich = getattr(_Qt, "mightBeRichText", None)
    if not text.strip():
        box.setHtml(default)
    elif might_be_rich(text) if might_be_rich else re.search(r"</?[A-Za-z][\w-]*(\s[^<>]*)?/?>", text):
        box.setHtml(text)
    else:
        box.setPlainText(text)


class UpdateDialog(ChromeDialog):
    IDLE = "idle"
    DOWNLOADING = "downloading"
    WAITING = "waiting"      # indirildi; sıkıştırma bitince kurulacak
    INSTALLING = "installing"
    ERROR = "error"

    update_accepted = pyqtSignal()   # Şimdi Güncelle / Tekrar dene
    update_deferred = pyqtSignal()   # Daha Sonra (ya da pencereyi kapatma)
    update_cancelled = pyqtSignal()  # indirme sürerken İptal / Esc / X

    def __init__(
        self, version: str, release_notes: str, is_mandatory: bool = False,
        parent=None, lang: str = "tr", size: int = 0,
    ):
        super().__init__(parent)
        self.lang = lang
        self.version = version
        self.is_mandatory = is_mandatory
        self.state = self.IDLE
        self.setWindowTitle(t("update_dialog_title", self.lang))
        self.setMinimumWidth(520)  # yükseklik yerleşimden gelir: sabit asgari yükseklik hata/notlar uzayınca kırpardı
        self.resize(560, 460)
        self.setModal(True)

        layout = QVBoxLayout(self.body_host)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)

        self.title = QLabel(t("update_available_title", self.lang).format(get_app_name(self.lang), f"v{version}"))
        self.title.setObjectName("dialog_header")
        self.title.setWordWrap(True)
        layout.addWidget(self.title)

        self.version_line = QLabel(t("update_version_line", self.lang).format(f"v{VERSION}", f"v{version}"))
        self.version_line.setWordWrap(True)
        layout.addWidget(self.version_line)

        self.size_line = QLabel()
        self.size_line.setObjectName("hint_label")
        self.size_line.setWordWrap(True)
        try:
            size = int(size or 0)
        except (TypeError, ValueError):
            size = 0
        if size > 0:
            self.size_line.setText(t("update_size_line", self.lang).format(size=format_bytes(size)))
        self.size_line.setVisible(size > 0)
        layout.addWidget(self.size_line)

        self.notes = QTextEdit()
        self.notes.setReadOnly(True)
        self.notes.setMinimumHeight(110)
        _set_notes(self.notes, release_notes, t("update_notes_default", self.lang))
        layout.addWidget(self.notes, 1)

        self.progress_bar = QProgressBar()
        self.progress_bar.setMinimumHeight(18)
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)
        self.progress_label = QLabel()
        self.progress_label.setVisible(False)
        self.progress_label.setWordWrap(True)
        self.progress_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.progress_label)
        self.status_label = QLabel()
        self.status_label.setVisible(False)
        self.status_label.setWordWrap(True)
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.status_label)

        # Satır içi hata: QMessageBox yok; çerçeve kenarlığı çizer, boşluğu yerleşim verir (sarmalı etiket kırpılmasın).
        self.error_box = QFrame()
        self.error_box.setObjectName("update_error_box")
        error_row = QVBoxLayout(self.error_box)
        error_row.setContentsMargins(12, 10, 12, 10)
        self.error_label = QLabel()
        self.error_label.setObjectName("banner_error")
        self.error_label.setWordWrap(True)
        self.error_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.error_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        error_row.addWidget(self.error_label)
        self.error_box.setVisible(False)
        layout.addWidget(self.error_box)

        buttons = QHBoxLayout()
        self.cancel_btn = QPushButton(t("cancel", self.lang))
        self.cancel_btn.setAutoDefault(False)
        self.cancel_btn.clicked.connect(self.reject)
        buttons.addWidget(self.cancel_btn)
        buttons.addStretch()
        self.later_btn = QPushButton(t("update_later", self.lang))
        self.later_btn.setAutoDefault(False)
        self.later_btn.clicked.connect(self.reject)
        buttons.addWidget(self.later_btn)
        self.close_btn = QPushButton(t("update_close", self.lang))
        self.close_btn.setAutoDefault(False)
        self.close_btn.clicked.connect(self.reject)
        buttons.addWidget(self.close_btn)
        self.update_btn = QPushButton(t("update_now", self.lang))
        self.update_btn.setProperty("class", "primary")
        self.update_btn.setDefault(True)
        self.update_btn.clicked.connect(self._on_update)
        buttons.addWidget(self.update_btn)
        layout.addLayout(buttons)

        self._set_state(self.IDLE)

    # ------------------------------------------------------------------ durumlar
    def _set_state(self, state: str) -> None:
        self.state = state
        idle, error = state == self.IDLE, state == self.ERROR
        downloading = state == self.DOWNLOADING
        self.cancel_btn.setVisible(downloading)
        self.later_btn.setVisible((idle or error) and not self.is_mandatory)
        self.update_btn.setVisible(idle or error)
        self.update_btn.setText(t("update_retry" if error else "update_now", self.lang))
        self.close_btn.setVisible(state == self.WAITING)
        self.progress_bar.setVisible(downloading)
        self.progress_label.setVisible(downloading)
        self.status_label.setVisible(state in (self.INSTALLING, self.WAITING))
        self.error_box.setVisible(error)

    def _on_update(self):
        self.show_downloading()
        self.update_accepted.emit()  # ana pencere reddederse (ön denetim) show_error ile durumu değiştirir

    def show_downloading(self) -> None:
        self.progress_bar.setRange(0, 0)  # ilk ilerleme gelene dek belirsiz
        self.progress_label.setText(t("update_downloading", self.lang))
        self._set_state(self.DOWNLOADING)

    def show_installing(self) -> None:
        self.status_label.setText(t("update_installing", self.lang))
        self._set_state(self.INSTALLING)

    def show_waiting_for_job(self) -> None:
        self.status_label.setText(t("msg_install_after_done", self.lang))
        self._set_state(self.WAITING)
        self.close_btn.setFocus()

    def show_ready(self) -> None:
        """Paket indirildi ama kurulum otomatik başlamayacak (sıkıştırma iptal edildi): kullanıcı "Şimdi Güncelle" ile
        (yeniden indirmeden) kurabilir ya da "Daha Sonra" diyebilir; pencere çıkışsız kalmaz."""
        self._set_state(self.IDLE)
        self.update_btn.setFocus()

    def show_error(self, message: str) -> None:
        self.error_label.setText(t("update_failed_inline", self.lang).format(error=message))
        self._set_state(self.ERROR)
        self.update_btn.setFocus()

    def update_download_progress(self, downloaded, total, speed_mbps: float):
        if self.state != self.DOWNLOADING:
            return
        speed = format_speed(speed_mbps) if speed_mbps > 0 else ""
        if total and total > 0:
            percent = min(int((downloaded / total) * 100), 100)
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(percent)
            text = f"{format_bytes(downloaded)} / {format_bytes(total)} ({percent}%)"
        else:
            self.progress_bar.setRange(0, 0)
            text = t("update_downloaded_bytes", self.lang).format(format_bytes(downloaded))
        if speed:
            text += f" — {speed}"
        self.progress_label.setText(text)

    def reject(self):
        """Esc / X / Daha Sonra / İptal. Kurulum başladıysa kapanmaz; indirme sürüyorsa iptal edilir (indirme arka
        planda sürüp pencere kapandıktan sonra uygulamayı habersiz yeniden başlatmasın)."""
        if self.state == self.INSTALLING:
            return
        if self.state == self.DOWNLOADING:
            self.update_cancelled.emit()
        elif self.state in (self.IDLE, self.ERROR) and not self.is_mandatory:
            self.update_deferred.emit()
        super().reject()
