"""Videoyu kırpma (başlangıç/bitiş), sesi kaldırma (genel + dosyaya özel) ve seçimlerin yeniden açılışta korunması.

* Kırpma girdi tarafında ``-ss``/``-t`` ile yapılır; ilerleme kırpılmış süreye göre hesaplanır.
* Kırpılmış / sessiz çıktı kaynaktan büyük olsa bile kaynak kopyalanmaz (istenen düzenleme kaybolurdu).
* Seçilen resim boyutu, özel px değeri, hız, GPU vb. yeniden açılışta aynı kalır.
* GPU menüsü dil değişince öğe adlarını karıştırmaz (eskiden 2. öğe "CPU" diye yeniden adlandırılıyordu).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from copy import deepcopy
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(__file__))
from _support import AUTO_BITRATE, TempDirTestCase  # noqa: E402

from PyQt6.QtCore import QCoreApplication  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from src.core.job_manager import JobWorker  # noqa: E402
from src.core.video_compressor import VideoCompressor, normalize_trim, trimmed_duration  # noqa: E402
from src.gui import trim_dialog  # noqa: E402
from src.gui.queue_panel import QueuePanel, override_label, override_values, trim_fraction  # noqa: E402
from src.gui.trim_dialog import TrimDialog  # noqa: E402
from src.utils.config import DEFAULTS, Config  # noqa: E402
from src.utils.theme_manager import ThemeManager  # noqa: E402
from src.utils.timecode import clock, parse_clock  # noqa: E402

FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")


_APP = None


def _app():
    # Referans tutulur: tutulmayan QApplication hemen silinir, sonraki QPixmap kullanımı süreci çökertir.
    global _APP
    _APP = QApplication.instance() or QApplication([])
    return _APP


def after(cmd, flag):
    return cmd[cmd.index(flag) + 1]


class TimecodeTests(unittest.TestCase):
    def test_round_trip(self):
        self.assertEqual(clock(83.44, tenths=True), "1:23.4")
        self.assertEqual(clock(59.96, tenths=True), "1:00.0")
        self.assertEqual(clock(3723), "1:02:03")
        self.assertEqual(parse_clock("1:23,4"), 83.4)
        self.assertEqual(parse_clock("1:02:03"), 3723)
        self.assertEqual(parse_clock("90"), 90)
        for bad in ("1:75", "abc", "", "1::2"):
            self.assertIsNone(parse_clock(bad), bad)


class TrimMathTests(unittest.TestCase):
    def test_normalize(self):
        self.assertEqual(normalize_trim((5, 90), 120), (5.0, 90.0))
        self.assertEqual(normalize_trim((5, 120), 120), (5.0, None), "sona dayanan bitiş = sona kadar")
        self.assertEqual(normalize_trim((5, None), 120), (5.0, None))
        self.assertIsNone(normalize_trim((0, None), 120), "kırpma yok")
        self.assertIsNone(normalize_trim((0, 120), 120))
        self.assertIsNone(normalize_trim((50, 40), 120), "ters aralık yok sayılır")
        self.assertIsNone(normalize_trim(None, 120))
        self.assertIsNone(normalize_trim(("x", 3), 120))

    def test_progress_duration(self):
        self.assertEqual(trimmed_duration(120, (5.0, 90.0)), 85.0)
        self.assertEqual(trimmed_duration(120, (30.0, None)), 90.0)
        self.assertEqual(trimmed_duration(120, None), 120)


class CommandTests(unittest.TestCase):
    def setUp(self):
        self.vc = VideoCompressor("ffmpeg")

    def _cmd(self, **kw):
        return self.vc.build_cmd("in.mp4", "out.mp4", kw.pop("family", "cpu"), "h264", AUTO_BITRATE, 24, "slow",
                                 "128k", None, **kw)

    def test_trim_is_an_input_seek_before_the_input(self):
        cmd = self._cmd(trim=(5.0, 90.0))
        self.assertEqual(after(cmd, "-ss"), "5.000")
        self.assertEqual(after(cmd, "-t"), "85.000")
        self.assertLess(cmd.index("-t"), cmd.index("-i"))
        cmd = self._cmd(trim=(0.0, 30.0))
        self.assertNotIn("-ss", cmd)
        self.assertEqual(after(cmd, "-t"), "30.000")
        cmd = self._cmd(trim=(12.5, None))
        self.assertEqual(after(cmd, "-ss"), "12.500")
        self.assertNotIn("-t", cmd)

    def test_trim_comes_after_gpu_decode_flags(self):
        cmd = self._cmd(family="nvenc", trim=(5.0, 9.0), decode="cuda")
        self.assertLess(cmd.index("-hwaccel"), cmd.index("-ss"))
        self.assertLess(cmd.index("-ss"), cmd.index("-i"))

    def test_remove_audio_drops_the_audio_map_and_codec(self):
        cmd = self._cmd(remove_audio=True)
        self.assertNotIn("0:a?", cmd)
        self.assertIn("-an", cmd)
        self.assertNotIn("-c:a", cmd)
        self.assertNotIn("-b:a", cmd)
        default = self._cmd()
        self.assertIn("0:a?", default)
        self.assertEqual(after(default, "-c:a"), "aac")


class CompressTests(TempDirTestCase):
    def _compress(self, out_size, **kw):
        src = self.tmp / "in.mp4"
        src.write_bytes(b"s" * 1000)
        vc = VideoCompressor("ffmpeg", "ffprobe")
        seen = []

        def fake_run(cmd, cancel, total, cb):
            seen.append((list(cmd), total))
            Path(cmd[-1]).write_bytes(b"v" * out_size)
            return "ok"

        with mock.patch.object(vc, "duration", return_value=120.0), \
                mock.patch.object(vc, "probe_streams", return_value=None), \
                mock.patch.object(vc, "_run", side_effect=fake_run):
            ok, msg = vc.compress(str(src), str(self.tmp / "out.mp4"), "cpu", "h264", AUTO_BITRATE, 24, "slow",
                                  "128k", None, **kw)
        return ok, msg, seen, (self.tmp / "out.mp4").read_bytes()

    def test_progress_uses_the_trimmed_length(self):
        ok, _msg, seen, _ = self._compress(10, trim=(30.0, 90.0))
        self.assertTrue(ok)
        self.assertEqual(seen[0][1], 60.0)

    def test_bigger_edited_output_is_kept_not_replaced_by_the_source(self):
        ok, msg, _seen, data = self._compress(5000, remove_audio=True)
        self.assertTrue(ok)
        self.assertEqual(data, b"v" * 5000, "sessiz çıktı korunur (kaynak kopyalansaydı ses geri gelirdi)")
        self.assertNotIn("Orijinal", msg)
        ok, msg, _seen, data = self._compress(5000)
        self.assertEqual(data, b"s" * 1000, "düzenleme yoksa eski davranış: büyük çıktı yerine kaynak")


class OverrideTests(unittest.TestCase):
    def test_values_and_labels(self):
        ov = {"trim": (5.0, 90.0, 120.0), "remove_audio": "mute", "video_res": "720p"}
        self.assertEqual(override_values(ov), {"trim": (5.0, 90.0), "remove_audio": True, "video_res": 1280})
        self.assertEqual(override_values({"remove_audio": "keep"}), {"remove_audio": False})
        self.assertEqual(override_label(ov, "tr"), "✂ 0:05–1:30 · 720p · Sessiz")
        self.assertEqual(override_label({"trim": (5.5, None, 60.0)}, "en"), "✂ 0:05.5–end")
        self.assertAlmostEqual(trim_fraction(ov), 85 / 120)
        self.assertEqual(trim_fraction({"trim": (30.0, None, 120.0)}), 0.75)
        self.assertEqual(trim_fraction({}), 1.0)

    def test_worker_reads_trim_and_audio_per_file(self):
        w = JobWorker({"remove_audio": False, "overrides": {"a.mp4": {"trim": (1.0, 2.0), "remove_audio": True}}})
        self.assertEqual(w.file_setting("a.mp4", "trim"), (1.0, 2.0))
        self.assertTrue(w.file_setting("a.mp4", "remove_audio"))
        self.assertFalse(w.file_setting("b.mp4", "remove_audio"))
        self.assertIsNone(w.file_setting("b.mp4", "trim"))


class QueueMenuTests(TempDirTestCase):
    def setUp(self):
        super().setUp()
        self.app = _app()
        self.panel = QueuePanel(lang="tr")
        self.addCleanup(self.panel.deleteLater)
        self.vid = str(self.tmp / "a.mp4")
        self.vid2 = str(self.tmp / "b.mov")
        self.img = str(self.tmp / "c.jpg")
        for p in (self.vid, self.vid2, self.img):
            Path(p).write_bytes(b"x")
        self.panel.set_files([self.vid, self.vid2, self.img])

    def _texts(self, menu):
        out = []
        for act in menu.actions():
            out.append(act.text())
            if act.menu():
                out += [f"{act.text()} > {t}" for t in self._texts(act.menu())]
        return out

    def test_trim_only_for_a_single_video(self):
        self.assertIn("Kırp…", self._texts(self.panel.build_menu([self.vid])))
        self.assertNotIn("Kırp…", self._texts(self.panel.build_menu([self.vid, self.vid2])))
        self.assertNotIn("Kırp…", self._texts(self.panel.build_menu([self.img])))

    def test_audio_exception_menu_and_chip(self):
        texts = self._texts(self.panel.build_menu([self.vid, self.img]))
        self.assertIn("İstisna Uygula > Ses > Sesi Kaldır", texts)
        self.panel.set_override([self.vid, self.img], "remove_audio", "mute")
        self.assertEqual(self.panel.overrides(), {self.vid: {"remove_audio": "mute"}}, "resme ses istisnası yok")

    def test_trim_signal_and_removal(self):
        got = []
        self.panel.trim_requested.connect(got.append)
        menu = self.panel.build_menu([self.vid])
        next(a for a in menu.actions() if a.text() == "Kırp…").trigger()
        self.assertEqual(got, [self.vid])
        self.panel.set_override([self.vid], "trim", (1.0, 3.0, 10.0))
        texts = self._texts(self.panel.build_menu([self.vid]))
        self.assertIn("İstisna Uygula > Kırpmayı Kaldır", texts)


class QueueIconTests(unittest.TestCase):
    def test_image_and_video_icons_differ_in_colour(self):
        from src.gui import queue_panel as qp

        _app()
        hues = {}
        for name in ("a.jpg", "b.mp4"):
            img = qp._icon_for(name).pixmap(32, 32).toImage()
            # kenara yakın, desen dışı bir nokta: zemin rengi
            hues[name] = img.pixelColor(img.width() // 8 + 1, img.height() // 2).hsvHue()
        diff = abs(hues["a.jpg"] - hues["b.mp4"])
        self.assertGreater(min(diff, 360 - diff), 90, hues)


class TrimDialogTests(unittest.TestCase):
    def setUp(self):
        self.app = _app()
        patcher = mock.patch.object(TrimDialog, "_extract", lambda *a: None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_values_and_constraints(self):
        dlg = TrimDialog("film.mp4", 100.0, (5.0, 90.0), lang="tr")
        self.addCleanup(dlg.deleteLater)
        self.assertEqual(dlg.values(), (5.0, 90.0))
        dlg.spins["start"].setValue(95.0)  # bitişi geçemez: bitiş ileri itilir
        start, end = dlg.values()[0], dlg.spins["end"].value()
        self.assertGreaterEqual(end - start, trim_dialog.MIN_LENGTH - 1e-6)
        self.assertLessEqual(end, 100.0)
        dlg.sliders["end"].setValue(1000)  # sona: bitiş yok
        self.assertIsNone(dlg.values()[1])
        dlg._reset()
        self.assertIsNone(dlg.values(), "tamamı seçiliyse kırpma yok")
        self.assertIn("1:40.0", dlg.info.text())

    def test_time_field_accepts_minutes_and_seconds(self):
        dlg = TrimDialog("film.mp4", 600.0, None, lang="en")
        self.addCleanup(dlg.deleteLater)
        spin = dlg.spins["start"]
        self.assertEqual(spin.valueFromText("2:05.5"), 125.5)
        self.assertEqual(spin.textFromValue(125.5), "2:05.5")
        spin.lineEdit().setText("1:00")
        spin.interpretText()
        self.assertEqual(dlg.values(), (60.0, None))

    @unittest.skipUnless(FFMPEG, "ffmpeg yok")
    def test_real_frames_load(self):
        mock.patch.stopall()
        with tempfile.TemporaryDirectory() as tmp:
            clip = os.path.join(tmp, "clip.mp4")
            subprocess.run([FFMPEG, "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                            "testsrc2=size=320x180:rate=25:duration=3", "-pix_fmt", "yuv420p", clip],
                           check=True, timeout=60, stdin=subprocess.DEVNULL)
            with mock.patch("src.gui.preview_dialog.FFmpegManager") as mgr:
                mgr.return_value.find.return_value = FFMPEG
                dlg = TrimDialog(clip, 3.0, (1.0, 2.0), lang="tr")
                deadline = time.time() + 20
                while time.time() < deadline and any(
                    f.pixmap() is None or f.pixmap().isNull() for f in dlg.frames.values()
                ):
                    QCoreApplication.processEvents()
                    time.sleep(0.02)
                loaded = [not f.pixmap().isNull() for f in dlg.frames.values()]
                dlg.reject()
            self.assertEqual(loaded, [True, True])


def _config(data=None) -> Config:
    cfg = object.__new__(Config)
    cfg.path, cfg._seed_path = "", None
    cfg.data = deepcopy(DEFAULTS) if data is None else data
    cfg.save = lambda *a, **k: None
    return cfg


class _FakeGpu:
    def available_families(self):
        return ["nvenc", "amf", "cpu"]

    def resolve_mode(self, choice):
        return {"auto": "nvenc"}.get(choice, choice)

    def status_text(self):
        return "RTX — NVENC"

    def is_ok(self):
        return True


class PersistenceTests(unittest.TestCase):
    def _window(self, cfg):
        from src.gui.main_window import MainWindow

        theme = ThemeManager(_app())
        theme.apply_from_setting("dark")
        # _prepare_ffmpeg kurulumdan 200 ms sonra da çağrılır: test boyunca devre dışı (gerçek ffmpeg taraması
        # arka planda iş parçacığı başlatır); pencere iş parçacıklarını durduran close() ile kapatılır.
        patcher = mock.patch.object(MainWindow, "_prepare_ffmpeg", lambda *a, **k: None)
        patcher.start()
        self.addCleanup(patcher.stop)
        w = MainWindow(cfg, theme, mock.MagicMock(), mock.MagicMock())
        self.addCleanup(w.close)
        return w

    def test_choices_survive_a_restart(self):
        from src.gui.res_combo import res_value

        cfg = _config()
        w = self._window(cfg)
        w.image_res.setCurrentIndex(w.image_res.findText("1920px"))
        w.preset.setCurrentIndex(w.preset.findData("fast"))
        w.adv_dialog.remove_audio.setChecked(True)
        w.audio.setCurrentText("192k")
        w._save_choices()
        self.assertEqual(cfg.data["profile"], "custom", "profilden sapma Özel'e geçirir")
        self.assertEqual(cfg.data["image_res"], "1920px")

        w2 = self._window(cfg)
        self.assertEqual(res_value(w2.image_res), "1920px")
        self.assertEqual(w2.preset.currentData(), "fast")
        self.assertEqual(w2.audio.currentText(), "192k")
        self.assertTrue(w2.adv_dialog.remove_audio.isChecked())
        self.assertFalse(w2.audio.isEnabled(), "ses kaldırılırken ses kalitesi seçilemez")

    def test_custom_pixel_value_is_restored(self):
        from src.gui.res_combo import res_value

        data = deepcopy(DEFAULTS)
        data.update(profile="custom", image_res="1600px", video_res="1000px", crf=28, fps=30)
        w = self._window(_config(data))
        self.assertEqual(res_value(w.image_res), "1600px")
        self.assertEqual(res_value(w.video_res), "1000px")
        self.assertEqual(w.crf.value(), 28)
        self.assertEqual(w.adv_dialog.fps_value(), 30)
        self.assertEqual(w._collect_settings, w._collect_settings)  # pencere sağlam kuruldu

    def test_named_profile_wins_over_saved_profile_values(self):
        from src.gui.res_combo import res_value

        data = deepcopy(DEFAULTS)
        data.update(profile="balanced", image_res="1280px", preset="veryfast")
        w = self._window(_config(data))
        self.assertEqual(res_value(w.image_res), "2400px", "Dengeli kendi değerini kurar")
        self.assertEqual(w.preset.currentData(), "veryfast", "profilden bağımsız seçim yine geri gelir")

    def test_broken_values_do_not_break_startup(self):
        data = deepcopy(DEFAULTS)
        data.update(profile="custom", crf="çok", image_res=42, preset=None)
        w = self._window(_config(data))
        self.assertTrue(w.crf.value())

    def test_gpu_choice_is_kept_and_survives_language_change(self):
        cfg = _config()
        w = self._window(cfg)
        w._on_prepared(w.ffmpeg, _FakeGpu())
        texts = [w.gpu_menu.itemText(i) for i in range(w.gpu_menu.count())]
        self.assertEqual(texts[1:3], ["NVIDIA NVENC", "AMD AMF"])
        w.adv_dialog.set_gpu_choice("amf")
        w._save_choices()
        self.assertEqual(cfg.data["gpu_mode"], "amf")
        w.adv_dialog.retranslate("en")
        self.assertEqual(w.gpu_menu.itemText(1), "NVIDIA NVENC", "dil değişince 2. öğe CPU olmaz")
        self.assertEqual(w.gpu_menu.itemData(w.gpu_menu.count() - 1), "cpu")

        w2 = self._window(cfg)
        self.assertEqual(w2.adv_dialog.gpu_choice(), "auto", "GPU listesi gelmeden seçim yapılamaz")
        w2._save_choices()
        self.assertEqual(cfg.data["gpu_mode"], "amf", "liste gelmeden kayıt seçimi ezmez")
        w2._on_prepared(w2.ffmpeg, _FakeGpu())
        self.assertEqual(w2.adv_dialog.gpu_choice(), "amf")

    def test_trim_and_audio_reach_the_worker_settings(self):
        w = self._window(_config())
        with tempfile.TemporaryDirectory() as tmp:
            vid = os.path.join(tmp, "v.mp4")
            Path(vid).write_bytes(b"x" * 1000)
            w._add_sources([vid])
            w.queue.set_override([vid], "trim", (10.0, 40.0, 100.0))
            w.adv_dialog.remove_audio.setChecked(True)
            w.ffmpeg = mock.MagicMock(ffmpeg_path="ffmpeg", ffprobe_path="ffprobe")
            s = w._collect_settings()
            self.assertTrue(s["remove_audio"])
            self.assertEqual(s["overrides"][vid], {"trim": (10.0, 40.0)})
            self.assertEqual(w._eta_weight(vid), 300, "kalan süre tahmini kırpılan payla tartılır")


@unittest.skipUnless(FFMPEG and FFPROBE, "ffmpeg/ffprobe yok")
class RealTrimTests(TempDirTestCase):
    def test_trimmed_silent_output(self):
        src = self.tmp / "src.mp4"
        subprocess.run(
            [FFMPEG, "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
             "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=30:duration=6",
             "-f", "lavfi", "-i", "sine=frequency=440:duration=6",
             "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(src)],
            check=True, timeout=120, stdin=subprocess.DEVNULL,
        )
        out = self.tmp / "out.mp4"
        progress = []
        vc = VideoCompressor(FFMPEG, FFPROBE)
        ok, msg = vc.compress(str(src), str(out), "cpu", "h264", AUTO_BITRATE, 26, "ultrafast", "128k", None,
                              progress_cb=progress.append, trim=(1.5, 4.0), remove_audio=True)
        self.assertTrue(ok, msg)
        info = json.loads(subprocess.run(
            [FFPROBE, "-v", "error", "-show_entries", "format=duration:stream=codec_type", "-of", "json", str(out)],
            capture_output=True, text=True, timeout=60,
        ).stdout)
        self.assertEqual([s["codec_type"] for s in info["streams"]], ["video"], "ses yok")
        self.assertAlmostEqual(float(info["format"]["duration"]), 2.5, delta=0.15)
        self.assertEqual(progress[-1], 1.0)
        self.assertTrue(any(0.3 < p < 1.0 for p in progress) or len(progress) <= 2)


if __name__ == "__main__":
    unittest.main()
