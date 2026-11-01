"""Madde 1: yarim cikti "mevcut" sayilmamali (atomik yazim + temizlik + sweep)."""

from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(__file__))
from _support import AUTO_BITRATE, SignalLog, TempDirTestCase, make_image  # noqa: E402

from PIL import Image  # noqa: E402

from src.core import job_manager  # noqa: E402
from src.core.atomic_output import (  # noqa: E402
    CANCELLED, is_partial_name, sweep_partial_files, temp_path_for,
)
from src.core.image_compressor import ImageCompressor  # noqa: E402
from src.core.job_manager import JobWorker, output_exists  # noqa: E402
from src.core.video_compressor import VideoCompressor  # noqa: E402


class TempNameTests(TempDirTestCase):
    def test_extension_is_kept_and_name_is_detected(self) -> None:
        tmp = temp_path_for(str(self.tmp / "a" / "film.mp4"))
        self.assertTrue(tmp.endswith("film.mcpart.mp4"))
        self.assertTrue(is_partial_name(tmp))
        self.assertFalse(is_partial_name("film.mp4"))
        # Kullanicinin mesru x.tmp.mp4 dosyasi gecici sanilmamali.
        self.assertFalse(is_partial_name("x.tmp.mp4"))

    def test_sweep_removes_only_partials_recursively(self) -> None:
        (self.tmp / "sub").mkdir()
        keep = self.tmp / "sub" / "ok.mp4"
        keep.write_bytes(b"x")
        keep2 = self.tmp / "x.tmp.mp4"
        keep2.write_bytes(b"x")
        for p in (self.tmp / "a.mcpart.jpg", self.tmp / "sub" / "b.mcpart.mp4"):
            p.write_bytes(b"partial")
        self.assertEqual(sweep_partial_files(str(self.tmp)), 2)
        self.assertEqual(self.listing(self.tmp), ["sub/ok.mp4", "x.tmp.mp4"])
        self.assertEqual(sweep_partial_files(str(self.tmp / "yok")), 0)


class OutputExistsTests(TempDirTestCase):
    def _write(self, name: str, data: bytes = b"data") -> str:
        path = self.tmp / name
        path.write_bytes(data)
        return str(path)

    def test_png_heic_heif_count_converted_jpg(self) -> None:
        for ext in (".png", ".heic", ".heif"):
            with self.subTest(ext=ext):
                dst = str(self.tmp / f"foto{ext}")
                self.assertFalse(output_exists(dst, ext))
                self._write(f"foto{ext}".replace(ext, ".jpg"))
                self.assertTrue(output_exists(dst, ext))
                os.remove(self.tmp / "foto.jpg")

    def test_jpg_is_not_accepted_for_other_formats(self) -> None:
        self._write("foto.jpg")
        self.assertFalse(output_exists(str(self.tmp / "foto.webp"), ".webp"))
        self.assertFalse(output_exists(str(self.tmp / "foto.avif"), ".avif"))

    def test_zero_byte_legacy_partial_is_not_existing(self) -> None:
        dst = self._write("film.mp4", b"")
        self.assertFalse(output_exists(dst, ".mp4"))
        self._write("film.mp4", b"gercek")
        self.assertTrue(output_exists(dst, ".mp4"))


class ImageAtomicTests(TempDirTestCase):
    def _failing_save(self, partial: bytes = b"yarim"):
        def fake_save(self_img, fp, *args, **kwargs):  # noqa: ANN001
            with open(fp, "wb") as handle:
                handle.write(partial)
            raise OSError("disk dolu")
        return fake_save

    def test_success_leaves_only_final_file(self) -> None:
        src = make_image(self.tmp / "in" / "a.jpg", (80, 60))
        dst = str(self.tmp / "out" / "a.jpg")
        os.makedirs(os.path.dirname(dst))
        ok, result = ImageCompressor.compress(src, dst)
        self.assertTrue(ok, result)
        self.assertEqual(self.listing(self.tmp / "out"), ["a.jpg"])

    def test_failed_save_leaves_nothing_behind(self) -> None:
        src = make_image(self.tmp / "in" / "a.jpg", (80, 60))
        out = self.tmp / "out"
        out.mkdir()
        dst = str(out / "a.jpg")
        with mock.patch.object(Image.Image, "save", self._failing_save()):
            ok, result = ImageCompressor.compress(src, dst)
        self.assertFalse(ok)
        self.assertEqual(self.listing(out), [])
        self.assertFalse(output_exists(dst, ".jpg"))

    def test_failed_png_to_jpg_conversion_leaves_nothing(self) -> None:
        src = make_image(self.tmp / "in" / "a.png", (40, 40), fmt="PNG")
        out = self.tmp / "out"
        out.mkdir()
        dst = str(out / "a.png")
        with mock.patch.object(Image.Image, "save", self._failing_save()):
            ok, _ = ImageCompressor.compress(src, dst)
        self.assertFalse(ok)
        self.assertEqual(self.listing(out), [])
        self.assertFalse(output_exists(dst, ".png"))


class VideoAtomicTests(TempDirTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.src = self.tmp / "in" / "film.mp4"
        self.src.parent.mkdir()
        self.src.write_bytes(b"s" * 5000)
        self.out = self.tmp / "out"
        self.dst = str(self.out / "film.mp4")
        self.vc = VideoCompressor("ffmpeg-sahte")
        patcher = mock.patch.object(self.vc, "duration", return_value=10.0)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _compress(self, run_side_effect, gpu_mode="cpu"):
        with mock.patch.object(self.vc, "_run", side_effect=run_side_effect) as run:
            result = self.vc.compress(
                str(self.src), self.dst, gpu_mode=gpu_mode, codec="h264", bitrate=AUTO_BITRATE,
                crf=24, preset="slow", audio_bitrate="128k", max_width=None,
            )
        return result, run

    @staticmethod
    def _write_output(cmd, size):
        with open(cmd[-1], "wb") as handle:
            handle.write(b"v" * size)

    def test_ffmpeg_writes_to_temp_with_same_extension(self) -> None:
        seen = []

        def fake_run(cmd, *args):
            seen.append(cmd[-1])
            self._write_output(cmd, 100)
            return "ok"

        (ok, _), _ = self._compress(fake_run)
        self.assertTrue(ok)
        self.assertNotEqual(seen[0], self.dst)
        self.assertTrue(seen[0].endswith(".mcpart.mp4"))
        self.assertEqual(self.listing(self.out), ["film.mp4"])

    def test_failure_removes_partial_and_is_not_skipped_next_time(self) -> None:
        def fake_run(cmd, *args):
            self._write_output(cmd, 100)  # yarim dosya
            return "Conversion failed!"

        (ok, msg), _ = self._compress(fake_run)
        self.assertFalse(ok)
        self.assertEqual(msg, "Conversion failed!")
        self.assertEqual(self.listing(self.out), [])
        self.assertFalse(output_exists(self.dst, ".mp4"))

    def test_cancel_removes_partial(self) -> None:
        def fake_run(cmd, *args):
            self._write_output(cmd, 100)
            return CANCELLED

        (ok, msg), _ = self._compress(fake_run)
        self.assertEqual((ok, msg), (False, CANCELLED))
        self.assertEqual(self.listing(self.out), [])

    def test_exception_in_run_still_cleans_temp(self) -> None:
        def fake_run(cmd, *args):
            self._write_output(cmd, 100)
            raise RuntimeError("beklenmedik")

        with self.assertRaises(RuntimeError):
            self._compress(fake_run)
        self.assertEqual(self.listing(self.out), [])

    def test_gpu_failure_then_cpu_success_commits_only_cpu_output(self) -> None:
        calls = []

        def fake_run(cmd, *args):
            calls.append(list(cmd))
            self._write_output(cmd, 100)
            return "Error initializing output stream" if len(calls) == 1 else "ok"

        with mock.patch("src.core.video_compressor.encoder_supported", return_value=True):
            (ok, msg), _ = self._compress(fake_run, gpu_mode="nvenc")
        self.assertTrue(ok)
        self.assertIn("CPU", msg)
        self.assertEqual(len(calls), 2)
        self.assertEqual(self.listing(self.out), ["film.mp4"])

    def test_output_not_smaller_keeps_original_atomically(self) -> None:
        def fake_run(cmd, *args):
            self._write_output(cmd, 9000)  # kaynaktan buyuk
            return "ok"

        (ok, msg), _ = self._compress(fake_run)
        self.assertTrue(ok)
        self.assertIn("Orijinal korundu", msg)
        self.assertEqual(self.listing(self.out), ["film.mp4"])
        self.assertEqual((self.out / "film.mp4").read_bytes(), b"s" * 5000)

    def test_zero_exit_without_output_file_is_failure(self) -> None:
        (ok, msg), _ = self._compress(lambda cmd, *a: "ok")
        self.assertFalse(ok)
        self.assertEqual(self.listing(self.out), [])


class JobIntegrationTests(TempDirTestCase):
    def _settings(self, sources, out):
        return {
            "sources": [str(s) for s in sources], "output_dir": str(out),
            "file_type": "all", "scan_subfolders": False,
            "ffmpeg_path": "ffmpeg-sahte", "ffprobe_path": None,
            "gpu_mode": "cpu", "codec": "h264", "bitrate": AUTO_BITRATE, "crf": 24,
            "preset": "slow", "audio_bitrate": "128k", "video_res": None,
            "image_res": 2400, "image_quality": None, "keep_order": True, "lang": "tr",
        }

    def _run_job(self, settings, run_side_effect):
        worker = JobWorker(settings)
        log = SignalLog(worker)
        with mock.patch.object(VideoCompressor, "duration", return_value=5.0), \
                mock.patch.object(VideoCompressor, "_run", side_effect=run_side_effect):
            worker._run_inner()
        return log

    def test_failed_video_is_retried_next_run_and_stale_parts_are_swept(self) -> None:
        src = self.tmp / "in" / "film.mp4"
        src.parent.mkdir()
        src.write_bytes(b"s" * 5000)
        out = self.tmp / "out"
        out.mkdir()
        stale = out / "eski.mcpart.jpg"
        stale.write_bytes(b"artik")
        settings = self._settings([src], out)

        def failing(cmd, *args):
            with open(cmd[-1], "wb") as handle:
                handle.write(b"yarim")
            return "Conversion failed!"

        log = self._run_job(settings, failing)
        self.assertEqual(log.finished[0]["fail"], 1)
        self.assertEqual(self.listing(out), [])  # stale silindi, yarim cikti kalmadi

        def succeeding(cmd, *args):
            with open(cmd[-1], "wb") as handle:
                handle.write(b"v" * 100)
            return "ok"

        log = self._run_job(settings, succeeding)
        self.assertEqual((log.finished[0]["ok"], log.finished[0]["skip"]), (1, 0))
        self.assertEqual(self.listing(out), ["film.mp4"])

        log = self._run_job(settings, succeeding)  # tamamlanmis cikti simdi gercekten atlanir
        self.assertEqual((log.finished[0]["ok"], log.finished[0]["skip"]), (0, 1))

    def test_heic_converted_jpg_is_skipped(self) -> None:
        # Gercek HEIC uretmek yerine uzanti mantigi: .heic kaynak + .jpg cikti.
        src = self.tmp / "in" / "foto.heic"
        src.parent.mkdir()
        src.write_bytes(b"heic")
        out = self.tmp / "out"
        out.mkdir()
        (out / "foto.jpg").write_bytes(b"jpegdata")
        self.assertTrue(job_manager.output_exists(str(out / "foto.heic"), ".heic"))


if __name__ == "__main__":
    unittest.main()
