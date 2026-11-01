"""Madde 6: FFmpeg tedarigi — zaman asimi, iptal, SHA-256 dogrulama, gecici zip.

Gercek ag cagrisi yapilmaz: urllib.request.urlopen taklit edilir.
"""

from __future__ import annotations

import hashlib
import io
import os
import sys
import threading
import unittest
import urllib.error
import zipfile
from unittest import mock

sys.path.insert(0, os.path.dirname(__file__))
from _support import TempDirTestCase  # noqa: E402

from src.core import ffmpeg_manager  # noqa: E402
from src.core.ffmpeg_manager import FFmpegManager, parse_sha256  # noqa: E402

EXE = ffmpeg_manager.ffmpeg_name()
PROBE = ffmpeg_manager.ffprobe_name()


def make_zip(include_exe=True) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("ffmpeg-7.1-essentials_build/README.txt", "okuyun")
        if include_exe:
            archive.writestr(f"ffmpeg-7.1-essentials_build/bin/{EXE}", b"MZ-ffmpeg-" + os.urandom(2000))
            archive.writestr(f"ffmpeg-7.1-essentials_build/bin/{PROBE}", b"MZ-ffprobe-" + os.urandom(500))
    return buf.getvalue()


class FakeResponse:
    def __init__(self, data: bytes, content_length="auto", chunk=None):
        self._buf = io.BytesIO(data)
        length = len(data) if content_length == "auto" else content_length
        self.headers = {} if length is None else {"Content-Length": str(length)}
        self._chunk = chunk

    def read(self, n=-1):
        if self._chunk and n > 0:
            n = min(n, self._chunk)
        return self._buf.read(n)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeNetwork:
    """urlopen yerine gecer; adrese gore zip ya da .sha256 doner."""

    def __init__(self, zip_bytes, sha_text="auto", sha_error=None, zip_kwargs=None):
        self.zip_bytes = zip_bytes
        self.sha_text = hashlib.sha256(zip_bytes).hexdigest() if sha_text == "auto" else sha_text
        self.sha_error = sha_error
        self.zip_kwargs = zip_kwargs or {}
        self.calls: list[tuple[str, object]] = []

    def __call__(self, request, *args, **kwargs):
        url = request.full_url if hasattr(request, "full_url") else str(request)
        self.calls.append((url, kwargs.get("timeout")))
        if url.endswith(".sha256"):
            if self.sha_error:
                raise self.sha_error
            return FakeResponse(self.sha_text.encode(), content_length=None)
        return FakeResponse(self.zip_bytes, **self.zip_kwargs)


class DownloadTests(TempDirTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.hedef = str(self.tmp / "ffmpeg")
        self.manager = FFmpegManager()

    def _run(self, network, progress_cb=None, cancel_event=None):
        with mock.patch.object(ffmpeg_manager.urllib.request, "urlopen", network):
            return self.manager._download_to(self.hedef, progress_cb, cancel_event)

    def _leftovers(self):
        return [p for p in self.listing(self.hedef) if p not in (f"bin/{EXE}", f"bin/{PROBE}")]

    def test_verified_download_installs_to_stable_bin_dir_and_find_sees_it(self) -> None:
        network = FakeNetwork(make_zip())
        path = self._run(network)
        self.assertEqual(path, os.path.join(self.hedef, "bin", EXE))
        self.assertTrue(os.path.isfile(path))
        self.assertEqual(self.manager.ffprobe_path, os.path.join(self.hedef, "bin", PROBE))
        self.assertEqual(self._leftovers(), [])  # .part ve acma klasoru temizlendi
        # Eski kod surum klasorune acip dondu: bir sonraki acilista find() bulamiyordu.
        fresh = FFmpegManager()
        with mock.patch.object(FFmpegManager, "_candidates", return_value=[(path, self.manager.ffprobe_path)]), \
                mock.patch.dict(os.environ, {"PATH": ""}):
            self.assertEqual(fresh.find(), path)

    def test_hash_mismatch_aborts_before_anything_is_installed(self) -> None:
        network = FakeNetwork(make_zip(), sha_text="0" * 64)
        with mock.patch.object(ffmpeg_manager, "log_error") as log_error:
            path = self._run(network)
        self.assertIsNone(path)
        self.assertIsNone(self.manager.ffmpeg_path)
        self.assertEqual(self.listing(self.hedef), [])
        self.assertIn("SHA-256", log_error.call_args.args[0])

    def test_tampered_zip_is_rejected(self) -> None:
        original = make_zip()
        network = FakeNetwork(original)
        network.zip_bytes = original[:-30] + b"x" * 30  # sha dosyasi orijinale ait
        self.assertIsNone(self._run(network))
        self.assertEqual(self.listing(self.hedef), [])

    def test_missing_checksum_logs_unverified_warning_and_still_installs(self) -> None:
        network = FakeNetwork(make_zip(), sha_error=urllib.error.URLError("404"))
        with mock.patch.object(ffmpeg_manager, "log_info") as log_info:
            path = self._run(network)
        self.assertTrue(path and os.path.isfile(path))
        messages = " ".join(str(c.args[0]) for c in log_info.call_args_list)
        self.assertIn("DOĞRULANAMADI", messages)

    def test_unparseable_checksum_is_treated_as_unverified_not_as_match(self) -> None:
        network = FakeNetwork(make_zip(), sha_text="<html>404 not found</html>")
        with mock.patch.object(ffmpeg_manager, "log_info") as log_info:
            path = self._run(network)
        self.assertTrue(path)
        self.assertIn("DOĞRULANAMADI", " ".join(str(c.args[0]) for c in log_info.call_args_list))

    def test_every_network_call_has_a_timeout(self) -> None:
        network = FakeNetwork(make_zip())
        self._run(network)
        self.assertGreaterEqual(len(network.calls), 2)  # zip + .sha256
        for url, timeout in network.calls:
            self.assertIsNotNone(timeout, url)
            self.assertLessEqual(timeout, 60, url)

    def test_cancel_stops_download_and_cleans_part_file(self) -> None:
        network = FakeNetwork(make_zip(), zip_kwargs={"chunk": 100})
        cancel = threading.Event()
        seen = []

        def progress(ratio):
            seen.append(ratio)
            if len(seen) == 3:
                cancel.set()

        self.assertIsNone(self._run(network, progress, cancel))
        self.assertEqual(len(seen), 3)  # iptal sonrasi okuma durdu
        self.assertEqual(self.listing(self.hedef), [])
        self.assertFalse(any(u.endswith(".sha256") for u, _ in network.calls))

    def test_truncated_download_is_rejected(self) -> None:
        data = make_zip()
        network = FakeNetwork(data, zip_kwargs={"content_length": len(data) + 500})
        self.assertIsNone(self._run(network))
        self.assertEqual(self.listing(self.hedef), [])

    def test_network_error_returns_none_without_leftovers(self) -> None:
        def broken(request, *args, **kwargs):
            raise TimeoutError("zaman asimi")

        with mock.patch.object(ffmpeg_manager.urllib.request, "urlopen", broken):
            self.assertIsNone(self.manager._download_to(self.hedef))
        self.assertEqual(self.listing(self.hedef), [])

    def test_zip_without_ffmpeg_exe_fails_cleanly(self) -> None:
        network = FakeNetwork(make_zip(include_exe=False))
        self.assertIsNone(self._run(network))
        self.assertEqual(self.listing(self.hedef), [])

    def test_non_https_url_is_refused_without_network(self) -> None:
        network = FakeNetwork(make_zip())
        with mock.patch.object(FFmpegManager, "DOWNLOAD_URL", "http://example.com/ffmpeg.zip"):
            self.assertIsNone(self._run(network))
        self.assertEqual(network.calls, [])

    def test_progress_reaches_one(self) -> None:
        network = FakeNetwork(make_zip(), zip_kwargs={"chunk": 512})
        ratios: list[float] = []
        self._run(network, ratios.append)
        self.assertEqual(ratios, sorted(ratios))
        self.assertEqual(ratios[-1], 1.0)

    def test_public_download_passes_cancel_event_and_uses_user_data_dir(self) -> None:
        windows_manager = FFmpegManager(platform="win32")  # indirme yalnizca Windows'ta acik
        with mock.patch.object(ffmpeg_manager, "get_user_data_dir", return_value=str(self.tmp)), \
                mock.patch.object(FFmpegManager, "_download_to", return_value="x") as inner:
            cancel = threading.Event()
            self.assertEqual(windows_manager.download(None, cancel_event=cancel), "x")
        args = inner.call_args.args
        self.assertEqual(args[0], os.path.join(str(self.tmp), "ffmpeg"))
        self.assertIs(args[2], cancel)


class HashParsingTests(unittest.TestCase):
    H = hashlib.sha256(b"x").hexdigest()

    def test_formats(self) -> None:
        self.assertEqual(parse_sha256(self.H), self.H)
        self.assertEqual(parse_sha256(f"{self.H.upper()}  ffmpeg-release-essentials.zip\n"), self.H)
        self.assertEqual(parse_sha256(f"SHA256 ({'x'}) = {self.H}"), self.H)
        self.assertIsNone(parse_sha256("404 not found"))
        self.assertIsNone(parse_sha256(self.H + "ab"))  # 66 hane: uzun bir sayinin parcasi
        self.assertIsNone(parse_sha256(""))


class PrepareWorkerTests(unittest.TestCase):
    def test_prepare_worker_forwards_cancel_event_to_download(self) -> None:
        from src.gui.main_window import PrepareWorker

        manager = mock.Mock()
        manager.find.return_value = None
        manager.download.return_value = None
        manager.missing_hint.return_value = "yok"
        worker = PrepareWorker(manager, download=True)
        worker.run()
        self.assertIs(manager.download.call_args.kwargs["cancel_event"], worker.cancel_event)
        worker.stop()
        self.assertTrue(worker.cancel_event.is_set())


if __name__ == "__main__":
    unittest.main()
