"""AV1 hangi yoldan kodlanacak ve kullanıcıya söylenir mi?

AV1 kodlayamayan bir ekran kartı + programın indirdiği "essentials" FFmpeg (SVT-AV1 yok) olunca AV1
libaom'a düşer: video süresinin ~10 katı sürer. Gelişmiş ayarlarda AV1 seçilince bunu açıkça yazmalı.
"""

from __future__ import annotations

import os
import sys
import unittest
from copy import deepcopy
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(__file__))

from PyQt6.QtWidgets import QApplication  # noqa: E402

from src.core import gpu_detector  # noqa: E402
from src.core.gpu_detector import GpuDetector  # noqa: E402
from src.utils.config import DEFAULTS, Config  # noqa: E402
from src.utils.theme_manager import ThemeManager  # noqa: E402

_APP = None


def _app():
    global _APP
    _APP = QApplication.instance() or QApplication([])
    return _APP


class RouteTests(unittest.TestCase):
    def _detector(self, supported: set[str], listed: set[str], nvenc: bool = True) -> GpuDetector:
        d = GpuDetector("ff")
        d.nvenc, d.amf = nvenc, True
        patches = [
            mock.patch.object(gpu_detector, "encoder_supported", side_effect=lambda _ff, enc: enc in supported),
            mock.patch.object(gpu_detector, "encoder_listed", side_effect=lambda _ff, enc: enc in listed),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        return d

    def test_amd_without_av1_encoder_with_the_essentials_build(self):
        d = self._detector(supported={"h264_amf", "hevc_amf"}, listed={"libaom-av1", "h264_amf", "av1_amf"}, nvenc=False)
        self.assertEqual(d.av1_route("amf"), "aom")
        self.assertEqual(d.av1_route("cpu"), "aom")

    def test_home_nvidia_with_the_full_build(self):
        d = self._detector(supported={"av1_nvenc", "h264_nvenc"}, listed={"libsvtav1", "libaom-av1", "av1_nvenc"})
        self.assertEqual(d.av1_route("nvenc"), "gpu")
        self.assertEqual(d.av1_route("cpu"), "svt", "GPU menüsünden CPU seçilince hızlı yazılım kodlayıcısı")

    def test_routes_are_computed_for_every_family(self):
        d = self._detector(supported={"av1_nvenc"}, listed={"libsvtav1"})
        self.assertEqual(d.compute_av1_routes(), {"nvenc": "gpu", "amf": "svt", "cpu": "svt"})


class _Gpu:
    def __init__(self, routes):
        self.av1_routes = routes

    def available_families(self):
        return [f for f in ("nvenc", "amf", "cpu") if f in self.av1_routes]

    def resolve_mode(self, choice):
        return {"auto": self.available_families()[0]}.get(choice, choice)

    def status_text(self):
        return "GPU"

    def is_ok(self):
        return True


class HintTests(unittest.TestCase):
    def _window(self):
        from src.gui.main_window import MainWindow

        cfg = object.__new__(Config)
        cfg.path, cfg._seed_path, cfg.data = "", None, deepcopy(DEFAULTS)
        cfg.save = lambda *a, **k: None
        theme = ThemeManager(_app())
        theme.apply_from_setting("dark")
        patcher = mock.patch.object(MainWindow, "_prepare_ffmpeg", lambda *a, **k: None)
        patcher.start()
        self.addCleanup(patcher.stop)
        w = MainWindow(cfg, theme, mock.MagicMock(), mock.MagicMock())
        self.addCleanup(w.close)
        return w

    def _pick_codec(self, w, codec):
        from src.gui.main_window import CODEC_KEYS

        w.codec.setCurrentIndex([c for c, _ in CODEC_KEYS].index(codec))

    def test_pc_without_av1_encoder_warns_that_av1_is_very_slow(self):
        w = self._window()
        w._on_prepared(w.ffmpeg, _Gpu({"amf": "aom", "cpu": "aom"}))
        hint = w.adv_dialog.codec_hint
        self._pick_codec(w, "h264")
        self.assertEqual(hint.objectName(), "hint_label", "H.264'te uyarı yok, yalnızca açıklama")
        self.assertIn("Önerilen", hint.text())
        self._pick_codec(w, "av1")
        self.assertFalse(hint.isHidden())
        self.assertIn("çok yavaş", hint.text())
        self.assertIn("HEVC", hint.text())
        self.assertEqual(hint.objectName(), "gpu_warn")
        self._pick_codec(w, "hevc")
        self.assertEqual(hint.objectName(), "hint_label")
        self.assertNotIn("çok yavaş", hint.text())

    def test_home_pc_shows_nothing_on_the_gpu_and_a_note_on_cpu(self):
        w = self._window()
        w._on_prepared(w.ffmpeg, _Gpu({"nvenc": "gpu", "cpu": "svt"}))
        self._pick_codec(w, "av1")
        hint = w.adv_dialog.codec_hint
        self.assertNotIn("işlemci", hint.text(), "ekran kartı AV1 kodluyor: yalnızca açıklama")
        self.assertEqual(hint.objectName(), "hint_label")
        w.adv_dialog.set_gpu_choice("cpu")
        self.assertIn("işlemci", hint.text())
        self.assertEqual(hint.objectName(), "hint_label")


class MainScreenTests(HintTests):
    """Kodek seçimi ana ekranda: varsayılan H.264, adlar net (H.265 = HEVC), yalnızca video varken görünür."""

    def test_codec_list_is_on_the_main_screen_with_h264_default(self):
        from src.gui.main_window import CODEC_KEYS

        w = self._window()
        self.assertIs(w.codec.window(), w, "kodek listesi ana pencerede (Gelişmiş ayarlarda değil)")
        self.assertEqual(CODEC_KEYS[w.codec.currentIndex()][0], "h264")
        texts = [w.codec.itemText(i) for i in range(w.codec.count())]
        self.assertEqual(texts, ["H.264 — her yerde açılır", "H.265 (HEVC) — daha küçük", "AV1 — en küçük"])
        for profile in ("balanced", "fast", "quality"):
            self._pick_codec(w, "av1")
            w._apply_profile(profile)
            self.assertEqual(CODEC_KEYS[w.codec.currentIndex()][0], "h264", profile)

    def test_codec_row_follows_the_video_box(self):
        w = self._window()
        w._sync_media_controls(has_img=True, has_vid=False)
        self.assertTrue(w.codec_box.isHidden(), "yalnızca resim varken kodek gereksiz")
        w._sync_media_controls(has_img=False, has_vid=True)
        self.assertFalse(w.codec_box.isHidden())


if __name__ == "__main__":
    unittest.main()
