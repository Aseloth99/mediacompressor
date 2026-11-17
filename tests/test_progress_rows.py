"""Ilerleme: bosta gorunmez; is surerken tek ince genel cubuk + her dosyanin ilerlemesi kendi kuyruk satirinda.
Sol ayar paneli gizlenebilir (durum hatirlanir); Gelismis/Onizleme dugmeleri kaydirmadan gorunur."""

from __future__ import annotations

import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from copy import deepcopy
from unittest import mock

from PyQt6.QtWidgets import QApplication

from src.gui import main_window as mw
from src.gui.main_window import MainWindow
from src.gui.queue_panel import ROW_H
from src.utils.config import DEFAULTS, Config
from src.utils.theme_manager import ThemeManager


def _memory_config(**values) -> Config:
    """Config that never touches the user's real settings file."""
    cfg = object.__new__(Config)
    cfg.path, cfg._seed_path, cfg.data = "", None, deepcopy(DEFAULTS)
    cfg.data["show_notifications"] = False
    cfg.data.update(values)
    cfg.save = lambda *a, **k: None
    return cfg


def _settle(app):
    for _ in range(4):
        app.processEvents()


class _Case(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def window(self, theme_name="light", **values) -> MainWindow:
        theme = ThemeManager(self.app)
        theme.apply_from_setting(theme_name)
        cfg = _memory_config(**values)
        with mock.patch.object(MainWindow, "_prepare_ffmpeg", lambda *a, **k: None):
            w = MainWindow(cfg, theme, mock.MagicMock(), mock.MagicMock())
        self.addCleanup(w.close)
        w.show()
        _settle(self.app)
        return w

    def queue_with(self, w, names):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        paths = []
        for name in names:
            p = pathlib.Path(tmp.name) / name
            p.write_bytes(b"\0" * 64)
            paths.append(str(p))
        w.queue.set_files(paths)
        return paths


class ProgressRowsTest(_Case):
    def test_box_follows_the_job_and_has_no_second_bar(self):
        w = self.window()
        self.assertFalse(w.prog_box.isVisible())
        self.assertFalse(w.stats.isVisible())
        w._show_progress(True)
        self.assertTrue(w.overall.isVisible())
        self.assertFalse(hasattr(w, "video_bar"), "dosya ilerlemesi kuyruk satırında; ikinci çubuk yok")
        self.assertFalse(w.overall.isTextVisible())
        self.assertLessEqual(w.overall.height(), 8)
        w._clear_queue()
        self.assertFalse(w.prog_box.isVisible())

    def test_running_video_shows_percent_and_eta_in_its_row(self):
        from src.core.eta import JobEta

        w = self.window()
        clip, photo = self.queue_with(w, ["clip.mp4", "photo.jpg"])
        w._job_t0 = 1000.0
        w._progress_total = 2
        w._eta = JobEta([(clip, 100), (photo, 1)], 1000.0)
        with mock.patch.object(mw.time, "time", return_value=1000.0):
            w._on_file_started(clip)
        self.assertEqual(w.queue.progress_of(clip), 0.0)
        with mock.patch.object(mw.time, "time", return_value=1040.0):
            w._on_file_progress(clip, 0.41)
        self.assertAlmostEqual(w.queue.progress_of(clip), 0.41)
        self.assertRegex(w.queue.status_display(clip), r"^%41 · ~\d+ sn$")
        self.assertRegex(w.overall_label.text(), r"^0/2 dosya  ·  %\d+$")
        # bitiş sinyali satırı kapatır; ardından gelen 1.0 ilerlemesi satırı yeniden açmaz
        w._on_file_done(clip, "ok", {"in": 64, "out": 32})
        w._on_file_progress(clip, 1.0)
        self.assertIsNone(w.queue.progress_of(clip))
        self.assertEqual(w.queue.status_display(clip), "Tamam")
        # resimde oran yok: satır yalnızca "İşleniyor"
        w._on_file_started(photo)
        self.assertIsNone(w.queue.progress_of(photo))
        self.assertEqual(w.queue.status_display(photo), "İşleniyor")

    def test_english_row_puts_percent_after_the_number(self):
        w = self.window(language="en")
        (clip,) = self.queue_with(w, ["clip.mp4"])
        w._on_file_started(clip)
        w.queue.set_progress(clip, 0.41, "58 s")
        self.assertEqual(w.queue.status_display(clip), "41% · ~58 s")

    def test_row_progress_survives_reordering(self):
        w = self.window()
        a, b = self.queue_with(w, ["a.mp4", "b.mp4"])
        w.queue.mark(a, "run")
        w.queue.set_progress(a, 0.3, "12 sn")
        w.queue.apply_order([b, a])
        self.assertAlmostEqual(w.queue.progress_of(a), 0.3)
        self.assertEqual(w.queue.status_display(a), "%30 · ~12 sn")

    def test_row_paints_the_progress_line(self):
        w = self.window("dark")
        w.resize(1280, 760)
        (clip,) = self.queue_with(w, ["clip.mp4"])
        w.queue.mark(clip, "run")
        w.queue.set_progress(clip, 0.5, "")
        _settle(self.app)
        rect = w.queue.visualItemRect(w.queue.item(0))
        img = w.queue.viewport().grab().toImage()
        accent = w.queue.status_color("run")
        y = rect.bottom() - 3
        left = img.pixelColor(rect.left() + 40, y)
        right = img.pixelColor(rect.right() - 40, y)
        self.assertLess(abs(left.red() - accent.red()) + abs(left.green() - accent.green())
                        + abs(left.blue() - accent.blue()), 60, "dolu kısım vurgu renginde")
        self.assertGreater(abs(right.red() - accent.red()) + abs(right.green() - accent.green())
                           + abs(right.blue() - accent.blue()), 60, "kalan kısım iz renginde")

    def test_smallest_window_still_shows_several_rows_while_running(self):
        w = self.window()
        self.queue_with(w, [f"f{i}.mp4" for i in range(12)])
        w._show_progress(True)
        w.overall_label.setText("5/12 dosya  ·  %40")
        w.stats.setText("geçen 1 dk  ·  kalan ~2 dk")
        w.log_toggle.setChecked(False)
        w.resize(w.minimumSize())
        _settle(self.app)
        visible_rows = w.queue.viewport().height() // ROW_H
        self.assertGreaterEqual(visible_rows, 4, visible_rows)


class LeftPanelTest(_Case):
    def test_advanced_and_preview_buttons_are_visible_without_scrolling_at_760(self):
        w = self.window()
        for size in ((1280, 760), (w.minimumWidth(), w.minimumHeight())):
            w.resize(*size)
            _settle(self.app)
            for btn in (w.adv_btn, w.preview_btn):
                self.assertTrue(btn.isVisible(), size)
                top_left = btn.mapTo(w, btn.rect().topLeft())
                bottom = btn.mapTo(w, btn.rect().bottomLeft()).y()
                self.assertGreaterEqual(top_left.y(), 0)
                self.assertLessEqual(bottom, w.height(), size)
                self.assertFalse(w.left_scroll.isAncestorOf(btn), "düğmeler kaydırılan alanın dışında")

    def test_collapse_hides_the_panel_widens_the_queue_and_is_remembered(self):
        w = self.window()
        w.resize(1280, 760)
        _settle(self.app)
        before = w.queue.width()
        w.panel_toggle.click()
        _settle(self.app)
        self.assertFalse(w.left_panel.isVisible())
        self.assertTrue(w.config.get("left_panel_collapsed"))
        self.assertGreater(w.queue.width(), before + 250)
        self.assertEqual(w.panel_toggle.toolTip(), "Ayar panelini göster")
        w.panel_toggle.click()
        _settle(self.app)
        self.assertTrue(w.left_panel.isVisible())
        self.assertFalse(w.config.get("left_panel_collapsed"))

    def test_collapsed_state_is_restored_on_start(self):
        w = self.window(left_panel_collapsed=True)
        self.assertFalse(w.left_panel.isVisible())
        self.assertFalse(w.panel_toggle.icon().isNull())

    def test_log_toggle_sits_in_the_queue_header(self):
        w = self.window(language="en")
        self.assertTrue(w.log_toggle.isVisible())
        self.assertEqual(w.log_toggle.text(), "Log")
        header_y = w.queue_title.mapTo(w, w.queue_title.rect().center()).y()
        toggle_y = w.log_toggle.mapTo(w, w.log_toggle.rect().center()).y()
        self.assertLessEqual(abs(header_y - toggle_y), 4, "kuyruk başlığıyla aynı satırda")
        self.assertLess(w.log_toggle.mapTo(w, w.log_toggle.rect().topLeft()).y(),
                        w.queue.mapTo(w, w.queue.rect().topLeft()).y())
        w.log_toggle.setChecked(True)
        _settle(self.app)
        self.assertTrue(w.log_box.isVisible())

    def test_retry_button_sits_below_the_header_next_to_the_summary(self):
        w = self.window()
        self.queue_with(w, ["a.mp4", "b.mp4"])
        w.retry_btn.show()
        w._update_queue_actions()
        _settle(self.app)
        self.assertTrue(w.queue_sub.isVisible())
        self.assertTrue(w.queue_sub.isAncestorOf(w.retry_btn), "başlık satırını daraltmaz")
        self.assertTrue(w.queue_sub.isAncestorOf(w.queue_summary))
        self.assertGreater(w.retry_btn.mapTo(w, w.retry_btn.rect().topLeft()).y(),
                           w.log_toggle.mapTo(w, w.log_toggle.rect().bottomLeft()).y())
        w.queue.set_files([])
        w.retry_btn.hide()
        w._update_queue_actions()
        self.assertFalse(w.queue_sub.isVisible())


@unittest.skipUnless(sys.platform == "win32" and not os.environ.get("MB_SKIP_REAL"), "gerçek Windows platformu gerekir")
class RealPlatformHeaderFit(unittest.TestCase):
    def test_header_buttons_keep_their_width_in_the_smallest_window_after_failures(self):
        env = {k: v for k, v in os.environ.items() if k != "QT_QPA_PLATFORM"}
        script = str(pathlib.Path(__file__).with_name("_real_header_fit.py"))
        proc = subprocess.run([sys.executable, "-X", "utf8", "-B", script], capture_output=True, text=True,
                              timeout=300, env=env)
        self.assertEqual(proc.returncode, 0, proc.stdout[-3000:] + proc.stderr[-1500:])
        self.assertIn("FIT-OK", proc.stdout, proc.stdout[-3000:])


if __name__ == "__main__":
    unittest.main()
