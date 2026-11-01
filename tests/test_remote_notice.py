"""Uzaktan duyuru satiri: istek bicimi, duyuru gosterimi, durust guncelleme mesaji."""

from __future__ import annotations

import io
import json
import os
import pathlib
import sys
import unittest
import urllib.parse
from copy import deepcopy
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from PyQt6.QtWidgets import QApplication

from src.utils import remote_notice as rn
from src.utils.config import DEFAULTS, Config
from src.utils.updater import UpdateChecker


def _memory_config(lang: str = "tr") -> Config:
    cfg = object.__new__(Config)
    cfg.path, cfg._seed_path, cfg.data = "", None, deepcopy(DEFAULTS)
    cfg.data["language"] = lang
    cfg.save = lambda *a, **k: None
    return cfg


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class UpdaterTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _run(self, reply: dict, lang: str = "tr"):
        cfg = _memory_config(lang)
        checker = UpdateChecker(cfg)
        seen, notices = {}, []
        checker.notice_received.connect(notices.append)

        def fake_open(req, timeout=0, context=None):
            seen["url"] = req.full_url
            return _Resp(json.dumps(reply).encode())

        # the worker is a thread: run its body inline
        with mock.patch("urllib.request.urlopen", fake_open):
            from src.utils.updater import _UpdateCheckWorker

            checker._manual = False
            url_params = {"appName": checker.APP_NAME, "currentVersion": checker.current_version}
            captured = {}
            with mock.patch.object(_UpdateCheckWorker, "start", lambda self_: captured.setdefault("worker", self_)):
                checker.check_for_updates(False)
            worker = captured["worker"]
            worker.run()
        self.app.processEvents()
        return seen.get("url", ""), notices, cfg

    def test_update_request_carries_only_app_name_and_version(self):
        url, _, _ = self._run({"updateAvailable": False})
        query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        self.assertEqual(set(query), {"appName", "currentVersion"})

    def test_notice_arrives_without_an_update(self):
        _, notices, _ = self._run({"updateAvailable": False, "notice": {"id": "n1", "text": "Bakım var"}})
        self.assertEqual([n.id for n in notices], ["n1"])
        _, notices, _ = self._run({"updateAvailable": False})
        self.assertEqual(notices, [])

    def test_failed_manual_check_is_not_reported_as_up_to_date(self):
        from src.utils.locales import t

        checker = UpdateChecker(_memory_config("en"))
        shown = []
        checker._show_info = lambda title, text: shown.append((title, text))
        checker._manual = True
        checker._on_worker_network_error("offline")
        self.assertEqual(shown, [(t("update_check_title", "en"), t("update_check_failed_msg", "en"))])
        self.assertNotIn("up to date", shown[0][1].lower())

    def test_up_to_date_message_follows_the_language(self):
        checker = UpdateChecker(_memory_config("en"))
        shown = []
        checker._show_info = lambda title, text: shown.append((title, text))
        checker._manual = True
        checker._on_worker_result({"updateAvailable": False})
        self.assertIn("up to date", shown[0][1].lower())
        self.assertEqual(shown[0][0], "Update Check")


class WindowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _window(self):
        from src.gui.main_window import MainWindow
        from src.utils.theme_manager import ThemeManager

        theme = ThemeManager(self.app)
        theme.apply_from_setting("light")
        with mock.patch.object(MainWindow, "_prepare_ffmpeg", lambda *a, **k: None):
            return MainWindow(_memory_config(), theme, mock.MagicMock(), mock.MagicMock())

    def test_bar_hidden_until_notice_and_dismissal_is_remembered(self):
        w = self._window()
        w.show()
        self.app.processEvents()
        self.assertFalse(w.notice_bar.isVisible())
        w.show_notice(rn.Notice("n1", "Duyuru", ""))
        self.assertTrue(w.notice_bar.isVisible())
        w.notice_bar.dismiss()
        self.assertEqual(w.config.get("dismissed_notice"), "n1")
        w.show_notice(rn.Notice("n1", "Duyuru", ""))
        self.assertFalse(w.notice_bar.isVisible(), "a dismissed notice must not come back")
        w.show_notice(rn.Notice("n2", "Yeni", ""))
        self.assertTrue(w.notice_bar.isVisible())
        w.close()


if __name__ == "__main__":
    unittest.main()
