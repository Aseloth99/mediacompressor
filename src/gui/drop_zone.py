"""Sürükle-bırak alanı — sabit yükseklik, taşmaz."""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QDragEnterEvent, QDropEvent
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout

from ..utils.helpers import local_paths_from_drop
from ..utils.locales import t


class DropZone(QFrame):
    files_dropped = pyqtSignal(list)
    select_files = pyqtSignal()
    select_folder = pyqtSignal()
    open_folder = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("DropZone")
        self.setAcceptDrops(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.lang = "tr"
        self._has_custom_status = False
        self._status_full = t("not_selected", self.lang)

        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(12, 12, 12, 12)

        self.hint_text = QLabel(t("drop_hint", self.lang))
        self.hint_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hint_text.setObjectName("hint_label")
        self.hint_text.setWordWrap(True)
        layout.addWidget(self.hint_text)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.folder_btn = QPushButton(t("choose_folder", self.lang))
        self.folder_btn.setProperty("class", "primary")
        self.folder_btn.setMinimumHeight(34)
        self.folder_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.folder_btn.clicked.connect(self.select_folder.emit)
        self.files_btn = QPushButton(t("choose_file", self.lang))
        self.files_btn.setProperty("class", "primary")
        self.files_btn.setMinimumHeight(34)
        self.files_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.files_btn.clicked.connect(self.select_files.emit)
        row.addWidget(self.folder_btn, 1)
        row.addWidget(self.files_btn, 1)
        layout.addLayout(row)

        status_row = QHBoxLayout()
        status_row.setSpacing(8)
        status_row.setContentsMargins(0, 0, 0, 0)
        self.status = QLabel(self._status_full)
        self.status.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        self.status.setObjectName("hint_label")
        self.status.setWordWrap(False)
        self.status.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.open_folder_btn = QPushButton(t("open_folder", self.lang))
        self.open_folder_btn.setProperty("class", "ghost-mini")
        self.open_folder_btn.style().unpolish(self.open_folder_btn)
        self.open_folder_btn.style().polish(self.open_folder_btn)
        self.open_folder_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.open_folder_btn.clicked.connect(self.open_folder.emit)
        self.open_folder_btn.hide()
        status_row.addWidget(self.status, 1)
        status_row.addWidget(self.open_folder_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(status_row)

    def retranslate(self, lang: str = "tr"):
        self.lang = lang
        self.hint_text.setText(t("drop_hint", lang))
        self.folder_btn.setText(t("choose_folder", lang))
        self.files_btn.setText(t("choose_file", lang))
        self.open_folder_btn.setText(t("open_folder", lang))
        if not self._has_custom_status:
            self._status_full = t("not_selected", lang)
            self._elide_status()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._elide_status()

    def set_status(self, text: str):
        self._has_custom_status = bool(text)
        self._status_full = text or t("not_selected", self.lang)
        self._elide_status()

    def set_folder_open_visible(self, visible: bool):
        self.open_folder_btn.setVisible(visible)
        self._elide_status()

    def _elide_status(self):
        width = max(self.status.width() - 8, 60)
        self.status.setText(
            self.status.fontMetrics().elidedText(
                self._status_full, Qt.TextElideMode.ElideMiddle, width
            )
        )
        self.status.setToolTip(self._status_full)

    @staticmethod
    def _dropped_paths(mime) -> list[str]:
        # file:// URL'leri (Windows/macOS/çoğu Linux yöneticisi); URL yoksa düz metin dosya yolları.
        return local_paths_from_drop(mime.urls(), mime.text() if mime.hasText() else "")

    def dragEnterEvent(self, event: QDragEnterEvent):
        mime = event.mimeData()
        if mime.hasUrls() or (mime.hasText() and self._dropped_paths(mime)):
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        paths = self._dropped_paths(event.mimeData())
        if paths:
            self.files_dropped.emit(paths)
        event.acceptProposedAction()
