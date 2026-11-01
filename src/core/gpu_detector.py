"""En güçlü GPU'yu seç: NVENC / AMF / QSV / VAAPI / VideoToolbox (platforma göre)."""

from __future__ import annotations

import json
import os
import re
import shlex
import tempfile
import threading
from dataclasses import dataclass, field
from typing import Optional

from ..utils.logger import log_error, log_info
from ..utils.platform_utils import LINUX, MACOS, WINDOWS, detect, is_linux, is_macos, is_windows
from ..utils.process import run_hidden

PROBE_TIMEOUT = 8

ENCODER_MAP = {
    "nvenc": {"h264": "h264_nvenc", "hevc": "hevc_nvenc", "av1": "av1_nvenc"},
    "amf": {"h264": "h264_amf", "hevc": "hevc_amf", "av1": "av1_amf"},
    "qsv": {"h264": "h264_qsv", "hevc": "hevc_qsv", "av1": "av1_qsv"},
    # VAAPI: Linux'ta AMD/Intel (Mesa/iHD). AV1 kodlama yalnızca yeni donanımda (AMD VCN4, Intel Arc).
    "vaapi": {"h264": "h264_vaapi", "hevc": "hevc_vaapi", "av1": "av1_vaapi"},
    # Apple'da donanım AV1 KODLAYICI yok (yalnızca çözücü): av1 için CPU kullanılır.
    "videotoolbox": {"h264": "h264_videotoolbox", "hevc": "hevc_videotoolbox"},
    "cpu": {"h264": "libx264", "hevc": "libx265", "av1": "libsvtav1"},
}

# Platforma göre sondajlanan donanım aileleri (sıra = vendor bilinmiyorsa tercih sırası).
PLATFORM_FAMILIES = {
    WINDOWS: ("nvenc", "amf", "qsv"),
    LINUX: ("nvenc", "vaapi", "qsv"),
    MACOS: ("videotoolbox",),
}

# Kart üreticisi -> o platformda tercih edilen aileler (ilk kullanılabilir olan seçilir).
VENDOR_FAMILIES = {
    WINDOWS: {"nvidia": ("nvenc",), "amd": ("amf",), "intel": ("qsv",)},
    LINUX: {"nvidia": ("nvenc",), "amd": ("vaapi",), "intel": ("qsv", "vaapi")},
    MACOS: {v: ("videotoolbox",) for v in ("apple", "amd", "intel", "nvidia", "unknown")},
}

DRI_DIR = "/dev/dri"


def families_for_platform(platform: Optional[str] = None) -> tuple[str, ...]:
    """Bu platformda sondajlanacak donanım aileleri (ör. macOS: yalnızca VideoToolbox)."""
    return PLATFORM_FAMILIES.get(detect(platform), ())


def find_vaapi_device(dri_dir: str = DRI_DIR) -> Optional[str]:
    """İlk DRM render düğümü (``/dev/dri/renderD128``...); yoksa None (VAAPI kullanılamaz)."""
    try:
        names = sorted(n for n in os.listdir(dri_dir) if re.fullmatch(r"renderD\d+", n))
    except OSError:
        return None
    return os.path.join(dri_dir, names[0]) if names else None


def hw_input_args(family: str, vaapi_device: Optional[str] = None, decode: Optional[str] = None) -> list[str]:
    """Girdiden (``-i``) ÖNCE verilecek aileye özgü bayraklar.

    * vaapi: ``-vaapi_device <düğüm>`` (kodlayıcının donanım bağlamı).
    * decode="videotoolbox": ``-hwaccel videotoolbox`` (kareler sistem belleğine döner).
    * decode="cuda" (yalnızca nvenc): NVDEC çözer, kareler GPU belleğinde kalır (``scale_cuda`` ile ölçeklenir).
    """
    if family == "vaapi":
        return ["-vaapi_device", vaapi_device or find_vaapi_device() or DRI_DIR + "/renderD128"]
    if family == "videotoolbox" and decode == "videotoolbox":
        return ["-hwaccel", "videotoolbox"]
    if family == "nvenc" and decode == "cuda":
        return ["-hwaccel", "cuda", "-hwaccel_output_format", "cuda"]
    return []


def hw_filter_chain(family: str) -> list[str]:
    """Aileye özgü süzgeçler (``-vf``): VAAPI yazılım karelerini GPU'ya yükler."""
    if family == "vaapi":
        return ["format=nv12", "hwupload"]
    return []


# ---------------------------------------------------------------------------
# Kodlayıcı yetenek sondajı: (ffmpeg yolu, kodlayıcı adı) bazında, süreç boyu önbellek.
# Yalnızca h264 denenip hevc/av1'in aynı aileyle çalıştığını varsaymak, desteklemeyen
# kartlarda (ör. AV1'siz GPU) her dosyada başarısız GPU denemesi + CPU yeniden denemesi demekti.
# ---------------------------------------------------------------------------
GPU_FAILURE_LIMIT = 2  # GPU başarısız + CPU başarılı bu kadar üst üste olursa o kombinasyon kapatılır

_CACHE_LOCK = threading.Lock()
_ENCODER_LIST_CACHE: dict[str, str] = {}
_PROBE_CACHE: dict[tuple[str, str], bool] = {}
_FAILURE_COUNTS: dict[tuple[str, str], int] = {}


def reset_probe_cache() -> None:
    """Önbellekleri temizle (testler ve ffmpeg yolu değiştiğinde)."""
    with _CACHE_LOCK:
        _ENCODER_LIST_CACHE.clear()
        _PROBE_CACHE.clear()
        _FAILURE_COUNTS.clear()
        _LISTING_CACHE.clear()
        _DECODE_FAILED.clear()


def encoder_list(ffmpeg_path: str) -> str:
    """``ffmpeg -encoders`` çıktısı (ffmpeg yolu başına bir kez)."""
    with _CACHE_LOCK:
        cached = _ENCODER_LIST_CACHE.get(ffmpeg_path)
    if cached is not None:
        return cached
    try:
        result = run_hidden([ffmpeg_path, "-nostdin", "-hide_banner", "-encoders"], timeout=20)
        text = (result.stdout or "") + (result.stderr or "")
    except Exception:
        text = ""
    with _CACHE_LOCK:
        _ENCODER_LIST_CACHE[ffmpeg_path] = text
    return text


def _name_in_list(listing: str, encoder: str) -> bool:
    """Tam sözcük eşleşmesi: 'hevc_nvenc' araması 'nvenc' içeren başka adlarla karışmaz."""
    pattern = r"(?<![\w-])" + re.escape(encoder) + r"(?![\w-])"
    return re.search(pattern, listing) is not None


def encoder_listed(ffmpeg_path: str, encoder: str) -> bool:
    """Kodlayıcı bu ffmpeg derlemesinin listesinde var mı?"""
    return _name_in_list(encoder_list(ffmpeg_path), encoder)


def _probe_command(ffmpeg_path: str, encoder: str, vaapi_device: Optional[str] = None) -> Optional[list[str]]:
    """Sondaj komutu. VAAPI kodlayıcıları DRM düğümü ve ``hwupload`` ister; düğüm yoksa None."""
    cmd = [ffmpeg_path, "-nostdin", "-hide_banner", "-loglevel", "error"]
    vaapi = encoder.endswith("_vaapi")
    if vaapi:
        device = vaapi_device or find_vaapi_device()
        if device is None:
            return None
        cmd += ["-vaapi_device", device]
    cmd += ["-f", "lavfi", "-i", "color=black:s=256x256:r=5:d=0.4"]
    if vaapi:
        cmd += ["-vf", ",".join(hw_filter_chain("vaapi"))]
    cmd += ["-frames:v", "3", "-c:v", encoder, "-f", "null", "-"]
    return cmd


def probe_encoder(ffmpeg_path: str, encoder: str) -> bool:
    """Kodlayıcı gerçekten çalışıyor mu? Kısa bir sentetik kodlamayla dener; sonuç önbelleklenir.

    NVENC yeni sürücülerde 128x128'i reddeder; 256x256 AMF/NVENC/QSV ile geçer.
    """
    key = (ffmpeg_path, encoder)
    with _CACHE_LOCK:
        if key in _PROBE_CACHE:
            return _PROBE_CACHE[key]
    cmd = _probe_command(ffmpeg_path, encoder)
    try:
        if cmd is None:
            works = False
        else:
            result = run_hidden(cmd, timeout=PROBE_TIMEOUT)
            works = result.returncode == 0
    except Exception:
        works = False
    with _CACHE_LOCK:
        _PROBE_CACHE.setdefault(key, works)
        return _PROBE_CACHE[key]


def encoder_supported(ffmpeg_path: str, encoder: str) -> bool:
    """Listede var, sondajı geçti ve gerçek kullanımda art arda başarısız olmadı."""
    if not encoder_listed(ffmpeg_path, encoder):
        return False
    return probe_encoder(ffmpeg_path, encoder)


def record_gpu_result(ffmpeg_path: str, encoder: str, gpu_failed_cpu_ok: bool) -> None:
    """Gerçek bir dosyada GPU sonucu: başarılıysa sayaç sıfırlanır; GPU başarısız ama CPU
    başarılıysa (sorun dosyada değil GPU yolunda) sayılır ve limite ulaşınca kombinasyon
    süreç boyunca kapatılır — sonraki dosyalar doğrudan CPU'ya gider."""
    key = (ffmpeg_path, encoder)
    with _CACHE_LOCK:
        if not gpu_failed_cpu_ok:
            _FAILURE_COUNTS.pop(key, None)
            return
        count = _FAILURE_COUNTS.get(key, 0) + 1
        _FAILURE_COUNTS[key] = count
        if count >= GPU_FAILURE_LIMIT:
            _PROBE_CACHE[key] = False
    if count >= GPU_FAILURE_LIMIT:
        log_info(f"{encoder} art arda {count} kez başarısız: bu oturumda CPU kullanılacak")


# ---------------------------------------------------------------------------
# Donanım çözme (NVDEC/CUDA): kareler GPU'da çözülür, GPU'da ölçeklenir ve doğrudan NVENC'e
# gider. Ölçüm (RTX 4070, 4K60 H.264 -> 1080p): yazılım çözme 8.3 sn / 31 sn işlemci zamanı,
# CUDA hattı 7.3 sn / 1.6 sn. AMF için d3d11va ile çözüp sistem belleğine indirmek de ölçüldü
# ve YAVAŞTI (8.7 -> 18.8 sn); AMF/QSV yazılım çözmede kalır.
# ---------------------------------------------------------------------------
_LISTING_CACHE: dict[tuple[str, str], str] = {}
_DECODE_FAILED: set[tuple[str, str]] = set()


def _listing(ffmpeg_path: str, flag: str) -> str:
    """``ffmpeg -hwaccels`` / ``-filters`` çıktısı (ffmpeg yolu başına bir kez)."""
    key = (ffmpeg_path, flag)
    with _CACHE_LOCK:
        cached = _LISTING_CACHE.get(key)
    if cached is not None:
        return cached
    try:
        result = run_hidden([ffmpeg_path, "-nostdin", "-hide_banner", flag], timeout=20)
        text = (result.stdout or "") + (result.stderr or "")
    except Exception:
        text = ""
    with _CACHE_LOCK:
        _LISTING_CACHE[key] = text
    return text


def amf_h264_bframes(ffmpeg_path: str) -> bool:
    """h264_amf bu kartta gerçekten B-karesi üretiyor mu? (oturum boyunca önbellekli)

    B-kareleri aynı görüntü kalitesinde dosyayı ~%25 küçültüyor (Radeon iGPU, VCN 3: 20.1 -> 15.5 MB). Eski
    AMD kartlarda olmayabilir; bayrak sessizce yok sayılırsa kalite tablosu yanlış olurdu. Bu yüzden kısa bir
    kodlamanın kare türlerine bakılır."""
    key = (ffmpeg_path, "h264_amf+bframes")
    with _CACHE_LOCK:
        if key in _PROBE_CACHE:
            return _PROBE_CACHE[key]
    works = False
    try:
        with tempfile.TemporaryDirectory(prefix="mc_amf_") as tmp:
            out = os.path.join(tmp, "bf.mkv")
            enc = run_hidden(
                [ffmpeg_path, "-nostdin", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                 "testsrc2=size=256x256:rate=25:duration=1", "-frames:v", "16", "-c:v", "h264_amf",
                 "-quality", "quality", "-rc", "cqp", "-qp_i", "26", "-qp_p", "26", "-qp_b", "28", "-bf", "3", "-y", out],
                timeout=PROBE_TIMEOUT,
            )
            if enc.returncode == 0 and os.path.isfile(out):
                dec = run_hidden([ffmpeg_path, "-nostdin", "-hide_banner", "-i", out, "-vf", "showinfo", "-f", "null", "-"],
                                 timeout=PROBE_TIMEOUT)
                works = "type:B" in ((dec.stderr or "") + (dec.stdout or ""))
    except Exception:
        works = False
    with _CACHE_LOCK:
        _PROBE_CACHE.setdefault(key, works)
        result = _PROBE_CACHE[key]
    log_info(f"h264_amf B-kareleri: {'var' if result else 'yok'}")
    return result


def cuda_pipeline_available(ffmpeg_path: str) -> bool:
    """Bu ffmpeg derlemesinde CUDA çözme VE ``scale_cuda`` var mı? (indirilen derleme farklı olabilir)"""
    return (_name_in_list(_listing(ffmpeg_path, "-hwaccels"), "cuda")
            and _name_in_list(_listing(ffmpeg_path, "-filters"), "scale_cuda"))


def decode_failed(ffmpeg_path: str, method: str, codec: str) -> bool:
    with _CACHE_LOCK:
        return (ffmpeg_path, f"{method}:{codec}") in _DECODE_FAILED


def mark_decode_failed(ffmpeg_path: str, method: str, codec: str) -> None:
    """Donanım çözme bu kaynak kodekte başarısız oldu (ör. AV1 çözemeyen eski kart): bu oturumda
    o kodek için doğrudan yazılım çözme kullanılır, her dosyada boşa deneme yapılmaz."""
    with _CACHE_LOCK:
        _DECODE_FAILED.add((ffmpeg_path, f"{method}:{codec}"))
    log_info(f"{method} donanım çözme {codec} için kapatıldı (yazılım çözme kullanılacak)")


@dataclass
class GpuCard:
    name: str
    vram_mb: int = 0
    vendor: str = "unknown"
    dedicated: bool = False
    score: int = 0


_GPU_DETECT_CACHE: dict[str, "GpuDetector"] = {}


@dataclass
class GpuDetector:
    ffmpeg_path: str
    cards: list[GpuCard] = field(default_factory=list)
    nvenc: bool = False
    amf: bool = False
    qsv: bool = False
    videotoolbox: bool = False
    selected_family: str = "cpu"
    selected_card: Optional[GpuCard] = None
    vaapi: bool = False
    platform: Optional[str] = None  # None = çalışan platform (testlerde mac/Linux dalları için verilir)
    # aile -> AV1 yolu ("gpu" / "svt" / "aom" / "none"); hazırlık iş parçacığında doldurulur (sondaj arayüzü dondurmasın)
    av1_routes: dict = field(default_factory=dict)

    def detect(self) -> "GpuDetector":
        if not self.ffmpeg_path:
            return self
        if self.ffmpeg_path in _GPU_DETECT_CACHE:
            cached = _GPU_DETECT_CACHE[self.ffmpeg_path]
            self.cards = list(cached.cards)
            self.nvenc = cached.nvenc
            self.amf = cached.amf
            self.qsv = cached.qsv
            self.vaapi = cached.vaapi
            self.videotoolbox = cached.videotoolbox
            self.selected_family = cached.selected_family
            self.selected_card = cached.selected_card
            return self
        try:
            self.cards = list_gpus(self.platform)
            encoders = self._encoder_list()
            flags = {name: False for name in ("nvenc", "amf", "qsv", "vaapi", "videotoolbox")}
            for family in families_for_platform(self.platform):
                flags[family] = self._family_ok(encoders, family)
            self.nvenc = flags["nvenc"]
            self.amf = flags["amf"]
            self.qsv = flags["qsv"]
            self.vaapi = flags["vaapi"]
            self.videotoolbox = flags["videotoolbox"]
            self._pick()
            names = ", ".join(f"{c.name} ({c.vendor})" for c in self.cards) or "yok"
            log_info(f"GPU listesi: {names}")
            log_info(self.status_text())
        except Exception as exc:
            log_error("GPU algılama hatası", exc)
            self.selected_family = "cpu"
        _GPU_DETECT_CACHE[self.ffmpeg_path] = self
        return self


    def _encoder_list(self) -> str:
        return encoder_list(self.ffmpeg_path)

    def _encoder_works(self, encoder: str) -> bool:
        return probe_encoder(self.ffmpeg_path, encoder)

    def _family_ok(self, encoder_list_text: str, family: str) -> bool:
        """Aile kullanılabilir mi? Aile kararı h264 ile verilir; hevc/av1 kodek başına,
        ilk kullanımda ``encoder_supported`` ile ayrıca sondajlanır."""
        h264 = ENCODER_MAP[family]["h264"]
        if not _name_in_list(encoder_list_text, h264):
            return False
        return self._encoder_works(h264)

    def supports(self, family: str, codec: str) -> bool:
        """(aile x kodek) kombinasyonu bu makinede çalışıyor mu? (önbellekli sondaj)"""
        if family == "cpu":
            return True
        encoder = ENCODER_MAP.get(family, {}).get(codec)
        return bool(encoder) and encoder_supported(self.ffmpeg_path, encoder)

    def av1_route(self, family: str) -> str:
        """Bu ailede AV1 nasıl kodlanır: "gpu" (ekran kartı), "svt" (hızlı yazılım, SVT-AV1), "aom" (libaom: çok
        yavaş; programın indirdiği "essentials" FFmpeg'de SVT-AV1 yok) ya da "none". VideoCompressor ile aynı sıra."""
        if family != "cpu" and self.supports(family, "av1"):
            return "gpu"
        if encoder_listed(self.ffmpeg_path, "libsvtav1"):
            return "svt"
        if encoder_listed(self.ffmpeg_path, "libaom-av1"):
            return "aom"
        return "none"

    def compute_av1_routes(self) -> dict:
        self.av1_routes = {family: self.av1_route(family) for family in self.available_families()}
        return self.av1_routes

    def available_families(self) -> list[str]:
        found = []
        if self.nvenc:
            found.append("nvenc")
        if self.amf:
            found.append("amf")
        if self.qsv:
            found.append("qsv")
        if self.vaapi:
            found.append("vaapi")
        if self.videotoolbox:
            found.append("videotoolbox")
        found.append("cpu")
        return found

    def _family_for_card(self, card: GpuCard) -> Optional[str]:
        preferred = VENDOR_FAMILIES.get(detect(self.platform), {}).get(card.vendor, ())
        available = self.available_families()
        for family in preferred:
            if family in available:
                return family
        return None

    def _pick(self) -> None:
        ranked = sorted(self.cards, key=lambda c: c.score, reverse=True)
        for card in ranked:
            family = self._family_for_card(card)
            if family:
                self.selected_family = family
                self.selected_card = card
                return

        flags = {
            "nvenc": self.nvenc, "amf": self.amf, "qsv": self.qsv,
            "vaapi": self.vaapi, "videotoolbox": self.videotoolbox,
        }
        for family in families_for_platform(self.platform):
            if flags.get(family):
                self.selected_family = family
                self.selected_card = ranked[0] if ranked else None
                return
        self.selected_family = "cpu"

    def resolve_mode(self, ui_choice: str) -> str:
        choice = (ui_choice or "auto").strip().lower()
        if choice == "" or choice.startswith(("auto", "otomatik")):
            return self.selected_family
        # Menü metni ("NVIDIA NVENC", "Intel QSV", "CPU (Sadece İşlemci)" ...) anahtar sözcükle
        # eşlenir. Eskiden yalnızca tam eşleşme ("nvenc", "qsv"...) vardı; menüdeki gerçek
        # metinler eşleşmediği için açık GPU seçimi sessizce CPU'ya düşüyordu.
        family = "cpu"
        for name, keywords in (
            ("nvenc", ("nvenc", "nvidia")),
            ("amf", ("amf", "amd")),
            ("qsv", ("qsv", "intel")),
            ("vaapi", ("vaapi",)),
            ("videotoolbox", ("videotoolbox",)),
        ):
            if any(k in choice for k in keywords):
                family = name
                break
        if family != "cpu" and family not in self.available_families():
            return self.selected_family if self.selected_family != "cpu" else "cpu"
        return family

    def gpu_menu_values(self) -> list[str]:
        values = ["Otomatik"]
        if self.nvenc:
            values.append("NVIDIA NVENC")
        if self.amf:
            values.append("AMD AMF")
        if self.qsv:
            values.append("Intel QSV")
        if self.vaapi:
            values.append("VAAPI")
        if self.videotoolbox:
            values.append("VideoToolbox")
        values.append("CPU (Sadece İşlemci)")
        return values

    def status_text(self) -> str:
        if self.selected_family == "cpu":
            return "GPU bulunamadı, işlemci (CPU) kullanılacak"
        family_label = {
            "nvenc": "NVENC",
            "amf": "AMF",
            "qsv": "QSV",
            "vaapi": "VAAPI",
            "videotoolbox": "VideoToolbox",
        }.get(self.selected_family, self.selected_family.upper())
        name = self.selected_card.name if self.selected_card else family_label
        vram = ""
        if self.selected_card and self.selected_card.vram_mb >= 256:
            gb = self.selected_card.vram_mb / 1024
            vram = f" · {gb:.0f} GB" if gb >= 1 else f" · {self.selected_card.vram_mb} MB"
        return f"{name} — {family_label}{vram}"

    def is_ok(self) -> bool:
        return self.selected_family != "cpu"


SKIP_GPU_NAMES = (
    "virtual display",
    "remote display",
    "microsoft basic",
    "iddcx",
)


def _should_skip_gpu(name: str, pnp: str = "") -> bool:
    n = name.lower()
    p = pnp.upper()
    if any(k in n for k in SKIP_GPU_NAMES):
        return True
    if p.startswith("ROOT\\DISPLAY") or p.startswith("SWD\\REMOTE"):
        return True
    return False


def list_gpus(platform: Optional[str] = None) -> list[GpuCard]:
    if is_windows(platform):
        cards = _list_windows()
        _merge_nvidia_smi(cards)
        return cards
    if is_macos(platform):
        return _list_mac()
    if is_linux(platform):
        cards = _list_linux()
        _merge_nvidia_smi(cards)
        return cards
    return []


def _score_card(card: GpuCard) -> int:
    name = card.name.lower()
    score = 0
    if card.dedicated:
        score += 10000
    score += min(max(card.vram_mb, 0), 48000)
    if any(k in name for k in ("rtx 40", "rtx 50", "rx 7", "rx 9", "arc a7", "arc b")):
        score += 2500
    elif any(k in name for k in ("rtx", "rx 6", "rx 5", "arc")):
        score += 1800
    elif "gtx" in name or "radeon pro" in name:
        score += 800
    if any(k in name for k in ("uhd", "iris", "vega", "graphics", "radeon(tm) graphics")):
        if not card.dedicated:
            score -= 200
    if "microsoft basic" in name or "remote" in name:
        score -= 5000
    card.score = score
    return score


def _vendor_from_name(name: str) -> str:
    n = name.lower()
    if "nvidia" in n or "geforce" in n or "quadro" in n or "rtx" in n or "gtx" in n:
        return "nvidia"
    if "amd" in n or "radeon" in n or "ryzen" in n:
        return "amd"
    if "intel" in n or "arc" in n or "uhd" in n or "iris" in n:
        return "intel"
    if "apple" in n or "m1" in n or "m2" in n or "m3" in n or "m4" in n:
        return "apple"
    return "unknown"


def _is_dedicated(name: str, vendor: str, vram_mb: int, pnp: str = "") -> bool:
    n = name.lower()
    if vendor == "nvidia":
        return True
    if vendor == "intel":
        return "arc" in n
    if vendor == "amd":
        if any(k in n for k in ("rx ", "xt", "pro w", "pro 5", "pro 6", "pro 7")):
            return True
        if "graphics" in n and "rx" not in n:
            return False
        return vram_mb >= 2048
    if vendor == "apple":
        return True
    return vram_mb >= 2048


def _list_windows() -> list[GpuCard]:
    cards: list[GpuCard] = []
    try:
        result = run_hidden(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "Get-CimInstance Win32_VideoController | "
                "Select-Object Name, AdapterRAM, PNPDeviceID | ConvertTo-Json -Compress",
            ],
            timeout=12,
        )
        raw = (result.stdout or "").strip()
        if not raw:
            return cards
        data = json.loads(raw)
        items = data if isinstance(data, list) else [data]
        for item in items:
            name = str(item.get("Name") or "GPU").strip()
            pnp = str(item.get("PNPDeviceID") or "").upper()
            if _should_skip_gpu(name, pnp):
                continue
            ram = item.get("AdapterRAM") or 0
            try:
                ram = int(ram)
                if ram < 0:
                    ram = ram + 2**32
                vram_mb = ram // (1024 * 1024) if ram > 1024 * 1024 else 0
            except (TypeError, ValueError):
                vram_mb = 0
            vendor = "unknown"
            if "VEN_10DE" in pnp:
                vendor = "nvidia"
            elif "VEN_1002" in pnp:
                vendor = "amd"
            elif "VEN_8086" in pnp:
                vendor = "intel"
            else:
                vendor = _vendor_from_name(name)
            card = GpuCard(
                name=name,
                vram_mb=vram_mb,
                vendor=vendor,
                dedicated=_is_dedicated(name, vendor, vram_mb, pnp),
            )
            _score_card(card)
            cards.append(card)
    except Exception as exc:
        log_error("Windows GPU listesi alınamadı", exc)
    return cards


def _merge_nvidia_smi(cards: list[GpuCard]) -> None:
    try:
        result = run_hidden(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            timeout=8,
        )
        if result.returncode != 0:
            return
        for line in (result.stdout or "").splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 1 or not parts[0]:
                continue
            name = parts[0]
            try:
                vram_mb = int(float(parts[1])) if len(parts) > 1 else 0
            except ValueError:
                vram_mb = 0
            key = name.lower()
            existing = next(
                (
                    c for c in cards
                    if c.vendor == "nvidia" and (key in c.name.lower() or c.name.lower() in key)
                ),
                None,
            )
            if existing:
                if vram_mb > existing.vram_mb:
                    existing.vram_mb = vram_mb
                    _score_card(existing)
                continue
            card = GpuCard(name=name, vram_mb=vram_mb, vendor="nvidia", dedicated=True)
            _score_card(card)
            cards.append(card)
    except Exception:
        pass


PCI_VENDORS = {"0x10de": "nvidia", "0x1002": "amd", "0x8086": "intel"}
_VENDOR_LABELS = {"nvidia": "NVIDIA", "amd": "AMD", "intel": "Intel"}
DRM_ROOT = "/sys/class/drm"


def _read_sysfs(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            return handle.read().strip()
    except OSError:
        return ""


def _clean_pci_name(vendor: str, device: str) -> str:
    """lspci "Advanced Micro Devices, Inc. [AMD/ATI]" + "Navi 31 [Radeon RX 7900 XT/XTX]" ->
    "AMD Radeon RX 7900 XT/XTX"."""
    low = vendor.lower()
    if "nvidia" in low:
        short = "NVIDIA"
    elif "advanced micro" in low or "amd" in low or "ati" in low.split():
        short = "AMD"
    elif "intel" in low:
        short = "Intel"
    else:
        short = vendor.split(",")[0].strip()
    bracket = re.search(r"\[([^\]]+)\]", device)
    model = bracket.group(1) if bracket else device
    return f"{short} {model}".strip()


def _lspci_names(runner=run_hidden) -> dict[str, str]:
    """PCI yuvası ("00:02.0") -> okunur GPU adı. ``lspci`` yoksa boş sözlük."""
    try:
        text = runner(["lspci", "-mm"], timeout=6).stdout or ""
    except Exception:
        return {}
    names: dict[str, str] = {}
    for line in text.splitlines():
        try:
            parts = shlex.split(line)
        except ValueError:
            continue
        if len(parts) < 4:
            continue
        slot, pci_class, vendor, device = parts[:4]
        if any(k in pci_class.lower() for k in ("vga", "3d controller", "display controller")):
            names[slot] = _clean_pci_name(vendor, device)
    return names


def _list_linux(drm_root: str = DRM_ROOT, runner=run_hidden) -> list[GpuCard]:
    """``/sys/class/drm/card*`` üzerinden GPU'lar (üretici PCI kimliğinden, ad ``lspci``'den)."""
    cards: list[GpuCard] = []
    try:
        entries = sorted(os.listdir(drm_root))
    except OSError:
        return cards
    names: Optional[dict[str, str]] = None
    for entry in entries:
        if not re.fullmatch(r"card\d+", entry):
            continue
        device_dir = os.path.join(drm_root, entry, "device")
        vendor_id = _read_sysfs(os.path.join(device_dir, "vendor")).lower()
        if not vendor_id:
            continue  # vkms/simpledrm gibi PCI olmayan sanal aygıtlar
        vendor = PCI_VENDORS.get(vendor_id, "unknown")
        if names is None:
            names = _lspci_names(runner)
        slot = os.path.basename(os.path.realpath(device_dir))
        name = next((label for pci, label in names.items() if slot.endswith(pci)), "")
        if not name:
            name = f"{_VENDOR_LABELS.get(vendor, 'Bilinmeyen')} GPU"
        vram_mb = 0
        total = _read_sysfs(os.path.join(device_dir, "mem_info_vram_total"))  # amdgpu, bayt
        if total.isdigit():
            vram_mb = int(total) // (1024 * 1024)
        card = GpuCard(
            name=name, vram_mb=vram_mb, vendor=vendor,
            dedicated=_is_dedicated(name, vendor, vram_mb),
        )
        _score_card(card)
        cards.append(card)
    return cards


def _list_mac() -> list[GpuCard]:
    cards: list[GpuCard] = []
    try:
        result = run_hidden(["system_profiler", "SPDisplaysDataType"], timeout=15)
        text = result.stdout or ""
        blocks = re.split(r"\n\s{4}(?=\S)", text)
        for block in blocks:
            name_m = re.search(r"^([^\n:]+):", block.strip())
            if not name_m:
                continue
            name = name_m.group(1).strip()
            if name in ("Displays", "Graphics/Displays", "Chipset Model"):
                continue
            vram_m = re.search(r"VRAM[^\d]*(\d+)\s*([MG]B)", block, re.I)
            vram_mb = 0
            if vram_m:
                val = int(vram_m.group(1))
                vram_mb = val * 1024 if vram_m.group(2).upper().startswith("G") else val
            vendor = _vendor_from_name(name)
            if "chipset model" in block.lower() and vendor == "unknown":
                model = re.search(r"Chipset Model:\s*(.+)", block)
                if model:
                    name = model.group(1).strip()
                    vendor = _vendor_from_name(name)
            if vendor == "unknown" and ("apple" in block.lower() or "metal" in block.lower()):
                vendor = "apple"
            card = GpuCard(
                name=name,
                vram_mb=vram_mb,
                vendor=vendor if vendor != "unknown" else "apple",
                dedicated=True,
            )
            _score_card(card)
            if card.name and card.name.lower() not in ("graphics/displays",):
                cards.append(card)
    except Exception as exc:
        log_error("macOS GPU listesi alınamadı", exc)
    if not cards:
        cards.append(GpuCard(name="Apple GPU", vendor="apple", dedicated=True, vram_mb=0, score=8000))
    return cards
