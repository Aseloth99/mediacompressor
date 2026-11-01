"""FFmpeg yolu, indirme ve platform adayları."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import tempfile
import threading
import urllib.parse
import urllib.request
import zipfile
from typing import Callable, Optional

from .app_info import LEGACY_APP_ID
from ..utils.helpers import app_bundle_dir, get_application_path, get_user_data_dir, resource_path
from ..utils.locales import t
from ..utils.logger import log_error, log_info
from ..utils.platform_utils import is_linux, is_macos, is_windows

# Ağ okumaları için soket zaman aşımı (sn): sunucu sustuğunda indirme sonsuza dek takılmasın.
NETWORK_TIMEOUT = 30
CHECKSUM_TIMEOUT = 15
_CHUNK_SIZE = 64 * 1024
_SHA256_RE = re.compile(r"(?<![0-9A-Fa-f])[0-9A-Fa-f]{64}(?![0-9A-Fa-f])")


def parse_sha256(text: str) -> Optional[str]:
    """Yayıncının .sha256 dosyasından ilk geçerli 64 haneli onaltılık özeti çıkar."""
    match = _SHA256_RE.search(text or "")
    return match.group(0).lower() if match else None


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ffmpeg_name(platform: str | None = None) -> str:
    return "ffmpeg.exe" if is_windows(platform) else "ffmpeg"


def ffprobe_name(platform: str | None = None) -> str:
    return "ffprobe.exe" if is_windows(platform) else "ffprobe"


# GUI uygulamaları (macOS Finder, Linux masaüstü başlatıcıları) kabuğun PATH'ini almaz; yaygın
# kurulum konumları bu yüzden ayrıca denenir. macOS: Homebrew (Apple Silicon / Intel), MacPorts.
MAC_FFMPEG_DIRS = ("/opt/homebrew/bin", "/usr/local/bin", "/opt/local/bin")
LINUX_FFMPEG_DIRS = ("/usr/bin", "/usr/local/bin", "/snap/bin", "/home/linuxbrew/.linuxbrew/bin")


def which_no_cwd(name: str) -> Optional[str]:
    """PATH'te ``name`` ara; yalnızca MUTLAK PATH girdilerine bakar, çalışma dizinini aramaz.

    ``shutil.which`` Windows'ta önce geçerli dizine bakar ve göreli yol döndürebilir; böylece
    CWD'ye bırakılmış bir ffmpeg.exe (veya göreli "ffmpeg" yedeği) çalıştırılabilirdi.
    """
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        entry = entry.strip().strip('"')
        if not entry or not os.path.isabs(entry):
            continue
        candidate = os.path.join(entry, name)
        if os.path.isfile(candidate) and (os.name == "nt" or os.access(candidate, os.X_OK)):
            return os.path.abspath(candidate)
    return None


class FFmpegManager:
    # Not: "release-essentials" son sürümü verir (sürüm sabit değil). Sabitlemek için bu iki
    # adresi sürüme özel ``.../packages/ffmpeg-X.Y.Z-essentials_build.zip`` ve ``.sha256``
    # karşılığına çevirin. SHA-256 yayıncıdan aynı sunucudan alındığı için aktarım/bozulma
    # bütünlüğünü doğrular, sunucu ele geçirilmesine karşı koruma DEĞİLDİR.
    DOWNLOAD_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
    CHECKSUM_URL = DOWNLOAD_URL + ".sha256"

    def __init__(self, platform: str | None = None):
        self.platform = platform  # None = çalışan platform; testlerde mac/Linux dalları için verilir
        self.ffmpeg_path: Optional[str] = None
        self.ffprobe_path: Optional[str] = None

    def can_download(self) -> bool:
        """Otomatik indirme yalnızca Windows'ta (yayıncı Windows derlemesi sunuyor); macOS/Linux'ta
        ffmpeg paket yöneticisiyle kurulur ve PATH/yaygın konumlardan bulunur."""
        return is_windows(self.platform)

    def find(self) -> Optional[str]:
        which_ff = which_no_cwd(ffmpeg_name(self.platform))
        which_fp = which_no_cwd(ffprobe_name(self.platform))
        if which_ff:
            self.ffmpeg_path = which_ff
            self.ffprobe_path = which_fp
            return which_ff

        for ff, fp in self._candidates():
            if self._runnable(ff):
                # Her zaman çözümlenmiş mutlak yol: alt süreç CWD'den arama yapmasın.
                self.ffmpeg_path = os.path.abspath(ff)
                self.ffprobe_path = os.path.abspath(fp) if self._runnable(fp) else None
                return self.ffmpeg_path
        return None

    def _runnable(self, path: str) -> bool:
        """Dosya var mı ve (POSIX'te) çalıştırılabilir mi? Yürütme biti olmayan bir dosya seçilirse
        her video "başlatılamadı" ile düşerdi."""
        return os.path.isfile(path) and (is_windows(self.platform) or os.access(path, os.X_OK))

    def _candidates(self) -> list[tuple[str, str]]:
        exe = ffmpeg_name(self.platform)
        probe = ffprobe_name(self.platform)
        data = get_user_data_dir()
        base = get_application_path()
        pairs = [
            (os.path.join(data, "ffmpeg", "bin", exe), os.path.join(data, "ffmpeg", "bin", probe)),
            (os.path.join(data, "ffmpeg", exe), os.path.join(data, "ffmpeg", probe)),
        ]
        if is_windows(self.platform):
            # Eski kimlikle ("MedyaSikistirici") indirilmiş ffmpeg: güncellenen kullanıcı yeniden indirmesin.
            legacy = os.path.join(get_user_data_dir(LEGACY_APP_ID), "ffmpeg", "bin")
            pairs.append((os.path.join(legacy, exe), os.path.join(legacy, probe)))
        pairs += [
            (os.path.join(base, exe), os.path.join(base, probe)),
            (os.path.join(base, "ffmpeg", "bin", exe), os.path.join(base, "ffmpeg", "bin", probe)),
            (os.path.join(base, "ffmpeg", exe), os.path.join(base, "ffmpeg", probe)),
            (resource_path(exe), resource_path(probe)),
        ]
        extra_dirs: list[str] = []
        if is_macos(self.platform):
            bundle = app_bundle_dir(platform=self.platform)
            if bundle:
                extra_dirs += [
                    os.path.join(bundle, "Contents", "Resources"),
                    os.path.join(bundle, "Contents", "Frameworks"),
                    os.path.dirname(bundle),  # ffmpeg'i .app'in yanına koyan kullanıcılar
                ]
            extra_dirs += MAC_FFMPEG_DIRS
        elif is_linux(self.platform):
            extra_dirs += [os.path.join(os.path.expanduser("~"), ".local", "bin"), *LINUX_FFMPEG_DIRS]
        elif not is_windows(self.platform):
            extra_dirs += ["/usr/local/bin", "/usr/bin"]
        for folder in extra_dirs:
            pairs.append((os.path.join(folder, exe), os.path.join(folder, probe)))
        return pairs

    def missing_hint(self, lang: str = "tr") -> str:
        """FFmpeg bulunamadığında platforma göre yerelleştirilmiş kurulum ipucu."""
        if is_windows(self.platform):
            key = "ffmpeg_missing_windows"
        elif is_macos(self.platform):
            key = "ffmpeg_missing_macos"
        else:
            key = "ffmpeg_missing_linux"
        return t(key, lang)

    def needed_message(self, lang: str = "tr") -> str:
        """Video işlenmek istenip FFmpeg yokken gösterilen uyarı metni."""
        if is_windows(self.platform):
            key = "msg_ffmpeg_needed"
        elif is_macos(self.platform):
            key = "msg_ffmpeg_needed_macos"
        else:
            key = "msg_ffmpeg_needed_linux"
        return t(key, lang)

    # ------------------------------------------------------------------ indirme
    @staticmethod
    def _https_only(url: str) -> bool:
        parsed = urllib.parse.urlparse(url)
        return parsed.scheme == "https" and bool(parsed.hostname)

    def _expected_sha256(self) -> Optional[str]:
        """Yayıncının .sha256 dosyasındaki özet; erişilemez/çözümlenemezse None."""
        try:
            req = urllib.request.Request(self.CHECKSUM_URL, headers={"User-Agent": "MediaCompressor"})
            with urllib.request.urlopen(req, timeout=CHECKSUM_TIMEOUT) as response:
                return parse_sha256(response.read(4096).decode("utf-8", errors="replace"))
        except Exception as exc:  # noqa: BLE001
            log_info(f"FFmpeg .sha256 dosyası alınamadı: {exc}")
            return None

    def _fetch_zip(
        self,
        target: str,
        progress_cb: Callable[[float], None] | None,
        cancel_event: Optional[threading.Event],
    ) -> bool:
        """Zip'i ``target``'a (geçici .part dosyası) akıt. İptal/ağ hatası/eksik indirmede False."""
        req = urllib.request.Request(self.DOWNLOAD_URL, headers={"User-Agent": "MediaCompressor"})
        with urllib.request.urlopen(req, timeout=NETWORK_TIMEOUT) as response:
            try:
                total = int(response.headers.get("Content-Length", 0) or 0)
            except (TypeError, ValueError):
                total = 0
            received = 0
            with open(target, "wb") as handle:
                while True:
                    if cancel_event is not None and cancel_event.is_set():
                        log_info("FFmpeg indirmesi iptal edildi")
                        return False
                    chunk = response.read(_CHUNK_SIZE)
                    if not chunk:
                        break
                    handle.write(chunk)
                    received += len(chunk)
                    if progress_cb and total > 0:
                        progress_cb(min(1.0, received / total))
        if total and received != total:
            log_error(f"FFmpeg indirmesi eksik kaldı: {received}/{total} bayt")
            return False
        return True

    def _install_from_zip(self, zip_path: str, hedef: str) -> Optional[str]:
        """Doğrulanmış zip'i geçici klasöre aç, ffmpeg/ffprobe'u ``hedef/bin``e kur."""
        staging = tempfile.mkdtemp(prefix="extract-", dir=hedef)
        try:
            with zipfile.ZipFile(zip_path, "r") as archive:
                bad = archive.testzip()
                if bad:
                    log_error(f"FFmpeg zip bozuk (ilk bozuk üye: {bad})")
                    return None
                archive.extractall(staging)

            found_dir = None
            for root, _dirs, files in os.walk(staging):
                if ffmpeg_name(self.platform) in files:
                    found_dir = root
                    break
            if not found_dir:
                log_error("FFmpeg zip içinde ffmpeg yürütülebilir dosyası bulunamadı")
                return None

            # find() kalıcı olarak bulabilsin diye sürüm klasörüne değil sabit hedef/bin'e kur.
            bin_dir = os.path.join(hedef, "bin")
            os.makedirs(bin_dir, exist_ok=True)
            installed: dict[str, str] = {}
            for name in (ffmpeg_name(self.platform), ffprobe_name(self.platform)):
                source = os.path.join(found_dir, name)
                if not os.path.isfile(source):
                    continue
                final = os.path.join(bin_dir, name)
                partial = final + ".new"
                shutil.copy2(source, partial)
                if not is_windows(self.platform):
                    os.chmod(partial, 0o755)  # extractall yürütme bitini korumaz
                os.replace(partial, final)
                installed[name] = final
            self.ffmpeg_path = installed[ffmpeg_name(self.platform)]
            self.ffprobe_path = installed.get(ffprobe_name(self.platform))
            return self.ffmpeg_path
        finally:
            shutil.rmtree(staging, ignore_errors=True)

    def download(
        self,
        progress_cb: Callable[[float], None] | None = None,
        cancel_event: Optional[threading.Event] = None,
    ) -> Optional[str]:
        if not self.can_download():
            log_info("FFmpeg otomatik indirme yalnızca Windows'ta var; PATH/yaygın konumlar kullanılır")
            return None
        return self._download_to(
            os.path.join(get_user_data_dir(), "ffmpeg"), progress_cb, cancel_event,
        )

    def _download_to(
        self,
        hedef: str,
        progress_cb: Callable[[float], None] | None = None,
        cancel_event: Optional[threading.Event] = None,
    ) -> Optional[str]:
        """İndir -> (SHA-256 doğrula) -> aç -> kur. Zip önce geçici dosyaya alınır; doğrulama
        geçmeden hiçbir şey açılmaz. Başarısızlıkta artık dosya bırakılmaz."""
        if not self._https_only(self.DOWNLOAD_URL):
            log_error(f"FFmpeg indirme adresi https değil, reddedildi: {self.DOWNLOAD_URL}")
            return None
        os.makedirs(hedef, exist_ok=True)
        fd, part_path = tempfile.mkstemp(prefix="ffmpeg-", suffix=".zip.part", dir=hedef)
        os.close(fd)
        try:
            log_info("FFmpeg indiriliyor")
            if not self._fetch_zip(part_path, progress_cb, cancel_event):
                return None

            expected = self._expected_sha256()
            actual = sha256_file(part_path)
            if expected is None:
                log_info(
                    "UYARI: FFmpeg SHA-256 özeti yayıncıdan alınamadı; indirme DOĞRULANAMADI "
                    f"(hesaplanan SHA-256: {actual})"
                )
            elif actual != expected:
                log_error(f"FFmpeg SHA-256 uyuşmuyor, kurulum iptal: beklenen={expected} gelen={actual}")
                return None
            else:
                log_info("FFmpeg SHA-256 doğrulandı")

            path = self._install_from_zip(part_path, hedef)
            if path:
                if progress_cb:
                    progress_cb(1.0)
                log_info(f"FFmpeg kuruldu: {path}")
            return path
        except Exception as exc:
            log_error("FFmpeg indirilemedi", exc)
            return None
        finally:
            try:
                os.remove(part_path)
            except OSError:
                pass

    def is_ready(self) -> bool:
        return bool(self.ffmpeg_path and os.path.isfile(self.ffmpeg_path))
