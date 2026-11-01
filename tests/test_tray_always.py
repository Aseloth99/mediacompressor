"""Tepsi simgesi her zaman vardır: ayarlarda açma/kapama seçeneği YOK; pencere kapatılınca (X) uygulama tepsiye gizlenir.
(Tüm uygulamalarda aynı davranış: tepsi uygulamaları kapatmakla çıkmaz, "Çıkış" menüsüyle çıkılır.)"""
import os
import sys
import types
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(__file__))
from _support import ROOT  # noqa: E402,F401

from PyQt6.QtGui import QCloseEvent  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from src.gui import main_window as mw  # noqa: E402
from src.utils.config import DEFAULTS  # noqa: E402
from src.utils.locales import LOCALES  # noqa: E402

MW = mw.MainWindow


class TrayAlwaysTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qapp = QApplication.instance() or QApplication([])

    def test_there_is_no_tray_setting_any_more(self):
        self.assertNotIn("minimize_to_tray", DEFAULTS)
        for lang, table in LOCALES.items():
            self.assertNotIn("minimize_to_tray", table, lang)
        for name in ("src/gui/settings_dialog.py", "src/gui/main_window.py"):
            self.assertNotIn("minimize_to_tray", (ROOT / name).read_text(encoding="utf-8"), name)

    def test_ctrl_q_really_quits_while_alt_f4_hides_to_the_tray(self):
        import inspect
        source = inspect.getsource(MW._setup_shortcuts)
        self.assertIn('bind("Ctrl+Q", self.force_quit)', source)
        self.assertIn('bind("Alt+F4", self.close)', source)

    def _fake_window(self, tray):
        calls = []
        fake = types.SimpleNamespace(
            _quitting=False, tray=tray, config=types.SimpleNamespace(get=lambda key, default=None: default),
            hide=lambda: calls.append("hide"),
        )
        return fake, calls

    def test_closing_the_window_hides_it_to_the_tray_without_any_setting(self):
        fake, calls = self._fake_window(tray=object())
        event = QCloseEvent()
        with mock.patch.object(mw.TrayIcon, "isSystemTrayAvailable", return_value=True):
            MW.closeEvent(fake, event)
        self.assertFalse(event.isAccepted(), "X çıkış değil: pencere gizlenir")
        self.assertEqual(calls, ["hide"])

    def test_without_a_system_tray_closing_really_quits_so_the_user_is_never_locked_out(self):
        fake, calls = self._fake_window(tray=None)
        fake._hide_tray = lambda: calls.append("hide_tray")
        fake._shutdown_background = lambda: calls.append("shutdown")
        fake._save_choices = lambda: None
        fake._file_type = lambda: "all"
        fake.config = types.SimpleNamespace(get=lambda key, default=None: default, set=lambda *a, **k: None)
        event = QCloseEvent()
        with mock.patch.object(mw.TrayIcon, "isSystemTrayAvailable", return_value=False), \
                mock.patch.object(mw.QTimer, "singleShot"):
            MW.closeEvent(fake, event)
        self.assertTrue(event.isAccepted())
        self.assertIn("shutdown", calls)


if __name__ == "__main__":
    unittest.main()
