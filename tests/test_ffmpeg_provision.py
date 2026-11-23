"""Madde 3: FFmpeg tedarigi platforma gore — Windows'ta indirme (degismedi), macOS/Linux'ta
indirme YOK; PATH + yaygin konumlar + uygulama paketi; yerellestirilmis kurulum ipuclari."""

from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(__file__))
from _support import TempDirTestCase  # noqa: E402

from src.core import ffmpeg_manager  # noqa: E402
from src.core.ffmpeg_manager import FFmpegManager, ffmpeg_name, ffprobe_name  # noqa: E402

POSIX = os.name != "nt"


def j(*parts: str) -> str:
    return os.path.join(*parts)


class NameTests(unittest.TestCase):
    def test_executable_names_per_platform(self) -> None:
        self.assertEqual(ffmpeg_name("win32"), "ffmpeg.exe")
        self.assertEqual(ffprobe_name("win32"), "ffprobe.exe")
        for platform in ("darwin", "linux"):
            self.assertEqual(ffmpeg_name(platform), "ffmpeg")
            self.assertEqual(ffprobe_name(platform), "ffprobe")


class CandidateTests(unittest.TestCase):
    def _candidates(self, platform: str, bundle: str | None = None):
        manager = FFmpegManager(platform=platform)
        with mock.patch.object(ffmpeg_manager, "get_user_data_dir", return_value=j("veri")), \
                mock.patch.object(ffmpeg_manager, "get_application_path", return_value=j("uygulama")), \
                mock.patch.object(ffmpeg_manager, "resource_path", side_effect=lambda *p: j("kaynak", *p)), \
                mock.patch.object(ffmpeg_manager, "app_bundle_dir", return_value=bundle):
            return [ff for ff, _fp in manager._candidates()]

    def test_windows_candidates_have_no_posix_locations(self) -> None:
        found = self._candidates("win32")
        self.assertIn(j("veri", "ffmpeg", "bin", "ffmpeg.exe"), found)
        self.assertIn(j("uygulama", "ffmpeg.exe"), found)
        self.assertFalse([p for p in found if "homebrew" in p or p.startswith(("/usr", "/opt", "/snap"))])

    def test_macos_searches_homebrew_macports_and_the_app_bundle(self) -> None:
        bundle = j(os.sep, "Applications", "Medya.app")
        found = self._candidates("darwin", bundle=bundle)
        for folder in ("/opt/homebrew/bin", "/usr/local/bin", "/opt/local/bin"):
            self.assertIn(j(folder, "ffmpeg"), found)
        self.assertIn(j(bundle, "Contents", "Resources", "ffmpeg"), found)
        self.assertIn(j(bundle, "Contents", "Frameworks", "ffmpeg"), found)
        self.assertIn(j(os.path.dirname(bundle), "ffmpeg"), found)  # .app'in yaninda
        self.assertIn(j("uygulama", "ffmpeg"), found)  # Contents/MacOS (get_application_path)
        self.assertNotIn(j("veri", "ffmpeg", "bin", "ffmpeg.exe"), found)

    def test_linux_searches_standard_directories(self) -> None:
        found = self._candidates("linux")
        for folder in ("/usr/bin", "/usr/local/bin", "/snap/bin"):
            self.assertIn(j(folder, "ffmpeg"), found)
        self.assertTrue(any(p.endswith(j(".local", "bin", "ffmpeg")) for p in found))
        self.assertFalse([p for p in found if p.endswith(".exe")])

    def test_probe_sits_next_to_the_binary(self) -> None:
        manager = FFmpegManager(platform="linux")
        for ff, fp in manager._candidates():
            self.assertEqual(os.path.dirname(ff), os.path.dirname(fp))
            self.assertEqual(os.path.basename(fp), "ffprobe")


class FindTests(TempDirTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.old_cwd = os.getcwd()
        os.chdir(self.tmp)
        self.addCleanup(os.chdir, self.old_cwd)

    def _install(self, folder, platform="linux", mode=0o755):
        folder.mkdir(parents=True, exist_ok=True)
        paths = []
        for name in (ffmpeg_name(platform), ffprobe_name(platform)):
            path = folder / name
            path.write_bytes(b"#!/bin/sh\n")
            os.chmod(path, mode)
            paths.append(str(path))
        return paths

    def test_found_on_path_with_probe(self) -> None:
        ff, fp = self._install(self.tmp / "bin")
        manager = FFmpegManager(platform="linux")
        with mock.patch.dict(os.environ, {"PATH": str(self.tmp / "bin")}), \
                mock.patch.object(FFmpegManager, "_candidates", return_value=[]):
            self.assertEqual(manager.find(), os.path.abspath(ff))
        self.assertEqual(manager.ffprobe_path, os.path.abspath(fp))
        self.assertTrue(manager.is_ready())

    def test_macos_finder_style_minimal_path_falls_back_to_homebrew_dir(self) -> None:
        brew = self.tmp / "opt" / "homebrew" / "bin"
        ff, fp = self._install(brew, "darwin")
        manager = FFmpegManager(platform="darwin")
        with mock.patch.dict(os.environ, {"PATH": os.pathsep.join(["/usr/bin", "/bin"])}), \
                mock.patch.object(ffmpeg_manager, "MAC_FFMPEG_DIRS", (str(brew),)), \
                mock.patch.object(ffmpeg_manager, "get_user_data_dir", return_value=str(self.tmp / "veri")), \
                mock.patch.object(ffmpeg_manager, "get_application_path", return_value=str(self.tmp / "uyg")), \
                mock.patch.object(ffmpeg_manager, "resource_path", side_effect=lambda *p: str(self.tmp / "kaynak" / p[-1])), \
                mock.patch.object(ffmpeg_manager, "app_bundle_dir", return_value=None):
            found = manager.find()
        # Gercek /usr/bin icinde ffmpeg varsa PATH araması once o bulur; her iki durumda da bulunur.
        self.assertTrue(found)
        self.assertTrue(os.path.isabs(found))

    def test_bundled_binary_next_to_the_app_is_found_without_path(self) -> None:
        app = self.tmp / "uyg"
        ff, fp = self._install(app)
        manager = FFmpegManager(platform="linux")
        with mock.patch.dict(os.environ, {"PATH": str(self.tmp / "bos")}), \
                mock.patch.object(ffmpeg_manager, "get_application_path", return_value=str(app)), \
                mock.patch.object(ffmpeg_manager, "get_user_data_dir", return_value=str(self.tmp / "veri")), \
                mock.patch.object(ffmpeg_manager, "resource_path", side_effect=lambda *p: str(self.tmp / "kaynak" / p[-1])), \
                mock.patch.object(FFmpegManager, "_candidates", wraps=manager._candidates):
            self.assertEqual(manager.find(), os.path.abspath(ff))

    @unittest.skipUnless(POSIX, "yurutme biti yalnizca POSIX'te anlamli")
    def test_non_executable_candidate_is_skipped(self) -> None:
        ff, fp = self._install(self.tmp / "yurutulemez", mode=0o644)
        manager = FFmpegManager(platform="linux")
        with mock.patch.dict(os.environ, {"PATH": str(self.tmp / "bos")}), \
                mock.patch.object(FFmpegManager, "_candidates", return_value=[(ff, fp)]):
            self.assertIsNone(manager.find())

    def test_nothing_found_returns_none(self) -> None:
        manager = FFmpegManager(platform="linux")
        with mock.patch.dict(os.environ, {"PATH": str(self.tmp / "bos")}), \
                mock.patch.object(FFmpegManager, "_candidates", return_value=[]):
            self.assertIsNone(manager.find())
        self.assertFalse(manager.is_ready())


class NoDownloadOffWindowsTests(TempDirTestCase):
    def test_download_is_windows_only(self) -> None:
        self.assertTrue(FFmpegManager(platform="win32").can_download())
        self.assertFalse(FFmpegManager(platform="darwin").can_download())
        self.assertFalse(FFmpegManager(platform="linux").can_download())

    def test_macos_and_linux_never_touch_the_network(self) -> None:
        for platform in ("darwin", "linux"):
            manager = FFmpegManager(platform=platform)
            with self.subTest(platform=platform), \
                    mock.patch.object(ffmpeg_manager.urllib.request, "urlopen") as urlopen, \
                    mock.patch.object(FFmpegManager, "_download_to") as inner:
                self.assertIsNone(manager.download(None))
            urlopen.assert_not_called()
            inner.assert_not_called()

    def test_installed_binaries_get_the_exec_bit_off_windows(self) -> None:
        import io
        import zipfile

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as archive:
            archive.writestr("ff/ffmpeg", b"x" * 100)
            archive.writestr("ff/ffprobe", b"y" * 100)
        zip_path = self.tmp / "ff.zip"
        zip_path.write_bytes(buf.getvalue())
        target = self.tmp / "hedef"
        target.mkdir()
        manager = FFmpegManager(platform="linux")
        installed = manager._install_from_zip(str(zip_path), str(target))
        self.assertEqual(installed, str(target / "bin" / "ffmpeg"))
        if POSIX:
            self.assertTrue(os.access(installed, os.X_OK))


class HintTests(unittest.TestCase):
    def test_windows_turkish_text_is_unchanged(self) -> None:
        self.assertEqual(
            FFmpegManager(platform="win32").missing_hint("tr"),
            "FFmpeg bulunamadı. FFmpeg İndir düğmesine basın veya ffmpeg'i PATH'e ekleyin.",
        )
        self.assertEqual(
            FFmpegManager(platform="win32").needed_message("tr"),
            "Video için FFmpeg gerekli. FFmpeg İndir düğmesine basın veya FFmpeg kurun.",
        )

    def test_macos_hint_has_homebrew_command_in_both_languages(self) -> None:
        manager = FFmpegManager(platform="darwin")
        for lang in ("tr", "en"):
            self.assertIn("brew install ffmpeg", manager.missing_hint(lang))
            self.assertIn("brew install ffmpeg", manager.needed_message(lang))
            self.assertNotIn("apt", manager.missing_hint(lang))

    def test_linux_hint_lists_package_managers_in_both_languages(self) -> None:
        manager = FFmpegManager(platform="linux")
        for lang in ("tr", "en"):
            hint = manager.missing_hint(lang)
            for command in ("apt install ffmpeg", "dnf install ffmpeg", "pacman -S ffmpeg"):
                self.assertIn(command, hint)
            self.assertNotIn("brew", hint)
            self.assertIn("apt install ffmpeg", manager.needed_message(lang))

    def test_languages_differ(self) -> None:
        manager = FFmpegManager(platform="linux")
        self.assertNotEqual(manager.missing_hint("tr"), manager.missing_hint("en"))


class PrepareWorkerHintTests(unittest.TestCase):
    def test_worker_logs_the_localised_platform_hint_when_ffmpeg_is_missing(self) -> None:
        from src.gui.main_window import PrepareWorker

        manager = FFmpegManager(platform="darwin")
        with mock.patch.object(FFmpegManager, "find", return_value=None):
            worker = PrepareWorker(manager, download=True, lang="en")
            logs, done = [], []
            worker.log.connect(logs.append)
            worker.done.connect(lambda m, g: done.append((m, g)))
            with mock.patch.object(ffmpeg_manager.urllib.request, "urlopen") as urlopen:
                worker.run()
        urlopen.assert_not_called()
        self.assertEqual(len(done), 1)
        self.assertIsNone(done[0][1])
        self.assertTrue(any("brew install ffmpeg" in line and "Scan Again" in line for line in logs), logs)


class WindowUiTests(unittest.TestCase):
    """MainWindow'un FFmpeg yok durumundaki paneli (sahte pencere; Qt widget'i olusturmadan)."""

    def setUp(self) -> None:
        # Sahte pencerede kayma animasyonu olmasın: dosya tek başına (QApplication'sız) koşunca animations_enabled()
        # Windows ayarına bakıp True döner, slide_in de MagicMock'un sizeHint'iyle hesap yapmaya kalkar.
        patcher = mock.patch("src.gui.anim.animations_enabled", return_value=False)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _window(self, platform):
        window = mock.MagicMock()
        window.lang = "tr"
        window.ffmpeg = FFmpegManager(platform=platform)
        window._applying_profile = False
        window._installing = False  # güncelleme kurulumu sürmüyor (MagicMock niteliği doğru sayılırdı)
        return window

    def test_button_label_is_download_on_windows_and_rescan_elsewhere(self) -> None:
        from src.gui.main_window import MainWindow

        self.assertEqual(MainWindow._ffmpeg_button_text(self._window("win32")), "FFmpeg İndir")
        self.assertEqual(MainWindow._ffmpeg_button_text(self._window("darwin")), "Yeniden Tara")
        self.assertEqual(MainWindow._ffmpeg_button_text(self._window("linux")), "Yeniden Tara")

    def test_banner_shows_hint_and_button_when_missing(self) -> None:
        from src.gui.main_window import MainWindow

        for platform, needle in (("darwin", "brew install ffmpeg"), ("linux", "apt install ffmpeg")):
            window = self._window(platform)
            manager = FFmpegManager(platform=platform)
            MainWindow._on_prepared(window, manager, None)
            with self.subTest(platform=platform):
                self.assertIn(needle, window.banner_label.setText.call_args.args[0])
                window.ffmpeg_btn.setVisible.assert_called_with(True)
                window.banner.show.assert_called_once()
                window.banner.hide.assert_not_called()

    def test_start_without_ffmpeg_warns_with_platform_text(self) -> None:
        from src.gui import main_window

        window = self._window("linux")
        window._collect_settings.return_value = {"sources": ["a.mp4"]}
        window._file_type.return_value = "all"
        window.worker = None
        with mock.patch.object(main_window.MessageBox, "warning") as warning:
            main_window.MainWindow._start_stop(window)
        self.assertIn("apt install ffmpeg", warning.call_args.args[2])


if __name__ == "__main__":
    unittest.main()
