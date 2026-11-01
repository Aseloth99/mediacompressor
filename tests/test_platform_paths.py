"""Madde 2: kullanici dizinleri (Windows/macOS/Linux XDG), masaustu, surukle-birak yollari,
dosya yoneticisinde gosterme ve tek ornek adlari. Platform dogrudan parametre olarak verilir."""

from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(__file__))
from _support import TempDirTestCase  # noqa: E402

from PyQt6.QtCore import QUrl  # noqa: E402

from src.core.app_info import APP_ID, LOCK_NAME, SOCKET_NAME  # noqa: E402
from src.utils import helpers  # noqa: E402
from src.utils.platform_utils import LINUX, MACOS, OTHER, WINDOWS, detect  # noqa: E402

HOME = os.path.join(os.sep, "home", "ayse")


def j(*parts: str) -> str:
    return os.path.join(*parts)


def norm(paths) -> list[str]:
    """Qt Windows'ta '/' ayracli yol verir; karsilastirmadan once ana makinenin bicimine cevir."""
    return [os.path.normpath(p) for p in paths]


class DetectTests(unittest.TestCase):
    def test_sys_platform_values_and_normalised_names(self) -> None:
        cases = {
            "win32": WINDOWS, "windows": WINDOWS, "darwin": MACOS, "macos": MACOS,
            "linux": LINUX, "linux2": LINUX, "freebsd13": OTHER, "": OTHER,
        }
        for value, expected in cases.items():
            self.assertEqual(detect(value), expected, value)

    def test_default_is_the_running_platform(self) -> None:
        with mock.patch.object(sys, "platform", "darwin"):
            self.assertEqual(detect(), MACOS)


class UserDirTests(unittest.TestCase):
    def test_windows_uses_appdata_and_localappdata(self) -> None:
        env = {"APPDATA": r"C:\Users\ayse\AppData\Roaming", "LOCALAPPDATA": r"C:\Users\ayse\AppData\Local"}
        self.assertEqual(
            helpers.get_user_config_dir(platform="win32", env=env, home=HOME),
            j(env["APPDATA"], APP_ID),
        )
        self.assertEqual(
            helpers.get_user_data_dir(platform="win32", env=env, home=HOME),
            j(env["LOCALAPPDATA"], APP_ID),
        )
        self.assertEqual(
            helpers.get_user_log_dir(platform="win32", env=env, home=HOME),
            j(env["LOCALAPPDATA"], APP_ID, "logs"),
        )

    def test_windows_falls_back_to_profile_when_variables_are_missing(self) -> None:
        self.assertEqual(
            helpers.get_user_config_dir(platform="win32", env={}, home=HOME),
            j(HOME, "AppData", "Roaming", APP_ID),
        )
        self.assertEqual(
            helpers.get_user_data_dir(platform="win32", env={}, home=HOME),
            j(HOME, "AppData", "Local", APP_ID),
        )

    def test_macos_uses_library_and_ignores_xdg(self) -> None:
        env = {"XDG_CONFIG_HOME": "/x/cfg", "XDG_DATA_HOME": "/x/data"}
        support = j(HOME, "Library", "Application Support", APP_ID)
        self.assertEqual(helpers.get_user_config_dir(platform="darwin", env=env, home=HOME), support)
        self.assertEqual(helpers.get_user_data_dir(platform="darwin", env=env, home=HOME), support)
        self.assertEqual(
            helpers.get_user_log_dir(platform="darwin", env=env, home=HOME),
            j(HOME, "Library", "Logs", APP_ID),
        )

    def test_linux_honours_absolute_xdg_variables(self) -> None:
        cfg, data = os.path.abspath("xdg-cfg"), os.path.abspath("xdg-data")
        env = {"XDG_CONFIG_HOME": cfg, "XDG_DATA_HOME": data}
        self.assertEqual(helpers.get_user_config_dir(platform="linux", env=env, home=HOME), j(cfg, APP_ID))
        self.assertEqual(helpers.get_user_data_dir(platform="linux", env=env, home=HOME), j(data, APP_ID))
        self.assertEqual(
            helpers.get_user_log_dir(platform="linux", env=env, home=HOME), j(data, APP_ID, "logs"),
        )

    def test_linux_defaults_and_relative_xdg_values_are_ignored(self) -> None:
        self.assertEqual(
            helpers.get_user_config_dir(platform="linux", env={}, home=HOME), j(HOME, ".config", APP_ID),
        )
        self.assertEqual(
            helpers.get_user_data_dir(platform="linux", env={}, home=HOME), j(HOME, ".local", "share", APP_ID),
        )
        env = {"XDG_CONFIG_HOME": "goreli/yol", "XDG_DATA_HOME": ""}
        self.assertEqual(
            helpers.get_user_config_dir(platform="linux", env=env, home=HOME), j(HOME, ".config", APP_ID),
        )
        self.assertEqual(
            helpers.get_user_data_dir(platform="linux", env=env, home=HOME), j(HOME, ".local", "share", APP_ID),
        )

    def test_running_platform_resolves_inside_the_test_sandbox(self) -> None:
        # _support.py APPDATA/LOCALAPPDATA/XDG_*/HOME'u gecici dizine yonlendirir.
        sandbox = os.environ["XDG_CONFIG_HOME"]
        for path in (helpers.get_user_config_dir(), helpers.get_user_data_dir(), helpers.get_user_log_dir()):
            if sys.platform == "darwin":
                self.assertTrue(path.startswith(os.path.expanduser("~")), path)
            else:
                self.assertTrue(os.path.normcase(path).startswith(os.path.normcase(sandbox)), path)


class DesktopDirTests(TempDirTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.home = str(self.tmp / "ev")
        os.makedirs(self.home)

    def _user_dirs(self, text: str) -> None:
        cfg = os.path.join(self.home, ".config")
        os.makedirs(cfg, exist_ok=True)
        with open(os.path.join(cfg, "user-dirs.dirs"), "w", encoding="utf-8") as handle:
            handle.write(text)

    def test_linux_reads_localised_desktop_from_user_dirs(self) -> None:
        os.makedirs(os.path.join(self.home, "Masaüstü"))
        self._user_dirs('# yorum\nXDG_DOWNLOAD_DIR="$HOME/Indirilenler"\nXDG_DESKTOP_DIR="$HOME/Masaüstü"\n')
        self.assertEqual(
            helpers.desktop_dir(platform="linux", env={}, home=self.home), os.path.join(self.home, "Masaüstü"),
        )

    def test_linux_user_dirs_pointing_nowhere_falls_back_to_desktop_then_home(self) -> None:
        self._user_dirs('XDG_DESKTOP_DIR="$HOME/yok"\n')
        self.assertEqual(helpers.desktop_dir(platform="linux", env={}, home=self.home), self.home)
        os.makedirs(os.path.join(self.home, "Desktop"))
        self.assertEqual(
            helpers.desktop_dir(platform="linux", env={}, home=self.home), os.path.join(self.home, "Desktop"),
        )

    def test_user_dirs_honours_xdg_config_home(self) -> None:
        cfg = self.tmp / "baska-cfg"
        cfg.mkdir()
        (self.tmp / "masa").mkdir()
        (cfg / "user-dirs.dirs").write_text(f'XDG_DESKTOP_DIR="{self.tmp / "masa"}"\n', encoding="utf-8")
        env = {"XDG_CONFIG_HOME": str(cfg)}
        self.assertEqual(
            helpers.desktop_dir(platform="linux", env=env, home=self.home), str(self.tmp / "masa"),
        )

    def test_macos_uses_desktop_folder(self) -> None:
        os.makedirs(os.path.join(self.home, "Desktop"))
        self.assertEqual(
            helpers.desktop_dir(platform="darwin", env={}, home=self.home), os.path.join(self.home, "Desktop"),
        )

    def test_turkish_desktop_name_is_still_found_without_user_dirs(self) -> None:
        os.makedirs(os.path.join(self.home, "Masaüstü"))
        self.assertEqual(
            helpers.desktop_dir(platform="darwin", env={}, home=self.home), os.path.join(self.home, "Masaüstü"),
        )

    def test_windows_profile_variable_is_used_on_a_non_windows_host(self) -> None:
        profile = self.tmp / "profil"
        (profile / "Desktop").mkdir(parents=True)
        with mock.patch.object(helpers.os, "name", "posix"):
            self.assertEqual(
                helpers.desktop_dir(platform="win32", env={"USERPROFILE": str(profile)}, home=self.home),
                str(profile / "Desktop"),
            )


class DropPathTests(TempDirTestCase):
    def test_file_urls_with_spaces_and_unicode_are_decoded(self) -> None:
        folder = self.tmp / "Resimlerim ve Videolar"
        folder.mkdir()
        photo = folder / "TATİL.JPG"
        photo.write_bytes(b"x")
        urls = [QUrl.fromLocalFile(str(photo)), QUrl.fromLocalFile(str(folder))]
        self.assertEqual(norm(helpers.local_paths_from_drop(urls)), [str(photo), str(folder)])

    def test_posix_style_url_text_is_decoded(self) -> None:
        url = QUrl("file:///home/ayse/Foto%C4%9Fraflar/a%20b.MOV")
        self.assertTrue(helpers.local_paths_from_drop([url])[0].replace("\\", "/").endswith(
            "/home/ayse/Fotoğraflar/a b.MOV"))

    def test_non_local_urls_are_ignored(self) -> None:
        self.assertEqual(helpers.local_paths_from_drop([QUrl("https://example.com/a.jpg")]), [])

    def test_plain_text_fallback_accepts_file_uris_and_absolute_paths(self) -> None:
        target = self.tmp / "klasor"
        target.mkdir()
        text = f"# yorum\r\n{QUrl.fromLocalFile(str(target)).toString()}\r\n{target}\r\n\r\nrelative/yol\n"
        self.assertEqual(norm(helpers.local_paths_from_drop([], text)), [str(target)])

    def test_text_is_only_used_when_there_are_no_urls(self) -> None:
        url = QUrl.fromLocalFile(str(self.tmp))
        self.assertEqual(norm(helpers.local_paths_from_drop([url], "/baska/yol")), [str(self.tmp)])

    def test_file_reference_urls_and_foreign_hosts_are_dropped(self) -> None:
        text = "file:///.file/id=6571367.4321\nfile://baska-makine/paylasim/a.jpg\n"
        self.assertEqual(helpers.local_paths_from_drop([], text), [])

    def test_duplicates_are_removed_keeping_order(self) -> None:
        a, b = str(self.tmp / "a"), str(self.tmp / "b")
        urls = [QUrl.fromLocalFile(p) for p in (a, b, a)]
        self.assertEqual(norm(helpers.local_paths_from_drop(urls)), [a, b])

    def test_drop_zone_emits_paths_from_text_only_drops(self) -> None:
        from PyQt6.QtCore import QMimeData
        from src.gui.drop_zone import DropZone

        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication

        app = QApplication.instance() or QApplication([])
        type(self)._keep_app_alive = app  # yerelde bırakılırsa test bitince yok edilir; sonra yeniden kurmak çöker
        zone = DropZone()
        got: list = []
        zone.files_dropped.connect(got.append)
        mime = QMimeData()
        mime.setText(QUrl.fromLocalFile(str(self.tmp)).toString())
        event = mock.Mock()
        event.mimeData.return_value = mime
        zone.dropEvent(event)
        self.assertEqual([norm(g) for g in got], [[str(self.tmp)]])
        event.acceptProposedAction.assert_called_once()
        self.assertIsNotNone(app)


class RevealTests(TempDirTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.file = self.tmp / "klip.mp4"
        self.file.write_bytes(b"x")

    def test_windows_selects_file_in_explorer_and_opens_folders(self) -> None:
        popen, startfile = mock.Mock(), mock.Mock()
        self.assertTrue(helpers.reveal_in_file_manager(str(self.file), "win32", popen, startfile))
        self.assertEqual(popen.call_args.args[0], ["explorer", "/select,", str(self.file)])
        self.assertTrue(helpers.reveal_in_file_manager(str(self.tmp), "win32", popen, startfile))
        startfile.assert_called_once_with(str(self.tmp))

    def test_macos_uses_open_dash_r(self) -> None:
        popen = mock.Mock()
        self.assertTrue(helpers.reveal_in_file_manager(str(self.file), "darwin", popen))
        self.assertEqual(popen.call_args.args[0], ["open", "-R", str(self.file)])
        self.assertTrue(popen.call_args.kwargs["start_new_session"])

    def test_linux_opens_the_parent_folder_with_xdg_open(self) -> None:
        popen = mock.Mock()
        self.assertTrue(helpers.reveal_in_file_manager(str(self.file), "linux", popen))
        self.assertEqual(popen.call_args.args[0], ["xdg-open", str(self.tmp)])
        self.assertTrue(helpers.reveal_in_file_manager(str(self.tmp), "linux", popen))
        self.assertEqual(popen.call_args.args[0], ["xdg-open", str(self.tmp)])

    def test_missing_path_and_launcher_errors_return_false(self) -> None:
        popen = mock.Mock()
        self.assertFalse(helpers.reveal_in_file_manager(str(self.tmp / "yok"), "linux", popen))
        popen.assert_not_called()
        self.assertFalse(helpers.reveal_in_file_manager(str(self.file), "linux", mock.Mock(side_effect=OSError)))


class InstanceNameTests(unittest.TestCase):
    def test_windows_names_are_unchanged(self) -> None:
        self.assertEqual(helpers.instance_lock_path("win32", tempdir="T"), j("T", LOCK_NAME))
        self.assertEqual(helpers.instance_socket_name("win32"), SOCKET_NAME)

    def test_posix_names_are_per_user(self) -> None:
        stem, ext = os.path.splitext(LOCK_NAME)
        for platform in ("linux", "darwin"):
            self.assertEqual(
                helpers.instance_lock_path(platform, tempdir="T", uid=1000), j("T", f"{stem}-1000{ext}"),
            )
            self.assertEqual(helpers.instance_socket_name(platform, uid=1000), f"{SOCKET_NAME}-1000")
            self.assertNotEqual(helpers.instance_socket_name(platform, uid=1000), helpers.instance_socket_name(platform, uid=1001))


class AppBundleTests(unittest.TestCase):
    def test_bundle_is_found_from_the_inner_executable(self) -> None:
        exe = j(os.sep, "Applications", "Medya Sıkıştırıcı.app", "Contents", "MacOS", "Medya Sıkıştırıcı")
        bundle = helpers.app_bundle_dir(exe, "darwin")
        self.assertEqual(os.path.basename(bundle), "Medya Sıkıştırıcı.app")

    def test_not_a_bundle_or_other_platforms_give_none(self) -> None:
        self.assertIsNone(helpers.app_bundle_dir(j(os.sep, "usr", "bin", "python3"), "darwin"))
        self.assertIsNone(helpers.app_bundle_dir(j(os.sep, "x", "Y.app", "z"), "linux"))
        self.assertIsNone(helpers.app_bundle_dir(j("C:", "x", "Y.app", "z"), "win32"))


class ExtensionCaseTests(TempDirTestCase):
    """Buyuk/kucuk harf duyarli dosya sistemlerinde (Linux) uzantilar yine taranmali."""

    def test_collect_files_matches_uppercase_extensions(self) -> None:
        from src.core.job_manager import collect_files

        names = ["a.JPG", "b.Jpeg", "c.PNG", "d.MOV", "e.Mp4", "f.HEIC", "g.txt"]
        for name in names:
            (self.tmp / name).write_bytes(b"x")
        _, files = collect_files([str(self.tmp)], str(self.tmp / "cikti"), "all", False)
        self.assertEqual(sorted(os.path.basename(f) for f in files), sorted(names[:-1]))


if __name__ == "__main__":
    unittest.main()
