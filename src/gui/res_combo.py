"""Çözünürlük açılır listelerindeki "Orijinal" seçeneği.

Kayıtlı/aktarılan DEĞER hep ``ORIGINAL`` ("Orijinal") kalır (profiller, önizleme penceresi, ayarlar);
ekranda görünen YAZI ise uygulama dilindedir ("Original"). Değer, öğenin ``UserRole`` verisinde saklanır.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QComboBox

ORIGINAL = "Orijinal"
_ROLE = Qt.ItemDataRole.UserRole


def mark_original(combo: QComboBox, display_text: str) -> None:
    """Listedeki "Orijinal" öğesini bulup yazısını dile göre değiştirir ve değerini verisine yazar."""
    idx = combo.findData(ORIGINAL, _ROLE)
    if idx < 0:
        idx = combo.findText(ORIGINAL)
    if idx >= 0:
        combo.setItemText(idx, display_text)
        combo.setItemData(idx, ORIGINAL, _ROLE)


def res_value(combo: QComboBox, index: int | None = None) -> str:
    """Seçili (ya da verilen) öğenin değeri: "Orijinal" ya da "1080p" / "2400px" gibi görünen yazı."""
    if index is None:
        index = combo.currentIndex()
    if index < 0:
        return combo.currentText()
    if combo.itemData(index, _ROLE) == ORIGINAL:
        return ORIGINAL
    return combo.itemText(index)


def find_res(combo: QComboBox, value: str) -> int:
    """Değere karşılık gelen öğenin sırası (yoksa -1)."""
    if value == ORIGINAL:
        return combo.findData(ORIGINAL, _ROLE)
    return combo.findText(value)


def select_res(combo: QComboBox, value: str) -> bool:
    """Değeri seçer; listede yoksa hiçbir şeyi değiştirmez ve False döner."""
    idx = find_res(combo, value)
    if idx < 0:
        return False
    combo.setCurrentIndex(idx)
    return True
