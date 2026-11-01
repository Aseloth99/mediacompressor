"""Güncelleme indirme ve yerinde kurulum.

İndirme: yalnızca https + güvenilen sunucu, SHA-256 doğrulaması, ``%TEMP%\\MediaCompressor_Update.pkg`` olarak atomik yayın.
Kurulum: betik/taskkill/PowerShell yok — çalışan exe yeniden adlandırılıp yenisi yerine konur, yeni sürüm
``--wait-pid`` ile başlatılır (bkz. ``self_update.py``). Kurulum bir iş parçacığında yürür, sonuç sinyalle gelir.
"""

from __future__ import annotations

import glob
import hashlib
import hmac
import http.client
import os
import re
import ssl
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from typing import Optional

from PyQt6.QtCore import QObject, pyqtSignal

from ..core.app_info import APP_ID, EXE_NAME, UPDATE_ALLOWED_HOSTS, VERSION
from ..core.workers import DaemonWorker
from . import self_update
from .locales import t
from .logger import log_error, log_info

_LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1")
_SHA256_HEX = re.compile(r"[0-9a-f]{64}")
# Eski/dev derlemelerde çalışan exe bu adla olabilir (spec çıktısı, pack_dist yeniden adlandırmadan önce).
LEGACY_EXE_NAME = "MedyaSikistirici.exe"
# İndirilen paket: sunucu adresi uzantısız olabilir ve paket ya exe ya zip'tir (içeriğe bakılır), bu yüzden sabit ad.
PACKAGE_NAME = f"{APP_ID}_Update.pkg"


def validate_download_url(url: str) -> tuple[bool, str]:
    """Sunucunun verdiği indirme adresini denetle: https + güvenilen sunucu.

    http yalnızca yerel geliştirme sunucusuna (localhost/127.0.0.1/::1) izinlidir. Sunucu adı
    UPDATE_ALLOWED_HOSTS içindeki bir alan adı veya alt alan adı olmalıdır; ``https://izinli@kotu``
    gibi kimlik bilgili adreslerde gerçek sunucu (hostname) denetlenir.
    """
    try:
        parsed = urllib.parse.urlparse(str(url or "").strip())
        host = (parsed.hostname or "").lower()
    except ValueError:
        return False, "adres çözümlenemedi"
    if not host:
        return False, "adreste sunucu adı yok"
    local = host in _LOCAL_HOSTS
    if parsed.scheme == "http" and local:
        return True, ""
    if parsed.scheme != "https":
        return False, "yalnızca https adresleri kabul edilir"
    if local:
        return True, ""
    for allowed in UPDATE_ALLOWED_HOSTS:
        allowed = allowed.lower()
        if host == allowed or host.endswith("." + allowed):
            return True, ""
    return False, f"güvenilmeyen güncelleme sunucusu: {host}"


def normalize_checksum(value) -> Optional[str]:
    """``sha256:``/boşluk/büyük harf toleranslı; geçerli 64 haneli onaltılık değilse None."""
    text = str(value or "").strip().lower()
    if text.startswith("sha256:"):
        text = text[len("sha256:"):].strip()
    return text if _SHA256_HEX.fullmatch(text) else None


def should_install_pending(has_pending: bool, cancelled: bool, mandatory: bool) -> bool:
    """İş bitince indirilmiş güncelleme kurulsun mu? Zorunlu güncelleme, iş iptal edilmiş olsa
    bile atlanmaz (eskiden ``not cancelled`` koşulu zorunlu kurulumu sessizce atlıyordu)."""
    return bool(has_pending) and (bool(mandatory) or not cancelled)


def should_show_pending_update(has_pending: bool, cancelled: bool, mandatory: bool) -> bool:
    """İş bitince bekleyen (henüz indirilmemiş) güncelleme sunulsun mu? Kural yukarıdakiyle aynı."""
    return bool(has_pending) and (bool(mandatory) or not cancelled)


def exe_names() -> list[str]:
    """Paketin içinde aranacak exe adları: bu uygulamanın adı, çalışan exe'nin (elle yeniden adlandırılmış olabilir) adı, eski ad."""
    running = os.path.basename(sys.executable) if getattr(sys, "frozen", False) else ""
    names: list[str] = []
    for name in (EXE_NAME, running, LEGACY_EXE_NAME):
        if name and name.casefold() not in (n.casefold() for n in names):
            names.append(name)
    return names


def _int_or_zero(value) -> int:
    try:
        return max(0, int(float(value)))
    except (TypeError, ValueError, OverflowError):
        return 0


class _Attempt:
    """Tek bir indirme denemesinin iptal bayrağı: iptal edilen eski deneme, hemen ardından başlayan yenisini etkilemez."""

    __slots__ = ("cancelled",)

    def __init__(self) -> None:
        self.cancelled = False


class _InstallWorker(DaemonWorker):
    """Paketi açıp exe'yi değiştirir ve yeni sürümü başlatır; arayüz iş parçacığı donmaz."""

    def __init__(self, installer: "UpdateInstaller", package: str, visible: bool, old_version: str):
        super().__init__()
        self.installer = installer
        self.package = package
        self.visible = visible
        self.old_version = old_version

    def run(self) -> None:
        installer = self.installer
        try:
            self_update.install_and_relaunch(
                self.package, sys.executable, exe_names(),
                visible=self.visible, old_version=self.old_version,
            )
        except self_update.PackageError as exc:
            log_error("Güncelleme kurulamadı", exc)
            installer.cleanup_file(self.package)
            installer.report_install_failure(installer.describe_error(exc))
        except Exception as exc:  # noqa: BLE001 - kurulum hatası uygulamayı düşürmesin
            log_error("Güncelleme kurulumunda beklenmeyen hata", exc)
            installer.cleanup_file(self.package)
            installer.report_install_failure(str(exc))
        else:
            installer.relaunching = True
            installer.install_complete.emit()


class UpdateInstaller(QObject):
    download_progress = pyqtSignal(object, object, float)  # indirilen, toplam (2 GB üstü sığsın diye object), MB/sn
    download_complete = pyqtSignal(str)
    download_failed = pyqtSignal(str)  # kullanıcıya gösterilebilir (arayüz dilinde) ileti; iptalde "cancelled"
    install_started = pyqtSignal()
    install_complete = pyqtSignal()  # yeni sürüm başlatıldı: çağıran uygulama TEMİZ çıkmalı
    install_failed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.temp_dir = tempfile.gettempdir()
        self.downloaded_file: Optional[str] = None
        self.speed_samples = deque()
        self.smoothed_speed = 0.0
        self._last_progress_emit = 0.0
        self.current_total = 0
        self._attempt = _Attempt()
        self._attempt_no = 0
        self._install_worker: Optional[_InstallWorker] = None
        self.relaunching = False  # kendini güncelleyip çıkıyoruz: açılışta/çıkışta "sağlıklı" sayılıp yan dosyalar silinmez
        self.lang = "tr"  # hata iletilerinin dili (ana pencere dil değişince günceller)

    # ------------------------------------------------------------------ iletiler
    def _msg(self, key: str, **params) -> str:
        return t(key, self.lang).format(**params)

    def describe_error(self, error: BaseException) -> str:
        """PackageError'ı arayüz dilinde anlat (sabit anahtarla); bilinmiyorsa özgün Türkçe ileti."""
        code = getattr(error, "code", "")
        if code:
            key = f"update_pkg_{code}"
            text = t(key, self.lang)
            if text != key:
                return text.format(detail=getattr(error, "detail", ""))
        return str(error)

    def _download_error_text(self, error: BaseException) -> str:
        if isinstance(error, urllib.error.HTTPError):
            return self._msg("update_err_http", code=error.code)
        if isinstance(error, (urllib.error.URLError, TimeoutError, ConnectionError, ssl.SSLError, http.client.HTTPException)):
            return self._msg("update_err_network")
        return str(error)

    # ------------------------------------------------------------------ hız / ilerleme
    def _emit_progress(self, downloaded: int, total: int, force: bool = False):
        now = time.time()
        if not force and (now - self._last_progress_emit) < 0.1:
            return
        self._last_progress_emit = now
        self.download_progress.emit(downloaded, total, self._smooth_speed(self._calc_speed()))

    def _add_sample(self, downloaded: int):
        now = time.time()
        self.speed_samples.append((now, downloaded))
        cutoff = now - 1.5
        while self.speed_samples and self.speed_samples[0][0] < cutoff:
            self.speed_samples.popleft()

    def _calc_speed(self) -> float:
        if len(self.speed_samples) < 2:
            return 0.0
        t0, b0 = self.speed_samples[0]
        t1, b1 = self.speed_samples[-1]
        dt = t1 - t0
        if dt <= 0:
            return 0.0
        return ((b1 - b0) / dt) / (1024 * 1024)

    def _smooth_speed(self, new: float) -> float:
        if self.smoothed_speed == 0.0:
            self.smoothed_speed = new
        else:
            self.smoothed_speed = 0.3 * new + 0.7 * self.smoothed_speed
        return self.smoothed_speed

    def _sha256_file(self, path: str) -> str:
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    # ------------------------------------------------------------------ indirme
    def download_update(
        self,
        download_url: str,
        expected_size: Optional[int] = None,
        expected_checksum: Optional[str] = None,
    ) -> bool:
        part_file = None
        attempt = _Attempt()
        self._attempt = attempt
        self._attempt_no += 1
        try:
            self.speed_samples.clear()
            self.smoothed_speed = 0.0
            self.current_total = _int_or_zero(expected_size)

            ok, reason = validate_download_url(download_url)
            if not ok:
                log_error(f"Güncelleme adresi reddedildi ({reason}): {download_url}")
                self.download_failed.emit(self._msg("update_err_unsafe_url"))
                return False

            # Sunucu sağlama toplamı gönderdiyse ZORUNLU doğrula: yorumlanamıyorsa da reddet
            # (sessizce atlamak, bozuk/sahte paketin kurulmasına izin verirdi).
            expect = None
            if str(expected_checksum or "").strip():
                expect = normalize_checksum(expected_checksum)
                if expect is None:
                    log_error("Sunucunun gönderdiği sağlama toplamı geçerli bir SHA-256 değil")
                    self.download_failed.emit(self._msg("update_err_checksum_invalid"))
                    return False
            else:
                log_info("UYARI: Sunucu sağlama toplamı göndermedi; güncelleme DOĞRULANAMADI")

            self.downloaded_file = os.path.join(self.temp_dir, PACKAGE_NAME)
            part_file = f"{self.downloaded_file}.{self._attempt_no}.part"
            self._remove_stale()

            parsed = urllib.parse.urlparse(download_url)
            ssl_context = ssl._create_unverified_context() if parsed.hostname in ("localhost", "127.0.0.1") else None
            sep = "&" if parsed.query else "?"
            url = f"{download_url}{sep}_t={int(time.time()*1000)}"
            req = urllib.request.Request(url)
            req.add_header("User-Agent", "AppUpp/1.0 MediaCompressor-Updater")
            req.add_header("Cache-Control", "no-cache, no-store, must-revalidate")

            with urllib.request.urlopen(req, timeout=30, context=ssl_context) as response:
                final_url = getattr(response, "geturl", lambda: url)()
                final = urllib.parse.urlparse(final_url)
                if final.scheme != "https" and (final.hostname or "") not in _LOCAL_HOSTS:
                    log_error(f"Güncelleme güvensiz bir adrese yönlendirildi: {final_url}")
                    self.download_failed.emit(self._msg("update_err_redirect"))
                    return False
                announced = _int_or_zero(response.headers.get("Content-Length", 0))
                total = announced or self.current_total
                self.current_total = total
                downloaded = 0
                with open(part_file, "wb") as f:
                    while True:
                        if attempt.cancelled:
                            self.download_failed.emit("cancelled")
                            return False
                        chunk = response.read(8192)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)
                        self._add_sample(downloaded)
                        self._emit_progress(downloaded, total)
            if attempt.cancelled:
                self.download_failed.emit("cancelled")
                return False
            self._emit_progress(downloaded, total, force=True)
            if announced and downloaded < announced:
                # http.client, bağlantı erken kapanınca hata vermeden boş okur: kesik dosya kurulmasın.
                log_error(f"Güncelleme eksik indi: {downloaded}/{announced} bayt")
                self.download_failed.emit(self._msg("update_err_incomplete"))
                return False
            if expect is not None:
                actual = self._sha256_file(part_file)
                if not hmac.compare_digest(actual, expect):
                    log_error(f"Güncelleme SHA-256 uyuşmuyor: beklenen={expect} gelen={actual}")
                    self.download_failed.emit(self._msg("update_err_checksum_mismatch"))
                    return False
            os.replace(part_file, self.downloaded_file)
            part_file = None
            self.download_complete.emit(self.downloaded_file)
            return True
        except Exception as e:
            if attempt.cancelled:
                self.download_failed.emit("cancelled")
                return False
            log_error("Güncelleme indirme hatası", e)
            self.download_failed.emit(self._download_error_text(e))
            return False
        finally:
            if part_file and os.path.exists(part_file):
                try:
                    os.remove(part_file)
                except OSError:
                    pass

    def cancel_download(self) -> None:
        self._attempt.cancelled = True

    def _remove_stale(self) -> None:
        """Önceki (çöken/iptal edilen) indirmelerin artıklarını sil; sürmekte olan bir iptal edilmiş denemenin
        açık dosyası silinemez, o dosyayı kendi iş parçacığı siler."""
        if not self.downloaded_file:
            return
        for path in [self.downloaded_file, *glob.glob(glob.escape(self.downloaded_file) + ".*part")]:
            self.cleanup_file(path)

    @staticmethod
    def cleanup_file(path: Optional[str]) -> None:
        if path and os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass

    def cleanup(self) -> None:
        if not self.downloaded_file:
            return
        for path in [self.downloaded_file, *glob.glob(glob.escape(self.downloaded_file) + ".*part")]:
            self.cleanup_file(path)

    # ------------------------------------------------------------------ kurulum
    def install_support(self) -> tuple[bool, str]:
        """Otomatik kurulum bu çalışmada mümkün mü? Değilse (False, arayüz dilinde neden). Kaynaktan çalışırken
        (frozen değil) kurulacak bir exe yoktur; Windows dışında yeni exe'yi yerine koyacak düzen yoktur."""
        if os.name != "nt":
            return False, self._msg("update_err_unsupported_os")
        if not getattr(sys, "frozen", False):
            return False, self._msg("update_err_unsupported_source")
        return True, ""

    def preflight(self) -> tuple[bool, str]:
        """İndirmeye başlamadan önce: kurulum desteklenmiyorsa ya da uygulama klasörü yazılamıyorsa indirme boşa gitmesin."""
        ok, message = self.install_support()
        if not ok:
            return False, message
        try:
            self_update.check_writable(sys.executable)
        except self_update.PackageError as exc:
            log_error("Uygulama klasörü yazılamıyor", exc)
            return False, self.describe_error(exc)
        return True, ""

    def report_install_failure(self, message: str) -> None:
        self.install_failed.emit(message)

    def installing(self) -> bool:
        worker = self._install_worker
        return worker is not None and worker.isRunning()

    def install_update(self, installer_path: Optional[str] = None, visible: bool = False,
                       old_version: str = VERSION) -> bool:
        """Kurulumu arka planda başlatır; sonuç ``install_complete`` (çıkılmalı) / ``install_failed`` ile gelir.
        ``visible``: ana pencere ekrandaysa yeni sürüm de pencereyi açık başlatır, tepsideyse tepside kalır."""
        update_file = installer_path or self.downloaded_file
        if not update_file or not os.path.exists(update_file):
            self.report_install_failure(self._msg("update_err_not_found"))
            return False
        ok, message = self.install_support()
        if not ok:
            self.report_install_failure(message)
            return False
        if self.installing():
            return False
        self.install_started.emit()
        worker = _InstallWorker(self, update_file, visible, old_version)
        self._install_worker = worker
        worker.start()
        return True
