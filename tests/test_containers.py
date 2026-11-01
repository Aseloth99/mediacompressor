"""Kapsayıcı (uzantı) x kodek: uzantı korunur, ancak taşıyamıyorsa .mp4 yazılır.

Gerçek ffmpeg ile denendi: .mov + AV1 her denemede "Conversion failed" veriyordu (iPhone videoları .mov),
.m4v + HEVC/AV1 de; .avi + HEVC ise "başarılı" diye "rawvideo" olarak okunan, açılmayan bir dosya üretiyordu.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(__file__))
from _support import AUTO_BITRATE, TempDirTestCase  # noqa: E402

from src.core.job_manager import JobWorker  # noqa: E402
from src.core.video_compressor import QUALITY_MAP, VideoCompressor, encoder_quality, video_output_path  # noqa: E402

FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")


class OutputPathTests(unittest.TestCase):
    def test_extension_is_kept_when_the_container_can_hold_the_codec(self):
        for ext in (".mp4", ".mkv", ".m4v"):
            for codec in ("h264", "hevc", "av1"):
                self.assertEqual(video_output_path(f"d/a{ext}", codec), f"d/a{ext}", (ext, codec))
        self.assertEqual(video_output_path("d/a.mov", "h264"), "d/a.mov")
        self.assertEqual(video_output_path("d/a.MOV", "hevc"), "d/a.MOV")

    def test_incompatible_pairs_become_mp4(self):
        self.assertEqual(video_output_path("d/IMG_1.MOV", "av1"), "d/IMG_1.mp4")
        for codec in ("h264", "hevc", "av1"):
            self.assertEqual(video_output_path("d/eski.avi", codec), "d/eski.mp4", codec)

    def test_m4v_is_written_with_the_mp4_muxer(self):
        vc = VideoCompressor("ffmpeg")
        cmd = vc.build_cmd("in.mov", "out.m4v", "cpu", "hevc", AUTO_BITRATE, 24, "slow", "128k", None)
        self.assertEqual(cmd[-3:], ["-f", "mp4", "out.m4v"])
        self.assertNotIn("-f", vc.build_cmd("in.mov", "out.mp4", "cpu", "hevc", AUTO_BITRATE, 24, "slow", "128k", None))


class QualityMapTests(unittest.TestCase):
    """Arayüzdeki kalite (libx264 CRF ölçeği) her kodlayıcıda aynı görüntü kalitesini versin (VMAF ile ölçüldü)."""

    def test_av1_no_longer_gets_a_near_lossless_value(self):
        # eskiden av1_nvenc'e "-qp 24" gidiyordu (0-255 ölçek): çıktı kaynaktan 3.4 kat büyüktü
        self.assertEqual(encoder_quality("av1_nvenc", 24), 106)
        self.assertEqual(encoder_quality("libsvtav1", 24), 39)
        self.assertEqual(encoder_quality("libsvtav1", 32), 63, "SVT-AV1 ölçeğinin sonu")
        self.assertEqual(encoder_quality("libx264", 24), 24, "referans ölçek değişmez")
        self.assertEqual(encoder_quality("h264_qsv", 24), 24, "ölçülemeyen kodlayıcıda eski davranış")

    def test_every_map_rises_with_crf_and_stays_in_range(self):
        for enc, (_values, top) in QUALITY_MAP.items():
            seq = [encoder_quality(enc, c) for c in range(10, 41)]
            self.assertEqual(seq, sorted(seq), enc)
            self.assertTrue(all(0 <= q <= top for q in seq), enc)

    def test_commands_use_the_mapped_values(self):
        vc = VideoCompressor("ffmpeg")

        def cmd(family, codec):
            return vc.build_cmd("i.mp4", "o.mp4", family, codec, AUTO_BITRATE, 24, "slow", "128k", None)

        def after(c, flag):
            return c[c.index(flag) + 1]

        self.assertEqual(after(cmd("nvenc", "av1"), "-qp"), "106")
        self.assertEqual(after(cmd("nvenc", "h264"), "-qp"), "27")
        self.assertEqual(after(cmd("amf", "hevc"), "-qp_p"), "28")
        self.assertEqual(after(cmd("cpu", "av1"), "-crf"), "39")
        self.assertEqual(after(cmd("cpu", "hevc"), "-crf"), "28")
        self.assertEqual(after(cmd("cpu", "h264"), "-crf"), "24")
        self.assertNotIn("-qp", vc.build_cmd("i.mp4", "o.mp4", "nvenc", "av1", "2000k", 24, "slow", "128k", None),
                         "sabit bitrate modunda kalite değeri kullanılmaz")


class AmdAndLibaomTests(unittest.TestCase):
    """Okuldaki AMD bilgisayar: H.264'te B-kareleri (kart destekliyorsa), AV1'de libaom (essentials FFmpeg)."""

    def _cmd(self, **kw):
        return VideoCompressor("ffmpeg").build_cmd("i.mp4", "o.mp4", "amf", "h264", kw.pop("bitrate", AUTO_BITRATE),
                                                   24, "slow", "128k", None, **kw)

    def test_amf_h264_uses_b_frames_only_when_the_card_has_them(self):
        def after(c, flag):
            return c[c.index(flag) + 1]

        with_bf = self._cmd(amf_bframes=True)
        self.assertEqual((after(with_bf, "-qp_p"), after(with_bf, "-qp_b"), after(with_bf, "-bf")), ("26", "28", "3"))
        without = self._cmd(amf_bframes=False)
        self.assertEqual(after(without, "-qp_p"), "27")
        self.assertNotIn("-bf", without)
        self.assertEqual(after(self._cmd(amf_bframes=True, bitrate="2000k"), "-bf"), "3")
        hevc = VideoCompressor("ffmpeg").build_cmd("i.mp4", "o.mp4", "amf", "hevc", AUTO_BITRATE, 24, "slow", "128k",
                                                   None, amf_bframes=True)
        self.assertNotIn("-bf", hevc, "hevc_amf B-karesi desteklemiyor")

    def test_b_frame_probe_reads_the_frame_types(self):
        from src.core import gpu_detector

        def fake(outputs):
            calls = []

            def run(cmd, **_kw):
                calls.append(cmd)
                if "-vf" in cmd:  # çözme: kare türleri
                    return mock.Mock(returncode=0, stdout="", stderr=outputs["dec"])
                Path(cmd[-1]).write_bytes(b"x")
                return mock.Mock(returncode=outputs["enc"], stdout="", stderr="")
            return run

        cases = (({"enc": 0, "dec": "n:0 type:I n:1 type:B"}, True), ({"enc": 0, "dec": "type:I type:P"}, False),
                 ({"enc": 1, "dec": "type:B"}, False))
        for outputs, expected in cases:
            gpu_detector.reset_probe_cache()
            with mock.patch.object(gpu_detector, "run_hidden", side_effect=fake(outputs)):
                self.assertEqual(gpu_detector.amf_h264_bframes("ff"), expected, outputs)
        gpu_detector.reset_probe_cache()

    def test_libaom_is_calibrated_and_fast_enough(self):
        self.assertEqual(encoder_quality("libaom-av1", 24), 34)
        cmd = VideoCompressor("ffmpeg").build_cmd("i.mp4", "o.mp4", "cpu", "av1", AUTO_BITRATE, 24, "slow", "128k", None)
        self.assertIn("-crf", cmd)


class JobPathTests(unittest.TestCase):
    def test_a_renamed_output_never_takes_another_sources_name(self):
        w = JobWorker({})
        w._natural_outputs = {os.path.normcase(p) for p in (r"o\film.avi", r"o\film.mp4", r"o\tek.avi")}
        self.assertEqual(w._video_dst(r"o\film.avi", "h264"), r"o\film (avi).mp4")
        self.assertEqual(w._video_dst(r"o\tek.avi", "h264"), r"o\tek.mp4")
        self.assertEqual(w._video_dst(r"o\film.mp4", "av1"), r"o\film.mp4")


class KeepOriginalTests(TempDirTestCase):
    def test_kept_original_keeps_its_own_extension(self):
        src = self.tmp / "eski.avi"
        src.write_bytes(b"s" * 1000)
        vc = VideoCompressor("ffmpeg", "ffprobe")

        def fake_run(cmd, *_a):
            Path(cmd[-1]).write_bytes(b"v" * 5000)  # çıktı büyük: orijinal korunur
            return "ok"

        with mock.patch.object(vc, "duration", return_value=5.0), \
                mock.patch.object(vc, "probe_streams", return_value=None), \
                mock.patch.object(vc, "_run", side_effect=fake_run):
            ok, msg = vc.compress(str(src), str(self.tmp / "o" / "eski.avi"), "cpu", "h264", AUTO_BITRATE, 24,
                                  "slow", "128k", None)
        self.assertTrue(ok, msg)
        self.assertIn("Orijinal", msg)
        self.assertEqual(self.listing(self.tmp / "o"), ["eski.avi"], "AVI içeriği .mp4 adıyla yazılmaz")
        self.assertEqual(vc.last_output, str(self.tmp / "o" / "eski.avi"))


@unittest.skipUnless(FFMPEG and FFPROBE, "ffmpeg/ffprobe yok")
class RealJobTests(TempDirTestCase):
    def _clip(self, path: Path, extra=()):
        subprocess.run(
            [FFMPEG, "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
             "testsrc2=size=320x240:rate=25:duration=1", "-f", "lavfi", "-i", "sine=duration=1",
             "-c:v", "libx264", "-preset", "ultrafast", "-crf", "0", "-pix_fmt", "yuv420p", *extra, "-shortest", str(path)],
            check=True, timeout=120, stdin=subprocess.DEVNULL,
        )

    def _job(self, src_dir: Path, out_dir: Path, codec: str):
        w = JobWorker({
            "sources": [str(src_dir)], "output_dir": str(out_dir), "file_type": "videos", "scan_subfolders": False,
            "ffmpeg_path": FFMPEG, "ffprobe_path": FFPROBE, "gpu_mode": "cpu", "codec": codec,
            "bitrate": AUTO_BITRATE, "crf": 30, "preset": "superfast", "audio_bitrate": "96k", "video_res": None,
            "image_res": None, "image_quality": None, "keep_order": True, "lang": "tr",
        })
        done = []
        w.file_done.connect(lambda p, status, extra: done.append((os.path.basename(p), status)))
        w.run()
        return sorted(done)

    def _codec(self, path: Path) -> str:
        out = subprocess.run([FFPROBE, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=codec_name",
                              "-of", "json", str(path)], capture_output=True, text=True, timeout=60).stdout
        return json.loads(out)["streams"][0]["codec_name"]

    def test_mov_av1_avi_and_a_name_clash(self):
        src = self.tmp / "src"
        src.mkdir()
        self._clip(src / "IMG_0001.mov")
        self._clip(src / "film.avi", ["-c:a", "pcm_s16le"])
        self._clip(src / "film.mp4")
        out = self.tmp / "out"
        first = self._job(src, out, "av1")
        self.assertEqual([s for _, s in first], ["ok"] * 3, first)
        self.assertEqual(self.listing(out), ["IMG_0001.mp4", "film (avi).mp4", "film.mp4"])
        for name in ("IMG_0001.mp4", "film (avi).mp4", "film.mp4"):
            self.assertEqual(self._codec(out / name), "av1", name)
        again = self._job(src, out, "av1")
        self.assertEqual([s for _, s in again], ["skip"] * 3, "ikinci çalıştırmada hepsi zaten var")


if __name__ == "__main__":
    unittest.main()
