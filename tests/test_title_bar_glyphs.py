"""Başlık çubuğu: büyüt/geri yükle glifi pencere durumunu izler, küçük ↑ güncelleme düğmesi, diyalog glifi."""

from __future__ import annotations

import os
import unittest
from copy import deepcopy
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from _support import ROOT  # noqa: E402,F401

from PyQt6.QtCore import QEvent, QEventLoop, QRectF, Qt, QTimer  # noqa: E402
from PyQt6.QtGui import QColor, QImage, QPainter  # noqa: E402
from PyQt6.QtWidgets import QApplication, QWidget  # noqa: E402

from src.gui import icons, message_box  # noqa: E402
from src.gui.chrome_dialog import ChromeDialog  # noqa: E402
from src.gui.main_window import MainWindow  # noqa: E402
from src.gui.title_bar import TitleBar  # noqa: E402
from src.utils import locales  # noqa: E402
from src.utils.config import DEFAULTS, Config  # noqa: E402
from src.utils.theme_manager import ThemeManager  # noqa: E402


def _settle(ms: int = 30) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def _config() -> Config:
    cfg = object.__new__(Config)
    cfg.path, cfg._seed_path, cfg.data = "", None, deepcopy(DEFAULTS)
    cfg.save = lambda *a, **k: None
    cfg.data["show_notifications"] = False
    return cfg


def _glyph_image(kind: str, size: int = 64) -> QImage:
    """Glif 32'lik ızgaradan 2x (64 px) çizilir: piksel = 2 × ızgara birimi."""
    image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    icons.paint_window_glyph(painter, QRectF(0, 0, size, size), kind, "#ffffff")
    painter.end()
    return image


def _ink(image: QImage, x: int, y: int) -> int:
    return image.pixelColor(x, y).alpha()


class _Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def tearDown(self) -> None:
        message_box.reset_configuration()
        locales.set_ui_language(None)


class GlyphDrawingTests(_Base):
    def test_maximize_is_one_rounded_square(self) -> None:
        img = _glyph_image("maximize")
        self.assertGreater(_ink(img, 17, 32), 150, "sol kenar (8.5 birim)")
        self.assertGreater(_ink(img, 47, 32), 150, "sağ kenar (23.5 birim)")
        self.assertGreater(_ink(img, 32, 17), 150, "üst kenar")
        self.assertEqual(_ink(img, 32, 32), 0, "içi boş (fırça yok)")

    def test_restore_back_square_does_not_show_through_the_front(self) -> None:
        img = _glyph_image("restore")
        # Ön kare x 8..20.5, y 11.5..24; arka kare x 11.5..24, y 7.5..20 (birim; piksel = 2 ×)
        self.assertGreater(_ink(img, 16, 36), 150, "ön karenin sol kenarı")
        self.assertGreater(_ink(img, 36, 15), 150, "arka karenin görünen üst kenarı")
        self.assertGreater(_ink(img, 48, 20), 150, "arka karenin görünen sağ kenarı")
        self.assertEqual(_ink(img, 23, 36), 0, "arka karenin sol kenarı ön karenin içinde çizilmez")
        self.assertEqual(_ink(img, 34, 40), 0, "arka karenin alt kenarı ön karenin içinde çizilmez")

    def test_update_arrow_points_up(self) -> None:
        img = _glyph_image("update")
        self.assertGreater(_ink(img, 32, 40), 150, "gövde")
        self.assertGreater(_ink(img, 26, 24), 100, "sol kanat")
        self.assertGreater(_ink(img, 38, 24), 100, "sağ kanat")
        self.assertEqual(_ink(img, 32, 54), 0, "gövde 24 birimde biter")


class MaximizeButtonTests(_Base):
    def _bar_in_window(self):
        host = QWidget()
        bar = TitleBar(host)
        self.addCleanup(host.deleteLater)
        host.resize(900, 300)
        host.show()
        _settle()
        return host, bar

    def test_glyph_follows_every_window_state_change(self) -> None:
        host, bar = self._bar_in_window()
        self.assertEqual(bar.max_btn.glyph, "maximize")
        # Durum, başlığın kendi düğmesinden geçmeden değişir (Win+Yukarı, Aero Snap, programdan showMaximized())
        host.setWindowState(Qt.WindowState.WindowMaximized)
        _settle()
        self.assertEqual(bar.max_btn.glyph, "restore")
        host.setWindowState(Qt.WindowState.WindowNoState)
        _settle()
        self.assertEqual(bar.max_btn.glyph, "maximize")
        host.showMaximized()
        _settle()
        self.assertEqual(bar.max_btn.glyph, "restore")

    def test_tooltip_follows_state_and_language(self) -> None:
        host, bar = self._bar_in_window()
        bar.retranslate("tr")
        self.assertEqual(bar.max_btn.toolTip(), "Ekranı Kapla")
        host.showMaximized()
        _settle()
        self.assertEqual(bar.max_btn.toolTip(), "Geri Yükle")
        bar.retranslate("en")
        self.assertEqual(bar.max_btn.toolTip(), "Restore Down", "dil değişince durum korunur")
        host.showNormal()
        _settle()
        self.assertEqual(bar.max_btn.toolTip(), "Maximize")
        self.assertEqual(bar.max_btn.accessibleName(), "Maximize")

    def test_glyph_ink_is_the_text_colour_and_the_arrow_uses_the_accent(self) -> None:
        bar = TitleBar()
        self.addCleanup(bar.deleteLater)
        bar.apply_palette({"text": "#e8e8e8", "accent_text": "#00acc1", "danger": "#ef4444"})
        self.assertEqual(bar.max_btn.ink(), QColor("#e8e8e8"))
        self.assertEqual(bar.update_btn.ink(), QColor("#00acc1"))
        bar.apply_palette({"text": "#1a1a1a", "accent_text": "#00838f", "danger": "#d32f2f"})
        self.assertEqual(bar.max_btn.ink(), QColor("#1a1a1a"))
        self.assertEqual(bar.update_btn.ink(), QColor("#00838f"))

    def test_main_window_glyph_changes_without_the_toggle_function(self) -> None:
        theme = ThemeManager(self.app)
        theme.apply_from_setting("dark")
        with mock.patch.object(MainWindow, "_prepare_ffmpeg", lambda *a, **k: None):
            win = MainWindow(_config(), theme, mock.MagicMock(), mock.MagicMock())
        win._quitting = True
        self.addCleanup(win.close)
        win.show()
        _settle()
        bar = win.title_bar
        self.assertEqual(bar.max_btn.glyph, "maximize")
        with mock.patch.object(win, "_toggle_max", side_effect=AssertionError("kendi işlevimiz çağrılmamalı")):
            win.setWindowState(Qt.WindowState.WindowMaximized)  # ör. Win+Yukarı / Aero Snap
            _settle()
            self.assertEqual(bar.max_btn.glyph, "restore")
            win.showNormal()  # ör. görev çubuğundan geri yükleme
            _settle()
        self.assertEqual(bar.max_btn.glyph, "maximize")
        self.assertEqual(bar.max_btn.toolTip(), locales.t("maximize", win.lang))


class UpdateArrowTests(_Base):
    def _bar(self) -> TitleBar:
        bar = TitleBar()
        bar.retranslate("tr")
        self.addCleanup(bar.deleteLater)
        bar.resize(1000, 38)
        bar.show()
        _settle()
        return bar

    def test_hidden_until_an_update_is_pending(self) -> None:
        bar = self._bar()
        self.assertFalse(bar.update_btn.isVisible())
        bar.set_update_available("1.2.3")
        _settle()
        self.assertTrue(bar.update_btn.isVisible())
        bar.set_update_available("")
        _settle()
        self.assertFalse(bar.update_btn.isVisible())

    def test_sits_left_of_minimize_with_the_window_button_size_and_no_text(self) -> None:
        bar = self._bar()
        bar.set_update_available("1.2.3")
        _settle()
        lay = bar.right_box.layout()
        self.assertEqual(lay.indexOf(bar.update_btn) + 1, lay.indexOf(bar.min_btn))
        self.assertLess(lay.indexOf(bar.min_btn), lay.indexOf(bar.max_btn))
        self.assertLess(lay.indexOf(bar.max_btn), lay.indexOf(bar.close_btn))
        self.assertLessEqual(bar.update_btn.geometry().right(), bar.min_btn.geometry().left())
        self.assertEqual(bar.update_btn.size(), bar.min_btn.size())
        self.assertEqual(bar.update_btn.size(), bar.max_btn.size())
        self.assertEqual(bar.update_btn.geometry().center().y(), bar.min_btn.geometry().center().y())
        self.assertEqual(bar.update_btn.text(), "")
        self.assertTrue(bar.update_btn.icon().isNull(), "glif paintEvent'te çizilir")
        self.assertGreaterEqual(bar.right_box.width(), bar.right_box.sizeHint().width(), "↑ kırpılmaz")

    def test_tooltip_and_accessible_name_in_both_languages(self) -> None:
        bar = self._bar()
        bar.set_update_available("1.2.3")
        self.assertEqual(bar.update_btn.toolTip(), "Yeni sürüm v1.2.3 hazır; ayrıntılar ve kurulum için tıklayın")
        self.assertEqual(bar.update_btn.accessibleName(), "Güncelle")
        bar.retranslate("en")
        self.assertEqual(bar.update_btn.toolTip(), "Version v1.2.3 is ready; click for details and installation")
        self.assertEqual(bar.update_btn.accessibleName(), "Update")

    def test_click_emits_update_clicked(self) -> None:
        bar = self._bar()
        bar.set_update_available("1.2.3")
        seen = []
        bar.update_clicked.connect(lambda: seen.append("update"))
        bar.update_btn.click()
        self.assertEqual(seen, ["update"])

    def test_retry_text_points_at_the_title_bar_arrow(self) -> None:
        self.assertIn("başlıktaki ↑", locales.t("update_auto_failed", "tr"))
        self.assertIn("↑ icon in the title bar", locales.t("update_auto_failed", "en"))


class ChromeDialogGlyphTests(_Base):
    def test_dialog_max_button_draws_the_vector_glyphs(self) -> None:
        dlg = ChromeDialog(None, resizable=True)
        self.addCleanup(dlg.deleteLater)
        dlg.resize(400, 300)
        dlg.show()
        _settle()
        btn = dlg._cd_max
        self.assertEqual(btn.glyph, "maximize")
        drawn = []
        real = icons.paint_centered_window_glyph

        def spy(painter, rect, kind, color, *args, **kwargs):
            drawn.append(kind)
            return real(painter, rect, kind, color, *args, **kwargs)

        with mock.patch.object(icons, "paint_centered_window_glyph", side_effect=spy):
            btn.grab()
            dlg.showMaximized()  # durum değişimi changeEvent'ten gelir (düğmeden geçmeden)
            _settle()
            self.assertEqual(btn.glyph, "restore")
            btn.grab()
        self.assertEqual(list(dict.fromkeys(drawn)), ["maximize", "restore"])  # ekran yenilemeleri tekrarlayabilir
        import inspect

        from src.gui import chrome_dialog

        source = inspect.getsource(chrome_dialog._MaxButton)
        self.assertNotIn("drawText", source, "metin glifi (□/❐) yerine vektör çizim")
        dlg.toggle_maximized()
        _settle()
        self.assertEqual(btn.glyph, "maximize")

    def test_dialog_max_button_tooltip_follows_state(self) -> None:
        message_box.configure(lang_provider=lambda: "en")
        dlg = ChromeDialog(None, resizable=True)
        self.addCleanup(dlg.deleteLater)
        btn = dlg._cd_max
        self.assertEqual(btn.toolTip(), "Maximize")
        btn.set_maximized(True)
        self.assertEqual(btn.toolTip(), "Restore Down")

    def test_glyph_event_type_is_window_state_change(self) -> None:
        # changeEvent yolunun kendisi: elle gönderilen WindowStateChange da glifi yeniler
        dlg = ChromeDialog(None, resizable=True)
        self.addCleanup(dlg.deleteLater)
        with mock.patch.object(dlg, "isMaximized", return_value=True):
            QApplication.sendEvent(dlg, QEvent(QEvent.Type.WindowStateChange))
        self.assertEqual(dlg._cd_max.glyph, "restore")


if __name__ == "__main__":
    unittest.main()
