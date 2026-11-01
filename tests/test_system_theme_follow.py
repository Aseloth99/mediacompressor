"""Tema "Sistem" iken Windows acik/koyu degisince uygulama (yeniden baslatmadan) takip etmeli."""

from __future__ import annotations

import os
import pathlib
import sys
import unittest
from copy import deepcopy
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from PyQt6.QtWidgets import QApplication

from src.gui.main_window import MainWindow
from src.utils import theme_manager
from src.utils.config import DEFAULTS, Config
from src.utils.theme_manager import ThemeManager


def _memory_config(theme: str) -> Config:
    cfg = object.__new__(Config)
    cfg.path, cfg._seed_path, cfg.data = "", None, deepcopy(DEFAULTS)
    cfg.data["theme"] = theme
    cfg.save = lambda *a, **k: None
    return cfg


class SystemThemeFollowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _window(self, theme: str):
        tm = ThemeManager(self.app)
        with mock.patch.object(MainWindow, "_prepare_ffmpeg", lambda *a, **k: None):
            return MainWindow(_memory_config(theme), tm, mock.MagicMock(), mock.MagicMock()), tm

    def test_follows_the_system_when_theme_is_system(self):
        w, tm = self._window("system")
        with mock.patch.object(theme_manager, "is_system_dark", return_value=True):
            w._on_system_scheme_changed()
            self.assertEqual(tm.get_current_theme(), "neumorphic_dark")
        with mock.patch.object(theme_manager, "is_system_dark", return_value=False):
            w._on_system_scheme_changed()
            self.assertEqual(tm.get_current_theme(), "neumorphic_light")
        w.close()

    def test_a_fixed_theme_is_left_alone(self):
        w, tm = self._window("light")
        tm.apply_from_setting("light")
        with mock.patch.object(theme_manager, "is_system_dark", return_value=True):
            w._on_system_scheme_changed()
        self.assertEqual(tm.get_current_theme(), "neumorphic_light")
        w.close()


if __name__ == "__main__":
    unittest.main()
