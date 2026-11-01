"""Madde 2: resim havuzunda iptal, bellek butcesi ve guvenli kapanis sirasi."""

from __future__ import annotations

import os
import sys
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(__file__))
from _support import SignalLog, TempDirTestCase, make_image  # noqa: E402

from PIL import ImageOps  # noqa: E402
from PyQt6.QtCore import Qt  # noqa: E402

from src.core import job_manager  # noqa: E402
from src.core.atomic_output import CANCELLED  # noqa: E402
from src.core.image_compressor import ImageCompressor  # noqa: E402
from src.core.job_manager import JobWorker  # noqa: E402
from src.core.workers import DaemonWorker, shutdown_workers  # noqa: E402


def _settings(sources, out):
    return {
        "sources": [str(s) for s in sources], "output_dir": str(out),
        "file_type": "images", "scan_subfolders": False,
        "ffmpeg_path": None, "ffprobe_path": None,
        "gpu_mode": "cpu", "codec": "h264", "bitrate": "otomatik", "crf": 24,
        "preset": "slow", "audio_bitrate": "128k", "video_res": None,
        "image_res": 2400, "image_quality": None, "keep_order": True, "lang": "tr",
    }


class ImageCancelTests(TempDirTestCase):
    def test_compress_honours_preset_cancel_event(self) -> None:
        src = make_image(self.tmp / "in" / "a.jpg")
        out = self.tmp / "out"
        out.mkdir()
        event = threading.Event()
        event.set()
        result = ImageCompressor.compress(src, str(out / "a.jpg"), cancel_event=event)
        self.assertEqual(result, (False, CANCELLED))
        self.assertEqual(self.listing(out), [])

    def test_compress_cancelled_midway_leaves_no_partial(self) -> None:
        src = make_image(self.tmp / "in" / "a.jpg")
        out = self.tmp / "out"
        out.mkdir()
        event = threading.Event()
        original = ImageOps.exif_transpose

        def transpose_then_cancel(img, *a, **k):
            result = original(img, *a, **k)
            event.set()  # decode bittikten sonra iptal gelir
            return result

        with mock.patch.object(ImageOps, "exif_transpose", transpose_then_cancel):
            result = ImageCompressor.compress(src, str(out / "a.jpg"), cancel_event=event)
        self.assertEqual(result, (False, CANCELLED))
        self.assertEqual(self.listing(out), [])


class ImagePoolCancelTests(TempDirTestCase):
    N = 40

    def _make_inputs(self):
        folder = self.tmp / "in"
        for i in range(self.N):
            make_image(folder / f"img{i:02d}.jpg", (48, 48))
        return folder

    def test_cancel_stops_submitting_remaining_images(self) -> None:
        folder = self._make_inputs()
        out = self.tmp / "out"
        out.mkdir()
        worker = JobWorker(_settings([folder], out))
        log = SignalLog(worker)
        # Ilk biten dosyada iptal et: eski kodda tum isler bastan havuza gonderildigi icin
        # N dosyanin hepsi yine de yazilirdi.
        worker.file_done.connect(lambda *_: worker.cancel_event.set())
        with mock.patch("os.cpu_count", return_value=2):
            worker._run_inner()
        written = [n for n in self.listing(out) if n.endswith(".jpg")]
        self.assertLess(len(written), self.N // 2, written)
        self.assertTrue(log.finished[0]["cancelled"])
        self.assertEqual([n for n in self.listing(out) if "mcpart" in n], [])
        self.assertLess(log.finished[0]["ok"], self.N // 2)

    def test_uncancelled_job_processes_everything(self) -> None:
        folder = self._make_inputs()
        out = self.tmp / "out"
        out.mkdir()
        worker = JobWorker(_settings([folder], out))
        log = SignalLog(worker)
        worker._run_inner()
        self.assertEqual(log.finished[0]["ok"], self.N)
        self.assertFalse(log.finished[0]["cancelled"])
        self.assertEqual(len(self.listing(out)), self.N)


class MemoryBudgetTests(TempDirTestCase):
    def _run_with_fake_compress(self, cost: int, n: int = 12, cpus: int = 4):
        folder = self.tmp / "in"
        for i in range(n):
            make_image(folder / f"img{i:02d}.jpg", (32, 32))
        out = self.tmp / "out"
        out.mkdir()
        lock = threading.Lock()
        state = {"now": 0, "peak": 0}

        def fake_compress(src, dst, **kwargs):
            with lock:
                state["now"] += 1
                state["peak"] = max(state["peak"], state["now"])
            time.sleep(0.04)
            with open(dst, "wb") as handle:
                handle.write(b"x")
            with lock:
                state["now"] -= 1
            return True, dst

        worker = JobWorker(_settings([folder], out))
        SignalLog(worker)
        with mock.patch("os.cpu_count", return_value=cpus), \
                mock.patch.object(ImageCompressor, "compress", side_effect=fake_compress), \
                mock.patch.object(job_manager, "estimate_image_memory", return_value=cost):
            worker._run_inner()
        return state["peak"]

    def test_large_images_reduce_parallelism_to_one(self) -> None:
        big = job_manager.IMAGE_MEMORY_BUDGET  # tek basina butceyi dolduran gorseller
        self.assertEqual(self._run_with_fake_compress(big), 1)

    def test_budget_for_two_images_caps_parallelism_at_two(self) -> None:
        half = job_manager.IMAGE_MEMORY_BUDGET // 2
        self.assertEqual(self._run_with_fake_compress(half), 2)

    def test_small_images_use_available_workers(self) -> None:
        self.assertGreaterEqual(self._run_with_fake_compress(1024 * 1024), 2)

    def test_estimate_scales_with_pixels_and_has_floor(self) -> None:
        small = make_image(self.tmp / "s.jpg", (32, 32))
        self.assertEqual(job_manager.estimate_image_memory(small), job_manager._MIN_IMAGE_COST)
        big = make_image(self.tmp / "b.png", (3000, 2000), fmt="PNG", noise=False)
        self.assertEqual(job_manager.estimate_image_memory(big), 3000 * 2000 * 12)
        missing = str(self.tmp / "yok.jpg")
        self.assertEqual(job_manager.estimate_image_memory(missing), job_manager._MIN_IMAGE_COST)


class _Sleeper(DaemonWorker):
    def __init__(self, seconds: float = 0.0, boom: bool = False):
        super().__init__()
        self.seconds = seconds
        self.boom = boom
        self.stopped = threading.Event()

    def stop(self) -> None:
        self.stopped.set()

    def run(self) -> None:
        if self.boom:
            raise RuntimeError("beklenmedik")
        self.stopped.wait(self.seconds)


class DaemonWorkerTests(unittest.TestCase):
    def test_runs_in_daemon_thread_and_signals_finished(self) -> None:
        worker = _Sleeper(0.0)
        fired = []
        worker.finished.connect(lambda: fired.append(1), Qt.ConnectionType.DirectConnection)
        self.assertFalse(worker.isRunning())
        worker.start()
        self.assertTrue(worker.wait(2000))
        self.assertTrue(worker._thread.daemon)
        self.assertFalse(worker.isRunning())
        deadline = time.time() + 2
        while not fired and time.time() < deadline:
            time.sleep(0.01)
        self.assertEqual(fired, [1])

    def test_wait_times_out_while_running_and_stop_releases(self) -> None:
        worker = _Sleeper(30)
        worker.start()
        self.assertTrue(worker.isRunning())
        self.assertFalse(worker.wait(50))
        worker.stop()
        self.assertTrue(worker.wait(2000))

    def test_exception_in_run_does_not_propagate(self) -> None:
        worker = _Sleeper(boom=True)
        worker.start()
        self.assertTrue(worker.wait(2000))


class _FakeWorker:
    def __init__(self, release_on_stop: bool, log: list, name: str):
        self.release_on_stop = release_on_stop
        self.running = True
        self.log = log
        self.name = name

    def stop(self) -> None:
        self.log.append(("stop", self.name))
        if self.release_on_stop:
            self.running = False

    def isRunning(self) -> bool:  # noqa: N802 - QThread arayuzu
        return self.running

    def wait(self, ms: int) -> bool:
        self.log.append(("wait", self.name))
        deadline = time.monotonic() + ms / 1000
        while self.running and time.monotonic() < deadline:
            time.sleep(0.005)
        return not self.running


class ShutdownOrderTests(unittest.TestCase):
    def test_all_stop_requests_precede_any_wait(self) -> None:
        log: list = []
        a = _FakeWorker(True, log, "a")
        b = _FakeWorker(True, log, "b")
        self.assertEqual(shutdown_workers([("a", a, a.stop), ("b", b, b.stop)], 1000), [])
        kinds = [k for k, _ in log]
        self.assertEqual(kinds, ["stop", "stop", "wait", "wait"])

    def test_unresponsive_worker_is_reported_within_total_budget(self) -> None:
        log: list = []
        stuck = _FakeWorker(False, log, "stuck")
        stuck2 = _FakeWorker(False, log, "stuck2")
        start = time.monotonic()
        still = shutdown_workers([("stuck", stuck, stuck.stop), ("stuck2", stuck2, stuck2.stop)], 150)
        elapsed = time.monotonic() - start
        self.assertEqual(sorted(still), ["stuck", "stuck2"])
        self.assertLess(elapsed, 0.6)  # sure butcesi ortak: workers*timeout degil

    def test_none_and_finished_workers_are_ignored_and_stop_errors_survive(self) -> None:
        log: list = []
        done = _FakeWorker(True, log, "done")
        done.running = False

        def bad_stop():
            raise RuntimeError("stop patladi")

        live = _FakeWorker(True, log, "live")
        still = shutdown_workers([("none", None, lambda: None), ("done", done, done.stop),
                                  ("live", live, bad_stop)], 100)
        self.assertEqual(still, ["live"])
        self.assertNotIn(("stop", "done"), log)


class MainWindowShutdownTests(unittest.TestCase):
    def _fake_window(self):
        log: list = []
        window = mock.MagicMock()
        window.worker = _FakeWorker(True, log, "job")
        window.prepare = _FakeWorker(True, log, "prepare")
        window._dl_thread = _FakeWorker(True, log, "download")
        window._quitting = False
        return window, log

    def test_shutdown_background_stops_job_prepare_and_download(self) -> None:
        from src.gui import main_window

        window, log = self._fake_window()
        main_window.MainWindow._shutdown_background(window)
        stopped = {name for kind, name in log if kind == "stop"}
        self.assertEqual(stopped, {"job", "prepare", "download"})

    def test_force_quit_hides_window_then_waits_then_quits(self) -> None:
        from src.gui import main_window

        window, _ = self._fake_window()
        order: list = []
        window._hide_tray = lambda: order.append("hide_tray")
        window.hide = lambda: order.append("hide")
        window._shutdown_background = lambda: order.append("shutdown")
        window._file_type = lambda: "all"
        fake_app = mock.MagicMock()
        fake_app.quit.side_effect = lambda: order.append("quit")
        with mock.patch.object(main_window.QApplication, "instance", return_value=fake_app):
            main_window.MainWindow.force_quit(window)
        self.assertEqual(order, ["hide_tray", "hide", "shutdown", "quit"])


if __name__ == "__main__":
    unittest.main()
