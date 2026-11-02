"""Sistem tepsisi simgesi (her zaman vardır).

Menü iskeleti (tüm uygulamalarda aynı): [Güncelle · vX] · ayırıcı · Göster/Gizle (pencere durumuna göre) · ayırıcı ·
Ayarlar · Tema ▸ · Dil ▸ · ayırıcı · Çıkış. Simgeye tek tık pencereyi açar/öne getirir (çift tık da aynı).
"""

from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QAction, QActionGroup, QIcon
from PyQt6.QtWidgets import QMenu, QSystemTrayIcon

from ..utils.locales import AUTO_LANGUAGE, get_active_language, get_app_name, language_choices, t, create_language_icon
from . import icons
from .title_bar import _THEME_ICONS, THEME_KEYS


class TrayIcon(QSystemTrayIcon):
    def __init__(self, window, icon: QIcon, parent=None, lang: str = "tr", update_version: str = ""):
        super().__init__(icon, parent)
        self.window = window
        self.lang = lang
        self._update_pending = bool(update_version)
        self._update_version = update_version or ""
        self.setToolTip(get_app_name(lang))
        menu = QMenu()
        self.menu = menu

        # Güncelleme satırı menünün EN ÜSTÜNDE ve kalın; yalnızca güncelleme bekliyorsa görünür (altındaki ayırıcıyla birlikte).
        self.update_action = QAction(icons.update_icon(self._accent()), "", menu)
        bold = self.update_action.font()
        bold.setBold(True)
        self.update_action.setFont(bold)
        self.update_action.triggered.connect(self._open_update)
        menu.addAction(self.update_action)
        self.update_separator = menu.addSeparator()

        # Göster/Gizle: etiket menü her açıldığında pencere durumuna göre ayarlanır
        self.show_action = QAction(icons.eye_icon(self._accent()), t("tray_show", lang), menu)
        self.show_action.triggered.connect(self._toggle_window)
        menu.addAction(self.show_action)

        menu.addSeparator()

        self.settings_action = QAction(icons.gear_icon(self._accent()), t("settings", lang), menu)
        self.settings_action.triggered.connect(window._open_settings)
        menu.addAction(self.settings_action)

        self.theme_menu = menu.addMenu(t("theme", lang).rstrip(":"))
        self.theme_menu.setIcon(icons.theme_system_icon())
        self.theme_group = QActionGroup(menu)
        self.theme_group.setExclusive(True)
        self._theme_actions: dict[str, QAction] = {}
        for key in THEME_KEYS:
            act = QAction(_THEME_ICONS[key](), t(f"theme_{key}", lang), menu)
            act.setCheckable(True)
            act.triggered.connect(lambda checked=False, k=key: self._change_theme(k) if checked else None)
            self.theme_group.addAction(act)
            self.theme_menu.addAction(act)
            self._theme_actions[key] = act

        self.lang_menu = menu.addMenu(t("language", lang).rstrip(":"))
        self.lang_menu.setIcon(icons.globe_icon(self._accent()))
        self.lang_group = QActionGroup(menu)
        self.lang_group.setExclusive(True)
        self._lang_actions: dict[str, QAction] = {}
        for code, label in language_choices(include_auto=True, lang=lang):
            act = QAction(create_language_icon(code), label, menu)
            act.setCheckable(True)
            act.triggered.connect(lambda checked=False, c=code: self._change_language(c) if checked else None)
            self.lang_group.addAction(act)
            self.lang_menu.addAction(act)
            self._lang_actions[code] = act

        menu.addSeparator()

        self.quit_action = QAction(icons.door_exit_icon(self._danger()), t("tray_quit", lang), menu)
        self.quit_action.triggered.connect(lambda: QTimer.singleShot(0, window.force_quit))
        menu.addAction(self.quit_action)

        menu.aboutToShow.connect(self._refresh_menus)
        self.theme_menu.aboutToShow.connect(self._refresh_menus)
        self.lang_menu.aboutToShow.connect(self._refresh_menus)
        self.setContextMenu(menu)
        self.activated.connect(self._activated)
        self._refresh_menus()

    # ------------------------------------------------------------------ renkler (simgeler vurguya uyar)
    def _palette(self) -> dict:
        try:
            palette = self.window.theme.get_palette()
            return palette if isinstance(palette, dict) else {}
        except Exception:
            return {}

    def _accent(self) -> str:
        pal = self._palette()
        return pal.get("accent_text") or pal.get("accent") or icons.DEFAULT_ICON_COLOR

    def _danger(self) -> str:
        return self._palette().get("danger") or "#ef4444"

    def _paint_icons(self) -> None:
        """Seçilen vurgu değişmiş olabilir: simgeleri yeniden boya (menü her açıldığında çağrılır)."""
        accent = self._accent()
        self.update_action.setIcon(icons.update_icon(accent))
        self.show_action.setIcon(icons.eye_off_icon(accent) if self._window_shown() else icons.eye_icon(accent))
        self.settings_action.setIcon(icons.gear_icon(accent))
        self.theme_menu.setIcon(icons.theme_system_icon())
        self.lang_menu.setIcon(icons.globe_icon(accent))
        self.quit_action.setIcon(icons.door_exit_icon(self._danger()))

    # ------------------------------------------------------------------ pencere: göster/gizle
    def _window_shown(self) -> bool:
        try:
            return bool(self.window.isVisible() and not self.window.isMinimized())
        except Exception:
            return False

    def _update_show_action(self) -> None:
        self.show_action.setText(t("tray_hide" if self._window_shown() else "tray_show", self.lang))

    def _toggle_window(self):
        if self._window_shown():
            self.window.hide()
        else:
            self._show()

    def _change_theme(self, key: str):
        if hasattr(self.window, "_set_theme"):
            self.window._set_theme(key)
        self._update_theme_menu()

    def _change_language(self, lang_choice: str):
        if hasattr(self.window, "_set_language"):
            self.window._set_language(lang_choice)
        self._update_language_menu()

    def _update_theme_menu(self):
        saved = "system"
        try:
            saved = self.window.config.get("theme", "system")
        except Exception:
            pass
        for key, act in self._theme_actions.items():
            act.setChecked(key == saved)
            act.setText(t(f"theme_{key}", self.lang))
            act.setIcon(_THEME_ICONS[key]())

    def _update_language_menu(self):
        choice = AUTO_LANGUAGE
        try:
            choice = self.window.config.get("language", AUTO_LANGUAGE)
        except Exception:
            pass
        lang = get_active_language(getattr(self.window, "config", None))
        labels = {code: label for code, label in language_choices(include_auto=True, lang=lang)}
        for code, act in self._lang_actions.items():
            act.setChecked(choice == code)
            act.setText(labels.get(code, code))
            act.setIcon(create_language_icon(code))

    def _refresh_menus(self):
        self._update_theme_menu()
        self._update_language_menu()
        self._sync_update_from_window()
        self._update_show_action()
        self._paint_icons()

    def retranslate(self, lang: str = "tr"):
        self.lang = lang
        self.setToolTip(get_app_name(lang))
        self.settings_action.setText(t("settings", lang))
        self.theme_menu.setTitle(t("theme", lang).rstrip(":"))
        self.lang_menu.setTitle(t("language", lang).rstrip(":"))
        self.quit_action.setText(t("tray_quit", lang))
        self._refresh_menus()

    # ------------------------------------------------------------------ güncelleme satırı
    def set_update_available(self, available: bool, version: str = ""):
        self._update_pending = bool(available)
        if version:
            self._update_version = version
        self._apply_update_state()

    def _sync_update_from_window(self):
        """Kaynak ana penceredeki bekleyen güncellemedir: tepsi kapatılıp açılsa, menü yeniden kurulsa ya da dil
        değişse bile satır doğru durumda olsun (yalnızca bir kez `True` verilip unutulmasın)."""
        getter = getattr(self.window, "pending_update_version", None)
        if callable(getter):
            version = getter()
            self._update_pending = bool(version)
            if version:
                self._update_version = version
        self._apply_update_state()

    def _apply_update_state(self):
        if self._update_version:
            text = t("tray_update_now", self.lang).format(version=self._update_version)
        else:
            text = t("update_now", self.lang)
        self.update_action.setText(text)
        self.update_action.setVisible(self._update_pending)
        self.update_separator.setVisible(self._update_pending)

    def _open_update(self):
        """Doğrudan kurmaz: güncelleme penceresini açar (ana pencere gizliyken de öne gelir). Menü kapandıktan sonra."""
        QTimer.singleShot(0, self.window.show_pending_update)

    def _show(self):
        self.window.showNormal()
        self.window.raise_()
        self.window.activateWindow()

    def _activated(self, reason):
        # Tek tık (Windows alışkanlığı) ve çift tık pencereyi açar/öne getirir; sağ tık menüyü Qt kendisi açar.
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self._show()

    def notify(self, title: str, message: str):
        self.showMessage(title, message, QSystemTrayIcon.MessageIcon.Information, 4000)
