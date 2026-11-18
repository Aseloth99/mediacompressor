"""Güncelleme akışı uçtan uca (Qt offscreen, ağ ve exe yok): tepsi satırı, güncelleme penceresi durumları, ana pencere
bağlantıları (boşta -> indirme -> kurma -> hata -> tekrar dene, iptal, ikinci indirme yok), başlangıç sırası."""

from __future__ import annotations

import os
import sys
import types
import unittest
from copy import deepcopy
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(__file__))
from _support import ROOT  # noqa: E402

from PyQt6 import sip  # noqa: E402
from PyQt6.QtCore import QCoreApplication, Qt  # noqa: E402
from PyQt6.QtGui import QIcon, QKeyEvent  # noqa: E402
from PyQt6.QtWidgets import QApplication, QDialog, QMenu, QMessageBox  # noqa: E402

from src.gui.message_box import MessageBox  # noqa: E402

from src.core.app_info import VERSION  # noqa: E402
from src.gui import main_window as mw  # noqa: E402
from src.gui.tray import TrayIcon  # noqa: E402
from src.gui.update_dialog import UpdateDialog  # noqa: E402
from src.utils import self_update  # noqa: E402
from src.utils.config import DEFAULTS, Config  # noqa: E402
from src.utils.theme_manager import ThemeManager  # noqa: E402
from src.utils.update_installer import UpdateInstaller  # noqa: E402

SHA = "ab" * 32
URL = "https://macik.com.tr/Pages/AppDownload?slug=mediacompressor&file=MediaCompressor.exe"


def destroy(*objects) -> None:
    """Qt nesnelerini hemen yok et. Testten sonra Python çöp toplayıcısına/deleteLater'a bırakılan pencere, tepsi ve
    diyaloglar, SONRAKİ test dosyalarında rastgele bir olay işlenirken yok edilip erişim ihlaliyle çökertiyordu."""
    for obj in objects:
        try:
            if not sip.isdeleted(obj):
                sip.delete(obj)
        except Exception:  # noqa: BLE001 - temizlik hiçbir zaman testi düşürmesin
            pass


def _no_modal():
    """Güncelleme akışında hiçbir QMessageBox açılmamalı (açılırsa test düşer, ekranda pencere bekletmez)."""
    patches = [mock.patch.object(box, name, side_effect=AssertionError(f"{box.__name__}.{name} çağrıldı"))
               for box in (QMessageBox, MessageBox)
               for name in ("question", "warning", "information", "critical", "about", "exec")]
    return patches


class ModalGuard:
    def setUp(self) -> None:  # noqa: N802
        super().setUp()
        for patch in _no_modal():
            patch.start()
            self.addCleanup(patch.stop)


# --------------------------------------------------------------------------------------------------- pencere
class UpdateDialogTests(ModalGuard, unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def _dialog(self, mandatory=False, lang="tr", size=0, notes="<p>Notlar</p>"):
        dialog = UpdateDialog("1.2.3", notes, mandatory, None, lang=lang, size=size)
        # modal pencere açık kalırsa sonraki testlerde "etkin modal pencere" var sanılır
        self.addCleanup(lambda d=dialog: (d.setModal(False), d.hide(), destroy(d)))
        self.signals = {"accepted": 0, "deferred": 0, "cancelled": 0}
        dialog.update_accepted.connect(lambda: self.signals.__setitem__("accepted", self.signals["accepted"] + 1))
        dialog.update_deferred.connect(lambda: self.signals.__setitem__("deferred", self.signals["deferred"] + 1))
        dialog.update_cancelled.connect(lambda: self.signals.__setitem__("cancelled", self.signals["cancelled"] + 1))
        dialog.show()
        self.app.processEvents()
        return dialog

    def _visible(self, dialog):
        names = ("cancel_btn", "later_btn", "close_btn", "update_btn", "progress_bar", "progress_label",
                 "status_label", "error_box", "size_line")
        return {name for name in names if getattr(dialog, name).isVisible()}

    def test_idle_shows_version_size_notes_and_the_two_buttons(self) -> None:
        dialog = self._dialog(size=12_345_678)
        self.assertEqual(dialog.state, UpdateDialog.IDLE)
        self.assertIn("v1.2.3", dialog.title.text())
        self.assertIn("v1.2.3", dialog.version_line.text())
        self.assertIn(f"v{VERSION}", dialog.version_line.text())
        self.assertEqual(dialog.size_line.text(), "İndirme boyutu: 11.8 MB")
        self.assertEqual(dialog.later_btn.text(), "Daha Sonra")
        self.assertEqual(dialog.update_btn.text(), "Şimdi Güncelle")
        self.assertEqual(self._visible(dialog), {"later_btn", "update_btn", "size_line"})
        self.assertIn("Notlar", dialog.notes.toPlainText())
        self.assertTrue(dialog.notes.isReadOnly())

    def test_size_line_is_hidden_when_the_size_is_unknown(self) -> None:
        for size in (0, None, "bilinmiyor", -5):
            dialog = self._dialog(size=size)
            self.assertNotIn("size_line", self._visible(dialog), size)
        self.assertEqual(self._dialog(size=2_500_000_000).size_line.text(), "İndirme boyutu: 2.3 GB")

    def test_english_texts(self) -> None:
        dialog = self._dialog(lang="en", size=1_048_576)
        self.assertEqual(dialog.size_line.text(), "Download size: 1.0 MB")
        self.assertEqual((dialog.later_btn.text(), dialog.update_btn.text()), ("Later", "Update Now"))
        dialog.show_error("boom")
        self.assertEqual(dialog.error_label.text(), "The update could not be completed: boom")
        self.assertEqual(dialog.update_btn.text(), "Try Again")

    def test_update_button_starts_the_download_state(self) -> None:
        dialog = self._dialog()
        dialog.update_btn.click()
        self.assertEqual(self.signals, {"accepted": 1, "deferred": 0, "cancelled": 0})
        self.assertEqual(dialog.state, UpdateDialog.DOWNLOADING)
        self.assertEqual(self._visible(dialog), {"cancel_btn", "progress_bar", "progress_label"})
        self.assertEqual((dialog.progress_bar.minimum(), dialog.progress_bar.maximum()), (0, 0), "ilk ilerlemeye dek belirsiz")

    def test_progress_shows_percent_size_and_speed_beyond_two_gigabytes(self) -> None:
        dialog = self._dialog()
        dialog.update_btn.click()
        dialog.update_download_progress(5_000_000_000, 6_000_000_000, 2.5)
        self.assertEqual(dialog.progress_bar.value(), 83)
        self.assertIn("4.7 GB / 5.6 GB (83%)", dialog.progress_label.text())
        self.assertIn("2.50 MB/s", dialog.progress_label.text())
        dialog.update_download_progress(1024, 0, 0.0)  # toplam bilinmiyor
        self.assertEqual(dialog.progress_bar.maximum(), 0)
        self.assertIn("1.0 KB", dialog.progress_label.text())

    def test_late_progress_after_the_state_changed_is_ignored(self) -> None:
        dialog = self._dialog()
        dialog.show_installing()
        dialog.update_download_progress(10, 100, 1.0)
        self.assertFalse(dialog.progress_bar.isVisible())

    def test_installing_state_has_no_buttons_and_cannot_be_closed(self) -> None:
        dialog = self._dialog()
        dialog.show_installing()
        self.assertEqual(self._visible(dialog), {"status_label"})
        self.assertIn("Kuruluyor", dialog.status_label.text())
        dialog.reject()
        QApplication.sendEvent(dialog, QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier))
        dialog.close()
        self.assertTrue(dialog.isVisible(), "kurulum başladıktan sonra pencere kapanmaz")
        self.assertEqual(self.signals, {"accepted": 0, "deferred": 0, "cancelled": 0})

    def test_error_stays_open_inline_with_retry_and_no_message_box(self) -> None:
        dialog = self._dialog()
        dialog.update_btn.click()
        dialog.show_error("Dosya bütünlüğü doğrulanamadı (checksum).")
        self.assertTrue(dialog.isVisible())
        self.assertEqual(dialog.state, UpdateDialog.ERROR)
        self.assertEqual(self._visible(dialog), {"later_btn", "update_btn", "error_box"})
        self.assertEqual(dialog.error_label.text(), "Güncelleme tamamlanamadı: Dosya bütünlüğü doğrulanamadı (checksum).")
        self.assertEqual(dialog.update_btn.text(), "Tekrar Dene")
        dialog.update_btn.click()  # tekrar dene: yeniden indirme durumu, hata satırı kaybolur
        self.assertEqual(dialog.state, UpdateDialog.DOWNLOADING)
        self.assertEqual(self.signals["accepted"], 2)
        self.assertNotIn("error_box", self._visible(dialog))
        dialog.show_error("yine olmadı")
        dialog.update_btn.click()
        self.assertEqual(dialog.state, UpdateDialog.DOWNLOADING)

    def test_closing_while_downloading_cancels_the_download_and_closes(self) -> None:
        for how in ("escape", "x", "button", "reject"):
            dialog = self._dialog()
            dialog.update_btn.click()
            if how == "escape":
                QApplication.sendEvent(dialog, QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier))
            elif how == "x":
                dialog.close()
            elif how == "button":
                dialog.cancel_btn.click()
            else:
                dialog.reject()
            self.assertFalse(dialog.isVisible(), how)
            self.assertEqual((self.signals["cancelled"], self.signals["deferred"]), (1, 0), how)

    def test_later_and_escape_defer_exactly_once(self) -> None:
        dialog = self._dialog()
        dialog.later_btn.click()
        self.assertFalse(dialog.isVisible())
        self.assertEqual(self.signals, {"accepted": 0, "deferred": 1, "cancelled": 0})
        dialog = self._dialog()
        QApplication.sendEvent(dialog, QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier))
        self.assertEqual(self.signals["deferred"], 1)

    def test_mandatory_update_has_no_later_button_and_closing_is_not_a_decline(self) -> None:
        dialog = self._dialog(mandatory=True)
        self.assertEqual(self._visible(dialog), {"update_btn"})
        dialog.reject()
        self.assertEqual(self.signals["deferred"], 0)

    def test_waiting_for_a_running_job_can_be_closed_without_side_effects(self) -> None:
        dialog = self._dialog()
        dialog.show_waiting_for_job()
        self.assertEqual(self._visible(dialog), {"close_btn", "status_label"})
        self.assertEqual(dialog.status_label.text(), "Sıkıştırma bitince kurulum başlayacak.")
        dialog.close_btn.click()
        self.assertFalse(dialog.isVisible())
        self.assertEqual(self.signals, {"accepted": 0, "deferred": 0, "cancelled": 0})

    def test_enter_does_not_press_cancel_by_accident(self) -> None:
        dialog = self._dialog()
        self.assertTrue(dialog.update_btn.isDefault())
        for button in (dialog.cancel_btn, dialog.later_btn, dialog.close_btn):
            self.assertFalse(button.autoDefault())

    def test_notes_support_html_plain_text_and_empty(self) -> None:
        self.assertEqual(self._dialog(notes="Yenilikler:\n- bir\n- iki").notes.toPlainText().splitlines(), ["Yenilikler:", "- bir", "- iki"])
        self.assertTrue(self._dialog(notes="").notes.toPlainText().strip())

    def test_every_state_fits_without_overflow_at_the_minimum_size(self) -> None:
        dialog = self._dialog(size=1_000_000, notes="satır\n" * 80)
        long_error = "Uzun bir hata iletisi " * 12
        for name, enter in (("idle", lambda: None), ("downloading", dialog.update_btn.click),
                            ("error", lambda: dialog.show_error(long_error)), ("installing", dialog.show_installing)):
            enter()
            self.app.processEvents()
            dialog.resize(dialog.minimumSizeHint())
            self.app.processEvents()
            layout = dialog.layout()
            self.assertGreaterEqual(dialog.height(), layout.minimumSize().height(), name)
            self.assertGreaterEqual(dialog.width(), layout.minimumSize().width(), name)
            self.assertEqual(dialog.minimumWidth(), 520, name)


# --------------------------------------------------------------------------------------------------- tepsi
class FakeTrayWindow:
    """TrayIcon'un ana pencereden beklediği yüzey."""

    def __init__(self, pending=""):
        self.pending = pending
        self.calls = []
        self.config = types.SimpleNamespace(get=lambda key, default=None: {"theme": "dark", "language": "tr"}.get(key, default))

    def pending_update_version(self):
        return self.pending

    def show_pending_update(self):
        self.calls.append("update")

    def _open_settings(self):
        self.calls.append("settings")

    def force_quit(self):
        self.calls.append("quit")


class TrayUpdateRowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def _tray(self, pending="", lang="tr"):
        window = FakeTrayWindow(pending)
        tray = TrayIcon(window, QIcon(), None, lang=lang)
        self.addCleanup(lambda: destroy(tray, tray.menu))
        return window, tray

    def test_update_row_is_first_bold_with_an_icon_and_a_separator_below(self) -> None:
        _window, tray = self._tray("1.2.3")
        actions = tray.menu.actions()
        self.assertIs(actions[0], tray.update_action)
        self.assertTrue(actions[1].isSeparator())
        self.assertIs(actions[1], tray.update_separator)
        self.assertEqual(tray.update_action.text(), "Güncelle · v1.2.3")
        self.assertTrue(tray.update_action.font().bold())
        self.assertFalse(tray.update_action.icon().isNull())
        self.assertTrue(tray.update_action.isVisible() and tray.update_separator.isVisible())

    def test_row_is_visible_only_while_an_update_is_pending(self) -> None:
        window, tray = self._tray("")
        self.assertFalse(tray.update_action.isVisible())
        self.assertFalse(tray.update_separator.isVisible(), "ayırıcı da gizlenir (menü ayırıcıyla başlamasın)")
        tray.set_update_available(True, "2.0.0")
        self.assertTrue(tray.update_action.isVisible())
        self.assertEqual(tray.update_action.text(), "Güncelle · v2.0.0")
        tray.set_update_available(False)
        self.assertFalse(tray.update_action.isVisible())

    def test_old_bottom_row_is_gone_and_quit_stays_last(self) -> None:
        _window, tray = self._tray("1.2.3")
        texts = [a.text() for a in tray.menu.actions()]
        self.assertFalse([x for x in texts if "●" in x or "mevcut" in x.lower()])
        self.assertIs(tray.menu.actions()[-1], tray.quit_action)

    def test_state_is_correct_when_the_tray_is_recreated_or_the_menu_rebuilt(self) -> None:
        # Eski hata: tepsi kapatılıp açılınca (yeni TrayIcon) satır, pencere "güncelleme var" bilse de gizli kalıyordu
        window = FakeTrayWindow("1.2.3")
        first = TrayIcon(window, QIcon(), None)
        destroy(first, first.menu)
        second = TrayIcon(window, QIcon(), None)
        self.addCleanup(lambda: destroy(second, second.menu))
        self.assertTrue(second.update_action.isVisible())
        self.assertEqual(second.update_action.text(), "Güncelle · v1.2.3")
        # menü her açıldığında pencerenin gerçek durumundan okunur
        window.pending = ""
        second.menu.aboutToShow.emit()
        self.assertFalse(second.update_action.isVisible())
        window.pending = "3.0.0"
        second.menu.aboutToShow.emit()
        self.assertTrue(second.update_action.isVisible())
        self.assertEqual(second.update_action.text(), "Güncelle · v3.0.0")

    def test_language_change_keeps_the_row_and_translates_it(self) -> None:
        _window, tray = self._tray("1.2.3")
        tray.retranslate("en")
        self.assertEqual(tray.update_action.text(), "Update · v1.2.3")
        self.assertTrue(tray.update_action.isVisible())
        tray.retranslate("tr")
        self.assertEqual(tray.update_action.text(), "Güncelle · v1.2.3")

    def test_click_opens_the_update_window_and_never_installs_directly(self) -> None:
        window, tray = self._tray("1.2.3")
        tray.update_action.trigger()
        self.assertEqual(window.calls, [], "menü kapanınca (olay döngüsünde) açılır")
        QCoreApplication.processEvents()
        self.assertEqual(window.calls, ["update"])

    def test_row_text_without_a_known_version_falls_back_to_a_plain_label(self) -> None:
        _window, tray = self._tray("")
        tray.set_update_available(True)
        self.assertEqual(tray.update_action.text(), "Şimdi Güncelle")

    def test_menu_is_a_real_qmenu_with_the_expected_order(self) -> None:
        _window, tray = self._tray("1.2.3")
        self.assertIsInstance(tray.menu, QMenu)
        visible = [a for a in tray.menu.actions() if a.isVisible() and not a.isSeparator()]
        self.assertEqual(visible[0], tray.update_action)
        self.assertEqual(visible[1], tray.show_action)
        self.assertEqual(visible[-1], tray.quit_action)


# --------------------------------------------------------------------------------------------------- ana pencere
class FakeDownload:
    instances: list = []

    def __init__(self, installer, url, size, checksum):
        self.args = (url, size, checksum)
        self.running = False
        FakeDownload.instances.append(self)

    def start(self):
        self.running = True

    def isRunning(self):
        return self.running

    def stop(self):
        self.running = False

    def wait(self, msecs=None):
        return True


def _memory_config(**data) -> Config:
    cfg = object.__new__(Config)
    cfg.path, cfg._seed_path, cfg.data = "", None, deepcopy(DEFAULTS)
    cfg.data.update({"show_notifications": True, "auto_update_install": False}, **data)
    cfg.save = lambda *a, **k: None
    return cfg


class QuietWindow(mw.MainWindow):
    """FFmpeg hazırlığı yok. Kurucu `QTimer.singleShot(200, _prepare_ffmpeg)` kurar; zamanlayıcı testten SONRA (yama
    kalkmışken) ateşlenirse gerçek GPU/ffmpeg taraması iş parçacığı çalışıp kapanmış pencereyle çökerdi: bu yüzden
    yama değil, alt sınıfta kalıcı olarak boş bırakılır."""

    def _prepare_ffmpeg(self, *args, **kwargs):
        return None


class MainWindowUpdateIntegrationTests(ModalGuard, unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        super().setUp()
        FakeDownload.instances = []
        patches = [
            mock.patch.object(mw, "DownloadThread", FakeDownload),
            mock.patch.object(UpdateInstaller, "preflight", return_value=(True, "")),
            mock.patch.object(UpdateInstaller, "install_update", return_value=True),
            mock.patch.object(UpdateInstaller, "cleanup"),
        ]
        started = [p.start() for p in patches]
        self.mock_preflight, self.mock_install, self.mock_cleanup = started[1], started[2], started[3]
        for p in patches:
            self.addCleanup(p.stop)
        theme = ThemeManager(self.app)
        theme.apply_from_setting("dark")
        self.installer = UpdateInstaller()
        self.window = QuietWindow(_memory_config(), theme, mock.MagicMock(), self.installer)
        # Çevrimdışı (offscreen) platformda QSystemTrayIcon.supportsMessages() False döner: sahte tepsi balonunu test edebilmek için True yap
        self.window.notifier._supports_messages = lambda: True
        self.addCleanup(self._close)
        self.w = self.window

    def _close(self):
        self.window._quitting = True
        self.window.close()
        if self.window.update_dialog is not None:
            self.window.update_dialog.close()
        self.app.processEvents()
        destroy(self.window)

    def _offer(self, mandatory=False, version="1.2.3", size=4_000_000):
        self.w._on_update_available(version, URL, "<p>Yenilikler</p>", mandatory, size, SHA)

    def _open_dialog(self):
        self._offer()
        self.w.show_pending_update()
        self.app.processEvents()
        return self.w.update_dialog

    # ---- sunum
    def test_offer_remembers_the_pending_version_but_opens_nothing(self) -> None:
        self._offer()
        self.assertEqual(self.w.pending_update_version(), "1.2.3")
        self.assertTrue(self.w.title_bar.update_btn.isVisibleTo(self.w.title_bar), "başlıkta küçük ↑ görünür")
        self.assertEqual(self.w.title_bar.update_btn.text(), "", "yalnızca simge: başlıkta metinli pill yok")
        self.assertIsNone(self.w.update_dialog)
        self.assertEqual(FakeDownload.instances, [])

    # ---- Ayarlar > Güncellemeler: "↑ Güncelle · vX" düğmesi
    def _settings(self, updater=None):
        from src.gui.settings_dialog import SettingsDialog

        dialog = SettingsDialog(self.w.config, "", "", self.w, updater=updater, theme=self.w.theme)
        self.addCleanup(lambda d=dialog: (d.setModal(False), d.hide(), destroy(d)))
        dialog.open()  # _open_settings gibi kalıcı (modal); exec() testi bekletirdi
        self.app.processEvents()
        return dialog

    def _assert_settings_button(self, dialog, version) -> None:
        self.assertTrue(dialog.update_open_btn.isVisibleTo(dialog))
        self.assertFalse(dialog.update_status.isVisibleTo(dialog), "düğme durum metninin yerini alır")
        self.assertEqual(dialog.update_open_btn.text(), f"↑  Güncelle · v{version}")
        self.assertEqual(dialog.update_open_btn.toolTip(), f"Yeni sürüm v{version} hazır; ayrıntılar ve kurulum için tıklayın")
        self.assertEqual(dialog.update_open_btn.property("class"), "primary")

    def test_settings_without_a_pending_update_shows_the_status_line_only(self) -> None:
        dialog = self._settings()
        self.assertFalse(dialog.update_open_btn.isVisibleTo(dialog))
        self.assertTrue(dialog.update_status.isVisibleTo(dialog))
        self.assertIn(VERSION, dialog.update_status.text())

    def test_settings_opened_with_a_pending_update_shows_the_button(self) -> None:
        self._offer()
        self._assert_settings_button(self._settings(), "1.2.3")

    def test_update_found_while_settings_is_open_shows_the_button_live(self) -> None:
        dialog = self._settings()
        self.assertFalse(dialog.update_open_btn.isVisibleTo(dialog))
        self._offer()
        self._assert_settings_button(dialog, "1.2.3")
        self._offer(version="1.2.4")  # daha yeni sürüm: metin güncellenir
        self._assert_settings_button(dialog, "1.2.4")

    def test_settings_button_closes_settings_then_opens_the_update_dialog(self) -> None:
        self._offer()
        dialog = self._settings()
        self.assertIsNone(self.w.update_dialog)
        dialog.update_open_btn.click()
        self.assertFalse(dialog.isVisible(), "Ayarlar kapanır (modal olduğundan üstündeki pencere tıklanamazdı)")
        self.assertEqual(dialog.result(), QDialog.DialogCode.Rejected.value, "kaydedilmemiş ayarlar uygulanmaz")
        self.assertIsNone(self.w.update_dialog, "güncelleme penceresi olay döngüsünün bir sonraki turunda açılır")
        self.app.processEvents()
        self.assertIsInstance(self.w.update_dialog, UpdateDialog)
        self.assertTrue(self.w.update_dialog.isVisible())
        self.assertEqual(self.w.update_dialog.state, UpdateDialog.IDLE)
        self.assertEqual((FakeDownload.instances, self.mock_install.call_count), ([], 0), "tıklamak kurmaz")

    def test_manual_check_that_finds_an_update_shows_the_button(self) -> None:
        from src.utils.updater import UpdateChecker

        checker = UpdateChecker(self.w.config)
        checker.update_available.connect(self.w._on_update_available)  # gerçek uygulamadaki bağlantı
        dialog = self._settings(updater=checker)
        dialog.update_check.start("Kontrol ediliyor…")  # "Kontrol Et" (ağa çıkmadan)
        checker._on_worker_result({"updateAvailable": True, "version": "99.0.0", "download_url": URL,
                                   "checksum": SHA, "fileSize": 1000})
        self.assertEqual(self.w.pending_update_version(), "99.0.0")
        self._assert_settings_button(dialog, "99.0.0")
        self.assertFalse(dialog.update_check.running, "dönen simge durur")
        self.assertTrue(dialog.check_btn.isEnabled())

    def test_pill_or_tray_opens_the_dialog_even_when_the_main_window_is_hidden_and_never_installs(self) -> None:
        self._offer()
        self.assertFalse(self.w.isVisible())
        self.w.show_pending_update()
        self.app.processEvents()
        dialog = self.w.update_dialog
        self.assertIsInstance(dialog, UpdateDialog)
        self.assertTrue(dialog.isVisible(), "ana pencere gizliyken de güncelleme penceresi görünür olmalı")
        self.assertEqual(dialog.state, UpdateDialog.IDLE)
        self.assertEqual(dialog.size_line.text(), "İndirme boyutu: 3.8 MB")
        self.assertEqual((FakeDownload.instances, self.mock_install.call_count), ([], 0))
        raised = []
        with mock.patch.object(dialog, "raise_", side_effect=lambda: raised.append("raise")), \
                mock.patch.object(dialog, "activateWindow", side_effect=lambda: raised.append("activate")):
            self.w.show_pending_update()  # ikinci tık: ikinci pencere açılmaz, mevcut olan öne gelir
        self.assertIs(self.w.update_dialog, dialog)
        self.assertEqual(raised, ["raise", "activate"])

    def test_title_bar_arrow_opens_the_same_dialog_and_never_installs(self) -> None:
        self.assertFalse(self.w.title_bar.update_btn.isVisibleTo(self.w.title_bar), "bekleyen güncelleme yokken gizli")
        self._offer()
        self.w.title_bar.update_btn.click()
        self.app.processEvents()
        dialog = self.w.update_dialog
        self.assertIsInstance(dialog, UpdateDialog)
        self.assertEqual(dialog.state, UpdateDialog.IDLE)
        self.assertEqual((FakeDownload.instances, self.mock_install.call_count), ([], 0))
        with mock.patch.object(self.w, "_show_update_dialog") as again:
            self.w.title_bar.update_btn.click()  # Ayarlar düğmesi/tepsi satırıyla aynı yol: ikinci pencere açılmaz
        again.assert_not_called()
        self.assertIs(self.w.update_dialog, dialog)

    def test_nothing_happens_without_a_pending_update(self) -> None:
        self.w.show_pending_update()
        self.assertIsNone(self.w.update_dialog)

    def test_closed_dialog_is_forgotten_so_the_next_click_opens_a_fresh_one(self) -> None:
        first = self._open_dialog()
        first.later_btn.click()
        self.app.processEvents()
        self.assertIsNone(self.w.update_dialog)
        self.assertEqual(self.w.pending_update_version(), "1.2.3", "Daha Sonra: pill/tepsi satırı kalır")
        self.w.show_pending_update()
        self.assertIsNotNone(self.w.update_dialog)
        self.assertIsNot(self.w.update_dialog, first)

    # ---- indirme -> kurma
    def test_full_success_path_downloads_once_then_installs_in_the_background_and_quits_cleanly(self) -> None:
        dialog = self._open_dialog()
        dialog.update_btn.click()
        self.assertEqual(len(FakeDownload.instances), 1)
        self.assertEqual(FakeDownload.instances[0].args, (URL, 4_000_000, SHA))
        self.mock_preflight.assert_called_once()
        dialog.update_accepted.emit()  # aynı anda ikinci indirme başlamaz
        self.assertEqual(len(FakeDownload.instances), 1)
        self.installer.download_progress.emit(2_000_000, 4_000_000, 1.0)
        self.assertEqual(dialog.progress_bar.value(), 50)
        self.installer.download_complete.emit("C:/Temp/MediaCompressor_Update.pkg")
        self.mock_install.assert_called_once_with("C:/Temp/MediaCompressor_Update.pkg", visible=False, old_version=VERSION)
        self.assertTrue(self.w._installing)
        self.assertEqual(dialog.state, UpdateDialog.DOWNLOADING, "install_update taklit: install_started sinyali gelmedi")
        self.installer.install_started.emit()
        self.assertEqual(dialog.state, UpdateDialog.INSTALLING)
        with mock.patch.object(mw.QTimer, "singleShot") as single_shot:
            self.installer.install_complete.emit()
        single_shot.assert_called_once_with(0, self.w._quit_for_update)

    def test_a_visible_window_asks_the_new_version_to_open_its_window_again(self) -> None:
        self.w.show()
        self.app.processEvents()
        dialog = self._open_dialog()
        dialog.update_btn.click()
        self.installer.download_complete.emit("C:/Temp/u.pkg")
        self.assertTrue(self.mock_install.call_args.kwargs["visible"])
        self.w.hide()

    def test_download_failure_stays_in_the_dialog_with_retry_and_keeps_the_pending_update(self) -> None:
        dialog = self._open_dialog()
        dialog.update_btn.click()
        self.installer.download_failed.emit("Dosya bütünlüğü doğrulanamadı (checksum).")
        self.assertEqual(dialog.state, UpdateDialog.ERROR)
        self.assertTrue(dialog.isVisible())
        self.assertIn("checksum", dialog.error_label.text())
        self.assertEqual(self.w.pending_update_version(), "1.2.3")
        FakeDownload.instances[0].running = False  # indirme iş parçacığı çıktı
        dialog.update_btn.click()  # Tekrar dene
        self.assertEqual(len(FakeDownload.instances), 2)
        self.assertEqual(dialog.state, UpdateDialog.DOWNLOADING)

    def test_install_failure_allows_retry_and_a_new_install_attempt(self) -> None:
        dialog = self._open_dialog()
        dialog.update_btn.click()
        self.installer.download_complete.emit("C:/Temp/u.pkg")
        self.assertTrue(self.w._installing)
        self.installer.install_failed.emit("Çalışan uygulama dosyası değiştirilemedi: erişim reddedildi")
        self.assertFalse(self.w._installing)
        self.assertEqual(dialog.state, UpdateDialog.ERROR)
        FakeDownload.instances[0].running = False
        dialog.update_btn.click()
        self.assertEqual(len(FakeDownload.instances), 2, "tekrar dene yeniden indirir (başarısız paket silinmişti)")

    def test_preflight_failure_is_shown_inline_without_downloading(self) -> None:
        self.mock_preflight.return_value = (False, "Uygulamanın bulunduğu klasöre yazılamıyor (C:/Program Files/X).")
        dialog = self._open_dialog()
        dialog.update_btn.click()
        self.assertEqual(FakeDownload.instances, [])
        self.assertEqual(dialog.state, UpdateDialog.ERROR)
        self.assertIn("klasöre yazılamıyor", dialog.error_label.text())

    def test_closing_the_dialog_while_downloading_cancels_and_a_late_completion_never_installs(self) -> None:
        dialog = self._open_dialog()
        dialog.update_btn.click()
        with mock.patch.object(UpdateInstaller, "cancel_download") as cancel:
            dialog.close()  # X
        cancel.assert_called_once()
        self.mock_cleanup.assert_called()
        self.assertFalse(dialog.isVisible())
        # indirme tam bu sırada bitmişti: sinyal geç gelir
        self.installer.download_complete.emit("C:/Temp/u.pkg")
        self.mock_install.assert_not_called()
        self.assertFalse(self.w._installing)
        self.assertIsNone(self.w._pending_install)
        self.assertEqual(self.w.pending_update_version(), "1.2.3", "iptal: pill/tepsi satırı kalır")

    def test_a_download_started_again_after_cancel_is_not_blocked_by_the_old_thread(self) -> None:
        dialog = self._open_dialog()
        dialog.update_btn.click()
        dialog.reject()
        self.w.show_pending_update()
        self.w.update_dialog.update_btn.click()
        self.assertEqual(len(FakeDownload.instances), 2)

    def test_download_finishing_during_a_compression_waits_and_installs_when_the_job_ends(self) -> None:
        dialog = self._open_dialog()
        dialog.update_btn.click()
        self.w.worker = types.SimpleNamespace(isRunning=lambda: True, stop=lambda: None, wait=lambda *a: True)
        self.installer.download_complete.emit("C:/Temp/u.pkg")
        self.mock_install.assert_not_called()
        self.assertEqual(self.w._pending_install, "C:/Temp/u.pkg")
        self.assertEqual(dialog.state, UpdateDialog.WAITING)
        # iş bitti (işçi iş parçacığı sinyalden hemen sonra hâlâ "çalışıyor" görünebilir)
        self.w._on_job_finished({"cancelled": False, "ok": 1, "skip": 0, "fail": 0})
        self.mock_install.assert_called_once_with("C:/Temp/u.pkg", visible=False, old_version=VERSION)
        self.w.worker = None

    def test_cancelled_compression_does_not_strand_the_dialog_in_waiting(self) -> None:
        """E2E H5: isteğe bağlı paket sıkıştırma sürerken indi, iş İPTAL edildi: kendiliğinden kurulmaz ama pencere
        "bekliyor"da (tek düğme Kapat) kalmamalı; "Şimdi Güncelle" yeniden indirmeden kurmalı."""
        dialog = self._open_dialog()
        dialog.update_btn.click()
        self.w.worker = types.SimpleNamespace(isRunning=lambda: True, stop=lambda: None, wait=lambda *a: True)
        self.installer.download_complete.emit("C:/Temp/u.pkg")
        self.assertEqual(dialog.state, UpdateDialog.WAITING)
        downloads = len(FakeDownload.instances)

        self.w._on_job_finished({"cancelled": True, "ok": 0, "skip": 0, "fail": 0})
        self.w.worker = None
        self.mock_install.assert_not_called()
        self.assertEqual(self.w._pending_install, "C:/Temp/u.pkg", "paket silinmez")
        self.assertEqual(dialog.state, UpdateDialog.IDLE)
        self.assertTrue(dialog.update_btn.isVisibleTo(dialog))
        self.assertTrue(dialog.later_btn.isVisibleTo(dialog))
        self.assertFalse(dialog.close_btn.isVisibleTo(dialog))

        dialog.update_btn.click()
        self.mock_install.assert_called_once_with("C:/Temp/u.pkg", visible=False, old_version=VERSION)
        self.assertEqual(len(FakeDownload.instances), downloads, "yeniden indirilmez")

    def test_reopening_the_dialog_with_a_downloaded_package_and_no_job_is_not_stuck(self) -> None:
        dialog = self._open_dialog()
        dialog.update_btn.click()
        self.w.worker = types.SimpleNamespace(isRunning=lambda: True, stop=lambda: None, wait=lambda *a: True)
        self.installer.download_complete.emit("C:/Temp/u.pkg")
        dialog.close_btn.click()  # bekleme penceresini kapat
        self.w._on_job_finished({"cancelled": True, "ok": 0, "skip": 0, "fail": 0})
        self.w.worker = None
        self.w.show_pending_update()
        reopened = self.w.update_dialog
        self.assertIsNotNone(reopened)
        self.assertEqual(reopened.state, UpdateDialog.IDLE)
        self.assertTrue(reopened.update_btn.isVisibleTo(reopened))

    def test_compression_started_between_download_and_install_defers_the_install(self) -> None:
        self.w.worker = types.SimpleNamespace(isRunning=lambda: True, stop=lambda: None, wait=lambda *a: True)
        self.w._upd_mandatory = False
        self.w._begin_install("C:/Temp/u.pkg")
        self.mock_install.assert_not_called()
        self.assertEqual(self.w._pending_install, "C:/Temp/u.pkg")
        self.w.worker = None

    def test_no_new_compression_can_start_while_the_update_installs(self) -> None:
        self.w._installing = True
        with mock.patch.object(self.w, "_collect_settings", side_effect=AssertionError("iş başlamamalı")):
            self.w._start_stop()

    def test_dialog_blocks_the_automatic_installer_while_it_is_open(self) -> None:
        self.w._on_update_available("1.2.3", URL, "", False, 1, SHA)
        self.assertTrue(self.w._is_idle_for_update())
        self.w.show_pending_update()
        self.assertFalse(self.w._is_idle_for_update())

    # ---- zorunlu / otomatik
    def test_mandatory_update_downloads_silently_without_a_dialog_and_failure_is_a_balloon(self) -> None:
        tray = mock.MagicMock()
        self.w.tray = tray
        self._offer(mandatory=True)
        self.assertIsNone(self.w.update_dialog)
        self.assertEqual(len(FakeDownload.instances), 1)
        self.installer.download_failed.emit("ağ koptu")
        tray.notify.assert_called_once()
        self.assertEqual(self.w.pending_update_version(), "1.2.3", "mandatory + indirme hatası: düğme/satır çalışır kalır")
        self.w.tray = None

    def test_mandatory_update_waits_for_a_running_job_and_then_downloads_even_if_it_was_cancelled(self) -> None:
        self.w.worker = types.SimpleNamespace(isRunning=lambda: True, stop=lambda: None, wait=lambda *a: True)
        self._offer(mandatory=True)
        self.assertEqual(FakeDownload.instances, [])
        self.w._on_job_finished({"cancelled": True, "ok": 0, "skip": 0, "fail": 0})
        self.assertEqual(len(FakeDownload.instances), 1)
        self.assertEqual(self.w.pending_update_version(), "1.2.3", "bekleyen güncelleme silinmez")
        self.w.worker = None

    def test_user_can_open_the_dialog_in_the_middle_of_a_silent_download(self) -> None:
        self._offer(mandatory=True)
        self.assertEqual(len(FakeDownload.instances), 1)
        FakeDownload.instances[0].running = True
        self.w.show_pending_update()
        dialog = self.w.update_dialog
        self.assertEqual(dialog.state, UpdateDialog.DOWNLOADING)
        self.installer.download_failed.emit("kesildi")
        self.assertEqual(dialog.state, UpdateDialog.ERROR, "hata artık pencerede satır içi görünür")

    # ---- tepsi ile birlikte
    def test_tray_row_survives_hiding_and_recreating_the_tray(self) -> None:
        with mock.patch.object(mw.TrayIcon, "isSystemTrayAvailable", return_value=True):
            self.assertTrue(self.w._ensure_tray())
            self.assertFalse(self.w.tray.update_action.isVisible())
            self._offer()
            self.assertTrue(self.w.tray.update_action.isVisible())
            self.assertEqual(self.w.tray.update_action.text(), "Güncelle · v1.2.3")
            self.w._hide_tray()
            self.assertIsNone(self.w.tray)
            self.assertTrue(self.w._ensure_tray())
            self.assertTrue(self.w.tray.update_action.isVisible(), "tepsi kapat-aç sonrası satır gizli kalıyordu")
            self.assertIs(self.w.tray.menu.actions()[0], self.w.tray.update_action)
            self.w._hide_tray()

    def test_language_change_updates_the_installer_error_language(self) -> None:
        self.w._set_language("en")
        self.assertEqual(self.installer.lang, "en")
        self.w._set_language("tr")
        self.assertEqual(self.installer.lang, "tr")

    # ---- güncellendi bildirimi
    def test_updated_notice_goes_to_the_tray_balloon_in_the_ui_language(self) -> None:
        tray = mock.MagicMock()
        self.w.tray = tray
        self.w.show_updated_notice("0.9.0")
        title, text = tray.showMessage.call_args.args[:2]  # Notifier tek yol olarak QSystemTrayIcon.showMessage'ı çağırır
        self.assertEqual(text, f"Medya Sıkıştırıcı v{VERSION} sürümüne güncellendi.")
        self.w.lang = "en"
        self.w.show_updated_notice("0.9.0")
        self.assertEqual(tray.showMessage.call_args.args[1], f"{mw.get_app_name('en')} was updated to v{VERSION}.")
        self.w.tray = None

    def test_updated_notice_respects_the_notifications_setting_and_works_without_a_tray(self) -> None:
        self.w.config.data["show_notifications"] = False
        tray = mock.MagicMock()
        self.w.tray = tray
        self.w.show_updated_notice("0.9.0")
        tray.showMessage.assert_not_called()
        tray.notify.assert_not_called()
        self.w.config.data["show_notifications"] = True
        self.w.tray = None
        with mock.patch.object(self.w.notifier, "notify", return_value=False) as notify:
            self.w.show_updated_notice("0.9.0")  # tepsi yok: Notifier'a sorulur, çökmez (Windows'ta alt süreç başlatılmaz)
        notify.assert_called_once()


# --------------------------------------------------------------------------------------------------- ayarlar
class SettingsCheckResultTests(ModalGuard, unittest.TestCase):
    """Ayarlardaki "Kontrol et" sonucu: başarısız denetim artık "Güncel" göstermez (check_failed hiç yayınlanmıyordu)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def _dialog(self, checker):
        from src.gui.settings_dialog import SettingsDialog

        dialog = SettingsDialog(_memory_config(), "", "", None, updater=checker)
        self.addCleanup(lambda: (dialog.hide(), destroy(dialog)))
        return dialog

    def _checker(self):
        from src.utils.updater import UpdateChecker

        config = mock.MagicMock()
        config.get.side_effect = lambda key, default=None: {"language": "tr"}.get(key, default)
        return UpdateChecker(config)

    def test_a_failed_check_is_shown_as_failed_not_as_up_to_date(self) -> None:
        checker = self._checker()
        dialog = self._dialog(checker)
        for trigger in (lambda: checker._on_worker_network_error("getaddrinfo failed"),
                        lambda: checker._on_worker_server_error(503), checker._on_worker_bad_reply):
            dialog.update_status.setText("")
            trigger()
            self.assertIn("Kontrol edilemedi", dialog.update_status.text())
            self.assertNotIn("Güncel", dialog.update_status.text())

    def test_a_successful_check_still_says_up_to_date_or_new_version(self) -> None:
        checker = self._checker()
        dialog = self._dialog(checker)
        checker._on_worker_result({"updateAvailable": False})
        self.assertIn("Güncel", dialog.update_status.text())


# --------------------------------------------------------------------------------------------------- açılış
class StartupWiringTests(unittest.TestCase):
    """main.py doğrudan çalıştırılamaz (uygulama başlatır): sıra ve bayrak işleme kaynakta sınanır."""

    def setUp(self) -> None:
        self.source = (ROOT / "main.py").read_text(encoding="utf-8")

    def test_previous_instance_is_awaited_before_the_lock_and_the_application(self) -> None:
        wait = self.source.index("wait_for_previous_instance(sys.argv)")
        self.assertLess(wait, self.source.index("QLockFile(lock_path)"))
        self.assertLess(wait, self.source.index("app = QApplication(sys.argv)"))

    def test_startup_guard_runs_after_the_lock_so_double_clicks_are_not_counted_as_failed_starts(self) -> None:
        # Kilide takılıp çıkan ikinci başlatma "açılış" sayılırsa, güncellemeden sonraki ilk 60 sn içinde iki kez çift
        # tıklamak SAĞLAM yeni sürümü geri aldırırdı.
        lock = self.source.index("lock.tryLock(100)")
        guard = self.source.index("self_update.startup_guard(")
        self.assertGreater(guard, lock)
        self.assertLess(guard, self.source.index("app.setQuitOnLastWindowClosed"))
        rollback = self.source[guard:guard + 700]
        self.assertIn("Guard.ROLLED_BACK", rollback)
        self.assertLess(rollback.index("lock.unlock()"), rollback.index("self_update.spawn("), "eski sürüm kilidi alabilsin")
        self.assertIn('["--minimized"]', rollback)
        self.assertNotIn("_try_raise_existing", self.source[:lock].split("def main():")[1], "kilitten önce yoklama yok")

    def test_health_is_confirmed_after_a_minute_and_on_clean_exit(self) -> None:
        self.assertIn("HEALTHY_AFTER_SECONDS * 1000", self.source)
        self.assertIn("confirm_healthy", self.source)
        self.assertIn("aboutToQuit", self.source)
        self.assertIn(">= 10", self.source)
        # kendini güncelleyip çıkan süreç sağlıklı saymaz: `.old` yeni sürümün denemesine aittir
        self.assertIn("if not installer.relaunching:", self.source)

    def test_flags_are_handled(self) -> None:
        self.assertIn("self_update.updated_from(sys.argv)", self.source)
        self.assertIn("self_update.wants_window(sys.argv)", self.source)
        self.assertIn("show_updated_notice(updated_from)", self.source)
        self.assertIn('"--minimized" in sys.argv and not show_window', self.source)
        sleep = self.source.index("time.sleep(2)")
        self.assertIn("--wait-pid", self.source[sleep - 200:sleep], "güncelleme yeniden başlatması 2 sn beklemez")

    def test_flag_helpers_understand_the_relaunch_arguments(self) -> None:
        args = ["MediaCompressor.exe", *self_update.relaunch_args(True, "1.0.0", 4242)]
        self.assertEqual(self_update.flag_value(args, "--wait-pid"), "4242")
        self.assertEqual(self_update.updated_from(args), "1.0.0")
        self.assertTrue(self_update.wants_window(args))
        hidden = ["MediaCompressor.exe", *self_update.relaunch_args(False, "", 7)]
        self.assertFalse(self_update.wants_window(hidden))
        self.assertIn("--minimized", hidden)
        self.assertIsNone(self_update.updated_from(hidden))

    def test_dialog_class_is_a_real_qdialog(self) -> None:
        self.assertTrue(issubclass(UpdateDialog, QDialog))


if __name__ == "__main__":
    unittest.main()
