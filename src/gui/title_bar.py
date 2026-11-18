"""Frameless pencere başlığı — TransferTCP ölçüleri (38 px)."""

from __future__ import annotations

from PyQt6.QtCore import QPoint, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QAction, QActionGroup, QFont, QIcon
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QMenu, QPushButton, QWidget

from ..core.app_info import APP_NAME, VERSION
from ..utils.locales import create_language_icon, get_app_name, language_choices, t
from ..utils.theme_manager import ACCENTS
from . import icons

THEME_KEYS = ("system", "dark", "light")
TITLE_BAR_HEIGHT = 38  # tüm uygulamalarda aynı başlık çubuğu yüksekliği
# Menüde ad ile kısayol arasına eklenen boşluk: Qt'nin kendi payı (~12 px) "Klasör Seç…Ctrl+Shift+O"
# gibi bitişik okunuyordu. Kısayol sütunu sola hizalı çizildiği için hepsi aynı yerden başlar.
SHORTCUT_GAP = " " * 6


def menu_text(label: str, keys: str) -> str:
    """Menü satırı: "ad<TAB>boşluk+kısayol" (kısayolu ana pencere bağlar; metin yalnızca bilgi)."""
    return f"{label}\t{SHORTCUT_GAP}{keys}"

_THEME_ICONS = {
    "system": icons.theme_system_icon,
    "dark": icons.theme_dark_icon,
    "light": icons.theme_light_icon,
}


def _color_swatch_icon(hex_color: str) -> QIcon:
    return icons.swatch_icon(hex_color)


def _globe_icon(color_hex: str = icons.DEFAULT_ICON_COLOR, size: int = 20) -> QIcon:
    return icons.globe_icon(color_hex, size)


def _chrome_font(size: int) -> QFont:
    font = QFont("Segoe UI")
    font.setPointSize(size)
    font.setWeight(QFont.Weight.Light)
    return font


class TitleBar(QFrame):
    theme_selected = pyqtSignal(str)
    accent_selected = pyqtSignal(str)
    language_selected = pyqtSignal(str)
    settings_clicked = pyqtSignal()
    help_clicked = pyqtSignal()
    minimize_clicked = pyqtSignal()
    maximize_clicked = pyqtSignal()
    close_clicked = pyqtSignal()
    add_files_clicked = pyqtSignal()    # Dosya > Dosya Ekle…
    add_folder_clicked = pyqtSignal()   # Dosya > Klasör Ekle…
    exit_clicked = pyqtSignal()         # Dosya > Çıkış (gerçekten çıkar; X tepsiye gizler)

    def __init__(self, parent=None, icon: QIcon | None = None):
        super().__init__(parent)
        self.setObjectName("title_bar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedHeight(TITLE_BAR_HEIGHT)
        self._drag_pos: QPoint | None = None
        self._window = parent
        self._theme_actions: dict[str, QAction] = {}
        self._accent_actions: dict[str, QAction] = {}
        self._lang_actions: dict[str, QAction] = {}
        self._lang = "tr"
        self._icon_color = icons.DEFAULT_ICON_COLOR
        self._danger_color = "#ef4444"
        self._accent_key = ""

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 6, 0)
        layout.setSpacing(0)
        layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        # Sol grup (İkon + Başlık + Versiyon)
        self.left_box = QWidget()
        self.left_box.setObjectName("title_left_box")
        self.left_box.setStyleSheet("QWidget#title_left_box { background: transparent; border: none; }")
        left_l = QHBoxLayout(self.left_box)
        left_l.setContentsMargins(0, 0, 0, 0)
        left_l.setSpacing(6)
        left_l.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)

        self.icon_label = QLabel()
        if icon and not icon.isNull():
            self.icon_label.setPixmap(icon.pixmap(22, 22))
        else:
            self.icon_label.setPixmap(icons.app_fallback_pixmap(22))  # uygulama simgesi yoksa vektör yedek
        self.icon_label.setFixedSize(22, 22)
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        left_l.addWidget(self.icon_label)

        self.title = QLabel(APP_NAME)
        self.title.setObjectName("title_label")
        left_l.addWidget(self.title)

        version = QLabel(f"v{VERSION}")
        version.setObjectName("version_label")
        left_l.addWidget(version)

        layout.addWidget(self.left_box)
        layout.addStretch(1)

        # Orta Menü Konteyneri (Şeffaf zemin ve ortalanmış butonlar)
        self.menu_container = QWidget()
        self.menu_container.setObjectName("menu_container")
        # Scoped by id: a bare rule here also cascaded into the drop-down QMenus and into the buttons
        # (killing their themed hover), so menus ignored the theme and the close button hovered white-on-light.
        self.menu_container.setStyleSheet("QWidget#menu_container { background: transparent; border: none; }")
        menu_l = QHBoxLayout(self.menu_container)
        menu_l.setContentsMargins(0, 0, 0, 0)
        menu_l.setSpacing(4)
        menu_l.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignCenter)

        # İlk menü: Dosya (Dosya Ekle… · Klasör Ekle… · ayırıcı · Çıkış). Kısayol metni yalnızca bilgidir
        # (sekmeyle sağa hizalanır); kısayolları ana pencere bağlar, böylece "belirsiz kısayol" çakışması olmaz.
        self.file_btn = self._menu_button("Dosya")
        file_menu = QMenu(self.file_btn)
        self.add_files_action = QAction("", file_menu)
        self.add_files_action.triggered.connect(lambda *_: self.add_files_clicked.emit())
        file_menu.addAction(self.add_files_action)
        self.add_folder_action = QAction("", file_menu)
        self.add_folder_action.triggered.connect(lambda *_: self.add_folder_clicked.emit())
        file_menu.addAction(self.add_folder_action)
        file_menu.addSeparator()
        self.exit_action = QAction("", file_menu)
        self.exit_action.triggered.connect(lambda *_: self.exit_clicked.emit())
        file_menu.addAction(self.exit_action)
        self.file_btn.setMenu(file_menu)
        menu_l.addWidget(self.file_btn)

        self.theme_btn = self._menu_button("Tema")
        theme_menu = QMenu(self.theme_btn)
        group = QActionGroup(self)
        group.setExclusive(True)
        for key in THEME_KEYS:
            act = QAction(_THEME_ICONS[key](), key, theme_menu)
            act.setCheckable(True)
            act.setData(key)
            group.addAction(act)
            theme_menu.addAction(act)
            self._theme_actions[key] = act
            act.triggered.connect(lambda checked, k=key: self.theme_selected.emit(k) if checked else None)
        self.theme_btn.setMenu(theme_menu)
        menu_l.addWidget(self.theme_btn)

        self.lang_btn = self._menu_button("Dil")
        lang_menu = QMenu(self.lang_btn)
        lang_group = QActionGroup(self)
        lang_group.setExclusive(True)
        for code, label in language_choices(include_auto=True, lang=self._lang):
            act = QAction(create_language_icon(code), label, lang_menu)
            act.setCheckable(True)
            act.setData(code)
            lang_group.addAction(act)
            lang_menu.addAction(act)
            self._lang_actions[code] = act
            act.triggered.connect(lambda checked, c=code: self.language_selected.emit(c) if checked else None)
        self.lang_btn.setMenu(lang_menu)
        menu_l.addWidget(self.lang_btn)

        self.color_btn = self._menu_button("Renk")
        color_menu = QMenu(self.color_btn)
        color_group = QActionGroup(self)
        color_group.setExclusive(True)
        for key, spec in ACCENTS.items():
            act = QAction(_color_swatch_icon(spec["accent"]), t(spec["label_key"], self._lang), color_menu)
            act.setCheckable(True)
            act.setData(key)
            color_group.addAction(act)
            color_menu.addAction(act)
            self._accent_actions[key] = act
            act.triggered.connect(lambda checked, k=key: self.accent_selected.emit(k) if checked else None)
        self.color_btn.setMenu(color_menu)
        menu_l.addWidget(self.color_btn)

        self.settings_btn = self._menu_button("Ayarlar")
        self.settings_btn.clicked.connect(self.settings_clicked.emit)
        menu_l.addWidget(self.settings_btn)

        layout.addWidget(self.menu_container)

        self.help_btn = None

        layout.addStretch(1)

        # Sağ grup (Pencere Kontrolleri)
        self.right_box = QWidget()
        self.right_box.setObjectName("title_right_box")
        self.right_box.setStyleSheet("QWidget#title_right_box { background: transparent; border: none; }")
        right_l = QHBoxLayout(self.right_box)
        right_l.setContentsMargins(0, 0, 0, 0)
        right_l.setSpacing(2)
        right_l.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)

        # Bekleyen güncelleme başlıkta değil, Ayarlar > Güncellemeler'de ve tepsi menüsünde görünür (FlexiKey gibi)
        self.min_btn = QPushButton("−")
        self.max_btn = QPushButton("□")
        self.close_btn = QPushButton("×")
        self.retranslate("tr")

        for btn, cls, signal, pt in (
            (self.min_btn, "title-button", self.minimize_clicked, 13),
            (self.max_btn, "title-button", self.maximize_clicked, 13),
            (self.close_btn, "title-button-close", self.close_clicked, 16),
        ):
            btn.setFont(_chrome_font(pt))
            btn.setFixedSize(28, 24)
            btn.setProperty("class", cls)
            btn.style().unpolish(btn)
            btn.style().polish(btn)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.clicked.connect(signal.emit)
            right_l.addWidget(btn)

        layout.addWidget(self.right_box)
        self.apply_palette(None)
        self._balance_title_bar()

    def _menu_button(self, text: str) -> QPushButton:
        btn = QPushButton(text)
        btn.setProperty("class", "menu-button")
        btn.style().unpolish(btn)
        btn.style().polish(btn)
        btn.setIconSize(QSize(16, 16))
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        return btn

    # ------------------------------------------------------------------ simgeler (vurguya göre boyanır)
    def apply_palette(self, palette: dict | None) -> None:
        """Menü ve düğme simgelerini temanın vurgusuna göre yeniden boya (tema/vurgu değişince ana pencere çağırır)."""
        if palette:
            self._icon_color = palette.get("accent_text") or palette.get("accent") or self._icon_color
            self._danger_color = palette.get("danger") or self._danger_color
        color = self._icon_color
        self.file_btn.setIcon(icons.file_add_icon(color))
        self.add_files_action.setIcon(icons.file_add_icon(color))
        self.add_folder_action.setIcon(icons.folder_add_icon(color))
        self.exit_action.setIcon(icons.door_exit_icon(self._danger_color))
        self.theme_btn.setIcon(icons.theme_system_icon())  # tema simgeleri vurguya göre değil, nötr/anlamsal renkte
        self.lang_btn.setIcon(_globe_icon(color))
        self.settings_btn.setIcon(icons.gear_icon(color))
        spec = ACCENTS.get(self._accent_key)
        if spec:
            self.color_btn.setIcon(_color_swatch_icon(spec["accent"]))

    def _balance_title_bar(self):
        if hasattr(self, "left_box") and hasattr(self, "right_box"):
            for box in (self.left_box, self.right_box):  # önceki sabit genişlik küçülmeyi engellemesin
                box.setMinimumWidth(0)
                box.setMaximumWidth(16777215)
            w_left = self.left_box.sizeHint().width()
            w_right = self.right_box.sizeHint().width()
            target_w = max(w_left, w_right)
            self.left_box.setFixedWidth(target_w)
            self.right_box.setFixedWidth(target_w)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._balance_title_bar()

    def set_theme_choice(self, key: str):
        act = self._theme_actions.get(key)
        if act:
            act.setChecked(True)

    def set_language_choice(self, code: str):
        act = self._lang_actions.get(code)
        if act:
            act.setChecked(True)

    def set_accent_choice(self, key: str):
        act = self._accent_actions.get(key)
        if act:
            act.setChecked(True)
        spec = ACCENTS.get(key)
        if spec:
            self._accent_key = key
            self.color_btn.setIcon(_color_swatch_icon(spec["accent"]))

    def retranslate(self, lang: str = "tr"):
        self._lang = lang
        self.title.setText(get_app_name(lang))
        self.file_btn.setText(t("menu_file", lang))
        self.add_files_action.setText(menu_text(t("menu_add_files", lang), "Ctrl+O"))
        self.add_folder_action.setText(menu_text(t("menu_add_folder", lang), "Ctrl+Shift+O"))
        self.exit_action.setText(menu_text(t("tray_quit", lang), "Ctrl+Q"))
        self.theme_btn.setText(t("theme", lang).rstrip(":"))
        self.lang_btn.setText(t("language", lang).rstrip(":"))
        self.color_btn.setText(t("accent", lang).rstrip(":"))
        self.settings_btn.setText(t("settings", lang))
        theme_labels = {
            "system": t("theme_system", lang),
            "dark": t("theme_dark", lang),
            "light": t("theme_light", lang),
        }
        for k, act in self._theme_actions.items():
            if k in theme_labels:
                act.setText(theme_labels[k])
        for key, act in self._accent_actions.items():
            spec = ACCENTS.get(key)
            if spec:
                act.setText(t(spec["label_key"], lang))
        for code, label in language_choices(include_auto=True, lang=lang):
            act = self._lang_actions.get(code)
            if act:
                act.setText(label)
                act.setIcon(create_language_icon(code))
        self.min_btn.setToolTip(t("minimize", lang))
        self.max_btn.setToolTip(t("maximize", lang))
        self.close_btn.setToolTip(t("close_tooltip", lang))

    def set_maximized(self, maximized: bool):
        self.max_btn.setText("❐" if maximized else "□")
        lang = getattr(self, "_lang", "tr")
        self.max_btn.setToolTip(t("restore", lang) if maximized else t("maximize", lang))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_pos is not None and self._window:
            if self._window.isMaximized():
                self._window.showNormal()
                self.set_maximized(False)
            delta = event.globalPosition().toPoint() - self._drag_pos
            self._window.move(self._window.pos() + delta)
            self._drag_pos = event.globalPosition().toPoint()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_pos = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        self.maximize_clicked.emit()
        super().mouseDoubleClickEvent(event)
