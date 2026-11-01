"""Kurulum bitince eski süreç GERÇEKTEN çıkmalı: görünür "Kuruluyor" penceresi `QApplication.quit()`'i iptal ettirmemeli.

E2E'de (gerçek exe) bulundu: pencereli akışta pencere INSTALLING durumunda kapanmayı reddeder; Qt 6'da `quit()` görünür pencereleri
kapatmayı dener, reddeden varsa çıkış iptal olur → eski süreç sonsuza dek yaşıyor, yeni süreç `--wait-pid` için 15 sn bekleyip vazgeçiyordu.
Önceki birim testleri pencereyi sahte nesneyle değiştirdiği için görmedi: burada GERÇEK UpdateDialog ve gerçek olay döngüsü var.
"""
import os
import sys
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(__file__))
from _support import ROOT  # noqa: E402,F401

from PyQt6 import sip  # noqa: E402
from PyQt6.QtCore import QCoreApplication, QTimer  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from src.gui import main_window as mw  # noqa: E402
from src.gui.update_dialog import UpdateDialog  # noqa: E402

MW = mw.MainWindow


class _Window:
    """MainWindow'un gerçek `_quit_for_update`'i; `force_quit` gerçek pencerenin yaptığı gibi QApplication.quit() çağırır."""

    def __init__(self):
        self.force_quit = lambda: QApplication.instance().quit()
        self._quit_for_update = lambda: MW._quit_for_update(self)


class QuitForUpdateTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qapp = QApplication.instance() or QApplication([])

    def _dialog(self):
        dialog = UpdateDialog(version="1.1.0", release_notes="notlar", parent=None, lang="tr")
        dialog.show_installing()
        dialog.show()
        self.assertTrue(dialog.isVisible())
        self.addCleanup(sip.delete, dialog)  # kurulum durumundaki pencere close()'u reddeder: gerçekten yok et (modal pencere sızmasın)
        return dialog

    def _run_loop(self, window) -> int:
        QTimer.singleShot(0, window._quit_for_update)
        QTimer.singleShot(3000, lambda: QCoreApplication.exit(99))
        return self.qapp.exec()

    def test_the_event_loop_ends_even_though_the_installing_dialog_refuses_to_close(self):
        self._dialog()
        self.assertEqual(self._run_loop(_Window()), 0, "döngü 0 ile bitmeli (99 = açık pencere çıkışı iptal ettirdi)")

    def test_the_hard_exit_watchdog_is_armed_only_for_the_frozen_app(self):
        self._dialog()
        with mock.patch.object(mw.self_update, "arm_exit_watchdog") as arm:
            self._run_loop(_Window())
        arm.assert_not_called()
        self._dialog()
        with mock.patch.object(mw.self_update, "arm_exit_watchdog") as arm, mock.patch.object(sys, "frozen", True, create=True):
            self._run_loop(_Window())
        arm.assert_called_once()


if __name__ == "__main__":
    unittest.main()
