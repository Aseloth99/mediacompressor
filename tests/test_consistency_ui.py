"""Uygulamalar arası tutarlılık işi (30 Ekim 2026): "Dosya" menüsü, tepsi iskeleti ve tek tık, Açılışta Başlat, güncelleme
kutusu etiketleri, özel başlık çubuklu pencereler, mikro metin kuralları (Title Case, "…", "siz", "Windows" yok),
`t()` dili, ikinci başlatmada kutu yok, menü simgeleri vurguya uyar."""

from __future__ import annotations

import ast
import os
import pathlib
import re
import sys
import tempfile
import unittest
from copy import deepcopy
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(__file__))
from _support import ROOT  # noqa: E402

from PyQt6.QtCore import QEventLoop, QTimer, Qt  # noqa: E402
from PyQt6.QtGui import QIcon  # noqa: E402
from PyQt6.QtWidgets import QApplication, QCheckBox, QLabel, QPushButton, QSystemTrayIcon  # noqa: E402

from src.gui import main_window as mw  # noqa: E402
from src.gui import message_box  # noqa: E402
from src.gui.about_dialog import AboutDialog  # noqa: E402
from src.gui.advanced_dialog import AdvancedDialog  # noqa: E402
from src.gui.chrome_dialog import ChromeDialog  # noqa: E402
from src.gui.main_window import MainWindow  # noqa: E402
from src.gui.preview_dialog import PreviewDialog  # noqa: E402
from src.gui.settings_dialog import SettingsDialog  # noqa: E402
from src.gui.title_bar import TITLE_BAR_HEIGHT, TitleBar  # noqa: E402
from src.gui.tray import TrayIcon  # noqa: E402
from src.gui.trim_dialog import TrimDialog  # noqa: E402
from src.gui.update_dialog import UpdateDialog  # noqa: E402
from src.utils import locales, startup  # noqa: E402
from src.utils.config import DEFAULTS, Config  # noqa: E402
from src.utils.locales import LOCALES, t  # noqa: E402
from src.utils.theme_manager import ThemeManager  # noqa: E402

_EMOJI = re.compile("[\u2190-\u21ff\u2600-\u27bf\U0001F000-\U0001FAFF\ufe0f]")


def _config(**overrides) -> Config:
    cfg = object.__new__(Config)
    cfg.path, cfg._seed_path, cfg.data = "", None, deepcopy(DEFAULTS)
    cfg.save = lambda *a, **k: None
    cfg.data["show_notifications"] = False
    cfg.data.update(overrides)
    return cfg


def _settle(ms: int = 30) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


class _Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def tearDown(self) -> None:
        message_box.reset_configuration()
        locales.set_ui_language(None)


class WindowCase(_Base):
    """Gerçek ana pencere (ffmpeg hazırlığı kapalı)."""

    def make_window(self, **cfg) -> MainWindow:
        theme = ThemeManager(self.app)
        theme.apply_from_setting("dark")
        with mock.patch.object(MainWindow, "_prepare_ffmpeg", lambda *a, **k: None):
            win = MainWindow(_config(**cfg), theme, mock.MagicMock(), mock.MagicMock())
        win._quitting = True  # kapanışta uygulamayı kapatmaya kalkışmasın
        self.addCleanup(win.close)
        return win


# --------------------------------------------------------------------------------------------------- başlık çubuğu
class TitleBarMenuTests(_Base):
    def _bar(self, lang="tr") -> TitleBar:
        bar = TitleBar()
        bar.retranslate(lang)
        self.addCleanup(bar.deleteLater)
        return bar

    def test_height_is_38_like_the_other_apps(self) -> None:
        self.assertEqual(TITLE_BAR_HEIGHT, 38)
        self.assertEqual(self._bar().height(), 38)

    def test_file_is_the_first_menu_with_add_files_add_folder_separator_exit(self) -> None:
        bar = self._bar()
        order = [bar.file_btn, bar.theme_btn, bar.lang_btn, bar.color_btn, bar.settings_btn]
        layout = bar.menu_container.layout()
        self.assertEqual([layout.itemAt(i).widget() for i in range(layout.count())], order)
        self.assertEqual(bar.file_btn.text(), "Dosya")
        actions = bar.file_btn.menu().actions()
        self.assertEqual([a.isSeparator() for a in actions], [False, False, False, True, False])
        def parts(act):
            return [part.strip() for part in act.text().split("\t")]

        self.assertEqual(parts(actions[0]), ["Dosya Seç…", "Ctrl+O"])
        self.assertEqual(parts(actions[1]), ["Klasör Seç…", "Ctrl+Shift+O"])
        self.assertEqual(parts(actions[2]), ["Çıkış Klasörünü Aç", "Ctrl+Shift+E"])
        self.assertEqual(parts(actions[4]), ["Çıkış", "Ctrl+Q"])
        for act in (actions[0], actions[1], actions[2], actions[4]):
            self.assertFalse(act.icon().isNull(), "vektör simge")

    def test_file_menu_leaves_room_between_names_and_shortcuts(self) -> None:
        from PyQt6.QtGui import QFontMetrics

        ThemeManager(self.app).apply_from_setting("dark")
        bar = self._bar()
        menu = bar.file_btn.menu()
        menu.ensurePolished()
        menu.adjustSize()
        fm = QFontMetrics(menu.font())
        for act in (bar.add_files_action, bar.add_folder_action, bar.exit_action):
            self.assertTrue(act.text().split("\t")[1].startswith("  "), "kısayol sütunundan önce boşluk")
        # en uzun ad + en uzun kısayol + simge/dolgu payından belirgin geniş: iki sütun arasında boşluk var
        longest_name = max(fm.horizontalAdvance(a.text().split("\t")[0]) for a in menu.actions() if not a.isSeparator())
        longest_keys = fm.horizontalAdvance("Ctrl+Shift+O")
        row = menu.actionGeometry(bar.add_folder_action).width()
        self.assertGreaterEqual(row - longest_name - longest_keys, 16 + 28 + 30 + 24, row)

    def test_file_menu_texts_follow_the_language(self) -> None:
        bar = self._bar("en")
        self.assertEqual(bar.file_btn.text(), "File")
        texts = [a.text().split("\t")[0] for a in bar.file_btn.menu().actions() if not a.isSeparator()]
        self.assertEqual(texts, ["Choose Files…", "Choose Folder…", "Open Output Folder", "Exit"])

    def test_file_menu_actions_emit_their_signals(self) -> None:
        bar = self._bar()
        seen = []
        bar.add_files_clicked.connect(lambda: seen.append("files"))
        bar.add_folder_clicked.connect(lambda: seen.append("folder"))
        bar.exit_clicked.connect(lambda: seen.append("exit"))
        bar.add_files_action.trigger()
        bar.add_folder_action.trigger()
        bar.exit_action.trigger()
        self.assertEqual(seen, ["files", "folder", "exit"])

    def test_no_emoji_in_the_title_bar_and_window_glyphs_are_the_shared_pair(self) -> None:
        bar = self._bar()
        for btn in bar.findChildren(QPushButton):
            self.assertIsNone(_EMOJI.search(btn.text()), btn.text())
        # büyüt/geri yükle metin değil vektör glif (dört uygulamada aynı 32'lik ızgara)
        self.assertEqual((bar.max_btn.text(), bar.max_btn.glyph), ("", "maximize"))
        bar.set_maximized(True)
        self.assertEqual((bar.max_btn.text(), bar.max_btn.glyph), ("", "restore"))
        bar.set_maximized(False)
        self.assertEqual((bar.max_btn.text(), bar.max_btn.glyph), ("", "maximize"))

    def test_menu_button_icons_follow_the_accent(self) -> None:
        bar = self._bar()
        bar.apply_palette({"accent_text": "#E91E63", "danger": "#d32f2f"})
        self.assertEqual(bar._icon_color, "#E91E63")
        self.assertFalse(bar.settings_btn.icon().isNull())
        self.assertFalse(bar.file_btn.icon().isNull())


class FileMenuWiringTests(WindowCase):
    def test_menu_items_open_the_same_pickers_as_the_shortcuts(self) -> None:
        win = self.make_window()
        with mock.patch.object(mw.QFileDialog, "getOpenFileNames", return_value=([], "")) as files, \
                mock.patch.object(mw.QFileDialog, "getExistingDirectory", return_value="") as folder:
            win.title_bar.add_files_action.trigger()
            files.assert_called_once()
            win.title_bar.add_folder_action.trigger()
            folder.assert_called_once()

    def test_exit_item_really_quits_while_x_only_hides(self) -> None:
        with mock.patch.object(MainWindow, "force_quit") as quit_:
            win = self.make_window()
            win.title_bar.exit_action.trigger()
            quit_.assert_called_once()

    def test_shortcuts_are_still_bound(self) -> None:
        import inspect

        source = inspect.getsource(MainWindow._setup_shortcuts)
        for line in ('bind("Ctrl+O", self._pick_files)', 'bind("Ctrl+Shift+O", self._pick_folder)',
                     'bind("Ctrl+Q", self.force_quit)', 'bind("F1", self._show_about)'):
            self.assertIn(line, source)


# --------------------------------------------------------------------------------------------------- tepsi
class _Window:
    def __init__(self):
        self.shown = False
        self.minimized = False
        self.calls: list[str] = []
        self.config = types_namespace(get=lambda key, default=None: {"theme": "dark", "language": "tr"}.get(key, default))

    def isVisible(self):
        return self.shown

    def isMinimized(self):
        return self.minimized

    def showNormal(self):
        self.shown, self.minimized = True, False
        self.calls.append("show")

    def hide(self):
        self.shown = False
        self.calls.append("hide")

    def raise_(self):
        self.calls.append("raise")

    def activateWindow(self):
        self.calls.append("activate")

    def _open_settings(self):
        self.calls.append("settings")

    def force_quit(self):
        self.calls.append("quit")

    def pending_update_version(self):
        return ""


def types_namespace(**kw):
    import types

    return types.SimpleNamespace(**kw)


class TrayMenuTests(_Base):
    def _tray(self, lang="tr"):
        window = _Window()
        tray = TrayIcon(window, QIcon(), None, lang=lang)
        self.addCleanup(tray.menu.deleteLater)
        return window, tray

    def test_skeleton_order(self) -> None:
        _window, tray = self._tray()
        actions = tray.menu.actions()
        kinds = []
        for act in actions:
            if act.isSeparator():
                kinds.append("---")
            elif act.menu() is not None:
                kinds.append("menu:" + act.text())
            else:
                kinds.append(act.text())
        self.assertEqual(kinds, [
            "Şimdi Güncelle", "---", "Göster", "---", "Ayarlar", "menu:Tema", "menu:Dil", "---", "Çıkış",
        ])
        self.assertIs(actions[0], tray.update_action)
        self.assertIs(actions[2], tray.show_action)
        self.assertIs(actions[-1], tray.quit_action)

    def test_theme_submenu_is_system_dark_light(self) -> None:
        _window, tray = self._tray()
        self.assertEqual([a.text() for a in tray.theme_menu.actions()], ["Sistem", "Koyu", "Açık"])
        self.assertEqual([a.text() for a in tray.lang_menu.actions()][1:], ["TR · Türkçe", "US · English"])
        self.assertTrue(tray.lang_menu.actions()[0].text().startswith("Otomatik"))

    def test_show_hide_label_follows_the_window_state(self) -> None:
        window, tray = self._tray()
        tray.menu.aboutToShow.emit()
        self.assertEqual(tray.show_action.text(), "Göster")
        window.shown = True
        tray.menu.aboutToShow.emit()
        self.assertEqual(tray.show_action.text(), "Gizle")
        window.minimized = True
        tray.menu.aboutToShow.emit()
        self.assertEqual(tray.show_action.text(), "Göster", "simge durumundaki pencere gizli sayılır")
        tray.retranslate("en")
        window.minimized = False
        tray.menu.aboutToShow.emit()
        self.assertEqual(tray.show_action.text(), "Hide")

    def test_menu_item_toggles_the_window(self) -> None:
        window, tray = self._tray()
        tray.show_action.trigger()
        self.assertTrue(window.shown)
        tray.show_action.trigger()
        self.assertFalse(window.shown)
        self.assertEqual(window.calls, ["show", "raise", "activate", "hide"])

    def test_single_click_and_double_click_open_the_window(self) -> None:
        for reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            with self.subTest(reason=reason):
                window, tray = self._tray()
                tray._activated(reason)
                self.assertTrue(window.shown)
                self.assertEqual(window.calls, ["show", "raise", "activate"])
        window, tray = self._tray()
        tray._activated(QSystemTrayIcon.ActivationReason.Context)
        self.assertEqual(window.calls, [], "sağ tık yalnızca menüyü açar")

    def test_icons_follow_the_accent_each_time_the_menu_opens(self) -> None:
        window, tray = self._tray()
        window.theme = types_namespace(get_palette=lambda: {"accent_text": "#E91E63", "danger": "#d32f2f"})
        tray.menu.aboutToShow.emit()
        self.assertEqual(tray._accent(), "#E91E63")
        self.assertFalse(tray.settings_action.icon().isNull())
        self.assertFalse(tray.theme_menu.icon().isNull())


# --------------------------------------------------------------------------------------------------- ayarlar
class SettingsLabelTests(_Base):
    def _dialog(self, lang="tr", **cfg):
        dlg = SettingsDialog(_config(language=lang, **cfg), "", "", None)
        self.addCleanup(dlg.deleteLater)
        return dlg

    def test_start_at_login_label_and_hint_without_windows(self) -> None:
        for lang, label in (("tr", "Açılışta Başlat"), ("en", "Start at Login")):
            dlg = self._dialog(lang)
            self.assertEqual(dlg.start_win.text(), label)
            labels = " ".join(w.text() for w in dlg.findChildren(QCheckBox))
            self.assertNotIn("Windows", labels)
            self.assertNotIn("Windows", t("start_at_login_hint", lang))

    def test_start_at_login_defaults_to_off(self) -> None:
        self.assertIs(DEFAULTS["start_with_windows"], False)
        self.assertFalse(self._dialog().start_win.isChecked())

    def test_two_update_checkboxes_share_one_short_hint(self) -> None:
        for lang, check, install, hint in (
            ("tr", "Güncellemeleri Otomatik Kontrol Et", "Güncellemeleri Otomatik Kur",
             "Yeni sürüm bulunduğunda arka planda indirilir ve uygulama kullanılmıyorken kurulur."),
            ("en", "Check for Updates Automatically", "Install Updates Automatically",
             "When a new version is found, it is downloaded in the background and installed while the app is not in use."),
        ):
            dlg = self._dialog(lang)
            self.assertEqual(dlg.auto_update.text(), check)
            self.assertEqual(dlg.auto_install.text(), install)
            self.assertEqual(dlg.auto_update.toolTip(), hint)
            self.assertEqual(dlg.auto_install.toolTip(), hint)
            self.assertIn(hint, [lab.text() for lab in dlg.findChildren(type(dlg.update_status))])

    def test_install_checkbox_is_passive_while_the_check_is_off(self) -> None:
        dlg = self._dialog()
        dlg.auto_update.setChecked(False)
        self.assertFalse(dlg.auto_install.isEnabled())
        dlg.auto_update.setChecked(True)
        self.assertTrue(dlg.auto_install.isEnabled())

    def test_save_no_longer_writes_the_pointless_start_minimized_key(self) -> None:
        cfg = _config()
        dlg = SettingsDialog(cfg, "", "", None)
        self.addCleanup(dlg.deleteLater)
        with mock.patch.object(startup, "add_to_startup") as add, mock.patch.object(startup, "remove_from_startup") as remove:
            dlg.start_win.setChecked(True)
            dlg._save()
            add.assert_called_once_with(minimized=True)
            dlg.start_win.setChecked(False)
            dlg._save()
            remove.assert_called_once()
        self.assertNotIn("start_minimized", cfg.data)
        self.assertNotIn("start_minimized", DEFAULTS)
        self.assertNotIn("start_minimized", (ROOT / "src" / "gui" / "settings_dialog.py").read_text(encoding="utf-8"))

    def test_about_button_has_a_vector_icon_not_an_emoji(self) -> None:
        dlg = self._dialog()
        about = next(b for b in dlg.findChildren(QPushButton) if b.text() == "Hakkında")
        self.assertFalse(about.icon().isNull())


# --------------------------------------------------------------------------------------------------- Açılışta Başlat (macOS/Linux)
class UnixAutostartTests(unittest.TestCase):
    def setUp(self) -> None:
        from src.utils import autostart_unix

        self.au = autostart_unix
        self._tmp = tempfile.TemporaryDirectory(prefix="mc_home_")
        self.addCleanup(self._tmp.cleanup)
        self.home = pathlib.Path(self._tmp.name)
        patcher = mock.patch.object(autostart_unix, "_home", lambda home=None: self.home)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _platform(self, name):
        patcher = mock.patch.object(startup.sys, "platform", name)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_linux_writes_a_desktop_file_with_minimized_and_removes_the_old_one(self) -> None:
        self._platform("linux")
        old = self.home / ".config" / "autostart" / "MediaCompressor.desktop"
        old.parent.mkdir(parents=True)
        old.write_text("[Desktop Entry]\nExec=/eski\n", encoding="utf-8")
        self.assertTrue(startup.is_in_startup(), "eski sürümün dosyası da bizimdir")
        self.assertTrue(startup.add_to_startup(minimized=True))
        new = self.home / ".config" / "autostart" / "mediacompressor.desktop"
        text = new.read_text(encoding="utf-8")
        self.assertIn("--minimized", text)
        self.assertIn("Name=Medya Sıkıştırıcı", text)
        if not old.samefile(new):  # Windows'ta dosya sistemi büyük/küçük harfe duyarsız: MediaCompressor.desktop == mediacompressor.desktop
            self.assertFalse(old.exists(), "çift başlatma olmasın")
        self.assertTrue(startup.is_in_startup())
        self.assertTrue(startup.remove_from_startup())
        self.assertFalse(new.exists())
        self.assertFalse(startup.is_in_startup())

    def test_macos_writes_a_launch_agent_with_run_at_load(self) -> None:
        import plistlib

        self._platform("darwin")
        old = self.home / "Library" / "LaunchAgents" / "com.mediacompressor.plist"
        old.parent.mkdir(parents=True)
        old.write_bytes(plistlib.dumps({"Label": "com.mediacompressor", "ProgramArguments": ["/eski"], "RunAtLoad": True}))
        self.assertTrue(startup.add_to_startup(minimized=True))
        new = self.home / "Library" / "LaunchAgents" / "com.macik.mediacompressor.plist"
        data = plistlib.loads(new.read_bytes())
        self.assertTrue(data["RunAtLoad"])
        self.assertEqual(data["Label"], "com.macik.mediacompressor")
        self.assertEqual(data["ProgramArguments"][-1], "--minimized")
        self.assertFalse(old.exists())
        self.assertTrue(startup.remove_from_startup())
        self.assertFalse(new.exists())

    def test_windows_branch_is_untouched(self) -> None:
        import inspect

        source = inspect.getsource(startup._win_add)
        self.assertIn("winreg.SetValueEx(key, APP_ID, 0, winreg.REG_SZ, _executable_command(minimized))", source)
        self.assertIn(r"Software\Microsoft\Windows\CurrentVersion\Run", source)
        self.assertEqual(startup._executable_command(True).split()[-1], "--minimized")


# --------------------------------------------------------------------------------------------------- mikro metin
class MicrocopyTests(_Base):
    def test_no_windows_word_in_any_user_facing_text(self) -> None:
        for lang, table in LOCALES.items():
            for key, value in table.items():
                self.assertNotIn("Windows", value, f"{lang}.{key}")

    def test_ellipsis_is_the_single_character_everywhere(self) -> None:
        for lang, table in LOCALES.items():
            for key, value in table.items():
                self.assertNotIn("...", value, f"{lang}.{key}")

    def test_no_emoji_in_locale_texts(self) -> None:
        for lang, table in LOCALES.items():
            for key, value in table.items():
                # → ve ↑ (başlıktaki güncelleme simgesine işaret eder) ok karakteri; emoji değil
                self.assertIsNone(_EMOJI.search(value.replace("→", "").replace("↑", "")), f"{lang}.{key}: {value}")

    def test_control_labels_are_title_case(self) -> None:
        keys = {
            "tr": ["show_notifications", "auto_update_check", "auto_update_install", "check_now", "adv_settings",
                   "clear_queue", "retry_failed", "open_output", "open_when_done", "queue_remove", "reveal_in_folder",
                   "open_file", "ovr_menu", "ovr_video_res", "ovr_image_res", "ovr_default", "ovr_clear",
                   "trim_title", "trim_reset", "trim_remove", "update_later", "update_now", "update_retry",
                   "start_at_login", "menu_add_files", "menu_add_folder", "profile_quality", "section_source",
                   "section_output", "section_quality", "restore"],
            "en": ["show_notifications", "auto_update_check", "auto_update_install", "check_now", "adv_settings",
                   "clear_queue", "retry_failed", "open_output", "open_when_done", "reveal_in_folder", "open_file",
                   "ovr_menu", "ovr_video_res", "ovr_image_res", "ovr_default", "ovr_clear", "trim_title",
                   "trim_reset", "trim_remove", "update_retry", "start_at_login", "menu_add_files", "menu_add_folder",
                   "profile_quality", "section_source", "section_output", "section_quality", "restore"],
        }
        for lang, names in keys.items():
            for key in names:
                value = LOCALES[lang][key]
                for word in re.findall(r"[^\s(/]+", value):
                    if word[0].isalpha() and word not in ("at", "for", "from", "in", "ve"):  # bağlaçlar küçük kalır
                        self.assertTrue(word[0].isupper(), f"{lang}.{key}: {value!r} ({word})")

    def test_no_colon_after_field_labels(self) -> None:
        for lang in LOCALES:
            for key in ("theme", "language", "accent", "preview_frame_label", "preview_format_label", "preview_res_label"):
                self.assertFalse(LOCALES[lang][key].endswith(":"), f"{lang}.{key}")

    def test_up_to_date_has_one_form(self) -> None:
        self.assertEqual(t("up_to_date", "tr").format("1.2.3"), "Güncel · v1.2.3")
        self.assertEqual(t("up_to_date", "en").format("1.2.3"), "Up to date · v1.2.3")

    def test_turkish_uses_siz_not_sen(self) -> None:
        sen_forms = ("tekrar dene.", "bağlantını", "seçtiğin", "istersen", "Eklediklerin", "bırak,", "tıkla.", "bırak ya da",
                     "yeniden aç.", "bunu seç.")
        for key, value in LOCALES["tr"].items():
            for form in sen_forms:  # tam sözcük eşleşmesi: "bağlantını" ile "bağlantınızı" karışmasın
                self.assertIsNone(re.search(r"(?<!\w)" + re.escape(form) + r"(?!\w)", value), f"tr.{key}: {value}")
        self.assertIn("deneyin", t("update_check_failed_msg", "tr"))
        self.assertIn("bırakın", t("queue_empty_hint", "tr"))

    def test_the_already_running_box_text_is_gone(self) -> None:
        for table in LOCALES.values():
            self.assertNotIn("msg_already_running", table)

    def test_new_keys_exist_in_both_languages(self) -> None:
        for key in ("menu_file", "menu_add_files", "menu_add_folder", "tray_hide", "start_at_login",
                    "start_at_login_hint", "auto_update_hint"):
            self.assertIn(key, LOCALES["tr"])
            self.assertIn(key, LOCALES["en"])


class UserLanguageTests(_Base):
    def test_t_without_a_language_uses_the_users_chosen_language(self) -> None:
        with mock.patch.object(locales, "get_system_language", return_value="tr"):
            locales.set_ui_language(None)
            self.assertEqual(t("settings"), "Ayarlar")
            locales.get_active_language(_config(language="en"))  # kullanıcı İngilizce seçti
            self.assertEqual(t("settings"), "Settings")
            self.assertEqual(locales.get_active_language(), "en", "argümansız çağrı da seçilen dili verir")
            self.assertEqual(t("settings", "tr"), "Ayarlar", "açık dil her zaman geçer")
            locales.get_active_language(_config(language="auto"))
            self.assertEqual(t("settings"), "Ayarlar")

    def test_without_any_choice_it_falls_back_to_the_system_language(self) -> None:
        locales.set_ui_language(None)
        with mock.patch.object(locales, "get_system_language", return_value="en"):
            self.assertEqual(t("settings"), "Settings")
            self.assertEqual(locales.get_active_language(), "en")


# --------------------------------------------------------------------------------------------------- ikinci başlatma
class SecondLaunchTests(unittest.TestCase):
    def test_main_never_opens_a_box_for_a_second_launch(self) -> None:
        source = (ROOT / "main.py").read_text(encoding="utf-8")
        self.assertNotIn("QMessageBox", source)
        self.assertNotIn("msg_already_running", source)
        self.assertNotIn("get_active_language()", source)
        self.assertIn("_try_raise_existing()", source)
        self.assertIn("window._ensure_tray()", source, "--minimized dalı tepsi sonucuna bakar")


# --------------------------------------------------------------------------------------------------- özel başlık çubuklu pencereler
class NoNativeDialogsTests(unittest.TestCase):
    def test_no_qmessagebox_or_qinputdialog_is_left_in_the_app(self) -> None:
        for path in list((ROOT / "src").rglob("*.py")) + [ROOT / "main.py"]:
            if path.name == "message_box.py":
                continue  # ortak modül: QMessageBox'ın yalnızca enum'larını takma ad olarak alır
            used = set()  # yorum/açıklama metinleri değil, gerçek kullanım (ad, öznitelik, içe aktarma)
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Name):
                    used.add(node.id)
                elif isinstance(node, ast.Attribute):
                    used.add(node.attr)
                elif isinstance(node, ast.alias):
                    used.add(node.name.split(".")[-1])
            self.assertFalse(used & {"QMessageBox", "QInputDialog"}, str(path))

    def test_every_dialog_class_uses_the_custom_title_bar(self) -> None:
        for cls in (SettingsDialog, UpdateDialog, TrimDialog, AdvancedDialog, PreviewDialog, AboutDialog):
            self.assertTrue(issubclass(cls, ChromeDialog), cls.__name__)


class ChromeDialogTests(_Base):
    def _theme(self):
        theme = ThemeManager(self.app)
        theme.apply_from_setting("dark")
        message_box.configure(palette_provider=theme.get_palette, lang_provider=lambda: "tr")
        return theme

    def test_dialogs_are_frameless_with_a_title_bar_and_the_window_title(self) -> None:
        self._theme()
        for make in (lambda: SettingsDialog(_config(), "", "", None), lambda: AboutDialog(None, "tr"),
                     lambda: UpdateDialog("1.2.3", "", False, None, lang="tr"),
                     lambda: PreviewDialog(None, 80, "2400px", None, "tr")):
            dlg = make()
            self.addCleanup(dlg.deleteLater)
            self.assertTrue(dlg.windowFlags() & Qt.WindowType.FramelessWindowHint)
            self.assertEqual(dlg._cd_bar.title_label.text(), dlg.windowTitle())
            self.assertEqual(dlg._cd_bar.height(), 38)

    def test_sizes_mean_content_size(self) -> None:
        self._theme()
        dlg = UpdateDialog("1.2.3", "", False, None, lang="tr")
        self.addCleanup(dlg.deleteLater)
        self.assertEqual(dlg.minimumWidth(), 520)

    def test_x_button_closes_like_the_native_close(self) -> None:
        self._theme()
        dlg = UpdateDialog("1.2.3", "", False, None, lang="tr")
        self.addCleanup(dlg.deleteLater)
        deferred = []
        dlg.update_deferred.connect(lambda: deferred.append(1))
        dlg.show()
        dlg._cd_bar.close_btn.click()
        self.assertFalse(dlg.isVisible())
        self.assertEqual(deferred, [1], "Güncelleme penceresinde X = Daha Sonra (mantık aynı)")

    def test_chrome_follows_a_live_theme_change(self) -> None:
        theme = self._theme()
        dlg = SettingsDialog(_config(), "", "", None, theme=theme)
        self.addCleanup(dlg.deleteLater)
        dlg.show()
        dark_base = dlg._pal["base"]
        theme.apply_from_setting("light")
        _settle()
        self.assertNotEqual(dlg._pal["base"], dark_base)
        self.assertEqual(dlg._pal["base"].lower(), theme.get_palette()["base"].lower())
        dlg.close()

    def test_preview_dialog_is_resizable_with_a_maximize_button(self) -> None:
        self._theme()
        dlg = PreviewDialog(None, 80, "2400px", None, "tr")
        self.addCleanup(dlg.deleteLater)
        self.addCleanup(dlg.close)  # açık kalan modal pencere sonraki testlerin "boşta mı" denetimini bozuyordu
        self.assertIsNotNone(dlg._cd_max)
        dlg.show()
        dlg.toggle_maximized()
        self.assertTrue(dlg.isMaximized())
        dlg.toggle_maximized()
        self.assertFalse(dlg.isMaximized())
        for btn in dlg.findChildren(QPushButton):
            self.assertIsNone(_EMOJI.search(btn.text()), btn.text())

    def test_tall_dialogs_scroll_instead_of_overflowing_a_small_screen(self) -> None:
        from PyQt6.QtCore import QRect

        theme = self._theme()

        class _Screen:
            def __init__(self, rect):
                self._rect = rect

            def availableGeometry(self):
                return self._rect

        small, large = QRect(0, 0, 1366, 728), QRect(0, 0, 2560, 1400)
        for make in (lambda: SettingsDialog(_config(), "", "", None, theme=theme),
                     lambda: AdvancedDialog(lambda l: [("h264", "H.264")], lambda l: [("auto", "Otomatik")], None, "tr")):
            dlg = make()
            self.addCleanup(dlg.deleteLater)
            natural = dlg.sizeHint().height()
            with mock.patch.object(ChromeDialog, "_screen", lambda self, r=small: _Screen(r)):
                dlg._prepare_geometry()
            self.assertLessEqual(dlg.height(), 728 - 16, type(dlg).__name__)
            self.assertLess(dlg.height(), natural, "ekrandan uzun içerik kısaltılır ve kaydırılır")
            self.assertIsNotNone(dlg._cd_scroll)
            dlg2 = make()
            self.addCleanup(dlg2.deleteLater)
            with mock.patch.object(ChromeDialog, "_screen", lambda self, r=large: _Screen(r)):
                dlg2._prepare_geometry()
            self.assertGreaterEqual(dlg2.height(), natural - 2, "büyük ekranda içerik kırpılmaz")

    def test_about_dialog_shows_name_version_and_link(self) -> None:
        self._theme()
        dlg = AboutDialog(None, "tr")
        self.addCleanup(dlg.deleteLater)
        self.assertEqual(dlg.windowTitle(), "Hakkında")
        self.assertIn("macik.com.tr", dlg.link.text())
        self.assertIn("v", dlg.version_label.text())


class MessageBoxWiringTests(WindowCase):
    def test_main_window_configures_the_shared_box_with_its_theme_and_language(self) -> None:
        win = self.make_window(language="en", accent="rose")
        win.theme.apply_from_setting("dark", "rose")
        pal = message_box.current_palette()
        self.assertEqual(pal["accent"].lower(), "#e91e63")
        self.assertTrue(pal["is_dark"])
        self.assertEqual(message_box.button_text(message_box.StandardButton.Cancel), "Cancel")

    def test_failures_use_the_custom_box(self) -> None:
        win = self.make_window()
        seen = []
        message_box.MessageBox.set_test_hook(lambda box: seen.append((box.windowTitle(), box.text())) or None)
        win.ffmpeg.ffmpeg_path = ""
        with mock.patch.object(mw, "reveal_in_file_manager", return_value=False):
            win._reveal_source("C:/yok/dosya.mp4")
        self.assertEqual(len(seen), 1)
        self.assertIn("dosya.mp4", seen[0][1])

    def test_queue_menu_actions_have_vector_icons(self) -> None:
        win = self.make_window()
        with tempfile.TemporaryDirectory() as tmp:
            video = pathlib.Path(tmp) / "klip.mp4"
            video.write_bytes(b"\0" * 10)
            menu = win.queue.build_menu([str(video)])
            by_text = {a.text(): a for a in menu.actions()}
            self.assertFalse(by_text["Canlı Önizleme / Karşılaştır"].icon().isNull())
            self.assertFalse(by_text["Kırp…"].icon().isNull())
            # simgesiz satır kalmasın: yoksa metinler iki farklı hizada başlar
            rows = [a for a in menu.actions() if not a.isSeparator()]
            self.assertEqual(len(rows), 6, [a.text() for a in rows])
            for act in rows:
                self.assertFalse(act.icon().isNull(), act.text())
        self.assertFalse(win.preview_btn.icon().isNull())

    def test_percent_follows_the_language(self) -> None:
        self.assertEqual(t("pct", "tr").format("74.5"), "%74.5")
        self.assertEqual(t("pct", "en").format("74.5"), "74.5%")
        from src.gui.queue_panel import progress_text

        en = progress_text(0.41, "58 s", "en")
        self.assertEqual(en, "41% · ~58 s")
        self.assertEqual(progress_text(0.41, "58 sn", "tr"), "%41 · ~58 sn")

    def test_job_summary_line_uses_dots_and_language_percent(self) -> None:
        win = self.make_window(language="en")
        win.notifier = mock.MagicMock()
        win.open_when_done.setChecked(False)
        win._on_job_finished({"ok": 2, "bytes_in": 4_000_000, "bytes_out": 1_000_000, "elapsed": 12})
        line = win.stats.text()
        self.assertIn("(-75.0%)", line)
        self.assertNotIn("|", line)
        self.assertIn("  ·  ", line)

    def test_stats_line_starts_where_the_progress_text_starts(self) -> None:
        win = self.make_window()
        self.assertEqual(win.stats.contentsMargins().left(), win.prog_box.layout().contentsMargins().left())

    def test_section_captions_are_not_indented(self) -> None:
        # Üst dolgu QLabel'e çerçeve verir; girinti -1 kalırsa Qt metni ~3 px içeri iter (alan etiketleriyle kayar).
        win = self.make_window()
        captions = [lab for lab in win.findChildren(QLabel) if lab.objectName() == "section_caption"]
        self.assertTrue(captions)
        for lab in captions:
            lab.ensurePolished()
            self.assertEqual(lab.indent(), 0, lab.text())


class SettingsHeaderTests(_Base):
    def test_version_is_written_once_in_the_updates_section(self) -> None:
        from src.core.app_info import VERSION

        ThemeManager(self.app).apply_from_setting("dark")
        dlg = SettingsDialog(_config(language="tr"), "", "", None)
        self.addCleanup(dlg.deleteLater)
        texts = [lab.text() for lab in dlg.findChildren(QLabel)]
        self.assertEqual(sum(VERSION in text for text in texts), 1, texts)
        headers = [lab.text() for lab in dlg.findChildren(QLabel) if lab.objectName() == "section_header"]
        self.assertIn("Medya Sıkıştırıcı", headers)
        self.assertIn(VERSION, dlg.update_status.text())


class ScrollBarStyleTests(unittest.TestCase):
    def test_scroll_handle_is_neutral_and_accent_only_on_hover(self) -> None:
        from src.utils import theme_manager as tm

        for base, dark in ((tm.DARK, True), (tm.LIGHT, False)):
            p = tm._with_accent(base, "cyan", dark)
            sheet = re.sub(r"\s+", " ", tm._build(p))
            handle = re.search(r"QScrollBar::handle:vertical \{ background: (#[0-9a-f]{6});", sheet)
            self.assertIsNotNone(handle)
            self.assertNotEqual(handle.group(1), p["accent"])
            self.assertEqual(handle.group(1), p["scroll"])
            self.assertIn(f"QScrollBar::handle:vertical:hover, QScrollBar::handle:vertical:pressed {{ background: {p['accent']}; }}", sheet)


if __name__ == "__main__":
    unittest.main()
