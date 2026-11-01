"""Güncelleme denetimi işçisi: sunucu hatası, ağ hatası ve bozuk yanıt ayrı sinyallerle bildirilir (ağ yok)."""

from __future__ import annotations

import os
import sys
import unittest
import urllib.error
from unittest import mock

sys.path.insert(0, os.path.dirname(__file__))
import _support  # noqa: E402,F401  (ortak test ortamı: ayarlar/günlükler geçici dizine yazılır)

from src.utils.updater import _UpdateCheckWorker  # noqa: E402


class UpdateCheckWorkerTests(unittest.TestCase):
    def _signals(self, side_effect=None, payload=b"{}"):
        worker = _UpdateCheckWorker("https://macik.com.tr/api/updates/check", None)
        seen = {"server": [], "network": [], "bad": 0, "error": [], "result": []}
        worker.server_error.connect(seen["server"].append)
        worker.network_error.connect(seen["network"].append)
        worker.bad_reply.connect(lambda: seen.__setitem__("bad", seen["bad"] + 1))
        worker.check_error.connect(seen["error"].append)
        worker.result_ready.connect(seen["result"].append)
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = payload
        with mock.patch("src.utils.updater.urllib.request.urlopen", side_effect=side_effect, return_value=response):
            worker.run()
        return seen

    def test_http_error_status_is_a_server_error_not_a_network_error(self) -> None:
        seen = self._signals(urllib.error.HTTPError("u", 503, "x", None, None))
        self.assertEqual(seen["server"], [503])
        self.assertEqual(seen["network"], [])

    def test_offline_and_timeouts_are_network_errors(self) -> None:
        for exc in (urllib.error.URLError("getaddrinfo failed"), urllib.error.URLError(TimeoutError("timed out"))):
            seen = self._signals(exc)
            self.assertEqual(len(seen["network"]), 1)
            self.assertEqual((seen["server"], seen["bad"]), ([], 0))

    def test_malformed_reply_is_a_bad_reply(self) -> None:
        for payload in (b"<html>", b"[1, 2]", b"\xff\xfe"):
            seen = self._signals(None, payload)
            self.assertEqual(seen["bad"], 1, payload)
            self.assertEqual(seen["result"], [])

    def test_valid_reply_is_delivered(self) -> None:
        seen = self._signals(None, b'{"updateAvailable": false}')
        self.assertEqual(seen["result"], [{"updateAvailable": False}])
        self.assertEqual((seen["server"], seen["network"], seen["bad"], seen["error"]), ([], [], 0, []))


if __name__ == "__main__":
    unittest.main()
