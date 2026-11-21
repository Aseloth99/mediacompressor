"""config.json ayar yöneticisi — kullanıcı dizinine yazar."""

from __future__ import annotations

import json
import os
import tempfile
from copy import deepcopy
from typing import Any

from ..core.app_info import APP_ID, BITRATE_AUTO, normalize_bitrate
from .helpers import get_application_path, resolve_user_config
from .logger import log_error

FILE_TYPE_ALL = "all"
FILE_TYPE_IMAGES = "images"
FILE_TYPE_VIDEOS = "videos"

_LEGACY_FILE_TYPES = {
    "Tümü": FILE_TYPE_ALL,
    "Resimler": FILE_TYPE_IMAGES,
    "Videolar": FILE_TYPE_VIDEOS,
}


def normalize_file_type(value: str | None) -> str:
    if not value:
        return FILE_TYPE_ALL
    if value in _LEGACY_FILE_TYPES:
        return _LEGACY_FILE_TYPES[value]
    if value in (FILE_TYPE_ALL, FILE_TYPE_IMAGES, FILE_TYPE_VIDEOS):
        return value
    return FILE_TYPE_ALL


DEFAULTS: dict[str, Any] = {
    "language": "auto",
    "theme": "system",
    "start_with_windows": False,
    "show_notifications": True,
    "auto_update_check": True,
    "auto_update_install": True,
    "dismissed_notice": "",
    "declined_update_version": None,
    "last_update_check": None,
    "profile": "balanced",
    "file_type": FILE_TYPE_ALL,
    "video_res": "1080p",
    "image_res": "2400px",
    "codec": "h264",
    "bitrate": BITRATE_AUTO,
    "crf": 24,
    "preset": "slow",
    "audio_bitrate": "128k",
    "image_quality_auto": True,
    "image_quality": 80,
    "scan_subfolders": True,
    "gpu_mode": "auto",  # gelişmiş ayarlardaki seçim: "auto" | "nvenc" | "amf" | "qsv" | ... | "cpu"
    "fps": None,  # None = orijinal kare hızı
    "remove_audio": False,
    "accent": "cyan",
    "last_input": "",
    "last_output": "",
    "recent_folders": [],
    "open_output_when_done": False,
    "left_panel_collapsed": False,  # kuyruk başlığındaki düğmeyle gizlenen ayar paneli
    "window_geometry": None,  # {"x","y","w","h","maximized"}: son pencere konumu/boyutu (ekrana sığdırılarak geri yüklenir)
}


class Config:
    def __init__(self, filename: str = "config.json"):
        user_path, seed_path = resolve_user_config(filename, APP_ID, get_application_path())
        self.path = user_path
        self._seed_path = seed_path
        self.data = deepcopy(DEFAULTS)
        self.load()

    def load(self) -> dict[str, Any]:
        if os.path.isfile(self.path):
            self._read(self.path)
            return self.data
        if self._seed_path and os.path.isfile(self._seed_path):
            self._read(self._seed_path)
            self.save()
            return self.data
        self.data = deepcopy(DEFAULTS)
        return self.data

    def _read(self, path: str) -> None:
        try:
            with open(path, "r", encoding="utf-8-sig") as f:  # Not Defteri BOM'u tolere edilir
                loaded = json.load(f)
            if not isinstance(loaded, dict):
                raise ValueError("config.json bir JSON nesnesi değil")
            self.data = {**deepcopy(DEFAULTS), **loaded}
            self.data["file_type"] = normalize_file_type(self.data.get("file_type"))
            # Eski yerelleştirilmiş "otomatik" değeri -> sabit sentinel (geriye uyum).
            self.data["bitrate"] = normalize_bitrate(self.data.get("bitrate"))
        except (ValueError, UnicodeDecodeError) as exc:  # JSONDecodeError de ValueError'dır
            log_error("Ayar dosyası bozuk, varsayılanlara dönülüyor", exc)
            self.data = deepcopy(DEFAULTS)
            if os.path.abspath(path) == os.path.abspath(self.path):
                self._quarantine(path)
        except Exception as exc:
            log_error("Ayar yükleme hatası", exc)
            self.data = deepcopy(DEFAULTS)

    @staticmethod
    def _quarantine(path: str) -> None:
        """Bozuk ayar dosyasını ``.corrupt`` olarak yedekle; sonraki kayıt temiz dosya yazsın,
        kullanıcı da eski içeriği kurtarabilsin."""
        backup = path + ".corrupt"
        try:
            os.replace(path, backup)
            log_error(f"Bozuk ayar dosyası yedeklendi: {backup}")
        except OSError as exc:
            log_error("Bozuk ayar dosyası yedeklenemedi", exc)

    def save(self) -> bool:
        """Atomik kayıt: aynı klasörde geçici dosyaya yaz, fsync, ``os.replace``.
        Yazma sırasında çökme/disk dolu eski ayarları yarım dosyayla ezmez."""
        tmp_path = None
        try:
            directory = os.path.dirname(self.path)
            if directory:
                os.makedirs(directory, exist_ok=True)
            fd, tmp_path = tempfile.mkstemp(
                prefix=os.path.basename(self.path) + ".", suffix=".tmp", dir=directory or ".",
            )
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=4, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, self.path)
            tmp_path = None
            return True
        except Exception as exc:
            log_error("Ayar kaydetme hatası", exc)
            return False
        finally:
            if tmp_path:
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default if default is not None else DEFAULTS.get(key))

    def set(self, key: str, value: Any, persist: bool = True) -> None:
        self.data[key] = value
        if persist:
            self.save()

    def add_recent_folder(self, folder: str) -> None:
        if not folder:
            return
        recent = [p for p in self.get("recent_folders", []) if p != folder]
        recent.insert(0, folder)
        self.set("recent_folders", recent[:8])
