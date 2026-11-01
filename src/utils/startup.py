"""Açılışta Başlat: Windows (HKCU Run), macOS (LaunchAgent) ve Linux (XDG autostart)."""

from __future__ import annotations

import os
import sys
from os.path import abspath

from ..core.app_info import APP_ID, APP_NAME, LAUNCH_AGENT_LABEL, LEGACY_APP_ID
from . import autostart_unix
from .helpers import get_application_path
from .logger import log_error, log_info


def _windows_pythonw() -> str:
    """python.exe konsol açar; başlangıç için pythonw.exe kullan."""
    exe = os.path.abspath(sys.executable)
    folder, name = os.path.split(exe)
    if name.lower() == "python.exe":
        pythonw = os.path.join(folder, "pythonw.exe")
        if os.path.isfile(pythonw):
            return pythonw
    return exe


def _executable_command(minimized: bool = False) -> str:
    if getattr(sys, "frozen", False):
        path = sys.executable
        cmd = f'"{path}"'
    else:
        root = get_application_path()
        script = os.path.join(root, "main.py")
        if not os.path.isfile(script):
            script = abspath(sys.argv[0])
        launcher = _windows_pythonw() if sys.platform == "win32" else sys.executable
        cmd = f'"{launcher}" "{script}"'
    if minimized:
        cmd = f"{cmd} --minimized"
    return cmd


# Eski sürümlerin bıraktığı dosyalar: com.mediacompressor.plist ve MediaCompressor.desktop (yeni adla yeniden yazılır, eskisi silinir)
_LEGACY = {"legacy_plist_labels": (LAUNCH_AGENT_LABEL,), "legacy_desktop_names": (APP_ID,)}


def _unix_launch() -> tuple[str, list[str]]:
    """macOS/Linux: (çalıştırılacak dosya, bağımsız değişkenler). Paketlenmişse yalnızca exe, değilse yorumlayıcı + betik."""
    if getattr(sys, "frozen", False):
        return sys.executable, []
    return sys.executable, [abspath(sys.argv[0])]


def add_to_startup(minimized: bool = False) -> bool:
    if sys.platform == "win32":
        return _win_add(minimized)
    if sys.platform == "darwin" or sys.platform.startswith("linux"):
        return _unix_add(minimized)
    return False


def remove_from_startup() -> bool:
    if sys.platform == "win32":
        return _win_remove()
    if sys.platform == "darwin" or sys.platform.startswith("linux"):
        return _unix_remove()
    return False


def is_in_startup() -> bool:
    if sys.platform == "win32":
        return _win_is_in()
    if sys.platform == "darwin" or sys.platform.startswith("linux"):
        return autostart_unix.is_enabled(APP_ID, **_LEGACY)
    return False


def update_startup_path_if_needed(minimized: bool = False) -> None:
    if not is_in_startup():
        return
    add_to_startup(minimized=minimized)


def _win_add(minimized: bool) -> bool:
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0,
            winreg.KEY_SET_VALUE,
        )
        winreg.SetValueEx(key, APP_ID, 0, winreg.REG_SZ, _executable_command(minimized))
        _win_delete_value(winreg, key, LEGACY_APP_ID)  # eski adla kayıt yeni adla yeniden yazıldı
        winreg.CloseKey(key)
        log_info("Windows başlangıcına eklendi")
        return True
    except Exception as exc:
        log_error("Başlangıç eklenemedi", exc)
        return False


def _win_remove() -> bool:
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0,
            winreg.KEY_SET_VALUE,
        )
        for name in (APP_ID, LEGACY_APP_ID):
            _win_delete_value(winreg, key, name)
        winreg.CloseKey(key)
        return True
    except Exception as exc:
        log_error("Başlangıç kaldırılamadı", exc)
        return False


def _win_delete_value(winreg, key, name: str) -> None:
    try:
        winreg.DeleteValue(key, name)
    except FileNotFoundError:
        pass


def _win_is_in() -> bool:
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0,
            winreg.KEY_READ,
        )
        try:
            # Eski adla ("MedyaSikistirici") kalan kayıt da bizimdir: açılışta yeni adla yeniden yazılır.
            for name in (APP_ID, LEGACY_APP_ID):
                try:
                    winreg.QueryValueEx(key, name)
                    return True
                except FileNotFoundError:
                    continue
            return False
        finally:
            winreg.CloseKey(key)
    except FileNotFoundError:
        return False
    except OSError:
        return False
    except Exception:
        return False


def _unix_add(minimized: bool) -> bool:
    try:
        exe, args = _unix_launch()
        if minimized:
            args = [*args, "--minimized"]
        ok = autostart_unix.set_enabled(APP_ID, exe, args, True, display_name=APP_NAME, **_LEGACY)
        if ok:
            log_info("Açılışta Başlat kaydı yazıldı")
        else:
            log_error("Açılışta Başlat kaydı yazılamadı")
        return ok
    except Exception as exc:
        log_error("Açılışta Başlat kaydı yazılamadı", exc)
        return False


def _unix_remove() -> bool:
    try:
        return autostart_unix.set_enabled(APP_ID, "", [], False, **_LEGACY)
    except Exception as exc:
        log_error("Açılışta Başlat kaydı silinemedi", exc)
        return False
