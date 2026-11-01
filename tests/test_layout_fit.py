"""Kısa pencerede sol panel kaydırılır; kartlar ve düğmeler üst üste binmez / kırpılmaz."""

from __future__ import annotations

import os
import sys
import unittest
from copy import deepcopy
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from PyQt6.QtWidgets import QApplication, QScrollArea  # noqa: E402

from src.gui.main_window import MainWindow  # noqa: E402
from src.utils.config import DEFAULTS, Config  # noqa: E402
from src.utils.theme_manager import ThemeManager  # noqa: E402


def _settle():
    for _ in range(4):
        QApplication.processEvents()


class LayoutFitTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._keep_app_alive = QApplication.instance() or QApplication([])
        cfg = object.__new__(Config)
        cfg.path, cfg._seed_path, cfg.data = "", None, deepcopy(DEFAULTS)
        cfg.save = lambda *a, **k: None
        cfg.data["show_notifications"] = False
        theme = ThemeManager(cls._keep_app_alive)
        theme.apply_from_setting("dark")
        with mock.patch.object(MainWindow, "_prepare_ffmpeg", lambda *a, **k: None):
            cls.win = MainWindow(cfg, theme, mock.MagicMock(), mock.MagicMock())
        cls.win.show()

    @classmethod
    def tearDownClass(cls):
        cls.win.close()

    def test_left_panel_lives_in_a_scroll_area(self):
        self.assertIsInstance(self.win.left_scroll, QScrollArea)
        self.assertTrue(self.win.left_scroll.widgetResizable())

    def test_inner_panel_is_never_squeezed_below_its_content_at_small_heights(self):
        left = self.win.left_scroll.widget()
        for size in ((860, 560), (1000, 640), (1200, 700)):
            self.win.resize(*size)
            _settle()
            need = left.layout().minimumSize().height()
            self.assertGreaterEqual(left.height() + 1, need, size)

    def test_scrollbar_appears_only_when_the_panel_does_not_fit(self):
        self.win.resize(860, 560)
        _settle()
        self.assertGreater(self.win.left_scroll.verticalScrollBar().maximum(), 0)
        self.win.resize(1440, 1000)
        _settle()
        self.assertEqual(self.win.left_scroll.verticalScrollBar().maximum(), 0)


if __name__ == "__main__":
    unittest.main()
