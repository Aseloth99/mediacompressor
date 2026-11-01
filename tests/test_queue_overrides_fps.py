"""Kuyruk: geniş pencerede iki sütun, sağ tıkla dosyaya özel istisna (çözünürlük / FPS), video için de önizleme;
kare hızı ayarı (varsayılan Orijinal, yalnızca düşürür); seçili satır vurgu renginde (hardal değil);
genel ilerleme ve kalan süre iş miktarına göre.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(__file__))
from _support import AUTO_BITRATE, TempDirTestCase  # noqa: E402

from PyQt6.QtCore import QCoreApplication  # noqa: E402
from PyQt6.QtGui import QColor  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from src.core.job_manager import JobWorker  # noqa: E402
from src.core.video_compressor import VideoCompressor, effective_fps, parse_rate, source_fps  # noqa: E402
from src.gui import queue_panel as qp  # noqa: E402
from src.gui.queue_panel import QueuePanel, override_label, override_values  # noqa: E402
from src.utils.theme_manager import ThemeManager  # noqa: E402

FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")


def _app():
    return QApplication.instance() or QApplication([])


class _QueueCase(TempDirTestCase):
    def setUp(self):
        super().setUp()
        self.app = _app()
        self.theme = ThemeManager(self.app)
        self.theme.apply_from_setting("dark")
        self.q = QueuePanel()
        self.q.set_status_palette(self.theme.get_palette())
        self.addCleanup(self.q.deleteLater)
        self.files = []
        for name in ("a.jpg", "b.mp4", "c.jpg", "d.mov", "e.jpg"):
            p = self.tmp / name
            p.write_bytes(b"x" * 4096)
            self.files.append(str(p))
        self.q.set_files(self.files)

    def show(self, w, h=500):
        self.q.resize(w, h)
        self.q.show()
        QCoreApplication.processEvents()


class TwoColumnTest(_QueueCase):
    def test_wide_queue_flows_into_two_columns_and_narrow_into_one(self):
        # eşik yazı tipine bağlı (gerçek Segoe UI 10 pt: sütun başına ~453 px); testte ölçüden hesaplanır
        self.show(2 * self.q.layout_info.min_col + 40)
        self.assertEqual(self.q.columns, 2)
        r0 = self.q.visualItemRect(self.q.item(0))
        r1 = self.q.visualItemRect(self.q.item(1))
        r2 = self.q.visualItemRect(self.q.item(2))
        self.assertEqual(r0.top(), r1.top(), "ikinci dosya ilkinin yanında")
        self.assertGreater(r1.left(), r0.left())
        self.assertGreater(r2.top(), r0.top(), "üçüncü dosya alt satırda")
        self.show(self.q.layout_info.min_col + 60)
        self.assertEqual(self.q.columns, 1)
        r0 = self.q.visualItemRect(self.q.item(0))
        r1 = self.q.visualItemRect(self.q.item(1))
        self.assertGreater(r1.top(), r0.top())

    def test_threshold_leaves_room_for_name_status_and_size(self):
        info = self.q.layout_info
        self.show(2 * info.min_col + 2 + 20 + 4)  # çerçeve + kaydırma payı + 4 px
        self.assertEqual(self.q.columns, 2)
        _icon, name, status, size = info.parts(self.q.visualItemRect(self.q.item(0)))
        self.assertGreaterEqual(name.width(), qp.NAME_MIN - 2)
        self.assertLessEqual(name.right(), status.left())
        self.assertLessEqual(status.right(), size.left() + 1)

    def test_selected_row_uses_the_accent_not_mustard(self):
        self.show(self.q.layout_info.min_col + 60)
        self.q.item(1).setSelected(True)
        QCoreApplication.processEvents()
        img = self.q.viewport().grab().toImage()
        rect = self.q.visualItemRect(self.q.item(1))
        _icon, name, status, size = self.q.layout_info.parts(rect)
        sample = img.pixelColor(status.left() - 4, rect.center().y())  # ad ile durum arası boşluk
        accent = QColor(self.theme.get_palette()["accent"])
        self.assertGreater(sample.hsvSaturation(), 40, sample.name())
        self.assertLess(abs(sample.hsvHue() - accent.hsvHue()), 20, f"{sample.name()} vurgu tonunda olmalı")

    def test_accent_soft_is_an_opaque_color(self):
        for mode in ("dark", "light"):
            self.theme.apply_from_setting(mode)
            soft = self.theme.get_palette()["accent_soft"]
            self.assertRegex(soft, r"^#[0-9a-f]{6}$", "8 haneli yarı saydam hex QSS'te yanlış karışıyordu")


class OverrideTest(_QueueCase):
    def test_override_labels_values_and_kind_filtering(self):
        img, vid = self.files[0], self.files[1]
        self.q.set_override([img, vid], "video_res", "720p")
        self.q.set_override([img, vid], "fps", "30")
        self.q.set_override([img, vid], "image_res", qp.ORIGINAL)
        ov = self.q.overrides()
        self.assertEqual(ov[vid], {"video_res": "720p", "fps": "30"}, "resme video ayarı verilmez")
        self.assertEqual(ov[img], {"image_res": qp.ORIGINAL})
        self.assertEqual(override_values(ov[vid]), {"video_res": 1280, "fps": 30})
        self.assertEqual(override_values(ov[img]), {"image_res": None}, "Orijinal = küçültme yok")
        self.assertEqual(override_label(ov[vid], "tr"), "720p · 30 fps")
        self.assertIn("720p", self.q.item(1).toolTip())
        self.q.set_override([vid], "fps", None)
        self.assertEqual(self.q.overrides()[vid], {"video_res": "720p"})
        self.q.clear_overrides([vid, img])
        self.assertEqual(self.q.overrides(), {})

    def test_overrides_survive_reorder_and_drop_with_removed_files(self):
        vid = self.files[1]
        self.q.set_override([vid], "video_res", "480p")
        self.q.apply_order(list(reversed(self.files)))
        self.assertIn(vid, self.q.overrides())
        self.q.set_files([p for p in self.files if p != vid])
        self.assertNotIn(vid, self.q.overrides())

    def _menu_for(self, paths):
        captured = []

        class Spy(qp.QMenu):
            def exec(self, *_a, **_k):  # noqa: A003
                captured.append(self)

        self.show(self.q.layout_info.min_col + 60)
        self.q.clearSelection()
        for p in paths:
            self.q.item(self.files.index(p)).setSelected(True)
        with mock.patch.object(qp, "QMenu", Spy):
            self.q._menu(self.q.visualItemRect(self.q.item(self.files.index(paths[0]))).center())
        self.assertEqual(len(captured), 1)
        return captured[0]

    @staticmethod
    def _texts(menu):
        out = []
        for a in menu.actions():
            out.append(a.text())
            if a.menu() is not None:
                out += ["> " + s for s in OverrideTest._texts(a.menu())]
        return out

    def test_video_context_menu_offers_preview_and_video_exceptions(self):
        texts = self._texts(self._menu_for([self.files[1]]))
        self.assertTrue(any("Önizleme" in s for s in texts), texts)
        self.assertIn("İstisna Uygula", texts)
        self.assertIn("> Video Çözünürlüğü", texts)
        self.assertIn("> Kare Hızı (FPS)", texts)
        self.assertNotIn("> Resim Boyutu", texts)

    def test_mixed_selection_offers_both_kinds(self):
        texts = self._texts(self._menu_for([self.files[0], self.files[1]]))
        self.assertIn("> Video Çözünürlüğü", texts)
        self.assertIn("> Resim Boyutu", texts)

    def test_choosing_an_exception_from_the_menu_applies_it_to_the_selection(self):
        menu = self._menu_for([self.files[1], self.files[3]])
        sub = next(a.menu() for a in menu.actions() if a.text() == "İstisna Uygula")
        fps_menu = next(a.menu() for a in sub.actions() if a.text() == "Kare Hızı (FPS)")
        next(a for a in fps_menu.actions() if a.text() == "24 fps").trigger()
        ov = self.q.overrides()
        self.assertEqual(ov[self.files[1]], {"fps": "24"})
        self.assertEqual(ov[self.files[3]], {"fps": "24"})

    def test_while_running_only_waiting_files_can_get_exceptions(self):
        self.q.mark(self.files[1], "run")
        self.q.set_locked(True)
        menu = self._menu_for([self.files[1]])
        sub = next(a for a in menu.actions() if a.text() == "İstisna Uygula")
        self.assertFalse(sub.isEnabled(), "başlamış dosyanın ayarı değişmez")
        self.assertFalse(any(a.text().startswith("Kuyruktan") for a in menu.actions()))

    def test_double_click_previews_videos_too(self):
        seen = []
        self.q.preview_requested.connect(seen.append)
        self.q._dbl(self.q.item(1))
        self.assertEqual(seen, [self.files[1]])


class WorkerOverrideTest(unittest.TestCase):
    def test_file_setting_prefers_the_exception_and_none_means_original(self):
        w = JobWorker({"video_res": 1920, "fps": None, "image_res": 2400,
                       "overrides": {"v.mp4": {"video_res": None, "fps": 30}}})
        self.assertIsNone(w.file_setting("v.mp4", "video_res"), "istisna Orijinal: küçültme yok")
        self.assertEqual(w.file_setting("v.mp4", "fps"), 30)
        self.assertEqual(w.file_setting("w.mp4", "video_res"), 1920)
        self.assertEqual(w.file_setting("w.mp4", "image_res"), 2400)


class FpsCommandTest(TempDirTestCase):
    def test_rate_parsing_and_never_raising_the_frame_rate(self):
        self.assertAlmostEqual(parse_rate("30000/1001"), 29.97, places=2)
        self.assertIsNone(parse_rate("0/0"))
        self.assertIsNone(parse_rate(None))
        self.assertEqual(effective_fps(30, 60), 30.0)
        self.assertIsNone(effective_fps(30, 29.97), "zaten 30: süzgeç gereksiz")
        self.assertIsNone(effective_fps(60, 24), "kare çoğaltılmaz")
        self.assertEqual(effective_fps(24, None), 24.0, "kaynak bilinmiyorsa uygulanır")
        self.assertIsNone(effective_fps(None, 60))
        self.assertEqual(source_fps([{"type": "audio"}, {"type": "video", "fps": 59.94}]), 59.94)

    def test_fps_filter_comes_before_scaling(self):
        vc = VideoCompressor("ffmpeg")
        streams = [{"index": 0, "type": "video", "width": 1920, "height": 1080}]  # çift boyut: kırpma yok
        cmd = vc.build_cmd("in.mp4", "out.mp4", "cpu", "h264", AUTO_BITRATE, 24, "slow", "128k", 1280, fps=30,
                           streams=streams)
        vf = cmd[cmd.index("-vf") + 1]
        self.assertTrue(vf.startswith("fps=30,scale="), vf)
        cmd = vc.build_cmd("in.mp4", "out.mp4", "cpu", "h264", AUTO_BITRATE, 24, "slow", "128k", None,
                           streams=streams)
        self.assertNotIn("-vf", cmd, "varsayılan (Orijinal) kare hızına dokunmaz")

    def test_compress_skips_the_filter_when_the_source_is_slower(self):
        src = self.tmp / "in.mp4"
        src.write_bytes(b"s" * 5000)
        vc = VideoCompressor("ffmpeg", "ffprobe")
        commands = []

        def fake_run(cmd, *_a):
            commands.append(list(cmd))
            Path(cmd[-1]).write_bytes(b"v" * 100)
            return "ok"

        for src_fps, expect in ((60.0, True), (24.0, False)):
            commands.clear()
            with mock.patch.object(vc, "duration", return_value=10.0), \
                 mock.patch.object(vc, "probe_streams", return_value=[{"index": 0, "type": "video", "codec": "h264", "fps": src_fps}]), \
                 mock.patch.object(vc, "_run", side_effect=fake_run):
                ok, _msg = vc.compress(str(src), str(self.tmp / f"o{int(src_fps)}.mp4"), "cpu", "h264", AUTO_BITRATE,
                                       24, "slow", "128k", None, fps=30)
            self.assertTrue(ok)
            vf = commands[0][commands[0].index("-vf") + 1] if "-vf" in commands[0] else ""
            self.assertEqual("fps=30" in vf, expect, (src_fps, vf))

    @unittest.skipUnless(FFMPEG and FFPROBE, "ffmpeg/ffprobe yok")
    def test_real_ffmpeg_halves_a_60_fps_clip(self):
        clip = self.tmp / "clip60.mp4"
        subprocess.run(
            [FFMPEG, "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
             "-i", "testsrc2=size=320x240:rate=60:duration=2", "-c:v", "libx264", "-preset", "ultrafast",
             "-crf", "0", "-pix_fmt", "yuv420p", str(clip)],
            check=True, timeout=120, stdin=subprocess.DEVNULL,
        )
        out = self.tmp / "out.mp4"
        vc = VideoCompressor(FFMPEG, FFPROBE)
        ok, msg = vc.compress(str(clip), str(out), "cpu", "h264", AUTO_BITRATE, 24, "ultrafast", "128k", None, fps=30)
        self.assertTrue(ok, msg)
        probe = subprocess.run(
            [FFPROBE, "-v", "error", "-select_streams", "v:0", "-count_frames",
             "-show_entries", "stream=avg_frame_rate,nb_read_frames", "-of", "json", str(out)],
            capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL,
        )
        stream = json.loads(probe.stdout)["streams"][0]
        self.assertAlmostEqual(parse_rate(stream["avg_frame_rate"]), 30.0, delta=0.1)
        self.assertAlmostEqual(int(stream["nb_read_frames"]), 60, delta=2)


class WindowWiringTest(unittest.TestCase):
    def _window(self):
        from src.gui.main_window import MainWindow
        from src.utils.config import DEFAULTS, Config

        app = _app()
        cfg = object.__new__(Config)
        cfg.path, cfg._seed_path, cfg.data = "", None, deepcopy(DEFAULTS)
        cfg.save = lambda *a, **k: None
        theme = ThemeManager(app)
        theme.apply_from_setting("dark")
        with mock.patch.object(MainWindow, "_prepare_ffmpeg", lambda *a, **k: None):
            w = MainWindow(cfg, theme, mock.MagicMock(), mock.MagicMock())
        self.addCleanup(w.close)
        return w

    def test_fps_defaults_to_original_and_profiles_reset_it(self):
        w = self._window()
        self.assertIsNone(w.adv_dialog.fps_value())
        w.adv_dialog.set_fps(30)
        self.assertEqual(w.adv_dialog.fps_value(), 30)
        w._apply_profile("balanced")
        self.assertIsNone(w.adv_dialog.fps_value())

    def test_settings_carry_fps_and_exceptions_to_the_worker(self):
        w = self._window()
        with tempfile.TemporaryDirectory() as tmp:
            vid = os.path.join(tmp, "v.mp4")
            Path(vid).write_bytes(b"x" * 100)
            w._add_sources([vid])
            w.queue.set_override([vid], "video_res", "720p")
            w.adv_dialog.set_fps(25)
            s = w._collect_settings()
        self.assertEqual(s["fps"], 25)
        self.assertEqual(s["overrides"], {vid: {"video_res": 1280}})

    def test_overall_bar_and_eta_follow_the_work_not_the_file_count(self):
        from src.core.eta import JobEta
        from src.gui import main_window as mw

        w = self._window()
        MB = 1024 * 1024
        files = [(f"i{i}.jpg", 2 * MB) for i in range(9)] + [("big.mp4", 2000 * MB)]
        w._job_t0 = 1000.0
        w._eta = JobEta(files, 1000.0)
        with mock.patch.object(mw.time, "time", return_value=1001.0):
            w._on_file_started("big.mp4")
        with mock.patch.object(mw.time, "time", return_value=1002.0):
            w._on_file_progress("big.mp4", 0.005)
        self.assertNotIn("kalan", w.stats.text(), "%1'den önce kalan süre yazılmaz")
        self.assertNotIn("kalan", w.video_label.text())
        with mock.patch.object(mw.time, "time", return_value=1061.0):
            w._on_file_progress("big.mp4", 0.5)
        self.assertIn("kalan", w.stats.text())
        self.assertIn("kalan", w.video_label.text())
        self.assertGreater(w.overall.value() / mw.OVERALL_STEPS, 0.4, "bir dosya bitmeden de ilerler")


if __name__ == "__main__":
    unittest.main()
