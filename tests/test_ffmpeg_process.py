"""Madde 3: ffmpeg surec yonetimi (-nostdin, anlik iptal, Job Object, kodlama, mutlak yol)."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(__file__))
from _support import AUTO_BITRATE, TempDirTestCase  # noqa: E402

from src.core import ffmpeg_manager  # noqa: E402
from src.core.atomic_output import CANCELLED  # noqa: E402
from src.core.ffmpeg_manager import FFmpegManager, ffmpeg_name, which_no_cwd  # noqa: E402
from src.core.video_compressor import VideoCompressor, build_frame_extract_cmd  # noqa: E402
from src.utils import process  # noqa: E402
from src.utils.process import KillOnCloseJob, popen_hidden, run_hidden  # noqa: E402

PY = sys.executable


class CommandTests(unittest.TestCase):
    def test_build_cmd_has_nostdin_and_output_last(self) -> None:
        vc = VideoCompressor(r"C:\tools\ffmpeg.exe")
        cmd = vc.build_cmd("in.mp4", "out.mp4", "cpu", "h264", AUTO_BITRATE, 24, "slow", "128k", 1920)
        self.assertEqual(cmd[0], r"C:\tools\ffmpeg.exe")
        self.assertIn("-nostdin", cmd)
        self.assertEqual(cmd[-1], "out.mp4")
        self.assertLess(cmd.index("-nostdin"), cmd.index("-i"))

    def test_frame_extract_cmd_has_nostdin(self) -> None:
        cmd = build_frame_extract_cmd(r"C:\tools\ffmpeg.exe", "film.mp4", 3.14159)
        self.assertIn("-nostdin", cmd)
        self.assertEqual(cmd[0], r"C:\tools\ffmpeg.exe")
        self.assertEqual(cmd[cmd.index("-ss") + 1], "3.14")
        self.assertEqual(cmd[-1], "-")

    def test_duration_fallback_probe_uses_nostdin(self) -> None:
        vc = VideoCompressor("ffmpeg-sahte")  # ffprobe yok -> ffmpeg -i yedegi
        with mock.patch("src.core.video_compressor.run_hidden") as run:
            run.return_value = mock.Mock(stderr="Duration: 00:01:30.50, start", stdout="")
            self.assertAlmostEqual(vc.duration("x.mp4"), 90.5)
        self.assertIn("-nostdin", run.call_args.args[0])


class _StalledStderr:
    """ffmpeg sessiz kaldi: satir gelmiyor (readline bloklar)."""

    def __init__(self, release: threading.Event):
        self.release = release

    def readline(self) -> str:
        self.release.wait(5)
        return ""

    def __iter__(self):
        return self

    def __next__(self) -> str:
        line = self.readline()
        if not line:
            raise StopIteration
        return line

    def close(self) -> None:
        pass


class _FakeProc:
    def __init__(self, stderr_lines=None, returncode_after=None):
        self.release = threading.Event()
        self.returncode = None
        self.terminated = False
        self.killed = False
        if stderr_lines is None:
            self.stderr = _StalledStderr(self.release)
        else:
            self.stderr = iter(stderr_lines)
            self.returncode = returncode_after
        self.pid = 4242

    def poll(self):
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = 1
        self.release.set()

    def kill(self) -> None:
        self.killed = True
        self.returncode = 1
        self.release.set()

    def wait(self, timeout=None):
        if self.returncode is None:
            raise subprocess.TimeoutExpired("ffmpeg", timeout or 0)
        return self.returncode


class RunLoopTests(unittest.TestCase):
    def setUp(self) -> None:
        self.vc = VideoCompressor("ffmpeg-sahte")

    def test_cancel_is_immediate_even_when_ffmpeg_is_silent(self) -> None:
        proc = _FakeProc()
        cancel = threading.Event()
        result: dict = {}

        def target() -> None:
            with mock.patch("src.core.video_compressor.popen_hidden", return_value=proc):
                result["value"] = self.vc._run(["ffmpeg", "-i", "x"], cancel, 10.0, None)
                result["at"] = time.monotonic()

        thread = threading.Thread(target=target)
        thread.start()
        time.sleep(0.3)  # ffmpeg stderr'de bekliyor
        t0 = time.monotonic()
        cancel.set()
        thread.join(8)
        self.assertEqual(result.get("value"), CANCELLED)
        # Eski kod readline'da takilip yaklasik 5 sn sonra fark ederdi.
        self.assertLess(result["at"] - t0, 1.5)
        self.assertTrue(proc.terminated)

    def test_popen_gets_devnull_stdin_and_job_flag(self) -> None:
        proc = _FakeProc(stderr_lines=["frame=1 time=00:00:01.00\n"], returncode_after=0)
        with mock.patch("src.core.video_compressor.popen_hidden", return_value=proc) as popen:
            self.vc._run(["ffmpeg"], None, 2.0, None)
        kwargs = popen.call_args.kwargs
        self.assertIs(kwargs["stdin"], subprocess.DEVNULL)
        self.assertTrue(kwargs["kill_on_parent_exit"])

    def test_progress_and_success(self) -> None:
        lines = ["x\n", "frame=10 time=00:00:05.00 bitrate=1\n", "time=00:00:10.00\n"]
        proc = _FakeProc(stderr_lines=lines, returncode_after=0)
        ratios: list[float] = []
        with mock.patch("src.core.video_compressor.popen_hidden", return_value=proc):
            result = self.vc._run(["ffmpeg"], None, 10.0, ratios.append)
        self.assertEqual(result, "ok")
        self.assertEqual(ratios, [0.5, 1.0, 1.0])

    def test_failure_returns_last_nonempty_stderr_line(self) -> None:
        proc = _FakeProc(stderr_lines=["boom\n", "Conversion failed!\n", "\n"], returncode_after=1)
        with mock.patch("src.core.video_compressor.popen_hidden", return_value=proc):
            self.assertEqual(self.vc._run(["ffmpeg"], None, 0, None), "Conversion failed!")

    def test_start_failure_message(self) -> None:
        with mock.patch("src.core.video_compressor.popen_hidden", side_effect=OSError("yok")):
            self.assertTrue(self.vc._run(["ffmpeg"], None, 0, None).startswith("başlatılamadı"))


class EncodingTests(unittest.TestCase):
    def test_run_hidden_text_mode_is_utf8_replace_with_devnull_stdin(self) -> None:
        with mock.patch("src.utils.process.subprocess.run") as run:
            run_hidden(["x"])
        kwargs = run.call_args.kwargs
        self.assertEqual(kwargs["encoding"], "utf-8")
        self.assertEqual(kwargs["errors"], "replace")
        self.assertIs(kwargs["stdin"], subprocess.DEVNULL)

    def test_binary_mode_gets_no_encoding(self) -> None:
        with mock.patch("src.utils.process.subprocess.run") as run:
            run_hidden(["x"], text=False)
        self.assertNotIn("encoding", run.call_args.kwargs)

    def test_undecodable_bytes_do_not_crash(self) -> None:
        # 0x81/0x8d/0x8f/0x90/0x9d hem utf-8'de gecersiz hem cp125x'te tanimsizdir.
        code = "import sys; sys.stdout.buffer.write(b'ab\\x81\\x8d\\x8f\\x90\\x9dcd')"
        result = run_hidden([PY, "-c", code], timeout=30)
        self.assertEqual(result.returncode, 0)
        self.assertTrue(result.stdout.startswith("ab"))
        self.assertIn("\ufffd", result.stdout)

    def test_popen_text_mode_defaults(self) -> None:
        with mock.patch("src.utils.process.subprocess.Popen") as popen:
            popen_hidden(["x"], universal_newlines=True)
        kwargs = popen.call_args.kwargs
        self.assertEqual((kwargs["encoding"], kwargs["errors"]), ("utf-8", "replace"))
        self.assertIs(kwargs["stdin"], subprocess.DEVNULL)


class _FakeJobApi:
    def __init__(self, create_ok=True, assign_ok=True, raise_on_assign=False):
        self.calls: list = []
        self.create_ok, self.assign_ok, self.raise_on_assign = create_ok, assign_ok, raise_on_assign

    def create_kill_on_close_job(self):
        self.calls.append("create")
        return "JOB" if self.create_ok else None

    def assign_pid(self, job, pid):
        self.calls.append(("assign", job, pid))
        if self.raise_on_assign:
            raise OSError("erisim reddedildi")
        return self.assign_ok

    def close(self, job):
        self.calls.append(("close", job))


class JobObjectTests(unittest.TestCase):
    def test_non_windows_is_a_safe_noop(self) -> None:
        job = KillOnCloseJob(platform="linux")
        self.assertFalse(job.assign(4242))
        self.assertFalse(job.assign(mock.Mock(pid=1)))

    def test_job_created_once_and_pid_assigned(self) -> None:
        api = _FakeJobApi()
        job = KillOnCloseJob(api=api)
        proc = mock.Mock(pid=77)
        self.assertTrue(job.assign(proc))
        self.assertTrue(job.assign(88))
        self.assertEqual(api.calls, ["create", ("assign", "JOB", 77), ("assign", "JOB", 88)])
        job.close()
        self.assertEqual(api.calls[-1], ("close", "JOB"))

    def test_api_failures_degrade_gracefully(self) -> None:
        self.assertFalse(KillOnCloseJob(api=_FakeJobApi(create_ok=False)).assign(1))
        self.assertFalse(KillOnCloseJob(api=_FakeJobApi(assign_ok=False)).assign(1))
        self.assertFalse(KillOnCloseJob(api=_FakeJobApi(raise_on_assign=True)).assign(1))

    def test_popen_hidden_assigns_to_default_job_only_when_asked(self) -> None:
        with mock.patch("src.utils.process.subprocess.Popen") as popen, \
                mock.patch.object(process, "kill_with_parent") as kill:
            popen_hidden(["x"])
            kill.assert_not_called()
            popen_hidden(["x"], kill_on_parent_exit=True)
            kill.assert_called_once_with(popen.return_value)

    @unittest.skipUnless(sys.platform == "win32", "Job Object yalnizca Windows")
    def test_real_job_kills_child_when_closed(self) -> None:
        child = subprocess.Popen([PY, "-c", "import time; time.sleep(60)"], stdin=subprocess.DEVNULL)
        job = KillOnCloseJob()
        try:
            self.assertTrue(job.assign(child))
            self.assertIsNone(child.poll())
            job.close()  # uygulama olurse isletim sistemi de ayni sekilde kapatir
            self.assertIsNotNone(self._wait_exit(child, 10))
        finally:
            if child.poll() is None:
                child.kill()
            child.wait()

    @staticmethod
    def _wait_exit(child, seconds):
        deadline = time.time() + seconds
        while time.time() < deadline:
            code = child.poll()
            if code is not None:
                return code
            time.sleep(0.05)
        return None


class AbsoluteFfmpegPathTests(TempDirTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.bin = self.tmp / "bin"
        self.cwd = self.tmp / "cwd"
        self.bin.mkdir()
        self.cwd.mkdir()
        self.old_cwd = os.getcwd()
        os.chdir(self.cwd)
        self.addCleanup(os.chdir, self.old_cwd)

    def _fake_exe(self, folder) -> str:
        path = folder / ffmpeg_name()
        path.write_bytes(b"MZ")
        os.chmod(path, 0o755)
        return str(path)

    def test_finds_absolute_path_on_path(self) -> None:
        exe = self._fake_exe(self.bin)
        with mock.patch.dict(os.environ, {"PATH": str(self.bin)}):
            self.assertEqual(which_no_cwd(ffmpeg_name()), os.path.abspath(exe))

    def test_current_directory_and_relative_entries_are_ignored(self) -> None:
        self._fake_exe(self.cwd)  # yalnizca CWD'de var
        with mock.patch.dict(os.environ, {"PATH": os.pathsep.join(["", ".", "bin_goreli"])}):
            self.assertIsNone(which_no_cwd(ffmpeg_name()))

    def test_find_never_returns_cwd_or_relative_path(self) -> None:
        self._fake_exe(self.cwd)
        manager = FFmpegManager()
        with mock.patch.dict(os.environ, {"PATH": str(self.tmp / "bos")}), \
                mock.patch.object(FFmpegManager, "_candidates", return_value=[]):
            self.assertIsNone(manager.find())
        self.assertIsNone(manager.ffmpeg_path)

    def test_find_returns_absolute_paths(self) -> None:
        exe = self._fake_exe(self.bin)
        manager = FFmpegManager()
        with mock.patch.dict(os.environ, {"PATH": str(self.bin)}):
            found = manager.find()
        self.assertEqual(found, os.path.abspath(exe))
        self.assertTrue(os.path.isabs(manager.ffmpeg_path))

    def test_candidate_paths_are_made_absolute(self) -> None:
        self._fake_exe(self.cwd)
        rel = (ffmpeg_name(), "ffprobe-yok")
        manager = FFmpegManager()
        with mock.patch.dict(os.environ, {"PATH": ""}), \
                mock.patch.object(FFmpegManager, "_candidates", return_value=[rel]):
            found = manager.find()
        self.assertTrue(os.path.isabs(found))
        self.assertIsNone(manager.ffprobe_path)


class PreviewWorkerTests(unittest.TestCase):
    def test_missing_ffmpeg_fails_instead_of_running_relative_name(self) -> None:
        from src.gui import preview_dialog

        worker = preview_dialog._ExtractFrameWorker(1, "film.mp4", 2.0)
        failures: list = []
        worker.frame_failed.connect(lambda req, msg: failures.append((req, msg)))
        with mock.patch.object(preview_dialog.FFmpegManager, "find", return_value=None), \
                mock.patch.object(preview_dialog, "popen_hidden") as popen:
            worker.run()
        popen.assert_not_called()
        self.assertEqual(failures, [(1, "FFmpeg bulunamadı")])

    def test_worker_uses_resolved_path_nostdin_and_job_flag(self) -> None:
        from src.gui import preview_dialog

        worker = preview_dialog._ExtractFrameWorker(2, "film.mp4", 2.0)
        frames: list = []
        worker.frame_ready.connect(lambda req, data, sec: frames.append((req, data)))
        fake = mock.Mock()
        fake.communicate.return_value = (b"PNGDATA", None)
        resolved = os.path.abspath("C:/tools/ffmpeg.exe")
        with mock.patch.object(preview_dialog.FFmpegManager, "find", return_value=resolved), \
                mock.patch.object(preview_dialog, "popen_hidden", return_value=fake) as popen:
            worker.run()
        cmd = popen.call_args.args[0]
        self.assertEqual(cmd[0], resolved)
        self.assertIn("-nostdin", cmd)
        self.assertTrue(popen.call_args.kwargs["kill_on_parent_exit"])
        self.assertEqual(frames, [(2, b"PNGDATA")])


if __name__ == "__main__":
    unittest.main()
