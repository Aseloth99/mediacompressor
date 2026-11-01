"""Testler arasi ortak yardimcilar (unittest discover -s tests ile ayni dizinden import edilir)."""

from __future__ import annotations

import atexit
import os
import pathlib
import sys
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# Uygulama gunlugu/ayar/veri dizinleri gercek kullanici profiline degil gecici dizine yazsin
# (logger ve helpers ortam degiskenlerini cagri aninda okur; bu modul src'den once import edilir).
_SANDBOX = tempfile.mkdtemp(prefix="mc_profile_")
for _name in ("APPDATA", "LOCALAPPDATA", "XDG_CONFIG_HOME", "XDG_DATA_HOME"):
    os.environ[_name] = _SANDBOX
if os.name != "nt":
    # macOS (~/Library/...) ve Linux (~/.config yedegi) yollari HOME'dan turetilir: gercek profile yazma.
    os.environ["HOME"] = _SANDBOX


def _cleanup_sandbox() -> None:
    import logging
    import shutil

    logging.shutdown()
    shutil.rmtree(_SANDBOX, ignore_errors=True)


atexit.register(_cleanup_sandbox)

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# "Otomatik bitrate" sentineli (ayri bir adimda src.core.app_info.BITRATE_AUTO olacak).
AUTO_BITRATE = "auto"


class TempDirTestCase(unittest.TestCase):
    """Her test icin gecici dizin; gercek kullanici dizinlerine dokunulmaz."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="mc_test_")
        self.addCleanup(self._tmp.cleanup)
        self.tmp = pathlib.Path(self._tmp.name)

    def listing(self, folder: pathlib.Path | str) -> list[str]:
        """Klasordeki (alt klasorler dahil) dosyalarin goreli yollari, sirali."""
        folder = pathlib.Path(folder)
        return sorted(
            str(p.relative_to(folder)).replace("\\", "/")
            for p in folder.rglob("*") if p.is_file()
        )


def make_image(path, size=(64, 48), fmt="JPEG", mode="RGB", noise=True, **save_kwargs):
    """Test icin kucuk bir gorsel yazar ve yolunu dondurur."""
    from PIL import Image

    path = str(path)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    channels = len(mode)
    data = os.urandom(size[0] * size[1] * channels) if noise else bytes(size[0] * size[1] * channels)
    img = Image.frombytes(mode, size, data)
    img.save(path, fmt, **save_kwargs)
    return path


class SignalLog:
    """JobWorker sinyallerini toplar (ayni thread'de dogrudan baglanti)."""

    def __init__(self, worker) -> None:
        self.logs: list[str] = []
        self.done: list[tuple[str, str, object]] = []
        self.started: list[str] = []
        self.finished: list[dict] = []
        worker.log.connect(self.logs.append)
        worker.file_started.connect(self.started.append)
        worker.file_done.connect(lambda p, s, e: self.done.append((p, s, e)))
        worker.finished_job.connect(self.finished.append)

    def statuses(self) -> list[str]:
        return [s for _, s, _ in self.done]
