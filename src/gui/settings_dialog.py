"""Ayarlar penceresi (özel başlık çubuklu)."""

from PyQt6.QtCore import Qt, QSize
from PyQt6.QtWidgets import (
    QButtonGroup, QCheckBox, QComboBox, QGridLayout, QHBoxLayout,
    QLabel, QPushButton, QVBoxLayout,
)

from ..core.app_info import VERSION
from ..utils import startup
from ..utils.config import Config
from ..utils.locales import AUTO_LANGUAGE, get_active_language, get_app_name, language_choices, t, create_language_icon
from ..utils.theme_manager import ACCENTS, DEFAULT_ACCENT, accent_label, fit_text_widgets
from . import icons
from .chrome_dialog import ChromeDialog
from .update_check_ui import UpdateCheckAnimator


def _field_label(text: str) -> QLabel:
    lab = QLabel(text)
    lab.setObjectName("field_label")
    lab.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
    return lab


class SettingsDialog(ChromeDialog):
    def __init__(
        self, config: Config, ffmpeg_path: str, gpu_text: str, parent=None,
        updater=None, theme=None,
    ):
        super().__init__(parent, scroll=True)
        self.config = config
        self.updater = updater
        self.theme = theme
        self.lang = get_active_language(config)
        self._prev_theme = config.get("theme", "system")
        self._prev_accent = config.get("accent", DEFAULT_ACCENT)
        self.setWindowTitle(t("settings", self.lang))
        self.setMinimumWidth(480)
        layout = QVBoxLayout(self.body_host)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(16)

        app_title = get_app_name(self.lang)
        header = QLabel(f"{app_title}  v{VERSION}")
        header.setObjectName("section_header")
        layout.addWidget(header)

        lang_box = QVBoxLayout()
        lang_box.setSpacing(6)
        lang_box.setContentsMargins(0, 0, 0, 0)
        self.lang_combo = QComboBox()
        self.lang_combo.setIconSize(QSize(22, 15))
        for code, label in language_choices(include_auto=True, lang=self.lang):
            self.lang_combo.addItem(create_language_icon(code), label, code)
        lang_idx = self.lang_combo.findData(config.get("language", AUTO_LANGUAGE))
        if lang_idx >= 0:
            self.lang_combo.setCurrentIndex(lang_idx)
        lang_box.addWidget(_field_label(t("language", self.lang)))
        lang_box.addWidget(self.lang_combo)
        layout.addLayout(lang_box)

        tema_box = QVBoxLayout()
        tema_box.setSpacing(6)
        tema_box.setContentsMargins(0, 0, 0, 0)
        self.theme_combo = QComboBox()
        self.theme_combo.addItems([
            t("theme_system", self.lang),
            t("theme_dark", self.lang),
            t("theme_light", self.lang),
        ])
        theme_map = {"system": 0, "dark": 1, "light": 2}
        self.theme_combo.setCurrentIndex(theme_map.get(config.get("theme", "system"), 0))
        tema_box.addWidget(_field_label(t("theme", self.lang)))
        tema_box.addWidget(self.theme_combo)
        self.theme_combo.currentIndexChanged.connect(self._preview_theme)
        layout.addLayout(tema_box)

        vurgu_box = QVBoxLayout()
        vurgu_box.setSpacing(8)
        vurgu_box.setContentsMargins(0, 0, 0, 0)
        vurgu_box.addWidget(_field_label(t("accent", self.lang)))
        accent_grid = QGridLayout()
        accent_grid.setHorizontalSpacing(10)
        accent_grid.setVerticalSpacing(10)
        accent_grid.setContentsMargins(0, 0, 0, 0)
        self.accent_group = QButtonGroup(self)
        self.accent_group.setExclusive(True)
        self._accent_btns: dict[str, QPushButton] = {}
        current_accent = config.get("accent", DEFAULT_ACCENT)
        if current_accent not in ACCENTS:
            current_accent = DEFAULT_ACCENT
        for i, (key, spec) in enumerate(ACCENTS.items()):
            btn = QPushButton()
            btn.setCheckable(True)
            btn.setFixedSize(28, 28)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setToolTip(
                accent_label(key, self.lang)
                + (f" {t('accent_default', self.lang)}" if key == DEFAULT_ACCENT else "")
            )
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            self._style_dot(btn, spec["accent"], key == current_accent)
            btn.setChecked(key == current_accent)
            self.accent_group.addButton(btn)
            self._accent_btns[key] = btn
            btn.clicked.connect(lambda checked, k=key: self._on_accent(k) if checked else None)
            accent_grid.addWidget(btn, i // 5, i % 5, Qt.AlignmentFlag.AlignLeft)
        vurgu_box.addLayout(accent_grid)
        self.accent_label = QLabel(accent_label(current_accent, self.lang))
        self.accent_label.setObjectName("hint_label")
        vurgu_box.addWidget(self.accent_label)
        layout.addLayout(vurgu_box)

        opts = QVBoxLayout()
        opts.setSpacing(8)
        opts.setContentsMargins(0, 0, 0, 0)
        self.start_win = QCheckBox(t("start_at_login", self.lang))
        self.start_win.setChecked(bool(config.get("start_with_windows")))  # ayar anahtarı eski adıyla kalır (kayıtlı ayarlar bozulmasın)
        opts.addWidget(self.start_win)
        start_hint = QLabel(t("start_at_login_hint", self.lang))
        start_hint.setObjectName("hint_label")
        start_hint.setWordWrap(True)
        opts.addWidget(start_hint)

        self.notify = QCheckBox(t("show_notifications", self.lang))
        self.notify.setChecked(bool(config.get("show_notifications", True)))
        opts.addWidget(self.notify)

        self.auto_update = QCheckBox(t("auto_update_check", self.lang))
        self.auto_update.setChecked(bool(config.get("auto_update_check", True)))
        self.auto_update.setToolTip(t("auto_update_hint", self.lang))
        opts.addWidget(self.auto_update)

        self.auto_install = QCheckBox(t("auto_update_install", self.lang))
        self.auto_install.setChecked(bool(config.get("auto_update_install", True)))
        self.auto_install.setToolTip(t("auto_update_hint", self.lang))
        self.auto_install.setEnabled(self.auto_update.isChecked())
        self.auto_update.toggled.connect(self.auto_install.setEnabled)
        opts.addWidget(self.auto_install)
        update_hint = QLabel(t("auto_update_hint", self.lang))  # iki güncelleme kutusunda da aynı kısa ipucu
        update_hint.setObjectName("hint_label")
        update_hint.setWordWrap(True)
        opts.addWidget(update_hint)

        layout.addLayout(opts)

        check_row = QHBoxLayout()
        self.check_btn = QPushButton(t("check_now", self.lang))
        self.check_btn.setProperty("class", "ghost")
        self.check_btn.clicked.connect(self._check_updates)
        check_row.addWidget(self.check_btn)
        check_row.addStretch()
        layout.addLayout(check_row)

        info = QVBoxLayout()
        info.setSpacing(6)
        info.setContentsMargins(0, 0, 0, 0)
        self.update_status = QLabel(t("current_version", self.lang).format(VERSION))
        self.update_status.setObjectName("update_status")
        self.update_check = UpdateCheckAnimator(self.check_btn, self.update_status, self)
        pending = getattr(parent, "_pending_update", None)
        if pending:  # sessiz denetim zaten yeni sürüm bulmuş
            self.update_status.setText(t("update_new_version", self.lang).format(version=pending[0]))
        info.addWidget(self.update_status)

        gpu = QLabel(t("gpu_prefix", self.lang).format(gpu_text or t("gpu_none_value", self.lang)))
        gpu.setObjectName("hint_label")
        gpu.setWordWrap(True)
        info.addWidget(gpu)
        ff = QLabel(f"FFmpeg: {ffmpeg_path or t('ffmpeg_not_found', self.lang)}")
        ff.setObjectName("hint_label")
        ff.setWordWrap(True)
        info.addWidget(ff)
        layout.addLayout(info)

        layout.addStretch(1)

        row = QHBoxLayout()
        row.setSpacing(10)
        about = QPushButton(t("about", self.lang))
        about.setIcon(icons.info_icon(self._icon_color()))
        about.setIconSize(QSize(18, 18))
        about.setProperty("class", "ghost")
        about.clicked.connect(self._show_about)
        row.addWidget(about)
        row.addStretch()
        save = QPushButton(t("save", self.lang))
        save.setProperty("class", "primary")
        save.clicked.connect(self._save)
        cancel = QPushButton(t("cancel", self.lang))
        cancel.clicked.connect(self.reject)
        row.addWidget(cancel)
        row.addWidget(save)
        layout.addLayout(row)

        if self.updater:
            self.updater.check_complete.connect(self._on_check_complete)
            self.updater.check_failed.connect(self._on_check_failed)
            self.finished.connect(self._cleanup_updater)

        fit_text_widgets(self)

    def _icon_color(self) -> str:
        """Düğme simgeleri seçilen vurguya uysun (açık temada okunur koyu ton)."""
        try:
            return self.theme.get_palette()["accent_text"]
        except Exception:
            return icons.DEFAULT_ICON_COLOR

    def _style_dot(self, btn: QPushButton, color: str, selected: bool):
        ring = "#ffffff" if selected else color
        btn.setStyleSheet(
            f"QPushButton {{ background-color: {color}; border-radius: 14px; "
            f"border: 2px solid {ring}; padding: 0px; min-width: 28px; max-width: 28px; "
            f"min-height: 28px; max-height: 28px; }}"
        )

    def _accent_key(self) -> str:
        for key, btn in self._accent_btns.items():
            if btn.isChecked():
                return key
        return DEFAULT_ACCENT

    def _theme_key(self) -> str:
        return ["system", "dark", "light"][self.theme_combo.currentIndex()]

    def _refresh_dots(self):
        selected = self._accent_key()
        for key, btn in self._accent_btns.items():
            self._style_dot(btn, ACCENTS[key]["accent"], key == selected)
        self.accent_label.setText(accent_label(selected, self.lang))

    def _preview(self):
        if self.theme:
            self.theme.apply_from_setting(self._theme_key(), self._accent_key())

    def _preview_theme(self, *_):
        self._preview()

    def _on_accent(self, key: str):
        self._refresh_dots()
        self._preview()

    def reject(self):
        if self.theme:
            self.theme.apply_from_setting(self._prev_theme, self._prev_accent)
        super().reject()

    def _cleanup_updater(self):
        self.update_check.cancel()
        if not self.updater:
            return
        try:
            self.updater.check_complete.disconnect(self._on_check_complete)
        except TypeError:
            pass
        try:
            self.updater.check_failed.disconnect(self._on_check_failed)
        except TypeError:
            pass

    def _check_updates(self):
        if not self.updater:
            self.update_check.finish("fail", t("updater_unavailable", self.lang))
            return
        if self.update_check.running:
            return
        self.update_check.start(t("checking", self.lang))
        self.updater.check_for_updates(show_message=True)

    def _on_check_complete(self, has_update: bool):
        if has_update:
            pending = getattr(self.parent(), "_pending_update", None)
            self.update_check.finish(
                "new",
                t("update_new_version", self.lang).format(version=pending[0]) if pending
                else t("update_new_available", self.lang),
            )
        else:
            self.update_check.finish("ok", t("up_to_date", self.lang).format(VERSION))

    def _on_check_failed(self):
        self.update_check.finish("fail", t("update_check_failed", self.lang))

    def _show_about(self):
        parent = self.parent()
        if parent is not None and hasattr(parent, "_show_about"):
            parent._show_about()

    def _save(self):
        theme = self._theme_key()
        accent = self._accent_key()
        lang_choice = self.lang_combo.currentData() or AUTO_LANGUAGE
        self.config.set("theme", theme, persist=False)
        self.config.set("accent", accent, persist=False)
        self.config.set("language", lang_choice, persist=False)
        self.config.set("start_with_windows", self.start_win.isChecked(), persist=False)
        self.config.set("show_notifications", self.notify.isChecked(), persist=False)
        self.config.set("auto_update_check", self.auto_update.isChecked(), persist=False)
        self.config.set("auto_update_install", self.auto_install.isChecked(), persist=False)
        self.config.save()
        if self.start_win.isChecked():
            startup.add_to_startup(minimized=True)
        else:
            startup.remove_from_startup()
        self.accept()
