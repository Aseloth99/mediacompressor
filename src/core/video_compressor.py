"""Video sıkıştırma — GPU encoder + CPU fallback."""

from __future__ import annotations

import json
import os
import queue
import re
import shutil
import subprocess
import threading
from typing import Callable, Optional

from .atomic_output import CANCELLED, commit_temp, discard_temp, temp_path_for
from .gpu_detector import (
    ENCODER_MAP, amf_h264_bframes, cuda_pipeline_available, decode_failed, encoder_listed, encoder_supported,
    find_vaapi_device, hw_filter_chain, hw_input_args, mark_decode_failed, record_gpu_result,
)
from .app_info import is_auto_bitrate
from ..utils.logger import log_info
from ..utils.process import kill_process_tree, popen_hidden, run_hidden, terminate_process_tree

VIDEO_EXTS = {".mov", ".mp4", ".mkv", ".avi", ".m4v"}

# _run ffmpeg'i hiç başlatamadığında bu önekle döner.
START_FAILED_PREFIX = "başlatılamadı"

CPU_ENCODERS = {"h264": "libx264", "hevc": "libx265", "av1": "libsvtav1"}
CPU_AV1_ENCODERS = ("libsvtav1", "libaom-av1")  # tercih sırası

# Tüm HEVC kodlayıcıları (libx265 + GPU aileleri). mp4/mov/m4v içinde Apple/QuickTime uyumu
# için hvc1 etiketi gerekir; yalnızca libx265'e eklemek GPU HEVC çıktılarını etiketsiz bırakıyordu.
HEVC_ENCODERS = frozenset(m["hevc"] for m in ENCODER_MAP.values())
H264_ENCODERS = frozenset(m["h264"] for m in ENCODER_MAP.values())
SOFTWARE_ENCODERS = frozenset({"libx264", "libx265", "libsvtav1", "libaom-av1"})
MP4_FAMILY_EXTS = frozenset({".mp4", ".m4v", ".mov"})

# Kullanıcı arayüzü x264 adlarıyla çalışır (superfast..slower); libsvtav1 ve libaom-av1 ise
# sayısal hız ister ("-preset slow" libsvtav1'de hata verir).
SVT_AV1_PRESETS = {
    "ultrafast": 12, "superfast": 11, "veryfast": 10, "faster": 9, "fast": 8,
    "medium": 6, "slow": 5, "slower": 4, "veryslow": 2, "placebo": 0,
}
# libaom yalnızca SVT-AV1'i olmayan FFmpeg'de kullanılır (programın indirdiği "essentials" derlemesi). Ölçüm (11 sn,
# 1308x1744 iPhone videosu, 6 çekirdek): cpu-used 3 = 552 sn, 5 = 170 sn, 6 = 112 sn; dosya boyutu farkı ~%5. Eski
# eşleme ("slow" -> 3) 10 dakikalık videoyu saatlerce kodluyordu. 6, "good" kipinin en hızlısı (7-8 aynı sonucu verir;
# "realtime" kipi hızlı ama dosyası H.264'ten büyük, AV1'in anlamı kalmıyor).
LIBAOM_CPU_USED = {
    "ultrafast": 6, "superfast": 6, "veryfast": 6, "faster": 6, "fast": 6,
    "medium": 6, "slow": 6, "slower": 5, "veryslow": 4, "placebo": 3,
}


def _numeric_preset(preset: str, table: dict[str, int], default: int, lo: int, hi: int) -> int:
    key = str(preset).strip().lower()
    if key in table:
        return table[key]
    if key.isdigit():
        return max(lo, min(hi, int(key)))
    return default


# Akış (stream) politikası: varsayılan ``-map 0:v:0 -map 0:a?`` (ilk video + tüm sesler).
# Altyazı yalnızca METİN tabanlıysa ve kapsayıcı destekliyorsa taşınır; bitmap altyazılar
# (PGS/hdmv_pgs_subtitle, dvd_subtitle, dvb_subtitle) mp4'e çevrilemediği ve dönüştürmeye
# çalışmak ffmpeg'i hatayla durdurduğu için BİLEREK atlanır. Veri/ek akışları da atlanır.
MP4_TEXT_SUBTITLES = frozenset({
    "subrip", "srt", "ass", "ssa", "webvtt", "mov_text", "text", "microdvd", "subviewer", "sami",
})
MKV_TEXT_SUBTITLES = frozenset({"subrip", "ass", "ssa", "webvtt"})


def plan_subtitles(streams: Optional[list[dict]], dst_ext: str) -> tuple[list[int], Optional[str]]:
    """(taşınacak altyazı akış indeksleri, ``-c:s`` değeri). Akış bilgisi yoksa altyazı taşınmaz."""
    if not streams:
        return [], None
    ext = dst_ext.lower()
    if ext in MP4_FAMILY_EXTS:
        allowed, codec_arg = MP4_TEXT_SUBTITLES, "mov_text"
    elif ext == ".mkv":
        allowed, codec_arg = MKV_TEXT_SUBTITLES, "copy"
    else:
        return [], None  # avi vb.: güvenilir altyazı desteği yok
    indices = [
        int(s["index"]) for s in streams
        if s.get("type") == "subtitle" and str(s.get("codec") or "").lower() in allowed
    ]
    return (indices, codec_arg) if indices else ([], None)


def parse_rate(text: Optional[str]) -> Optional[float]:
    """ffprobe kare hızı ("30000/1001", "25/1", "29.97") -> 29.97; bilinmiyorsa ("0/0") None."""
    if not text:
        return None
    try:
        if "/" in str(text):
            num, den = str(text).split("/", 1)
            num_f, den_f = float(num), float(den)
            return num_f / den_f if num_f > 0 and den_f > 0 else None
        value = float(text)
        return value if value > 0 else None
    except (TypeError, ValueError):
        return None


def source_fps(streams: Optional[list[dict]]) -> Optional[float]:
    """İlk video akışının kare hızı (bilinmiyorsa None)."""
    for s in streams or []:
        if s.get("type") == "video" and s.get("fps"):
            return float(s["fps"])
    return None


def effective_fps(target: Optional[float], src: Optional[float]) -> Optional[float]:
    """Uygulanacak kare hızı: yalnızca DÜŞÜRÜR (kaynak 24 fps iken 30 seçmek kare çoğaltmaz).
    Kaynak bilinmiyorsa istenen değer uygulanır."""
    if not target:
        return None
    if src and target >= src - 0.05:
        return None
    return float(target)


def video_output_path(dst: str, codec: str) -> str:
    """Çıktı yolu: uzantı korunur, ancak kapsayıcı seçilen kodeği taşıyamıyorsa .mp4 yazılır.

    * .mov + AV1: QuickTime biçiminde AV1 yok; ffmpeg her denemede "Conversion failed" veriyordu.
    * .avi: AAC sesi ve HEVC/AV1'i standart dışı taşır; HEVC "rawvideo" diye okunan, açılmayan bir
      dosya "başarılı" diye üretiliyordu. AVI kaynaklar her kodekte .mp4 olur.
    .m4v ise MP4'ün kendisidir: uzantısı kalır, yalnızca MP4 yazıcısıyla yazılır (bkz. build_cmd)."""
    root, ext = os.path.splitext(dst)
    ext = ext.lower()
    if ext == ".avi" or (ext == ".mov" and codec == "av1"):
        return root + ".mp4"
    return dst


def first_video(streams: Optional[list[dict]]) -> Optional[dict]:
    """``-map 0:v:0`` ile seçilen akış: ilk video akışı (yoksa None)."""
    return next((s for s in streams or [] if s.get("type") == "video"), None)


_PIX_420 = ("yuv420", "yuvj420", "nv12", "nv21", "p010", "p012", "p016")


def pix_fmt_info(pix_fmt: Optional[str]) -> Optional[tuple[int, bool]]:
    """ffprobe piksel biçimi -> (bit derinliği, 4:2:0 mı); bilinmiyorsa None.
    "yuv420p" -> (8, True), "yuv420p10le" / "p010le" -> (10, True), "yuv422p10le" -> (10, False)."""
    p = str(pix_fmt or "").strip().lower()
    if not p or p in ("none", "unknown"):
        return None
    m = re.search(r"(9|10|12|14|16)(le|be)$", p)
    return (int(m.group(1)) if m else 8), p.startswith(_PIX_420)


def target_pix_fmt(vcodec: str, pix_fmt: Optional[str]) -> Optional[str]:
    """Kodlayıcıya verilecek piksel biçimi; dönüşüm gerekmiyorsa None.

    H.264 her zaman 8-bit 4:2:0: 10-bit kaynakta (iPhone HDR, HEVC Main 10) GPU H.264 kodlayıcıları
    hata verip CPU'ya düşüyor, libx264 ise çoğu cihazın oynatamadığı "High 10" üretiyordu.
    HEVC/AV1 10-bit 4:2:0'ı korur; 4:2:2 / 4:4:4 / RGB kaynaklar 4:2:0'a indirilir."""
    info = pix_fmt_info(pix_fmt)
    if info is None:
        return None
    depth, is420 = info
    hardware = vcodec not in SOFTWARE_ENCODERS
    if vcodec in H264_ENCODERS:
        if depth == 8 and is420:
            return None
        return "nv12" if hardware else "yuv420p"
    if is420 and depth <= 10:
        return None
    if depth > 8:
        return "p010le" if hardware else "yuv420p10le"
    return "nv12" if hardware else "yuv420p"


# NVDEC'in güvenle çözdüğü kaynaklar (kodek -> en yüksek bit derinliği; yalnızca 4:2:0). H.264 10-bit
# ve 4:2:2 yalnızca en yeni kartlarda var. Desteklemeyen eski kartta (ör. AV1) çözme başarısız olursa
# dosya yazılım çözmeyle yeniden denenir ve o kodek oturum boyunca kapatılır.
NVDEC_MAX_DEPTH = {"h264": 8, "hevc": 10, "av1": 10, "vp9": 10, "mpeg2video": 8}


def cuda_decodable(video: Optional[dict]) -> bool:
    """Kaynak CUDA hattına (NVDEC + scale_cuda) uygun mu?

    Döndürme bilgisi olan videolar (telefonda dikey çekim) HAYIR: ffmpeg GPU karelerini otomatik
    döndüremiyor, çıktı yan yatık ve döndürme etiketi olmadan çıkıyordu."""
    if not video or video.get("rotated"):
        return False
    if odd_size(video):  # GPU karesi kırpılamaz; tek boyut yazılım çözmede çifte kırpılır (bkz. EVEN_CROP)
        return False
    limit = NVDEC_MAX_DEPTH.get(str(video.get("codec") or "").lower())
    info = pix_fmt_info(video.get("pix_fmt"))
    return bool(limit and info and info[1] and info[0] <= limit)


# 4:2:0 kodlayıcılar (libx264, libx265, AMF...) tek genişlik/yükseklikte "width not divisible by 2" ile duruyor.
# Kırpma (en çok 1 piksel) neredeyse bedava; yalnızca boyut tek ya da bilinmiyorsa eklenir.
EVEN_CROP = "crop=trunc(iw/2)*2:trunc(ih/2)*2"


def odd_size(video: Optional[dict]) -> Optional[bool]:
    """Kaynağın genişliği ya da yüksekliği tek mi? Boyut bilinmiyorsa None."""
    try:
        width, height = int((video or {}).get("width") or 0), int((video or {}).get("height") or 0)
    except (TypeError, ValueError):
        return None
    if width <= 0 or height <= 0:
        return None
    return bool(width % 2 or height % 2)


def _rotation_of(stream: dict) -> bool:
    """ffprobe akışında sıfırdan farklı döndürme (yan veri ya da eski "rotate" etiketi) var mı?"""
    angles = [(stream.get("tags") or {}).get("rotate")]
    angles += [d.get("rotation") for d in stream.get("side_data_list") or [] if isinstance(d, dict)]
    for angle in angles:
        try:
            if angle is not None and abs(float(angle)) % 360 > 0.5:
                return True
        except (TypeError, ValueError):
            continue
    return False


_PIX_FMT_RE = re.compile(
    r",\s*((?:yuvj|yuva|yuv|nv|p0|p2|p4|gray|rgb|bgr|gbr|argb|abgr|rgba|bgra|ya|xyz|bayer|pal|uyvy|yuyv|vuy|ayuv|x2)\w*)"
)


def normalize_trim(trim, duration: float = 0.0) -> Optional[tuple[float, Optional[float]]]:
    """Kırpma aralığı (başlangıç sn, bitiş sn | None = sona kadar); etkisizse None.

    Süre biliniyorsa bitiş süreye kırpılır; sona dayanan bitiş "sona kadar" sayılır."""
    if not trim:
        return None
    try:
        start = max(0.0, float(trim[0] or 0.0))
        end = float(trim[1]) if len(trim) > 1 and trim[1] is not None else None
    except (TypeError, ValueError, IndexError):
        return None
    if duration > 0 and end is not None and end >= duration - 0.05:
        end = None
    if end is not None and end <= start + 0.05:
        return None
    if start < 0.05 and end is None:
        return None
    return start, end


def trimmed_duration(duration: float, trim: Optional[tuple[float, Optional[float]]]) -> float:
    """İlerleme için kırpılmış süre (ffmpeg'in time= değeri kırpılmış parçada 0'dan başlar)."""
    if not trim:
        return duration
    start, end = trim
    stop = min(end, duration) if (end is not None and duration > 0) else (end if end is not None else duration)
    return max(0.0, stop - start)


# Kalite eşlemesi: arayüzdeki kalite (CRF, libx264 ölçeği) hangi kodlayıcı seçilirse seçilsin AYNI görüntü
# kalitesini versin. Eskiden aynı sayı her kodlayıcıya veriliyordu; ama ölçekler farklı: av1_nvenc 0-255, SVT-AV1
# 0-63. "24" AV1'de neredeyse kayıpsız demekti ve AV1 çıktısı KAYNAKTAN BÜYÜK oluyordu (iPhone videosu 19.3 MB ->
# 65.6 MB). NVENC H.264 de aynı kalite için ~%60 büyük dosya yazıyordu (QP, CRF'nin uyarlamalı nicemlemesi yok).
# Değerler ölçüldü (23 Ekim 2026, gerçek iPhone videosu, VMAF; her satır: libx264 CRF -> o kodlayıcının değeri,
# ikisi aynı VMAF'ı verir). AMF Radeon iGPU (VCN 3) ile ölçüldü; av1_amf ölçülemedi, aynı 0-255 ölçekli
# av1_nvenc tablosu kullanılır. QSV/VAAPI/VideoToolbox ölçülemedi (donanım yok): eski davranış sürer.
_QUALITY_POINTS = (18, 20, 22, 24, 26, 28, 30, 32)
QUALITY_MAP: dict[str, tuple[tuple[float, ...], int]] = {  # kodlayıcı -> (değerler, en büyük değer)
    "h264_nvenc": ((21.6, 23.4, 25.1, 26.9, 29.0, 31.2, 33.4, 36.3), 51),
    "hevc_nvenc": ((21.8, 24.0, 25.6, 27.4, 30.1, 32.5, 35.0, 38.4), 51),
    "av1_nvenc": ((68.0, 79.8, 94.5, 106.3, 122.7, 139.3, 156.8, 173.6), 255),
    "h264_amf": ((22.4, 24.2, 25.8, 27.4, 29.3, 31.2, 33.2, 35.0), 51),
    # B-kareleriyle (-bf 3, B karelerinin QP'si +2): aynı kalitede ~%25 küçük; yalnızca kart destekliyorsa
    "h264_amf_bf": ((20.5, 22.4, 24.1, 25.8, 28.1, 30.2, 32.0, 34.0), 51),
    "hevc_amf": ((23.4, 25.1, 27.0, 27.6, 28.8, 30.4, 32.2, 34.3), 51),
    "av1_amf": ((68.0, 79.8, 94.5, 106.3, 122.7, 139.3, 156.8, 173.6), 255),
    "libx265": ((21.7, 23.9, 25.9, 27.7, 30.1, 32.0, 34.0, 36.0), 51),  # varsayılan "slow" hızında ölçüldü
    # SVT-AV1 yüksek CRF'de bile kaliteyi korur: 28'den sonrası ölçeğin sonuna (63) dayanır.
    "libsvtav1": ((27.3, 31.0, 34.8, 39.2, 47.4, 57.4, 63.0, 63.0), 63),
    # libaom (essentials FFmpeg'de tek AV1 kodlayıcı) cpu-used 6 ile ayrıca ölçüldü
    "libaom-av1": ((23.1, 27.2, 30.3, 33.7, 39.3, 47.1, 54.1, 60.4), 63),
}


def encoder_quality(vcodec: str, crf: int) -> int:
    """Arayüzdeki CRF (libx264 ölçeği) -> bu kodlayıcının aynı görüntü kalitesini veren değeri."""
    entry = QUALITY_MAP.get(vcodec)
    if entry is None:
        return int(crf)
    values, top = entry
    xs = _QUALITY_POINTS
    c = float(crf)
    if c <= xs[0]:
        i = 0
    elif c >= xs[-1]:
        i = len(xs) - 2
    else:
        i = max(k for k in range(len(xs) - 1) if xs[k] <= c)
    slope = (values[i + 1] - values[i]) / (xs[i + 1] - xs[i])
    return int(round(max(0.0, min(float(top), values[i] + (c - xs[i]) * slope))))


def vaapi_qp(vcodec: str, crf: int) -> int:
    """CRF (x264 ölçeği, 0-51) -> VAAPI sabit QP. AV1'in nicemleme indeksi 0-255 olduğundan
    (CRF ölçeği 0-63 ile orantılı) av1_vaapi için ~4 ile çarpılır."""
    if "av1" in vcodec:
        return max(0, min(255, int(crf) * 4))
    return max(0, min(51, int(crf)))


def cpu_preset_args(vcodec: str, preset: str) -> list[str]:
    """CPU kodlayıcıya uygun hız argümanları."""
    if vcodec == "libsvtav1":
        # SVT-AV1: 0 (en yavaş/en iyi) .. 13; 12 tüm sürümlerde geçerli üst sınır.
        return ["-preset", str(_numeric_preset(preset, SVT_AV1_PRESETS, 6, 0, 12))]
    if vcodec == "libaom-av1":
        return ["-cpu-used", str(_numeric_preset(preset, LIBAOM_CPU_USED, 6, 0, 8)), "-row-mt", "1"]
    return ["-preset", preset]


class VideoCompressor:
    def __init__(self, ffmpeg_path: str, ffprobe_path: str | None = None):
        self.ffmpeg_path = ffmpeg_path
        self.ffprobe_path = ffprobe_path
        self._cpu_av1: Optional[str] = None
        self.last_output: Optional[str] = None  # son başarılı compress() çıktısının gerçek yolu

    def duration(self, src: str) -> float:
        if self.ffprobe_path:
            try:
                result = run_hidden(
                    [
                        self.ffprobe_path, "-v", "error",
                        "-show_entries", "format=duration",
                        "-of", "default=noprint_wrappers=1:nokey=1", src,
                    ],
                    timeout=10,
                )
                return float((result.stdout or "").strip())
            except Exception:
                pass
        try:
            result = run_hidden([self.ffmpeg_path, "-nostdin", "-hide_banner", "-i", src], timeout=10)
            text = (result.stderr or "") + (result.stdout or "")
            match = re.search(r"Duration: (\d{2}):(\d{2}):(\d{2}\.\d+)", text)
            if match:
                h, m, s = map(float, match.groups())
                return h * 3600 + m * 60 + s
        except Exception:
            pass
        return 0.0

    def probe_streams(self, src: str) -> Optional[list[dict]]:
        """Kaynaktaki akışlar: [{'index', 'type', 'codec'}]; belirlenemezse None.

        ffprobe varsa JSON okunur; yoksa ``ffmpeg -i`` çıktısı çözümlenir.
        """
        if self.ffprobe_path:
            try:
                result = run_hidden(
                    [
                        self.ffprobe_path, "-v", "error",
                        "-show_entries",
                        "stream=index,codec_type,codec_name,avg_frame_rate,r_frame_rate,pix_fmt,width,height"
                        ":stream_tags=rotate:stream_side_data=rotation",
                        "-of", "json", src,
                    ],
                    timeout=15,
                )
                data = json.loads(result.stdout or "{}")
                raw = data.get("streams")
                if isinstance(raw, list):
                    return [
                        {
                            "index": int(s["index"]), "type": s.get("codec_type"), "codec": s.get("codec_name"),
                            "fps": parse_rate(s.get("avg_frame_rate")) or parse_rate(s.get("r_frame_rate")),
                            "pix_fmt": s.get("pix_fmt"), "rotated": _rotation_of(s),
                            "width": s.get("width"), "height": s.get("height"),
                        }
                        for s in raw if "index" in s
                    ]
            except Exception:
                pass
        try:
            result = run_hidden([self.ffmpeg_path, "-nostdin", "-hide_banner", "-i", src], timeout=10)
            text = (result.stderr or "") + (result.stdout or "")
            found = []
            # "displaymatrix: rotation of -90.00 degrees" akış bloğunun altında; hangi akışa ait olduğunu
            # çözmek yerine temkinli davranılır: varsa video akışları döndürülmüş sayılır.
            rotated = any(
                abs(float(a)) % 360 > 0.5 for a in re.findall(r"rotation of (-?\d+(?:\.\d+)?) degrees", text)
            )
            for m in re.finditer(
                r"Stream #0:(\d+)\S*:\s+(Video|Audio|Subtitle|Data|Attachment):\s+([\w\-]+)([^\n]*)", text
            ):
                video = m.group(2) == "Video"
                fps = re.search(r"(\d+(?:\.\d+)?) fps", m.group(4)) if video else None
                pix = _PIX_FMT_RE.search(m.group(4)) if video else None
                size = re.search(r",\s*(\d{2,5})x(\d{2,5})\b", m.group(4)) if video else None
                found.append({
                    "index": int(m.group(1)), "type": m.group(2).lower(), "codec": m.group(3).lower(),
                    "fps": parse_rate(fps.group(1)) if fps else None,
                    "pix_fmt": pix.group(1) if pix else None, "rotated": video and rotated,
                    "width": int(size.group(1)) if size else None, "height": int(size.group(2)) if size else None,
                })
            return found or None
        except Exception:
            return None

    def _vcodec(self, gpu_mode: str, codec: str) -> str:
        family = gpu_mode if gpu_mode in ENCODER_MAP else "cpu"
        if family == "cpu" and codec == "av1" and self._cpu_av1:
            return self._cpu_av1
        return ENCODER_MAP[family].get(codec, CPU_ENCODERS.get(codec, "libx264"))

    def _resolve_cpu_av1(self) -> None:
        """Bu ffmpeg derlemesinde hangi CPU AV1 kodlayıcısı var? (libsvtav1 öncelikli)"""
        if self._cpu_av1 is not None:
            return
        self._cpu_av1 = next(
            (name for name in CPU_AV1_ENCODERS if encoder_listed(self.ffmpeg_path, name)),
            CPU_AV1_ENCODERS[0],
        )

    def effective_family(self, gpu_mode: str, codec: str) -> str:
        """İstenen (aile x kodek) bu makinede çalışmıyorsa doğrudan 'cpu'.

        Sondaj sonucu süreç boyunca önbelleklenir; çalışmayan kombinasyon her dosyada
        yeniden denenip başarısız olmaz.
        """
        if gpu_mode not in ENCODER_MAP or gpu_mode == "cpu":
            return "cpu"
        encoder = ENCODER_MAP[gpu_mode].get(codec)
        if encoder and encoder_supported(self.ffmpeg_path, encoder):
            return gpu_mode
        log_info(f"{gpu_mode}/{codec} bu makinede desteklenmiyor, doğrudan CPU kullanılacak")
        return "cpu"

    def decode_method(self, family: str, video: Optional[dict]) -> Optional[str]:
        """Donanım çözme yolu: "videotoolbox", "cuda" ya da None (yazılım çözme)."""
        if family == "videotoolbox":
            return "videotoolbox"
        if family != "nvenc" or not cuda_decodable(video):
            return None
        codec = str(video.get("codec")).lower()
        if decode_failed(self.ffmpeg_path, "cuda", codec) or not cuda_pipeline_available(self.ffmpeg_path):
            return None
        return "cuda"

    def build_cmd(
        self,
        src: str,
        dst: str,
        gpu_mode: str,
        codec: str,
        bitrate: str,
        crf: int,
        preset: str,
        audio_bitrate: str,
        max_width: int | None,
        streams: Optional[list[dict]] = None,
        vaapi_device: Optional[str] = None,
        hw_decode: bool = True,
        fps: Optional[float] = None,
        decode: Optional[str] = None,
        trim: Optional[tuple[float, Optional[float]]] = None,
        remove_audio: bool = False,
        amf_bframes: bool = False,
    ) -> list[str]:
        """``decode``: donanım çözme yolu ("cuda", "videotoolbox"); None = ailenin varsayılanı
        (VideoToolbox'ta donanım, diğerlerinde yazılım). ``hw_decode=False`` her zaman yazılım çözer.
        ``trim``: (başlangıç, bitiş | None) saniye — yalnızca bu aralık kodlanır. ``remove_audio``: ses atılır."""
        vcodec = self._vcodec(gpu_mode, codec)
        # Donanım ailesi: yalnızca istenen kodlayıcı gerçekten o ailenin kodlayıcısıysa (ör. macOS'ta
        # av1 için videotoolbox yoktur -> cpu).
        family = gpu_mode if gpu_mode != "cpu" and ENCODER_MAP.get(gpu_mode, {}).get(codec) == vcodec else "cpu"
        dst_ext = os.path.splitext(dst)[1].lower()
        sub_indices, sub_codec = plan_subtitles(streams, dst_ext)
        # -nostdin: ffmpeg klavye/stdin okumasın (konsolsuz exe'de takılma/yanlış 'q' girdisi olmaz).
        cmd = [self.ffmpeg_path, "-nostdin", "-hide_banner", "-y", "-loglevel", "info"]
        method = decode if decode is not None else ("videotoolbox" if family == "videotoolbox" else None)
        if not hw_decode or (method == "cuda" and family != "nvenc"):
            method = None
        # Girdiden önce: VAAPI için -vaapi_device; donanım çözmede -hwaccel videotoolbox / cuda.
        cmd += hw_input_args(family, vaapi_device, method)
        if trim:
            # Girdi tarafında arama: hızlı (baştan çözmez) ve yeniden kodlamada kare doğru; altyazılar da kayar.
            start, end = trim
            if start > 0:
                cmd += ["-ss", f"{start:.3f}"]
            if end is not None:
                cmd += ["-t", f"{end - start:.3f}"]
        cmd += ["-i", src, "-map", "0:v:0"]
        if not remove_audio:
            cmd += ["-map", "0:a?"]
        for index in sub_indices:
            cmd += ["-map", f"0:{index}"]
        cmd += ["-c:v", vcodec]

        if not is_auto_bitrate(bitrate):
            kbps = int(str(bitrate).replace("k", ""))
            max_rate = f"{kbps + 500}k"
            buf = f"{kbps * 2}k"
            if "nvenc" in vcodec:
                cmd += ["-preset", "p6", "-rc", "vbr", "-b:v", bitrate, "-maxrate", max_rate, "-bufsize", buf]
            elif "amf" in vcodec:
                cmd += ["-quality", "quality", "-rc", "vbr_peak", "-b:v", bitrate, "-maxrate", max_rate]
                if amf_bframes and vcodec == "h264_amf":
                    cmd += ["-bf", "3"]
            elif "qsv" in vcodec:
                cmd += ["-preset", "medium", "-b:v", bitrate, "-maxrate", max_rate, "-bufsize", buf]
            elif "videotoolbox" in vcodec:
                cmd += ["-b:v", bitrate, "-maxrate", max_rate, "-bufsize", buf, "-realtime", "0"]
            elif "vaapi" in vcodec:
                cmd += ["-b:v", bitrate, "-maxrate", max_rate, "-bufsize", buf]
            else:
                cmd += cpu_preset_args(vcodec, preset)
                cmd += ["-b:v", bitrate, "-maxrate", max_rate, "-bufsize", buf]
        else:
            if "nvenc" in vcodec:
                cmd += ["-preset", "p6", "-rc", "constqp", "-qp", str(encoder_quality(vcodec, crf)), "-b:v", "0"]
            elif "amf" in vcodec:
                if amf_bframes and vcodec == "h264_amf":
                    q = encoder_quality("h264_amf_bf", crf)
                    cmd += ["-quality", "quality", "-rc", "cqp", "-qp_i", str(q), "-qp_p", str(q),
                            "-qp_b", str(min(51, q + 2)), "-bf", "3"]
                else:
                    q = encoder_quality(vcodec, crf)
                    cmd += ["-quality", "quality", "-rc", "cqp", "-qp_i", str(q), "-qp_p", str(q)]
            elif "qsv" in vcodec:
                cmd += ["-global_quality", str(crf), "-preset", "medium"]
            elif "videotoolbox" in vcodec:
                cmd += ["-q:v", str(max(20, min(65, crf + 25))), "-realtime", "0"]
            elif "vaapi" in vcodec:
                # h264/hevc_vaapi: -qp (0-52). av1_vaapi'de -qp seçeneği yoktur (ffmpeg 6.1 -h encoder=av1_vaapi):
                # CQP kalitesi genel -global_quality ile (AV1 nicemleme indeksi) verilir.
                qp_flag = "-global_quality" if "av1" in vcodec else "-qp"
                cmd += ["-rc_mode", "CQP", qp_flag, str(vaapi_qp(vcodec, crf))]
            else:
                cmd += ["-crf", str(encoder_quality(vcodec, crf))] + cpu_preset_args(vcodec, preset)
                if vcodec == "libaom-av1":
                    cmd += ["-b:v", "0"]  # libaom'da CRF yalnızca b:v 0 ile sabit kalite olur

        mp4_family = dst_ext in MP4_FAMILY_EXTS
        if vcodec in HEVC_ENCODERS and mp4_family:
            cmd += ["-tag:v", "hvc1"]
        if remove_audio:
            cmd += ["-an"]
        else:
            cmd += ["-c:a", "aac", "-b:a", audio_bitrate]
        if sub_codec:
            cmd += ["-c:s", sub_codec]
        if mp4_family:
            cmd += ["-movflags", "+faststart"]
        video = first_video(streams)
        # VAAPI kendi format=nv12,hwupload zincirini kullanır.
        pix_fmt = None if family == "vaapi" else target_pix_fmt(vcodec, (video or {}).get("pix_fmt"))
        filters: list[str] = []
        if max_width:
            # 4:2:0'da genişlik çift olmalı: elle girilen tek değer (ör. 1285) libx264/libx265'i
            # "width not divisible by 2" ile durduruyordu (yükseklik zaten -2 ile çift).
            max_width = max(2, int(max_width) // 2 * 2)
        if fps:  # ölçeklemeden ÖNCE: ölçek süzgeci atılacak karelerle uğraşmaz (GPU karelerinde de çalışır)
            filters.append(f"fps={fps:g}")
        if method == "cuda":
            # Kareler GPU'da: ölçek + biçim tek scale_cuda'da. lanczos: varsayılan bicubic gerçek videoda
            # VMAF'ı 96.4 -> 90.8'e düşürüyordu; lanczos yazılım ölçeğiyle aynı boyutta 95.8.
            opts = [f"w='if(gt(iw,{max_width}),{max_width},iw)'", "h=-2", "interp_algo=lanczos"] if max_width else []
            if pix_fmt:
                opts.append(f"format={pix_fmt}")
            if opts:
                filters.append("scale_cuda=" + ":".join(opts))
        else:
            if odd_size(video) is not False:  # tek ya da bilinmeyen boyut (ölçeklenmeyen kaynak tek kalırdı)
                filters.append(EVEN_CROP)
            if max_width:
                filters.append(f"scale='if(gt(iw,{max_width}),{max_width},iw)':-2")
            if pix_fmt:
                filters.append(f"format={pix_fmt}")
        filters += hw_filter_chain(family)  # VAAPI: önce yazılım ölçekle, sonra format=nv12,hwupload
        if filters:
            cmd += ["-vf", ",".join(filters)]
        if dst_ext == ".m4v":
            # ffmpeg .m4v'yi "ipod" yazıcısıyla yazar ve o yalnızca H.264 kabul eder (HEVC/AV1 başarısızdı).
            cmd += ["-f", "mp4"]
        cmd.append(dst)  # çıktı yolu her zaman son argüman
        return cmd

    @staticmethod
    def _terminate(proc) -> None:
        """ffmpeg'i sonlandır: Windows'ta terminate -> kill; POSIX'te tüm süreç grubuna
        SIGTERM -> bekle -> SIGKILL (zombi bırakmaz)."""
        terminate_process_tree(proc)

    @staticmethod
    def _release_stderr(proc, reader_thread) -> None:
        """stderr borusunu kapat (her ffmpeg çalıştırmasında açık dosya sızmasın). Okuyucu iş
        parçacığı hâlâ okuyorsa (süreç ölmedi) altından kapatılmaz; daemon olduğu için sorun değil."""
        reader_thread.join(timeout=2.0)
        if reader_thread.is_alive():
            return
        closer = getattr(getattr(proc, "stderr", None), "close", None)
        if closer is not None:
            try:
                closer()
            except Exception:
                pass

    def _run(
        self,
        cmd: list[str],
        cancel_event: Optional[threading.Event],
        total_sec: float,
        progress_cb: Callable[[float], None] | None,
    ) -> str:
        try:
            proc = popen_hidden(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                universal_newlines=True,
                bufsize=1,
                kill_on_parent_exit=True,
            )
        except Exception as exc:
            return f"{START_FAILED_PREFIX}: {exc}"

        # stderr okuması bloklayıcıdır (ffmpeg sessiz kalırsa saatlerce satır gelmeyebilir);
        # ayrı bir thread satırları kuyruğa koyar, ana döngü iptali her 0.2 sn'de kontrol eder.
        lines: "queue.Queue[Optional[str]]" = queue.Queue()

        def reader() -> None:
            try:
                assert proc.stderr is not None
                for line in proc.stderr:
                    lines.put(line)
            except Exception:
                pass
            finally:
                lines.put(None)

        reader_thread = threading.Thread(target=reader, name="ffmpeg-stderr", daemon=True)
        reader_thread.start()

        time_re = re.compile(r"time=(\d{2}):(\d{2}):(\d{2}\.\d+)")
        last_err = ""
        try:
            while True:
                if cancel_event is not None and cancel_event.is_set():
                    self._terminate(proc)
                    return CANCELLED
                try:
                    line = lines.get(timeout=0.2)
                except queue.Empty:
                    continue
                if line is None:
                    break
                text = line.strip()
                if text:
                    last_err = text
                if total_sec > 0 and progress_cb:
                    match = time_re.search(line)
                    if match:
                        h, m, s = map(float, match.groups())
                        progress_cb(min(1.0, (h * 3600 + m * 60 + s) / total_sec))

            # stderr kapandı: süreç bitmek üzere; iptale duyarlı kalarak çıkışı bekle.
            while proc.poll() is None:
                if cancel_event is not None and cancel_event.is_set():
                    self._terminate(proc)
                    return CANCELLED
                try:
                    proc.wait(timeout=0.2)
                except subprocess.TimeoutExpired:
                    continue
            if proc.returncode == 0:
                if progress_cb:
                    progress_cb(1.0)
                return "ok"
            return last_err or f"çıkış kodu {proc.returncode}"
        except Exception as exc:
            kill_process_tree(proc)
            return str(exc)
        finally:
            self._release_stderr(proc, reader_thread)

    def compress(
        self,
        src: str,
        dst: str,
        gpu_mode: str,
        codec: str,
        bitrate: str,
        crf: int,
        preset: str,
        audio_bitrate: str,
        max_width: int | None,
        cancel_event: Optional[threading.Event] = None,
        progress_cb: Callable[[float], None] | None = None,
        fps: Optional[float] = None,
        trim=None,
        remove_audio: bool = False,
    ):
        self.last_output = None
        dst = video_output_path(dst, codec)  # iş parçacığı zaten uygun yolu verir; doğrudan çağrılara karşı
        os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
        # ffmpeg doğrudan dst'ye değil geçici dosyaya yazar (uzantı korunur: biçim uzantıdan çıkar).
        # Başarıda os.replace; hata/iptalde geçici dosya silinir, dst hiç yarım kalmaz.
        tmp = temp_path_for(dst)
        discard_temp(tmp)
        try:
            duration = self.duration(src)
            trim = normalize_trim(trim, duration)
            # Kırpılan parçada ffmpeg'in time= değeri 0'dan başlar: ilerleme kırpılmış süreye göre.
            progress_total = trimmed_duration(duration, trim)
            # Kırpma / ses kaldırma istenen bir düzenleme: çıktı kaynaktan büyük çıksa bile kaynak kopyalanmaz.
            edited = bool(trim or remove_audio)
            extra = {"trim": trim, "remove_audio": remove_audio}
            if codec == "av1":
                self._resolve_cpu_av1()
            family = self.effective_family(gpu_mode, codec)
            gpu_encoder = ENCODER_MAP[family].get(codec) if family != "cpu" else None
            streams = self.probe_streams(src)
            video = first_video(streams)
            fps = effective_fps(fps, source_fps(streams))
            vaapi_device = find_vaapi_device() if family == "vaapi" else None
            decode = self.decode_method(family, video)
            # AMD H.264: B-kareleri kart destekliyorsa (kısa sondaj, oturumda bir kez)
            amf_bf = family == "amf" and codec == "h264" and amf_h264_bframes(self.ffmpeg_path)
            cmd = self.build_cmd(
                src, tmp, family, codec, bitrate, crf, preset, audio_bitrate, max_width, streams=streams,
                vaapi_device=vaapi_device, fps=fps, decode=decode, amf_bframes=amf_bf, **extra,
            )
            result = self._run(cmd, cancel_event, progress_total, progress_cb)
            if result not in ("ok", CANCELLED) and decode:
                # Donanım çözme bazı girdilerde başarısız olabilir: önce AYNI donanım kodlayıcıyla
                # yazılım çözmeyle yeniden dene, ancak sonra CPU'ya düş.
                log_info(f"{family} donanım çözme ({decode}) başarısız, yazılım çözmeyle deneniyor")
                discard_temp(tmp)
                cmd = self.build_cmd(
                    src, tmp, family, codec, bitrate, crf, preset, audio_bitrate, max_width,
                    streams=streams, vaapi_device=vaapi_device, hw_decode=False, fps=fps, amf_bframes=amf_bf, **extra,
                )
                result = self._run(cmd, cancel_event, progress_total, progress_cb)
                if result == "ok" and decode == "cuda":
                    mark_decode_failed(self.ffmpeg_path, decode, str(video.get("codec")).lower())

            used = f"{codec.upper()} ({family.upper()})"

            if result == "ok":
                if gpu_encoder:
                    record_gpu_result(self.ffmpeg_path, gpu_encoder, gpu_failed_cpu_ok=False)
            elif result == CANCELLED:
                return False, CANCELLED
            elif family != "cpu":
                log_info(f"{family} başarısız, CPU deneniyor")
                discard_temp(tmp)
                cmd_cpu = self.build_cmd(
                    src, tmp, "cpu", codec, bitrate, crf, preset, audio_bitrate, max_width, streams=streams,
                    fps=fps, **extra,
                )
                result_cpu = self._run(cmd_cpu, cancel_event, progress_total, progress_cb)
                if result_cpu == "ok":
                    used = f"{codec.upper()} (CPU)"
                    # GPU başarısız ama CPU başarılı: sorun GPU yolunda; tekrarlanırsa kapat.
                    record_gpu_result(self.ffmpeg_path, gpu_encoder, gpu_failed_cpu_ok=True)
                elif result_cpu == CANCELLED:
                    return False, CANCELLED
                else:
                    return False, result_cpu
            else:
                return False, result

            if not os.path.exists(tmp):
                return False, "ffmpeg çıktı dosyası üretmedi"

            first = os.path.getsize(src)
            new = os.path.getsize(tmp)
            if new >= first and not edited:
                log_info("Çıktı küçülmedi, orijinal kopyalandı")
                # Kaynak kendi biçimiyle kendi uzantısında kalır (bir AVI ".mp4" adıyla yazılmasın).
                keep = dst
                if os.path.splitext(src)[1].lower() != os.path.splitext(dst)[1].lower():
                    keep = os.path.splitext(dst)[0] + os.path.splitext(src)[1]
                keep_tmp = temp_path_for(keep)
                try:
                    discard_temp(tmp)
                    shutil.copy2(src, keep_tmp)
                    commit_temp(keep_tmp, keep)
                    self.last_output = keep
                    return True, f"{used} (Orijinal korundu)"
                except Exception as exc:
                    return False, f"Orijinal kopyalama hatası: {exc}"
                finally:
                    discard_temp(keep_tmp)
            try:
                commit_temp(tmp, dst)
                self.last_output = dst
            except OSError as exc:
                return False, f"Çıktı taşınamadı: {exc}"
            return True, used
        finally:
            discard_temp(tmp)


def build_frame_extract_cmd(ffmpeg_path: str, file_path: str, seconds: float) -> list[str]:
    """Önizleme için tek kare (PNG, stdout) çıkaran ffmpeg komutu."""
    return [
        ffmpeg_path, "-nostdin", "-hide_banner", "-loglevel", "error",
        "-ss", f"{max(0.0, seconds):.2f}",
        "-i", file_path,
        "-vframes", "1",
        "-f", "image2pipe",
        "-vcodec", "png",
        "-",
    ]
