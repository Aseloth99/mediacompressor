"""Çıkış klasörü etiketi: kısaltılmış yol kutuya pay bırakarak sığar (son harf yarım görünmesin), tema / yazı tipi
değişince yeniden kısaltılır."""

from __future__ import annotations

import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from PyQt6.QtGui import QFont  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from src.gui.path_label import ELIDE_SLACK, ElidedPathLabel  # noqa: E402

_APP = None
LONG = r"C:\Users\usr\Desktop\Projelerim\MediaCompressor\çok uzun bir klasör adı\sıkıştırılmış"


class PathLabelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        global _APP
        _APP = QApplication.instance() or QApplication([])

    def _fits(self, label: ElidedPathLabel) -> bool:
        return label.fontMetrics().horizontalAdvance(label.text()) <= label.contentsRect().width() - ELIDE_SLACK

    def test_elided_text_leaves_room_for_the_last_glyph(self):
        label = ElidedPathLabel(LONG)
        self.addCleanup(label.deleteLater)
        label.resize(220, 30)
        label.show()  # gizli pencereye yeniden boyut olayı gösterilene kadar gelmez
        QApplication.processEvents()
        self.assertNotEqual(label.text(), LONG)
        self.assertIn("…", label.text())
        self.assertTrue(self._fits(label), label.text())
        self.assertEqual(label.toolTip(), LONG, "tam yol ipucunda")

    def test_font_change_re_elides(self):
        label = ElidedPathLabel(LONG)
        self.addCleanup(label.deleteLater)
        label.resize(260, 30)
        label.show()
        QApplication.processEvents()
        small = label.text()
        bigger = QFont(label.font())
        bigger.setPointSizeF(bigger.pointSizeF() * 1.6)
        label.setFont(bigger)
        self.assertTrue(self._fits(label), "büyüyen yazı tipiyle eski kısaltma taşardı")
        self.assertNotEqual(label.text(), small)


if __name__ == "__main__":
    unittest.main()
