"""Madde 4: GPU (aile x kodek) sondaji + onbellek, hvc1 etiketi, AV1 preset eslemesi.

ffmpeg hic calistirilmaz: komut listeleri uretilir, run_hidden/_run taklit edilir.
"""

from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(__file__))
from _support import AUTO_BITRATE, TempDirTestCase  # noqa: E402

from src.core import gpu_detector  # noqa: E402
from src.core.gpu_detector import GpuDetector, encoder_supported, reset_probe_cache  # noqa: E402
from src.core.video_compressor import (  # noqa: E402
    SVT_AV1_PRESETS, VideoCompressor, cpu_preset_args,
)

LISTING = """\
 Encoders:
 V....D libx264              libx264 H.264 (codec h264)
 V....D libx265              libx265 H.265 / HEVC (codec hevc)
 V....D libsvtav1            SVT-AV1(Scalable Video Technology for AV1) encoder (codec av1)
 V....D libaom-av1           libaom AV1 (codec av1)
 V....D h264_nvenc           NVIDIA NVENC H.264 encoder (codec h264)
 V....D hevc_nvenc           NVIDIA NVENC hevc encoder (codec hevc)
 V....D av1_nvenc            NVIDIA NVENC av1 encoder (codec av1)
 V....D h264_qsv             H.264 / AVC / MPEG-4 AVC (Intel Quick Sync Video acceleration)
"""


class FakeFfmpeg:
    """gpu_detector.run_hidden yerine: -encoders listesi ve kodlayici sondaji."""

    def __init__(self, working, listing=LISTING):
        self.working = set(working)
        self.listing = listing
        self.probes: list[str] = []
        self.list_calls = 0

    def __call__(self, cmd, **kwargs):
        if "-encoders" in cmd:
            self.list_calls += 1
            return mock.Mock(stdout=self.listing, stderr="", returncode=0)
        encoder = cmd[cmd.index("-c:v") + 1]
        self.probes.append(encoder)
        return mock.Mock(stdout="", stderr="", returncode=0 if encoder in self.working else 1)


class CmdBuildTests(unittest.TestCase):
    def setUp(self) -> None:
        self.vc = VideoCompressor("ffmpeg")

    def _cmd(self, family, codec, dst="out.mp4", bitrate=AUTO_BITRATE, preset="slow"):
        return self.vc.build_cmd("in.mov", dst, family, codec, bitrate, 24, preset, "128k", None)

    @staticmethod
    def _after(cmd, flag):
        return cmd[cmd.index(flag) + 1]

    def test_hvc1_tag_for_every_hevc_encoder_in_mp4_family(self) -> None:
        for family in ("cpu", "nvenc", "amf", "qsv", "videotoolbox", "vaapi"):
            for dst in ("a.mp4", "a.mov", "a.m4v"):
                with self.subTest(family=family, dst=dst):
                    cmd = self._cmd(family, "hevc", dst)
                    self.assertEqual(self._after(cmd, "-tag:v"), "hvc1")

    def test_no_hvc1_for_h264_av1_or_non_mp4_containers(self) -> None:
        for family in ("cpu", "nvenc"):
            self.assertNotIn("-tag:v", self._cmd(family, "h264"))
            self.assertNotIn("-tag:v", self._cmd(family, "av1"))
        self.assertNotIn("-tag:v", self._cmd("nvenc", "hevc", "a.mkv"))
        self.assertNotIn("-tag:v", self._cmd("cpu", "hevc", "a.avi"))

    def test_movflags_only_for_mp4_family(self) -> None:
        self.assertIn("+faststart", self._cmd("cpu", "h264", "a.mp4"))
        self.assertNotIn("-movflags", self._cmd("cpu", "h264", "a.mkv"))
        self.assertNotIn("-movflags", self._cmd("cpu", "h264", "a.avi"))

    def test_temp_name_keeps_mp4_family_behaviour(self) -> None:
        cmd = self._cmd("nvenc", "hevc", "x.mcpart.mp4")
        self.assertIn("hvc1", cmd)
        self.assertIn("+faststart", cmd)

    def test_svtav1_gets_numeric_preset_never_a_name(self) -> None:
        for name in ("superfast", "veryfast", "faster", "fast", "medium", "slow", "slower"):
            for bitrate in (AUTO_BITRATE, "2000k"):
                with self.subTest(preset=name, bitrate=bitrate):
                    cmd = self._cmd("cpu", "av1", preset=name, bitrate=bitrate)
                    self.assertEqual(self._after(cmd, "-c:v"), "libsvtav1")
                    value = self._after(cmd, "-preset")
                    self.assertTrue(value.isdigit(), value)
                    self.assertTrue(0 <= int(value) <= 13)
                    self.assertEqual(int(value), SVT_AV1_PRESETS[name])
                    self.assertNotIn(name, cmd)

    def test_svt_presets_are_monotonic_slower_means_lower_number(self) -> None:
        order = ["superfast", "veryfast", "faster", "fast", "medium", "slow", "slower"]
        numbers = [SVT_AV1_PRESETS[n] for n in order]
        self.assertEqual(numbers, sorted(numbers, reverse=True))

    def test_x264_x265_keep_named_presets(self) -> None:
        self.assertEqual(self._after(self._cmd("cpu", "h264"), "-preset"), "slow")
        self.assertEqual(self._after(self._cmd("cpu", "hevc"), "-preset"), "slow")
        self.assertEqual(cpu_preset_args("libx264", "faster"), ["-preset", "faster"])

    def test_libaom_uses_cpu_used_and_zero_bitrate_for_crf(self) -> None:
        self.vc._cpu_av1 = "libaom-av1"
        cmd = self._cmd("cpu", "av1", preset="slow")
        self.assertEqual(self._after(cmd, "-c:v"), "libaom-av1")
        # "slow" eskiden cpu-used 3'tü: 11 sn'lik video 552 sn sürüyordu; 6 aynı boyuta yakın, ~5 kat hızlı
        self.assertEqual(self._after(cmd, "-cpu-used"), "6")
        self.assertEqual(self._after(self._cmd("cpu", "av1", preset="slower"), "-cpu-used"), "5")
        self.assertEqual(self._after(cmd, "-b:v"), "0")
        self.assertNotIn("-preset", cmd)

    def test_numeric_and_unknown_presets_are_clamped(self) -> None:
        self.assertEqual(cpu_preset_args("libsvtav1", "99"), ["-preset", "12"])
        self.assertEqual(cpu_preset_args("libsvtav1", "garip"), ["-preset", "6"])


class ProbeTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_probe_cache()
        self.addCleanup(reset_probe_cache)

    def _patch(self, fake):
        patcher = mock.patch.object(gpu_detector, "run_hidden", fake)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_each_encoder_is_probed_once_and_cached(self) -> None:
        fake = FakeFfmpeg({"h264_nvenc", "hevc_nvenc"})
        self._patch(fake)
        for _ in range(3):
            self.assertTrue(encoder_supported("ff-a", "hevc_nvenc"))
            self.assertFalse(encoder_supported("ff-a", "av1_nvenc"))
        self.assertEqual(sorted(fake.probes), ["av1_nvenc", "hevc_nvenc"])
        self.assertEqual(fake.list_calls, 1)

    def test_not_listed_encoder_is_never_probed(self) -> None:
        fake = FakeFfmpeg({"hevc_amf"})
        self._patch(fake)
        self.assertFalse(encoder_supported("ff-b", "hevc_amf"))
        self.assertEqual(fake.probes, [])

    def test_name_match_is_whole_word(self) -> None:
        fake = FakeFfmpeg({"hevc_nvenc"}, listing=" V....D h264_nvenc  NVIDIA\n")
        self._patch(fake)
        self.assertFalse(encoder_supported("ff-c", "hevc_nvenc"))

    def test_cache_is_per_ffmpeg_path(self) -> None:
        fake = FakeFfmpeg({"h264_nvenc"})
        self._patch(fake)
        self.assertTrue(encoder_supported("ff-1", "h264_nvenc"))
        self.assertTrue(encoder_supported("ff-2", "h264_nvenc"))
        self.assertEqual(fake.probes, ["h264_nvenc", "h264_nvenc"])

    def test_detector_probes_only_h264_at_startup_and_supports_is_lazy(self) -> None:
        fake = FakeFfmpeg({"h264_nvenc", "hevc_nvenc"})
        self._patch(fake)
        with mock.patch.object(gpu_detector, "list_gpus", return_value=[]):
            detector = GpuDetector("ff-detect-1").detect()
        self.assertTrue(detector.nvenc)
        self.assertTrue(fake.probes)
        self.assertTrue(all(name.startswith("h264_") for name in fake.probes), fake.probes)  # hevc/av1 acilista denenmez
        self.assertTrue(detector.supports("nvenc", "hevc"))
        self.assertFalse(detector.supports("nvenc", "av1"))
        self.assertTrue(detector.supports("cpu", "av1"))
        self.assertIn("hevc_nvenc", fake.probes)
        self.assertIn("av1_nvenc", fake.probes)


class ResolveModeTests(unittest.TestCase):
    """Menu metninden aile cozumleme: acik GPU secimi sessizce CPU'ya dusmemeli."""

    def _detector(self, **flags):
        detector = GpuDetector("ff-menu")
        for name, value in flags.items():
            setattr(detector, name, value)
        detector.selected_family = "nvenc" if flags.get("nvenc") else "cpu"
        return detector

    def test_real_menu_entries_resolve_to_their_family(self) -> None:
        detector = self._detector(nvenc=True, amf=True, qsv=True, videotoolbox=True)
        for text, family in (
            ("NVIDIA NVENC", "nvenc"), ("AMD AMF", "amf"), ("Intel QSV", "qsv"),
            ("VideoToolbox", "videotoolbox"),
        ):
            with self.subTest(text=text):
                self.assertEqual(detector.resolve_mode(text), family)

    def test_gpu_menu_values_round_trip(self) -> None:
        detector = self._detector(nvenc=True, qsv=True)
        modes = {text: detector.resolve_mode(text) for text in detector.gpu_menu_values()}
        self.assertEqual(sorted(set(modes.values())), ["cpu", "nvenc", "qsv"])
        self.assertEqual(modes["Otomatik"], "nvenc")
        self.assertEqual(modes[detector.gpu_menu_values()[-1]], "cpu")

    def test_cpu_and_auto_texts_in_both_languages(self) -> None:
        detector = self._detector(nvenc=True)
        for text in ("CPU (Sadece İşlemci)", "CPU (Processor only)", "cpu"):
            self.assertEqual(detector.resolve_mode(text), "cpu", text)
        for text in ("Otomatik", "Auto", "auto", "", None):
            self.assertEqual(detector.resolve_mode(text), "nvenc", text)

    def test_unavailable_explicit_choice_falls_back_to_selected_family(self) -> None:
        detector = self._detector(nvenc=True)
        self.assertEqual(detector.resolve_mode("Intel QSV"), "nvenc")
        self.assertEqual(self._detector().resolve_mode("NVIDIA NVENC"), "cpu")


class CompressRoutingTests(TempDirTestCase):
    def setUp(self) -> None:
        super().setUp()
        reset_probe_cache()
        self.addCleanup(reset_probe_cache)
        self.src = self.tmp / "in" / "film.mp4"
        self.src.parent.mkdir()
        self.src.write_bytes(b"s" * 5000)
        self.vc = VideoCompressor("ff-route")
        patcher = mock.patch.object(self.vc, "duration", return_value=10.0)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.commands: list[list[str]] = []

    def _fake_ffmpeg(self, gpu_ok=True):
        fake = FakeFfmpeg({"h264_nvenc", "hevc_nvenc"})
        patcher = mock.patch.object(gpu_detector, "run_hidden", fake)
        patcher.start()
        self.addCleanup(patcher.stop)
        return fake

    def _compress(self, n, codec, gpu_mode="nvenc", gpu_succeeds=True, **kw):
        outcomes = []
        for i in range(n):
            dst = str(self.tmp / "out" / f"film{i}.mp4")

            def fake_run(cmd, *args, _outcomes=outcomes):
                self.commands.append(list(cmd))
                with open(cmd[-1], "wb") as handle:
                    handle.write(b"v" * 100)
                encoder = cmd[cmd.index("-c:v") + 1]
                is_gpu = encoder.endswith(("_nvenc", "_qsv", "_amf"))
                ok = gpu_succeeds if is_gpu else True
                return "ok" if ok else "Error while opening encoder"

            with mock.patch.object(self.vc, "_run", side_effect=fake_run):
                outcomes.append(self.vc.compress(
                    str(self.src), dst, gpu_mode=gpu_mode, codec=codec, bitrate=AUTO_BITRATE,
                    crf=24, preset="slow", audio_bitrate="128k", max_width=None, **kw,
                ))
        return outcomes

    @staticmethod
    def _encoder(cmd):
        return cmd[cmd.index("-c:v") + 1]

    def test_unsupported_combination_goes_straight_to_cpu_without_retry_noise(self) -> None:
        fake = self._fake_ffmpeg()
        outcomes = self._compress(3, "av1")  # av1_nvenc sondajdan gecemiyor
        self.assertTrue(all(ok for ok, _ in outcomes))
        self.assertEqual(len(self.commands), 3)  # her dosyada yalnizca BIR calistirma (GPU denemesi yok)
        self.assertTrue(all(self._encoder(c) == "libsvtav1" for c in self.commands))
        self.assertEqual(fake.probes.count("av1_nvenc"), 1)  # sondaj onbellekli
        self.assertTrue(all("CPU" in msg for _, msg in outcomes))

    def test_supported_hevc_uses_gpu_encoder_with_hvc1(self) -> None:
        self._fake_ffmpeg()
        outcomes = self._compress(1, "hevc")
        self.assertTrue(outcomes[0][0])
        cmd = self.commands[0]
        self.assertEqual(self._encoder(cmd), "hevc_nvenc")
        self.assertIn("hvc1", cmd)
        self.assertIn("NVENC", outcomes[0][1])

    def test_repeated_gpu_failures_disable_gpu_for_rest_of_session(self) -> None:
        self._fake_ffmpeg()
        outcomes = self._compress(5, "h264", gpu_succeeds=False)
        self.assertTrue(all(ok for ok, _ in outcomes))
        encoders = [self._encoder(c) for c in self.commands]
        # Ilk 2 dosya: GPU dene + CPU'ya dus (4 calistirma). Sonrakiler dogrudan CPU (3 calistirma).
        self.assertEqual(encoders, ["h264_nvenc", "libx264"] * 2 + ["libx264"] * 3)

    def test_gpu_success_resets_failure_counter(self) -> None:
        self._fake_ffmpeg()
        for succeeds in (False, True, False, True):
            self._compress(1, "h264", gpu_succeeds=succeeds)
        gpu_runs = [c for c in self.commands if self._encoder(c) == "h264_nvenc"]
        self.assertEqual(len(gpu_runs), 4)  # ardisik 2 hata olmadigi icin GPU hic kapanmadi

    def test_cpu_av1_encoder_falls_back_to_libaom_when_svt_missing(self) -> None:
        listing = " V....D libaom-av1           libaom AV1 (codec av1)\n"
        fake = FakeFfmpeg(set(), listing=listing)
        with mock.patch.object(gpu_detector, "run_hidden", fake):
            outcomes = self._compress(1, "av1", gpu_mode="cpu")
        self.assertTrue(outcomes[0][0])
        cmd = self.commands[0]
        self.assertEqual(self._encoder(cmd), "libaom-av1")
        self.assertIn("-cpu-used", cmd)


if __name__ == "__main__":
    unittest.main()
