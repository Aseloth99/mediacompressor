"""Uzaktan güncelleme kontrolü — macik.com.tr."""

from __future__ import annotations

import json
import re
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from typing import Optional

from PyQt6.QtCore import QObject, QThread, QTimer, pyqtSignal

from ..core.app_info import APP_ID, APP_NAME, UPDATE_CHECK_URL, VERSION
from . import self_update
from .config import Config
from .logger import log_error, log_info
from .locales import get_active_language, t
from .remote_notice import parse_notice
from .update_installer import validate_download_url


_TRUE_TEXT = ("true", "1", "yes", "evet", "on")


def to_bool(value) -> bool:
    """Sunucu JSON'unda bool bazen metin gelir ("false" Python'da doğrudur): yalnızca açıkça doğru olanlar True."""
    if isinstance(value, str):
        return value.strip().lower() in _TRUE_TEXT
    if isinstance(value, (int, float)):
        return value != 0
    return bool(value) if isinstance(value, bool) else False


def to_size(value) -> int:
    """fileSize: sayı, ondalık ya da metin olabilir; geçersiz/negatif/boş -> 0 (bilinmiyor)."""
    if isinstance(value, bool):
        return 0
    try:
        return max(0, int(float(str(value).strip())))
    except (TypeError, ValueError, OverflowError):
        return 0


def to_text(value) -> str:
    return value.strip() if isinstance(value, str) else ""


class _UpdateCheckWorker(QThread):
    result_ready = pyqtSignal(dict)
    network_error = pyqtSignal(str)
    check_error = pyqtSignal(str)
    server_error = pyqtSignal(int)  # sunucu HTTP hata durumu döndü (internet yokluğu DEĞİL)
    bad_reply = pyqtSignal()  # yanıt çözümlenemedi / JSON nesnesi değil

    def __init__(self, url: str, ssl_context, parent=None):
        super().__init__(parent)
        self._url = url
        self._ssl_context = ssl_context

    def run(self):
        try:
            req = urllib.request.Request(self._url)
            req.add_header("User-Agent", "AppUpp/1.0 MediaCompressor-UpdateChecker")
            with urllib.request.urlopen(req, timeout=10, context=self._ssl_context) as response:
                data = json.loads(response.read().decode())
            if not isinstance(data, dict):
                self.bad_reply.emit()
                return
            self.result_ready.emit(data)
        except urllib.error.HTTPError as e:  # URLError'ın alt sınıfı: önce o yakalanmalı
            self.server_error.emit(int(e.code))
        except urllib.error.URLError as e:
            reason = e.reason if hasattr(e, "reason") else e
            self.network_error.emit(str(reason))
        except ValueError:  # bozuk JSON / UnicodeDecodeError
            self.bad_reply.emit()
        except Exception as e:
            self.check_error.emit(str(e))


class UpdateChecker(QObject):
    update_available = pyqtSignal(str, str, str, bool, object, str)  # boyut object: 2 GB üstü int'e sığmaz
    check_complete = pyqtSignal(bool)  # denetim BAŞARIYLA bitti (True: yeni sürüm var)
    check_failed = pyqtSignal()  # denetim yapılamadı (ağ/sunucu/yanıt): "güncel" sanılmasın
    notice_received = pyqtSignal(object)  # remote_notice.Notice (duyuru satırı)

    CURRENT_VERSION = VERSION
    UPDATE_CHECK_URL = UPDATE_CHECK_URL
    APP_NAME = APP_ID
    # Açılışta: son denetim bundan eskiyse hemen denetlenir (uzun süre açılmayanlar yeni sürümü hemen görür).
    STARTUP_STALE_HOURS = 1
    # Açıkken: en geç bu kadar saatte bir denetlenir.
    CHECK_INTERVAL_HOURS = 4
    # Sık tık duvar saatine bakar: uyku / hazırda bekleme sonrası kaçan denetim de yakalanır.
    TICK_MINUTES = 30

    def __init__(self, config: Config, parent=None):
        super().__init__(parent)
        self.config = config
        self.current_version = self.CURRENT_VERSION
        self.last_check_time: Optional[datetime] = None
        self.check_timer = QTimer(self)
        self.check_timer.timeout.connect(self._auto_check)
        self._worker: Optional[_UpdateCheckWorker] = None
        self._manual = False

    def start(self):
        if not self.config.get("auto_update_check", True):
            return
        self._check_if_needed(self.STARTUP_STALE_HOURS)
        self.check_timer.start(self.TICK_MINUTES * 60 * 1000)

    def stop(self):
        self.check_timer.stop()

    def _auto_check(self):
        self._check_if_needed(self.CHECK_INTERVAL_HOURS)

    def _check_if_needed(self, max_age_hours: float | None = None):
        last_check_str = self.config.get("last_update_check")
        if last_check_str:
            try:
                self.last_check_time = datetime.fromisoformat(last_check_str)
                if datetime.now() - self.last_check_time < timedelta(hours=self.CHECK_INTERVAL_HOURS if max_age_hours is None else max_age_hours):
                    return
            except Exception:
                pass
        self.check_for_updates(show_message=False)

    def check_for_updates(self, show_message: bool = False):
        auto = self.config.get("auto_update_check", True)
        if not auto and not show_message:
            return
        if self._worker is not None and self._worker.isRunning():
            if show_message:
                self._manual = True
            return
        self._manual = bool(show_message)
        params = {"appName": self.APP_NAME, "currentVersion": self.current_version}
        url = f"{self.UPDATE_CHECK_URL}?{urllib.parse.urlencode(params)}"
        parsed = urllib.parse.urlparse(url)
        is_local = parsed.hostname in ("localhost", "127.0.0.1", "::1")
        ssl_context = ssl._create_unverified_context() if is_local else None
        self._worker = _UpdateCheckWorker(url, ssl_context, self)
        self._worker.result_ready.connect(self._on_worker_result)
        self._worker.network_error.connect(self._on_worker_network_error)
        self._worker.check_error.connect(self._on_worker_error)
        self._worker.server_error.connect(self._on_worker_server_error)
        self._worker.bad_reply.connect(self._on_worker_bad_reply)
        self._worker.finished.connect(self._on_worker_finished)
        self._worker.start()

    def _on_worker_finished(self):
        worker = self.sender()
        if worker is self._worker:
            self._worker = None

    def _on_worker_result(self, data: dict):
        show_message = self._manual
        try:
            notice = parse_notice(data, get_active_language(self.config))
            if notice is not None:
                self.notice_received.emit(notice)
            if not to_bool(data.get("updateAvailable", False)):
                self._finish_up_to_date(show_message)
                return

            latest = str(data.get("version") or "").strip().lstrip("vV")
            download_url = to_text(data.get("download_url"))
            raw_notes = data.get("release_notes")
            notes = raw_notes if isinstance(raw_notes, str) else ("" if raw_notes is None else str(raw_notes))
            mandatory = to_bool(data.get("isMandatory", False))
            size = to_size(data.get("fileSize"))
            checksum = to_text(data.get("checksum"))
            if not latest or not download_url:
                # Sunucu "güncelleme var" dedi ama sürüm/adres vermedi: "güncel" demek yanıltıcı olurdu.
                log_error("Güncelleme yanıtı eksik (sürüm ya da indirme adresi yok)")
                self.check_failed.emit()
                return
            url_ok, url_reason = validate_download_url(download_url)
            if not url_ok:
                # Güvenli olmayan/güvenilmeyen adres: kullanıcıya hiç sunulmaz.
                log_error(f"Güncelleme sunucusu geçersiz indirme adresi verdi ({url_reason}): {download_url}")
                self.check_failed.emit()
                return
            newer = self._compare_versions(latest, self.current_version) > 0
            skipped = self._skipped_version()
            if newer and skipped and skipped.lstrip("vV") == latest:
                # Bu sürüm bu bilgisayarda açılışta ölüp geri alındı: aynı sürüm bir daha önerilmez.
                log_info(f"Geri alınan sürüm {latest} yeniden sunuldu; atlanıyor")
                newer = False
            if newer:
                # Damga ATILMAZ: güncelleme bekliyorken uygulama kapanıp açılırsa (ya da kurulum yarıda kalırsa) bir
                # sonraki açılışta yeniden denetlenir; yoksa "Güncelle" düğmesi/tepsi satırı 24 saat kaybolurdu.
                self.update_available.emit(latest, download_url, notes, mandatory, size, checksum)
                self.check_complete.emit(True)
            else:
                self._finish_up_to_date(show_message)
        except Exception as e:
            log_error("Güncelleme sonucu işlenemedi", e)
            self.check_failed.emit()
            if show_message:
                self._show_info(t("update_check_title", self._lang()), t("update_check_failed_msg", self._lang()))

    def _finish_up_to_date(self, show_message: bool):
        self.config.set("last_update_check", datetime.now().isoformat())
        self.check_complete.emit(False)
        if show_message:
            self._show_current()

    def _show_current(self):
        self._show_info(
            t("update_check_title", self._lang()),
            t("update_current", self._lang()).format(app=APP_NAME, version=self.current_version),
        )

    def _skipped_version(self) -> Optional[str]:
        """Geri alınmış (açılışta ölen) sürüm; yalnızca paketlenmiş uygulamada, exe'nin yanındaki `.skip` dosyasından."""
        if not getattr(sys, "frozen", False):
            return None
        return self_update.skipped_version(sys.executable)

    def _on_worker_network_error(self, reason: str):
        """İnternet yok / zaman aşımı / sunucu hatası: denetim yapılamadı. Eskiden `check_complete(False)` yayılıp
        ayarlardaki durum satırı "Güncel" gösteriyordu; artık `check_failed`."""
        log_info(f"Güncelleme atlandı (ağ): {reason}")
        self.check_failed.emit()
        if self._manual:
            self._show_info(
                t("update_check_title", self._lang()),
                t("update_check_failed_msg", self._lang()),
            )

    def _on_worker_server_error(self, code: int):
        self._on_worker_network_error(f"HTTP {code}")

    def _on_worker_bad_reply(self):
        self._on_worker_error("geçersiz yanıt")

    def _on_worker_error(self, message: str):
        log_error(f"Güncelleme hatası: {message}")
        self.check_failed.emit()
        if self._manual:
            self._show_info(
                t("update_check_title", self._lang()),
                t("update_check_failed_msg", self._lang()),
            )

    def _lang(self) -> str:
        return get_active_language(self.config)

    def _show_info(self, title: str, text: str):
        """Güncelleme sonuçları için pop-up açılmaz: ayarlardaki durum satırı / "Güncelle" düğmesi gösterir."""
        log_info(f"{title}: {text}")

    def _show_warning(self, title: str, text: str):
        log_info(f"{title}: {text}")

    @staticmethod
    def _version_parts(text: str):
        """"1.2.3", "v1.2" ya da "1.2.3-beta" -> [1, 2, 3]; sürüm gibi görünmüyorsa None."""
        match = re.match(r"\s*[vV]?(\d+(?:\.\d+)*)", str(text))
        return [int(x) for x in match.group(1).split(".")] if match else None

    def _compare_versions(self, v1: str, v2: str) -> int:
        a = self._version_parts(v1)
        b = self._version_parts(v2)
        if a is None or b is None:
            return 0
        n = max(len(a), len(b))
        a += [0] * (n - len(a))
        b += [0] * (n - len(b))
        for x, y in zip(a, b):
            if x > y:
                return 1
            if x < y:
                return -1
        return 0

    def get_current_version(self) -> str:
        return self.current_version
