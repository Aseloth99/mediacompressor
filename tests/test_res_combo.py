"""Cozunurluk listesindeki 'Orijinal': gorunen yazi uygulama dilinde, saklanan deger sabit."""

from __future__ import annotations

import os
import pathlib
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from copy import deepcopy
from unittest import mock

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QComboBox

from src.gui.main_window import PROFILES, MainWindow, _parse_custom_res, _parse_video_res
from src.gui.res_combo import ORIGINAL, find_res, mark_original, res_value, select_res
from src.utils.config import DEFAULTS, Config
from src.utils.theme_manager import ThemeManager


def _memory_config(lang: str) -> Config:
    cfg = object.__new__(Config)
    cfg.path, cfg._seed_path, cfg.data = "", None, deepcopy(DEFAULTS)
    cfg.data["language"] = lang
    cfg.save = lambda *a, **k: None
    return cfg


def _window(app, lang: str) -> MainWindow:
    theme = ThemeManager(app)
    theme.apply_from_setting("light")
    with mock.patch.object(MainWindow, "_prepare_ffmpeg", lambda *a, **k: None):
        return MainWindow(_memory_config(lang), theme, mock.MagicMock(), mock.MagicMock())


class ResComboHelpersTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _combo(self) -> QComboBox:
        combo = QComboBox()
        combo.addItems(["720p", "1080p", ORIGINAL])
        mark_original(combo, "Original")
        return combo

    def test_display_text_is_translated_but_value_stays(self):
        combo = self._combo()
        self.assertEqual(combo.itemText(2), "Original")
        combo.setCurrentIndex(2)
        self.assertEqual(res_value(combo), ORIGINAL)
        combo.setCurrentIndex(1)
        self.assertEqual(res_value(combo), "1080p")

    def test_select_and_find_by_value(self):
        combo = self._combo()
        self.assertTrue(select_res(combo, ORIGINAL))
        self.assertEqual(combo.currentIndex(), 2)
        self.assertEqual(find_res(combo, "720p"), 0)
        self.assertFalse(select_res(combo, "9999px"))
        self.assertEqual(combo.currentIndex(), 2, "an unknown value must not move the selection")

    def test_retranslating_keeps_the_value(self):
        combo = self._combo()
        mark_original(combo, "Orijinal")
        self.assertEqual(combo.itemText(2), "Orijinal")
        mark_original(combo, "Original")
        self.assertEqual(res_value(combo, 2), ORIGINAL)
        self.assertEqual(combo.count(), 3, "relabelling must not add items")


class MainWindowResolutionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_english_ui_says_original(self):
        w = _window(self.app, "en")
        for combo in (w.video_res, w.image_res):
            texts = [combo.itemText(i) for i in range(combo.count())]
            self.assertIn("Original", texts)
            self.assertNotIn("Orijinal", texts)
        w.close()

    def test_turkish_ui_says_orijinal(self):
        w = _window(self.app, "tr")
        self.assertIn("Orijinal", [w.video_res.itemText(i) for i in range(w.video_res.count())])
        w.close()

    def test_quality_profile_selects_original_in_english(self):
        w = _window(self.app, "en")
        self.assertEqual(PROFILES["quality"]["video_res"], ORIGINAL)
        w._apply_profile("quality")
        self.assertEqual(res_value(w.video_res), ORIGINAL)
        self.assertEqual(w.video_res.currentText(), "Original")
        self.assertIsNone(_parse_video_res(res_value(w.video_res)), "original = no downscale")
        self.assertEqual(res_value(w.image_res), "3840px")
        w.close()

    def test_language_switch_relabels_the_selected_original(self):
        w = _window(self.app, "tr")
        w._apply_profile("quality")
        self.assertEqual(w.video_res.currentText(), "Orijinal")
        w._set_language("en")
        self.assertEqual(w.video_res.currentText(), "Original")
        self.assertEqual(res_value(w.video_res), ORIGINAL)
        w._set_language("tr")
        self.assertEqual(w.video_res.currentText(), "Orijinal")
        w.close()

    def test_custom_video_width_is_clamped_to_even(self):
        from src.gui import main_window as mw
        w = _window(self.app, "en")
        self.addCleanup(mw.VIDEO_RES.pop, "1284px", None)
        custom = w.video_res.findData(mw.CUSTOM_RES, Qt.ItemDataRole.UserRole)
        self.assertGreaterEqual(custom, 0)
        with mock.patch.object(mw.InputDialog, "getInt", return_value=(1285, True)):
            w._on_video_res_activated(custom)
        self.assertEqual(res_value(w.video_res), "1284px")
        self.assertEqual(_parse_video_res(res_value(w.video_res)), 1284)
        w.close()

    def test_preview_result_goes_to_the_right_combo(self):
        w = _window(self.app, "en")
        # image preview applied with "Original": the VIDEO combo must stay as it was
        before = res_value(w.video_res)
        w._on_preview_settings_applied(70, ORIGINAL, False)
        self.assertEqual(res_value(w.image_res), ORIGINAL)
        self.assertEqual(res_value(w.video_res), before)
        self.assertIsNone(_parse_custom_res(res_value(w.image_res)))
        # video preview with a custom size adds it to the video combo only
        w._on_preview_settings_applied(70, "1500px", True)
        self.assertEqual(res_value(w.video_res), "1500px")
        self.assertEqual(w.image_res.findText("1500px"), -1)
        w.close()


if __name__ == "__main__":
    unittest.main()
