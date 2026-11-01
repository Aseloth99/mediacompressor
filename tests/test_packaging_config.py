"""Madde 7: bagimlilik/paket yapilandirmasi, atomik ayar kaydi, bitrate sentineli."""

from __future__ import annotations

import ast
import json
import os
import re
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.dirname(__file__))
from _support import ROOT, TempDirTestCase  # noqa: E402

from src.core import app_info  # noqa: E402
from src.core.app_info import BITRATE_AUTO, is_auto_bitrate, normalize_bitrate  # noqa: E402
from src.core.video_compressor import VideoCompressor  # noqa: E402
from src.utils import config as config_module  # noqa: E402
from src.utils.config import DEFAULTS, Config  # noqa: E402

SPEC = ROOT / "MediaCompressor.spec"


def _requirement_names() -> set[str]:
    names = set()
    for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            names.add(re.split(r"[<>=!~;\[ ]", line, maxsplit=1)[0].lower().replace("_", "-"))
    return names


def _spec_excludes() -> list[str]:
    tree = ast.parse(SPEC.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "excludes" for t in node.targets
        ):
            return [elt.value for elt in node.value.elts]
    raise AssertionError("spec icinde excludes listesi yok")


class RequirementsTests(unittest.TestCase):
    def test_runtime_dependencies_used_by_code_are_declared(self) -> None:
        names = _requirement_names()
        for needed in ("pyqt6", "pillow", "piexif", "pillow-heif", "pillow-avif-plugin", "imagecodecs", "numpy"):
            self.assertIn(needed, names)

    def test_every_third_party_import_in_image_pipeline_is_covered(self) -> None:
        source = (ROOT / "src" / "core" / "image_compressor.py").read_text(encoding="utf-8")
        modules = {"pillow_heif": "pillow-heif", "pillow_avif": "pillow-avif-plugin",
                   "imagecodecs": "imagecodecs", "piexif": "piexif", "numpy": "numpy"}
        names = _requirement_names()
        for module, requirement in modules.items():
            if re.search(rf"^\s*(import|from)\s+{module}\b", source, re.M):
                self.assertIn(requirement, names, f"{module} import ediliyor ama requirements'ta yok")


class SpecTests(unittest.TestCase):
    def test_spec_is_valid_python(self) -> None:
        ast.parse(SPEC.read_text(encoding="utf-8"))

    def test_numpy_is_not_excluded_because_jxl_needs_it(self) -> None:
        self.assertNotIn("numpy", _spec_excludes())

    def test_imagecodecs_is_collected(self) -> None:
        self.assertIn("collect_all('imagecodecs')", SPEC.read_text(encoding="utf-8"))

    def test_no_stdlib_module_is_excluded(self) -> None:
        # xml/email/html/ssl/http... dislanirsa PyQt6/urllib/Pillow calisma zamaninda cokar.
        # tkinter onceden beri dislaniyordu (kullanilmiyor); yenisi eklenmemeli.
        stdlib = {m for m in sys.stdlib_module_names}
        offenders = [e for e in _spec_excludes() if e.split(".")[0] in stdlib and e != "tkinter"]
        self.assertEqual(offenders, [])

    def test_exe_declares_version_file_that_exists(self) -> None:
        text = SPEC.read_text(encoding="utf-8")
        match = re.search(r"version='([^']+)'", text)
        self.assertIsNotNone(match)
        self.assertTrue((ROOT / match.group(1)).is_file())


class VersionInfoTests(unittest.TestCase):
    def test_version_file_matches_app_version(self) -> None:
        text = (ROOT / "version_info.txt").read_text(encoding="utf-8")
        parts = tuple(int(p) for p in app_info.VERSION.split("."))
        quad = (parts + (0, 0, 0, 0))[:4]
        self.assertIn(f"filevers={quad}", text)
        self.assertIn(f"prodvers={quad}", text)
        dotted = ".".join(str(p) for p in quad)
        self.assertIn(f"StringStruct('FileVersion', '{dotted}')", text)
        self.assertIn(f"StringStruct('ProductVersion', '{dotted}')", text)

    def test_pyinstaller_can_parse_it(self) -> None:
        try:
            from PyInstaller.utils.win32 import versioninfo
        except Exception:  # noqa: BLE001
            self.skipTest("PyInstaller yok")
        info = versioninfo.load_version_info_from_text_file(str(ROOT / "version_info.txt"))
        parts = tuple(int(p) for p in app_info.VERSION.split("."))
        ms, ls = info.ffi.fileVersionMS, info.ffi.fileVersionLS
        parsed = (ms >> 16, ms & 0xFFFF, ls >> 16, ls & 0xFFFF)
        self.assertEqual(parsed, (parts + (0, 0, 0, 0))[:4])


class AtomicConfigTests(TempDirTestCase):
    def _config(self, content: str | bytes | None = None) -> Config:
        path = self.tmp / "cfg" / "config.json"
        path.parent.mkdir(exist_ok=True)
        if content is not None:
            path.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))
        with mock.patch.object(config_module, "resolve_user_config", return_value=(str(path), None)):
            cfg = Config()
        self.path = path
        return cfg

    def test_save_roundtrip_leaves_no_temp_files(self) -> None:
        cfg = self._config()
        cfg.set("accent", "mor")
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8"))["accent"], "mor")
        self.assertEqual(self.listing(self.path.parent), ["config.json"])

    def test_save_fsyncs_then_replaces(self) -> None:
        cfg = self._config()
        with mock.patch.object(config_module.os, "fsync") as fsync, \
                mock.patch.object(config_module.os, "replace", wraps=os.replace) as replace:
            self.assertTrue(cfg.save())
        fsync.assert_called_once()
        self.assertEqual(replace.call_args.args[1], str(self.path))

    def test_crash_while_writing_keeps_previous_settings_intact(self) -> None:
        cfg = self._config(json.dumps({"accent": "eski"}))
        cfg.data["accent"] = "yeni"

        def exploding_dump(obj, handle, **kwargs):
            handle.write('{"accent": "yar')  # yarim yazilmis icerik
            raise OSError("disk dolu")

        with mock.patch.object(config_module.json, "dump", exploding_dump):
            self.assertFalse(cfg.save())
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8"))["accent"], "eski")
        self.assertEqual(self.listing(self.path.parent), ["config.json"])  # gecici dosya silindi

    def test_corrupt_json_is_backed_up_and_defaults_used(self) -> None:
        cfg = self._config('{"accent": "mor", bozuk')
        self.assertEqual(cfg.data["accent"], DEFAULTS["accent"])
        corrupt = self.path.parent / "config.json.corrupt"
        self.assertTrue(corrupt.is_file())
        self.assertEqual(corrupt.read_text(encoding="utf-8"), '{"accent": "mor", bozuk')
        self.assertFalse(self.path.exists())
        cfg.set("accent", "yesil")  # sonraki kayit temiz dosya yazar, yedege dokunmaz
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8"))["accent"], "yesil")
        self.assertEqual(corrupt.read_text(encoding="utf-8"), '{"accent": "mor", bozuk')

    def test_non_object_json_counts_as_corrupt(self) -> None:
        cfg = self._config("[1, 2, 3]")
        self.assertEqual(cfg.data, json.loads(json.dumps(DEFAULTS)))
        self.assertTrue((self.path.parent / "config.json.corrupt").is_file())

    def test_utf8_bom_file_loads_normally(self) -> None:
        cfg = self._config(b"\xef\xbb\xbf" + json.dumps({"accent": "bomlu"}).encode("utf-8"))
        self.assertEqual(cfg.data["accent"], "bomlu")
        self.assertFalse((self.path.parent / "config.json.corrupt").exists())


class BitrateSentinelTests(TempDirTestCase):
    def test_sentinel_is_not_a_localized_word(self) -> None:
        self.assertEqual(BITRATE_AUTO, "auto")
        self.assertNotEqual(BITRATE_AUTO, "otomatik")
        self.assertEqual(DEFAULTS["bitrate"], BITRATE_AUTO)

    def test_legacy_and_empty_values_are_accepted(self) -> None:
        for value in ("auto", "AUTO", "otomatik", "Otomatik", "", None, " auto "):
            self.assertTrue(is_auto_bitrate(value), value)
            self.assertEqual(normalize_bitrate(value), BITRATE_AUTO)
        for value in ("2000k", "1500k"):
            self.assertFalse(is_auto_bitrate(value))
            self.assertEqual(normalize_bitrate(value), value)

    def test_stored_legacy_value_is_migrated_on_load(self) -> None:
        path = self.tmp / "config.json"
        path.write_text(json.dumps({"bitrate": "otomatik"}), encoding="utf-8")
        with mock.patch.object(config_module, "resolve_user_config", return_value=(str(path), None)):
            self.assertEqual(Config().data["bitrate"], BITRATE_AUTO)

    def test_stored_fixed_bitrate_is_kept(self) -> None:
        path = self.tmp / "config.json"
        path.write_text(json.dumps({"bitrate": "2000k"}), encoding="utf-8")
        with mock.patch.object(config_module, "resolve_user_config", return_value=(str(path), None)):
            self.assertEqual(Config().data["bitrate"], "2000k")

    def test_build_cmd_treats_old_and_new_auto_identically(self) -> None:
        vc = VideoCompressor("ffmpeg")
        legacy = vc.build_cmd("i.mp4", "o.mp4", "cpu", "h264", "otomatik", 24, "slow", "128k", None)
        new = vc.build_cmd("i.mp4", "o.mp4", "cpu", "h264", BITRATE_AUTO, 24, "slow", "128k", None)
        self.assertEqual(legacy, new)
        self.assertIn("-crf", new)
        fixed = vc.build_cmd("i.mp4", "o.mp4", "cpu", "h264", "2000k", 24, "slow", "128k", None)
        self.assertNotIn("-crf", fixed)
        self.assertEqual(fixed[fixed.index("-b:v") + 1], "2000k")

    def test_ui_tables_use_the_constant(self) -> None:
        from src.gui import main_window

        self.assertEqual(main_window.BITRATE_KEYS[0][0], BITRATE_AUTO)
        for key, spec in main_window.PROFILES.items():
            if "bitrate" in spec:
                self.assertEqual(spec["bitrate"], BITRATE_AUTO, key)

    def test_advanced_dialog_detects_auto_with_new_and_old_ids(self) -> None:
        from src.gui.advanced_dialog import AdvancedDialog

        for ident in (BITRATE_AUTO, "otomatik"):
            fake = SimpleNamespace(
                bitrate=SimpleNamespace(currentIndex=lambda: 0),
                _bitrate_labels=lambda lang, ident=ident: [(ident, "x"), ("1500k", "y")],
                lang="tr",
            )
            self.assertTrue(AdvancedDialog._is_auto_bitrate(fake))
        fake.bitrate = SimpleNamespace(currentIndex=lambda: 1)
        self.assertFalse(AdvancedDialog._is_auto_bitrate(fake))


if __name__ == "__main__":
    unittest.main()
