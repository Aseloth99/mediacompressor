"""Güncelleme indirme (URL, SHA-256, atomik yayın), betiksiz yerinde kurulum, zorunlu kurulum akışı, denetim yanıtı sağlamlığı."""

from __future__ import annotations

import ast
import hashlib
import io
import os
import pathlib
import sys
import threading
import unittest
import urllib.error
import zipfile
from unittest import mock

sys.path.insert(0, os.path.dirname(__file__))
from _support import ROOT, TempDirTestCase  # noqa: E402

from PyQt6.QtCore import QCoreApplication  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from src.core.app_info import EXE_NAME, VERSION  # noqa: E402
from src.utils import self_update, update_installer  # noqa: E402
from src.utils.update_installer import (  # noqa: E402
    LEGACY_EXE_NAME, PACKAGE_NAME, UpdateInstaller, exe_names, normalize_checksum, should_install_pending,
    should_show_pending_update, validate_download_url,
)

PAYLOAD = b"PK-sahte-guncelleme-" + bytes(range(256)) * 20
GOOD_SHA = hashlib.sha256(PAYLOAD).hexdigest()


def fake_pe(machine: int = 0x8664, payload: bytes = b"") -> bytes:
    head = bytearray(0x80)
    head[:2] = b"MZ"
    head[0x3C:0x40] = (0x80).to_bytes(4, "little")
    return bytes(head) + b"PE\0\0" + machine.to_bytes(2, "little") + payload


def make_zip(entries: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    return buf.getvalue()


class UrlValidationTests(unittest.TestCase):
    def test_accepts_https_on_trusted_host_and_subdomains(self) -> None:
        for url in ("https://macik.com.tr/dl/app.zip", "https://cdn.macik.com.tr/a/b.zip",
                    "https://MACIK.com.tr/x.zip", "http://localhost:8000/x.zip",
                    "https://127.0.0.1:8443/x.zip", "http://127.0.0.1/x.zip",
                    "https://macik.com.tr/Pages/AppDownload?slug=mediacompressor&file=MediaCompressor.exe"):
            self.assertTrue(validate_download_url(url)[0], url)

    def test_rejects_plain_http_foreign_hosts_and_lookalikes(self) -> None:
        for url in (
            "http://macik.com.tr/app.zip",              # https degil
            "https://evil.example.com/app.zip",         # yabanci sunucu
            "https://macik.com.tr.evil.com/app.zip",    # on ek taklidi
            "https://evilmacik.com.tr/app.zip",         # alan adi taklidi
            "https://macik.com.tr@evil.com/app.zip",    # kimlik bilgisi hilesi
            "ftp://macik.com.tr/app.zip", "file:///C:/x.zip", "https:///yok.zip", "", "macik.com.tr/x.zip",
        ):
            ok, reason = validate_download_url(url)
            self.assertFalse(ok, url)
            self.assertTrue(reason)


class ChecksumNormalizeTests(unittest.TestCase):
    def test_normalize(self) -> None:
        self.assertEqual(normalize_checksum(f" SHA256:{GOOD_SHA.upper()} "), GOOD_SHA)
        self.assertEqual(normalize_checksum(GOOD_SHA), GOOD_SHA)
        for bad in ("", None, "md5:abc", "zz" * 32, GOOD_SHA[:-1], GOOD_SHA + "0"):
            self.assertIsNone(normalize_checksum(bad), bad)


class FakeResponse:
    def __init__(self, data: bytes, url: str, chunk: int = 0, announced=None):
        self._buf = io.BytesIO(data)
        self._url = url
        self._chunk = chunk
        self.headers = {"Content-Length": str(len(data) if announced is None else announced)}

    def geturl(self) -> str:
        return self._url

    def read(self, n=-1):
        return self._buf.read(min(n, self._chunk) if self._chunk and n > 0 else n)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class DownloadTests(TempDirTestCase):
    URL = "https://macik.com.tr/dl/Medya.zip"

    def setUp(self) -> None:
        super().setUp()
        self.installer = UpdateInstaller()
        self.installer.temp_dir = str(self.tmp)
        self.failed: list[str] = []
        self.done: list[str] = []
        self.installer.download_failed.connect(self.failed.append)
        self.installer.download_complete.connect(self.done.append)

    def _download(self, url=None, checksum=GOOD_SHA, response=None):
        response = response or FakeResponse(PAYLOAD, url or self.URL)
        with mock.patch.object(update_installer.urllib.request, "urlopen", return_value=response) as urlopen:
            result = self.installer.download_update(url or self.URL, len(PAYLOAD), checksum)
        return result, urlopen

    def test_verified_download_is_published_atomically(self) -> None:
        ok, _ = self._download()
        self.assertTrue(ok)
        self.assertEqual(self.done, [str(self.tmp / PACKAGE_NAME)])
        self.assertEqual(self.listing(self.tmp), [PACKAGE_NAME])  # .part kalmadi
        self.assertEqual((self.tmp / PACKAGE_NAME).read_bytes(), PAYLOAD)

    def test_package_name_is_fixed_whatever_the_server_address_looks_like(self) -> None:
        # Sunucu adresi uzantisiz olabilir; paket turu dosyanin icerigine bakilarak anlasilir (self_update.sniff_package)
        for url in ("https://macik.com.tr/dl/Medya.zip", "https://macik.com.tr/dl/MediaCompressor.exe",
                    "https://macik.com.tr/Pages/AppDownload?slug=mediacompressor&file=MediaCompressor.exe",
                    "https://macik.com.tr/api/download?id=7"):
            self.done.clear()
            ok, _ = self._download(url=url)
            self.assertTrue(ok, url)
            self.assertEqual(self.done, [str(self.tmp / PACKAGE_NAME)], url)
        self.assertEqual(PACKAGE_NAME, "MediaCompressor_Update.pkg")

    def test_checksum_prefix_and_case_are_tolerated(self) -> None:
        ok, _ = self._download(checksum="sha256:" + GOOD_SHA.upper())
        self.assertTrue(ok)

    def test_mismatching_checksum_fails_and_leaves_no_file(self) -> None:
        ok, _ = self._download(checksum="0" * 64)
        self.assertFalse(ok)
        self.assertEqual(self.done, [])
        self.assertIn("checksum", self.failed[0])
        self.assertEqual(self.listing(self.tmp), [])  # dogrulanmamis dosya kurulabilir halde kalmaz

    def test_malformed_checksum_from_server_is_refused_before_any_download(self) -> None:
        for bad in ("md5:d41d8cd98f00b204e9800998ecf8427e", "xyz", "12345"):
            ok, urlopen = self._download(checksum=bad)
            self.assertFalse(ok, bad)
            urlopen.assert_not_called()
        self.assertEqual(self.listing(self.tmp), [])

    def test_missing_checksum_installs_but_logs_unverified_warning(self) -> None:
        with mock.patch.object(update_installer, "log_info") as log_info:
            ok, _ = self._download(checksum="")
        self.assertTrue(ok)
        self.assertIn("DOĞRULANAMADI", " ".join(str(c.args[0]) for c in log_info.call_args_list))

    def test_untrusted_or_insecure_urls_are_refused_without_network(self) -> None:
        for url in ("http://macik.com.tr/Medya.zip", "https://evil.example.com/Medya.zip"):
            ok, urlopen = self._download(url=url)
            self.assertFalse(ok, url)
            urlopen.assert_not_called()
            self.assertIn("Güvenli olmayan", self.failed[-1])
        self.assertEqual(self.done, [])

    def test_https_to_http_redirect_is_refused(self) -> None:
        ok, _ = self._download(response=FakeResponse(PAYLOAD, "http://macik.com.tr/Medya.zip"))
        self.assertFalse(ok)
        self.assertEqual(self.listing(self.tmp), [])

    def test_cancel_leaves_nothing_behind(self) -> None:
        response = FakeResponse(PAYLOAD, self.URL, chunk=100)
        original_read = response.read
        calls = {"n": 0}

        def read_then_cancel(n=-1):
            calls["n"] += 1
            if calls["n"] == 3:
                self.installer.cancel_download()
            return original_read(n)

        response.read = read_then_cancel
        ok, _ = self._download(response=response)
        self.assertFalse(ok)
        self.assertEqual(self.failed, ["cancelled"])
        self.assertEqual(self.listing(self.tmp), [])

    def test_truncated_download_is_refused_even_without_a_checksum(self) -> None:
        # http.client bağlantı erken kapanınca hata vermeden boş okur: kesik exe kurulmasın
        ok, _ = self._download(checksum="", response=FakeResponse(PAYLOAD[:1000], self.URL, announced=len(PAYLOAD)))
        self.assertFalse(ok)
        self.assertEqual(self.done, [])
        self.assertEqual(self.listing(self.tmp), [])
        self.assertIn("yarıda", self.failed[0])

    def test_a_cancelled_attempt_that_is_still_winding_down_cannot_disturb_the_next_download(self) -> None:
        blocked, release = threading.Event(), threading.Event()
        old_events: list[str] = []

        class Slow(FakeResponse):
            def read(self_inner, n=-1):  # noqa: N805
                blocked.set()
                release.wait(5)
                return super().read(n)

        self.qapp = QApplication.instance() or QApplication([])  # kuyruklu sinyaller için (referans tutulmazsa uygulama yok edilir)
        old = UpdateInstaller()
        old.temp_dir = str(self.tmp)
        old.download_failed.connect(old_events.append)
        # aynı UpdateInstaller üstünde ardışık iki deneme (ana pencerenin yaptığı gibi): eskisi bloklu
        first = threading.Thread(target=lambda: self._run_with(old, Slow(PAYLOAD, self.URL, chunk=100)))
        first.start()
        self.assertTrue(blocked.wait(5))
        old.cancel_download()
        ok, _ = self._download_with(old, FakeResponse(PAYLOAD, self.URL))
        self.assertTrue(ok, "yeni deneme, iptal edilen eskisinin bayrağından etkilenmemeli")
        release.set()
        first.join(10)
        QCoreApplication.processEvents()
        self.assertEqual(old_events, ["cancelled"])
        self.assertEqual((self.tmp / PACKAGE_NAME).read_bytes(), PAYLOAD, "eski deneme yeni dosyayı silmemeli")
        self.assertEqual(self.listing(self.tmp), [PACKAGE_NAME])

    def _run_with(self, installer, response):
        with mock.patch.object(update_installer.urllib.request, "urlopen", return_value=response):
            return installer.download_update(self.URL, len(PAYLOAD), GOOD_SHA)

    def _download_with(self, installer, response):
        return self._run_with(installer, response), None

    def test_error_texts_follow_the_ui_language(self) -> None:
        self.installer.lang = "en"
        ok, _ = self._download(checksum="0" * 64)
        self.assertFalse(ok)
        self.assertIn("integrity", self.failed[-1])
        self._download(url="https://evil.example.com/x.zip")
        self.assertEqual(self.failed[-1], "Unsafe download address.")
        self.installer.lang = "tr"
        self._download(url="https://evil.example.com/x.zip")
        self.assertEqual(self.failed[-1], "Güvenli olmayan indirme adresi.")

    def test_network_failures_get_friendly_localized_texts(self) -> None:
        self.installer.lang = "en"
        with mock.patch.object(update_installer.urllib.request, "urlopen", side_effect=urllib.error.URLError("getaddrinfo failed")):
            self.assertFalse(self.installer.download_update(self.URL, 10, GOOD_SHA))
        self.assertIn("internet connection", self.failed[-1])
        error = urllib.error.HTTPError(self.URL, 404, "Not Found", None, None)
        with mock.patch.object(update_installer.urllib.request, "urlopen", side_effect=error):
            self.assertFalse(self.installer.download_update(self.URL, 10, GOOD_SHA))
        self.assertIn("HTTP 404", self.failed[-1])
        self.installer.lang = "tr"
        with mock.patch.object(update_installer.urllib.request, "urlopen", side_effect=TimeoutError("timed out")):
            self.assertFalse(self.installer.download_update(self.URL, 10, GOOD_SHA))
        self.assertIn("bağlanılamadı", self.failed[-1])
        self.assertEqual(self.listing(self.tmp), [])

    def test_progress_signal_carries_sizes_beyond_two_gigabytes(self) -> None:
        seen: list[tuple] = []
        self.installer.download_progress.connect(lambda d, t, s: seen.append((d, t, s)))
        self.installer._emit_progress(5_000_000_000, 6_000_000_000, force=True)
        self.assertEqual(seen[0][:2], (5_000_000_000, 6_000_000_000))


class InstallTests(TempDirTestCase):
    """Betik yok: çalışan exe yeniden adlandırılır, yenisi yerine konur, yeni sürüm `--wait-pid` ile başlatılır.
    Eski betik testlerinin güvenceleri (Türkçe/boşluklu/%/' içeren yol, yeniden adlandırılmış exe, exe'siz paket sessiz
    başarı değil hata, yeni sürüm gerçekten başlatılır) burada gerçek self_update ile sınanır; yalnızca süreç başlatma taklit."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        super().setUp()
        self.folder = self.tmp / "Uygulama Klasörü %TEMP% Ali'nin"
        self.folder.mkdir()
        self.exe = self.folder / EXE_NAME
        self.exe.write_bytes(fake_pe(0x8664, b"-eski"))
        self.installer = UpdateInstaller()
        self.installer.temp_dir = str(self.tmp)
        self.events: list[str] = []
        self.failures: list[str] = []
        self.installer.install_started.connect(lambda: self.events.append("started"))
        self.installer.install_complete.connect(lambda: self.events.append("complete"))
        self.installer.install_failed.connect(self.failures.append)

    def _package(self, entries, name=PACKAGE_NAME) -> pathlib.Path:
        path = self.tmp / name
        path.write_bytes(entries if isinstance(entries, bytes) else make_zip(entries))
        return path

    def _install(self, package, exe=None, **kwargs):
        exe = exe or self.exe
        with mock.patch.object(sys, "frozen", True, create=True), mock.patch.object(sys, "executable", str(exe)), \
                mock.patch.object(self_update, "spawn") as spawn:
            started = self.installer.install_update(str(package), **kwargs)
            worker = self.installer._install_worker
            if worker is not None:
                worker.wait(10000)
        QCoreApplication.processEvents()
        return started, spawn

    def test_install_replaces_the_exe_keeps_the_old_one_and_relaunches_hidden(self) -> None:
        new = fake_pe(0x8664, b"-yeni")
        package = self._package({EXE_NAME: new, "okubeni.txt": b"x"})
        started, spawn = self._install(package, visible=False, old_version="1.0.0")
        self.assertTrue(started)
        self.assertEqual(self.events, ["started", "complete"])
        self.assertEqual(self.failures, [])
        self.assertEqual(self.exe.read_bytes(), new)
        self.assertEqual((self.folder / (EXE_NAME + ".old")).read_bytes(), fake_pe(0x8664, b"-eski"))
        self.assertEqual(sorted(p.name for p in self.folder.iterdir()), sorted([EXE_NAME, EXE_NAME + ".old"]),
                         "zip'ten yalnızca exe yazılır")
        self.assertFalse(package.exists(), "indirilen paket silinir")
        exe, args = spawn.call_args[0]
        self.assertEqual(exe, str(self.exe))
        self.assertEqual(list(args), ["--wait-pid", str(os.getpid()), "--updated", "1.0.0", "--minimized"])

    def test_a_visible_window_is_reopened_by_the_new_version(self) -> None:
        _started, spawn = self._install(self._package({EXE_NAME: fake_pe()}), visible=True)
        self.assertEqual(list(spawn.call_args[0][1])[-1], "--show-window")
        self.assertEqual(list(spawn.call_args[0][1])[2:4], ["--updated", VERSION], "varsayılan eski sürüm = çalışan sürüm")

    def test_raw_exe_package_without_zip_is_accepted_whatever_the_file_name(self) -> None:
        package = self._package(fake_pe(0x8664, b"-yeni"), name="MediaCompressor_Update.zip")  # adı yanıltıcı
        self._install(package)
        self.assertTrue(self.exe.read_bytes().endswith(b"-yeni"))

    def test_renamed_running_exe_is_replaced_by_the_packaged_exe(self) -> None:
        # Çalışan kopya elle yeniden adlandırılmış olabilir; paketin içindeki ad EXE_NAME'dir
        mine = self.folder / "Benim Sıkıştırıcım.exe"
        mine.write_bytes(fake_pe(0x8664, b"-eski"))
        self._install(self._package({EXE_NAME: fake_pe(0x8664, b"-yeni")}), exe=mine)
        self.assertTrue(mine.read_bytes().endswith(b"-yeni"))
        self.assertTrue((self.folder / "Benim Sıkıştırıcım.exe.old").exists())

    def test_legacy_package_exe_name_is_accepted(self) -> None:
        self._install(self._package({LEGACY_EXE_NAME: fake_pe(0x8664, b"-yeni")}))
        self.assertTrue(self.exe.read_bytes().endswith(b"-yeni"))
        self.assertEqual(self.failures, [])

    def test_exe_names_cover_package_running_and_legacy_names(self) -> None:
        self.assertEqual(exe_names(), [EXE_NAME, LEGACY_EXE_NAME])
        with mock.patch.object(sys, "frozen", True, create=True), \
                mock.patch.object(sys, "executable", str(self.folder / "Elle Adlandırılmış.exe")):
            self.assertEqual(exe_names(), [EXE_NAME, "Elle Adlandırılmış.exe", LEGACY_EXE_NAME])
        with mock.patch.object(sys, "frozen", True, create=True), mock.patch.object(sys, "executable", str(self.folder / EXE_NAME.lower())):
            self.assertEqual(exe_names(), [EXE_NAME, LEGACY_EXE_NAME], "büyük/küçük harf farkı yinelenmez")

    def test_package_without_the_exe_is_an_error_not_a_silent_success(self) -> None:
        before = self.exe.read_bytes()
        package = self._package({"readme.txt": b"x"})
        started, spawn = self._install(package)
        self.assertTrue(started)
        self.assertEqual(self.events, ["started"])
        self.assertEqual(self.failures, ["Pakette uygulamanın exe dosyası yok."])
        spawn.assert_not_called()
        self.assertEqual(self.exe.read_bytes(), before, "çalışan uygulama olduğu gibi kalır")
        self.assertEqual(sorted(p.name for p in self.folder.iterdir()), [EXE_NAME], "yarım dosya kalmaz")
        self.assertFalse(package.exists(), "başarısız paket temp'te birikmez")

    def test_install_errors_follow_the_ui_language(self) -> None:
        self.installer.lang = "en"
        self._install(self._package({"readme.txt": b"x"}))
        self.assertEqual(self.failures, ["The package does not contain the application's exe."])
        self.failures.clear()
        self._install(self._package(fake_pe(0x014C)))  # başka işlemci mimarisi
        self.assertEqual(self.failures, ["The package was built for a different processor architecture."])

    def test_every_package_error_code_has_a_translation_in_both_languages(self) -> None:
        from src.utils.locales import LOCALES

        source = (ROOT / "src" / "utils" / "self_update.py").read_text(encoding="utf-8")
        codes = {
            node.args[1].value for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "PackageError"
            and len(node.args) > 1 and isinstance(node.args[1], ast.Constant)
        }
        self.assertEqual(codes, {"read", "not_package", "too_big", "no_exe", "bad_zip", "write", "not_pe", "arch",
                                 "not_writable", "swap", "swap2", "spawn"})
        for code in codes:
            for lang in ("tr", "en"):
                self.assertIn(f"update_pkg_{code}", LOCALES[lang], (code, lang))

    def test_a_process_that_updated_itself_is_marked_as_relaunching_only_on_success(self) -> None:
        # Kendini güncelleyip çıkan süreç `confirm_healthy` çağırmaz (yan dosyalar yeni sürümün denemesine ait)
        self.assertFalse(self.installer.relaunching)
        self._install(self._package({"readme.txt": b"x"}))
        self.assertFalse(self.installer.relaunching, "başarısız kurulum uygulamayı çalışır bırakır")
        self._install(self._package({EXE_NAME: fake_pe()}))
        self.assertTrue(self.installer.relaunching)

    def test_only_one_install_runs_at_a_time(self) -> None:
        gate = threading.Event()
        with mock.patch.object(sys, "frozen", True, create=True), mock.patch.object(sys, "executable", str(self.exe)), \
                mock.patch.object(self_update, "install_and_relaunch", side_effect=lambda *a, **k: gate.wait(5)):
            package = self._package(fake_pe())
            self.assertTrue(self.installer.install_update(str(package)))
            self.assertTrue(self.installer.installing())
            self.assertFalse(self.installer.install_update(str(package)), "ikinci kurulum başlamaz")
            gate.set()
            self.installer._install_worker.wait(5000)
        QCoreApplication.processEvents()
        self.assertEqual(self.events, ["started", "complete"])

    def test_install_does_not_freeze_the_caller(self) -> None:
        gate = threading.Event()
        with mock.patch.object(sys, "frozen", True, create=True), mock.patch.object(sys, "executable", str(self.exe)), \
                mock.patch.object(self_update, "install_and_relaunch", side_effect=lambda *a, **k: gate.wait(5)):
            self.assertTrue(self.installer.install_update(str(self._package(fake_pe()))))
            self.assertEqual(self.events, ["started"], "install_update dönmüş, iş arka planda sürüyor")
            gate.set()
            self.installer._install_worker.wait(5000)

    def test_missing_package_is_reported_in_the_ui_language(self) -> None:
        self.assertFalse(self.installer.install_update(str(self.tmp / "yok.pkg")))
        self.assertEqual(self.failures, ["Güncelleme dosyası bulunamadı."])
        self.installer.lang = "en"
        self.assertFalse(self.installer.install_update(str(self.tmp / "yok.pkg")))
        self.assertEqual(self.failures[-1], "The update file was not found.")

    def test_running_from_source_is_refused_inline_and_not_even_downloaded(self) -> None:
        package = self._package(fake_pe())
        self.assertFalse(getattr(sys, "frozen", False))
        ok, message = self.installer.preflight()
        self.assertFalse(ok)
        self.assertIn("paketlenmiş", message)
        self.assertFalse(self.installer.install_update(str(package)))
        self.assertIn("paketlenmiş", self.failures[-1])
        self.installer.lang = "en"
        self.assertIn("packaged app", self.installer.preflight()[1])

    def test_non_windows_is_refused(self) -> None:
        with mock.patch.object(update_installer.os, "name", "posix"):
            ok, message = self.installer.install_support()
        self.assertFalse(ok)
        self.assertIn("desteklenm", message)

    def test_preflight_refuses_a_folder_that_cannot_be_written_before_any_download(self) -> None:
        with mock.patch.object(sys, "frozen", True, create=True), mock.patch.object(sys, "executable", str(self.exe)):
            self.assertEqual(self.installer.preflight(), (True, ""))
            denied = self_update.PackageError("x", "not_writable", str(self.folder))
            with mock.patch.object(self_update, "check_writable", side_effect=denied):
                ok, message = self.installer.preflight()
                self.assertFalse(ok)
                self.assertIn("Uygulamanın bulunduğu klasöre yazılamıyor", message)
                self.assertIn("Uygulama Klasörü", message)
                self.assertIn("taşıyıp", message)
                self.installer.lang = "en"
                self.assertIn("Move the app to a writable folder", self.installer.preflight()[1])

    def test_preflight_leaves_no_probe_file_behind(self) -> None:
        with mock.patch.object(sys, "frozen", True, create=True), mock.patch.object(sys, "executable", str(self.exe)):
            self.assertTrue(self.installer.preflight()[0])
        self.assertEqual([p.name for p in self.folder.iterdir()], [EXE_NAME])

    @staticmethod
    def _code_strings(path) -> list[str]:
        """Kaynağın metin sabitleri ve adları (belge dizgileri hariç: onlar "taskkill yok" diyebilir)."""
        tree = ast.parse(path.read_text(encoding="utf-8"))
        docs = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
                first = node.body[0]
                if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                    docs.add(id(first.value))
        found = [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs]
        found += [n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.ClassDef))]
        found += [n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)]
        return [text.lower() for text in found]

    def test_no_batch_script_taskkill_or_powershell_is_left_in_the_update_path(self) -> None:
        for relative in ("src/utils/update_installer.py", "src/utils/self_update.py", "src/gui/main_window.py",
                         "src/gui/update_dialog.py", "main.py"):
            strings = self._code_strings(ROOT / relative)
            for needle in ("taskkill", "powershell", "expand-archive", "xcopy", "winrar", "cmd.exe", ".bat", "updater_script"):
                hits = [text for text in strings if needle in text]
                self.assertEqual(hits, [], f"{relative}: {needle}")


class LocalServerEndToEndTests(TempDirTestCase):
    """Gerçek urllib + yerel HTTP sunucusu (macik.com.tr'ye istek yok): uzantısız adres, zip/exe paketi, yönlendirme,
    kesik indirme; ardından gerçek self_update ile (süreç başlatma taklit) kurulum."""

    @classmethod
    def setUpClass(cls) -> None:
        import http.server

        cls.app = QApplication.instance() or QApplication([])
        cls.new_exe = fake_pe(0x8664, b"-sunucudan-gelen-yeni")
        cls.zip_bytes = make_zip({"MediaCompressor.exe": cls.new_exe})
        outer = cls

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):  # sessiz
                pass

            def do_GET(self):  # noqa: N802
                route = self.path.split("?")[0]
                if route == "/Pages/AppDownload":  # uzantısız, sorgulu adres (macik.com.tr'nin gerçek biçimi)
                    body = outer.zip_bytes
                elif route == "/raw":
                    body = outer.new_exe
                elif route == "/redirect":
                    self.send_response(302)
                    self.send_header("Location", "/Pages/AppDownload?slug=mediacompressor&file=MediaCompressor.exe")
                    self.end_headers()
                    return
                elif route == "/truncated":
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(outer.zip_bytes) + 5000))
                    self.end_headers()
                    self.wfile.write(outer.zip_bytes)
                    self.wfile.flush()
                    self.close_connection = True
                    return
                else:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self) -> None:
        super().setUp()
        self.installer = UpdateInstaller()
        self.installer.temp_dir = str(self.tmp)
        self.failed: list[str] = []
        self.done: list[str] = []
        self.installer.download_failed.connect(self.failed.append)
        self.installer.download_complete.connect(self.done.append)

    def _url(self, path: str) -> str:
        return f"http://127.0.0.1:{self.port}{path}"

    def test_extension_less_zip_download_verifies_the_checksum_and_installs(self) -> None:
        url = self._url("/Pages/AppDownload?slug=mediacompressor&file=MediaCompressor.exe")
        sha = hashlib.sha256(self.zip_bytes).hexdigest()
        self.assertTrue(self.installer.download_update(url, len(self.zip_bytes), "sha256:" + sha))
        self.assertEqual(self.done, [str(self.tmp / PACKAGE_NAME)])
        self.assertEqual(self.listing(self.tmp), [PACKAGE_NAME])
        # kurulum: gerçek self_update, çalışan exe = sahte "eski sürüm"
        folder = self.tmp / "uygulama"
        folder.mkdir()
        exe = folder / EXE_NAME
        exe.write_bytes(fake_pe(0x8664, b"-eski"))
        with mock.patch.object(sys, "frozen", True, create=True), mock.patch.object(sys, "executable", str(exe)), \
                mock.patch.object(self_update, "spawn") as spawn:
            self.assertTrue(self.installer.install_update(self.done[0], visible=False, old_version="1.0.0"))
            self.installer._install_worker.wait(10000)
        QCoreApplication.processEvents()
        self.assertEqual(exe.read_bytes(), self.new_exe)
        self.assertTrue((folder / (EXE_NAME + ".old")).exists())
        self.assertEqual(list(spawn.call_args[0][1])[2:], ["--updated", "1.0.0", "--minimized"])

    def test_raw_exe_and_redirects_work_and_a_wrong_checksum_is_refused(self) -> None:
        sha_exe = hashlib.sha256(self.new_exe).hexdigest()
        self.assertTrue(self.installer.download_update(self._url("/raw"), len(self.new_exe), sha_exe))
        self.assertEqual((self.tmp / PACKAGE_NAME).read_bytes(), self.new_exe)
        sha_zip = hashlib.sha256(self.zip_bytes).hexdigest()
        self.assertTrue(self.installer.download_update(self._url("/redirect"), None, sha_zip), "yönlendirme izlenir")
        self.assertEqual((self.tmp / PACKAGE_NAME).read_bytes(), self.zip_bytes)
        self.assertFalse(self.installer.download_update(self._url("/Pages/AppDownload"), None, "0" * 64))
        self.assertEqual(self.listing(self.tmp), [], "doğrulanmamış paket kalmaz")

    def test_server_errors_and_cut_connections_are_reported_without_leftovers(self) -> None:
        self.installer.lang = "en"
        self.assertFalse(self.installer.download_update(self._url("/yok"), None, None))
        self.assertIn("HTTP 404", self.failed[-1])
        self.assertFalse(self.installer.download_update(self._url("/truncated"), None, None))
        self.assertIn("cut off", self.failed[-1], "sağlama toplamı olmasa da kesik indirme kurulmaz")
        self.assertEqual(self.listing(self.tmp), [])
        self.assertEqual(self.done, [])


class PendingInstallPolicyTests(unittest.TestCase):
    def test_policy_truth_table(self) -> None:
        # (bekleyen var, iptal, zorunlu) -> beklenen
        cases = {
            (True, False, False): True,
            (True, False, True): True,
            (True, True, True): True,    # zorunlu: iptal edilse bile kurulur (eskiden atlanirdi)
            (True, True, False): False,  # normal guncelleme: davranis ayni
            (False, False, True): False,
            (False, True, True): False,
        }
        for (pending, cancelled, mandatory), expected in cases.items():
            self.assertEqual(should_install_pending(pending, cancelled, mandatory), expected)
            self.assertEqual(should_show_pending_update(pending, cancelled, mandatory), expected)


class MainWindowUpdateFlowTests(unittest.TestCase):
    def _window(self, **attrs):
        window = mock.MagicMock()
        window.lang = "tr"
        window._pending_install = None
        window._pending_install_mandatory = False
        window._pending_update = None
        window._upd_mandatory = False
        window._installing = False
        window._download_wanted = True
        window._job_running.return_value = False
        for key, value in attrs.items():
            setattr(window, key, value)
        return window

    def _finish(self, window, cancelled):
        from src.gui import main_window

        main_window.MainWindow._on_job_finished(window, {"cancelled": cancelled, "ok": 1, "skip": 0, "fail": 0})

    def test_mandatory_install_runs_even_after_cancelled_job(self) -> None:
        window = self._window(_pending_install="C:/tmp/u.pkg", _pending_install_mandatory=True)
        self._finish(window, cancelled=True)
        # iş az önce bitti: işçi iş parçacığı henüz çıkmamış olabilir, bu yüzden meşguliyet yeniden sorulmaz
        window._begin_install.assert_called_once_with("C:/tmp/u.pkg", check_busy=False)
        self.assertIsNone(window._pending_install)

    def test_regular_install_still_waits_after_cancelled_job(self) -> None:
        window = self._window(_pending_install="C:/tmp/u.pkg")
        self._finish(window, cancelled=True)
        window._begin_install.assert_not_called()
        self.assertEqual(window._pending_install, "C:/tmp/u.pkg")

    def test_regular_install_runs_after_completed_job(self) -> None:
        window = self._window(_pending_install="C:/tmp/u.pkg")
        self._finish(window, cancelled=False)
        window._begin_install.assert_called_once_with("C:/tmp/u.pkg", check_busy=False)

    def test_mandatory_update_is_downloaded_after_cancel_and_stays_retryable(self) -> None:
        payload = ("9.9.9", "https://macik.com.tr/u.zip", "", True, 10, GOOD_SHA)
        window = self._window(_pending_update=payload)
        self._finish(window, cancelled=True)
        window._begin_silent_update.assert_called_once_with(payload, mandatory=True)
        self.assertEqual(window._pending_update, payload, "indirme başarısız olursa pill/tepsi satırı çalışmaya devam eder")

    def test_optional_update_is_not_started_after_cancel(self) -> None:
        payload = ("9.9.9", "https://macik.com.tr/u.zip", "", False, 10, GOOD_SHA)
        window = self._window(_pending_update=payload)
        self._finish(window, cancelled=True)
        window._begin_silent_update.assert_not_called()

    def test_download_complete_during_job_remembers_mandatory_flag(self) -> None:
        from src.gui import main_window

        window = self._window(_upd_mandatory=True)
        window._job_running.return_value = True
        window.update_dialog = None
        main_window.MainWindow._on_dl_complete(window, "C:/tmp/u.pkg")
        self.assertEqual(window._pending_install, "C:/tmp/u.pkg")
        self.assertTrue(window._pending_install_mandatory)
        window._begin_install.assert_not_called()

    def test_download_that_finishes_after_the_user_cancelled_is_discarded_not_installed(self) -> None:
        from src.gui import main_window

        window = self._window(_download_wanted=False)
        main_window.MainWindow._on_dl_complete(window, "C:/tmp/u.pkg")
        window._begin_install.assert_not_called()
        window.installer.cleanup.assert_called_once()
        self.assertIsNone(window._pending_install)

    def test_install_rechecks_that_no_job_started_in_the_meantime(self) -> None:
        from src.gui import main_window

        window = self._window()
        window._job_running.return_value = True
        main_window.MainWindow._begin_install(window, "C:/tmp/u.pkg")
        window.installer.install_update.assert_not_called()
        self.assertEqual(window._pending_install, "C:/tmp/u.pkg")
        self.assertFalse(window._installing)

    def test_install_runs_hidden_when_the_window_is_in_the_tray_and_visible_otherwise(self) -> None:
        from src.gui import main_window

        for shown, minimized, expect_visible in ((False, False, False), (True, True, False), (True, False, True)):
            window = self._window()
            window.isVisible.return_value = shown
            window.isMinimized.return_value = minimized
            main_window.MainWindow._begin_install(window, "C:/tmp/u.pkg")
            window.installer.install_update.assert_called_once_with("C:/tmp/u.pkg", visible=expect_visible, old_version=VERSION)
            self.assertTrue(window._installing)

    def test_successful_install_quits_cleanly_not_by_killing(self) -> None:
        from src.gui import main_window

        window = self._window()
        with mock.patch.object(main_window.QTimer, "singleShot") as single_shot:
            main_window.MainWindow._on_install_complete(window)
        single_shot.assert_called_once_with(0, window._quit_for_update)

    def test_show_dialog_opens_the_update_window_for_the_offered_version(self) -> None:
        from src.gui import main_window

        window = self._window()
        window._download_active.return_value = False
        with mock.patch.object(main_window, "UpdateDialog") as dialog_cls:
            main_window.MainWindow._show_update_dialog(window, "9.9.9", "https://macik.com.tr/u.zip", "notlar", False, 10, GOOD_SHA)
        dialog_cls.assert_called_once()
        self.assertEqual(dialog_cls.call_args.args[:3], ("9.9.9", "notlar", False))
        self.assertEqual(dialog_cls.call_args.kwargs["size"], 10)
        dialog_cls.return_value.open.assert_called_once()
        self.assertEqual(window._upd, ("https://macik.com.tr/u.zip", 10, GOOD_SHA))

    def test_restart_after_a_cancelled_job_installs_the_already_downloaded_package_without_downloading_again(self) -> None:
        from src.gui import main_window

        window = self._window(_pending_install="C:/tmp/u.pkg", _upd=("https://macik.com.tr/u.zip", 10, GOOD_SHA))
        window._update_busy.return_value = False
        main_window.MainWindow._start_download(window)
        window._begin_install.assert_called_once_with("C:/tmp/u.pkg")
        self.assertIsNone(window._pending_install)
        window.installer.preflight.assert_not_called()


class UpdateCheckerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def _checker(self):
        from src.utils.updater import UpdateChecker

        config = mock.MagicMock()
        config.get.side_effect = lambda key, default=None: {"language": "tr"}.get(key, default)
        checker = UpdateChecker(config)
        offered: list = []
        completed: list = []
        failed: list = []
        checker.update_available.connect(lambda *a: offered.append(a))
        checker.check_complete.connect(completed.append)
        checker.check_failed.connect(lambda: failed.append(1))
        return checker, offered, completed, failed

    def _data(self, url="https://macik.com.tr/u.zip", **extra):
        data = {"updateAvailable": True, "version": "99.0.0", "download_url": url,
                "isMandatory": False, "fileSize": 10, "checksum": GOOD_SHA}
        data.update(extra)
        return data

    def test_untrusted_url_is_never_offered_to_the_user(self) -> None:
        checker, offered, completed, failed = self._checker()
        checker._on_worker_result(self._data("http://evil.example.com/u.zip"))
        self.assertEqual(offered, [])
        # sunucu "güncelleme var" dedi ama kabul edilemez bir adres verdi: "güncel" demek yanıltıcı olurdu
        self.assertEqual((completed, failed), ([], [1]))

    def test_trusted_url_is_offered(self) -> None:
        checker, offered, completed, failed = self._checker()
        checker._on_worker_result(self._data("https://macik.com.tr/u.zip"))
        self.assertEqual(len(offered), 1)
        self.assertEqual(offered[0][1], "https://macik.com.tr/u.zip")
        self.assertEqual((completed, failed), ([True], []))

    def test_extension_less_server_address_is_offered(self) -> None:
        checker, offered, *_ = self._checker()
        url = "https://macik.com.tr/Pages/AppDownload?slug=mediacompressor&file=MediaCompressor.exe"
        checker._on_worker_result(self._data(url))
        self.assertEqual(offered[0][1], url)

    def test_failed_checks_emit_check_failed_instead_of_pretending_to_be_up_to_date(self) -> None:
        checker, _offered, completed, failed = self._checker()
        checker._on_worker_network_error("getaddrinfo failed")
        checker._on_worker_server_error(503)
        checker._on_worker_bad_reply()
        checker._on_worker_error("beklenmeyen")
        self.assertEqual(len(failed), 4)
        self.assertEqual(completed, [], "başarısız denetim 'güncel' sayılmaz (ayarlarda 'Güncel' görünüyordu)")

    def test_incomplete_positive_reply_is_a_failure_not_up_to_date(self) -> None:
        checker, offered, completed, failed = self._checker()
        checker._on_worker_result(self._data(download_url=""))
        checker._on_worker_result(self._data(version=""))
        self.assertEqual((offered, completed, len(failed)), ([], [], 2))

    def test_up_to_date_and_successful_checks_complete_and_stamp_the_time(self) -> None:
        checker, offered, completed, failed = self._checker()
        checker._on_worker_result({"updateAvailable": False})
        checker._on_worker_result(self._data(version=VERSION))  # aynı sürüm
        self.assertEqual((offered, completed, failed), ([], [False, False], []))
        stamps = [c for c in checker.config.set.call_args_list if c.args[0] == "last_update_check"]
        self.assertEqual(len(stamps), 2)

    def test_a_found_update_does_not_stamp_the_check_time(self) -> None:
        # Güncelleme bekliyorken uygulama kapanıp açılırsa yeniden denetlenmeli; yoksa "Güncelle" düğmesi/tepsi satırı
        # 24 saat boyunca kaybolurdu.
        checker, offered, completed, failed = self._checker()
        checker._on_worker_result(self._data())
        self.assertEqual((len(offered), completed, failed), (1, [True], []))
        stamps = [c for c in checker.config.set.call_args_list if c.args[0] == "last_update_check"]
        self.assertEqual(stamps, [])

    def test_json_field_types_from_the_server_are_handled(self) -> None:
        checker, offered, completed, failed = self._checker()
        # "false" metni Python'da doğrudur: eskiden "güncelleme yok" yanıtı güncelleme sanılıyordu
        checker._on_worker_result(self._data(updateAvailable="false"))
        self.assertEqual((offered, completed), ([], [False]))
        checker._on_worker_result(self._data(isMandatory="false", fileSize="123456", version="v100.0.0"))
        self.assertEqual(offered[-1][0], "100.0.0")
        self.assertEqual((offered[-1][3], offered[-1][4]), (False, 123456))
        checker._on_worker_result(self._data(isMandatory="true", fileSize=7_000_000_000))
        self.assertEqual((offered[-1][3], offered[-1][4]), (True, 7_000_000_000), "2 GB üstü boyut sinyale sığar")
        checker._on_worker_result(self._data(fileSize=None, release_notes=None, checksum=None))
        self.assertEqual(offered[-1][2:6:1], ("", False, 0, ""))
        checker._on_worker_result(self._data(fileSize="büyük", release_notes=["a"], isMandatory=1))
        self.assertEqual((offered[-1][3], offered[-1][4]), (True, 0))
        self.assertEqual(failed, [])

    def test_version_comparison_tolerates_suffixes_and_junk(self) -> None:
        checker, *_ = self._checker()
        compare = checker._compare_versions
        self.assertEqual(compare("1.2.3", "1.2.3"), 0)
        self.assertEqual(compare("1.10.0", "1.9.9"), 1)
        self.assertEqual(compare("1.2", "1.2.1"), -1)
        self.assertEqual(compare("2.0.0-beta", "1.9.0"), 1)
        self.assertEqual(compare("v3.0", "2.9.9"), 1)
        self.assertEqual(compare("abc", "1.0.0"), 0)

    def test_a_version_that_was_rolled_back_is_not_offered_again(self) -> None:
        checker, offered, completed, failed = self._checker()
        with mock.patch.object(checker, "_skipped_version", return_value="99.0.0"):
            checker._on_worker_result(self._data())
        self.assertEqual((offered, completed, failed), ([], [False], []))
        with mock.patch.object(checker, "_skipped_version", return_value="98.0.0"):
            checker._on_worker_result(self._data())
        self.assertEqual(len(offered), 1, "daha yeni bir sürüm yine sunulur")

    def test_skipped_version_is_read_from_the_exe_only_when_packaged(self) -> None:
        from src.utils.updater import UpdateChecker

        checker, *_ = self._checker()
        with mock.patch.object(self_update, "skipped_version", return_value="9.9.9") as skipped:
            self.assertIsNone(checker._skipped_version())
            skipped.assert_not_called()
            with mock.patch.object(sys, "frozen", True, create=True):
                self.assertEqual(checker._skipped_version(), "9.9.9")
            skipped.assert_called_once_with(sys.executable)
        self.assertTrue(hasattr(UpdateChecker, "_skipped_version"))


if __name__ == "__main__":
    unittest.main()
