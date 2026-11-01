"""Baslik cubugundaki acilir menuler ve dugmeler temayi izlemeli (acik temada da).

Gercek cizim kontrol edilir: menu paneli temanin rengiyle dolu olmali (eskiden seffaf kaliyordu),
kapat dugmesi hover'da tehlike rengini almali.
"""

from __future__ import annotations

import os
import pathlib
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtGui import QColor, QPainter, QPixmap
from PyQt6.QtWidgets import QApplication, QStyle, QStyleOptionButton

from src.gui.title_bar import TitleBar
from src.utils.theme_manager import ThemeManager


def _hex(c: QColor) -> str:
    return c.name().lower()


def _dominant(img) -> str:
    """Most common colour of a painted button (ignores the magenta backdrop and the glyph)."""
    from collections import Counter

    counts = Counter(_hex(img.pixelColor(x, y)) for x in range(img.width()) for y in range(img.height()))
    counts.pop("#ff00ff", None)
    return counts.most_common(1)[0][0]


class TitleBarThemeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.tm = ThemeManager(cls.app)

    def _bar(self, setting: str) -> TitleBar:
        self.tm.apply_from_setting(setting)
        bar = TitleBar()
        bar.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        bar.resize(900, 40)
        bar.show()
        self.app.processEvents()
        return bar

    def _paint_button(self, btn, hover: bool) -> QPixmap:
        opt = QStyleOptionButton()
        btn.initStyleOption(opt)
        if hover:
            opt.state |= QStyle.StateFlag.State_MouseOver
        pm = QPixmap(btn.size())
        pm.fill(QColor(255, 0, 255))
        p = QPainter(pm)
        btn.style().drawControl(QStyle.ControlElement.CE_PushButton, opt, p, btn)
        p.end()
        return pm

    def test_dropdown_menus_are_painted_with_the_theme(self):
        for setting in ("light", "dark"):
            bar = self._bar(setting)
            raised = self.tm.get_palette()["raised"].lower()
            for btn in (bar.lang_btn, bar.theme_btn, bar.color_btn):
                menu = btn.menu()
                menu.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
                menu.popup(QPoint(50, 50))
                self.app.processEvents()
                pm = QPixmap(menu.size())
                pm.fill(QColor(255, 0, 255))
                menu.render(pm)
                menu.hide()
                img = pm.toImage()
                # a spot inside the panel, in the padding below the last item
                self.assertEqual(_hex(img.pixelColor(img.width() // 2, img.height() - 3)), raised, (setting, btn.text()))
            bar.close()

    def test_close_button_hover_uses_the_danger_color(self):
        for setting in ("light", "dark"):
            bar = self._bar(setting)
            danger = self.tm.get_palette()["danger"].lower()
            img = self._paint_button(bar.close_btn, hover=True).toImage()
            self.assertEqual(_dominant(img), danger, setting)
            idle = self._paint_button(bar.close_btn, hover=False).toImage()
            self.assertNotEqual(_dominant(idle), danger, setting)
            bar.close()

    def test_other_title_buttons_get_a_themed_hover(self):
        for setting in ("light", "dark"):
            bar = self._bar(setting)
            surface = self.tm.get_palette()["surface"].lower()
            for btn in (bar.min_btn, bar.lang_btn, bar.settings_btn):
                img = self._paint_button(btn, hover=True).toImage()
                self.assertEqual(_dominant(img), surface, (setting, btn.text()))
            bar.close()

    def test_title_bar_sheets_are_scoped(self):
        """A selector-less widget sheet cascades into the drop-down menus and the buttons."""
        self.tm.apply_from_setting("light")
        bar = TitleBar()
        for box in (bar.left_box, bar.menu_container, bar.right_box):
            sheet = box.styleSheet().strip()
            self.assertTrue(sheet.startswith("QWidget#"), sheet)
            self.assertTrue(box.objectName(), sheet)
            self.assertIn("#" + box.objectName(), sheet)


if __name__ == "__main__":
    unittest.main()
