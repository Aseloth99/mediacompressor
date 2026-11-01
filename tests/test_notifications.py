"""Bildirimler: tek yol Qt'nin QSystemTrayIcon.showMessage'ı (Windows/macOS/Linux), tepsi yoksa macOS osascript / Linux
notify-send yedeği, Windows'ta ASLA alt süreç (winotify/PowerShell kalktı), hiçbir yolda çökme yok. Ayrıca tepsisiz masaüstü
koruması. (Ayrıntılı birim testleri: test_notify.py; bu dosya MediaCompressor'ın `show_toast` uyumluluk katmanı ve
uygulama düzeyi sözleşmeleri içindir.)"""

from __future__ import annotations

import os
import sys
import threading
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(__file__))
from _support import ROOT  # noqa: E402

from PyQt6.QtWidgets import QApplication, QSystemTrayIcon  # noqa: E402

from src.utils import notify  # noqa: E402
from src.utils.notify import build_linux_command, build_macos_command, show_toast  # noqa: E402

_qapp = QApplication.instance() or QApplication([])


class _Tray:
    """showMessage'ı olmayan eski sarmalayıcı tepsi (notify(title, message))."""

    def __init__(self, visible=True, fails=False):
        self._visible = visible
        self.fails = fails
        self.messages: list = []

    def isVisible(self) -> bool:
        return self._visible

    def notify(self, title, message) -> None:
        if self.fails:
            raise RuntimeError("tepsi bozuk")
        self.messages.append((title, message))


class _MessageTray:
    """QSystemTrayIcon.showMessage'lı sahte tepsi."""

    def __init__(self, visible=True):
        self._visible = visible
        self.shown: list = []

    def isVisible(self) -> bool:
        return self._visible

    def showMessage(self, title, body, icon, timeout) -> None:
        self.shown.append((title, body, icon, timeout))


class WindowsNeverSpawnsProcessTests(unittest.TestCase):
    """Eski winotify yolu (PowerShell alt süreci) kalktı: Windows'ta yalnızca tepsi kullanılır."""

    def test_windows_uses_the_tray_balloon_and_starts_no_process(self) -> None:
        tray = _MessageTray()

        def no_process(*args, **kwargs):
            raise AssertionError("Windows'ta alt süreç başlatılmamalı")

        with mock.patch.object(QSystemTrayIcon, "supportsMessages", staticmethod(lambda: True)), \
                mock.patch.object(notify.subprocess, "run", side_effect=no_process), \
                mock.patch.object(notify.subprocess, "Popen", side_effect=no_process):
            self.assertTrue(show_toast("Baslik", "Mesaj", "MediaCompressor", platform="win32", tray=tray))
        self.assertEqual(tray.shown[0][:2], ("Baslik", "Mesaj"))

    def test_windows_without_a_tray_returns_false_and_starts_no_process(self) -> None:
        runner = mock.Mock()
        self.assertFalse(show_toast("a", "b", platform="win32", tray=None, runner=runner))
        runner.assert_not_called()

    def test_the_module_never_imports_winotify(self) -> None:
        import subprocess

        code = (
            "import sys, importlib; sys.path.insert(0, %r); importlib.import_module('src.utils.notify'); "
            "print('winotify' in sys.modules)" % str(ROOT)
        )
        out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60,
                             env={**os.environ, "QT_QPA_PLATFORM": "offscreen"})
        self.assertEqual(out.stdout.strip(), "False", out.stderr)

    def test_the_old_toast_module_and_the_winotify_requirement_are_gone(self) -> None:
        self.assertFalse((ROOT / "src" / "utils" / "toast.py").exists())
        requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8").lower()
        self.assertNotIn("winotify", requirements)


class TrayToastTests(unittest.TestCase):
    def test_visible_tray_is_the_primary_path_on_every_platform(self) -> None:
        for platform in ("win32", "darwin", "linux"):
            tray = _MessageTray()
            runner = mock.Mock()
            with self.subTest(platform=platform), \
                    mock.patch.object(QSystemTrayIcon, "supportsMessages", staticmethod(lambda: True)):
                self.assertTrue(show_toast("T", "M", platform=platform, tray=tray, runner=runner,
                                           which=lambda name: "/usr/bin/" + name))
                self.assertEqual(tray.shown[0][:2], ("T", "M"))
                runner.assert_not_called()

    def test_generic_qsystemtrayicon_mock_uses_showmessage(self) -> None:
        tray = mock.Mock(spec=["isVisible", "showMessage"])
        tray.isVisible.return_value = True
        # Çevrimdışı (offscreen) platformda supportsMessages() False döner: gerçek platformdaki davranışı taklit et
        with mock.patch.object(QSystemTrayIcon, "supportsMessages", staticmethod(lambda: True)):
            self.assertTrue(show_toast("T", "M", platform="linux", tray=tray))
        self.assertEqual(tray.showMessage.call_args.args[:2], ("T", "M"))

    def test_wrapper_tray_without_showmessage_still_works(self) -> None:
        tray = _Tray()
        self.assertTrue(show_toast("T", "M", platform="linux", tray=tray))
        self.assertEqual(tray.messages, [("T", "M")])

    def test_failing_or_invisible_tray_falls_back_without_raising(self) -> None:
        for tray in (_Tray(visible=False), _Tray(fails=True), None):
            with self.subTest(tray=tray):
                self.assertFalse(show_toast("T", "M", platform="linux", tray=tray, which=lambda name: None))


class CliFallbackTests(unittest.TestCase):
    def test_linux_notify_send_command(self) -> None:
        cmd = build_linux_command("MediaCompressor", "Başlık", "Mesaj", icon="/ikon.png", timeout_ms=4000,
                                  notify_send="/usr/bin/notify-send")
        self.assertEqual(cmd, ["/usr/bin/notify-send", "-a", "MediaCompressor", "-t", "4000", "-i", "/ikon.png",
                               "--", "Başlık", "Mesaj"])

    def test_linux_without_notify_send_has_no_fallback(self) -> None:
        self.assertFalse(show_toast("a", "b", platform="linux", tray=None, which=lambda name: None))

    def test_linux_title_starting_with_dash_is_not_an_option(self) -> None:
        cmd = build_linux_command("app", "-t", "x")
        self.assertLess(cmd.index("--"), len(cmd) - 2)

    def test_macos_osascript_escapes_quotes_backslashes_and_newlines(self) -> None:
        cmd = build_macos_command('Ti"tle', 'a\\b "c"\nsatır')
        self.assertEqual(cmd[:2], ["osascript", "-e"])
        self.assertEqual(cmd[2], 'display notification "a\\\\b \\"c\\" satır" with title "Ti\\"tle"')

    def test_other_platforms_have_no_fallback(self) -> None:
        runner = mock.Mock()
        self.assertFalse(show_toast("a", "b", platform="freebsd13", runner=runner))
        runner.assert_not_called()

    def test_fallback_runs_in_the_background_and_reports_success(self) -> None:
        ran = threading.Event()
        calls: list = []

        def runner(cmd, **kwargs):
            calls.append((cmd, kwargs))
            ran.set()

        self.assertTrue(show_toast("T", "M", platform="linux", tray=None, runner=runner,
                                   which=lambda name: "/usr/bin/notify-send"))
        self.assertTrue(ran.wait(5))
        cmd, kwargs = calls[0]
        self.assertEqual(cmd[0], "/usr/bin/notify-send")
        self.assertIsNotNone(kwargs["timeout"])

    def test_runner_errors_do_not_propagate(self) -> None:
        done = threading.Event()

        def runner(cmd, **kwargs):
            done.set()
            raise OSError("calistirilamadi")

        self.assertFalse(show_toast("T", "M", platform="darwin", runner=runner))
        self.assertTrue(done.wait(5))


class AppIconAssetsTests(unittest.TestCase):
    def test_tray_balloon_icon_assets_exist(self) -> None:
        # Balonun simgesi uygulama penceresinin simgesidir (QSystemTrayIcon.showMessage); dosyalar pakette durmalı.
        icons = ROOT / "assets" / "icons"
        self.assertTrue((icons / "app_icon.png").is_file())
        self.assertTrue((icons / "app_icon.ico").is_file())


class NotificationSettingTests(unittest.TestCase):
    """Bildirim AYARI aynen kalır (varsayılan açık); mekanizma ayarı gözetir."""

    def test_setting_and_default_are_unchanged(self) -> None:
        from src.utils.config import DEFAULTS

        self.assertIs(DEFAULTS["show_notifications"], True)

    def test_disabled_setting_shows_nothing(self) -> None:
        tray = _MessageTray()
        notifier = notify.Notifier("MediaCompressor", tray_provider=lambda: tray, enabled_provider=lambda: False,
                                   supports_messages=lambda: True)
        self.assertFalse(notifier.notify("T", "M"))
        self.assertEqual(tray.shown, [])


class NoTrayDesktopTests(unittest.TestCase):
    """Sistem tepsisi olmayan masaustu (ör. eklentisiz GNOME): pencere gizlenip kaybolmamali."""

    def test_ensure_tray_refuses_when_no_system_tray(self) -> None:
        from src.gui import main_window

        window = mock.MagicMock()
        window.tray = None
        with mock.patch.object(main_window, "TrayIcon") as tray_cls:
            tray_cls.isSystemTrayAvailable.return_value = False
            self.assertFalse(main_window.MainWindow._ensure_tray(window))
        tray_cls.assert_not_called()
        self.assertIsNone(window.tray)

    def test_ensure_tray_creates_the_icon_when_available(self) -> None:
        from src.gui import main_window

        window = mock.MagicMock()
        window.tray = None
        with mock.patch.object(main_window, "TrayIcon") as tray_cls:
            tray_cls.isSystemTrayAvailable.return_value = True
            self.assertTrue(main_window.MainWindow._ensure_tray(window))
        tray_cls.assert_called_once()
        window.tray.show.assert_called_once()

    def test_close_really_closes_when_the_tray_host_is_gone(self) -> None:
        from src.gui import main_window

        window = mock.MagicMock()
        window._quitting = False
        window.config.get.return_value = True
        event = mock.Mock()
        with mock.patch.object(main_window, "TrayIcon") as tray_cls, \
                mock.patch.object(main_window.QApplication, "instance", return_value=None):
            tray_cls.isSystemTrayAvailable.return_value = False
            main_window.MainWindow.closeEvent(window, event)
        event.ignore.assert_not_called()
        event.accept.assert_called_once()

    def test_close_hides_to_tray_when_available(self) -> None:
        from src.gui import main_window

        window = mock.MagicMock()
        window._quitting = False
        window.config.get.return_value = True
        event = mock.Mock()
        with mock.patch.object(main_window, "TrayIcon") as tray_cls:
            tray_cls.isSystemTrayAvailable.return_value = True
            main_window.MainWindow.closeEvent(window, event)
        event.ignore.assert_called_once()
        window.hide.assert_called_once()


if __name__ == "__main__":
    unittest.main()
