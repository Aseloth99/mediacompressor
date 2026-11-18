"""Güncelleme deneyimi: pop-up yok; "Güncelle · vX" düğmesi Ayarlar'da (başlık çubuğunda değil); kullanılmıyorken otomatik kurulum."""

from __future__ import annotations

import os
import sys
import types
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from PyQt6.QtWidgets import QApplication  # noqa: E402

from src.gui.message_box import MessageBox  # noqa: E402

from src.gui import main_window as mw  # noqa: E402
from src.gui.title_bar import TitleBar  # noqa: E402

MW = mw.MainWindow
PAYLOAD = ("1.2.3", "https://macik.com.tr/u.zip", "notlar", False, 100, "ab")


class IdleRuleTest(unittest.TestCase):
    def test_truth_table(self):
        idle = MW.update_is_idle
        self.assertFalse(idle(True, False, False, 0), "iş sürerken kurulmaz")
        self.assertFalse(idle(False, True, False, 0), "pencere ekrandayken kurulmaz")
        self.assertFalse(idle(False, False, True, 0), "açık bir diyalog varken kurulmaz")
        self.assertFalse(idle(False, False, False, 3), "kuyrukta dosya varken kurulmaz")
        self.assertTrue(idle(False, False, False, 0), "pencere gizli/simge durumunda ve boşta -> uygun")


class FakeWindow:
    """MainWindow'un güncelleme yöntemlerini gerçek koduyla çalıştıran, Qt widget'ı olmayan sahte pencere."""

    def __init__(self):
        self.calls = []
        self.lang = "tr"
        self.worker = None
        self._pending_update = None
        self._auto_update_timer = None
        self._dl_thread = None
        self._download_wanted = False
        self._installing = False
        self._pending_install = None
        self.update_dialog = None
        # açık Ayarlar penceresi: bekleyen sürüm ona canlı iletilir
        settings_dialog = types.SimpleNamespace(show_pending_update=lambda v: self.calls.append(("settings", v)))
        self.findChildren = lambda cls: [settings_dialog]
        self.tray = types.SimpleNamespace(
            set_update_available=lambda available, version="": self.calls.append(("tray", available, version)),
            notify=lambda *a: self.calls.append(("balloon", a[1])),
        )
        self.installer = types.SimpleNamespace(install_support=lambda: (True, ""))
        self.config = types.SimpleNamespace(get=lambda key, default=None: self.settings.get(key, default),
                                            set=lambda key, value: self.settings.__setitem__(key, value))
        self.settings = {}
        self._schedule_auto_update = lambda: self.calls.append(("schedule",))
        self._start_silent_update = lambda: self.calls.append(("silent",))
        self._begin_silent_update = lambda payload, mandatory: self.calls.append(("mandatory-silent", payload[0], mandatory))

    # gerçek yöntemler (durumu FakeWindow üstünde okur/yazar)
    def pending_update_version(self):
        return MW.pending_update_version(self)

    def _sync_update_indicators(self):
        MW._sync_update_indicators(self)

    def _job_running(self):
        return MW._job_running(self)

    def _download_active(self):
        return MW._download_active(self)

    def _update_busy(self):
        return MW._update_busy(self)

    def _stop_auto_update_timer(self):
        MW._stop_auto_update_timer(self)

    def _update_failed(self, message):
        MW._update_failed(self, message)

    def _notify_silent_failure(self, message):
        self.calls.append(("balloon", message))


class OnUpdateAvailableTest(unittest.TestCase):
    def test_optional_update_shows_button_and_never_a_dialog(self):
        w = FakeWindow()
        with mock.patch.object(mw, "UpdateDialog", side_effect=AssertionError("pop-up açılmamalı")):
            MW._on_update_available(w, *PAYLOAD)
        self.assertIn(("settings", "1.2.3"), w.calls)
        self.assertIn(("tray", True, "1.2.3"), w.calls)
        self.assertIn(("schedule",), w.calls)
        self.assertFalse([c for c in w.calls if c[0] == "mandatory-silent"], "isteğe bağlı güncelleme kendiliğinden inmez")
        self.assertEqual(w._pending_update[0], "1.2.3")

    def test_declined_version_still_shows_button(self):
        w = FakeWindow()
        MW._on_update_available(w, *PAYLOAD)
        self.assertIn(("settings", "1.2.3"), w.calls)

    def test_mandatory_update_starts_in_background_when_idle(self):
        w = FakeWindow()
        MW._on_update_available(w, "2.0.0", "https://macik.com.tr/u.zip", "", True, 100, "ab")
        self.assertEqual([c for c in w.calls if c[0] == "mandatory-silent"], [("mandatory-silent", "2.0.0", True)])
        self.assertNotIn(("schedule",), w.calls)

    def test_mandatory_update_waits_while_a_job_runs(self):
        w = FakeWindow()
        w.worker = types.SimpleNamespace(isRunning=lambda: True)
        MW._on_update_available(w, "2.0.0", "https://macik.com.tr/u.zip", "", True, 100, "ab")
        self.assertFalse([c for c in w.calls if c[0] == "mandatory-silent"])
        self.assertIsNotNone(w._pending_update)


class AutoUpdateTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app_ = QApplication.instance() or QApplication([])

    def _fake(self, *, enabled, idle, pending=True):
        w = FakeWindow()
        w._pending_update = PAYLOAD[:5] + ("a" * 64,) if pending else None
        w._auto_update_enabled = lambda: enabled
        w._is_idle_for_update = lambda: idle
        return w

    def test_installs_only_when_enabled_idle_and_pending(self):
        for enabled, idle, pending, expect in (
            (True, True, True, True),
            (False, True, True, False),
            (True, False, True, False),
            (True, True, False, False),
        ):
            w = self._fake(enabled=enabled, idle=idle, pending=pending)
            MW._try_auto_update(w)
            self.assertEqual(("silent",) in w.calls, expect, (enabled, idle, pending))

    def test_update_without_a_checksum_is_never_installed_automatically(self):
        for checksum in ("", None, "ab", "zz" * 32):
            w = self._fake(enabled=True, idle=True)
            w._pending_update = PAYLOAD[:5] + (checksum,)
            MW._try_auto_update(w)
            self.assertNotIn(("silent",), w.calls, checksum)

    def test_a_declined_version_is_not_installed_automatically_but_a_newer_one_is(self):
        w = self._fake(enabled=True, idle=True)
        w.settings["declined_update_version"] = "1.2.3"
        w._auto_update_timer = types.SimpleNamespace(stop=lambda: w.calls.append(("timer-stop",)))
        MW._try_auto_update(w)
        self.assertNotIn(("silent",), w.calls)
        self.assertIn(("timer-stop",), w.calls)
        w = self._fake(enabled=True, idle=True)
        w.settings["declined_update_version"] = "1.2.2"
        MW._try_auto_update(w)
        self.assertIn(("silent",), w.calls)

    def test_a_mandatory_update_ignores_the_declined_version(self):
        w = self._fake(enabled=True, idle=True)
        w._pending_update = ("1.2.3", "https://macik.com.tr/u.zip", "notlar", True, 100, "a" * 64)
        w.settings["declined_update_version"] = "1.2.3"
        MW._try_auto_update(w)
        self.assertIn(("silent",), w.calls)

    def test_does_not_start_a_second_download(self):
        w = self._fake(enabled=True, idle=True)
        w._dl_thread = types.SimpleNamespace(isRunning=lambda: True)
        w._download_wanted = True
        MW._try_auto_update(w)
        self.assertNotIn(("silent",), w.calls)

    def test_does_not_start_while_an_install_is_running(self):
        w = self._fake(enabled=True, idle=True)
        w._installing = True
        MW._try_auto_update(w)
        self.assertNotIn(("silent",), w.calls)

    def test_cancelled_download_that_is_still_winding_down_does_not_block_a_new_one(self):
        w = self._fake(enabled=True, idle=True)
        w._dl_thread = types.SimpleNamespace(isRunning=lambda: True)
        w._download_wanted = False  # kullanıcı iptal etti; eski iş parçacığı henüz çıkmadı
        MW._try_auto_update(w)
        self.assertIn(("silent",), w.calls)

    def test_never_installs_automatically_when_the_app_cannot_self_update(self):
        w = self._fake(enabled=True, idle=True)
        w.installer = types.SimpleNamespace(install_support=lambda: (False, "kaynaktan çalışıyor"))
        MW._try_auto_update(w)
        self.assertNotIn(("silent",), w.calls)

    def test_scheduler_does_nothing_when_auto_install_is_off(self):
        w = FakeWindow()
        w._auto_update_enabled = lambda: False
        MW._schedule_auto_update(w)
        self.assertIsNone(w._auto_update_timer)

    def test_enabled_needs_both_settings(self):
        for check, install, expect in ((True, True, True), (True, False, False), (False, True, False)):
            cfg = {"auto_update_check": check, "auto_update_install": install}
            w = types.SimpleNamespace(config=types.SimpleNamespace(get=lambda k, d=None, c=cfg: c.get(k, d)))
            self.assertEqual(MW._auto_update_enabled(w), expect)

    def test_default_is_off(self):
        from src.utils.config import DEFAULTS

        self.assertTrue(DEFAULTS["auto_update_install"])


class FakeDialog:
    def __init__(self):
        self.errors = []
        self.waiting = 0
        self.installing = 0

    def show_error(self, message):
        self.errors.append(message)

    def show_waiting_for_job(self):
        self.waiting += 1

    def show_installing(self):
        self.installing += 1


class UpdateFailureTest(unittest.TestCase):
    """Güncelleme hatası: pencere açıksa satır içi (MessageBox YOK), arka planda tepsi balonu; bekleyen güncelleme silinmez."""

    def test_background_download_failure_has_no_modal_and_keeps_the_update(self):
        w = FakeWindow()
        w._pending_update = PAYLOAD
        with mock.patch.object(MessageBox, "warning", side_effect=AssertionError("modal açılmamalı")):
            MW._on_dl_failed(w, "ağ koptu")
        self.assertIn(("balloon", "ağ koptu"), w.calls)
        self.assertIsNotNone(w._pending_update, "pill/tepsi satırı yeniden denemek için çalışmaya devam eder")

    def test_background_install_failure_has_no_modal_and_allows_a_new_install(self):
        w = FakeWindow()
        w._installing = True
        with mock.patch.object(MessageBox, "warning", side_effect=AssertionError("modal açılmamalı")):
            MW._on_install_failed(w, "izin yok")
        self.assertIn(("balloon", "izin yok"), w.calls)
        self.assertFalse(w._installing)

    def test_failure_with_the_window_open_is_shown_inline_not_in_a_message_box(self):
        for handler in (MW._on_dl_failed, MW._on_install_failed):
            w = FakeWindow()
            w.update_dialog = FakeDialog()
            with mock.patch.object(MessageBox, "warning", side_effect=AssertionError("modal açılmamalı")), \
                 mock.patch.object(MessageBox, "critical", side_effect=AssertionError("modal açılmamalı")):
                handler(w, "izin yok")
            self.assertEqual(w.update_dialog.errors, ["izin yok"])
            self.assertFalse([c for c in w.calls if c[0] == "balloon"])

    def test_user_cancel_is_not_a_failure(self):
        w = FakeWindow()
        w.update_dialog = FakeDialog()
        MW._on_dl_failed(w, "cancelled")
        self.assertEqual(w.update_dialog.errors, [])
        self.assertEqual(w.calls, [])

    def test_download_finished_during_a_job_waits_without_a_modal(self):
        w = FakeWindow()
        w._download_wanted = True
        w._upd_mandatory = False
        w.worker = types.SimpleNamespace(isRunning=lambda: True)
        w.update_dialog = FakeDialog()
        with mock.patch.object(MessageBox, "information", side_effect=AssertionError("modal açılmamalı")):
            MW._on_dl_complete(w, "C:/tmp/u.pkg")
        self.assertEqual(w._pending_install, "C:/tmp/u.pkg")
        self.assertEqual(w.update_dialog.waiting, 1)


class TitleBarHasNoPillTest(unittest.TestCase):
    """Bekleyen güncelleme başlık çubuğunda değil Ayarlar'da gösterilir (FlexiKey ile aynı)."""

    @classmethod
    def setUpClass(cls):
        cls.app_ = QApplication.instance() or QApplication([])

    def test_title_bar_has_no_update_pill(self):
        from PyQt6.QtWidgets import QPushButton

        bar = TitleBar()
        self.addCleanup(bar.deleteLater)
        for name in ("update_btn", "update_clicked", "set_update_available"):
            self.assertFalse(hasattr(bar, name), name)
        self.assertEqual([b for b in bar.findChildren(QPushButton) if b.objectName() == "update_pill"], [])
        texts = [b.text() for b in bar.findChildren(QPushButton)]
        self.assertFalse([s for s in texts if "v1." in s or "Güncelle" in s or "Update" in s], texts)

    def test_theme_has_no_dead_pill_rule(self):
        from src.utils import theme_manager as tm

        for base, dark in ((tm.DARK, True), (tm.LIGHT, False)):
            self.assertNotIn("update_pill", tm._build(tm._with_accent(base, "cyan", dark)))


class CheckerHasNoPopupsTest(unittest.TestCase):
    def test_check_results_never_open_message_boxes(self):
        from src.utils.updater import UpdateChecker

        with mock.patch.object(MessageBox, "information", side_effect=AssertionError("pop-up")), \
             mock.patch.object(MessageBox, "warning", side_effect=AssertionError("pop-up")):
            UpdateChecker._show_info(object(), "başlık", "metin")
            UpdateChecker._show_warning(object(), "başlık", "metin")


class LocaleTest(unittest.TestCase):
    def test_new_strings_exist_in_both_languages(self):
        from src.utils.locales import t

        for lang in ("tr", "en"):
            for key in ("update_pill", "update_pill_tip", "update_new_version", "auto_update_install",
                        "update_auto_failed", "check_now", "tray_update_now", "update_size_line",
                        "update_failed_inline", "update_retry", "update_installed_toast"):
                self.assertNotEqual(t(key, lang), key, (lang, key))
        self.assertEqual(t("check_now", "tr"), "Kontrol Et")


if __name__ == "__main__":
    unittest.main()
