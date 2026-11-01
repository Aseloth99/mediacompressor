"""Madde 5: platforma gore donanim kodlayici secimi ve komut kurulumu.

Windows (nvenc/amf/qsv) degismez; Linux (nvenc/vaapi/qsv, /dev/dri, -vaapi_device,
-vf format=nv12,hwupload); macOS (videotoolbox, -hwaccel, AV1 donanim kodlayici yok).
ffmpeg calistirilmaz: run_hidden / _run taklit edilir.
"""

from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(__file__))
from _support import AUTO_BITRATE, TempDirTestCase  # noqa: E402

from src.core import gpu_detector  # noqa: E402
from src.core.atomic_output import CANCELLED  # noqa: E402
from src.core.gpu_detector import (  # noqa: E402
    ENCODER_MAP, GpuCard, GpuDetector, _list_linux, _probe_command, families_for_platform,
    find_vaapi_device, probe_encoder, reset_probe_cache,
)
from src.core.video_compressor import HEVC_ENCODERS, VideoCompressor, vaapi_qp  # noqa: E402

DEVICE = "/dev/dri/renderD128"
# Boyutu bilinen çift kaynak: tek/bilinmeyen boyuttaki "crop=..." süzgeci eklenmez (komutlar aynı kalır).
EVEN_VIDEO = [{"index": 0, "type": "video", "width": 1920, "height": 1080}]

LISTING = """\
 Encoders:
 V....D libx264              libx264 H.264 (codec h264)
 V....D libx265              libx265 H.265 / HEVC (codec hevc)
 V....D libsvtav1            SVT-AV1 encoder (codec av1)
 V....D h264_nvenc           NVIDIA NVENC H.264 encoder (codec h264)
 V....D hevc_nvenc           NVIDIA NVENC hevc encoder (codec hevc)
 V....D av1_nvenc            NVIDIA NVENC av1 encoder (codec av1)
 V....D h264_amf             AMD AMF H.264 Encoder (codec h264)
 V....D hevc_amf             AMD AMF HEVC encoder (codec hevc)
 V..... h264_qsv             H.264 (Intel Quick Sync Video acceleration) (codec h264)
 V..... hevc_qsv             HEVC (Intel Quick Sync Video acceleration) (codec hevc)
 V....D h264_vaapi           H.264/AVC (VAAPI) (codec h264)
 V....D hevc_vaapi           H.265/HEVC (VAAPI) (codec hevc)
 V....D av1_vaapi            AV1 (VAAPI) (codec av1)
 V....D h264_videotoolbox    VideoToolbox H.264 Encoder (codec h264)
 V....D hevc_videotoolbox    VideoToolbox H.265 Encoder (codec hevc)
"""


class FakeFfmpeg:
    def __init__(self, working, listing=LISTING):
        self.working = set(working)
        self.listing = listing
        self.commands: list[list[str]] = []

    @property
    def probes(self) -> list[str]:
        return [c[c.index("-c:v") + 1] for c in self.commands if "-encoders" not in c]

    def __call__(self, cmd, **kwargs):
        self.commands.append(list(cmd))
        if "-encoders" in cmd:
            return mock.Mock(stdout=self.listing, stderr="", returncode=0)
        encoder = cmd[cmd.index("-c:v") + 1]
        return mock.Mock(stdout="", stderr="", returncode=0 if encoder in self.working else 1)


def after(cmd, flag):
    return cmd[cmd.index(flag) + 1]


class PlatformTableTests(unittest.TestCase):
    def test_families_per_platform(self) -> None:
        self.assertEqual(families_for_platform("win32"), ("nvenc", "amf", "qsv"))
        self.assertEqual(families_for_platform("linux"), ("nvenc", "vaapi", "qsv"))
        self.assertEqual(families_for_platform("darwin"), ("videotoolbox",))
        self.assertEqual(families_for_platform("freebsd13"), ())

    def test_encoder_map_shape(self) -> None:
        self.assertEqual(ENCODER_MAP["vaapi"], {"h264": "h264_vaapi", "hevc": "hevc_vaapi", "av1": "av1_vaapi"})
        self.assertEqual(
            ENCODER_MAP["videotoolbox"], {"h264": "h264_videotoolbox", "hevc": "hevc_videotoolbox"},
        )  # Apple'da AV1 donanim kodlayici yok
        for family, encoders in ENCODER_MAP.items():
            self.assertIn("h264", encoders, family)
            self.assertIn("hevc", encoders, family)
        self.assertIn("hevc_vaapi", HEVC_ENCODERS)
        self.assertIn("hevc_videotoolbox", HEVC_ENCODERS)


class VaapiCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.vc = VideoCompressor("ffmpeg")

    def _cmd(self, codec="h264", dst="out.mp4", bitrate=AUTO_BITRATE, max_width=None, crf=24):
        return self.vc.build_cmd(
            "in.mov", dst, "vaapi", codec, bitrate, crf, "slow", "128k", max_width, vaapi_device=DEVICE,
            streams=EVEN_VIDEO,
        )

    def test_device_precedes_input_and_filter_uploads_frames(self) -> None:
        cmd = self._cmd()
        self.assertEqual(after(cmd, "-vaapi_device"), DEVICE)
        self.assertLess(cmd.index("-vaapi_device"), cmd.index("-i"))
        self.assertEqual(after(cmd, "-vf"), "format=nv12,hwupload")
        self.assertEqual(after(cmd, "-c:v"), "h264_vaapi")
        self.assertEqual(cmd[-1], "out.mp4")
        self.assertNotIn("-hwaccel", cmd)  # yazilim cozme + hwupload (en saglam yol)

    def test_software_scale_runs_before_the_upload(self) -> None:
        vf = after(self._cmd(max_width=1280), "-vf")
        self.assertEqual(vf, "scale='if(gt(iw,1280),1280,iw)':-2,format=nv12,hwupload")

    def test_constant_quality_uses_cqp(self) -> None:
        cmd = self._cmd(crf=26)
        self.assertEqual(after(cmd, "-rc_mode"), "CQP")
        self.assertEqual(after(cmd, "-qp"), "26")
        self.assertNotIn("-b:v", cmd)

    def test_fixed_bitrate_uses_rate_flags(self) -> None:
        cmd = self._cmd(bitrate="2000k")
        self.assertEqual(after(cmd, "-b:v"), "2000k")
        self.assertEqual(after(cmd, "-maxrate"), "2500k")
        self.assertEqual(after(cmd, "-bufsize"), "4000k")
        self.assertNotIn("-rc_mode", cmd)

    def test_hevc_gets_hvc1_in_mp4_family_only(self) -> None:
        for dst in ("a.mp4", "a.mov", "a.m4v"):
            self.assertEqual(after(self._cmd("hevc", dst), "-tag:v"), "hvc1", dst)
        self.assertNotIn("-tag:v", self._cmd("hevc", "a.mkv"))
        self.assertNotIn("-tag:v", self._cmd("h264", "a.mp4"))

    def test_av1_qp_uses_the_0_255_scale_via_global_quality(self) -> None:
        cmd = self._cmd("av1", crf=24)
        self.assertEqual(after(cmd, "-rc_mode"), "CQP")
        self.assertEqual(after(cmd, "-global_quality"), "96")
        self.assertNotIn("-qp", cmd)  # av1_vaapi'nin -qp seceneği yok
        self.assertEqual(vaapi_qp("av1_vaapi", 99), 255)
        self.assertEqual(vaapi_qp("h264_vaapi", 99), 51)
        self.assertEqual(vaapi_qp("hevc_vaapi", -3), 0)

    def test_default_device_comes_from_dev_dri_when_not_given(self) -> None:
        with mock.patch.object(gpu_detector, "find_vaapi_device", return_value=None):
            cmd = self.vc.build_cmd("in.mov", "o.mp4", "vaapi", "h264", AUTO_BITRATE, 24, "slow", "128k", None)
        self.assertEqual(after(cmd, "-vaapi_device"), "/dev/dri/renderD128")


class VideoToolboxCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.vc = VideoCompressor("ffmpeg")

    def _cmd(self, codec="h264", dst="out.mp4", hw_decode=True, max_width=None, bitrate=AUTO_BITRATE):
        return self.vc.build_cmd(
            "in.mov", dst, "videotoolbox", codec, bitrate, 24, "slow", "128k", max_width, hw_decode=hw_decode,
            streams=EVEN_VIDEO,
        )

    def test_hwaccel_precedes_input_and_no_vaapi_flags(self) -> None:
        cmd = self._cmd()
        self.assertEqual(after(cmd, "-hwaccel"), "videotoolbox")
        self.assertLess(cmd.index("-hwaccel"), cmd.index("-i"))
        self.assertNotIn("-vaapi_device", cmd)
        self.assertNotIn("-vf", cmd)
        self.assertEqual(after(cmd, "-c:v"), "h264_videotoolbox")

    def test_software_decode_variant_drops_only_hwaccel(self) -> None:
        with_hw, without = self._cmd(), self._cmd(hw_decode=False)
        self.assertNotIn("-hwaccel", without)
        self.assertEqual([a for a in with_hw if a not in ("-hwaccel", "videotoolbox")], [
            a for a in without if a != "videotoolbox"])

    def test_hevc_tag_and_quality_flags(self) -> None:
        cmd = self._cmd("hevc", "a.mov")
        self.assertEqual(after(cmd, "-c:v"), "hevc_videotoolbox")
        self.assertEqual(after(cmd, "-tag:v"), "hvc1")
        self.assertEqual(after(cmd, "-q:v"), "49")
        self.assertIn("-realtime", cmd)
        self.assertEqual(after(self._cmd(bitrate="2000k"), "-b:v"), "2000k")

    def test_av1_has_no_hardware_path_and_falls_back_to_the_cpu_encoder(self) -> None:
        cmd = self._cmd("av1")
        self.assertEqual(after(cmd, "-c:v"), "libsvtav1")
        self.assertNotIn("-hwaccel", cmd)
        self.assertNotIn("videotoolbox", " ".join(cmd))

    def test_scale_filter_is_plain_software_scale(self) -> None:
        self.assertEqual(after(self._cmd(max_width=1920), "-vf"), "scale='if(gt(iw,1920),1920,iw)':-2")


class WindowsCommandsUnchangedTests(unittest.TestCase):
    def test_no_new_flags_leak_into_windows_families(self) -> None:
        vc = VideoCompressor("ffmpeg")
        for family in ("cpu", "nvenc", "amf", "qsv"):
            for codec in ("h264", "hevc", "av1"):
                cmd = vc.build_cmd("in.mov", "o.mp4", family, codec, AUTO_BITRATE, 24, "slow", "128k", 1280,
                                   streams=EVEN_VIDEO)
                with self.subTest(family=family, codec=codec):
                    for flag in ("-hwaccel", "-vaapi_device", "-rc_mode"):
                        self.assertNotIn(flag, cmd)
                    self.assertEqual(after(cmd, "-vf"), "scale='if(gt(iw,1280),1280,iw)':-2")
                    self.assertEqual(cmd[:6], ["ffmpeg", "-nostdin", "-hide_banner", "-y", "-loglevel", "info"])
                    self.assertEqual(cmd[6], "-i")

    def test_probe_command_for_windows_encoders_is_the_original(self) -> None:
        self.assertEqual(
            _probe_command("ff", "h264_nvenc"),
            [
                "ff", "-nostdin", "-hide_banner", "-loglevel", "error",
                "-f", "lavfi", "-i", "color=black:s=256x256:r=5:d=0.4",
                "-frames:v", "3", "-c:v", "h264_nvenc", "-f", "null", "-",
            ],
        )


class ProbeTests(TempDirTestCase):
    def setUp(self) -> None:
        super().setUp()
        reset_probe_cache()
        self.addCleanup(reset_probe_cache)

    def test_vaapi_probe_command_has_device_and_hwupload(self) -> None:
        cmd = _probe_command("ff", "h264_vaapi", vaapi_device=DEVICE)
        self.assertEqual(after(cmd, "-vaapi_device"), DEVICE)
        self.assertEqual(after(cmd, "-vf"), "format=nv12,hwupload")
        self.assertLess(cmd.index("-vaapi_device"), cmd.index("-i"))
        self.assertLess(cmd.index("-vf"), cmd.index("-c:v"))

    def test_vaapi_probe_without_render_node_never_runs_ffmpeg(self) -> None:
        fake = FakeFfmpeg({"h264_vaapi"})
        with mock.patch.object(gpu_detector, "run_hidden", fake), \
                mock.patch.object(gpu_detector, "find_vaapi_device", return_value=None):
            self.assertFalse(probe_encoder("ff-novaapi", "h264_vaapi"))
        self.assertEqual(fake.commands, [])

    def test_find_vaapi_device_picks_the_first_render_node(self) -> None:
        dri = self.tmp / "dri"
        dri.mkdir()
        for name in ("card0", "renderD129", "renderD128", "controlD64"):
            (dri / name).write_text("")
        self.assertEqual(find_vaapi_device(str(dri)), str(dri / "renderD128"))
        self.assertIsNone(find_vaapi_device(str(self.tmp / "yok")))
        empty = self.tmp / "bos"
        empty.mkdir()
        self.assertIsNone(find_vaapi_device(str(empty)))


class DetectorPlatformTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_probe_cache()
        gpu_detector._GPU_DETECT_CACHE.clear()
        self.addCleanup(reset_probe_cache)
        self.addCleanup(gpu_detector._GPU_DETECT_CACHE.clear)
        patcher = mock.patch.object(gpu_detector, "find_vaapi_device", return_value=DEVICE)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _detect(self, platform, working, cards, ffmpeg="ff-detect"):
        fake = FakeFfmpeg(working)
        with mock.patch.object(gpu_detector, "run_hidden", fake), \
                mock.patch.object(gpu_detector, "list_gpus", return_value=cards):
            detector = GpuDetector(f"{ffmpeg}-{platform}", platform=platform).detect()
        return detector, fake

    def test_macos_probes_only_videotoolbox_and_picks_it(self) -> None:
        cards = [GpuCard("Apple M2", vendor="apple", dedicated=True, score=9000)]
        detector, fake = self._detect("darwin", {"h264_videotoolbox", "hevc_videotoolbox"}, cards)
        self.assertEqual(fake.probes, ["h264_videotoolbox"])
        self.assertTrue(detector.videotoolbox)
        self.assertFalse(detector.nvenc or detector.amf or detector.qsv or detector.vaapi)
        self.assertEqual(detector.selected_family, "videotoolbox")
        self.assertEqual(detector.available_families(), ["videotoolbox", "cpu"])
        self.assertEqual(detector.gpu_menu_values(), ["Otomatik", "VideoToolbox", "CPU (Sadece İşlemci)"])
        with mock.patch.object(gpu_detector, "run_hidden", fake):
            self.assertTrue(detector.supports("videotoolbox", "hevc"))
            self.assertFalse(detector.supports("videotoolbox", "av1"))  # kodlayici yok -> sondaj bile yok
        self.assertNotIn("av1_videotoolbox", fake.probes)

    def test_macos_intel_mac_with_amd_gpu_still_uses_videotoolbox(self) -> None:
        cards = [GpuCard("AMD Radeon Pro 5500M", vendor="amd", dedicated=True, score=5000)]
        detector, _ = self._detect("darwin", {"h264_videotoolbox"}, cards, ffmpeg="ff-intelmac")
        self.assertEqual(detector.selected_family, "videotoolbox")

    def test_linux_probes_nvenc_vaapi_qsv_but_never_amf_or_videotoolbox(self) -> None:
        detector, fake = self._detect("linux", set(), [])
        self.assertEqual(sorted(fake.probes), ["h264_nvenc", "h264_qsv", "h264_vaapi"])
        self.assertEqual(detector.selected_family, "cpu")

    def test_linux_vaapi_probe_gets_device_and_upload_filter(self) -> None:
        _, fake = self._detect("linux", {"h264_vaapi"}, [], ffmpeg="ff-vaapi-cmd")
        probe = next(c for c in fake.commands if "h264_vaapi" in c)
        self.assertEqual(after(probe, "-vaapi_device"), DEVICE)
        self.assertEqual(after(probe, "-vf"), "format=nv12,hwupload")

    def test_linux_vendor_mapping(self) -> None:
        cases = [
            ("nvidia", {"h264_nvenc"}, "nvenc"),
            ("amd", {"h264_vaapi"}, "vaapi"),
            ("amd", {"h264_nvenc"}, "nvenc"),         # AMD kart ama yalniz nvenc calisiyor -> yedek sira
            ("intel", {"h264_qsv", "h264_vaapi"}, "qsv"),
            ("intel", {"h264_vaapi"}, "vaapi"),
            ("unknown", {"h264_vaapi", "h264_qsv"}, "vaapi"),
        ]
        for i, (vendor, working, expected) in enumerate(cases):
            with self.subTest(vendor=vendor, working=sorted(working)):
                reset_probe_cache()
                gpu_detector._GPU_DETECT_CACHE.clear()
                cards = [GpuCard(f"{vendor} gpu", vendor=vendor, dedicated=True, score=100)]
                detector, _ = self._detect("linux", working, cards, ffmpeg=f"ff-map{i}")
                self.assertEqual(detector.selected_family, expected)

    def test_linux_menu_and_resolve_mode_know_vaapi(self) -> None:
        detector, _ = self._detect("linux", {"h264_vaapi"}, [], ffmpeg="ff-menu")
        self.assertIn("VAAPI", detector.gpu_menu_values())
        self.assertEqual(detector.resolve_mode("VAAPI"), "vaapi")
        self.assertEqual(detector.resolve_mode("vaapi"), "vaapi")
        self.assertEqual(detector.resolve_mode("Otomatik"), "vaapi")
        self.assertIn("VAAPI", detector.status_text())

    def test_windows_probes_exactly_the_original_families(self) -> None:
        detector, fake = self._detect("win32", {"h264_nvenc"}, [], ffmpeg="ff-win")
        self.assertEqual(sorted(fake.probes), ["h264_amf", "h264_nvenc", "h264_qsv"])
        self.assertEqual(detector.selected_family, "nvenc")
        self.assertFalse(detector.vaapi or detector.videotoolbox)
        self.assertNotIn("VAAPI", detector.gpu_menu_values())

    def test_cache_copies_vaapi_flag(self) -> None:
        first, _ = self._detect("linux", {"h264_vaapi"}, [], ffmpeg="ff-cache")
        self.assertTrue(first.vaapi)
        with mock.patch.object(gpu_detector, "run_hidden", side_effect=AssertionError("onbellek kullanilmaliydi")):
            again = GpuDetector("ff-cache-linux", platform="linux").detect()
        self.assertTrue(again.vaapi)
        self.assertEqual(again.selected_family, "vaapi")


class ListLinuxGpusTests(TempDirTestCase):
    def _gpu(self, drm, name, vendor, extra=None, slot=None):
        card = drm / name / "device"
        card.mkdir(parents=True)
        (card / "vendor").write_text(vendor + "\n")
        for key, value in (extra or {}).items():
            (card / key).write_text(value)
        return card

    LSPCI = (
        '00:02.0 "VGA compatible controller" "Intel Corporation" "UHD Graphics 630 (Desktop)" -p00 "Dell" "x"\n'
        '01:00.0 "VGA compatible controller" "NVIDIA Corporation" "GA104 [GeForce RTX 3070]" -ra1 "ASUS" "y"\n'
        '03:00.0 "Display controller" "Advanced Micro Devices, Inc. [AMD/ATI]" "Navi 31 [Radeon RX 7900 XT/XTX]" "z" "w"\n'
        '00:1f.3 "Audio device" "Intel Corporation" "Cannon Lake PCH cAVS" "a" "b"\n'
    )

    def test_cards_are_read_from_sysfs_with_names_from_lspci(self) -> None:
        drm = self.tmp / "drm"
        self._gpu(drm, "card0", "0x8086")
        self._gpu(drm, "card1", "0x10de")
        self._gpu(drm, "card2", "0x1002", {"mem_info_vram_total": str(20 * 1024 ** 3)})
        (drm / "card0-HDMI-A-1").mkdir()  # baglanti noktasi, kart degil
        runner = mock.Mock(return_value=mock.Mock(stdout=self.LSPCI))
        # Gercek sysfs'te "device" PCI yuvasini gosteren sembolik baglantidir; burada klasor oldugundan
        # yuva eslesmesi olmaz -> adlar bilinen ureticiden turetilir.
        cards = _list_linux(str(drm), runner)
        self.assertEqual([c.vendor for c in cards], ["intel", "nvidia", "amd"])
        self.assertEqual(cards[2].vram_mb, 20 * 1024)
        self.assertTrue(cards[1].dedicated and cards[2].dedicated)
        self.assertFalse(cards[0].dedicated)

    @unittest.skipIf(os.name == "nt", "sembolik baglanti gerektirir")
    def test_names_match_the_pci_slot_through_the_device_symlink(self) -> None:
        pci = self.tmp / "devices" / "pci0000:00" / "0000:01:00.0"
        pci.mkdir(parents=True)
        (pci / "vendor").write_text("0x10de\n")
        drm = self.tmp / "drm"
        (drm / "card0").mkdir(parents=True)
        os.symlink(pci, drm / "card0" / "device")
        runner = mock.Mock(return_value=mock.Mock(stdout=self.LSPCI))
        cards = _list_linux(str(drm), runner)
        self.assertEqual([c.name for c in cards], ["NVIDIA GeForce RTX 3070"])

    def test_virtual_devices_without_pci_vendor_are_skipped_and_missing_tree_is_empty(self) -> None:
        drm = self.tmp / "drm"
        (drm / "card0" / "device").mkdir(parents=True)  # vkms: vendor dosyasi yok
        self.assertEqual(_list_linux(str(drm), mock.Mock()), [])
        self.assertEqual(_list_linux(str(self.tmp / "yok"), mock.Mock()), [])

    def test_missing_lspci_falls_back_to_generic_names(self) -> None:
        drm = self.tmp / "drm"
        self._gpu(drm, "card0", "0x1002")
        cards = _list_linux(str(drm), mock.Mock(side_effect=FileNotFoundError("lspci")))
        self.assertEqual(cards[0].name, "AMD GPU")
        self.assertEqual(cards[0].vendor, "amd")

    def test_clean_pci_names(self) -> None:
        clean = gpu_detector._clean_pci_name
        self.assertEqual(clean("NVIDIA Corporation", "GA104 [GeForce RTX 3070]"), "NVIDIA GeForce RTX 3070")
        self.assertEqual(
            clean("Advanced Micro Devices, Inc. [AMD/ATI]", "Navi 31 [Radeon RX 7900 XT/XTX]"),
            "AMD Radeon RX 7900 XT/XTX",
        )
        self.assertEqual(clean("Intel Corporation", "UHD Graphics 630"), "Intel UHD Graphics 630")

    def test_list_gpus_dispatches_by_platform(self) -> None:
        with mock.patch.object(gpu_detector, "_list_linux", return_value=["L"]) as lin, \
                mock.patch.object(gpu_detector, "_merge_nvidia_smi") as smi, \
                mock.patch.object(gpu_detector, "_list_mac", return_value=["M"]) as mac, \
                mock.patch.object(gpu_detector, "_list_windows", return_value=["W"]) as win:
            self.assertEqual(gpu_detector.list_gpus("linux"), ["L"])
            smi.assert_called_once()
            self.assertEqual(gpu_detector.list_gpus("darwin"), ["M"])
            self.assertEqual(gpu_detector.list_gpus("win32"), ["W"])
            self.assertEqual(gpu_detector.list_gpus("freebsd13"), [])
        lin.assert_called_once()
        mac.assert_called_once()
        win.assert_called_once()


class CompressRoutingPlatformTests(TempDirTestCase):
    def setUp(self) -> None:
        super().setUp()
        reset_probe_cache()
        self.addCleanup(reset_probe_cache)
        self.src = self.tmp / "in" / "film.mp4"
        self.src.parent.mkdir()
        self.src.write_bytes(b"s" * 5000)
        self.vc = VideoCompressor("ff-route-platform")
        for target in (
            mock.patch.object(self.vc, "duration", return_value=10.0),
            mock.patch.object(gpu_detector, "find_vaapi_device", return_value=DEVICE),
            mock.patch("src.core.video_compressor.find_vaapi_device", return_value=DEVICE),
        ):
            target.start()
            self.addCleanup(target.stop)
        self.commands: list[list[str]] = []

    def _compress(self, family, codec, outcomes, working):
        fake = FakeFfmpeg(working)
        results = list(outcomes)

        def fake_run(cmd, *args):
            self.commands.append(list(cmd))
            outcome = results.pop(0)
            if outcome == "ok":
                with open(cmd[-1], "wb") as handle:
                    handle.write(b"v" * 100)
            return outcome

        dst = str(self.tmp / "out" / "film.mp4")
        with mock.patch.object(gpu_detector, "run_hidden", fake), \
                mock.patch.object(self.vc, "_run", side_effect=fake_run):
            return self.vc.compress(
                str(self.src), dst, gpu_mode=family, codec=codec, bitrate=AUTO_BITRATE, crf=24,
                preset="slow", audio_bitrate="128k", max_width=None,
            )

    @staticmethod
    def _encoder(cmd):
        return after(cmd, "-c:v")

    def test_vaapi_is_used_with_device_and_upload_when_supported(self) -> None:
        ok, msg = self._compress("vaapi", "hevc", ["ok"], {"h264_vaapi", "hevc_vaapi"})
        self.assertTrue(ok)
        self.assertIn("VAAPI", msg)
        cmd = self.commands[0]
        self.assertEqual(self._encoder(cmd), "hevc_vaapi")
        self.assertEqual(after(cmd, "-vaapi_device"), DEVICE)
        # Akışlar okunamadı (sahte ffmpeg): boyut bilinmediği için önce çifte kırpılır, sonra yüklenir.
        self.assertEqual(after(cmd, "-vf"), "crop=trunc(iw/2)*2:trunc(ih/2)*2,format=nv12,hwupload")
        self.assertEqual(after(cmd, "-tag:v"), "hvc1")

    def test_vaapi_av1_unsupported_goes_straight_to_cpu(self) -> None:
        ok, msg = self._compress("vaapi", "av1", ["ok"], {"h264_vaapi"})
        self.assertTrue(ok)
        self.assertEqual(len(self.commands), 1)
        self.assertEqual(self._encoder(self.commands[0]), "libsvtav1")
        self.assertNotIn("-vaapi_device", self.commands[0])

    def test_vaapi_failure_retries_on_cpu(self) -> None:
        ok, msg = self._compress("vaapi", "h264", ["Error initialising hwupload", "ok"], {"h264_vaapi"})
        self.assertTrue(ok)
        self.assertEqual([self._encoder(c) for c in self.commands], ["h264_vaapi", "libx264"])
        self.assertIn("CPU", msg)

    def test_videotoolbox_hwaccel_failure_retries_same_encoder_in_software_decode(self) -> None:
        ok, msg = self._compress("videotoolbox", "h264", ["hwaccel hatasi", "ok"], {"h264_videotoolbox"})
        self.assertTrue(ok)
        first, second = self.commands
        self.assertEqual([self._encoder(c) for c in self.commands], ["h264_videotoolbox"] * 2)
        self.assertIn("-hwaccel", first)
        self.assertNotIn("-hwaccel", second)
        self.assertIn("VIDEOTOOLBOX", msg)

    def test_videotoolbox_falls_back_to_cpu_only_after_both_attempts_fail(self) -> None:
        ok, msg = self._compress("videotoolbox", "h264", ["e1", "e2", "ok"], {"h264_videotoolbox"})
        self.assertTrue(ok)
        self.assertEqual(
            [self._encoder(c) for c in self.commands], ["h264_videotoolbox", "h264_videotoolbox", "libx264"],
        )
        self.assertIn("-hwaccel", self.commands[0])
        self.assertNotIn("-hwaccel", self.commands[1])
        self.assertIn("CPU", msg)

    def test_videotoolbox_cancel_does_not_trigger_a_retry(self) -> None:
        ok, msg = self._compress("videotoolbox", "h264", [CANCELLED], {"h264_videotoolbox"})
        self.assertEqual((ok, msg), (False, CANCELLED))
        self.assertEqual(len(self.commands), 1)

    def test_videotoolbox_av1_uses_cpu_immediately(self) -> None:
        ok, _ = self._compress("videotoolbox", "av1", ["ok"], {"h264_videotoolbox"})
        self.assertTrue(ok)
        self.assertEqual(self._encoder(self.commands[0]), "libsvtav1")
        self.assertNotIn("-hwaccel", self.commands[0])


if __name__ == "__main__":
    unittest.main()
