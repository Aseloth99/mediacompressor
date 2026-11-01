"""Uygulama kimligi "MedyaSikistirici" -> "MediaCompressor" oldu: eski kimligin ayarlari, baslangic kaydi ve
indirilmis ffmpeg'i kaybolmasin. Gercek %APPDATA% ve kayit defterine dokunulmaz (gecici dizin + sahte winreg)."""

from __future__ import annotations

import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(__file__))
from _support import TempDirTestCase  # noqa: E402

from src.core import ffmpeg_manager  # noqa: E402
from src.core.app_info import APP_ID, LEGACY_APP_ID  # noqa: E402
from src.core.ffmpeg_manager import FFmpegManager  # noqa: E402
from src.utils import config as config_module  # noqa: E402
from src.utils import helpers, startup  # noqa: E402


class LegacyConfigTests(TempDirTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.app_dir = self.tmp / "uygulama"
        self.app_dir.mkdir()
        dirs = lambda app_id=APP_ID, *a, **k: str(self.tmp / "roaming" / app_id)  # noqa: E731
        patcher = mock.patch.object(helpers, "get_user_config_dir", side_effect=dirs)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.legacy = self.tmp / "roaming" / LEGACY_APP_ID / "config.json"
        self.legacy.parent.mkdir(parents=True)
        self.new = self.tmp / "roaming" / APP_ID / "config.json"

    def _write_legacy(self, data: dict) -> str:
        text = json.dumps(data, ensure_ascii=False)
        self.legacy.write_text(text, encoding="utf-8")
        return text

    def test_legacy_settings_seed_the_new_config_and_the_old_file_stays(self) -> None:
        old_text = self._write_legacy({"codec": "hevc", "last_output": "D:\\Çıktı", "start_with_windows": True})
        with mock.patch.object(config_module, "get_application_path", return_value=str(self.app_dir)):
            cfg = config_module.Config()
        self.assertEqual(os.path.normcase(cfg.path), os.path.normcase(str(self.new)))
        self.assertEqual(cfg.get("codec"), "hevc")
        self.assertEqual(cfg.get("last_output"), "D:\\Çıktı")
        self.assertTrue(cfg.get("start_with_windows"))
        self.assertEqual(json.loads(self.new.read_text(encoding="utf-8"))["codec"], "hevc")
        self.assertEqual(self.legacy.read_text(encoding="utf-8"), old_text, "eski ayar dosyasi silinmez/degismez")

    def test_existing_new_config_wins_over_the_legacy_one(self) -> None:
        self._write_legacy({"codec": "hevc"})
        self.new.parent.mkdir(parents=True)
        self.new.write_text(json.dumps({"codec": "av1"}), encoding="utf-8")
        user_path, seed = helpers.resolve_user_config("config.json", APP_ID, str(self.app_dir))
        self.assertEqual(os.path.normcase(user_path), os.path.normcase(str(self.new)))
        self.assertIsNone(seed)

    def test_legacy_config_comes_before_the_seed_next_to_the_app(self) -> None:
        self._write_legacy({"codec": "hevc"})
        (self.app_dir / "config.json").write_text("{}", encoding="utf-8")
        _, seed = helpers.resolve_user_config("config.json", APP_ID, str(self.app_dir))
        self.assertEqual(os.path.normcase(seed), os.path.normcase(str(self.legacy)))


class FakeWinreg:
    """Yalnizca Run anahtarindaki degerleri tutan sahte winreg."""

    HKEY_CURRENT_USER = object()
    KEY_SET_VALUE = 2
    KEY_READ = 1
    REG_SZ = 1

    def __init__(self, values=None) -> None:
        self.values: dict[str, str] = dict(values or {})

    def OpenKey(self, root, path, reserved, access):  # noqa: N802
        return "run"

    def CloseKey(self, key) -> None:  # noqa: N802
        pass

    def SetValueEx(self, key, name, reserved, kind, value) -> None:  # noqa: N802
        self.values[name] = value

    def DeleteValue(self, key, name) -> None:  # noqa: N802
        if name not in self.values:
            raise FileNotFoundError(name)
        del self.values[name]

    def QueryValueEx(self, key, name):  # noqa: N802
        if name not in self.values:
            raise FileNotFoundError(name)
        return self.values[name], self.REG_SZ


class LegacyStartupEntryTests(unittest.TestCase):
    def _with(self, values):
        fake = FakeWinreg(values)
        patcher = mock.patch.dict(sys.modules, {"winreg": fake})
        patcher.start()
        self.addCleanup(patcher.stop)
        return fake

    def test_legacy_run_value_counts_as_enabled(self) -> None:
        self._with({LEGACY_APP_ID: '"C:\\eski\\Medya Sıkıştırıcı.exe" --minimized'})
        self.assertTrue(startup._win_is_in())

    def test_nothing_registered_is_disabled(self) -> None:
        self._with({"BaskaUygulama": "x.exe"})
        self.assertFalse(startup._win_is_in())

    def test_enabling_rewrites_under_the_new_name_and_drops_the_legacy_value(self) -> None:
        fake = self._with({LEGACY_APP_ID: "eski.exe", "BaskaUygulama": "x.exe"})
        self.assertTrue(startup._win_add(minimized=True))
        self.assertNotIn(LEGACY_APP_ID, fake.values)
        self.assertTrue(fake.values[APP_ID].endswith("--minimized"))
        self.assertEqual(fake.values["BaskaUygulama"], "x.exe")

    def test_disabling_removes_both_names(self) -> None:
        fake = self._with({APP_ID: "yeni.exe", LEGACY_APP_ID: "eski.exe", "BaskaUygulama": "x.exe"})
        self.assertTrue(startup._win_remove())
        self.assertEqual(fake.values, {"BaskaUygulama": "x.exe"})
        self.assertFalse(startup._win_is_in())


class LegacyFfmpegTests(TempDirTestCase):
    def _patches(self):
        data = lambda app_id=APP_ID, *a, **k: str(self.tmp / "local" / app_id)  # noqa: E731
        return (
            mock.patch.object(ffmpeg_manager, "get_user_data_dir", side_effect=data),
            mock.patch.object(ffmpeg_manager, "get_application_path", return_value=str(self.tmp / "uygulama")),
            mock.patch.object(ffmpeg_manager, "resource_path", side_effect=lambda *p: str(self.tmp / "kaynak" / p[-1])),
            mock.patch.object(ffmpeg_manager, "which_no_cwd", return_value=None),
        )

    def test_ffmpeg_downloaded_under_the_legacy_id_is_found_on_windows(self) -> None:
        legacy_bin = self.tmp / "local" / LEGACY_APP_ID / "ffmpeg" / "bin"
        legacy_bin.mkdir(parents=True)
        for name in ("ffmpeg.exe", "ffprobe.exe"):
            (legacy_bin / name).write_bytes(b"")
        p1, p2, p3, p4 = self._patches()
        with p1, p2, p3, p4:
            manager = FFmpegManager(platform="win32")
            found = manager.find()
            order = [ff for ff, _fp in manager._candidates()]
        self.assertEqual(found, str(legacy_bin / "ffmpeg.exe"))
        self.assertEqual(manager.ffprobe_path, str(legacy_bin / "ffprobe.exe"))
        new_bin = str(self.tmp / "local" / APP_ID / "ffmpeg" / "bin" / "ffmpeg.exe")
        self.assertLess(order.index(new_bin), order.index(found), "yeni kimligin ffmpeg'i once gelir")

    def test_legacy_folder_is_only_searched_on_windows(self) -> None:
        p1, p2, p3, p4 = self._patches()
        with p1, p2, p3, p4:
            found = [ff for ff, _fp in FFmpegManager(platform="linux")._candidates()]
        self.assertFalse([p for p in found if LEGACY_APP_ID in p])


if __name__ == "__main__":
    unittest.main()
