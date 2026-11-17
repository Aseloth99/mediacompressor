"""Is kaydi satirlari arayuzun dilinde: en arayuzde Ingilizce, yuzde bicimi dile gore (tr %41.2, en 41.2%)."""

from __future__ import annotations

import os
import re
import string
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(__file__))
from _support import SignalLog, TempDirTestCase, make_image  # noqa: E402

from src.core import job_manager  # noqa: E402
from src.core.job_manager import JobWorker  # noqa: E402
from src.utils.locales import LOCALES  # noqa: E402

# Ingilizce satirda gecmemesi gereken Turkce izler (dosya adlari ASCII secildi)
TURKISH = re.compile(r"[çğıöşüÇĞİÖŞÜ]|\b(dosya|Resim|Atland|Hata|Tamamland|durduruldu|bulundu|yok)\b")


def _settings(sources, out, lang, file_type="images", ffmpeg=None):
    return {
        "sources": [str(s) for s in sources], "output_dir": str(out),
        "file_type": file_type, "scan_subfolders": False,
        "ffmpeg_path": ffmpeg, "ffprobe_path": None,
        "gpu_mode": "cpu", "codec": "h264", "bitrate": "auto", "crf": 24,
        "preset": "slow", "audio_bitrate": "128k", "video_res": None,
        "image_res": 2400, "image_quality": None, "keep_order": True, "lang": lang,
    }


class _FakeVideo:
    """Kodlamayi taklit eder: hedefi yarim boyutta yazar."""

    def __init__(self, *_a, **_k) -> None:
        self.last_output = None

    def compress(self, src, dst, **_k):
        with open(dst, "wb") as f:
            f.write(b"\0" * (os.path.getsize(src) // 2))
        self.last_output = dst
        return True, "H264 (CPU)"


class JobLogLanguageTests(TempDirTestCase):
    def _images(self, n=2):
        folder = self.tmp / "in"
        for i in range(n):
            make_image(folder / f"pic{i}.jpg", (40, 40))
        out = self.tmp / "out"
        out.mkdir(exist_ok=True)
        return folder, out

    def _run(self, settings):
        worker = JobWorker(settings)
        log = SignalLog(worker)
        worker._run_inner()
        return log

    def test_english_image_job_has_no_turkish_and_puts_percent_after_the_number(self) -> None:
        folder, out = self._images()
        log = self._run(_settings([folder], out, "en"))
        self.assertIn("Found 2 file(s). Starting compression…", log.logs)
        done = [line for line in log.logs if line.startswith("Image [")]
        self.assertEqual(len(done), 2, log.logs)
        for line in done:
            self.assertRegex(line, r"\| -?-?\d+\.\d%\)$")
            self.assertNotRegex(line, r"-%")
        for line in log.logs:
            self.assertNotRegex(line, TURKISH)

    def test_turkish_image_job_keeps_turkish_lines_and_percent_before_the_number(self) -> None:
        folder, out = self._images()
        log = self._run(_settings([folder], out, "tr"))
        self.assertIn("2 dosya bulundu. Sıkıştırma başlıyor…", log.logs)
        done = [line for line in log.logs if line.startswith("Resim [")]
        self.assertEqual(len(done), 2, log.logs)
        for line in done:
            self.assertRegex(line, r"\| -%-?\d+\.\d\)$")

    def test_skipped_line_follows_the_language(self) -> None:
        folder, out = self._images(1)
        self._run(_settings([folder], out, "en"))
        again = self._run(_settings([folder], out, "en"))
        self.assertIn("Skipped (already exists): pic0.jpg", again.logs)
        tr = self._run(_settings([folder], out, "tr"))
        self.assertIn("Atlandı (zaten mevcut): pic0.jpg", tr.logs)

    def test_empty_selection_line_follows_the_language(self) -> None:
        empty = self.tmp / "empty"
        empty.mkdir()
        out = self.tmp / "out"
        self.assertEqual(self._run(_settings([empty], out, "en")).logs,
                         ["No files of the selected type to process."])
        self.assertEqual(self._run(_settings([empty], out, "tr")).logs,
                         ["Seçilen türde işlenecek dosya bulunamadı."])

    def test_image_error_detail_is_wrapped_in_the_language_line(self) -> None:
        folder, out = self._images(1)
        with mock.patch.object(job_manager.ImageCompressor, "compress",
                               return_value=(False, "Hata: pic0.jpg — bozuk veri")):
            log = self._run(_settings([folder], out, "en"))
        self.assertIn("Error (pic0.jpg): bozuk veri", log.logs)
        self.assertEqual(log.done[-1][1:], ("fail", "bozuk veri"))

    def test_missing_ffmpeg_line_and_row_reason_follow_the_language(self) -> None:
        folder = self.tmp / "in"
        folder.mkdir()
        (folder / "clip.mp4").write_bytes(b"\0" * 64)
        out = self.tmp / "out"
        log = self._run(_settings([folder], out, "en", file_type="all"))
        self.assertIn("No FFmpeg, video skipped: clip.mp4", log.logs)
        self.assertEqual(log.done[-1][1:], ("fail", "No FFmpeg, video skipped"))

    def test_video_lines_follow_the_language(self) -> None:
        folder = self.tmp / "in"
        folder.mkdir()
        (folder / "clip.mp4").write_bytes(b"\0" * 4096)
        out = self.tmp / "out"
        with mock.patch.object(job_manager, "VideoCompressor", _FakeVideo):
            en = self._run(_settings([folder], out, "en", file_type="all", ffmpeg="ffmpeg"))
        self.assertIn("Video [1/1]: clip.mp4 …", en.logs)
        done = [line for line in en.logs if line.startswith("Done [H264 (CPU)]: clip.mp4 (")]
        self.assertEqual(len(done), 1, en.logs)
        self.assertIn("| -50.0% |", done[0])
        for line in en.logs:
            self.assertNotRegex(line, TURKISH)

        out_tr = self.tmp / "out_tr"
        with mock.patch.object(job_manager, "VideoCompressor", _FakeVideo):
            tr = self._run(_settings([folder], out_tr, "tr", file_type="all", ffmpeg="ffmpeg"))
        done = [line for line in tr.logs if line.startswith("Tamamlandı [H264 (CPU)]: clip.mp4 (")]
        self.assertEqual(len(done), 1, tr.logs)
        self.assertIn("| -%50.0 |", done[0])

    def test_original_kept_label_is_translated(self) -> None:
        en = JobWorker({"lang": "en"})
        self.assertEqual(en._video_method("H264 (CPU) (Orijinal korundu)"), "H264 (CPU) (original kept)")
        tr = JobWorker({"lang": "tr"})
        self.assertEqual(tr._video_method("H264 (CPU) (Orijinal korundu)"), "H264 (CPU) (Orijinal korundu)")
        self.assertEqual(en._video_method("HEVC (NVENC)"), "HEVC (NVENC)")

    def test_unexpected_error_line_follows_the_language(self) -> None:
        worker = JobWorker({"lang": "en"})
        log = SignalLog(worker)
        with mock.patch.object(worker, "_run_inner", side_effect=RuntimeError("boom")), \
             mock.patch.object(job_manager, "log_error"):
            worker.run()
        self.assertEqual(log.logs, ["Unexpected error: boom"])
        self.assertEqual(log.finished[0]["ok"], 0)

    def test_log_keys_take_the_same_fields_in_every_language(self) -> None:
        def fields(text):
            return sorted(name for _, name, _, _ in string.Formatter().parse(text) if name)

        keys = [k for k in LOCALES["tr"] if k.startswith("log_")]
        self.assertGreaterEqual(len(keys), 15)
        for lang, table in LOCALES.items():
            for key in keys:
                self.assertEqual(fields(table[key]), fields(LOCALES["tr"][key]), (lang, key))


if __name__ == "__main__":
    unittest.main()
