"""Platforma göre subprocess bayrakları, süreç ağacı sonlandırma ve yetim süreç koruması.

Windows: konsol penceresi gizlenir, çocuklar Job Object ile uygulamayla birlikte ölür.
POSIX (Linux/macOS): ffmpeg kendi oturumunda (``start_new_session``) = kendi süreç grubunda
çalışır; iptal SIGTERM -> bekle -> SIGKILL ile TÜM gruba gider ve lider ``wait`` ile toplanır
(zombi kalmaz). Uygulama normal/sinyalle çıkarken atexit canlı grupları öldürür; Linux'ta ayrıca
``PR_SET_PDEATHSIG`` ile uygulama SIGKILL'le ölse bile ffmpeg yetim kalmaz.
"""

from __future__ import annotations

import atexit
import os
import signal
import subprocess
import sys
import threading
import time
import weakref

from .logger import log_error
from .platform_utils import is_linux, is_posix

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000) if os.name == "nt" else 0


def run_flags() -> dict:
    if os.name != "nt":
        return {}
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = subprocess.SW_HIDE
    return {"creationflags": CREATE_NO_WINDOW, "startupinfo": si}


def _apply_common_defaults(kwargs: dict) -> None:
    """Pencere gizleme dışındaki ortak güvenli varsayılanlar."""
    # Konsolsuz (windowed) exe'de stdin geçersiz olabilir; alt süreç girdi beklemesin.
    if "stdin" not in kwargs and "input" not in kwargs:
        kwargs["stdin"] = subprocess.DEVNULL
    # Metin kipinde sistem kod sayfasına (Türkçe Windows'ta cp1254) güvenme: ffmpeg/powershell
    # çıktısındaki çözülemeyen bayt uygulamayı UnicodeDecodeError ile düşürmesin.
    if kwargs.get("text") or kwargs.get("universal_newlines"):
        kwargs.setdefault("encoding", "utf-8")
        kwargs.setdefault("errors", "replace")


def run_hidden(cmd, **kwargs):
    flags = run_flags()
    kwargs.setdefault("capture_output", True)
    kwargs.setdefault("text", True)
    _apply_common_defaults(kwargs)
    if "startupinfo" not in kwargs and "startupinfo" in flags:
        kwargs["startupinfo"] = flags["startupinfo"]
    extra = flags.get("creationflags", 0)
    if extra:
        kwargs["creationflags"] = kwargs.get("creationflags", 0) | extra
    return subprocess.run(cmd, **kwargs)


def popen_hidden(cmd, kill_on_parent_exit: bool = False, **kwargs):
    """Gizli pencereli Popen. ``kill_on_parent_exit``: uygulama çökse/öldürülse bile alt
    süreç (ffmpeg) yetim kalmasın diye Windows'ta Job Object'e, Linux'ta PDEATHSIG'e bağlanır.
    POSIX'te süreç kendi oturumunda başlar ve ``terminate_process_tree`` ile grup olarak biter."""
    flags = run_flags()
    _apply_common_defaults(kwargs)
    if "startupinfo" not in kwargs and "startupinfo" in flags:
        kwargs["startupinfo"] = flags["startupinfo"]
    extra = flags.get("creationflags", 0)
    if extra:
        kwargs["creationflags"] = kwargs.get("creationflags", 0) | extra
    for key, value in posix_spawn_kwargs(kill_on_parent_exit).items():
        kwargs.setdefault(key, value)
    proc = subprocess.Popen(cmd, **kwargs)
    if kill_on_parent_exit:
        kill_with_parent(proc)
    _track_group(proc, kwargs)
    return proc


# --------------------------------------------------------------------------- POSIX süreç grubu
TERMINATE_GRACE = 5.0  # SIGTERM'den sonra SIGKILL'e geçmeden önce beklenecek süre (sn)
_GROUP_POLL = 0.02
_PR_SET_PDEATHSIG = 1  # linux/prctl.h

_SIGTERM = int(signal.SIGTERM)
_SIGKILL = int(getattr(signal, "SIGKILL", 9))  # Windows'ta SIGKILL adı yok; POSIX dalları zaten orada çalışmaz

_GROUP_LOCK = threading.Lock()
_LIVE_GROUPS: "dict[int, weakref.ReferenceType]" = {}  # lider pid -> Popen (zayıf)


def _load_prctl():
    """libc ``prctl`` (yalnızca Linux); yüklenemezse None. Çocukta ctypes yüklemesi yapılmasın
    diye fork ÖNCESİ ebeveynde çözülür."""
    try:
        import ctypes

        libc = ctypes.CDLL(None, use_errno=True)
        prctl = libc.prctl
        prctl.argtypes = [ctypes.c_int, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong]
        prctl.restype = ctypes.c_int
        return prctl
    except Exception:  # noqa: BLE001 - libc yok/ctypes yok: koruma olmadan devam
        return None


def _pdeathsig_preexec():
    prctl = _load_prctl()
    if prctl is None:
        return None
    sigkill = _SIGKILL

    def _preexec() -> None:
        # Ebeveyn (bu süreç/iş parçacığı) ölürse çekirdek çocuğa SIGKILL yollar.
        prctl(_PR_SET_PDEATHSIG, sigkill, 0, 0, 0)

    return _preexec


def posix_spawn_kwargs(kill_on_parent_exit: bool = False, platform: str | None = None) -> dict:
    """``subprocess.Popen`` için POSIX'e özgü ek argümanlar (Windows'ta boş).

    * ``start_new_session``: süreç kendi oturum/süreç grubunda -> iptalde grup halinde öldürülür,
      terminalin Ctrl+C'si veya bizim grubumuza giden sinyaller ffmpeg'e karışmaz.
    * Linux + ``kill_on_parent_exit``: ``preexec_fn`` ile PR_SET_PDEATHSIG(SIGKILL).
    """
    if not is_posix(platform):
        return {}
    extra: dict = {"start_new_session": True}
    if kill_on_parent_exit and is_linux(platform):
        preexec = _pdeathsig_preexec()
        if preexec is not None:
            extra["preexec_fn"] = preexec
    return extra


def _track_group(proc, popen_kwargs: dict) -> None:
    """Kendi oturumunda başlatılan süreci atexit temizliği ve grup sonlandırma için kaydet."""
    pid = getattr(proc, "pid", None)
    if not popen_kwargs.get("start_new_session") or not isinstance(pid, int) or pid <= 1:
        return
    try:
        ref = weakref.ref(proc)
    except TypeError:
        return
    with _GROUP_LOCK:
        for stale in [key for key, value in _LIVE_GROUPS.items() if value() is None]:
            del _LIVE_GROUPS[stale]  # Popen nesnesi çoktan atılmış: pid yeniden kullanılmış olabilir
        _LIVE_GROUPS[pid] = ref


def _managed_pgid(proc) -> "int | None":
    """``popen_hidden`` ile kendi oturumunda başlatılmış ``proc``'un grup kimliği; yoksa None."""
    pid = getattr(proc, "pid", None)
    if not isinstance(pid, int) or pid <= 1:
        return None
    with _GROUP_LOCK:
        ref = _LIVE_GROUPS.get(pid)
    return pid if ref is not None and ref() is proc else None


def _forget_group(pid: int) -> None:
    with _GROUP_LOCK:
        _LIVE_GROUPS.pop(pid, None)


def _signal_group(pgid: int, sig: int) -> bool:
    """Gruba sinyal yolla; grup yok/bizim değilse False."""
    try:
        os.killpg(pgid, sig)
        return True
    except (ProcessLookupError, PermissionError):
        return False
    except OSError as exc:  # noqa: BLE001
        log_error(f"Süreç grubuna sinyal gönderilemedi ({pgid})", exc)
        return False


def _group_alive(pgid: int) -> bool:
    """Grupta (zombi lider dahil) hâlâ üye var mı?"""
    try:
        os.killpg(pgid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False
    except OSError:
        return False


def _terminate_single(proc, grace: float) -> None:
    """Grup yönetimi olmayan süreç (Windows veya dışarıdan verilen): terminate -> kill."""
    try:
        proc.terminate()
        try:
            proc.wait(timeout=grace)
            return
        except Exception:  # noqa: BLE001
            pass
        proc.kill()
        proc.wait(timeout=5)
    except Exception:  # noqa: BLE001
        pass


def terminate_process_tree(proc, grace: float = TERMINATE_GRACE) -> None:
    """Süreci (ve POSIX'te tüm grubunu) sonlandır: SIGTERM -> ``grace`` sn bekle -> SIGKILL.

    Dönmeden önce lider ``wait`` ile toplanır (zombi kalmaz). Windows'ta ve grup kaydı olmayan
    süreçlerde eski davranış: ``terminate`` -> bekle -> ``kill``.
    """
    pgid = _managed_pgid(proc)
    if pgid is None:
        _terminate_single(proc, grace)
        return
    try:
        _signal_group(pgid, _SIGTERM)
        deadline = time.monotonic() + max(0.0, grace)
        while proc.poll() is None:  # poll lideri toplar
            if time.monotonic() >= deadline:
                _signal_group(pgid, _SIGKILL)  # SIGTERM'i yok sayan lider: tüm gruba SIGKILL
                break
            time.sleep(_GROUP_POLL)
        if proc.poll() is not None and _group_alive(pgid):
            _signal_group(pgid, _SIGKILL)  # lider çıktı ama torunlar kaldı
        try:
            proc.wait(timeout=5)
        except Exception:  # noqa: BLE001
            pass
    finally:
        _forget_group(pgid)


def kill_process_tree(proc, wait: bool = False) -> None:
    """Hemen öldür (SIGKILL; POSIX'te tüm grup). ``wait``: lideri topla (zombi bırakma)."""
    pgid = _managed_pgid(proc)
    try:
        if pgid is None:
            proc.kill()
        else:
            _signal_group(pgid, _SIGKILL)
        if wait:
            proc.wait(timeout=5)
    except Exception:  # noqa: BLE001
        pass
    finally:
        if pgid is not None and wait:
            _forget_group(pgid)


def kill_all_children() -> None:
    """Hâlâ çalışan, kendi grubunda başlatılmış tüm süreçleri öldür (atexit / sinyal kapanışı).

    Yalnızca henüz toplanmamış (``poll() is None``) süreçlere dokunulur: lider toplandıysa pid
    başka bir sürece verilmiş olabilir ve yanlış gruba sinyal gitmemelidir.
    """
    with _GROUP_LOCK:
        items = list(_LIVE_GROUPS.items())
        _LIVE_GROUPS.clear()
    for pid, ref in items:
        proc = ref()
        try:
            if proc is None or proc.poll() is not None:
                continue
        except Exception:  # noqa: BLE001
            continue
        _signal_group(pid, _SIGKILL)
        try:
            proc.wait(timeout=2)
        except Exception:  # noqa: BLE001
            pass


if is_posix():
    atexit.register(kill_all_children)


# --------------------------------------------------------------------------- Job Object
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS = 9
PROCESS_SET_QUOTA = 0x0100
PROCESS_TERMINATE = 0x0001


class _Win32JobApi:
    """kernel32 Job Object çağrıları (yalnızca win32'de oluşturulur)."""

    def __init__(self) -> None:
        import ctypes
        from ctypes import wintypes

        class BasicLimit(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_int64),
                ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class IoCounters(ctypes.Structure):
            _fields_ = [
                (name, ctypes.c_uint64) for name in (
                    "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                    "ReadTransferCount", "WriteTransferCount", "OtherTransferCount",
                )
            ]

        class ExtendedLimit(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", BasicLimit),
                ("IoInfo", IoCounters),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        self._ctypes = ctypes
        self._ExtendedLimit = ExtendedLimit
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        k32.CreateJobObjectW.restype = wintypes.HANDLE
        k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        k32.SetInformationJobObject.restype = wintypes.BOOL
        k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        k32.AssignProcessToJobObject.restype = wintypes.BOOL
        k32.CloseHandle.argtypes = [wintypes.HANDLE]
        k32.CloseHandle.restype = wintypes.BOOL
        self._k32 = k32

    def create_kill_on_close_job(self):
        job = self._k32.CreateJobObjectW(None, None)
        if not job:
            return None
        info = self._ExtendedLimit()
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        ok = self._k32.SetInformationJobObject(
            job, JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS,
            self._ctypes.byref(info), self._ctypes.sizeof(info),
        )
        if not ok:
            self._k32.CloseHandle(job)
            return None
        return job

    def assign_pid(self, job, pid: int) -> bool:
        handle = self._k32.OpenProcess(PROCESS_SET_QUOTA | PROCESS_TERMINATE, False, int(pid))
        if not handle:
            return False
        try:
            return bool(self._k32.AssignProcessToJobObject(job, handle))
        finally:
            self._k32.CloseHandle(handle)

    def close(self, job) -> None:
        self._k32.CloseHandle(job)


class KillOnCloseJob:
    """Eklenen süreçleri, bu nesne (veya onu tutan süreç) kapanınca öldüren Job Object.

    Windows dışında ya da API kurulamazsa sessizce etkisizdir (``assign`` False döner);
    uygulama bu durumda eskisi gibi çalışır.
    """

    def __init__(self, api=None, platform: str | None = None) -> None:
        self._api = api
        self._platform = platform or sys.platform
        self._job = None
        self._unavailable = False
        self._lock = threading.Lock()

    def _ensure(self) -> bool:
        if self._job is not None:
            return True
        if self._unavailable:
            return False
        with self._lock:
            if self._job is not None:
                return True
            try:
                api = self._api
                if api is None:
                    if self._platform != "win32":
                        self._unavailable = True
                        return False
                    api = _Win32JobApi()
                job = api.create_kill_on_close_job()
                if not job:
                    self._unavailable = True
                    return False
                self._api, self._job = api, job
                return True
            except Exception as exc:  # noqa: BLE001 - ctypes/OS hatası: güvenli düşüş
                log_error("Job Object kurulamadı (yetim süreç koruması yok)", exc)
                self._unavailable = True
                return False

    def assign(self, proc) -> bool:
        """``proc`` (Popen veya pid) işi kapanınca öldürülecek şekilde job'a eklenir."""
        if not self._ensure():
            return False
        pid = getattr(proc, "pid", proc)
        try:
            return bool(self._api.assign_pid(self._job, pid))
        except Exception as exc:  # noqa: BLE001
            log_error("Süreç Job Object'e eklenemedi", exc)
            return False

    def close(self) -> None:
        """Job'u kapatır: içindeki tüm süreçler öldürülür."""
        with self._lock:
            job, self._job = self._job, None
            self._unavailable = True
        if job is not None and self._api is not None:
            try:
                self._api.close(job)
            except Exception:  # noqa: BLE001
                pass


_DEFAULT_JOB = KillOnCloseJob()


def kill_with_parent(proc) -> bool:
    """Alt süreci uygulamayla birlikte ölecek şekilde işaretle (yalnızca Windows)."""
    return _DEFAULT_JOB.assign(proc)
