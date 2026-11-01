"""Donanımlı kod çözme ve piksel biçimi.

* NVENC: NVDEC çözer, kareler GPU'da kalır (scale_cuda, lanczos) -> işlemci neredeyse boşta.
* Döndürülmüş (telefonda dikey) videolar ve NVDEC'in çözemediği biçimler yazılım çözmede kalır.
* Donanım çözme başarısız olursa aynı kodlayıcıyla yazılım çözme denenir; o kodek oturum boyunca kapatılır.
* H.264 çıktısı her zaman 8-bit 4:2:0: 10-bit kaynakta GPU kodlayıcıları hata verip CPU'ya düşüyor,
  libx264 ise "High 10" (çoğu cihazda oynamaz) üretiyordu.
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

from src.core import gpu_detector, video_compressor  # noqa: E402
from src.core.gpu_detector import hw_input_args, mark_decode_failed, reset_probe_cache  # noqa: E402
from src.core.video_compressor import (  # noqa: E402
    EVEN_CROP, VideoCompressor, cuda_decodable, first_video, odd_size, pix_fmt_info, target_pix_fmt,
)

FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")


def after(cmd, flag):
    return cmd[cmd.index(flag) + 1]


def video(codec="h264", pix_fmt="yuv420p", rotated=False, fps=30.0, width=1920, height=1080):
    return {"index": 0, "type": "video", "codec": codec, "fps": fps, "pix_fmt": pix_fmt, "rotated": rotated,
            "width": width, "height": height}


AUDIO = {"index": 1, "type": "audio", "codec": "aac", "fps": None, "pix_fmt": None, "rotated": False}


class PixelFormatTests(unittest.TestCase):
    def test_bit_depth_and_chroma_are_read_from_the_name(self):
        self.assertEqual(pix_fmt_info("yuv420p"), (8, True))
        self.assertEqual(pix_fmt_info("yuvj420p"), (8, True))
        self.assertEqual(pix_fmt_info("yuv420p10le"), (10, True))
        self.assertEqual(pix_fmt_info("p010le"), (10, True))
        self.assertEqual(pix_fmt_info("yuv422p10le"), (10, False))
        self.assertEqual(pix_fmt_info("yuv444p12le"), (12, False))
        self.assertEqual(pix_fmt_info("rgb24"), (8, False))
        for unknown in (None, "", "none", "unknown"):
            self.assertIsNone(pix_fmt_info(unknown))

    def test_h264_is_always_8_bit_420(self):
        for enc in ("h264_nvenc", "h264_amf", "h264_qsv", "h264_videotoolbox"):
            self.assertEqual(target_pix_fmt(enc, "yuv420p10le"), "nv12", enc)
            self.assertEqual(target_pix_fmt(enc, "yuv422p"), "nv12", enc)
            self.assertIsNone(target_pix_fmt(enc, "yuv420p"), "8-bit 4:2:0 kaynağa dokunulmaz")
            self.assertIsNone(target_pix_fmt(enc, "yuvj420p"), "tam aralık (iPhone) olduğu gibi kalır")
        self.assertEqual(target_pix_fmt("libx264", "yuv420p10le"), "yuv420p")
        self.assertEqual(target_pix_fmt("libx264", "rgb24"), "yuv420p", "4:4:4 Predictive yerine uyumlu High")

    def test_hevc_and_av1_keep_10_bit_but_drop_to_420(self):
        self.assertIsNone(target_pix_fmt("hevc_nvenc", "yuv420p10le"))
        self.assertIsNone(target_pix_fmt("libx265", "yuv420p10le"))
        self.assertIsNone(target_pix_fmt("libsvtav1", "yuv420p"))
        self.assertEqual(target_pix_fmt("libx265", "yuv422p10le"), "yuv420p10le")
        self.assertEqual(target_pix_fmt("hevc_nvenc", "yuv422p10le"), "p010le")
        self.assertEqual(target_pix_fmt("hevc_amf", "yuv444p"), "nv12")
        self.assertEqual(target_pix_fmt("libx265", "yuv420p12le"), "yuv420p10le", "12-bit: 10-bit'e")
        self.assertIsNone(target_pix_fmt("hevc_nvenc", None), "bilinmeyen kaynak: eski davranış")

    def test_first_video_is_the_mapped_stream(self):
        self.assertIsNone(first_video(None))
        self.assertIs(first_video([AUDIO, video("hevc")])["codec"], "hevc")


class CudaEligibilityTests(unittest.TestCase):
    def test_supported_sources(self):
        self.assertTrue(cuda_decodable(video("h264", "yuv420p")))
        self.assertTrue(cuda_decodable(video("h264", "yuvj420p")))
        self.assertTrue(cuda_decodable(video("hevc", "yuv420p10le")))
        self.assertTrue(cuda_decodable(video("av1", "yuv420p")))
        self.assertTrue(cuda_decodable(video("vp9", "yuv420p10le")))

    def test_unsupported_sources_stay_on_software_decode(self):
        self.assertFalse(cuda_decodable(video("h264", "yuv420p10le")), "H.264 High 10: NVDEC çözemez")
        self.assertFalse(cuda_decodable(video("hevc", "yuv422p10le")), "4:2:2")
        self.assertFalse(cuda_decodable(video("hevc", "yuv420p12le")))
        self.assertFalse(cuda_decodable(video("prores", "yuv422p10le")))
        self.assertFalse(cuda_decodable(video("h264", None)), "biçim bilinmiyor")
        self.assertFalse(cuda_decodable(None))

    def test_rotated_phone_video_is_not_decoded_on_the_gpu(self):
        # ffmpeg GPU karelerini otomatik döndüremiyor: dikey video yan yatık çıkıyordu.
        self.assertFalse(cuda_decodable(video("hevc", "yuvj420p", rotated=True)))


class InputArgsTests(unittest.TestCase):
    def test_cuda_only_for_nvenc_and_videotoolbox_only_on_request(self):
        self.assertEqual(hw_input_args("nvenc", decode="cuda"), ["-hwaccel", "cuda", "-hwaccel_output_format", "cuda"])
        self.assertEqual(hw_input_args("amf", decode="cuda"), [])
        self.assertEqual(hw_input_args("nvenc"), [])
        self.assertEqual(hw_input_args("videotoolbox", decode="videotoolbox"), ["-hwaccel", "videotoolbox"])
        self.assertEqual(hw_input_args("videotoolbox"), [])


class CudaCommandTests(unittest.TestCase):
    def setUp(self):
        self.vc = VideoCompressor("ffmpeg")

    def _cmd(self, family="nvenc", codec="h264", streams=None, max_width=None, **kw):
        return self.vc.build_cmd("in.mp4", "out.mp4", family, codec, AUTO_BITRATE, 24, "slow", "128k", max_width,
                                 streams=streams, **kw)

    def test_ten_bit_hevc_to_h264_scales_and_converts_on_the_gpu(self):
        cmd = self._cmd(streams=[video("hevc", "yuv420p10le"), AUDIO], max_width=1920, decode="cuda", fps=30)
        self.assertEqual(cmd[6:10], ["-hwaccel", "cuda", "-hwaccel_output_format", "cuda"])
        self.assertLess(cmd.index("-hwaccel"), cmd.index("-i"))
        self.assertEqual(
            after(cmd, "-vf"),
            "fps=30,scale_cuda=w='if(gt(iw,1920),1920,iw)':h=-2:interp_algo=lanczos:format=nv12",
        )
        self.assertEqual(after(cmd, "-c:v"), "h264_nvenc")

    def test_without_scaling_only_the_needed_conversion_runs(self):
        self.assertEqual(after(self._cmd(streams=[video("hevc", "yuv420p10le")], decode="cuda"), "-vf"),
                         "scale_cuda=format=nv12")
        self.assertNotIn("-vf", self._cmd(streams=[video("h264", "yuv420p")], decode="cuda"))
        self.assertNotIn("-vf", self._cmd(codec="hevc", streams=[video("hevc", "yuv420p10le")], decode="cuda"),
                         "HEVC 10-bit korunur (Main 10)")

    def test_software_retry_variant_uses_cpu_scale_and_format(self):
        cmd = self._cmd(streams=[video("hevc", "yuv420p10le")], max_width=1280, decode="cuda", hw_decode=False)
        self.assertNotIn("-hwaccel", cmd)
        self.assertEqual(after(cmd, "-vf"), "scale='if(gt(iw,1280),1280,iw)':-2,format=nv12")

    def test_odd_custom_width_is_made_even_on_cpu_and_cuda(self):
        # 1285 gibi tek genişlik libx264/libx265'te "width not divisible by 2" hatası veriyordu.
        cuda = self._cmd(streams=[video("hevc", "yuv420p10le")], max_width=1285, decode="cuda")
        self.assertEqual(after(cuda, "-vf"),
                         "scale_cuda=w='if(gt(iw,1284),1284,iw)':h=-2:interp_algo=lanczos:format=nv12")
        cpu = self._cmd(family="cpu", streams=[video("h264", "yuv420p")], max_width=1285)
        self.assertEqual(after(cpu, "-vf"), "scale='if(gt(iw,1284),1284,iw)':-2")
        even = self._cmd(family="cpu", streams=[video("h264", "yuv420p")], max_width=1280)
        self.assertEqual(after(even, "-vf"), "scale='if(gt(iw,1280),1280,iw)':-2")

    def test_cuda_request_is_ignored_for_other_families(self):
        for family in ("amf", "qsv", "cpu"):
            cmd = self._cmd(family=family, streams=[video("h264", "yuv420p")], max_width=1280, decode="cuda")
            self.assertNotIn("-hwaccel", cmd, family)
            self.assertNotIn("scale_cuda", " ".join(cmd), family)

    def test_ten_bit_source_on_every_h264_path_gets_8_bit(self):
        streams = [video("hevc", "yuv420p10le")]
        self.assertEqual(after(self._cmd(family="amf", streams=streams), "-vf"), "format=nv12")
        self.assertEqual(after(self._cmd(family="qsv", streams=streams), "-vf"), "format=nv12")
        self.assertEqual(after(self._cmd(family="cpu", streams=streams), "-vf"), "format=yuv420p")
        self.assertEqual(after(self._cmd(family="nvenc", streams=streams), "-vf"), "format=nv12")
        self.assertEqual(after(self._cmd(family="vaapi", streams=streams), "-vf"), "format=nv12,hwupload",
                         "VAAPI kendi zincirini kullanır")


class OddDimensionTests(unittest.TestCase):
    """Tek boyutlu kaynak (ör. 321x241) libx264/libx265/AMF'de "width not divisible by 2" ile duruyordu."""

    def setUp(self):
        self.vc = VideoCompressor("ffmpeg")

    def _vf(self, family="cpu", codec="h264", streams=None, max_width=None):
        cmd = self.vc.build_cmd("in.mp4", "out.mp4", family, codec, AUTO_BITRATE, 24, "slow", "128k", max_width,
                                streams=streams)
        return after(cmd, "-vf") if "-vf" in cmd else None

    def test_odd_size_helper(self):
        self.assertFalse(odd_size(video(width=320, height=240)))
        self.assertTrue(odd_size(video(width=321, height=240)))
        self.assertTrue(odd_size(video(width=320, height=241)))
        self.assertIsNone(odd_size(video(width=None, height=None)))
        self.assertIsNone(odd_size(None))

    def test_odd_source_is_cropped_to_even_on_every_software_frame_path(self):
        odd = [video("h264", "yuv420p", width=321, height=241)]
        for family in ("cpu", "nvenc", "amf", "qsv"):
            for codec in ("h264", "hevc", "av1"):
                with self.subTest(family=family, codec=codec):
                    self.assertEqual(self._vf(family, codec, odd), EVEN_CROP)
        self.assertEqual(self._vf("cpu", "h264", odd, max_width=1280),
                         EVEN_CROP + ",scale='if(gt(iw,1280),1280,iw)':-2")
        self.assertEqual(self._vf("vaapi", "h264", odd), EVEN_CROP + ",format=nv12,hwupload")

    def test_unknown_size_is_cropped_but_even_size_is_unchanged(self):
        self.assertEqual(self._vf(streams=None), EVEN_CROP)
        self.assertEqual(self._vf(streams=[video(width=None, height=None)]), EVEN_CROP)
        even = [video("h264", "yuv420p", width=1920, height=1080)]
        self.assertIsNone(self._vf(streams=even))
        self.assertEqual(self._vf(streams=even, max_width=1280), "scale='if(gt(iw,1280),1280,iw)':-2")

    def test_odd_source_skips_the_cuda_path(self):
        odd = video("h264", "yuv420p", width=1281, height=721)
        self.assertFalse(cuda_decodable(odd))
        with mock.patch.object(video_compressor, "cuda_pipeline_available", return_value=True):
            self.assertIsNone(VideoCompressor("ffmpeg-odd").decode_method("nvenc", odd))

    def test_ffmpeg_i_fallback_reads_the_size(self):
        text = ("  Stream #0:0[0x1](und): Video: h264 (High) (avc1 / 0x31637661), yuv420p(tv, bt709, progressive),"
                " 321x241 [SAR 1:1 DAR 321:241], 25 fps, 25 tbr (default)\n")
        with mock.patch("src.core.video_compressor.run_hidden", return_value=mock.Mock(stdout="", stderr=text)):
            streams = VideoCompressor("ffmpeg").probe_streams("a.mp4")
        self.assertEqual((streams[0]["width"], streams[0]["height"]), (321, 241))


class DecodeMethodTests(unittest.TestCase):
    def setUp(self):
        reset_probe_cache()
        self.addCleanup(reset_probe_cache)
        self.vc = VideoCompressor("ffmpeg-x")

    def test_choice(self):
        with mock.patch.object(video_compressor, "cuda_pipeline_available", return_value=True):
            self.assertEqual(self.vc.decode_method("nvenc", video("hevc", "yuv420p10le")), "cuda")
            self.assertIsNone(self.vc.decode_method("nvenc", video("hevc", "yuv420p10le", rotated=True)))
            self.assertIsNone(self.vc.decode_method("amf", video()))
            self.assertIsNone(self.vc.decode_method("cpu", video()))
            self.assertEqual(self.vc.decode_method("videotoolbox", None), "videotoolbox")
            mark_decode_failed("ffmpeg-x", "cuda", "hevc")
            self.assertIsNone(self.vc.decode_method("nvenc", video("hevc", "yuv420p")), "başarısız kodek kapalı")
            self.assertEqual(self.vc.decode_method("nvenc", video("h264")), "cuda", "diğer kodekler etkilenmez")
        with mock.patch.object(video_compressor, "cuda_pipeline_available", return_value=False):
            self.assertIsNone(self.vc.decode_method("nvenc", video()), "derlemede cuda/scale_cuda yok")

    def test_capability_listing_is_read_once_per_ffmpeg(self):
        calls = []

        def fake_run(cmd, **_kw):
            calls.append(cmd[-1])
            text = "Hardware acceleration methods:\ncuda\nd3d11va\n" if cmd[-1] == "-hwaccels" else \
                " .. scale_cuda        V->V       GPU accelerated video resizer\n"
            return mock.Mock(stdout=text, stderr="", returncode=0)

        with mock.patch.object(gpu_detector, "run_hidden", side_effect=fake_run):
            self.assertTrue(gpu_detector.cuda_pipeline_available("ff-a"))
            self.assertTrue(gpu_detector.cuda_pipeline_available("ff-a"))
        self.assertEqual(calls, ["-hwaccels", "-filters"])

    def test_missing_scale_cuda_disables_the_pipeline(self):
        def fake_run(cmd, **_kw):
            text = "cuda\n" if cmd[-1] == "-hwaccels" else " .. hwupload_cuda  V->V  Upload\n"
            return mock.Mock(stdout=text, stderr="", returncode=0)

        with mock.patch.object(gpu_detector, "run_hidden", side_effect=fake_run):
            self.assertFalse(gpu_detector.cuda_pipeline_available("ff-b"))


class CompressRetryTests(TempDirTestCase):
    def setUp(self):
        super().setUp()
        reset_probe_cache()
        self.addCleanup(reset_probe_cache)
        self.src = self.tmp / "in.mp4"
        self.src.write_bytes(b"s" * 5000)
        self.vc = VideoCompressor("ffmpeg-y", "ffprobe")
        self.commands = []

    def _compress(self, outcomes, streams, name="out.mp4"):
        results = list(outcomes)

        def fake_run(cmd, *_a):
            self.commands.append(list(cmd))
            outcome = results.pop(0)
            if outcome == "ok":
                Path(cmd[-1]).write_bytes(b"v" * 100)
            return outcome

        with mock.patch.object(self.vc, "duration", return_value=5.0), \
                mock.patch.object(self.vc, "probe_streams", return_value=streams), \
                mock.patch.object(video_compressor, "encoder_supported", return_value=True), \
                mock.patch.object(video_compressor, "cuda_pipeline_available", return_value=True), \
                mock.patch.object(self.vc, "_run", side_effect=fake_run):
            return self.vc.compress(str(self.src), str(self.tmp / name), "nvenc", "h264", AUTO_BITRATE, 24, "slow",
                                    "128k", 1920)

    def test_cuda_failure_retries_with_software_decode_then_remembers(self):
        streams = [video("av1", "yuv420p"), AUDIO]
        ok, msg = self._compress(["av1 çözülemedi", "ok"], streams)
        self.assertTrue(ok, msg)
        first, second = self.commands
        self.assertEqual([after(c, "-c:v") for c in self.commands], ["h264_nvenc", "h264_nvenc"])
        self.assertIn("-hwaccel", first)
        self.assertIn("scale_cuda", after(first, "-vf"))
        self.assertNotIn("-hwaccel", second)
        self.assertTrue(after(second, "-vf").startswith("scale='"))
        self.assertIn("NVENC", msg)
        # Aynı kodek bir sonraki dosyada doğrudan yazılım çözmeyle gider.
        self.commands.clear()
        ok, _ = self._compress(["ok"], streams, "out2.mp4")
        self.assertTrue(ok)
        self.assertNotIn("-hwaccel", self.commands[0])

    def test_cpu_fallback_only_after_both_gpu_attempts_fail(self):
        ok, msg = self._compress(["e1", "e2", "ok"], [video("h264", "yuv420p")])
        self.assertTrue(ok)
        self.assertEqual([after(c, "-c:v") for c in self.commands], ["h264_nvenc", "h264_nvenc", "libx264"])
        self.assertIn("-hwaccel", self.commands[0])
        self.assertNotIn("-hwaccel", self.commands[1])
        self.assertNotIn("-hwaccel", self.commands[2])
        self.assertIn("CPU", msg)

    def test_rotated_source_goes_straight_to_software_decode(self):
        ok, _ = self._compress(["ok"], [video("hevc", "yuvj420p", rotated=True)])
        self.assertTrue(ok)
        self.assertEqual(len(self.commands), 1)
        self.assertNotIn("-hwaccel", self.commands[0])


def _nvenc_cuda_ready() -> bool:
    if not (FFMPEG and FFPROBE):
        return False
    return gpu_detector.probe_encoder(FFMPEG, "h264_nvenc") and gpu_detector.cuda_pipeline_available(FFMPEG)


def _probe(path: Path) -> dict:
    out = subprocess.run(
        [FFPROBE, "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=width,height,pix_fmt,profile:stream_side_data=rotation", "-of", "json", str(path)],
        capture_output=True, text=True, timeout=60,
    ).stdout
    return json.loads(out)["streams"][0]


@unittest.skipUnless(_nvenc_cuda_ready(), "NVENC + CUDA ffmpeg yok")
class RealNvencCudaTests(TempDirTestCase):
    def _make(self, name, *args):
        path = self.tmp / name
        subprocess.run([FFMPEG, "-nostdin", "-hide_banner", "-loglevel", "error", "-y", *args, str(path)],
                       check=True, timeout=180, stdin=subprocess.DEVNULL)
        return path

    def _compress(self, src, max_width):
        vc = VideoCompressor(FFMPEG, FFPROBE)
        seen = []
        real_run = vc._run

        def spy(cmd, *a):
            seen.append(list(cmd))
            return real_run(cmd, *a)

        out = self.tmp / f"out_{src.stem}.mp4"
        with mock.patch.object(vc, "_run", side_effect=spy):
            ok, msg = vc.compress(str(src), str(out), "nvenc", "h264", AUTO_BITRATE, 30, "slow", "128k", max_width)
        return ok, msg, out, seen

    def test_ten_bit_hevc_is_decoded_on_the_gpu_and_comes_out_8_bit(self):
        src = self._make("hevc10.mp4", "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30:duration=2",
                         "-c:v", "libx265", "-preset", "ultrafast", "-pix_fmt", "yuv420p10le", "-x265-params",
                         "log-level=error")
        ok, msg, out, seen = self._compress(src, 640)
        self.assertTrue(ok, msg)
        self.assertEqual(len(seen), 1, "ilk denemede başarılı")
        self.assertIn("-hwaccel", seen[0])
        info = _probe(out)
        self.assertEqual((info["width"], info["height"], info["pix_fmt"]), (640, 360, "yuv420p"))
        self.assertNotIn("10", info.get("profile", ""), info.get("profile"))

    def test_rotated_video_keeps_its_orientation(self):
        plain = self._make("plain.mp4", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30:duration=1",
                           "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p")
        rotated = self._make("rotated.mp4", "-display_rotation", "90", "-i", str(plain), "-c", "copy")
        ok, msg, out, seen = self._compress(rotated, None)
        self.assertTrue(ok, msg)
        self.assertNotIn("-hwaccel", seen[0])
        info = _probe(out)
        self.assertEqual((info["width"], info["height"]), (360, 640), "otomatik döndürme uygulandı (dikey)")


if __name__ == "__main__":
    unittest.main()
