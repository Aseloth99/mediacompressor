"""Vektör simgeler (emoji yok): menü, tepsi ve düğme simgeleri QPainter ile çizilir.

Renkler çağıran tarafından verilir: menü/tepsi simgeleri seçilen vurgu rengine uysun diye sabit bir mavi yerine temanın
`accent_text` rengi (koyuda parlak vurgu, açıkta onun koyu tonu) kullanılır. Tüm simgeler 20x20 mantıksal px'lik bir
tuvalde çizilir ve 2x çözünürlüklü pixmap'e basılır (yüksek DPI'da keskin kalır).
"""

from __future__ import annotations

import math

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QBrush, QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap, QPolygonF

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


def scissors_icon(color: str = DEFAULT_ICON_COLOR) -> QIcon:
    pix, p = _canvas()
    p.setPen(_pen(color, 1.5))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawEllipse(QPointF(5.2, 14.6), 2.4, 2.4)
    p.drawEllipse(QPointF(14.8, 14.6), 2.4, 2.4)
    p.drawLine(QPointF(6.6, 12.6), QPointF(14.6, 3.6))
    p.drawLine(QPointF(13.4, 12.6), QPointF(5.4, 3.6))
    return _finish(pix, p)


def trash_icon(color: str = DEFAULT_ICON_COLOR) -> QIcon:
    """Çöp kutusu: kuyruk menüsünde "Kuyruktan Çıkar"."""
    pix, p = _canvas()
    p.setPen(_pen(color, 1.4))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawLine(QPointF(3.5, 5.5), QPointF(16.5, 5.5))
    p.drawPolyline([QPointF(8.0, 5.5), QPointF(8.0, 3.2), QPointF(12.0, 3.2), QPointF(12.0, 5.5)])
    p.drawPolyline([QPointF(5.2, 5.5), QPointF(6.2, 17.0), QPointF(13.8, 17.0), QPointF(14.8, 5.5)])
    p.drawLine(QPointF(8.6, 8.6), QPointF(8.9, 14.2))
    p.drawLine(QPointF(11.4, 8.6), QPointF(11.1, 14.2))
    return _finish(pix, p)


def sliders_icon(color: str = DEFAULT_ICON_COLOR) -> QIcon:
    """Üç kaydırıcı: kuyruk menüsünde "İstisna Uygula" (dosyaya özel ayar)."""
    pix, p = _canvas()
    p.setPen(_pen(color, 1.4))
    p.setBrush(Qt.BrushStyle.NoBrush)
    for y, knob in ((5.0, 12.5), (10.0, 6.5), (15.0, 10.5)):
        p.drawLine(QPointF(3.0, y), QPointF(knob - 2.0, y))
        p.drawLine(QPointF(knob + 2.0, y), QPointF(17.0, y))
        p.drawEllipse(QPointF(knob, y), 2.0, 2.0)
    return _finish(pix, p)


def sidebar_icon(color: str = DEFAULT_ICON_COLOR, collapsed: bool = False) -> QIcon:
    """Sol bölmeli pencere + ok: kuyruk başlığında "ayar panelini gizle/göster" (gizliyken ok sağa bakar)."""
    pix, p = _canvas()
    p.setPen(_pen(color, 1.4))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(QRectF(2.5, 3.5, 15.0, 13.0), 2.5, 2.5)
    p.drawLine(QPointF(7.5, 3.5), QPointF(7.5, 16.5))
    if collapsed:
        p.drawPolyline([QPointF(11.0, 7.5), QPointF(13.5, 10.0), QPointF(11.0, 12.5)])
    else:
        p.drawPolyline([QPointF(13.5, 7.5), QPointF(11.0, 10.0), QPointF(13.5, 12.5)])
    return _finish(pix, p)


def folder_icon(color: str = DEFAULT_ICON_COLOR) -> QIcon:
    """Klasör: "Klasörde Göster"."""
    pix, p = _canvas()
    p.setPen(_pen(color, 1.4))
    p.setBrush(Qt.BrushStyle.NoBrush)
    body = QPainterPath()
    body.moveTo(3.5, 16.0)
    body.lineTo(3.5, 4.5)
    body.lineTo(8.0, 4.5)
    body.lineTo(9.8, 6.5)
    body.lineTo(16.5, 6.5)
    body.lineTo(16.5, 16.0)
    body.closeSubpath()
    p.drawPath(body)
    p.drawLine(QPointF(3.5, 9.0), QPointF(16.5, 9.0))
    return _finish(pix, p)


def open_external_icon(color: str = DEFAULT_ICON_COLOR) -> QIcon:
    """Kutudan dışarı çıkan ok: "Dosyayı Aç" (varsayılan uygulamada)."""
    pix, p = _canvas()
    p.setPen(_pen(color, 1.4))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPolyline([QPointF(9.0, 4.0), QPointF(4.0, 4.0), QPointF(4.0, 16.0), QPointF(16.0, 16.0), QPointF(16.0, 11.0)])
    p.setPen(_pen(color, 1.5))
    p.drawLine(QPointF(9.5, 10.5), QPointF(16.0, 4.0))
    p.drawPolyline([QPointF(11.5, 4.0), QPointF(16.0, 4.0), QPointF(16.0, 8.5)])
    return _finish(pix, p)


# ---------------------------------------------------------------------------------------------------------------
# Tema simgeleri: anlamsal renkler (güneş sarı, ay ve sistem nötr gri); lacivert/slate ton yok
# ---------------------------------------------------------------------------------------------------------------
def theme_system_icon() -> QIcon:
    """Yarısı açık / yarısı koyu daire (nötr gri); ince kenarlık açık menü zemininde de görünmesini sağlar.
    Dört Python uygulamasında (FlexiKey, Lumina, MediaCompressor, TransferTCP) aynı çizim ve renkler kullanılır."""
    pix, p = _canvas()
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(QColor("#6f6f6f")))
    p.drawEllipse(QRectF(2.0, 2.0, 16.0, 16.0))
    p.setBrush(QBrush(QColor("#f2f2f2")))
    p.drawPie(QRectF(2.0, 2.0, 16.0, 16.0), 90 * 16, 180 * 16)
    p.setPen(QPen(QColor("#8c8c8c"), 1.0))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawEllipse(QRectF(2.5, 2.5, 15.0, 15.0))
    return _finish(pix, p)


def theme_dark_icon() -> QIcon:
    """Hilal: orta gri (koyu ve açık menüde okunur); daireden kaydırılmış daire çıkarılarak çizilir (saydam kesim)."""
    pix, p = _canvas()
    p.setPen(Qt.PenStyle.NoPen)
    moon = QPainterPath()
    moon.addEllipse(QRectF(3.0, 3.0, 14.0, 14.0))
    cut = QPainterPath()
    cut.addEllipse(QRectF(7.6, 1.2, 12.0, 12.0))
    p.setBrush(QBrush(QColor("#9a9a9a")))
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


# ---------------------------------------------------------------------- pencere düğmesi glifleri (32'lik ızgara)
# Dört PyQt uygulamasında aynı: büyüt (tek kare), geri yükle (üst üste iki kare; arkadaki öndekinin altından görünmez)
# ve başlıktaki "güncelleme hazır" oku. Düğmenin paintEvent'inde doğrudan çizilir: her ölçekte (%100/%125/%150) keskin.
WINDOW_GLYPHS = ("maximize", "restore", "update")
# 32'lik ızgaranın düğmede kapladığı mantıksal kare: 7.5 birim = 4 px, böylece büyüt karesinin kenarları ve okun gövdesi
# %100/%125/%150/%200 ölçekte tam piksele oturur (□ 8 px, çizgi ≈ 1 px: yanındaki ince "−" ve "×" ile aynı iri).
WINDOW_GLYPH_PX = 32 * 8 / 15
_SNAP_REF = {"maximize": (8.5, 8.5), "restore": (8.0, 11.5), "update": (16.0, 9.0)}  # piksel merkezine oturan nokta


def paint_window_glyph(painter: QPainter, target: QRectF, kind: str, color) -> None:
    """`kind` ("maximize" | "restore" | "update") glifini `target` karesine (32'lik ızgara) `color` ile çizer."""
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.translate(target.x(), target.y())
    painter.scale(target.width() / 32.0, target.height() / 32.0)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    ink = QColor(color)
    if kind == "maximize":
        painter.setPen(_pen(ink, 1.85))
        painter.drawRoundedRect(QRectF(8.5, 8.5, 15, 15), 2.2, 2.2)
    elif kind == "restore":
        front = QRectF(8, 11.5, 12.5, 12.5)
        painter.setPen(_pen(ink, 1.7))
        # Arkadaki kare yalnızca öndekinin örtmediği yerde: çizgiler kesişmez (Windows'un kendi simgesi gibi)
        hole = QPainterPath()
        hole.addRoundedRect(front, 1.8, 1.8)
        area = QPainterPath()
        area.addRect(QRectF(-2, -2, 36, 36))
        painter.save()
        painter.setClipPath(area.subtracted(hole), Qt.ClipOperation.IntersectClip)
        painter.drawRoundedRect(QRectF(11.5, 7.5, 12.5, 12.5), 1.8, 1.8)
        painter.restore()
        painter.drawRoundedRect(front, 1.8, 1.8)  # kırpma kenarı öndeki çizginin altında kalır
    elif kind == "update":
        painter.setPen(_pen(ink, 2.1))
        painter.drawLine(QPointF(16, 24), QPointF(16, 9))
        painter.drawPolyline([QPointF(10.5, 14.5), QPointF(16, 9), QPointF(21.5, 14.5)])
    painter.restore()


def paint_centered_window_glyph(painter: QPainter, rect, kind: str, color, size: float = WINDOW_GLYPH_PX,
                                center_y: float | None = None) -> None:
    """Glifi `rect`in (düğmenin) ortasına `size` px'lik kare olarak çizer (`center_y`: komşu metin gliflerinin dikey
    ortası). Ana çizgiler aygıt pikselinin ortasına kaydırılır: kesirli ölçekte de bulanıklaşmaz."""
    box = QRectF(rect)
    cy = box.center().y() if center_y is None else float(center_y)
    ox, oy = box.center().x() - size / 2.0, cy - size / 2.0
    ref = _SNAP_REF.get(kind)
    if ref is not None:
        unit = size / 32.0
        dev = painter.deviceTransform()
        sx, sy = abs(dev.m11()) or 1.0, abs(dev.m22()) or 1.0
        at = dev.map(QPointF(ox + ref[0] * unit, oy + ref[1] * unit))
        ox += (round(at.x() - 0.5) + 0.5 - at.x()) / sx
        oy += (round(at.y() - 0.5) + 0.5 - at.y()) / sy
    paint_window_glyph(painter, QRectF(ox, oy, size, size), kind, color)


def _menu_accent(kind: str = "accent") -> str:
    """Seçili vurgunun rengi (`accent`, `hi_light`): tema yöneticisinin en son uyguladığı vurgudan okunur."""
    from ..utils import theme_manager as tm

    return (tm.ACCENTS.get(tm.active_accent()) or tm.ACCENTS[tm.DEFAULT_ACCENT])[kind]


# --- Renkli menü simgeleri ------------------------------------------------------------------------------------
# Lumina'daki (`app/ui/icons.py: menu_icon`) çizim ve renklerin aynısı: başlık menüleri, tepsi menüsü, sağ tık
# menüleri ve Ayarlar kenar çubuğu için iki tonlu, renkli simgeler. Her anlamın sabit bir rengi var (ayarlar mor
# dişli, bilgi mavi, güncelleme yeşil, çıkış/sil kırmızı, klasör amber...); "blue"/"sky" aileleri seçili vurguyu
# izler. Araç çubuğu simgeleri tek renk kalır. 32'lik ızgarada çizilir (32 ve 48 px kopya: %100/%150'de keskin);
# devre dışı satırlarda Qt simgeyi kendisi griler.

MENU_PALETTE = {
    "blue": "#2196F3", "blue_soft": "#90CAF9",  # "blue"/"sky" aileleri `_mi_color` içinde seçili vurguya yönlenir
    "amber": "#f59e0b", "amber_soft": "#fcd34d", "amber_deep": "#d97706",
    "green": "#22c55e", "emerald": "#10b981",
    "violet": "#8b5cf6", "purple": "#a855f7", "purple_soft": "#e9d5ff",
    "indigo": "#7c7ff5", "sky": "#2196F3", "sky_soft": "#90CAF9",
    "teal": "#14b8a6", "red": "#ef4444", "red_soft": "#fecaca",
    "orange": "#f97316", "cyan": "#06b6d4", "yellow": "#eab308",
}


def _mi_color(name: str) -> QColor:
    """Menü simgesi rengi. "blue"/"sky" aileleri seçili vurguyu izler; diğerleri anlam taşıyan sabit tonlardır."""
    if name in ("blue", "sky"):
        return QColor(_menu_accent("accent"))
    if name in ("blue_soft", "sky_soft"):
        return QColor(_menu_accent("hi_light"))
    return QColor(MENU_PALETTE[name])


def _mi_pen(color: QColor, width: float = 2.2) -> QPen:
    pen = QPen(color, width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return pen


def _mi_icon(draw) -> QIcon:
    """`draw(painter)` 32×32'lik ızgarada çizer; 32 ve 48 px kopyalar."""
    icon = QIcon()
    for size in (32, 48):
        pix = QPixmap(size, size)
        pix.fill(Qt.GlobalColor.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.scale(size / 32.0, size / 32.0)
        draw(p)
        p.end()
        icon.addPixmap(pix)
    return icon


def _mi_gear(p: QPainter) -> None:
    gear = QPainterPath()
    gear.addEllipse(QPointF(16, 16), 8.6, 8.6)
    for i in range(8):
        tooth = QPainterPath()
        tooth.addRoundedRect(QRectF(-2.4, -12.4, 4.8, 6.0), 1.2, 1.2)
        p.save()
        p.translate(16, 16)
        p.rotate(i * 45)
        gear = gear.united(p.transform().map(tooth))
        p.restore()
    hole = QPainterPath()
    hole.addEllipse(QPointF(16, 16), 3.6, 3.6)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(_mi_color("violet")))
    p.drawPath(gear.subtracted(hole))


def _mi_badge(p: QPainter, color: str) -> None:
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(_mi_color(color)))
    p.drawEllipse(QPointF(16, 16), 11, 11)


def _mi_info(p: QPainter) -> None:
    _mi_badge(p, "blue")
    p.setBrush(QBrush(QColor("#ffffff")))
    p.drawEllipse(QPointF(16, 10.6), 1.7, 1.7)
    p.drawRoundedRect(QRectF(14.5, 14, 3, 9.5), 1.3, 1.3)


def _mi_add(p: QPainter) -> None:
    """Yeşil rozet + beyaz artı: "Yeni …" satırları."""
    _mi_badge(p, "green")
    p.setPen(_mi_pen(QColor("#ffffff"), 2.4))
    p.drawLine(QPointF(16, 10.5), QPointF(16, 21.5))
    p.drawLine(QPointF(10.5, 16), QPointF(21.5, 16))


def _mi_update(p: QPainter) -> None:
    color = _mi_color("emerald")
    p.setPen(_mi_pen(color, 2.2))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawArc(QRectF(6.5, 6.5, 19, 19), 30 * 16, 150 * 16)
    p.drawArc(QRectF(6.5, 6.5, 19, 19), 210 * 16, 150 * 16)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(color))
    p.drawPolygon(QPolygonF([QPointF(24.6, 5.8), QPointF(25.4, 12.6), QPointF(18.8, 10.6)]))
    p.drawPolygon(QPolygonF([QPointF(7.4, 26.2), QPointF(6.6, 19.4), QPointF(13.2, 21.4)]))


def _mi_exit(p: QPainter) -> None:
    """Kapı + dışarı ok: "Çıkış" satırları."""
    color = _mi_color("red")
    p.setPen(_mi_pen(color, 2.0))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPolyline(QPolygonF([QPointF(14.5, 6.5), QPointF(6.5, 6.5), QPointF(6.5, 25.5), QPointF(14.5, 25.5)]))
    p.drawLine(QPointF(12.0, 16.0), QPointF(26.0, 16.0))
    p.drawPolyline(QPolygonF([QPointF(21.0, 11.0), QPointF(26.0, 16.0), QPointF(21.0, 21.0)]))


def _mi_view(p: QPainter) -> None:
    eye = QPainterPath()
    eye.moveTo(4, 16)
    eye.quadTo(16, 4.5, 28, 16)
    eye.quadTo(16, 27.5, 4, 16)
    p.setPen(_mi_pen(_mi_color("indigo"), 1.8))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(eye)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(_mi_color("indigo")))
    p.drawEllipse(QPointF(16, 16), 4.6, 4.6)


def _mi_globe(p: QPainter) -> None:
    fill = _mi_color("sky")
    fill.setAlpha(55)
    p.setPen(_mi_pen(_mi_color("sky"), 1.7))
    p.setBrush(QBrush(fill))
    p.drawEllipse(QPointF(16, 16), 10, 10)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawEllipse(QPointF(16, 16), 4.6, 10)
    p.drawLine(QPointF(6, 16), QPointF(26, 16))
    p.drawLine(QPointF(7.6, 11), QPointF(24.4, 11))
    p.drawLine(QPointF(7.6, 21), QPointF(24.4, 21))


def _mi_document(p: QPainter) -> None:
    body = QPainterPath()
    body.moveTo(9, 5.5)
    body.lineTo(18.5, 5.5)
    body.lineTo(24, 11)
    body.lineTo(24, 25)
    body.quadTo(24, 26.5, 22.5, 26.5)
    body.lineTo(9.5, 26.5)
    body.quadTo(8, 26.5, 8, 25)
    body.lineTo(8, 7)
    body.quadTo(8, 5.5, 9, 5.5)
    p.setPen(_mi_pen(_mi_color("blue"), 1.6))
    p.setBrush(QBrush(_mi_color("blue_soft")))
    p.drawPath(body)
    p.setBrush(QBrush(_mi_color("blue")))
    p.drawPolygon(QPolygonF([QPointF(18.5, 5.5), QPointF(24, 11), QPointF(18.5, 11)]))
    p.setPen(_mi_pen(_mi_color("blue"), 1.5))
    for y, x2 in ((15.5, 20.5), (19, 20.5), (22.5, 17)):
        p.drawLine(QPointF(11.5, y), QPointF(x2, y))


def _mi_folder(p: QPainter) -> None:
    back = QPainterPath()
    back.moveTo(5, 9.5)
    back.quadTo(5, 7.5, 7, 7.5)
    back.lineTo(12.5, 7.5)
    back.lineTo(15, 10)
    back.lineTo(25, 10)
    back.quadTo(27, 10, 27, 12)
    back.lineTo(27, 23)
    back.quadTo(27, 25, 25, 25)
    back.lineTo(7, 25)
    back.quadTo(5, 25, 5, 23)
    back.closeSubpath()
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(_mi_color("amber_deep")))
    p.drawPath(back)
    p.setBrush(QBrush(_mi_color("amber_soft")))
    p.drawRoundedRect(QRectF(5, 12.5, 22, 12.5), 2.0, 2.0)


def _mi_plus_badge(p: QPainter) -> None:
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(_mi_color("green")))
    p.drawEllipse(QPointF(23, 22), 7, 7)
    p.setPen(_mi_pen(QColor("#ffffff"), 1.9))
    p.drawLine(QPointF(23, 18.6), QPointF(23, 25.4))
    p.drawLine(QPointF(19.6, 22), QPointF(26.4, 22))


def _mi_folder_add(p: QPainter) -> None:
    """Klasör + yeşil artı rozeti (Lumina "Kopyala…" ile aynı çizim): "Klasör Ekle"."""
    _mi_folder(p)
    _mi_plus_badge(p)


def _mi_file_add(p: QPainter) -> None:
    """Belge + yeşil artı rozeti: "Dosya Ekle"."""
    _mi_document(p)
    _mi_plus_badge(p)


def _mi_copy(p: QPainter) -> None:
    p.setPen(_mi_pen(_mi_color("sky"), 1.6))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(QRectF(12, 5.5, 13, 15.5), 2, 2)
    p.setBrush(QBrush(_mi_color("sky_soft")))
    p.drawRoundedRect(QRectF(7, 10.5, 13, 15.5), 2, 2)


def _mi_trash(p: QPainter) -> None:
    p.setPen(_mi_pen(_mi_color("red"), 1.8))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawLine(QPointF(7.5, 10), QPointF(24.5, 10))
    p.drawLine(QPointF(13, 10), QPointF(13.8, 6.8))
    p.drawLine(QPointF(19, 10), QPointF(18.2, 6.8))
    p.drawLine(QPointF(13.8, 6.8), QPointF(18.2, 6.8))
    p.setBrush(QBrush(_mi_color("red_soft")))
    p.drawRoundedRect(QRectF(9.5, 10, 13, 15.5), 2, 2)
    p.drawLine(QPointF(14, 14), QPointF(14, 21.5))
    p.drawLine(QPointF(18, 14), QPointF(18, 21.5))


def _mi_open_with(p: QPainter) -> None:
    p.setPen(_mi_pen(_mi_color("purple"), 1.8))
    p.setBrush(QBrush(_mi_color("purple_soft")))
    p.drawRoundedRect(QRectF(5.5, 9.5, 17, 17), 2.5, 2.5)
    p.setPen(_mi_pen(_mi_color("purple"), 2.1))
    p.drawLine(QPointF(14, 18), QPointF(26, 6))
    p.drawLine(QPointF(19, 6), QPointF(26, 6))
    p.drawLine(QPointF(26, 6), QPointF(26, 13))


def _mi_rename(p: QPainter) -> None:
    p.save()
    p.translate(16, 16)
    p.rotate(45)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(_mi_color("amber")))
    p.drawRoundedRect(QRectF(-3.2, -11.5, 6.4, 17), 1.2, 1.2)
    p.setBrush(QBrush(_mi_color("amber_deep")))
    p.drawRect(QRectF(-3.2, -11.5, 6.4, 3.4))
    p.setBrush(QBrush(QColor("#fde68a")))
    p.drawPolygon(QPolygonF([QPointF(-3.2, 5.5), QPointF(3.2, 5.5), QPointF(0, 11)]))
    p.restore()
    p.setPen(_mi_pen(_mi_color("amber_deep"), 1.6))
    p.drawLine(QPointF(17, 26), QPointF(26, 26))


def _mi_guide(p: QPainter) -> None:
    """Açık kitap: "Kullanım Kılavuzu"."""
    color = _mi_color("indigo")
    soft = QColor(color)
    soft.setAlpha(60)
    p.setPen(_mi_pen(color, 1.7))
    p.setBrush(QBrush(soft))
    for x_out in (5.0, 27.0):
        page = QPainterPath()
        page.moveTo(16, 9)
        page.cubicTo(16 + (x_out - 16) * 0.27, 7, 16 + (x_out - 16) * 0.68, 6.8, x_out, 7.5)
        page.lineTo(x_out, 24)
        page.cubicTo(16 + (x_out - 16) * 0.68, 23.3, 16 + (x_out - 16) * 0.27, 23.5, 16, 25.5)
        page.closeSubpath()
        p.drawPath(page)
    p.drawLine(QPointF(16, 9), QPointF(16, 25.5))


def _mi_bolt(p: QPainter) -> None:
    """Şimşek: "Hızlı İşlemler"."""
    p.setPen(_mi_pen(_mi_color("amber_deep"), 1.2))
    p.setBrush(QBrush(_mi_color("yellow")))
    p.drawPolygon(QPolygonF([QPointF(18.4, 4), QPointF(8.8, 16.8), QPointF(15.6, 16.8), QPointF(13.6, 28),
                             QPointF(23.2, 15.2), QPointF(16.4, 15.2)]))


def _mi_backup(p: QPainter) -> None:
    """Arşiv kutusu: "Yedekleme ve Aktarım"."""
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(_mi_color("amber_deep")))
    p.drawRoundedRect(QRectF(5, 7, 22, 6.5), 1.8, 1.8)
    p.setBrush(QBrush(_mi_color("amber_soft")))
    p.drawRoundedRect(QRectF(7, 13.5, 18, 12.5), 1.8, 1.8)
    p.setPen(_mi_pen(_mi_color("amber_deep"), 2.0))
    p.drawLine(QPointF(13, 17.5), QPointF(19, 17.5))


def _mi_trim(p: QPainter) -> None:
    """Makas: "Kırp…" (Lumina'daki kırpma gibi yeşil)."""
    color = _mi_color("green")
    p.setPen(_mi_pen(color, 2.0))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawEllipse(QPointF(9.5, 22.5), 3.6, 3.6)
    p.drawEllipse(QPointF(22.5, 22.5), 3.6, 3.6)
    p.drawLine(QPointF(11.8, 19.6), QPointF(23, 6))
    p.drawLine(QPointF(20.2, 19.6), QPointF(9, 6))


def _mi_adjust(p: QPainter) -> None:
    """Kaydırıcılar: dosyaya özel ayarlar."""
    color = _mi_color("orange")
    p.setPen(_mi_pen(color, 2.0))
    for y in (9, 16, 23):
        p.drawLine(QPointF(5.5, y), QPointF(26.5, y))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(color))
    for x, y in ((11, 9), (21, 16), (14, 23)):
        p.drawEllipse(QPointF(x, y), 3.3, 3.3)


def _mi_send(p: QPainter) -> None:
    """Kâğıt uçak: "Dosya Gönder" / aktarım."""
    color = _mi_color("teal")
    soft = QColor(color)
    soft.setAlpha(70)
    p.setPen(_mi_pen(color, 1.8))
    p.setBrush(QBrush(soft))
    p.drawPolygon(QPolygonF([QPointF(4.5, 15), QPointF(27.5, 5.5), QPointF(20.5, 27), QPointF(15, 18.5)]))
    p.drawLine(QPointF(15, 18.5), QPointF(27.5, 5.5))


def _mi_star(p: QPainter) -> None:
    """Yıldız: sık kullanılanlar."""
    points = []
    for i in range(10):
        radius = 11.0 if i % 2 == 0 else 4.8
        angle = math.radians(-90 + i * 36)
        points.append(QPointF(16 + radius * math.cos(angle), 16.8 + radius * math.sin(angle)))
    p.setPen(_mi_pen(_mi_color("amber_deep"), 1.2))
    p.setBrush(QBrush(_mi_color("yellow")))
    p.drawPolygon(QPolygonF(points))


def _mi_network(p: QPainter) -> None:
    """Bağlı üç düğüm: ağ ayarları."""
    color = _mi_color("cyan")
    p.setPen(_mi_pen(color, 2.0))
    p.drawLine(QPointF(16, 8.5), QPointF(8.5, 22.5))
    p.drawLine(QPointF(16, 8.5), QPointF(23.5, 22.5))
    p.drawLine(QPointF(8.5, 22.5), QPointF(23.5, 22.5))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(color))
    for x, y in ((16, 8.5), (8.5, 22.5), (23.5, 22.5)):
        p.drawEllipse(QPointF(x, y), 4.2, 4.2)


def _mi_pause(p: QPainter) -> None:
    """İki çubuk: "Duraklat"."""
    p.setPen(_mi_pen(_mi_color("amber_deep"), 1.2))
    p.setBrush(QBrush(_mi_color("amber")))
    p.drawRoundedRect(QRectF(8.2, 6.5, 5.8, 19), 1.8, 1.8)
    p.drawRoundedRect(QRectF(18, 6.5, 5.8, 19), 1.8, 1.8)


def _mi_play(p: QPainter) -> None:
    """Üçgen: "Sürdür" / oynat."""
    p.setPen(_mi_pen(_mi_color("emerald"), 1.4))
    p.setBrush(QBrush(_mi_color("green")))
    p.drawPolygon(QPolygonF([QPointF(10, 6.5), QPointF(26, 16), QPointF(10, 25.5)]))

# Anlam -> simge (renk anlamla birlikte gelir; dört uygulamada aynı tablo)
_MENU_DRAWERS = {
    "settings": _mi_gear,       # mor dişli
    "info": _mi_info,           # mavi (vurgu) rozet
    "update": _mi_update,       # zümrüt yeşili oklar
    "exit": _mi_exit,           # kırmızı kapı
    "view": _mi_view,           # çivit göz (Göster/Gizle, önizleme)
    "globe": _mi_globe,         # vurgu küre (dil)
    "file": _mi_document,       # mavi (vurgu) belge
    "folder": _mi_folder,       # amber klasör (klasörde göster / klasörü aç)
    "folder_add": _mi_folder_add,
    "file_add": _mi_file_add,
    "add": _mi_add,             # yeşil artı (yeni …)
    "copy": _mi_copy,           # vurgu kopya
    "trash": _mi_trash,         # kırmızı çöp
    "open_with": _mi_open_with,  # mor dışarı aç
    "rename": _mi_rename,       # amber kalem (yaz/düzenle)
    "guide": _mi_guide,         # çivit kitap
    "bolt": _mi_bolt,           # sarı şimşek
    "backup": _mi_backup,       # amber arşiv
    "trim": _mi_trim,           # yeşil makas
    "adjust": _mi_adjust,       # turuncu kaydırıcılar
    "send": _mi_send,           # camgöbeği-yeşil uçak (aktarım)
    "star": _mi_star,           # sarı yıldız
    "network": _mi_network,     # camgöbeği düğümler
    "pause": _mi_pause,         # amber çubuklar (duraklat)
    "play": _mi_play,           # yeşil üçgen (sürdür / oynat)
}
MENU_ICON_NAMES = frozenset(_MENU_DRAWERS)
_MENU_ICON_CACHE: dict[str, QIcon] = {}


def menu_icon(name: str) -> QIcon:
    """Menü satırı / ayarlar sekmesi için renkli simge (önbellekli; QApplication kurulduktan sonra çağrılmalı)."""
    key = f"{name}|{_menu_accent('accent')}"  # vurgu değişince "blue"/"sky" ailesi yeniden çizilir
    icon = _MENU_ICON_CACHE.get(key)
    if icon is None:
        icon = _mi_icon(_MENU_DRAWERS[name])
        _MENU_ICON_CACHE[key] = icon
    return icon
