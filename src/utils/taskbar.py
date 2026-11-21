"""Windows görev çubuğu düğmesindeki ilerleme (ITaskbarList3) — yalnızca ctypes, ek paket yok.

Görev çubuğu simgesi genel ilerleme çubuğunu yansıtır: iş sürerken yeşil dolgu, durdurulurken sarı (duraklatıldı),
iş hatayla bitince kırmızı. Windows dışında (ve COM nesnesi oluşturulamazsa) her çağrı sessizce hiçbir şey yapmaz;
hiçbir yol istisna fırlatmaz. GUI iş parçacığından çağrılmalıdır (Qt bu iş parçacığında COM'u STA olarak açar).
"""

from __future__ import annotations

import inspect
import sys
import weakref
from typing import Callable

# TBPFLAG
NO_PROGRESS = 0x0
INDETERMINATE = 0x1
NORMAL = 0x2
ERROR = 0x4
PAUSED = 0x8

_STEPS = 1000  # SetProgressValue tam sayı ister: binde bir adım

# ITaskbarList3 vtable sırası: IUnknown(0-2) · HrInit 3 · AddTab 4 · DeleteTab 5 · ActivateTab 6 · SetActiveAlt 7 ·
# MarkFullscreenWindow 8 · SetProgressValue 9 · SetProgressState 10
_HRINIT, _SET_VALUE, _SET_STATE, _RELEASE = 3, 9, 10, 2
_CLSID_TASKBARLIST = "{56FDF344-FD6D-11d0-958A-006097C9A090}"
_IID_ITASKBARLIST3 = "{EA1AFB91-9E28-4B86-90E9-9E9F8A5EEFAF}"
_CO_E_NOTINITIALIZED = -2147221008  # 0x800401F0


class _ComTaskbar:
    """ITaskbarList3'ün ham vtable üzerinden en küçük sarmalayıcısı."""

    def __init__(self):
        import ctypes
        from ctypes import wintypes

        self._ctypes = ctypes
        ole32 = ctypes.windll.ole32

        class GUID(ctypes.Structure):
            _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD),
                        ("Data4", ctypes.c_ubyte * 8)]

        def guid(text: str) -> GUID:
            g = GUID()
            if ole32.CLSIDFromString(ctypes.c_wchar_p(text), ctypes.byref(g)) != 0:
                raise OSError("CLSIDFromString")
            return g

        clsid, iid = guid(_CLSID_TASKBARLIST), guid(_IID_ITASKBARLIST3)
        ptr = ctypes.c_void_p()
        create = ole32.CoCreateInstance
        create.restype = ctypes.c_long
        hr = create(ctypes.byref(clsid), None, 1, ctypes.byref(iid), ctypes.byref(ptr))  # CLSCTX_INPROC_SERVER
        if hr == _CO_E_NOTINITIALIZED:
            ole32.CoInitialize(None)
            hr = create(ctypes.byref(clsid), None, 1, ctypes.byref(iid), ctypes.byref(ptr))
        if hr != 0 or not ptr.value:
            raise OSError(f"CoCreateInstance(TaskbarList) 0x{hr & 0xFFFFFFFF:08X}")
        self._ptr = ptr
        vtable = ctypes.cast(ctypes.cast(ptr, ctypes.POINTER(ctypes.c_void_p))[0], ctypes.POINTER(ctypes.c_void_p))
        hresult = ctypes.c_long
        self._hrinit = ctypes.WINFUNCTYPE(hresult, ctypes.c_void_p)(vtable[_HRINIT])
        self._set_value = ctypes.WINFUNCTYPE(hresult, ctypes.c_void_p, wintypes.HWND, ctypes.c_ulonglong,
                                             ctypes.c_ulonglong)(vtable[_SET_VALUE])
        self._set_state = ctypes.WINFUNCTYPE(hresult, ctypes.c_void_p, wintypes.HWND, ctypes.c_int)(vtable[_SET_STATE])
        self._release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vtable[_RELEASE])
        if self._hrinit(self._ptr) != 0:
            self.release()
            raise OSError("ITaskbarList3.HrInit")

    def set_value(self, hwnd: int, done: int, total: int) -> None:
        self._set_value(self._ptr, hwnd, done, total)

    def set_state(self, hwnd: int, state: int) -> None:
        self._set_state(self._ptr, hwnd, state)

    def release(self) -> None:
        if getattr(self, "_ptr", None) is not None and self._ptr.value:
            try:
                self._release(self._ptr)
            except Exception:
                pass
            self._ptr = None


class TaskbarProgress:
    """Bir pencerenin görev çubuğu ilerlemesi. `hwnd_provider()` pencere tutamacını verir (0/None: henüz yok).

    `backend_factory` testler içindir (set_value/set_state yöntemli bir nesne döndürür). Durum değişmedikçe COM'a
    tekrar gidilmez; aynı değer art arda verilirse çağrı yapılmaz.
    """

    def __init__(self, hwnd_provider: Callable[[], int | None], *, enabled: bool | None = None,
                 backend_factory: Callable[[], object] | None = None):
        # Pencerenin bağlı yöntemi zayıf tutulur: pencere → TaskbarProgress → pencere döngüsü olmasın.
        self._hwnd_provider = weakref.WeakMethod(hwnd_provider) if inspect.ismethod(hwnd_provider)             else (lambda: hwnd_provider)
        self._enabled = (sys.platform == "win32") if enabled is None else bool(enabled)
        self._factory = backend_factory or _ComTaskbar
        self._backend = None
        self._failed = False
        self._state = NO_PROGRESS
        self._value = -1

    @property
    def state(self) -> int:
        return self._state

    @property
    def value(self) -> int:
        """Son verilen değer (binde), henüz yoksa -1."""
        return self._value

    def _target(self):
        if not self._enabled or self._failed:
            return None, 0
        try:
            provider = self._hwnd_provider()
            hwnd = int(provider() or 0) if provider is not None else 0
        except Exception:
            hwnd = 0
        if not hwnd:
            return None, 0
        if self._backend is None:
            try:
                self._backend = self._factory()
            except Exception:
                self._failed = True  # COM yok (eski Windows, kısıtlı oturum): bir daha denenmez
                return None, 0
        return self._backend, hwnd

    def set_state(self, state: int) -> None:
        if state == self._state:
            return
        backend, hwnd = self._target()
        self._state = state
        if state == NO_PROGRESS:
            self._value = -1
        if backend is None:
            return
        try:
            backend.set_state(hwnd, state)
        except Exception:
            pass

    def set_fraction(self, fraction: float, state: int | None = None) -> None:
        """İlerlemeyi (0..1) ve isteğe bağlı durumu (NORMAL / PAUSED / ERROR) verir."""
        if state is not None:
            self.set_state(state)
        elif self._state in (NO_PROGRESS, INDETERMINATE):
            self.set_state(NORMAL)
        try:
            value = int(round(max(0.0, min(1.0, float(fraction))) * _STEPS))
        except (TypeError, ValueError):
            return
        if value == self._value:
            return
        backend, hwnd = self._target()
        self._value = value
        if backend is None:
            return
        try:
            backend.set_value(hwnd, value, _STEPS)
        except Exception:
            pass

    def clear(self) -> None:
        self.set_state(NO_PROGRESS)

    def close(self) -> None:
        backend, self._backend = self._backend, None
        release = getattr(backend, "release", None)
        if callable(release):
            release()
