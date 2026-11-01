"""Madde 5a: akis (-map) politikasi — coklu ses, metin altyazi, bitmap altyazi atlama."""

from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(__file__))
from _support import AUTO_BITRATE, TempDirTestCase  # noqa: E402

from src.core.video_compressor import VideoCompressor, plan_subtitles  # noqa: E402

STREAMS = [
    {"index": 0, "type": "video", "codec": "h264"},
    {"index": 1, "type": "audio", "codec": "aac"},
    {"index": 2, "type": "audio", "codec": "ac3"},
    {"index": 3, "type": "subtitle", "codec": "subrip"},
    {"index": 4, "type": "subtitle", "codec": "hdmv_pgs_subtitle"},
    {"index": 5, "type": "subtitle", "codec": "ass"},
    {"index": 6, "type": "subtitle", "codec": "dvd_subtitle"},
    {"index": 7, "type": "subtitle", "codec": "mov_text"},
    {"index": 8, "type": "subtitle", "codec": "webvtt"},
    {"index": 9, "type": "data", "codec": "bin_data"},
    {"index": 10, "type": "attachment", "codec": "ttf"},
]


def maps_of(cmd: list[str]) -> list[str]:
    return [cmd[i + 1] for i, token in enumerate(cmd) if token == "-map"]


class StreamPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.vc = VideoCompressor("ffmpeg")

    def _cmd(self, dst, streams=None, codec="h264"):
        return self.vc.build_cmd("in.mkv", dst, "cpu", codec, AUTO_BITRATE, 24, "slow", "128k", None, streams=streams)

    def test_default_policy_without_probe_is_first_video_all_audio_no_subtitles(self) -> None:
        cmd = self._cmd("out.mp4")
        self.assertEqual(maps_of(cmd), ["0:v:0", "0:a?"])
        self.assertNotIn("-c:s", cmd)
        self.assertLess(cmd.index("-map"), cmd.index("-c:v"))

    def test_multiple_audio_tracks_are_all_kept(self) -> None:
        cmd = self._cmd("out.mp4", STREAMS)
        self.assertIn("0:a?", maps_of(cmd))
        self.assertNotIn("0:a:0", maps_of(cmd))  # yalnizca ilk sesi secen kalip yok

    def test_mp4_keeps_text_subtitles_as_mov_text_and_skips_bitmap(self) -> None:
        for dst in ("out.mp4", "out.mov", "out.m4v", "out.mcpart.mp4"):
            with self.subTest(dst=dst):
                cmd = self._cmd(dst, STREAMS)
                self.assertEqual(maps_of(cmd), ["0:v:0", "0:a?", "0:3", "0:5", "0:7", "0:8"])
                self.assertEqual(cmd[cmd.index("-c:s") + 1], "mov_text")
                for bitmap in ("0:4", "0:6", "0:9", "0:10"):
                    self.assertNotIn(bitmap, maps_of(cmd))

    def test_mkv_copies_supported_text_subtitles_only(self) -> None:
        cmd = self._cmd("out.mkv", STREAMS)
        self.assertEqual(maps_of(cmd), ["0:v:0", "0:a?", "0:3", "0:5", "0:8"])
        self.assertEqual(cmd[cmd.index("-c:s") + 1], "copy")

    def test_avi_gets_no_subtitles(self) -> None:
        cmd = self._cmd("out.avi", STREAMS)
        self.assertEqual(maps_of(cmd), ["0:v:0", "0:a?"])
        self.assertNotIn("-c:s", cmd)

    def test_only_bitmap_subtitles_means_no_subtitle_args(self) -> None:
        streams = [s for s in STREAMS if s["codec"] not in ("subrip", "ass", "mov_text", "webvtt")]
        cmd = self._cmd("out.mp4", streams)
        self.assertEqual(maps_of(cmd), ["0:v:0", "0:a?"])
        self.assertNotIn("-c:s", cmd)
        self.assertEqual(plan_subtitles(streams, ".mp4"), ([], None))

    def test_gpu_hevc_cmd_keeps_policy_and_other_flags(self) -> None:
        cmd = self.vc.build_cmd("i.mkv", "o.mp4", "nvenc", "hevc", AUTO_BITRATE, 24, "slow", "128k", 1920,
                                streams=STREAMS)
        self.assertEqual(maps_of(cmd)[:2], ["0:v:0", "0:a?"])
        self.assertEqual(cmd[cmd.index("-c:v") + 1], "hevc_nvenc")
        self.assertIn("hvc1", cmd)
        self.assertEqual(cmd[-1], "o.mp4")


class ProbeStreamsTests(unittest.TestCase):
    FFMPEG_I_OUTPUT = """\
Input #0, matroska,webm, from 'film.mkv':
  Duration: 00:42:00.00, start: 0.000000, bitrate: 5000 kb/s
  Stream #0:0: Video: h264 (High), yuv420p(progressive), 1920x1080 [SAR 1:1 DAR 16:9], 24 fps
  Stream #0:1(eng): Audio: aac (LC), 48000 Hz, 5.1, fltp (default)
  Stream #0:2(tur): Audio: ac3, 48000 Hz, stereo, fltp
  Stream #0:3(eng): Subtitle: subrip (default)
  Stream #0:4[0x1100](jpn): Subtitle: hdmv_pgs_subtitle, 1920x1080
At least one output file must be specified
"""

    def test_ffprobe_json_is_parsed(self) -> None:
        vc = VideoCompressor("ffmpeg", "ffprobe")
        payload = ('{"streams": [{"index": 0, "codec_name": "hevc", "codec_type": "video",'
                   ' "avg_frame_rate": "30000/1001", "r_frame_rate": "30/1", "pix_fmt": "yuv420p10le",'
                   ' "width": 1920, "height": 1080,'
                   ' "side_data_list": [{"side_data_type": "Display Matrix", "rotation": -90}]},'
                   ' {"index": 2, "codec_name": "subrip", "codec_type": "subtitle", "avg_frame_rate": "0/0"}]}')
        with mock.patch("src.core.video_compressor.run_hidden", return_value=mock.Mock(stdout=payload)) as run:
            streams = vc.probe_streams("film.mkv")
        self.assertEqual(streams, [
            {"index": 0, "type": "video", "codec": "hevc", "fps": 30000 / 1001, "pix_fmt": "yuv420p10le",
             "rotated": True, "width": 1920, "height": 1080},
            {"index": 2, "type": "subtitle", "codec": "subrip", "fps": None, "pix_fmt": None, "rotated": False,
             "width": None, "height": None},
        ])
        self.assertIn("pix_fmt", run.call_args.args[0][4])
        self.assertIn("width,height", run.call_args.args[0][4])
        self.assertEqual(run.call_args.args[0][0], "ffprobe")

    def test_falls_back_to_ffmpeg_i_text(self) -> None:
        vc = VideoCompressor("ffmpeg")
        with mock.patch("src.core.video_compressor.run_hidden",
                        return_value=mock.Mock(stdout="", stderr=self.FFMPEG_I_OUTPUT)):
            streams = vc.probe_streams("film.mkv")
        self.assertEqual([(s["index"], s["type"], s["codec"]) for s in streams], [
            (0, "video", "h264"), (1, "audio", "aac"), (2, "audio", "ac3"),
            (3, "subtitle", "subrip"), (4, "subtitle", "hdmv_pgs_subtitle"),
        ])
        self.assertEqual(streams[0]["fps"], 24.0, "kare hızı ffmpeg -i çıktısından da okunur")
        self.assertEqual(streams[0]["pix_fmt"], "yuv420p")
        self.assertFalse(streams[0]["rotated"])
        self.assertIsNone(streams[1]["pix_fmt"])

    def test_ffmpeg_i_text_reports_ten_bit_and_rotation(self) -> None:
        text = (
            "  Stream #0:0[0x1](und): Video: hevc (Main 10) (hvc1 / 0x31637668), yuv420p10le(tv, bt2020nc/bt2020/"
            "arib-std-b67), 1920x1080, 9000 kb/s, 29.97 fps, 29.97 tbr (default)\n"
            "      Side data:\n        displaymatrix: rotation of -90.00 degrees\n"
            "  Stream #0:1[0x2](und): Audio: aac (LC) (mp4a / 0x6134706D), 44100 Hz, stereo, fltp\n"
        )
        vc = VideoCompressor("ffmpeg")
        with mock.patch("src.core.video_compressor.run_hidden", return_value=mock.Mock(stdout="", stderr=text)):
            streams = vc.probe_streams("a.mov")
        self.assertEqual((streams[0]["pix_fmt"], streams[0]["rotated"]), ("yuv420p10le", True))
        self.assertEqual((streams[1]["pix_fmt"], streams[1]["rotated"]), (None, False))

    def test_probe_failure_returns_none(self) -> None:
        vc = VideoCompressor("ffmpeg", "ffprobe")
        with mock.patch("src.core.video_compressor.run_hidden", side_effect=OSError("yok")):
            self.assertIsNone(vc.probe_streams("film.mkv"))


class CompressUsesProbeTests(TempDirTestCase):
    def test_probed_streams_reach_both_gpu_and_cpu_commands(self) -> None:
        src = self.tmp / "in" / "film.mkv"
        src.parent.mkdir()
        src.write_bytes(b"s" * 5000)
        vc = VideoCompressor("ffmpeg", "ffprobe")
        commands = []

        def fake_run(cmd, *args):
            commands.append(list(cmd))
            with open(cmd[-1], "wb") as handle:
                handle.write(b"v" * 100)
            return "ok" if len(commands) == 2 else "gpu hata"

        with mock.patch.object(vc, "duration", return_value=5.0), \
                mock.patch.object(vc, "probe_streams", return_value=STREAMS), \
                mock.patch("src.core.video_compressor.encoder_supported", return_value=True), \
                mock.patch.object(vc, "_run", side_effect=fake_run):
            ok, _ = vc.compress(str(src), str(self.tmp / "out" / "film.mkv"), gpu_mode="nvenc", codec="h264",
                                bitrate=AUTO_BITRATE, crf=24, preset="slow", audio_bitrate="128k", max_width=None)
        self.assertTrue(ok)
        self.assertEqual(len(commands), 2)
        for cmd in commands:
            self.assertEqual(maps_of(cmd), ["0:v:0", "0:a?", "0:3", "0:5", "0:8"])


if __name__ == "__main__":
    unittest.main()
