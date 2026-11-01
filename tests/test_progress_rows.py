"""Hazir / Video: bekleniyor satirlari bosta gorunmemeli; is baslayinca gelmeli."""

from __future__ import annotations

import os
import pathlib
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from copy import deepcopy
from unittest import mock

from PyQt6.QtWidgets import QApplication

from src.gui.main_window import MainWindow
from src.utils.config import DEFAULTS, Config
from src.utils.theme_manager import ThemeManager


def _memory_config() -> Config:
    """Config that never touches the user's real settings file."""
    cfg = object.__new__(Config)
    cfg.path, cfg._seed_path, cfg.data = "", None, deepcopy(DEFAULTS)
    cfg.save = lambda *a, **k: None
    return cfg


class ProgressRowsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_rows_follow_the_job(self):
        theme = ThemeManager(self.app)
        theme.apply_from_setting("light")
        with mock.patch.object(MainWindow, "_prepare_ffmpeg", lambda *a, **k: None):
            w = MainWindow(_memory_config(), theme, mock.MagicMock(), mock.MagicMock())
        w.show()
        self.app.processEvents()
        self.assertFalse(w.prog_box.isVisible())
        self.assertFalse(w.stats.isVisible())
        w._show_progress(True, False)
        self.assertTrue(w.overall.isVisible())
        self.assertFalse(w.video_bar.isVisible())
        w._on_file_started("clip.mp4")
        self.assertTrue(w.video_bar.isVisible())
        w._on_file_started("photo.jpg")
        self.assertFalse(w.video_bar.isVisible())
        w._clear_queue()
        self.assertFalse(w.prog_box.isVisible())
        w.close()


if __name__ == "__main__":
    unittest.main()
