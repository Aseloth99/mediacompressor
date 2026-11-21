"""Ortak yardımcılar."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
from typing import Iterable, Mapping

from ..core.app_info import APP_ID, LEGACY_APP_ID, LOCK_NAME, SOCKET_NAME
from .platform_utils import is_macos, is_windows


def get_application_path() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def app_bundle_dir(executable: str | None = None, platform: str | None = None) -> str | None:
    """macOS'ta çalışan ``X.app`` paketinin yolu (``X.app/Contents/MacOS/X`` -> ``X.app``).

    Paket dışında (kaynak koddan çalışma, Windows, Linux) None döner.
    """
    if not is_macos(platform):
        return None
    exe = os.path.abspath(executable or sys.executable)
    parts = exe.split(os.sep)
    for index in range(len(parts) - 1, -1, -1):
        if parts[index].lower().endswith(".app"):
            return os.sep.join(parts[: index + 1]) or os.sep
    return None


def _abs_env_dir(name: str, env: Mapping[str, str]) -> str | None:
    """XDG kuralı: ortam değişkeni yalnızca MUTLAK bir yol ise geçerlidir."""
    value = (env.get(name) or "").strip()
    return value if value and os.path.isabs(value) else None


def get_user_config_dir(
    app_id: str = APP_ID, platform: str | None = None,
    env: Mapping[str, str] | None = None, home: str | None = None,
) -> str:
    """Ayar klasörü: Windows %APPDATA%, macOS ~/Library/Application Support, Linux $XDG_CONFIG_HOME."""
    env = os.environ if env is None else env
    home = home or os.path.expanduser("~")
    if is_windows(platform):
        base = env.get("APPDATA") or os.path.join(home, "AppData", "Roaming")
        return os.path.join(base, app_id)
    if is_macos(platform):
        return os.path.join(home, "Library", "Application Support", app_id)
    xdg = _abs_env_dir("XDG_CONFIG_HOME", env) or os.path.join(home, ".config")
    return os.path.join(xdg, app_id)


def get_user_data_dir(
    app_id: str = APP_ID, platform: str | None = None,
    env: Mapping[str, str] | None = None, home: str | None = None,
) -> str:
    """Veri klasörü: Windows %LOCALAPPDATA%, macOS ~/Library/Application Support, Linux $XDG_DATA_HOME."""
    env = os.environ if env is None else env
    home = home or os.path.expanduser("~")
    if is_windows(platform):
        base = env.get("LOCALAPPDATA") or os.path.join(home, "AppData", "Local")
        return os.path.join(base, app_id)
    if is_macos(platform):
        return os.path.join(home, "Library", "Application Support", app_id)
    xdg = _abs_env_dir("XDG_DATA_HOME", env) or os.path.join(home, ".local", "share")
    return os.path.join(xdg, app_id)


def get_user_log_dir(
    app_id: str = APP_ID, platform: str | None = None,
    env: Mapping[str, str] | None = None, home: str | None = None,
) -> str:
    """Günlük klasörü: macOS ~/Library/Logs/<uygulama>; diğerlerinde <veri klasörü>/logs."""
    if is_macos(platform):
        return os.path.join(home or os.path.expanduser("~"), "Library", "Logs", app_id)
    return os.path.join(get_user_data_dir(app_id, platform, env, home), "logs")


def instance_lock_path(
    platform: str | None = None, tempdir: str | None = None, uid: int | None = None,
) -> str:
    """Tek örnek kilit dosyası. Windows'ta eskisi gibi ``<temp>/<LOCK_NAME>``; POSIX'te /tmp
    kullanıcılar arasında ortak olduğundan dosya adına kullanıcı kimliği eklenir (başka bir
    kullanıcının kilidi yüzünden "zaten çalışıyor" denmesin)."""
    tempdir = tempdir or tempfile.gettempdir()
    if is_windows(platform):
        return os.path.join(tempdir, LOCK_NAME)
    stem, ext = os.path.splitext(LOCK_NAME)
    return os.path.join(tempdir, f"{stem}-{_uid(uid)}{ext}")


def instance_socket_name(platform: str | None = None, uid: int | None = None) -> str:
    """Tek örnek yerel soket adı (POSIX'te kullanıcıya özel)."""
    if is_windows(platform):
        return SOCKET_NAME
    return f"{SOCKET_NAME}-{_uid(uid)}"


def _uid(uid: int | None) -> str:
    if uid is not None:
        return str(uid)
    getter = getattr(os, "getuid", None)
    return str(getter()) if getter else "0"


def resolve_user_config(filename: str = "config.json", app_id: str = APP_ID,
                        app_dir: str | None = None) -> tuple[str, str | None]:
    """Kullanıcı config yolu; tohum yalnızca kullanıcı dosyası yokken."""
    user_dir = get_user_config_dir(app_id)
    os.makedirs(user_dir, exist_ok=True)
    user_path = os.path.join(user_dir, filename)
    if os.path.isfile(user_path):
        return user_path, None
    # Eski kimliğin ("MedyaSikistirici") ayarları önce gelir: Config.load kopyalayıp yeni yere kaydeder,
    # eski klasör silinmez. Yoksa güncellenen kullanıcının tüm ayarları varsayılana dönüyordu.
    if app_id == APP_ID:
        legacy = os.path.join(get_user_config_dir(LEGACY_APP_ID), filename)
        if os.path.isfile(legacy):
            return user_path, legacy
    app_dir = app_dir or get_application_path()
    seen: set[str] = set()
    for candidate in (os.path.join(app_dir, filename), os.path.join(os.getcwd(), filename)):
        norm = os.path.normcase(os.path.abspath(candidate))
        if norm in seen:
            continue
        seen.add(norm)
        if os.path.isfile(candidate):
            return user_path, candidate
    return user_path, None


def resource_path(*parts: str) -> str:
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    else:
        base = get_application_path()
    return os.path.join(base, *parts)


def format_bytes(size: int | float) -> str:
    size = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(size) < 1024.0:
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} PB"


def format_speed(speed_mbps: float) -> str:
    if speed_mbps >= 1.0:
        return f"{speed_mbps:.2f} MB/s"
    speed_kbps = speed_mbps * 1024.0
    return f"{speed_kbps:.2f} KB/s"


def format_duration(seconds: float, lang: str | None = None) -> str:
    from .locales import get_system_language, t

    if lang is None:
        lang = get_system_language()
    seconds = max(0, int(round(seconds)))
    hours, rem = divmod(seconds, 3600)
    minutes, sec = divmod(rem, 60)
    h_unit = t("dur_h", lang)
    m_unit = t("dur_m", lang)
    s_unit = t("dur_s", lang)
    if hours:
        return f"{hours} {h_unit} {minutes} {m_unit}"
    if minutes:
        return f"{minutes} {m_unit} {sec} {s_unit}"
    return f"{sec} {s_unit}"


def format_eta(seconds: float, lang: str | None = None) -> str:
    """Kalan süre metni: okunur adımlara yuvarlanır ve gereksiz birim yazılmaz
    ("45 sn", "3 dk 20 sn", "12 dk", "1 sa 25 dk"); geçen süre için format_duration kullanılır."""
    from ..core.eta import round_eta
    from .locales import get_system_language, t

    if lang is None:
        lang = get_system_language()
    total = round_eta(seconds)
    hours, rem = divmod(total, 3600)
    minutes, sec = divmod(rem, 60)
    if hours:
        return f"{hours} {t('dur_h', lang)} {minutes} {t('dur_m', lang)}" if minutes else f"{hours} {t('dur_h', lang)}"
    if minutes >= 10 or (minutes and not sec):
        return f"{minutes} {t('dur_m', lang)}"
    if minutes:
        return f"{minutes} {t('dur_m', lang)} {sec} {t('dur_s', lang)}"
    return f"{sec} {t('dur_s', lang)}"


def _xdg_user_dir(name: str, env: Mapping[str, str], home: str) -> str | None:
    """``~/.config/user-dirs.dirs`` içindeki ``XDG_<NAME>_DIR`` değeri (varsa ve klasörse)."""
    config_home = _abs_env_dir("XDG_CONFIG_HOME", env) or os.path.join(home, ".config")
    try:
        with open(os.path.join(config_home, "user-dirs.dirs"), "r", encoding="utf-8", errors="replace") as handle:
            lines = handle.read().splitlines()
    except OSError:
        return None
    key = f"XDG_{name}_DIR"
    for line in lines:
        line = line.strip()
        if not line.startswith(key + "="):
            continue
        value = line.split("=", 1)[1].strip().strip('"').strip("'")
        value = value.replace("${HOME}", home).replace("$HOME", home)
        if value and os.path.isabs(value) and os.path.isdir(value):
            return os.path.normpath(value)
    return None


def desktop_dir(
    platform: str | None = None, env: Mapping[str, str] | None = None, home: str | None = None,
) -> str:
    """Masaüstü klasörü; bulunamazsa ev dizini. Linux'ta XDG_DESKTOP_DIR (yerelleştirilmiş
    ad, ör. "Masaüstü") ``user-dirs.dirs`` dosyasından okunur."""
    env = os.environ if env is None else env
    home = home or os.path.expanduser("~")
    if is_windows(platform) and os.name == "nt":
        try:
            import ctypes
            buf = ctypes.create_unicode_buffer(260)
            if ctypes.windll.shell32.SHGetFolderPathW(None, 0, None, 0, buf) == 0:
                if buf.value and os.path.isdir(buf.value):
                    return buf.value
        except Exception:
            pass
    if not is_windows(platform) and not is_macos(platform):
        xdg = _xdg_user_dir("DESKTOP", env, home)
        if xdg:
            return xdg
    profile = env.get("USERPROFILE", home) if is_windows(platform) else home
    for base in (profile, home):
        for name in ("Desktop", "Masaüstü"):
            path = os.path.join(base, name)
            if os.path.isdir(path):
                return path
    return home


def default_output_dir(lang: str = "tr") -> str:
    from .locales import get_output_folder_name
    folder = get_output_folder_name(lang)
    return os.path.join(desktop_dir(), folder)


def norm_path(path: str) -> str:
    return os.path.normcase(os.path.abspath(path))


def local_paths_from_drop(urls: Iterable, text: str = "") -> list[str]:
    """Sürükle-bırak verisinden yerel yolları çıkar.

    ``urls``: ``toLocalFile()`` sahibi nesneler (QUrl). Bazı Linux dosya yöneticileri/uygulamaları
    ``text/uri-list`` yerine düz metin (``file:///...`` satırları veya mutlak yol) bırakır; URL
    yoksa ``text`` bu biçimlerde çözülür. Yinelenenler atılır, sıra korunur.
    """
    found: list[str] = []
    for url in urls or ():
        getter = getattr(url, "toLocalFile", None)
        path = getter() if callable(getter) else ""
        if path:
            found.append(path)
    if not found and text:
        for line in text.replace("\r", "\n").split("\n"):
            line = line.strip().strip("\x00")
            if not line or line.startswith("#"):
                continue
            path = ""
            if line.lower().startswith("file:"):
                parsed = urllib.parse.urlparse(line)
                if parsed.netloc in ("", "localhost"):
                    path = urllib.request.url2pathname(parsed.path)
            elif os.path.isabs(line):
                path = line
            if path:
                found.append(path)
    result: list[str] = []
    for path in found:
        if path.replace("\\", "/").startswith("/.file/"):  # macOS dosya başvuru URL'si (çözümlenememiş)
            continue
        if path not in result:
            result.append(path)
    return result


def reveal_in_file_manager(path: str, platform: str | None = None, popen=None, startfile=None) -> bool:
    """Dosyayı gezginde seçili gösterir; klasörü açar."""
    try:
        path = os.path.normpath(os.path.abspath(path))
        if not os.path.exists(path):
            return False
        if is_windows(platform):
            if os.path.isdir(path):
                (startfile or os.startfile)(path)
            else:
                (popen or subprocess.Popen)(["explorer", "/select,", path])
            return True
        launch = popen or subprocess.Popen
        # Dosya yöneticisi bağımsız çalışsın; çıktısı terminali kirletmesin.
        detach = {
            "stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL,
            "start_new_session": True,
        }
        if is_macos(platform):
            launch(["open", "-R", path], **detach)
            return True
        parent = path if os.path.isdir(path) else os.path.dirname(path)
        launch(["xdg-open", parent], **detach)
        return True
    except Exception:
        return False
