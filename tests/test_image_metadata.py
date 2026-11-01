"""Madde 5b: ICC profili ve EXIF korunur (HEIC dahil); bozuk dosya basarili sayilmaz."""

from __future__ import annotations

import io
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))
from _support import TempDirTestCase  # noqa: E402

import piexif  # noqa: E402
from PIL import Image, ImageCms, ImageFile, features  # noqa: E402

from src.core import image_compressor  # noqa: E402
from src.core.image_compressor import ImageCompressor, _icc_for_mode, _prepare_exif  # noqa: E402

try:
    import pillow_heif  # noqa: F401
    HAS_HEIF = True
except ImportError:
    HAS_HEIF = False


def srgb_profile() -> bytes:
    return ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()


def exif_bytes(orientation: int | None = None, make: str = "TestMake") -> bytes:
    exif = Image.Exif()
    exif[0x010F] = make
    exif[0x0110] = "TestModel"
    if orientation is not None:
        exif[0x0112] = orientation
    return exif.tobytes()


def noise(size=(64, 48), mode="RGB"):
    return Image.frombytes(mode, size, os.urandom(size[0] * size[1] * len(mode)))


class MetadataPreservationTests(TempDirTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.icc = srgb_profile()
        self.out = self.tmp / "out"
        self.out.mkdir()

    def _compress(self, src: str, name: str):
        ok, result = ImageCompressor.compress(src, str(self.out / name))
        self.assertTrue(ok, result)
        return result

    def _make_exif_dict(self, path: str) -> dict:
        return piexif.load(path)

    def test_jpeg_keeps_icc_and_exif_and_fixes_orientation(self) -> None:
        src = str(self.tmp / "a.jpg")
        noise((64, 48)).save(src, "JPEG", exif=exif_bytes(orientation=6), icc_profile=self.icc)
        result = self._compress(src, "a.jpg")
        with Image.open(result) as out:
            self.assertEqual(out.info.get("icc_profile"), self.icc)
            self.assertEqual(out.size, (48, 64))  # Orientation 6 uygulandi
        exif = self._make_exif_dict(result)
        self.assertEqual(exif["0th"][piexif.ImageIFD.Make], b"TestMake")
        self.assertNotEqual(exif["0th"].get(piexif.ImageIFD.Orientation, 1), 6)  # cift dondurme yok

    @unittest.skipUnless(HAS_HEIF, "pillow_heif yok")
    def test_heic_to_jpeg_keeps_exif_and_icc(self) -> None:
        src = str(self.tmp / "foto.heic")
        noise((64, 48)).save(src, "HEIF", exif=exif_bytes(orientation=1, make="HeicMake"), icc_profile=self.icc)
        # Eski kod: piexif.load(HEIC) InvalidImageDataError verip EXIF'i sessizce kaybediyordu.
        with self.assertRaises(Exception):
            piexif.load(src)
        result = self._compress(src, "foto.heic")
        self.assertTrue(result.endswith(".jpg"))
        with Image.open(result) as out:
            self.assertEqual(out.format, "JPEG")
            self.assertEqual(out.info.get("icc_profile"), self.icc)
        self.assertEqual(self._make_exif_dict(result)["0th"][piexif.ImageIFD.Make], b"HeicMake")

    def test_webp_keeps_icc(self) -> None:
        src = str(self.tmp / "a.webp")
        noise().save(src, "WEBP", icc_profile=self.icc)
        result = self._compress(src, "a.webp")
        with Image.open(result) as out:
            self.assertEqual(out.info.get("icc_profile"), self.icc)

    def test_png_with_transparency_keeps_icc(self) -> None:
        src = str(self.tmp / "a.png")
        img = noise((40, 40), "RGBA")
        img.putalpha(Image.new("L", (40, 40), 100))
        img.save(src, "PNG", icc_profile=self.icc)
        result = self._compress(src, "a.png")
        self.assertTrue(result.endswith(".png"))
        with Image.open(result) as out:
            self.assertEqual(out.info.get("icc_profile"), self.icc)

    def test_grayscale_png_with_alpha_is_compressed(self) -> None:
        # LA (gri + saydamlik) quantize'a dogrudan verilince "image has wrong mode" ile basarisiz oluyordu.
        src = str(self.tmp / "gri.png")
        img = Image.new("LA", (40, 40), (128, 255))
        img.putalpha(Image.linear_gradient("L").resize((40, 40)))
        img.save(src, "PNG")
        result = self._compress(src, "gri.png")
        self.assertTrue(result.endswith(".png"))
        with Image.open(result) as out:
            self.assertEqual(out.size, (40, 40))
            self.assertEqual(out.mode, "P")
            alpha = out.convert("RGBA").getchannel("A").getextrema()
        self.assertLess(alpha[0], 255, "saydamlik korunur")

    def test_opaque_png_converted_to_jpeg_keeps_icc(self) -> None:
        src = str(self.tmp / "b.png")
        noise((40, 40), "RGB").save(src, "PNG", icc_profile=self.icc)
        result = self._compress(src, "b.png")
        self.assertTrue(result.endswith(".jpg"))
        with Image.open(result) as out:
            self.assertEqual(out.info.get("icc_profile"), self.icc)

    @unittest.skipUnless(features.check("avif") or image_compressor.__dict__.get("pillow_avif"), "AVIF yok")
    def test_avif_does_not_fail_with_icc(self) -> None:
        src = str(self.tmp / "a.avif")
        try:
            noise().save(src, "AVIF", icc_profile=self.icc)
        except Exception as exc:  # noqa: BLE001
            self.skipTest(f"AVIF yazilamiyor: {exc}")
        result = self._compress(src, "a.avif")
        self.assertTrue(os.path.getsize(result) > 0)

    def test_mismatched_profile_is_dropped_when_mode_changes(self) -> None:
        # Gri profil + paletli PNG -> JPEG(RGB): gri profil RGB goruntuye eklenirse renkler bozulur.
        fake_gray_icc = bytearray(128)
        fake_gray_icc[16:20] = b"GRAY"
        src = str(self.tmp / "c.png")
        noise((32, 32), "RGB").convert("P").save(src, "PNG", icc_profile=bytes(fake_gray_icc))
        result = self._compress(src, "c.png")
        self.assertTrue(result.endswith(".jpg"))
        with Image.open(result) as out:
            self.assertEqual(out.mode, "RGB")
            self.assertNotIn("icc_profile", out.info)

    def test_palette_png_with_rgb_profile_keeps_profile_after_rgb_conversion(self) -> None:
        src = str(self.tmp / "d.png")
        noise((32, 32), "RGB").convert("P").save(src, "PNG", icc_profile=self.icc)
        result = self._compress(src, "d.png")
        with Image.open(result) as out:
            self.assertEqual(out.info.get("icc_profile"), self.icc)


class HelperTests(unittest.TestCase):
    def test_icc_for_mode_matches_colour_space(self) -> None:
        rgb = bytes(16) + b"RGB " + bytes(108)
        gray = bytes(16) + b"GRAY" + bytes(108)
        cmyk = bytes(16) + b"CMYK" + bytes(108)
        self.assertEqual(_icc_for_mode(rgb, "RGB"), rgb)
        self.assertEqual(_icc_for_mode(rgb, "P"), rgb)
        self.assertIsNone(_icc_for_mode(rgb, "L"))
        self.assertEqual(_icc_for_mode(gray, "L"), gray)
        self.assertIsNone(_icc_for_mode(gray, "RGB"))
        self.assertEqual(_icc_for_mode(cmyk, "CMYK"), cmyk)
        self.assertIsNone(_icc_for_mode(cmyk, "RGB"))
        self.assertIsNone(_icc_for_mode(None, "RGB"))
        self.assertIsNone(_icc_for_mode(b"kisa", "RGB"))

    def test_prepare_exif_resets_orientation(self) -> None:
        prepared = _prepare_exif(exif_bytes(orientation=6))
        self.assertEqual(piexif.load(prepared)["0th"][piexif.ImageIFD.Orientation], 1)
        self.assertEqual(piexif.load(prepared)["0th"][piexif.ImageIFD.Make], b"TestMake")

    def test_prepare_exif_drops_thumbnail_when_too_big(self) -> None:
        buf = io.BytesIO()
        noise((220, 220)).save(buf, "JPEG", quality=95)
        thumb = buf.getvalue()
        self.assertTrue(50000 < len(thumb) < 64000, len(thumb))  # piexif kucuk resmi 64 kB ile sinirlar
        data = piexif.dump({
            "0th": {piexif.ImageIFD.Make: b"BigMake"},
            "Exif": {piexif.ExifIFD.MakerNote: b"m" * 9000},
            "1st": {},
            "thumbnail": thumb,
        })
        self.assertGreater(len(data), 65533)  # Pillow bu haliyle "EXIF data is too long" verirdi
        prepared = _prepare_exif(data)
        self.assertIsNotNone(prepared)
        self.assertLessEqual(len(prepared), 65000)
        self.assertEqual(piexif.load(prepared)["0th"][piexif.ImageIFD.Make], b"BigMake")

    def test_prepare_exif_discards_unfixable_oversize_and_garbage(self) -> None:
        huge = piexif.dump({"Exif": {piexif.ExifIFD.UserComment: b"ASCII\x00\x00\x00" + b"x" * 66000}})
        self.assertIsNone(_prepare_exif(huge))
        self.assertIsNone(_prepare_exif(None))
        self.assertIsNone(_prepare_exif(b""))


class TruncatedFileTests(TempDirTestCase):
    def test_truncated_jpeg_is_reported_as_failure_and_leaves_nothing(self) -> None:
        src = self.tmp / "kesik.jpg"
        noise((200, 200)).save(src, "JPEG", quality=95)
        data = src.read_bytes()
        src.write_bytes(data[: int(len(data) * 0.6)])
        out = self.tmp / "out"
        out.mkdir()
        ok, message = ImageCompressor.compress(str(src), str(out / "kesik.jpg"))
        self.assertFalse(ok, "kesik dosya basarili gosterildi")
        self.assertIn("kesik.jpg", message)
        self.assertEqual(self.listing(out), [])

    def test_truncated_flag_is_off_even_with_gui_modules_imported(self) -> None:
        from src.gui import preview_dialog  # noqa: F401  (eskiden bayragi True yapiyordu)

        self.assertFalse(ImageFile.LOAD_TRUNCATED_IMAGES)


if __name__ == "__main__":
    unittest.main()
