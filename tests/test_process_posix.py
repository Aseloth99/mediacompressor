"""Madde 4: POSIX surec yonetimi — kendi oturum/grup, SIGTERM -> bekle -> SIGKILL, zombi yok,
ebeveyn olunce yetim kalmama (Linux). Gercek surec testleri yalnizca POSIX'te kosar; sinyal
siralamasi her platformda taklit (fake killpg) ile denetlenir."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import textwrap
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(__file__))
from _support import TempDirTestCase  # noqa: E402

from src.utils import process  # noqa: E402
from src.utils.process import (  # noqa: E402
    kill_all_children, kill_process_tree, popen_hidden, posix_spawn_kwargs, terminate_process_tree,
)

POSIX = os.name != "nt"
SIGTERM, SIGKILL = process._SIGTERM, process._SIGKILL


def _is_gone(pid: int) -> bool:
    """Surec yok ya da zombi (toplanmamis) mu?"""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    except PermissionError:
        return False
    try:
        with open(f"/proc/{pid}/stat", "r", encoding="utf-8", errors="replace") as handle:
            state = handle.read().rsplit(")", 1)[1].split()[0]
        return state in ("Z", "X")
    except OSError:
        return True


def _wait_until(predicate, seconds: float = 5.0, step: float = 0.05) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(step)
    return predicate()


class SpawnKwargsTests(unittest.TestCase):
    def test_windows_gets_nothing_extra(self) -> None:
        self.assertEqual(posix_spawn_kwargs(True, "win32"), {})
        self.assertEqual(posix_spawn_kwargs(False, "win32"), {})

    def test_macos_and_linux_start_a_new_session(self) -> None:
        self.assertEqual(posix_spawn_kwargs(True, "darwin"), {"start_new_session": True})
        self.assertTrue(posix_spawn_kwargs(False, "linux")["start_new_session"])
        self.assertNotIn("preexec_fn", posix_spawn_kwargs(False, "linux"))

    def test_pdeathsig_is_linux_only_and_only_when_requested(self) -> None:
        sentinel = lambda: None  # noqa: E731
        with mock.patch.object(process, "_pdeathsig_preexec", return_value=sentinel):
            self.assertIs(posix_spawn_kwargs(True, "linux")["preexec_fn"], sentinel)
            self.assertNotIn("preexec_fn", posix_spawn_kwargs(True, "darwin"))
            self.assertNotIn("preexec_fn", posix_spawn_kwargs(False, "linux"))
        with mock.patch.object(process, "_pdeathsig_preexec", return_value=None):
            self.assertNotIn("preexec_fn", posix_spawn_kwargs(True, "linux"))

    def test_popen_hidden_applies_the_host_platform_rules(self) -> None:
        with mock.patch("src.utils.process.subprocess.Popen") as popen:
            popen_hidden(["x"])
        kwargs = popen.call_args.kwargs
        self.assertEqual(kwargs.get("start_new_session", False), POSIX)
        self.assertIs(kwargs["stdin"], subprocess.DEVNULL)  # -nostdin ile birlikte stdin kapali

    def test_caller_can_override_the_session_choice(self) -> None:
        with mock.patch("src.utils.process.subprocess.Popen") as popen:
            popen_hidden(["x"], start_new_session=False)
        self.assertFalse(popen.call_args.kwargs["start_new_session"])


class _GroupProc:
    """Popen benzeri; sahte killpg ile birlikte calisir."""

    def __init__(self, pid: int = 424242, exits_on_term: bool = True, group_survives: bool = False) -> None:
        self.pid = pid
        self.returncode = None
        self.exits_on_term = exits_on_term
        self.group_survives = group_survives  # lider gitse de torun kaldi
        self.group_empty = False
        self.signals: list[int] = []
        self.terminated = self.killed = False

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        if self.returncode is None:
            raise subprocess.TimeoutExpired("x", timeout or 0)
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = -SIGTERM

    def kill(self) -> None:
        self.killed = True
        self.returncode = -SIGKILL

    def killpg(self, pgid: int, sig: int) -> None:
        assert pgid == self.pid
        if sig == 0:
            if self.group_empty or (self.returncode is not None and not self.group_survives):
                raise ProcessLookupError
            return
        self.signals.append(sig)
        if sig == SIGTERM and self.exits_on_term:
            self.returncode = -SIGTERM
        if sig == SIGKILL:
            self.returncode = -SIGKILL
            self.group_empty = True


class SignalOrderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.addCleanup(process._LIVE_GROUPS.clear)

    def _register(self, proc) -> None:
        process._track_group(proc, {"start_new_session": True})

    def _run(self, proc, **kwargs):
        with mock.patch.object(process.os, "killpg", proc.killpg, create=True):
            terminate_process_tree(proc, **kwargs)

    def test_cooperative_process_gets_sigterm_only(self) -> None:
        proc = _GroupProc(exits_on_term=True)
        self._register(proc)
        self._run(proc, grace=2.0)
        self.assertEqual(proc.signals, [SIGTERM])
        self.assertNotIn(proc.pid, process._LIVE_GROUPS)

    def test_sigterm_ignoring_process_is_killed_after_the_grace_period(self) -> None:
        proc = _GroupProc(exits_on_term=False)
        self._register(proc)
        started = time.monotonic()
        self._run(proc, grace=0.3)
        self.assertEqual(proc.signals, [SIGTERM, SIGKILL])
        self.assertGreaterEqual(time.monotonic() - started, 0.25)
        self.assertEqual(proc.returncode, -SIGKILL)

    def test_leftover_group_members_are_killed_when_the_leader_exits_alone(self) -> None:
        proc = _GroupProc(exits_on_term=True, group_survives=True)
        self._register(proc)
        self._run(proc, grace=2.0)
        self.assertEqual(proc.signals, [SIGTERM, SIGKILL])

    def test_unmanaged_process_falls_back_to_terminate_then_kill(self) -> None:
        proc = _GroupProc(exits_on_term=True)  # popen_hidden ile baslatilmadi -> kayitsiz
        with mock.patch.object(process.os, "killpg", proc.killpg, create=True):
            terminate_process_tree(proc, grace=0.2)
        self.assertTrue(proc.terminated)
        self.assertEqual(proc.signals, [])  # asla bir grubu vurmaz (sahte pid'ler guvenli)

    def test_fake_pid_of_a_different_object_is_not_treated_as_managed(self) -> None:
        owner, impostor = _GroupProc(pid=777), _GroupProc(pid=777)
        self._register(owner)
        self.assertIsNone(process._managed_pgid(impostor))
        self.assertEqual(process._managed_pgid(owner), 777)

    def test_kill_process_tree_is_immediate_sigkill_on_the_group(self) -> None:
        proc = _GroupProc()
        self._register(proc)
        with mock.patch.object(process.os, "killpg", proc.killpg, create=True):
            kill_process_tree(proc, wait=True)
        self.assertEqual(proc.signals, [SIGKILL])
        self.assertFalse(proc.killed)  # tek sureci degil grubu vurdu

    def test_kill_process_tree_on_unmanaged_process_uses_kill(self) -> None:
        proc = _GroupProc()
        kill_process_tree(proc)
        self.assertTrue(proc.killed)

    def test_kill_all_children_only_touches_still_running_processes(self) -> None:
        running, finished = _GroupProc(pid=501), _GroupProc(pid=502)
        finished.returncode = 0
        for proc in (running, finished):
            self._register(proc)
        calls: list[tuple[int, int]] = []

        def fake_killpg(pgid, sig):
            calls.append((pgid, sig))
            if pgid == 501 and sig == SIGKILL:
                running.returncode = -SIGKILL

        with mock.patch.object(process.os, "killpg", fake_killpg, create=True):
            kill_all_children()
        self.assertEqual(calls, [(501, SIGKILL)])
        self.assertEqual(process._LIVE_GROUPS, {})

    def test_dead_popen_objects_are_dropped_instead_of_signalled(self) -> None:
        proc = _GroupProc(pid=611)
        self._register(proc)
        del proc  # Popen nesnesi kayboldu: pid baska surece gecmis olabilir
        import gc
        gc.collect()
        with mock.patch.object(process.os, "killpg", create=True) as killpg:
            kill_all_children()
        killpg.assert_not_called()


@unittest.skipUnless(POSIX, "gercek surec grubu testleri POSIX'e ozgu")
class RealProcessGroupTests(TempDirTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.addCleanup(process.kill_all_children)

    def _spawn_tree(self, **kwargs):
        # sh + iki torun (sleep): lider tek surec degil, gercek bir agac.
        proc = popen_hidden(
            ["sh", "-c", "sleep 60 & sleep 60 & wait"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kwargs,
        )
        self.addCleanup(self._close_pipes, proc)
        return proc

    @staticmethod
    def _close_pipes(proc) -> None:
        for pipe in (proc.stdout, proc.stderr):
            if pipe is not None:
                pipe.close()

    def _group_members(self, pgid: int) -> list[int]:
        out = subprocess.run(["ps", "-eo", "pid=,pgid=,stat="], capture_output=True, text=True).stdout
        members = []
        for line in out.splitlines():
            parts = line.split()
            if len(parts) >= 3 and parts[1] == str(pgid) and not parts[2].startswith("Z"):
                members.append(int(parts[0]))
        return members

    def test_child_runs_in_its_own_session_and_group(self) -> None:
        proc = self._spawn_tree()
        try:
            self.assertEqual(os.getpgid(proc.pid), proc.pid)
            self.assertNotEqual(os.getpgid(proc.pid), os.getpgrp())
            self.assertEqual(os.getsid(proc.pid), proc.pid)
            self.assertTrue(_wait_until(lambda: len(self._group_members(proc.pid)) >= 3))
        finally:
            terminate_process_tree(proc, grace=2.0)

    def test_terminate_kills_the_whole_tree_and_leaves_no_zombie(self) -> None:
        proc = self._spawn_tree()
        pgid = proc.pid
        self.assertTrue(_wait_until(lambda: len(self._group_members(pgid)) >= 3))
        members = self._group_members(pgid)
        terminate_process_tree(proc, grace=3.0)
        self.assertIsNotNone(proc.returncode)  # lider toplandi (wait)
        self.assertTrue(_wait_until(lambda: all(_is_gone(pid) for pid in members)), members)
        self.assertEqual(self._group_members(pgid), [])
        with self.assertRaises(ChildProcessError):  # toplanmamis cocuk (zombi) kalmadi
            os.waitpid(pgid, os.WNOHANG)

    def test_sigterm_ignoring_process_is_force_killed(self) -> None:
        code = "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); print('hazir', flush=True); time.sleep(60)"
        proc = popen_hidden([sys.executable, "-c", code], stdout=subprocess.PIPE)
        self.addCleanup(self._close_pipes, proc)
        self.assertEqual(proc.stdout.readline().strip(), b"hazir")
        started = time.monotonic()
        terminate_process_tree(proc, grace=0.5)
        self.assertEqual(proc.returncode, -signal.SIGKILL)
        self.assertLess(time.monotonic() - started, 4.0)

    def test_orphan_grandchild_is_killed_even_if_the_leader_exits_on_sigterm(self) -> None:
        pid_file = self.tmp / "torun.pid"
        script = f"sleep 60 & echo $! > '{pid_file}'; wait"
        proc = popen_hidden(["sh", "-c", script], stdout=subprocess.DEVNULL)
        self.assertTrue(_wait_until(pid_file.exists))
        self.assertTrue(_wait_until(lambda: pid_file.read_text().strip() != ""))
        grandchild = int(pid_file.read_text().strip())
        terminate_process_tree(proc, grace=3.0)
        self.assertTrue(_wait_until(lambda: _is_gone(grandchild)))

    @unittest.skipUnless(sys.platform.startswith("linux"), "PDEATHSIG yalnizca Linux")
    def test_child_dies_when_the_parent_is_sigkilled(self) -> None:
        repo = str(process.__file__).rsplit(os.sep + "src" + os.sep, 1)[0]
        helper = self.tmp / "ebeveyn.py"
        helper.write_text(textwrap.dedent(f"""
            import sys, time
            sys.path.insert(0, {repo!r})
            from src.utils.process import popen_hidden
            child = popen_hidden(["sleep", "60"], kill_on_parent_exit=True)
            print(child.pid, flush=True)
            time.sleep(60)
        """), encoding="utf-8")
        parent = subprocess.Popen(
            [sys.executable, str(helper)], stdout=subprocess.PIPE, stdin=subprocess.DEVNULL,
            env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
        )
        self.addCleanup(self._close_pipes, parent)
        try:
            child_pid = int(parent.stdout.readline().strip())
            self.assertFalse(_is_gone(child_pid))
            parent.kill()  # SIGKILL: atexit/finally calismaz
            parent.wait(10)
            self.assertTrue(_wait_until(lambda: _is_gone(child_pid), seconds=5), "ffmpeg benzeri cocuk yetim kaldi")
        finally:
            if parent.poll() is None:
                parent.kill()
                parent.wait()

    def test_atexit_sweeper_kills_running_children_of_a_normally_exiting_app(self) -> None:
        repo = str(process.__file__).rsplit(os.sep + "src" + os.sep, 1)[0]
        helper = self.tmp / "cikis.py"
        helper.write_text(textwrap.dedent(f"""
            import sys
            sys.path.insert(0, {repo!r})
            from src.utils.process import popen_hidden
            child = popen_hidden(["sleep", "60"])
            print(child.pid, flush=True)
        """), encoding="utf-8")
        parent = subprocess.run(
            [sys.executable, str(helper)], capture_output=True, text=True, timeout=60,
            env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
        )
        self.assertEqual(parent.returncode, 0, parent.stderr)
        child_pid = int(parent.stdout.strip().splitlines()[-1])
        self.assertTrue(_wait_until(lambda: _is_gone(child_pid), seconds=5))


if __name__ == "__main__":
    unittest.main()
