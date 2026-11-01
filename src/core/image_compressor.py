"""Resim sıkıştırma (Pillow + piexif)."""

from __future__ import annotations

import os
from pathlib import Path

from PIL import Image, ImageFile, ImageOps

from .atomic_output import CANCELLED, commit_temp, discard_temp, temp_path_for

try:
    import piexif
except ImportError:
    piexif = None

try:
    import pillow_heif
    pillow_heif.register_heif_opener()
except ImportError:
    pass

try:
    import pillow_avif  # noqa: F401
except ImportError:
    pass

try:
    import imagecodecs
    HAS_IMAGECODECS = True
except ImportError:
    HAS_IMAGECODECS = False


def _register_jxl_support() -> None:
    if not HAS_IMAGECODECS:
        return
    try:
        class JxlImageFile(ImageFile.ImageFile):
            format = "JXL"
            format_description = "JPEG XL image"

            def _open(self) -> None:
                data = self.fp.read()
                arr = imagecodecs.jpegxl_decode(data)
                img = Image.fromarray(arr)
                self._size = img.size
                self._mode = img.mode
                self._arr = arr

            def load(self):
                if hasattr(self, "_arr"):
                    img = Image.fromarray(self._arr)
                    self.im = img.im
                    del self._arr
                return ImageFile.ImageFile.load(self)

        Image.register_open(
            JxlImageFile.format,
            JxlImageFile,
            lambda prefix: prefix.startswith(b"\xff\n") or prefix.startswith(b"\x00\x00\x00\x0cJXL \r\n\x87\n"),
        )
        Image.register_extension(JxlImageFile.format, ".jxl")
        Image.register_mime(JxlImageFile.format, "image/jxl")
    except Exception:
        pass


_register_jxl_support()

# Bozuk/kesik görsel BAŞARILI sayılmasın: True iken eksik veri sessizce gri/yarım olarak
# kaydediliyor ve iş "ok" görünüyordu. False iken Pillow OSError verir ve dosya "hata" olur.
ImageFile.LOAD_TRUNCATED_IMAGES = False

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".avif", ".jxl"}

# Pillow JPEG yazıcısı APP1 işaretçisinde en çok 65533 bayt EXIF kabul eder (aşarsa ValueError).
_MAX_EXIF_BYTES = 65000

_RGB_MODES = frozenset({"RGB", "RGBA", "P", "PA"})
_GRAY_MODES = frozenset({"L", "LA"})


def _icc_for_mode(icc, mode: str):
    """ICC profili yalnızca renk uzayı kaydedilen görselin kipiyle uyuşuyorsa korunur.

    Örn. CMYK profili RGB'ye çevrilmiş görsele eklenirse renkler bozulur; bu durumda düşürülür.
    """
    if not icc or not isinstance(icc, (bytes, bytearray)) or len(icc) < 20:
        return None
    space = bytes(icc[16:20])
    if space == b"RGB " and mode in _RGB_MODES:
        return bytes(icc)
    if space == b"GRAY" and mode in _GRAY_MODES:
        return bytes(icc)
    if space == b"CMYK" and mode == "CMYK":
        return bytes(icc)
    return None


def _prepare_exif(exif):
    """Kaynağın (HEIC dahil) ham EXIF baytlarını JPEG'e yazılabilir hale getirir.

    ``piexif.load(src)`` yalnızca JPEG/TIFF dosyalarını okur; HEIC'te hata verip EXIF'i kaybettiriyordu.
    Artık Pillow/pillow_heif'in açtığı ``img.info["exif"]`` baytları doğrudan kullanılır;
    Orientation 1'e çekilir (görsel zaten döndürüldü) ve çok büyükse küçük resim çıkarılır.
    """
    if not exif or not isinstance(exif, (bytes, bytearray)):
        return None
    data = bytes(exif)
    if piexif is not None:
        try:
            parsed = piexif.load(data)
            changed = False
            if parsed.get("0th", {}).get(piexif.ImageIFD.Orientation, 1) != 1:
                parsed["0th"][piexif.ImageIFD.Orientation] = 1
                changed = True
            if len(data) > _MAX_EXIF_BYTES:
                parsed["thumbnail"] = None
                parsed["1st"] = {}
                changed = True
            if changed:
                data = piexif.dump(parsed)
        except Exception:
            pass  # ayrıştırılamadı: ham baytlar boyut denetiminden geçerse aynen korunur
    return data if len(data) <= _MAX_EXIF_BYTES else None


def _save_atomic(img, target: str, fmt: str, **opts) -> None:
    """Görseli önce geçici dosyaya yaz, başarıda asıl ada taşı; hatada geçiciyi sil."""
    tmp = temp_path_for(target)
    try:
        img.save(tmp, fmt, **opts)
        commit_temp(tmp, target)
    except BaseException:
        discard_temp(tmp)
        raise


def _write_bytes_atomic(target: str, data: bytes) -> None:
    tmp = temp_path_for(target)
    try:
        with open(tmp, "wb") as handle:
            handle.write(data)
        commit_temp(tmp, target)
    except BaseException:
        discard_temp(tmp)
        raise


class ImageCompressor:
    QUALITY = {
        "huge": {"size": 5000, "quality": 78},
        "large": {"size": 2000, "quality": 84},
        "mid": {"size": 1000, "quality": 88},
        "small": {"size": 0, "quality": 90},
    }

    @staticmethod
    def has_transparency(img) -> bool:
        if img.mode == "RGBA":
            extrema = img.getextrema()
            if extrema[3][0] < 255:
                return True
        if img.mode == "P" and "transparency" in img.info:
            return True
        if img.mode == "LA":
            return True
        return False

    @classmethod
    def optimal_quality(cls, size_kb: float) -> int:
        a = cls.QUALITY
        if size_kb > a["huge"]["size"]:
            return a["huge"]["quality"]
        if size_kb > a["large"]["size"]:
            return a["large"]["quality"]
        if size_kb > a["mid"]["size"]:
            return a["mid"]["quality"]
        return a["small"]["quality"]

    @classmethod
    def compress(
        cls,
        src: str,
        dst: str,
        max_width=None,
        max_height=None,
        fixed_quality=None,
        cancel_event=None,
    ):
        """Görseli sıkıştırır. ``cancel_event`` ayarlıysa ağır adımlar arasında kontrol edilir
        ve ``(False, CANCELLED)`` döner (geçici dosya bırakılmaz)."""

        def cancelled() -> bool:
            return cancel_event is not None and cancel_event.is_set()

        if cancelled():
            return False, CANCELLED
        try:
            size_kb = os.path.getsize(src) / 1024
            with Image.open(src) as img:
                img = ImageOps.exif_transpose(img)
                if cancelled():
                    return False, CANCELLED
                # exif_transpose Orientation'ı info["exif"]'ten çıkarır; metaveriyi bundan sonra al.
                src_icc = img.info.get("icc_profile")
                src_exif = img.info.get("exif")
                if max_width and max_height:
                    if img.width > max_width or img.height > max_height:
                        ratio = min(max_width / img.width, max_height / img.height, 1.0)
                        if ratio < 1.0:
                            img = img.resize(
                                (int(round(img.width * ratio)), int(round(img.height * ratio))),
                                Image.Resampling.LANCZOS,
                            )
                if cancelled():
                    return False, CANCELLED
                ext = Path(src).suffix.lower()
                dst_ext = Path(dst).suffix.lower()
                quality = int(fixed_quality if fixed_quality is not None else cls.optimal_quality(size_kb))

                # JXL Çıktı
                if dst_ext == ".jxl" or (ext == ".jxl" and dst_ext == ".jxl"):
                    if HAS_IMAGECODECS:
                        import numpy as np
                        if img.mode not in ("RGB", "RGBA", "L"):
                            img = img.convert("RGB")
                        arr = np.asarray(img)
                        jxl_bytes = imagecodecs.jpegxl_encode(arr, level=quality, effort=7)
                        _write_bytes_atomic(dst, jxl_bytes)
                        return True, dst

                # AVIF Çıktı
                if dst_ext == ".avif" or (ext == ".avif" and dst_ext == ".avif"):
                    if img.mode in ("RGBA", "LA", "P") and cls.has_transparency(img):
                        img = img.convert("RGBA")
                    elif img.mode != "RGB":
                        img = img.convert("RGB")
                    opts = {"quality": quality}
                    icc = _icc_for_mode(src_icc, img.mode)
                    if icc:
                        opts["icc_profile"] = icc
                    _save_atomic(img, dst, "AVIF", **opts)
                    return True, dst

                # WebP Çıktı
                if dst_ext == ".webp" or ext == ".webp":
                    if img.mode in ("RGBA", "LA", "P") and cls.has_transparency(img):
                        img = img.convert("RGBA")
                    elif img.mode != "RGB":
                        img = img.convert("RGB")
                    opts = {"quality": quality, "method": 6}
                    icc = _icc_for_mode(src_icc, img.mode)
                    if icc:
                        opts["icc_profile"] = icc
                    _save_atomic(img, dst, "WEBP", **opts)
                    return True, dst

                # JPEG / HEIC Çıktı
                if ext in (".jpg", ".jpeg", ".heic", ".heif") or dst_ext in (".jpg", ".jpeg"):
                    if img.mode in ("RGBA", "P", "LA"):
                        img = img.convert("RGB")
                    if ext in (".heic", ".heif") and dst_ext in (".heic", ".heif"):
                        dst = str(Path(dst).with_suffix(".jpg"))
                    exif_bytes = _prepare_exif(src_exif)
                    opts = {"quality": quality, "optimize": True, "progressive": size_kb > 1024}
                    if exif_bytes:
                        opts["exif"] = exif_bytes
                    icc = _icc_for_mode(src_icc, img.mode)
                    if icc:
                        opts["icc_profile"] = icc
                    _save_atomic(img, dst, "JPEG", **opts)
                    return True, dst

                # PNG Çıktı
                if ext == ".png":
                    if cls.has_transparency(img):
                        # quantize LA (gri + saydamlık) kabul etmez ("image has wrong mode"): RGBA'ya çevrilir.
                        if img.mode not in ("RGBA", "P"):
                            img = img.convert("RGBA")
                        palet = img.quantize(colors=256, method=2)
                        opts = {"optimize": True}
                        icc = _icc_for_mode(src_icc, img.mode)
                        if icc:
                            opts["icc_profile"] = icc
                        _save_atomic(palet, dst, "PNG", **opts)
                        return True, dst
                    if img.mode in ("RGBA", "P", "LA"):
                        img = img.convert("RGB")
                    dst = str(Path(dst).with_suffix(".jpg"))
                    opts = {"quality": quality, "optimize": True, "progressive": True}
                    icc = _icc_for_mode(src_icc, img.mode)
                    if icc:
                        opts["icc_profile"] = icc
                    _save_atomic(img, dst, "JPEG", **opts)
                    return True, dst

                # Diğer genel formatlar (BMP vb.) -> JPEG
                if img.mode != "RGB":
                    img = img.convert("RGB")
                dst = str(Path(dst).with_suffix(".jpg"))
                opts = {"quality": quality, "optimize": True}
                icc = _icc_for_mode(src_icc, img.mode)
                if icc:
                    opts["icc_profile"] = icc
                _save_atomic(img, dst, "JPEG", **opts)
                return True, dst
        except Exception as exc:
            return False, f"Hata: {os.path.basename(src)} — {exc}"
