"""Gercek ffmpeg ile uctan uca testler (PATH'te ffmpeg/ffprobe + libx264 varsa; yoksa atlanir).

Linux/macOS'ta surec grubu, iptal ve zombi/yetim denetimi gercek bir kodlamayla yapilir.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(__file__))
from _support import AUTO_BITRATE, TempDirTestCase  # noqa: E402

from src.core import gpu_detector, video_compressor  # noqa: E402
from src.core.atomic_output import CANCELLED  # noqa: E402
from src.core.gpu_detector import GpuDetector, probe_encoder, reset_probe_cache  # noqa: E402
from src.core.job_manager import JobWorker  # noqa: E402
from src.core.video_compressor import VideoCompressor  # noqa: E402
from src.utils import process  # noqa: E402

FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")


def _has_encoder(name: str) -> bool:
    if not FFMPEG:
        return False
    try:
        out = subprocess.run(
            [FFMPEG, "-nostdin", "-hide_banner", "-encoders"], capture_output=True, text=True, timeout=30,
            stdin=subprocess.DEVNULL,
        ).stdout
    except Exception:  # noqa: BLE001
        return False
    return f" {name} " in out


READY = bool(FFMPEG and FFPROBE and _has_encoder("libx264"))
POSIX = os.name != "nt"


def _make_clip(path: str, seconds: int, size: str, crf: int = 10) -> None:
    subprocess.run(
        [
            FFMPEG, "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", f"testsrc2=size={size}:rate=25:duration={seconds}",
            "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", str(crf), "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", path,
        ],
        check=True, timeout=120, stdin=subprocess.DEVNULL,
    )


def _probe_width(path: str) -> int:
    out = subprocess.run(
        [FFPROBE, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width", "-of", "json", path],
        capture_output=True, text=True, timeout=30, stdin=subprocess.DEVNULL,
    ).stdout
    return int(json.loads(out)["streams"][0]["width"])


def _zombie_children() -> list[int]:
    """Bu surecin toplanmamis (zombi) cocuklari (yalnizca /proc olan sistemlerde)."""
    if not os.path.isdir("/proc/self"):
        return []
    me = os.getpid()
    zombies = []
    for name in os.listdir("/proc"):
        if not name.isdigit():
            continue
        try:
            with open(f"/proc/{name}/stat", "r", encoding="utf-8", errors="replace") as handle:
                raw = handle.read()
        except OSError:
            continue
        fields = raw.rsplit(")", 1)[1].split()
        if fields[0] == "Z" and int(fields[1]) == me:
            zombies.append(int(name))
    return zombies


@unittest.skipUnless(READY, "ffmpeg/ffprobe (libx264) PATH'te yok")
class RealEncodeTests(TempDirTestCase):
    def setUp(self) -> None:
        super().setUp()
        reset_probe_cache()
        self.addCleanup(reset_probe_cache)
        self.vc = VideoCompressor(FFMPEG, FFPROBE)

    def _compress(self, src: str, dst: str, **overrides):
        args = dict(
            gpu_mode="cpu", codec="h264", bitrate=AUTO_BITRATE, crf=30, preset="ultrafast",
            audio_bitrate="96k", max_width=None,
        )
        args.update(overrides)
        return self.vc.compress(src, dst, **args)

    def test_cpu_h264_roundtrip_with_downscale(self) -> None:
        src = str(self.tmp / "giris.mp4")
        _make_clip(src, 2, "640x360")
        dst = str(self.tmp / "cikti" / "giris.mp4")
        ok, msg = self._compress(src, dst, max_width=320)
        self.assertTrue(ok, msg)
        self.assertIn("CPU", msg)
        self.assertEqual(_probe_width(dst), 320)
        self.assertLess(os.path.getsize(dst), os.path.getsize(src))
        self.assertEqual(sorted(os.listdir(os.path.dirname(dst))), ["giris.mp4"])  # .mcpart kalmadi

    def test_odd_custom_width_encodes_with_libx264(self) -> None:
        # Tek genislik (321) libx264'te "width not divisible by 2" ile basarisiz oluyordu.
        src = str(self.tmp / "tek.mp4")
        _make_clip(src, 1, "640x360")
        dst = str(self.tmp / "cikti" / "tek.mp4")
        ok, msg = self._compress(src, dst, max_width=321)
        self.assertTrue(ok, msg)
        self.assertEqual(_probe_width(dst), 320)

    def test_odd_sized_source_encodes_with_libx264(self) -> None:
        # 321x241 kaynak (olceklenmeyen ya da hedeften dar) libx264'te "width not divisible by 2" veriyordu.
        src = str(self.tmp / "tek.mkv")
        subprocess.run(
            [
                FFMPEG, "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
                "-f", "lavfi", "-i", "testsrc2=size=640x480:rate=25:duration=1", "-vf", "scale=321:241",
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "10", "-pix_fmt", "yuv444p", src,
            ],
            check=True, timeout=120, stdin=subprocess.DEVNULL,
        )
        self.assertEqual(_probe_width(src), 321)
        for max_width in (None, 1280):
            with self.subTest(max_width=max_width):
                dst = str(self.tmp / "cikti" / f"tek_{max_width}.mp4")
                ok, msg = self._compress(src, dst, max_width=max_width)
                self.assertTrue(ok, msg)
                self.assertEqual(_probe_width(dst), 320)

    def test_uppercase_extensions_work_end_to_end_through_the_job_worker(self) -> None:
        src_dir = self.tmp / "kaynak"
        src_dir.mkdir()
        clip = str(src_dir / "TATIL.MOV")
        _make_clip(clip, 1, "320x180")
        out = self.tmp / "cikti"
        worker = JobWorker({
            "sources": [str(src_dir)], "output_dir": str(out), "file_type": "all", "scan_subfolders": False,
            "ffmpeg_path": FFMPEG, "ffprobe_path": FFPROBE, "gpu_mode": "cpu", "codec": "h264",
            "bitrate": AUTO_BITRATE, "crf": 30, "preset": "ultrafast", "audio_bitrate": "96k",
            "video_res": None, "image_res": 2400, "image_quality": None, "keep_order": True, "lang": "tr",
        })
        finished: list[dict] = []
        worker.finished_job.connect(finished.append)
        worker._run_inner()
        self.assertEqual((finished[0]["ok"], finished[0]["fail"]), (1, 0))
        self.assertEqual(os.listdir(out), ["TATIL.MOV"])

    def _long_encode(self, seconds: int = 20):
        src = str(self.tmp / "uzun.mp4")
        _make_clip(src, seconds, "1280x720", crf=14)
        return src

    def test_cancel_kills_the_real_encode_and_leaves_no_process_or_zombie(self) -> None:
        src = self._long_encode()
        dst = str(self.tmp / "cikti" / "uzun.mp4")
        procs: list = []
        real_popen = video_compressor.popen_hidden

        def capture(*args, **kwargs):
            proc = real_popen(*args, **kwargs)
            procs.append(proc)
            return proc

        cancel = threading.Event()
        result: dict = {}

        def target() -> None:
            with mock.patch.object(video_compressor, "popen_hidden", capture):
                # Yavas ayarlar: kodlama iptal edilene kadar bitmez.
                result["value"] = self._compress(src, dst, preset="veryslow", crf=18, cancel_event=cancel)

        thread = threading.Thread(target=target, daemon=True)
        thread.start()
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline and not (procs and procs[0].poll() is None):
            time.sleep(0.05)
        self.assertTrue(procs, "ffmpeg hic baslamadi")
        time.sleep(0.8)  # kodlama gercekten surerken iptal et
        self.assertIsNone(procs[0].poll(), "ffmpeg iptalden once bitti; test yavas ayar gerektiriyor")
        pid = procs[0].pid
        started = time.monotonic()
        cancel.set()
        thread.join(30)
        self.assertFalse(thread.is_alive())
        self.assertEqual(result["value"], (False, CANCELLED))
        self.assertLess(time.monotonic() - started, 10)
        self.assertIsNotNone(procs[0].poll())  # lider toplandi
        if POSIX:
            with self.assertRaises(ProcessLookupError):
                os.killpg(pid, 0)  # tum grup gitti
            self.assertEqual(_zombie_children(), [])
        # Cikti klasorunde yarim dosya kalmadi.
        out_dir = os.path.dirname(dst)
        self.assertEqual(os.listdir(out_dir) if os.path.isdir(out_dir) else [], [])

    def test_process_is_started_in_its_own_group_on_posix(self) -> None:
        src = self._long_encode(6)
        dst = str(self.tmp / "cikti" / "grup.mp4")
        procs: list = []
        real_popen = video_compressor.popen_hidden

        def capture(*args, **kwargs):
            proc = real_popen(*args, **kwargs)
            procs.append(proc)
            return proc

        cancel = threading.Event()
        with mock.patch.object(video_compressor, "popen_hidden", capture):
            runner = threading.Thread(
                target=lambda: self._compress(src, dst, preset="veryslow", crf=18, cancel_event=cancel), daemon=True,
            )
            runner.start()
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline and not (procs and procs[0].poll() is None):
                time.sleep(0.05)
            self.assertTrue(procs)
            if POSIX:
                self.assertEqual(os.getpgid(procs[0].pid), procs[0].pid)
                self.assertNotEqual(os.getpgid(procs[0].pid), os.getpgrp())
            cancel.set()
            runner.join(30)
            self.assertFalse(runner.is_alive())


class RealGpuListingTests(unittest.TestCase):
    def test_listing_the_real_machine_never_raises_and_returns_cards(self) -> None:
        cards = gpu_detector.list_gpus()
        self.assertIsInstance(cards, list)
        for card in cards:
            self.assertIsInstance(card, gpu_detector.GpuCard)
            self.assertTrue(card.name)

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux sysfs")
    def test_real_sysfs_drm_tree_is_parsed_without_errors(self) -> None:
        cards = gpu_detector._list_linux()
        self.assertTrue(all(c.vendor in ("nvidia", "amd", "intel", "unknown") for c in cards))
        device = gpu_detector.find_vaapi_device()
        self.assertTrue(device is None or device.startswith("/dev/dri/renderD"))


@unittest.skipUnless(READY, "ffmpeg/ffprobe (libx264) PATH'te yok")
class RealProbeTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_probe_cache()
        self.addCleanup(reset_probe_cache)

    def test_cpu_encoder_probe_passes_and_missing_family_fails(self) -> None:
        self.assertTrue(probe_encoder(FFMPEG, "libx264"))
        self.assertFalse(probe_encoder(FFMPEG, "encoder_that_does_not_exist"))

    def test_detector_always_offers_cpu_and_never_crashes(self) -> None:
        detector = GpuDetector(FFMPEG).detect()
        self.assertIn("cpu", detector.available_families())
        self.assertIn(detector.selected_family, detector.available_families())
        self.assertIsInstance(detector.status_text(), str)
        gpu_detector._GPU_DETECT_CACHE.pop(FFMPEG, None)

    @unittest.skipIf(sys.platform == "darwin", "VideoToolbox macOS'ta gercek")
    def test_videotoolbox_is_never_offered_off_macos(self) -> None:
        detector = GpuDetector(FFMPEG).detect()
        self.assertFalse(detector.videotoolbox)
        gpu_detector._GPU_DETECT_CACHE.pop(FFMPEG, None)


if __name__ == "__main__":
    unittest.main()
