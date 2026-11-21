"""Kuyruk arayüzü: boşken Başlat pasif + açıklama, doluyken aktif + özet; ilk açılış boyutu ekrana göre."""

from __future__ import annotations

import os
import pathlib
import sys
import tempfile
import unittest
from copy import deepcopy
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from PyQt6.QtWidgets import QApplication

from src.gui.main_window import MainWindow
from src.utils.config import DEFAULTS, Config
from src.utils.theme_manager import ThemeManager


def _memory_config() -> Config:
    cfg = object.__new__(Config)
    cfg.path, cfg._seed_path, cfg.data = "", None, deepcopy(DEFAULTS)
    cfg.save = lambda *a, **k: None
    return cfg


class QueueUxTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _window(self) -> MainWindow:
        theme = ThemeManager(self.app)
        theme.apply_from_setting("dark")
        with mock.patch.object(MainWindow, "_prepare_ffmpeg", lambda *a, **k: None):
            w = MainWindow(_memory_config(), theme, mock.MagicMock(), mock.MagicMock())
        self.addCleanup(w.close)
        w.show()
        self.app.processEvents()
        return w

    def test_start_is_disabled_with_an_empty_queue_and_explains_why(self):
        w = self._window()
        self.assertFalse(w.start_btn.isEnabled())
        self.assertTrue(w.start_btn.toolTip())
        self.assertFalse(w.queue_summary.isVisible())

    def test_start_becomes_enabled_when_files_are_queued_and_disabled_again_when_cleared(self):
        w = self._window()
        with tempfile.TemporaryDirectory() as tmp:
            p = pathlib.Path(tmp) / "foto.jpg"
            p.write_bytes(b"x" * 2048)
            w._add_sources([str(p)])
            self.app.processEvents()
            self.assertEqual(w.queue.rowCount(), 1)
            self.assertTrue(w.start_btn.isEnabled())
            self.assertIn("Ctrl+Enter", w.start_btn.toolTip(), "kısayol ipucu")
            self.assertTrue(w.queue_summary.isVisible())
            self.assertIn("1", w.queue_summary.text())
            self.assertNotEqual(w.queue.size_text_of(w.queue.paths()[0]), "—", "kaynak boyutu hemen görünmeli")
            w._clear_queue()
            self.app.processEvents()
            self.assertFalse(w.start_btn.isEnabled())

    def test_empty_queue_paints_the_hint_without_error(self):
        w = self._window()
        pix = w.queue.viewport().grab()
        self.assertFalse(pix.isNull())

    def test_status_text_colors_follow_the_theme_palette(self):
        from PyQt6.QtGui import QColor

        w = self._window()
        with tempfile.TemporaryDirectory() as tmp:
            paths = []
            for name in ("a.jpg", "b.jpg", "c.jpg"):
                p = pathlib.Path(tmp) / name
                p.write_bytes(b"x" * 100)
                paths.append(str(p))
            w._add_sources(paths)
            self.app.processEvents()
            queued = w.queue.paths()
            palette = w.theme.get_palette()
            w.queue.mark(queued[0], "ok", {"in": 100, "out": 50})
            w.queue.mark(queued[1], "fail")
            expected_ok = QColor(palette["ok_text"]).name()
            expected_fail = QColor(palette["fail_text"]).name()
            def color(path):
                return w.queue.status_color(w.queue.status_of(path)).name()

            self.assertEqual(color(queued[0]), expected_ok)
            self.assertEqual(color(queued[1]), expected_fail)
            self.assertEqual(color(queued[2]), QColor(palette["text_muted"]).name(), "bekleyen soluk kalmalı")

    def test_output_path_is_elided_in_the_middle_and_tooltip_keeps_the_full_path(self):
        w = self._window()
        long_path = "C:/Users/usr/Desktop/cok/uzun/bir/klasor/yolu/sikistirilmis_videolar_2026"
        w.out_label.resize(180, 30)
        w.out_label.setText(long_path)
        self.assertIn("…", w.out_label.text())
        self.assertEqual(w.out_label.toolTip(), long_path)
        self.assertEqual(w.out_label.full_text(), long_path)

    def test_section_captions_follow_the_language(self):
        w = self._window()
        w.lang = "en"
        w._retranslate_ui()
        self.assertEqual(w._captions["section_source"].text(), "Source")
        self.assertEqual(w._captions["section_output"].text(), "Output Folder")
        self.assertEqual(w.out_btn.text(), "Change")

    def test_default_window_size_is_large_on_big_screens_and_fits_small_ones(self):
        class _Screen:
            def __init__(self, w, h):
                self._g = mock.Mock(width=lambda: w, height=lambda: h)

            def availableGeometry(self):
                return self._g

        with mock.patch.object(QApplication, "primaryScreen", return_value=_Screen(2560, 1400)):
            self.assertEqual(MainWindow._default_window_size(), (1440, 900))
        with mock.patch.object(QApplication, "primaryScreen", return_value=_Screen(1366, 728)):
            w, h = MainWindow._default_window_size()
            self.assertLessEqual(w, 1366)
            self.assertLessEqual(h, 728)
            self.assertGreaterEqual(w, 980)


if __name__ == "__main__":
    unittest.main()
