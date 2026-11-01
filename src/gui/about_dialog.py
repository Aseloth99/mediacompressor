"""Hakkında penceresi (F1 ve Ayarlar > Hakkında): özel başlık çubuklu, tema renkli."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel, QPushButton, QVBoxLayout

from ..core.app_info import VERSION
from ..utils.locales import get_app_name, t
from ..utils.remote_notice import SITE_URL
from .chrome_dialog import ChromeDialog
from .notice_bar import LinkLabel


class AboutDialog(ChromeDialog):
    def __init__(self, parent=None, lang: str = "tr"):
        super().__init__(parent)
        self.lang = lang
        self.setWindowTitle(t("about", lang))
        self.setMinimumWidth(400)

        lay = QVBoxLayout(self.body_host)
        lay.setContentsMargins(22, 18, 22, 18)
        lay.setSpacing(10)

        self.title_label = QLabel(get_app_name(lang))
        self.title_label.setObjectName("about_title")
        lay.addWidget(self.title_label)

        self.version_label = QLabel(t("about_version_line", lang).format(VERSION))
        self.version_label.setObjectName("hint_label")
        lay.addWidget(self.version_label)

        self.desc_label = QLabel(t("about_desc", lang))
        self.desc_label.setWordWrap(True)  # donanım hızlandırma satırı dar pencerede sarılsın
        lay.addWidget(self.desc_label)

        self.link = LinkLabel("macik.com.tr", SITE_URL)
        lay.addWidget(self.link, 0, Qt.AlignmentFlag.AlignLeft)
        lay.addSpacing(6)

        self.ok_btn = QPushButton(t("ok", lang))
        self.ok_btn.setProperty("class", "primary")
        self.ok_btn.setDefault(True)
        self.ok_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.ok_btn.clicked.connect(self.accept)
        lay.addWidget(self.ok_btn, 0, Qt.AlignmentFlag.AlignRight)
