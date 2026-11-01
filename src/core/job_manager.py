"""Kuyruk işçisi — hatalar pencereyi düşürmez."""

from __future__ import annotations

import os
import threading
import time
from collections import deque
from concurrent.futures import CancelledError, FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
from itertools import groupby
from pathlib import Path

from PIL import Image
from PyQt6.QtCore import pyqtSignal

from .app_info import OUTPUT_FOLDER_NAME
from .atomic_output import CANCELLED, is_partial_name, sweep_partial_files
from .image_compressor import IMAGE_EXTS, ImageCompressor
from .video_compressor import VIDEO_EXTS, VideoCompressor, video_output_path
from .workers import DaemonWorker
from ..utils.config import FILE_TYPE_ALL, FILE_TYPE_IMAGES, FILE_TYPE_VIDEOS, normalize_file_type
from ..utils.helpers import format_bytes, format_duration
from ..utils.logger import log_error, log_info

SKIP_DIR_NAMES = {"compressed", "sıkıştırılmış", OUTPUT_FOLDER_NAME.casefold()}

# Paralel görsel çözümleme bellek bütçesi: işçi sayısı en çok IMAGE_MAX_WORKERS, ancak
# aynı anda işlenen görsellerin tahmini bellek toplamı IMAGE_MEMORY_BUDGET'i aşmaz
# (çok büyük görsellerde işçi sayısı kendiliğinden düşer; en az bir işçi her zaman çalışır).
IMAGE_MAX_WORKERS = 8
IMAGE_MEMORY_BUDGET = 1536 * 1024 * 1024
_BYTES_PER_PIXEL_BUDGET = 12  # çözümleme + dönüşüm/yeniden boyutlama kopyaları için kaba tahmin
_MIN_IMAGE_COST = 16 * 1024 * 1024
_CANCEL_POLL_SECONDS = 0.2

# Kaynak uzantısı -> çıktının .jpg olarak yazılabildiği durumlar (ImageCompressor ile uyumlu):
# PNG saydam değilse JPEG'e, HEIC/HEIF her zaman JPEG'e dönüştürülür.
JPEG_FALLBACK_EXTS = {".png", ".heic", ".heif"}


def output_candidates(dst: str, ext: str) -> list[str]:
    """Bu kaynak için çıktının yazılmış olabileceği tüm yollar."""
    candidates = [dst]
    if ext.lower() in JPEG_FALLBACK_EXTS:
        candidates.append(str(Path(dst).with_suffix(".jpg")))
    return candidates


def output_exists(dst: str, ext: str) -> bool:
    """Tamamlanmış bir çıktı var mı?

    Çıktılar atomik yazıldığı için asıl adda bulunan dosya tamdır; yalnızca eski
    sürümlerden kalma 0 baytlık yarım dosyalar "mevcut" sayılmaz.
    """
    for candidate in output_candidates(dst, ext):
        try:
            if os.path.isfile(candidate) and os.path.getsize(candidate) > 0:
                return True
        except OSError:
            continue
    return False


def image_worker_limit() -> int:
    return max(1, min(IMAGE_MAX_WORKERS, os.cpu_count() or 4))


def estimate_image_memory(path: str) -> int:
    """Bir görselin çözümlenip sıkıştırılması için kabaca bellek ihtiyacı (bayt)."""
    try:
        file_size = os.path.getsize(path)
    except OSError:
        file_size = 0
    # JXL eklentisi dosyayı açarken tamamını çözer; başlık okumak pahalı, boyuttan tahmin et.
    if Path(path).suffix.lower() != ".jxl":
        try:
            with Image.open(path) as probe:
                width, height = probe.size
            return max(_MIN_IMAGE_COST, int(width) * int(height) * _BYTES_PER_PIXEL_BUDGET)
        except Exception:  # noqa: BLE001 - bozuk dosya vb.: boyuttan tahmin et
            pass
    return max(_MIN_IMAGE_COST, file_size * 30)


def collect_files(
    sources: list[str],
    output_dir: str,
    file_type: str,
    scan_subfolders: bool,
    keep_order: bool = False,
) -> tuple[str, list[str]]:
    """Kaynak dosya/klasör listesinden işlenecek dosyaları çıkar."""
    file_type = normalize_file_type(file_type)
    exts: set[str] = set()
    if file_type in (FILE_TYPE_IMAGES, FILE_TYPE_ALL):
        exts |= IMAGE_EXTS
    if file_type in (FILE_TYPE_VIDEOS, FILE_TYPE_ALL):
        exts |= VIDEO_EXTS

    files: list[str] = []
    roots: list[str] = []
    for src in sources:
        if os.path.isfile(src):
            if Path(src).suffix.lower() in exts:
                files.append(os.path.abspath(src))
            roots.append(os.path.dirname(os.path.abspath(src)))
        elif os.path.isdir(src):
            root = os.path.abspath(src)
            roots.append(root)
            out_abs = os.path.abspath(output_dir)
            walker = os.walk(root) if scan_subfolders else [(root, [], os.listdir(root))]
            for folder, _, names in walker:
                folder_abs = os.path.abspath(folder)
                if os.path.basename(folder_abs).casefold() in SKIP_DIR_NAMES:
                    continue
                if out_abs != root and out_abs.startswith(root + os.sep):
                    if folder_abs == out_abs or folder_abs.startswith(out_abs + os.sep):
                        continue
                for name in names:
                    if is_partial_name(name):
                        continue
                    if Path(name).suffix.lower() in exts:
                        files.append(os.path.join(folder, name))

    common = os.getcwd()
    if roots:
        try:
            common = os.path.commonpath(roots)
        except ValueError:
            common = os.path.dirname(files[0]) if files else roots[0]
    unique = list(dict.fromkeys(files))
    if not keep_order:
        unique = sorted(unique)
    return common, unique


def relative_output(src: str, common_root: str, output_dir: str) -> str:
    output_dir_abs = os.path.abspath(output_dir)
    try:
        rel = os.path.relpath(src, common_root)
        if rel.startswith("..") or os.path.isabs(rel):
            rel = os.path.basename(src)
        else:
            parts = [p for p in os.path.normpath(rel).split(os.sep) if p and p != ".."]
            rel = os.path.join(*parts) if parts else os.path.basename(src)
    except (ValueError, Exception):
        rel = os.path.basename(src)

    target = os.path.abspath(os.path.join(output_dir_abs, rel))
    try:
        if os.path.commonpath([output_dir_abs, target]) != output_dir_abs:
            target = os.path.join(output_dir_abs, os.path.basename(src))
    except Exception:
        target = os.path.join(output_dir_abs, os.path.basename(src))
    return target


@dataclass
class _Stats:
    total: int
    done: int = 0
    ok: int = 0
    skip: int = 0
    fail: int = 0
    bytes_in: int = 0
    bytes_out: int = 0


class JobWorker(DaemonWorker):
    log = pyqtSignal(str)
    progress = pyqtSignal(int, int)
    file_started = pyqtSignal(str)
    file_progress = pyqtSignal(str, float)
    file_done = pyqtSignal(str, str, object)  # path, status, extra
    finished_job = pyqtSignal(dict)

    def __init__(self, settings: dict, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.cancel_event = threading.Event()

    def stop(self):
        self.cancel_event.set()

    def _video_dst(self, natural: str, codec: str) -> str:
        """Video çıktı yolu (bkz. ``video_output_path``). Yeni ad başka bir kaynağın çıktısıysa (aynı klasörde
        hem film.avi hem film.mp4) ``film (avi).mp4`` yazılır; biri diğerini ezmez ya da "zaten var" diye atlanmaz."""
        dst = video_output_path(natural, codec)
        if dst != natural and os.path.normcase(dst) in getattr(self, "_natural_outputs", set()):
            root, ext = os.path.splitext(natural)
            dst = f"{root} ({ext[1:].lower()}).mp4"
        return dst

    def file_setting(self, src: str, key: str):
        """Dosyaya özel istisna varsa o (None = orijinal), yoksa genel ayar.

        ``settings["overrides"]`` arayüzle paylaşılır: iş sürerken henüz başlamamış dosyaya verilen
        istisna o dosya başladığında geçerli olur (dosya başlarken bir kez okunur)."""
        ov = (self.settings.get("overrides") or {}).get(src) or {}
        return ov[key] if key in ov else self.settings.get(key)

    def run(self):
        try:
            self._run_inner()
        except Exception as exc:
            log_error("İş kuyruğu beklenmeyen hata", exc)
            self.log.emit(f"Beklenmeyen hata: {exc}")
            self.finished_job.emit({
                "cancelled": False,
                "ok": 0, "skip": 0, "fail": 0,
                "bytes_in": 0, "bytes_out": 0,
                "elapsed": 0,
            })

    def _run_inner(self):
        s = self.settings
        sources = s["sources"]
        output_dir = s["output_dir"]
        common, files = collect_files(
            sources, output_dir, s["file_type"], s["scan_subfolders"],
            keep_order=bool(s.get("keep_order")),
        )
        # Her kaynağın uzantısı korunmuş çıktı yolu: .avi -> .mp4 gibi değişen bir çıktı, aynı klasördeki
        # başka bir kaynağın çıktısıyla çakışmasın diye.
        self._natural_outputs = {os.path.normcase(relative_output(f, common, output_dir)) for f in files}
        total = len(files)
        if total == 0:
            self.log.emit("Seçilen türde işlenecek dosya bulunamadı.")
            self.finished_job.emit({
                "cancelled": False, "ok": 0, "skip": 0, "fail": 0,
                "bytes_in": 0, "bytes_out": 0,
                "elapsed": 0,
            })
            return

        stale = sweep_partial_files(output_dir)
        if stale:
            self.log.emit(f"{stale} yarım kalmış geçici dosya temizlendi.")
            log_info(f"Eski geçici dosyalar silindi: {stale}")

        self.log.emit(f"{total} dosya bulundu. Sıkıştırma başlıyor…")
        self.progress.emit(0, total)
        job_t0 = time.time()

        video = None
        ffmpeg = s.get("ffmpeg_path")
        if ffmpeg:
            video = VideoCompressor(ffmpeg, s.get("ffprobe_path"))

        stats = _Stats(total=total)

        for is_image_group, group in groupby(files, key=lambda p: Path(p).suffix.lower() in IMAGE_EXTS):
            if self.cancel_event.is_set():
                break
            group_files = list(group)
            if is_image_group:
                self._run_image_group(group_files, common, output_dir, stats)
            else:
                self._run_other_group(group_files, common, output_dir, video, stats)

        self.finished_job.emit({
            "cancelled": self.cancel_event.is_set(),
            "ok": stats.ok, "skip": stats.skip, "fail": stats.fail,
            "bytes_in": stats.bytes_in, "bytes_out": stats.bytes_out,
            "elapsed": time.time() - job_t0,
        })
        log_info(f"İş bitti ok={stats.ok} skip={stats.skip} fail={stats.fail}")

    # ------------------------------------------------------------------ resimler
    def _compress_image(self, src: str, dst: str):
        s = self.settings
        first_size = os.path.getsize(src)
        res = self.file_setting(src, "image_res")
        success, result = ImageCompressor.compress(
            src, dst,
            max_width=res,
            max_height=res,
            fixed_quality=s.get("image_quality"),
            cancel_event=self.cancel_event,
        )
        return success, result, first_size

    def _run_image_group(self, files: list[str], common: str, output_dir: str, stats: _Stats) -> None:
        """Görselleri sınırlı pencereyle paralel işler.

        Tüm işler baştan havuza gönderilmez: en fazla ``image_worker_limit()`` iş uçuşta
        tutulur ve tahmini bellek toplamı bütçeyi aşmaz. İptalde henüz gönderilmemiş
        dosyalar hiç başlatılmaz, bekleyen future'lar iptal edilir, çalışanlar
        ``cancel_event``'i kendileri kontrol eder.
        """
        workers = image_worker_limit()
        pending = deque(files)
        inflight: dict = {}
        in_use = 0
        pool = ThreadPoolExecutor(max_workers=workers)
        try:
            while pending or inflight:
                if self.cancel_event.is_set():
                    pending.clear()

                while pending and len(inflight) < workers:
                    src = pending[0]
                    name = os.path.basename(src)
                    ext = Path(src).suffix.lower()
                    dst = relative_output(src, common, output_dir)
                    if output_exists(dst, ext):
                        pending.popleft()
                        self.file_started.emit(src)
                        stats.skip += 1
                        stats.done += 1
                        self.log.emit(f"Atlandı (zaten mevcut): {name}")
                        self.file_done.emit(src, "skip", None)
                        self.progress.emit(stats.done, stats.total)
                        continue
                    cost = estimate_image_memory(src)
                    if inflight and in_use + cost > IMAGE_MEMORY_BUDGET:
                        break  # bellek bütçesi dolu: bir iş bitene kadar bekle
                    pending.popleft()
                    self.file_started.emit(src)
                    try:
                        os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
                    except OSError as exc:
                        stats.fail += 1
                        stats.done += 1
                        self.log.emit(f"Hata ({name}): {exc}")
                        self.file_done.emit(src, "fail", str(exc))
                        self.progress.emit(stats.done, stats.total)
                        continue
                    fut = pool.submit(self._compress_image, src, dst)
                    inflight[fut] = (src, dst, name, cost)
                    in_use += cost

                if not inflight:
                    break

                done, _ = wait(list(inflight), timeout=_CANCEL_POLL_SECONDS, return_when=FIRST_COMPLETED)
                for fut in done:
                    src, dst, name, cost = inflight.pop(fut)
                    in_use -= cost
                    self._finish_image(fut, src, dst, name, stats)

                if self.cancel_event.is_set():
                    for fut in list(inflight):
                        if fut.cancel():  # henüz başlamamış iş
                            src, dst, name, cost = inflight.pop(fut)
                            in_use -= cost
                            self._finish_image(fut, src, dst, name, stats)
        finally:
            pool.shutdown(wait=True, cancel_futures=True)

    def _finish_image(self, fut, src: str, dst: str, name: str, stats: _Stats) -> None:
        stats.done += 1
        try:
            success, result, first_size = fut.result()
            if success:
                out_path = result if isinstance(result, str) and os.path.exists(result) else dst
                last_size = os.path.getsize(out_path)
                stats.ok += 1
                stats.bytes_in += first_size
                stats.bytes_out += last_size
                pct = ((first_size - last_size) / first_size) * 100 if first_size else 0
                self.log.emit(
                    f"Resim [{stats.done}/{stats.total}]: {name} "
                    f"({format_bytes(first_size)} → {format_bytes(last_size)} | -%{pct:.1f})"
                )
                self.file_done.emit(src, "ok", {"in": first_size, "out": last_size})
            elif result == CANCELLED:
                self.file_done.emit(src, "cancel", None)
            else:
                stats.fail += 1
                self.log.emit(str(result))
                self.file_done.emit(src, "fail", str(result))
        except CancelledError:
            self.file_done.emit(src, "cancel", None)
        except Exception as exc:
            stats.fail += 1
            self.log.emit(f"Hata ({name}): {exc}")
            self.file_done.emit(src, "fail", str(exc))
        self.progress.emit(stats.done, stats.total)

    # ------------------------------------------------------------------ videolar
    def _run_other_group(self, files: list[str], common: str, output_dir: str, video, stats: _Stats) -> None:
        s = self.settings
        for src in files:
            if self.cancel_event.is_set():
                self.log.emit("İşlem durduruldu.")
                break
            stats.done += 1
            name = os.path.basename(src)
            ext = Path(src).suffix.lower()
            dst = natural = relative_output(src, common, output_dir)
            if ext in VIDEO_EXTS:
                dst = self._video_dst(natural, s["codec"])
                if dst != natural:
                    self.log.emit(
                        f"{name}: {ext} bu kodeği ({s['codec'].upper()}) düzgün taşımıyor, "
                        f"{os.path.basename(dst)} olarak kaydedilecek"
                    )
            self.file_started.emit(src)

            try:
                if output_exists(dst, ext) or (natural != dst and output_exists(natural, ext)):
                    stats.skip += 1
                    self.log.emit(f"Atlandı (zaten mevcut): {name}")
                    self.file_done.emit(src, "skip", None)
                    self.progress.emit(stats.done, stats.total)
                    continue

                os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
                first_size = os.path.getsize(src)

                if ext in VIDEO_EXTS:
                    if not video:
                        stats.fail += 1
                        msg = "FFmpeg yok, video atlandı"
                        self.log.emit(f"{msg}: {name}")
                        self.file_done.emit(src, "fail", msg)
                    else:
                        self.log.emit(f"Video [{stats.done}/{stats.total}]: {name} …")
                        self.file_progress.emit(src, 0.0)
                        started = time.time()

                        def cb(ratio, path=src):
                            self.file_progress.emit(path, ratio)

                        success, msg = video.compress(
                            src, dst,
                            gpu_mode=s["gpu_mode"],
                            codec=s["codec"],
                            bitrate=s["bitrate"],
                            crf=s["crf"],
                            preset=s["preset"],
                            audio_bitrate=s["audio_bitrate"],
                            max_width=self.file_setting(src, "video_res"),
                            cancel_event=self.cancel_event,
                            progress_cb=cb,
                            fps=self.file_setting(src, "fps"),
                            trim=self.file_setting(src, "trim"),
                            remove_audio=bool(self.file_setting(src, "remove_audio")),
                        )
                        elapsed = format_duration(time.time() - started, s.get("lang"))
                        if success:
                            # orijinal korunduysa kendi uzantısıyla yazılmış olabilir (bkz. compress)
                            last_size = os.path.getsize(getattr(video, "last_output", None) or dst)
                            stats.ok += 1
                            stats.bytes_in += first_size
                            stats.bytes_out += last_size
                            pct = ((first_size - last_size) / first_size) * 100 if first_size else 0
                            self.log.emit(
                                f"Tamamlandı [{msg}]: {name} "
                                f"({format_bytes(first_size)} → {format_bytes(last_size)} | -%{pct:.1f} | {elapsed})"
                            )
                            self.file_done.emit(src, "ok", {"in": first_size, "out": last_size, "msg": msg})
                        elif msg == CANCELLED:
                            self.log.emit("İşlem durduruldu.")
                            self.file_done.emit(src, "cancel", None)
                            break
                        else:
                            stats.fail += 1
                            short = str(msg)[:160]
                            self.log.emit(f"Video hatası ({name}): {short}")
                            self.file_done.emit(src, "fail", short)
                        self.file_progress.emit(src, 1.0)
                else:
                    stats.skip += 1
                    self.file_done.emit(src, "skip", None)
            except Exception as exc:
                stats.fail += 1
                log_error(f"Dosya işlenemedi: {src}", exc)
                self.log.emit(f"Hata ({name}): {exc}")
                self.file_done.emit(src, "fail", str(exc))

            self.progress.emit(stats.done, stats.total)
