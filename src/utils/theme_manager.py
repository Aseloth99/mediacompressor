"""Neumorphic tema — TransferTCP mavi paleti."""

from __future__ import annotations

import gc
import os
import tempfile
from contextlib import contextmanager

from PyQt6.QtCore import QObject, QPointF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QImage, QPainter, QPen, QPolygonF
from PyQt6.QtWidgets import QApplication, QStyleFactory

# TransferTCP: koyu grafit + Material Blue #2196F3
DARK = {
    "base": "#1a1a1a",
    "raised": "#2a2a2a",
    "sunken": "#1f1f1f",
    "surface": "#252525",
    "border": "#1a1a1a",
    "hi": "#3a3a3a",
    "hi2": "#353535",
    "lo": "#0f0f0f",
    "border_focus": "#2196F3",
    "text": "#e8e8e8",
    "text_muted": "#9e9e9e",
    "accent": "#2196F3",
    "accent2": "#1976D2",
    "accent_hi": "#42A5F5",
    "danger": "#d32f2f",
    "danger_hi": "#f44336",
    "success": "#2196F3",
    "warn": "#FFC107",
    "selected_text": "#ffffff",
    # Onay kutusu (FlexiKey surface2 / border_strong / surface / border ile aynı değerler; üç uygulamada aynı kutu)
    "chk_fill": "#262626",
    "chk_border": "#454545",
    "chk_hover": "#1e1e1e",
    "chk_dis_border": "#2e2e2e",
}

# TransferTCP açık: #e0e0e0 zemin, beyaz highlight, mavi vurgu
LIGHT = {
    "base": "#e0e0e0",
    "raised": "#f5f5f5",
    "sunken": "#d8d8d8",
    "surface": "#ececec",
    "border": "#c5c5c5",
    "hi": "#ffffff",
    "hi2": "#fafafa",
    "lo": "#bdbdbd",
    "border_focus": "#2196F3",
    "text": "#1a1a1a",
    "text_muted": "#616161",
    "accent": "#2196F3",
    "accent2": "#1976D2",
    "accent_hi": "#90CAF9",
    "danger": "#e53935",
    "danger_hi": "#ff5252",
    "success": "#2196F3",
    "warn": "#8A5300",  # amber text on the light greys: #F9A825 was only 1.5:1
    "selected_text": "#ffffff",
    # Onay kutusu (FlexiKey surface2 / border_strong / surface / border ile aynı değerler; üç uygulamada aynı kutu)
    "chk_fill": "#ececec",
    "chk_border": "#b0b0b0",
    "chk_hover": "#f5f5f5",
    "chk_dis_border": "#c5c5c5",
}

# Vurgu renkleri — varsayılan Material Blue #2196F3
ACCENTS = {
    "cyan": {
        "label_key": "accent_cyan",
        "accent": "#00ACC1",
        "accent2": "#00838F",
        "hi_dark": "#4DD0E1",
        "hi_light": "#80DEEA",
    },
    "blue": {
        "label_key": "accent_blue",
        "accent": "#2196F3",
        "accent2": "#1976D2",
        "hi_dark": "#42A5F5",
        "hi_light": "#90CAF9",
    },
    "teal": {
        "label_key": "accent_teal",
        "accent": "#00897B",
        "accent2": "#00695C",
        "hi_dark": "#4DB6AC",
        "hi_light": "#80CBC4",
    },
    "indigo": {
        "label_key": "accent_indigo",
        "accent": "#3F51B5",
        "accent2": "#303F9F",
        "hi_dark": "#7986CB",
        "hi_light": "#9FA8DA",
    },
    "violet": {
        "label_key": "accent_violet",
        "accent": "#7C4DFF",
        "accent2": "#651FFF",
        "hi_dark": "#B388FF",
        "hi_light": "#D1C4E9",
    },
    "rose": {
        "label_key": "accent_rose",
        "accent": "#E91E63",
        "accent2": "#C2185B",
        "hi_dark": "#F06292",
        "hi_light": "#F8BBD0",
    },
    "orange": {
        "label_key": "accent_orange",
        "accent": "#FB8C00",
        "accent2": "#EF6C00",
        "hi_dark": "#FFB74D",
        "hi_light": "#FFE0B2",
    },
    "red": {
        "label_key": "accent_red",
        "accent": "#E53935",
        "accent2": "#C62828",
        "hi_dark": "#EF5350",
        "hi_light": "#FFCDD2",
    },
    "green": {
        "label_key": "accent_green",
        "accent": "#43A047",
        "accent2": "#2E7D32",
        "hi_dark": "#66BB6A",
        "hi_light": "#C8E6C9",
    },
    "yellow": {
        "label_key": "accent_yellow",
        "accent": "#F9A825",
        "accent2": "#F57F17",
        "hi_dark": "#FDD835",
        "hi_light": "#FFF59D",
    },
}

DEFAULT_ACCENT = "cyan"
_ACTIVE_ACCENT = DEFAULT_ACCENT  # en son uygulanan vurgu: renkli menü simgelerinin "blue"/"sky" ailesi bunu izler


def active_accent() -> str:
    return _ACTIVE_ACCENT


def accent_label(key: str, lang: str | None = None) -> str:
    from .locales import t

    spec = ACCENTS.get(key) or ACCENTS[DEFAULT_ACCENT]
    return t(spec["label_key"], lang)


def _with_accent(base: dict, accent_key: str, dark: bool) -> dict:
    spec = ACCENTS.get(accent_key) or ACCENTS[DEFAULT_ACCENT]
    palette = dict(base)
    accent = spec["accent"]
    palette["accent"] = accent
    palette["accent2"] = spec["accent2"]
    palette["accent_hi"] = spec["hi_dark"] if dark else spec["hi_light"]
    # Opak karışım: 8 haneli yarı saydam hex (#AARRGGBB) Qt stil sayfasında yanlış karışıyor, seçili kuyruk
    # satırı turkuaz yerine hardal sarısı görünüyordu (#89905c).
    palette["accent_soft"] = _mix(accent, base["raised"], 0.24 if dark else 0.16)
    # accent used as TEXT: the bright accent is fine on dark, but only ~2:1 on the light greys, so use its deeper shade there
    palette["accent_text"] = accent if dark else spec["accent2"]
    # Durum renkleri (kuyruk tablosu): metin olarak okunabilir tonlar; koyuda parlak, açıkta derin.
    palette["ok_text"] = "#5fcf7f" if dark else "#1b6e36"
    palette["fail_text"] = "#ff7b72" if dark else "#b3261e"
    # Kaydırma çubuğu tutamacı nötr gri (vurgu yalnızca üzerine gelince): diğer uygulamalarla aynı; her
    # zaman görünen sol panel çubuğu vurgu renginde göze batıyordu.
    palette["scroll"] = _mix(base["text"], base["sunken"], 0.28)
    palette["border_focus"] = accent
    palette["success"] = accent
    # Toast (pencere içi kısa bildirim) temanın tersi renklerde: kuyruk satırlarının üstünde her iki temada da seçilir.
    toast_bg = "#ececec" if dark else "#2b2b2b"
    toast_text = "#1a1a1a" if dark else "#f2f2f2"
    palette["toast_bg"] = toast_bg
    palette["toast_text"] = toast_text
    palette["toast_muted"] = _mix(toast_text, toast_bg, 0.68)
    palette["toast_border"] = _mix(toast_text, toast_bg, 0.14)
    palette["toast_hover"] = _mix(toast_text, toast_bg, 0.10)
    palette["toast_accent"] = readable_on(accent, toast_bg)
    return palette


def _luminance(color: str) -> float:
    def lin(v: int) -> float:
        c = v / 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = _hex_rgb(color)
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def contrast_ratio(a: str, b: str) -> float:
    la, lb = _luminance(a), _luminance(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def readable_on(color: str, background: str, minimum: float = 4.5) -> str:
    """`color`'ı `background` üstünde en az `minimum` kontrastla okunana dek koyulaştırır/açar (tonu korunur)."""
    toward = "#000000" if _luminance(background) > 0.4 else "#ffffff"
    result = color
    for step in range(1, 21):
        if contrast_ratio(result, background) >= minimum:
            break
        result = _mix(toward, color, step / 20)
    return result


def _mix(color: str, base: str, amount: float) -> str:
    """`color`'ın `amount` oranında `base` üzerine karışımı (opak #RRGGBB)."""
    c, b = _hex_rgb(color), _hex_rgb(base)
    return "#" + "".join(f"{round(cv * amount + bv * (1 - amount)):02x}" for cv, bv in zip(c, b))


def _hex_rgb(color: str) -> tuple[int, int, int]:
    h = color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _chevron_url(color: str) -> str:
    """Gerçek ok görseli — CSS üçgen Windows'ta siyah kareye dönüşüyor."""
    dest = os.path.join(tempfile.gettempdir(), f"ms_chevron_{color.lstrip('#')}.png")
    try:
        from PIL import Image, ImageDraw
        img = Image.new("RGBA", (20, 20), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        r, g, b = _hex_rgb(color)
        draw.polygon([(4, 7), (16, 7), (10, 13)], fill=(r, g, b, 255))
        img.save(dest, "PNG")
    except Exception:
        pass
    return dest.replace("\\", "/")


_CHECK_SCALE = 4  # 16 px kutu 64 px çizilir; Qt kutuya küçültür (%150 ölçekte tik bulanık olmasın)


def _check_url(color: str) -> str:
    """Onay kutusu tiki: FlexiKey/TransferTCP ile aynı çizim — 16x16 içerik kutusunda (3,8)-(6,11)-(13,4),
    2.2 px yuvarlak uçlu kalem, 4x PNG. QImage ile çizilir (QGuiApplication gerekmez)."""
    s = _CHECK_SCALE
    dest = os.path.join(tempfile.gettempdir(), f"ms_check_{color.lstrip('#').lower()}_x{s}.png")
    if not os.path.exists(dest):
        img = QImage(16 * s, 16 * s, QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(Qt.GlobalColor.transparent)
        painter = QPainter(img)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor(color), 2.2 * s)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.drawPolyline(QPolygonF([QPointF(3 * s, 8 * s), QPointF(6 * s, 11 * s), QPointF(13 * s, 4 * s)]))
        painter.end()
        img.save(dest, "PNG")
    return dest.replace("\\", "/")


def _nav_colors(p: dict) -> tuple[str, str]:
    """Ayarlar kenar çubuğunda seçili sekme (Lumina ile aynı kural): kenar çubuğu zeminine %16 (koyu) / %13 (açık)
    vurgu karışmış hafif zemin ve onun üstünde en az 4,5:1 okunan vurgu yazısı."""
    dark = _luminance(p["base"]) < 0.4
    tint = _mix(p["accent"], p["surface"], 0.16 if dark else 0.13)
    ink = readable_on(p["accent_hi"] if dark else p["accent2"], tint, 4.5)
    return tint, ink


def _build(p: dict) -> str:
    chev = _chevron_url(p["text_muted"])
    tick = _check_url("#ffffff")
    tick_muted = _check_url(p["text_muted"])
    nav_tint, nav_ink = _nav_colors(p)
    return f"""
        * {{
            font-family: 'Segoe UI', 'SF Pro Text', 'Helvetica Neue', Arial, sans-serif;
            font-size: 10pt;
        }}
        QMainWindow {{
            background-color: {p['lo']};
            color: {p['text']};
        }}
        QDialog {{
            background-color: {p['base']};
            color: {p['text']};
        }}
        QWidget {{
            background-color: {p['base']};
            color: {p['text']};
        }}

        QMainWindow {{
            background-color: transparent;
        }}

        QFrame#app_chrome, QWidget#app_chrome {{
            background-color: {p['base']};
            border: 1px solid {p['border']};
            border-top: 2px solid {p['accent']};
            border-radius: 12px;
        }}

        QFrame#title_bar, QWidget#title_bar {{
            background-color: {p['raised']};
            border: none;
            border-top: none;
            border-bottom: 1px solid {p['border']};
            border-top-left-radius: 12px;
            border-top-right-radius: 12px;
        }}
        QFrame#title_bar QWidget, QWidget#title_bar QWidget {{
            background-color: transparent;
            border: none;
        }}
        /* the drop-down menus are children of the title-bar buttons, so the rule above would clear them too */
        QFrame#title_bar QMenu, QWidget#title_bar QMenu {{
            background-color: {p['raised']};
            border: 1px solid {p['border']};
            border-radius: 10px;
            padding: 6px;
        }}
        QLabel#title_label {{
            color: {p['text']};
            font-size: 9.5pt;
            font-weight: 600;
            background: transparent;
        }}
        QLabel#version_label {{
            color: {p['text_muted']};
            font-size: 8pt;
            background: transparent;
        }}

        QPushButton {{
            background-color: {p['raised']};
            color: {p['text']};
            border: 1px solid {p['border']};
            border-top-color: {p['hi']};
            border-left-color: {p['hi']};
            border-radius: 10px;
            padding: 0px 14px;
            font-weight: 600;
            font-size: 10pt;
            min-height: 34px;
        }}
        QPushButton:hover {{
            background-color: {p['surface']};
            border-top-color: {p['hi2']};
            border-left-color: {p['hi2']};
        }}
        QPushButton:pressed {{
            background-color: {p['sunken']};
            border-top-color: {p['lo']};
            border-left-color: {p['lo']};
            border-bottom-color: {p['hi']};
            border-right-color: {p['hi']};
        }}
        QPushButton:disabled {{
            color: {p['text_muted']};
            background-color: {p['base']};
        }}

        QPushButton[class="primary"] {{
            background-color: {p['accent2']};
            color: #ffffff;
            border: 1px solid {p['accent2']};
            border-top-color: {p['accent_hi']};
            border-left-color: {p['accent_hi']};
            font-weight: 600;
            padding: 0px 16px;
            min-height: 34px;
        }}
        QPushButton[class="primary"]:hover {{
            background-color: {p['accent']};
        }}
        QPushButton[class="primary"]:pressed {{
            background-color: {p['accent2']};
            border-top-color: {p['accent2']};
            border-left-color: {p['accent2']};
        }}

        QPushButton[class="danger"] {{
            background-color: {p['danger']};
            color: #ffffff;
            border: 1px solid {p['danger']};
            border-top-color: {p['danger_hi']};
            border-left-color: {p['danger_hi']};
            font-weight: 600;
        }}

        QPushButton[class="danger"]:hover {{
            background-color: {p['danger_hi']};
        }}
        QPushButton[class="danger"]:pressed {{
            background-color: #b71c1c;
        }}
        /* a class rule outranks the generic :disabled one, so a disabled coloured button must say so itself */
        QPushButton[class="primary"]:disabled, QPushButton[class="danger"]:disabled {{
            background-color: {p['base']};
            color: {p['text_muted']};
            border: 1px solid {p['border']};
        }}

        QPushButton[class="ghost"] {{
            background-color: {p['raised']};
            padding: 0px 14px;
        }}

        QPushButton[class="ghost-mini"] {{
            background-color: {p['raised']};
            padding: 0px 10px;
            font-size: 9pt;
            font-weight: 600;
            border-radius: 7px;
            min-height: 28px;
        }}
        QPushButton[class="ghost-mini"]:checked {{
            background-color: {p['accent_soft']};
            color: {p['accent_text']};
            border: 1px solid {p['accent']};
        }}
        QPushButton#panel_toggle {{
            padding: 0px;
        }}

        QPushButton[class="chip"] {{
            background-color: {p['raised']};
            border: 1px solid {p['border']};
            border-top-color: {p['hi']};
            border-left-color: {p['hi']};
            border-radius: 14px;
            padding: 0px 14px;
            font-weight: 600;
            min-height: 30px;
        }}
        QPushButton[class="chip"]:checked {{
            background-color: {p['accent2']};
            color: #ffffff;
            border: 1px solid {p['accent2']};
            border-top-color: {p['accent_hi']};
            border-left-color: {p['accent_hi']};
        }}

        QPushButton[class="segment"] {{
            border-radius: 8px;
            padding: 0px 12px;
            min-height: 30px;
        }}
        QPushButton[class="segment"]:checked {{
            background-color: {p['accent2']};
            color: #ffffff;
            border: 1px solid {p['accent2']};
            border-top-color: {p['accent_hi']};
            border-left-color: {p['accent_hi']};
        }}

        QPushButton[class="title-button"] {{
            background-color: {p['raised']};
            color: {p['text']};
            border: 1px solid {p['border']};
            border-top-color: {p['hi']};
            border-left-color: {p['hi']};
            border-radius: 6px;
            padding: 0px;
            margin: 0px;
            font-size: 13pt;
            font-weight: 300;
        }}
        QPushButton[class="title-button"]:hover {{
            background-color: {p['surface']};
        }}
        QPushButton[class="title-button"]:pressed {{
            background-color: {p['sunken']};
            border-top-color: {p['lo']};
            border-left-color: {p['lo']};
        }}
        QFrame#title_bar QPushButton[class="title-button"],
        QFrame#title_bar QPushButton[class="title-button-close"] {{
            padding: 0px;
            margin: 0px;
            min-width: 26px;
            max-width: 26px;
            min-height: 22px;
            max-height: 22px;
        }}

        QPushButton[class="title-button-close"] {{
            background-color: {p['raised']};
            color: {p['text']};
            border: 1px solid {p['border']};
            border-top-color: {p['hi']};
            border-left-color: {p['hi']};
            border-radius: 6px;
            padding: 0px;
            margin: 0px;
            font-size: 16pt;
            font-weight: 300;
        }}
        QPushButton[class="title-button-close"]:hover {{
            background-color: {p['danger']};
            color: #ffffff;
            border-color: {p['danger']};
            border-top-color: {p['danger_hi']};
            border-left-color: {p['danger_hi']};
        }}
        QPushButton[class="title-button-close"]:pressed {{
            background-color: #b71c1c;
            color: #ffffff;
        }}

        /* title-bar buttons are flat; hover still comes from the theme (a widget-level sheet used to wipe it) */
        QFrame#title_bar QPushButton[class="title-button"],
        QFrame#title_bar QPushButton[class="title-button-close"],
        QFrame#title_bar QPushButton[class="menu-button"] {{
            background-color: transparent;
            border: none;
        }}
        QFrame#title_bar QPushButton[class="title-button"]:hover,
        QFrame#title_bar QPushButton[class="menu-button"]:hover {{
            background-color: {p['surface']};
        }}
        QFrame#title_bar QPushButton[class="title-button"]:pressed {{
            background-color: {p['sunken']};
        }}
        QFrame#title_bar QPushButton[class="title-button-close"]:hover {{
            background-color: {p['danger']};
            color: #ffffff;
        }}
        QFrame#title_bar QPushButton[class="title-button-close"]:pressed {{
            background-color: #b71c1c;
            color: #ffffff;
        }}

        QPushButton[class="menu-button"] {{
            background-color: {p['raised']};
            color: {p['text']};
            border: 1px solid {p['border']};
            border-top-color: {p['hi']};
            border-left-color: {p['hi']};
            border-radius: 6px;
            padding: 0px 22px 0px 10px;
            font-size: 9pt;
            font-weight: 600;
            min-height: 24px;
            max-height: 24px;
        }}
        QPushButton[class="menu-button"]:hover {{
            background-color: {p['surface']};
        }}
        QPushButton[class="menu-button"]::menu-indicator {{
            subcontrol-origin: padding;
            subcontrol-position: right center;
            right: 7px;
            width: 8px;
        }}

        QLineEdit {{
            background-color: {p['raised']};
            color: {p['text']};
            border: 1px solid {p['border']};
            border-top-color: {p['hi']};
            border-left-color: {p['hi']};
            border-radius: 10px;
            padding: 0px 10px;
            min-height: 34px;
            selection-background-color: {p['accent']};
            selection-color: {p['selected_text']};
        }}
        QPlainTextEdit, QTextEdit {{
            background-color: {p['raised']};
            color: {p['text']};
            border: 1px solid {p['border']};
            border-top-color: {p['hi']};
            border-left-color: {p['hi']};
            border-radius: 10px;
            padding: 8px 10px;
            min-height: 60px;
            selection-background-color: {p['accent']};
            selection-color: {p['selected_text']};
        }}
        QComboBox {{
            background-color: {p['raised']};
            color: {p['text']};
            border: 1px solid {p['border']};
            border-top-color: {p['hi']};
            border-left-color: {p['hi']};
            border-radius: 10px;
            padding: 0px 28px 0px 12px;
            min-height: 34px;
            combobox-popup: 0;
        }}
        QComboBox:hover {{
            background-color: {p['hi2']};
        }}
        QComboBox:focus {{
            border: 1px solid {p['accent']};
        }}
        QComboBox:disabled, QLineEdit:disabled {{
            background-color: {p['base']};
            color: {p['text_muted']};
        }}
        QComboBox::drop-down {{
            subcontrol-origin: padding;
            subcontrol-position: center right;
            border: none;
            width: 22px;
            background: transparent;
        }}
        QComboBox::down-arrow {{
            image: url("{chev}");
            width: 10px;
            height: 6px;
        }}
        QComboBox QAbstractItemView {{
            background-color: {p['raised']};
            color: {p['text']};
            border: 1px solid {p['border']};
            border-radius: 10px;
            padding: 4px;
            outline: none;
            selection-background-color: {p['accent']};
            selection-color: {p['selected_text']};
        }}
        QComboBox QAbstractItemView::item {{
            padding: 4px 12px;
            min-height: 28px;
            border-radius: 6px;
        }}
        QComboBox QAbstractItemView::item:selected {{
            background-color: {p['accent']};
            color: #ffffff;
        }}

        /* Ayarlar kenar çubuğu: dört uygulamada aynı iskelet (Lumina `dialog_stylesheet`). Seçili sekme vurgu tonlu
           hafif zemin + vurgu yazı + solda 3 px vurgu çizgisi; diğerleri soluk yazı. */
        QFrame#sidebar {{
            background-color: {p['surface']};
            border: 1px solid {p['border']};
            border-radius: 8px;
        }}
        QPushButton#nav_btn {{
            text-align: left;
            padding-left: 7px;
            color: {p['text_muted']};
            font-size: 13px;
            font-weight: 500;
            background: transparent;
            border: none;
            border-left: 3px solid transparent;
            border-radius: 6px;
            min-height: 38px;
            max-height: 38px;
            outline: none;
        }}
        QPushButton#nav_btn:hover {{
            background-color: {p['raised']};
            color: {p['text']};
        }}
        QPushButton#nav_btn:pressed {{
            border-color: transparent;  /* genel düğmenin basılı kabartma kenarları sekmede görünmesin */
        }}
        QPushButton#nav_btn:checked {{
            background-color: {nav_tint};
            color: {nav_ink};
            border-left: 3px solid {p['accent']};
            font-weight: 700;
        }}

        /* Onay kutusu: FlexiKey / TransferTCP / Lumina ile aynı (18 px kutu, 5 px köşe, 1 px kenar, seçiliyken vurgu
           dolgu + beyaz tik; pasifte gri). Durum kuralları aynı özgüllükte, sıra önemli. */
        QCheckBox {{
            spacing: 10px;
            color: {p['text']};
            background: transparent;
            padding: 0px;
            min-height: 24px;
        }}
        QCheckBox:disabled {{
            color: {p['text_muted']};
        }}
        QCheckBox::indicator {{
            width: 18px;
            height: 18px;
            border-radius: 5px;
            background-color: {p['chk_fill']};
            border: 1px solid {p['chk_border']};
        }}
        QCheckBox::indicator:unchecked:hover {{
            background-color: {p['chk_hover']};
            border-color: {p['accent']};
        }}
        QCheckBox::indicator:checked {{
            background-color: {p['accent2']};
            border-color: {p['accent2']};
            image: url("{tick}");
        }}
        QCheckBox::indicator:checked:hover {{
            background-color: {p['accent']};
            border-color: {p['accent']};
        }}
        QCheckBox::indicator:unchecked:disabled {{
            background-color: transparent;
            border-color: {p['chk_dis_border']};
        }}
        QCheckBox::indicator:checked:disabled {{
            background-color: {p['chk_border']};
            border-color: {p['chk_border']};
            image: url("{tick_muted}");
        }}

        QSlider:horizontal {{
            min-height: 24px;
            height: 24px;
        }}
        QSlider::groove:horizontal {{
            height: 6px;
            background: {p['sunken']};
            border: 1px solid {p['lo']};
            border-radius: 3px;
        }}
        QSlider::handle:horizontal {{
            width: 16px;
            height: 16px;
            margin: -5px 0;
            border-radius: 8px;
            background: {p['accent']};
        }}
        QSlider::handle:horizontal:hover {{
            background: {p['accent_hi']};
        }}
        QSlider::handle:horizontal:disabled {{
            background: {p['text_muted']};
        }}

        QSlider:vertical {{
            min-width: 24px;
            width: 24px;
        }}
        QSlider::groove:vertical {{
            width: 6px;
            background: {p['sunken']};
            border: 1px solid {p['lo']};
            border-radius: 3px;
        }}
        QSlider::handle:vertical {{
            width: 16px;
            height: 16px;
            margin: 0 -5px;
            border-radius: 8px;
            background: {p['accent']};
        }}
        QSlider::handle:vertical:hover {{
            background: {p['accent_hi']};
        }}

        QScrollArea {{ border: none; background: transparent; }}
        QWidget#right_col {{
            background: transparent;
        }}
        QScrollBar:vertical {{
            background: {p['sunken']};
            width: 10px;
            border-radius: 5px;
            margin: 2px;
        }}
        QScrollBar::handle:vertical {{
            background: {p['scroll']};
            border-radius: 5px;
            min-height: 28px;
        }}
        QScrollBar::handle:vertical:hover, QScrollBar::handle:vertical:pressed {{
            background: {p['accent']};
        }}
        QScrollBar:horizontal {{
            background: {p['sunken']};
            height: 10px;
            border-radius: 5px;
            margin: 2px;
        }}
        QScrollBar::handle:horizontal {{
            background: {p['scroll']};
            border-radius: 5px;
            min-width: 28px;
        }}
        QScrollBar::handle:horizontal:hover, QScrollBar::handle:horizontal:pressed {{
            background: {p['accent']};
        }}
        QScrollBar::add-line, QScrollBar::sub-line,
        QScrollBar::add-page, QScrollBar::sub-page {{
            background: none; border: none; height: 0; width: 0;
        }}

        /* Kuyruk listesi: satırları kendi temsilcisi çizer (iki sütun, durum renkleri, istisna etiketi) */
        QListWidget#queue_panel {{
            background-color: {p['raised']};
            color: {p['text']};
            border: 1px solid {p['border']};
            border-radius: 10px;
            outline: none;
        }}

        QProgressBar {{
            background-color: {p['sunken']};
            border: 1px solid {p['border']};
            border-radius: 8px;
            text-align: center;
            color: {p['text']};
            font-weight: 600;
            min-height: 20px;
        }}
        QProgressBar::chunk {{
            background-color: {p['accent']};
            border-radius: 7px;
        }}
        /* alttaki genel ilerleme: yazısız ince çizgi (yüzde üstteki satırda) */
        QProgressBar#slim_bar {{
            border: none;
            border-radius: 3px;
            min-height: 6px;
            max-height: 6px;
        }}
        QProgressBar#slim_bar::chunk {{
            border-radius: 3px;
        }}

        QFrame[frameShape="6"] {{
            background-color: {p['sunken']};
            border: 1px solid {p['border']};
            border-radius: 10px;
        }}

        QFrame#control_bar {{
            background-color: {p['sunken']};
            border: 1px solid {p['border']};
            border-radius: 8px;
            padding: 6px;
        }}
        QFrame#frame_box {{
            background-color: {p['sunken']};
            border: 1px solid {p['border']};
            border-radius: 6px;
            padding: 2px 4px;
        }}
        QScrollArea#preview_scroll {{
            background: transparent;
            border: 1px solid {p['border']};
            border-radius: 8px;
        }}
        QFrame#DropZone {{
            background-color: {p['sunken']};
            border: 1.5px dashed {p['accent']};
            border-radius: 10px;
            margin: 2px;
        }}
        QFrame#DropZone:hover {{
            border: 2.5px dashed {p['accent']};
            margin: 1px;
            background-color: {p['surface']};
        }}
        QFrame#DropZone QPushButton[class="primary"] {{
            min-height: 34px;
            padding: 0px 16px;
        }}
        /* dosya sürüklenirken: düz vurgu kenarlığı ve yumuşak vurgu zemini ("buraya bırakın") */
        QFrame#DropZone[dragActive="true"] {{
            border: 2.5px solid {p['accent']};
            margin: 1px;
            background-color: {p['accent_soft']};
        }}
        QFrame#DropZone[dragActive="true"] QLabel#hint_label {{
            color: {p['accent_text']};
            font-weight: 600;
        }}
        /* pencere içi toast: temanın tersi renkler (koyu temada açık kutu, açık temada koyu kutu) */
        QFrame#toast {{
            background-color: {p['toast_bg']};
            border: 1px solid {p['toast_border']};
            border-radius: 10px;
        }}
        QFrame#toast QLabel#toast_text {{
            color: {p['toast_text']};
            background: transparent;
            margin-right: 0px;
        }}
        QFrame#toast QPushButton#toast_action {{
            background: transparent;
            color: {p['toast_accent']};
            border: none;
            border-radius: 6px;
            font-weight: 700;
            padding: 4px 10px;
            min-height: 0px;
        }}
        QFrame#toast QPushButton#toast_action:hover {{
            background: {p['toast_hover']};
        }}
        QFrame#toast QPushButton#toast_close {{
            background: transparent;
            color: {p['toast_muted']};
            border: none;
            border-radius: 12px;
            padding: 0px;
            min-height: 0px;
            font-size: 9pt;
        }}
        QFrame#toast QPushButton#toast_close:hover {{
            background: {p['toast_hover']};
            color: {p['toast_text']};
        }}
        QFrame#left_panel, QFrame#right_panel, QFrame#action_bar {{
            background-color: {p['sunken']};
            border: 1px solid {p['border']};
            border-radius: 10px;
        }}
        /* sol panelin kaydırılan içeriği ve altına sabitlenen düğme şeridi panelin zeminini paylaşır */
        QWidget#left_content {{
            background: transparent;
        }}
        QFrame#left_footer {{
            background: transparent;
            border: none;
            border-top: 1px solid {p['hi2']};  /* kaydırılan kartlar bu çizginin altına girer */
            border-radius: 0px;
        }}

        QLabel {{
            color: {p['text']};
            background: transparent;
            border: none;
            padding: 0px;
        }}
        QFrame#title_bar QLabel {{
            min-height: 0px;
            padding: 0px;
            margin: 0px;
        }}
        QLabel#hint_label {{
            color: {p['text_muted']};
            font-size: 9pt;
            min-height: 1.45em;
        }}
        QLabel#dialog_header {{
            font-size: 13pt;
            font-weight: 700;
            min-height: 1.45em;
        }}
        QLabel#about_title {{
            color: {p['accent_text']};
            font-size: 13pt;
            font-weight: 700;
            min-height: 1.45em;
        }}
        QLabel#section_header {{
            font-size: 12pt;
            font-weight: 700;
            min-height: 1.45em;
        }}
        QLabel#gpu_ok {{
            color: {p['accent_text']};
            font-weight: 600;
            min-height: 1.45em;
        }}
        QLabel#gpu_warn {{
            color: {p['warn']};
            font-weight: 600;
            min-height: 1.45em;
        }}
        QLabel#banner_error {{
            color: {p['danger']};
            font-weight: 600;
            min-height: 1.45em;
        }}
        QFrame#update_error_box {{
            background-color: transparent;
            border: 1px solid {p['danger']};
            border-radius: 8px;
        }}
        QFrame#adv_card {{
            background-color: {p['sunken']};
            border: 1px solid {p['border']};
            border-radius: 10px;
        }}
        QFrame#adv_card QCheckBox, QFrame#adv_card QSlider {{ background: transparent; }}
        QLabel#trim_frame {{
            background-color: {p['sunken']};
            color: {p['text_muted']};
            border: 1px solid {p['border']};
            border-radius: 8px;
        }}
        /* içerik kapları panel rengini taşısın (genel QWidget kuralı onları daha koyu boyuyordu) */
        QWidget#plain_box {{ background-color: transparent; }}
        /* sol panel grupları: kabartmalı (neumorphic) kutu — üst/sol kenar açık, alt/sağ kenar koyu */
        QFrame#group_card {{
            background-color: {p['surface']};
            border: 1px solid {p['lo']};
            border-top-color: {p['hi2']};
            border-left-color: {p['hi2']};
            border-radius: 12px;
        }}
        QFrame#group_card QLabel#section_caption {{ padding-top: 0px; }}
        /* qproperty-indent: üst dolgu QLabel'e çerçeve kazandırıyor, Qt de metni yarım "x" (~3 px) içeri
           itiyordu; başlık altındaki alan etiketleri ve kutularla aynı çizgiden başlamıyordu. */
        QLabel#section_caption {{
            color: {p['text_muted']};
            font-size: 8.5pt;
            font-weight: 700;
            min-height: 1.3em;
            padding-top: 4px;
            qproperty-indent: 0;
        }}
        QLabel#path_box {{
            background-color: {p['base']};
            color: {p['text']};
            border: 1px solid {p['border']};
            border-radius: 8px;
            padding: 0px 10px;
            min-height: 30px;
        }}
        QLabel#path_box:hover {{
            border-color: {p['accent']};
        }}
        QLabel#field_label {{
            color: {p['text_muted']};
            font-size: 9pt;
            font-weight: 600;
            min-height: 1.5em;
        }}
        QLabel#update_status {{
            color: {p['text_muted']};
            font-size: 9pt;
            min-height: 1.45em;
        }}

        QMenu {{
            background-color: {p['raised']};
            border: 1px solid {p['border']};
            border-radius: 10px;
            padding: 6px;
        }}
        QMenu::item {{
            padding: 8px 28px 8px 16px;
            border-radius: 6px;
            color: {p['text']};
        }}
        QMenu::item:selected {{
            background-color: {p['accent']};
            color: #ffffff;
        }}
        QMenu::item:checked {{
            background-color: {p['accent_soft']};
            color: {p['accent_text']};
            font-weight: 700;
        }}
        QMenu::item:checked:selected {{
            background-color: {p['accent']};
            color: #ffffff;
            font-weight: 700;
        }}
        QMenu::item:disabled {{
            color: {p['text_muted']};  /* pasif satır soluk yazılır; simgesini Qt soldurur */
        }}
        QMenu::icon {{
            padding-left: 6px;
            padding-right: 6px;
        }}
        QMenu::indicator {{
            width: 0px;
            height: 0px;
        }}
        QMenu::right-arrow {{
            width: 8px;
            height: 8px;
            margin-right: 8px;
        }}
        QMenu::separator {{
            height: 1px;
            background: {p['border']};
            margin: 4px 6px;
        }}


        QToolTip {{
            background-color: {p['raised']};
            color: {p['text']};
            border: 1px solid {p['border']};
            border-radius: 8px;
            padding: 6px 10px;
        }}
        QSizeGrip {{ width: 14px; height: 14px; }}
        QSplitter::handle {{ background: transparent; width: 14px; }}
        QSplitter::handle:hover {{ background: {p['accent']}33; border-radius: 4px; }}
    """


def fit_text_widgets(root) -> None:
    """Fusion + QSS kombinasyonu g/ç/ş/y kuyruklarını kesmesin diye satır yüksekliği."""
    from PyQt6.QtWidgets import QCheckBox, QLabel

    if root is None:
        return
    sample = "Şğçypq"
    skip = {"title_label", "version_label"}
    labels = [root] if isinstance(root, QLabel) else []
    labels.extend(root.findChildren(QLabel))
    for lab in labels:
        if lab.objectName() in skip:
            continue
        parent = lab.parentWidget()
        if parent is not None and parent.objectName() == "title_bar":
            continue
        pix = None
        try:
            pix = lab.pixmap()
        except Exception:
            pix = None
        if not lab.text() and (pix is None or pix.isNull()):
            continue
        needed = lab.fontMetrics().boundingRect(sample).height() + 2
        if lab.minimumHeight() < needed:
            lab.setMinimumHeight(needed)
    boxes = [root] if isinstance(root, QCheckBox) else []
    boxes.extend(root.findChildren(QCheckBox))
    for box in boxes:
        needed = box.fontMetrics().boundingRect(sample).height() + 8
        if box.minimumHeight() < needed:
            box.setMinimumHeight(needed)


@contextmanager
def _no_gc():
    """Qt tüm widget'ları dolaşırken (stil / stil sayfası değişimi) Python çöp toplayıcısı çalışmasın.

    Döngüsel başvurulu, kapanmış bir pencere tam o anda toplanırsa Qt silinmiş bir widget'a dokunup çöker.
    """
    enabled = gc.isenabled()
    gc.disable()
    try:
        yield
    finally:
        if enabled:
            gc.enable()


class ThemeManager(QObject):
    theme_changed = pyqtSignal(str)

    def __init__(self, app: QApplication):
        super().__init__()
        self.app = app
        if "Fusion" in QStyleFactory.keys():
            with _no_gc():
                self.app.setStyle("Fusion")
        font = QFont("Segoe UI", 10)
        font.setHintingPreference(QFont.HintingPreference.PreferVerticalHinting)
        font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
        self.app.setFont(font)
        self.current_theme = "neumorphic_dark"
        self.accent_key = DEFAULT_ACCENT

    def set_theme(self, theme_name: str):
        if theme_name not in ("neumorphic_light", "neumorphic_dark"):
            theme_name = "neumorphic_dark"
        self.current_theme = theme_name
        dark = "dark" in theme_name
        global _ACTIVE_ACCENT
        _ACTIVE_ACCENT = self.accent_key if self.accent_key in ACCENTS else DEFAULT_ACCENT
        palette = _with_accent(DARK if dark else LIGHT, self.accent_key, dark)
        with _no_gc():
            self.app.setStyleSheet(_build(palette))
        for widget in self.app.topLevelWidgets():
            fit_text_widgets(widget)
        self.theme_changed.emit(theme_name)

    def get_current_theme(self) -> str:
        return self.current_theme

    def get_palette(self) -> dict:
        dark = "dark" in self.current_theme
        return _with_accent(DARK if dark else LIGHT, self.accent_key, dark)

    def apply_from_setting(self, setting: str, accent: str | None = None) -> None:
        if accent:
            self.accent_key = accent if accent in ACCENTS else DEFAULT_ACCENT
        if setting == "system":
            self.set_theme("neumorphic_dark" if is_system_dark() else "neumorphic_light")
        elif setting == "light":
            self.set_theme("neumorphic_light")
        else:
            self.set_theme("neumorphic_dark")


def is_system_dark() -> bool:
    import sys
    if sys.platform == "win32":
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
            )
            value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            winreg.CloseKey(key)
            return value == 0
        except Exception:
            return True
    if sys.platform == "darwin":
        try:
            import subprocess
            out = subprocess.run(
                ["defaults", "read", "-g", "AppleInterfaceStyle"],
                capture_output=True, text=True, timeout=3,
            )
            return "Dark" in (out.stdout or "")
        except Exception:
            return True
    return os.environ.get("GTK_THEME", "").lower().find("dark") >= 0
