"""Vektör simgeler (emoji yok): menü, tepsi ve düğme simgeleri QPainter ile çizilir.

Renkler çağıran tarafından verilir: menü/tepsi simgeleri seçilen vurgu rengine uysun diye sabit bir mavi yerine temanın
`accent_text` rengi (koyuda parlak vurgu, açıkta onun koyu tonu) kullanılır. Tüm simgeler 20x20 mantıksal px'lik bir
tuvalde çizilir ve 2x çözünürlüklü pixmap'e basılır (yüksek DPI'da keskin kalır).
"""

from __future__ import annotations

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QBrush, QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

DEFAULT_ICON_COLOR = "#00ACC1"  # varsayılan vurgu (Turkuaz); gerçek renk temadan gelir
_SCALE = 2


def accent_color_for(palette: dict | None) -> str:
    """Simge rengi: koyu temada parlak vurgu, açık temada onun koyu tonu (açık zeminde okunur kalsın)."""
    if not palette:
        return DEFAULT_ICON_COLOR
    if palette.get("accent_text"):
        return str(palette["accent_text"])
    if palette.get("is_dark", True):
        return str(palette.get("accent") or DEFAULT_ICON_COLOR)
    return str(palette.get("accent2") or palette.get("accent") or DEFAULT_ICON_COLOR)


def _canvas(size: int = 20) -> tuple[QPixmap, QPainter]:
    pix = QPixmap(size * _SCALE, size * _SCALE)
    pix.fill(Qt.GlobalColor.transparent)
    pix.setDevicePixelRatio(_SCALE)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    return pix, painter


def _pen(color: str, width: float = 1.5) -> QPen:
    pen = QPen(QColor(color), width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return pen


def _finish(pix: QPixmap, painter: QPainter) -> QIcon:
    painter.end()
    return QIcon(pix)


def eye_icon(color: str = DEFAULT_ICON_COLOR) -> QIcon:
    pix, p = _canvas()
    p.setPen(_pen(color))
    p.setBrush(Qt.BrushStyle.NoBrush)
    path = QPainterPath()
    path.moveTo(2.5, 10.0)
    path.cubicTo(6.0, 4.5, 14.0, 4.5, 17.5, 10.0)
    path.cubicTo(14.0, 15.5, 6.0, 15.5, 2.5, 10.0)
    p.drawPath(path)
    p.setBrush(QBrush(QColor(color)))
    p.drawEllipse(QPointF(10.0, 10.0), 2.6, 2.6)
    return _finish(pix, p)


def eye_off_icon(color: str = DEFAULT_ICON_COLOR) -> QIcon:
    """Göz + çapraz çizgi: tepsi menüsündeki "Gizle" satırı."""
    pix, p = _canvas()
    p.setPen(_pen(color))
    p.setBrush(Qt.BrushStyle.NoBrush)
    path = QPainterPath()
    path.moveTo(2.5, 10.0)
    path.cubicTo(6.0, 4.5, 14.0, 4.5, 17.5, 10.0)
    path.cubicTo(14.0, 15.5, 6.0, 15.5, 2.5, 10.0)
    p.drawPath(path)
    p.setBrush(QBrush(QColor(color)))
    p.drawEllipse(QPointF(10.0, 10.0), 2.4, 2.4)
    p.setPen(_pen(color, 1.7))
    p.drawLine(QPointF(4.2, 16.2), QPointF(15.8, 3.8))
    return _finish(pix, p)


def gear_icon(color: str = DEFAULT_ICON_COLOR) -> QIcon:
    pix, p = _canvas()
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(QColor(color)))
    p.drawEllipse(QRectF(5.6, 5.6, 8.8, 8.8))
    for ang in range(0, 360, 45):
        p.save()
        p.translate(10, 10)
        p.rotate(ang)
        p.drawRoundedRect(QRectF(-1.5, -8.6, 3.0, 4.6), 0.8, 0.8)
        p.restore()
    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)  # gerçek (saydam) göbek deliği
    p.drawEllipse(QRectF(7.6, 7.6, 4.8, 4.8))
    return _finish(pix, p)


def door_exit_icon(color: str = "#ef4444") -> QIcon:
    pix, p = _canvas()
    p.setPen(_pen(color))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPolyline([QPointF(9.0, 3.5), QPointF(3.5, 3.5), QPointF(3.5, 16.5), QPointF(9.0, 16.5)])
    p.drawLine(QPointF(7.0, 10.0), QPointF(16.5, 10.0))
    p.drawLine(QPointF(13.0, 6.5), QPointF(16.5, 10.0))
    p.drawLine(QPointF(13.0, 13.5), QPointF(16.5, 10.0))
    return _finish(pix, p)


def update_icon(color: str = DEFAULT_ICON_COLOR) -> QIcon:
    """İndirme oku + tepsi: "güncelleme var" satırının simgesi."""
    pix, p = _canvas()
    p.setPen(_pen(color, 1.7))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawLine(QPointF(10.0, 3.0), QPointF(10.0, 12.2))
    p.drawPolyline([QPointF(6.4, 8.8), QPointF(10.0, 12.4), QPointF(13.6, 8.8)])
    p.drawPolyline([QPointF(4.0, 13.2), QPointF(4.0, 16.6), QPointF(16.0, 16.6), QPointF(16.0, 13.2)])
    return _finish(pix, p)


def globe_icon(color: str = DEFAULT_ICON_COLOR, size: int = 20) -> QIcon:
    pix, p = _canvas(size)
    p.setPen(_pen(color))
    p.setBrush(Qt.BrushStyle.NoBrush)
    r = (size - 4) / 2.0
    cx, cy = size / 2.0, size / 2.0
    p.drawEllipse(QPointF(cx, cy), r, r)
    p.drawLine(QPointF(cx - r, cy), QPointF(cx + r, cy))
    p.drawLine(QPointF(cx, cy - r), QPointF(cx, cy + r))
    p.drawEllipse(QPointF(cx, cy), r * 0.55, r)
    return _finish(pix, p)


def swatch_icon(hex_color: str) -> QIcon:
    pix, p = _canvas(16)
    p.setPen(QPen(QColor(hex_color).darker(115), 1))
    p.setBrush(QBrush(QColor(hex_color)))
    p.drawRoundedRect(QRectF(1, 1, 14, 14), 4, 4)
    return _finish(pix, p)


def contrast_icon(color: str = DEFAULT_ICON_COLOR) -> QIcon:
    """Yarısı dolu daire: "Tema" düğmesinin simgesi."""
    pix, p = _canvas()
    p.setPen(_pen(color, 1.5))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawEllipse(QRectF(3.0, 3.0, 14.0, 14.0))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(QColor(color)))
    p.drawPie(QRectF(3.0, 3.0, 14.0, 14.0), 90 * 16, 180 * 16)
    return _finish(pix, p)


def info_icon(color: str = DEFAULT_ICON_COLOR) -> QIcon:
    pix, p = _canvas()
    p.setPen(_pen(color, 1.5))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawEllipse(QRectF(2.5, 2.5, 15.0, 15.0))
    p.drawLine(QPointF(10.0, 9.0), QPointF(10.0, 14.0))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(QColor(color)))
    p.drawEllipse(QPointF(10.0, 6.4), 1.1, 1.1)
    return _finish(pix, p)


def file_add_icon(color: str = DEFAULT_ICON_COLOR) -> QIcon:
    """Kıvrık köşeli sayfa + artı: "Dosya Ekle…"."""
    pix, p = _canvas()
    p.setPen(_pen(color, 1.4))
    p.setBrush(Qt.BrushStyle.NoBrush)
    page = QPainterPath()
    page.moveTo(5.0, 2.5)
    page.lineTo(11.0, 2.5)
    page.lineTo(15.0, 6.5)
    page.lineTo(15.0, 9.0)
    p.drawPath(page)
    p.drawPolyline([QPointF(5.0, 2.5), QPointF(5.0, 17.5), QPointF(10.0, 17.5)])
    p.drawPolyline([QPointF(11.0, 2.5), QPointF(11.0, 6.5), QPointF(15.0, 6.5)])
    p.setPen(_pen(color, 1.5))
    p.drawLine(QPointF(14.0, 12.0), QPointF(14.0, 18.0))
    p.drawLine(QPointF(11.0, 15.0), QPointF(17.0, 15.0))
    return _finish(pix, p)


def folder_add_icon(color: str = DEFAULT_ICON_COLOR) -> QIcon:
    """Klasör + artı: "Klasör Ekle…"."""
    pix, p = _canvas()
    p.setPen(_pen(color, 1.4))
    p.setBrush(Qt.BrushStyle.NoBrush)
    body = QPainterPath()
    body.moveTo(10.0, 16.5)
    body.lineTo(3.5, 16.5)
    body.lineTo(3.5, 4.5)
    body.lineTo(8.0, 4.5)
    body.lineTo(9.8, 6.5)
    body.lineTo(16.5, 6.5)
    body.lineTo(16.5, 9.0)
    p.drawPath(body)
    p.setPen(_pen(color, 1.5))
    p.drawLine(QPointF(14.0, 12.0), QPointF(14.0, 18.0))
    p.drawLine(QPointF(11.0, 15.0), QPointF(17.0, 15.0))
    return _finish(pix, p)


def image_icon(color: str = DEFAULT_ICON_COLOR) -> QIcon:
    pix, p = _canvas()
    p.setPen(_pen(color, 1.4))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(QRectF(2.5, 3.5, 15.0, 13.0), 2.0, 2.0)
    p.drawPolyline([QPointF(3.5, 14.5), QPointF(8.0, 9.5), QPointF(11.5, 13.0), QPointF(13.5, 11.0), QPointF(16.5, 14.5)])
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(QColor(color)))
    p.drawEllipse(QPointF(13.5, 7.2), 1.4, 1.4)
    return _finish(pix, p)


def film_icon(color: str = DEFAULT_ICON_COLOR) -> QIcon:
    pix, p = _canvas()
    p.setPen(_pen(color, 1.4))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(QRectF(2.5, 3.5, 15.0, 13.0), 2.0, 2.0)
    p.drawLine(QPointF(6.5, 3.5), QPointF(6.5, 16.5))
    p.drawLine(QPointF(13.5, 3.5), QPointF(13.5, 16.5))
    for y in (6.5, 10.0, 13.5):
        p.drawLine(QPointF(2.5, y), QPointF(6.5, y))
        p.drawLine(QPointF(13.5, y), QPointF(17.5, y))
    return _finish(pix, p)


def clock_icon(color: str = DEFAULT_ICON_COLOR) -> QIcon:
    pix, p = _canvas()
    p.setPen(_pen(color, 1.5))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawEllipse(QRectF(2.5, 2.5, 15.0, 15.0))
    p.drawPolyline([QPointF(10.0, 5.8), QPointF(10.0, 10.0), QPointF(13.0, 11.8)])
    return _finish(pix, p)


def scissors_icon(color: str = DEFAULT_ICON_COLOR) -> QIcon:
    pix, p = _canvas()
    p.setPen(_pen(color, 1.5))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawEllipse(QPointF(5.2, 14.6), 2.4, 2.4)
    p.drawEllipse(QPointF(14.8, 14.6), 2.4, 2.4)
    p.drawLine(QPointF(6.6, 12.6), QPointF(14.6, 3.6))
    p.drawLine(QPointF(13.4, 12.6), QPointF(5.4, 3.6))
    return _finish(pix, p)


# ---------------------------------------------------------------------------------------------------------------
# Tema simgeleri: anlamsal renkler (güneş sarı, ay ve sistem nötr gri); lacivert/slate ton yok
# ---------------------------------------------------------------------------------------------------------------
def theme_system_icon() -> QIcon:
    pix, p = _canvas()
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(QColor("#6f6f6f")))
    p.drawEllipse(2, 2, 16, 16)
    p.setBrush(QBrush(QColor("#f2f2f2")))
    p.drawPie(2, 2, 16, 16, 90 * 16, 180 * 16)
    return _finish(pix, p)


def theme_dark_icon() -> QIcon:
    """Hilal: nötr açık gri daireden zemin rengine kaydırılmış daire çıkarılarak çizilir (saydam kesim)."""
    pix, p = _canvas()
    p.setPen(Qt.PenStyle.NoPen)
    moon = QPainterPath()
    moon.addEllipse(QRectF(3.0, 3.0, 14.0, 14.0))
    cut = QPainterPath()
    cut.addEllipse(QRectF(7.6, 1.2, 12.0, 12.0))
    p.setBrush(QBrush(QColor("#c9c9c9")))
    p.drawPath(moon.subtracted(cut))
    return _finish(pix, p)


def theme_light_icon() -> QIcon:
    pix, p = _canvas()
    p.setPen(QPen(QColor("#f59e0b"), 1.6))
    p.setBrush(QBrush(QColor("#fbbf24")))
    p.drawEllipse(5, 5, 10, 10)
    for ang in range(0, 360, 45):
        p.save()
        p.translate(10, 10)
        p.rotate(ang)
        p.drawLine(QPointF(0, -9), QPointF(0, -7))
        p.restore()
    return _finish(pix, p)


def app_fallback_pixmap(size: int = 22, color: str = DEFAULT_ICON_COLOR) -> QPixmap:
    """Uygulama simgesi yoksa başlıkta gösterilen basit "sıkıştır" simgesi (iki ok içeri bakar)."""
    pix, p = _canvas(size)
    s = size / 20.0
    p.scale(s, s)
    p.setPen(_pen(color, 1.8))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(QRectF(2.0, 2.0, 16.0, 16.0), 4.0, 4.0)
    p.drawPolyline([QPointF(6.0, 8.0), QPointF(10.0, 10.0), QPointF(14.0, 8.0)])
    p.drawPolyline([QPointF(6.0, 12.0), QPointF(10.0, 10.0), QPointF(14.0, 12.0)])
    p.end()
    return pix
