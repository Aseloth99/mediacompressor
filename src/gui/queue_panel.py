"""İş kuyruğu — her dosya tek öğe; pencere genişse iki sütuna akar.

Eski tablo (QTableWidget) tek sütundu: geniş ekranda satırların ortası boş kalıyordu. Liste görünümü
ızgara genişliğini görünüm alanına göre ayarlar (``columns``); seçim, sürükle-bırak, sağ tık ve çift tık
öğe bazında çalışır. Sağ tıkla seçili dosyalara "istisna" (o dosyalara özel çözünürlük / FPS / ses) verilir,
tek videoda "Kırp…" ile başlangıç-bitiş seçilir; istisnası olan satırda adın yanında küçük bir etiket görünür.
"""

from __future__ import annotations

import os
from pathlib import Path

from PyQt6.QtCore import QModelIndex, QPoint, QRect, QSize, Qt, pyqtSignal
from PyQt6.QtGui import (
    QAction, QActionGroup, QColor, QDragEnterEvent, QDragMoveEvent, QDropEvent, QFont, QFontMetrics, QIcon,
    QPainter, QPalette, QPen, QPixmap,
)
from PyQt6.QtWidgets import (
    QAbstractItemView, QListView, QListWidget, QListWidgetItem, QMenu, QStyle, QStyledItemDelegate,
    QStyleOptionViewItem, QWidget,
)

from ..core.image_compressor import IMAGE_EXTS
from ..core.video_compressor import VIDEO_EXTS
from ..utils.helpers import format_bytes, format_duration
from ..utils.locales import t
from ..utils.timecode import clock
from . import icons

# Durum -> palet anahtarı (metin rengi); palet gelene kadar tema fark etmeden okunabilir sabitler.
STATUS_COLOR_KEYS = {
    "wait": "text_muted",
    "run": "accent_text",
    "ok": "ok_text",
    "skip": "warn",
    "fail": "fail_text",
    "cancel": "text_muted",
}

STATUS_KEYS = {
    "wait": "status_wait",
    "run": "status_run",
    "ok": "status_ok",
    "skip": "status_skip",
    "fail": "status_fail",
    "cancel": "status_cancel",
}

# İstisna seçenekleri: (değer etiketi, iş parçacığına giden sayı). "Orijinal" = küçültme yok / FPS korunur.
ORIGINAL = "Orijinal"
VIDEO_RES_CHOICES = [(ORIGINAL, None), ("2160p", 3840), ("1440p", 2560), ("1080p", 1920), ("720p", 1280), ("480p", 854)]
IMAGE_RES_CHOICES = [(ORIGINAL, None), ("3840px", 3840), ("2400px", 2400), ("1920px", 1920), ("1280px", 1280)]
FPS_CHOICES = [(ORIGINAL, None), ("60", 60), ("30", 30), ("25", 25), ("24", 24)]
AUDIO_CHOICES = [("keep", False), ("mute", True)]  # remove_audio değeri
OVERRIDE_CHOICES = {
    "video_res": VIDEO_RES_CHOICES, "image_res": IMAGE_RES_CHOICES, "fps": FPS_CHOICES, "remove_audio": AUDIO_CHOICES,
}
VIDEO_ONLY_KEYS = ("video_res", "fps", "remove_audio", "trim")

ROLE_PATH = Qt.ItemDataRole.UserRole
ROLE_STATUS = Qt.ItemDataRole.UserRole + 1
ROLE_SIZE = Qt.ItemDataRole.UserRole + 2
ROLE_PROGRESS = Qt.ItemDataRole.UserRole + 3  # sürmekte olan dosyanın oranı (0–1); None = oran bilinmiyor
ROLE_ETA = Qt.ItemDataRole.UserRole + 4  # o dosyanın kalan süresi ("58 sn"); "" = henüz tahmin yok

ROW_H = 40
HEADER_H = 34
PAD = 12
ICON = 18
NAME_MIN = 180  # bir sütunda dosya adına kalan en az genişlik (iki sütuna geçiş eşiği bundan hesaplanır)

# Çok büyük kuyrukta her dosya için boyut okumak arayüzü yavaşlatır; bu sayıdan sonra boyut gösterilmez.
SIZE_LOOKUP_LIMIT = 3000


def _status_text(status: str, lang: str) -> str:
    key = STATUS_KEYS.get(status)
    return t(key, lang) if key else status


def progress_text(ratio: float, eta: str, lang: str) -> str:
    """Satır içi ilerleme: "%41 · ~58 sn" (en: "41% · ~58 s"); süre tahmini yoksa yalnızca yüzde."""
    pct = t("pct", lang).format(int(ratio * 100))
    return f"{pct} · ~{eta}" if eta else pct


def row_status_text(status: str, ratio, eta: str, lang: str, fm: QFontMetrics | None = None, room: int = 0) -> str:
    """Durum sütununda yazan metin. Sürmekte olan dosyanın oranı biliniyorsa durum adı yerine ilerleme;
    süreli metin sütuna sığmazsa yalnızca yüzde."""
    if status != "run" or ratio is None:
        return _status_text(status, lang)
    text = progress_text(ratio, eta, lang)
    if fm is not None and room and fm.horizontalAdvance(text) > room:
        text = progress_text(ratio, "", lang)
    return text


def is_video(path: str) -> bool:
    return Path(path).suffix.lower() in VIDEO_EXTS


# Resim mavi, video turuncu: eskiden ikisi de maviydi, uzun kuyrukta bir bakışta ayırt edilmiyordu. Mavi-turuncu
# renk körlüğünde de ayrışan çift; ikisi de vurgu rengindeki (turkuaz) seçili satırın üstünde okunur.
IMAGE_ICON_COLOR = "#1E88E5"
VIDEO_ICON_COLOR = "#F4511E"


def _paint_icon(kind: str) -> QIcon:
    pm = QPixmap(64, 64)  # 150% ölçekte de keskin (öğede 18 px çizilir)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.scale(2, 2)
    if kind == "image":
        p.setBrush(QColor(IMAGE_ICON_COLOR))
        p.drawRoundedRect(3, 5, 26, 22, 4, 4)
        p.setBrush(QColor("#FFD54F"))
        p.drawEllipse(8, 9, 6, 6)
        p.setBrush(QColor("#E3F2FD"))
        p.drawPolygon(
            [QPoint(5, 25), QPoint(12, 16), QPoint(17, 21), QPoint(21, 17), QPoint(27, 25)]
        )
    else:
        p.setBrush(QColor(VIDEO_ICON_COLOR))
        p.drawRoundedRect(3, 5, 26, 22, 4, 4)
        p.setBrush(QColor("#FFFFFF"))
        p.drawPolygon([QPoint(12, 10), QPoint(12, 22), QPoint(23, 16)])
    p.end()
    return QIcon(pm)


_IMAGE_ICON: QIcon | None = None
_VIDEO_ICON: QIcon | None = None


def _icon_for(path: str) -> QIcon:
    global _IMAGE_ICON, _VIDEO_ICON
    if _IMAGE_ICON is None:
        _IMAGE_ICON = _paint_icon("image")
        _VIDEO_ICON = _paint_icon("video")
    ext = Path(path).suffix.lower()
    if ext in IMAGE_EXTS:
        return _IMAGE_ICON
    return _VIDEO_ICON


def trim_text(trim, lang: str) -> str:
    """Kırpma etiketi: "✂ 0:05–1:30" (bitiş yoksa "✂ 0:05–son")."""
    start, end = trim[0], trim[1]
    end_text = clock(end, tenths=bool(end % 1)) if end is not None else t("trim_to_end", lang)
    return f"✂ {clock(start, tenths=bool(start % 1))}–{end_text}"


def override_label(ov: dict, lang: str) -> str:
    """İstisna etiketi: "✂ 0:05–1:30 · 720p · 30 fps · Sessiz" (Orijinal dile göre)."""
    parts = []
    if ov.get("trim"):
        parts.append(trim_text(ov["trim"], lang))
    for key in ("video_res", "image_res"):
        if key in ov:
            parts.append(t("res_original", lang) if ov[key] == ORIGINAL else ov[key])
    if "fps" in ov:
        parts.append(t("fps_original", lang) if ov["fps"] == ORIGINAL else t("fps_value", lang).format(ov["fps"]))
    if "remove_audio" in ov:
        parts.append(t("ovr_audio_mute" if ov["remove_audio"] == "mute" else "ovr_audio_keep", lang))
    return " · ".join(parts)


def override_values(ov: dict) -> dict:
    """Etiketlerden iş parçacığının kullandığı değerler ({'video_res': 1280, 'fps': 30, 'trim': (5.0, 90.0),
    'remove_audio': True, ...}; None = orijinal)."""
    out = {}
    for key, label in ov.items():
        if key == "trim":
            if label:
                out["trim"] = (float(label[0]), None if label[1] is None else float(label[1]))
            continue
        choices = dict(OVERRIDE_CHOICES.get(key, []))
        if label in choices:
            out[key] = choices[label]
    return out


def trim_fraction(ov: dict) -> float:
    """Kırpılan videonun kalan payı (süre biliniyorsa); kalan süre tahmini dosyayı bu oranda tartar."""
    trim = ov.get("trim")
    if not trim or len(trim) < 3 or not trim[2]:
        return 1.0
    start, end, duration = float(trim[0]), trim[1], float(trim[2])
    stop = duration if end is None else min(float(end), duration)
    return max(0.0, min(1.0, (stop - start) / duration))


class _Layout:
    """Bir hücrenin iç yerleşimi (başlık ve satırlar aynı ölçüleri kullanır)."""

    def __init__(self, font: QFont, lang: str):
        bold = QFont(font)
        bold.setBold(True)
        fm, fmb = QFontMetrics(font), QFontMetrics(bold)
        statuses = [_status_text(s, lang) for s in STATUS_KEYS] + [t("queue_col_status", lang)]
        statuses.append(progress_text(1.0, format_duration(59, lang), lang))  # "%100 · ~59 sn" sığsın
        self.status_w = max(fmb.horizontalAdvance(s) for s in statuses) + 20
        self.size_w = max(fm.horizontalAdvance("999.9 MB → 999.9 MB"), fmb.horizontalAdvance(t("queue_col_size", lang))) + 16
        self.min_col = PAD + ICON + 9 + NAME_MIN + 10 + self.status_w + self.size_w + PAD  # parts() ile aynı boşluklar

    def parts(self, rect: QRect) -> tuple[QRect, QRect, QRect, QRect]:
        """(ikon, ad, durum, boyut) dikdörtgenleri."""
        x, y, w, h = rect.x(), rect.y(), rect.width(), rect.height()
        size = QRect(x + w - PAD - self.size_w, y, self.size_w, h)
        status = QRect(size.x() - self.status_w, y, self.status_w, h)
        icon = QRect(x + PAD, y + (h - ICON) // 2, ICON, ICON)
        name = QRect(icon.right() + 9, y, max(0, status.x() - icon.right() - 9 - 10), h)
        return icon, name, status, size


class _Delegate(QStyledItemDelegate):
    def __init__(self, panel: "QueuePanel"):
        super().__init__(panel)
        self.panel = panel

    def sizeHint(self, option, index):  # noqa: N802
        return self.panel.gridSize()

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex):
        panel = self.panel
        pal = panel.colors
        rect = option.rect
        cols = panel.columns
        row = index.row()
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        # sıra rengi: görünen satıra göre (iki sütunda yan yana iki öğe aynı satırdadır); satırın son
        # hücresi zemini görünüm alanının sağ kenarına kadar uzatır (ızgara payı boş görünmesin)
        if (row // cols) % 2:
            band = QRect(rect)
            if row % cols == cols - 1:
                band.setRight(max(rect.right(), panel.viewport().width()))
            painter.fillRect(band, pal["alt"])
        if cols > 1 and row % cols:
            painter.setPen(QPen(pal["line"], 1))
            painter.drawLine(rect.topLeft(), rect.bottomLeft())
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        if selected or hovered:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(pal["select"] if selected else pal["hover"])
            painter.drawRoundedRect(rect.adjusted(3, 2, -3, -2), 6, 6)

        path = index.data(ROLE_PATH) or ""
        status = index.data(ROLE_STATUS) or "wait"
        icon_r, name_r, status_r, size_r = panel.layout_info.parts(rect)
        _icon_for(path).paint(painter, icon_r)

        font = QFont(option.font)
        painter.setFont(font)
        fm = QFontMetrics(font)
        name = os.path.basename(path)
        chip = override_label(panel.overrides_for(path), panel.lang)
        chip_w = 0
        small = QFont(font)
        small.setPointSizeF(max(7.5, font.pointSizeF() - 1.5))
        small.setBold(True)
        fms = QFontMetrics(small)
        if chip:
            chip_w = min(fms.horizontalAdvance(chip) + 14, max(0, name_r.width() // 2))
        name_room = max(0, name_r.width() - (chip_w + 8 if chip_w else 0))
        shown = fm.elidedText(name, Qt.TextElideMode.ElideMiddle, name_room)
        painter.setPen(pal["text"])
        painter.drawText(QRect(name_r.x(), name_r.y(), name_room, name_r.height()),
                         int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), shown)
        if chip_w:
            cx = name_r.x() + fm.horizontalAdvance(shown) + 8
            chip_r = QRect(cx, rect.y() + (rect.height() - 20) // 2, chip_w, 20)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(pal["chip_bg"])
            painter.drawRoundedRect(chip_r, 10, 10)
            painter.setFont(small)
            painter.setPen(pal["chip_text"])
            painter.drawText(chip_r.adjusted(7, 0, -7, 0), int(Qt.AlignmentFlag.AlignCenter),
                             fms.elidedText(chip, Qt.TextElideMode.ElideRight, chip_r.width() - 14))

        st_font = QFont(font)
        st_font.setBold(status in ("run", "ok", "fail"))
        painter.setFont(st_font)
        painter.setPen(panel.status_color(status))
        st_fm = QFontMetrics(st_font)
        ratio = index.data(ROLE_PROGRESS) if status == "run" else None
        st_text = row_status_text(status, ratio, index.data(ROLE_ETA) or "", panel.lang, st_fm, status_r.width() - 6)
        painter.drawText(status_r, int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
                         st_fm.elidedText(st_text, Qt.TextElideMode.ElideRight, status_r.width() - 6))
        if ratio is not None:
            # Satırın altında ince ilerleme çizgisi (alttaki büyük çubuğun yerine; her dosya kendi satırında)
            track = QRect(icon_r.x(), rect.bottom() - 4, size_r.right() - icon_r.x(), 3)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(pal["track"])
            painter.drawRoundedRect(track, 1.5, 1.5)
            if ratio > 0:
                fill = QRect(track)
                fill.setWidth(max(3, int(track.width() * ratio)))
                painter.setBrush(panel.status_color("run"))
                painter.drawRoundedRect(fill, 1.5, 1.5)
        painter.setFont(font)
        painter.setPen(pal["text"])
        painter.drawText(size_r, int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight),
                         fm.elidedText(index.data(ROLE_SIZE) or "—", Qt.TextElideMode.ElideLeft, size_r.width()))
        painter.restore()


class _Header(QWidget):
    """Sütun başlıkları (her kuyruk sütunu için Dosya / Durum / Boyut)."""

    def __init__(self, panel: "QueuePanel"):
        super().__init__(panel)
        self.panel = panel
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def paintEvent(self, event):  # noqa: N802
        panel = self.panel
        pal = panel.colors
        p = QPainter(self)
        p.fillRect(self.rect(), pal["header_bg"])
        p.setPen(QPen(pal["line"], 1))
        p.drawLine(self.rect().bottomLeft(), self.rect().bottomRight())
        font = QFont(self.font())
        font.setPointSizeF(9)
        font.setBold(True)
        p.setFont(font)
        col_w = panel.gridSize().width()
        for c in range(panel.columns):
            cell = QRect(c * col_w, 0, col_w, self.height())
            icon_r, name_r, status_r, size_r = panel.layout_info.parts(cell)
            if c:
                p.setPen(QPen(pal["line"], 1))
                p.drawLine(cell.topLeft(), cell.bottomLeft())
            p.setPen(pal["muted"])
            left = Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft
            p.drawText(QRect(icon_r.x(), 0, name_r.right() - icon_r.x(), self.height()), int(left),
                       t("queue_col_file", panel.lang))
            p.drawText(QRect(status_r.x(), 0, status_r.width(), self.height()), int(left), t("queue_col_status", panel.lang))
            p.drawText(QRect(size_r.x(), 0, size_r.width(), self.height()),
                       int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight), t("queue_col_size", panel.lang))
        p.end()


class QueuePanel(QListWidget):
    remove_requested = pyqtSignal(list)
    reveal_requested = pyqtSignal(str)
    open_requested = pyqtSignal(str)
    preview_requested = pyqtSignal(str)
    trim_requested = pyqtSignal(str)
    selection_count_changed = pyqtSignal(int)
    overrides_changed = pyqtSignal()

    def __init__(self, parent=None, lang: str = "tr"):
        super().__init__(parent)
        self.setObjectName("queue_panel")
        self.lang = lang
        self._locked = False
        self._items: dict[str, QListWidgetItem] = {}
        self._sizes: dict[str, int] = {}
        self._overrides: dict[str, dict] = {}
        self._status_colors: dict[str, QColor] = {}
        self._drop_at: tuple[int, bool] | None = None  # (öğe sırası, sonrasına mı) — sürükleme göstergesi
        self.columns = 1
        self.colors = self._default_colors()
        self.layout_info = _Layout(self.font(), lang)

        self.setViewMode(QListView.ViewMode.ListMode)
        self.setFlow(QListView.Flow.LeftToRight)
        self.setWrapping(True)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setUniformItemSizes(True)
        self.setSpacing(0)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(False)  # göstergeyi kendimiz çiziyoruz (iki sütunda da doğru yer)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)
        self.itemSelectionChanged.connect(self._emit_sel)
        self.itemDoubleClicked.connect(self._dbl)
        self.setItemDelegate(_Delegate(self))
        self._header = _Header(self)
        self.setViewportMargins(0, HEADER_H, 0, 0)
        self.setGridSize(QSize(400, ROW_H))
        self.retranslate(lang)

    # ------------------------------------------------------------------ görünüm
    @staticmethod
    def _default_colors() -> dict[str, QColor]:
        return {
            "text": QColor("#e8e8e8"), "muted": QColor("#9e9e9e"), "alt": QColor("#252525"),
            "line": QColor("#1a1a1a"), "header_bg": QColor("#252525"),
            "select": QColor(0, 172, 193, 70), "hover": QColor(255, 255, 255, 14),
            "chip_bg": QColor(0, 172, 193, 50), "chip_text": QColor("#4DD0E1"),
            "track": QColor(158, 158, 158, 60),
        }

    def set_status_palette(self, palette: dict) -> None:
        """Tema renkleri: durum yazıları (bekliyor soluk, sürüyor vurgu, tamam yeşil, hata kırmızı), sıra/seçim tonları."""
        self._status_colors = {
            status: QColor(str(palette[key])) for status, key in STATUS_COLOR_KEYS.items() if palette.get(key)
        }
        self._menu_icon_color = str(palette.get("accent_text") or palette.get("accent") or icons.DEFAULT_ICON_COLOR)
        light = QColor(str(palette.get("raised", "#2a2a2a"))).lightness() > 128
        accent = QColor(str(palette.get("accent", "#00ACC1")))
        select = QColor(accent)
        select.setAlpha(60 if light else 75)
        chip_bg = QColor(accent)
        chip_bg.setAlpha(40 if light else 55)
        hover = QColor(0, 0, 0, 12) if light else QColor(255, 255, 255, 14)
        muted = QColor(str(palette.get("text_muted", "#9e9e9e")))
        track = QColor(muted)
        track.setAlpha(55 if light else 70)
        self.colors = {
            "text": QColor(str(palette.get("text", "#e8e8e8"))),
            "muted": muted,
            "track": track,
            "alt": QColor(str(palette.get("surface", "#252525"))),
            "line": QColor(str(palette.get("border", "#1a1a1a"))),
            "header_bg": QColor(str(palette.get("surface", "#252525"))),
            "select": select, "hover": hover, "chip_bg": chip_bg,
            "chip_text": QColor(str(palette.get("accent_text", accent.name()))),
        }
        self._header.update()
        self.viewport().update()

    def status_color(self, status: str) -> QColor:
        color = self._status_colors.get(status)
        return color if color is not None and color.isValid() else self.colors["muted" if status in ("wait", "cancel") else "text"]

    def retranslate(self, lang: str = "tr"):
        self.lang = lang
        self.layout_info = _Layout(self.font(), lang)
        self.setToolTip(t("queue_tooltip", lang))
        for path, item in self._items.items():
            item.setToolTip(self._tooltip(path))
        self._relayout()

    def _relayout(self) -> None:
        width = self.viewport().width()
        # QListView sararken dikey kaydırma çubuğu için pay bırakır (çubuk yokken PM_ScrollBarExtent, varken
        # birkaç px): hücreler tam yarı genişlik olunca ikinci öğe alt satıra kayıyordu. Sağda kalan şeridi
        # temsilci satır zeminiyle doldurur.
        sb_visible = self.verticalScrollBar().isVisible()
        reserve = (0 if sb_visible else self.style().pixelMetric(QStyle.PixelMetric.PM_ScrollBarExtent, None, self)) + 6
        usable = max(1, width - reserve)
        cols = 2 if usable >= 2 * self.layout_info.min_col else 1
        grid = QSize(max(1, usable // cols), ROW_H)
        changed = cols != self.columns or grid != self.gridSize()
        self.columns = cols
        if changed:
            self.setGridSize(grid)
        frame = self.frameWidth()
        self._header.setGeometry(frame, frame, width, HEADER_H)
        self._header.update()
        self.viewport().update()

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        self._relayout()

    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        self._relayout()

    def changeEvent(self, event):  # noqa: N802
        super().changeEvent(event)
        if event.type() in (event.Type.FontChange, event.Type.StyleChange):
            self.layout_info = _Layout(self.font(), self.lang)
            self._relayout()

    # ------------------------------------------------------------------ içerik
    def set_locked(self, locked: bool):
        self._locked = locked

    def rowCount(self) -> int:  # noqa: N802 — eski tablo arayüzü (ana pencere ve testler)
        return self.count()

    def total_bytes(self) -> int:
        """Kuyruktaki kaynak dosyaların toplam boyutu (bilinenler; çok büyük kuyrukta 0)."""
        return sum(self._sizes.get(p, 0) for p in self.paths())

    def size_of(self, path: str) -> int:
        size = self._sizes.get(path)
        if size is None:
            try:
                size = os.path.getsize(path)
            except OSError:
                size = 0
        return size

    def _size_text(self, path: str) -> str:
        size = self._sizes.get(path)
        return format_bytes(size) if size is not None else "—"

    def _new_item(self, path: str, status: str = "wait", size_text: str | None = None) -> QListWidgetItem:
        item = QListWidgetItem()
        item.setData(ROLE_PATH, path)
        item.setData(ROLE_STATUS, status)
        item.setData(ROLE_SIZE, size_text if size_text is not None else self._size_text(path))
        item.setToolTip(self._tooltip(path))
        item.setSizeHint(QSize(1, ROW_H))
        return item

    def set_files(self, files: list[str]):
        self.clear()
        self._items.clear()
        self._sizes = {}
        if len(files) <= SIZE_LOOKUP_LIMIT:
            for path in files:
                try:
                    self._sizes[path] = os.path.getsize(path)
                except OSError:
                    pass
        keep = set(files)
        dropped = [p for p in self._overrides if p not in keep]
        for p in dropped:
            del self._overrides[p]
        for path in files:
            item = self._new_item(path)
            self.addItem(item)
            self._items[path] = item
        if dropped:
            self.overrides_changed.emit()
        self._emit_sel()
        self.viewport().update()

    def paintEvent(self, event):  # noqa: N802
        super().paintEvent(event)
        painter = QPainter(self.viewport())
        if self._drop_at is not None:
            self._paint_drop_indicator(painter)
        if self.count() > 0:
            painter.end()
            return
        # Boş durum: başlığın altında ortalanmış açıklama (kuyruk dolunca kendiliğinden kaybolur).
        rect = self.viewport().rect()
        muted = self.palette().color(QPalette.ColorRole.PlaceholderText)
        cx, cy = rect.width() // 2, rect.height() // 2 - 78
        pen = QPen(muted, 2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(pen)
        painter.drawLine(cx, cy - 18, cx, cy + 6)
        painter.drawLine(cx, cy + 6, cx - 9, cy - 3)
        painter.drawLine(cx, cy + 6, cx + 9, cy - 3)
        painter.drawPolyline([QPoint(cx - 18, cy + 4), QPoint(cx - 18, cy + 18), QPoint(cx + 18, cy + 18), QPoint(cx + 18, cy + 4)])
        painter.setPen(muted)
        title_font = QFont(self.font())
        title_font.setPointSizeF(self.font().pointSizeF() + 3)
        title_font.setBold(True)
        painter.setFont(title_font)
        title_rect = rect.adjusted(24, rect.height() // 2 - 44, -24, 0)
        painter.drawText(title_rect, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, t("queue_empty_title", self.lang))
        painter.setFont(self.font())
        hint_rect = rect.adjusted(40, rect.height() // 2 - 8, -40, 0)
        painter.drawText(
            hint_rect,
            int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop) | int(Qt.TextFlag.TextWordWrap),
            t("queue_empty_hint", self.lang),
        )
        painter.end()

    def path_at(self, row: int) -> str:
        item = self.item(row)
        if item is None:
            return ""
        return item.data(ROLE_PATH) or ""

    def paths(self) -> list[str]:
        return [p for r in range(self.count()) if (p := self.path_at(r))]

    def selected_paths(self) -> list[str]:
        rows = sorted(self.row(item) for item in self.selectedItems())
        return [p for r in rows if (p := self.path_at(r))]

    def status_of(self, path: str) -> str:
        item = self._items.get(path)
        return (item.data(ROLE_STATUS) or "wait") if item is not None else ""

    def size_text_of(self, path: str) -> str:
        item = self._items.get(path)
        return (item.data(ROLE_SIZE) or "") if item is not None else ""

    def mark(self, path: str, status: str, extra=None):
        item = self._items.get(path)
        if item is None:
            return
        item.setData(ROLE_STATUS, status)
        # yeni başlayan ya da biten dosyada eski oran kalmasın (oranı set_progress verir)
        item.setData(ROLE_PROGRESS, None)
        item.setData(ROLE_ETA, "")
        if isinstance(extra, dict) and "in" in extra and "out" in extra:
            item.setData(ROLE_SIZE, f"{format_bytes(extra['in'])} → {format_bytes(extra['out'])}")

    def set_progress(self, path: str, ratio: float | None, eta: str = "") -> None:
        """Sürmekte olan dosyanın satırındaki ilerleme (yüzde, kalan süre ve satır altı çizgisi)."""
        item = self._items.get(path)
        if item is None:
            return
        item.setData(ROLE_PROGRESS, None if ratio is None else max(0.0, min(1.0, float(ratio))))
        item.setData(ROLE_ETA, eta or "")

    def progress_of(self, path: str) -> float | None:
        item = self._items.get(path)
        return item.data(ROLE_PROGRESS) if item is not None else None

    def status_display(self, path: str) -> str:
        """Satırın Durum sütununda okunan metin (sığdırma kısaltması hariç)."""
        item = self._items.get(path)
        if item is None:
            return ""
        return row_status_text(item.data(ROLE_STATUS) or "wait", item.data(ROLE_PROGRESS),
                               item.data(ROLE_ETA) or "", self.lang)

    def apply_order(self, paths: list[str]):
        snap = {p: (self.status_of(p), self.size_text_of(p), self.progress_of(p),
                    self._items[p].data(ROLE_ETA) or "") for p in self.paths()}
        selected = set(self.selected_paths())
        self.clear()
        self._items.clear()
        for path in paths:
            status, size, ratio, eta = snap.get(path, ("wait", None, None, ""))
            item = self._new_item(path, status or "wait", size)
            if ratio is not None:
                item.setData(ROLE_PROGRESS, ratio)
                item.setData(ROLE_ETA, eta)
            self.addItem(item)
            self._items[path] = item
            if path in selected:
                item.setSelected(True)
        self._emit_sel()
        self.viewport().update()

    def failed_paths(self) -> list[str]:
        return [p for p in self.paths() if self.status_of(p) == "fail"]

    # ------------------------------------------------------------------ istisnalar
    def overrides_for(self, path: str) -> dict:
        return self._overrides.get(path, {})

    def overrides(self) -> dict[str, dict]:
        """{yol: {'video_res'|'image_res'|'fps'|'remove_audio': etiket, 'trim': (bas, bit, sure)}}
        — yalnızca kuyruktaki dosyalar."""
        return {p: dict(ov) for p, ov in self._overrides.items() if ov and p in self._items}

    def set_override(self, paths: list[str], key: str, label: str | None) -> None:
        """`label` None ise o ayarın istisnası kaldırılır (genel ayar geçerli olur)."""
        for path in paths:
            if key in VIDEO_ONLY_KEYS and not is_video(path):
                continue
            if key == "image_res" and is_video(path):
                continue
            ov = self._overrides.setdefault(path, {})
            if label is None:
                ov.pop(key, None)
            else:
                ov[key] = label
            if not ov:
                self._overrides.pop(path, None)
            item = self._items.get(path)
            if item is not None:
                item.setToolTip(self._tooltip(path))
        self.viewport().update()
        self.overrides_changed.emit()

    def clear_overrides(self, paths: list[str]) -> None:
        for path in paths:
            self._overrides.pop(path, None)
            item = self._items.get(path)
            if item is not None:
                item.setToolTip(self._tooltip(path))
        self.viewport().update()
        self.overrides_changed.emit()

    def _tooltip(self, path: str) -> str:
        label = override_label(self._overrides.get(path, {}), self.lang)
        return f"{path}\n{t('ovr_tooltip', self.lang).format(label)}" if label else path

    # ------------------------------------------------------------------ sürükle-bırak
    def _drop_target(self, point: QPoint) -> tuple[int, bool]:
        """(hedef öğe sırası, sonrasına mı). Boş alana bırakılırsa en sona."""
        index = self.indexAt(point)
        if not index.isValid():
            return self.count() - 1, True
        rect = self.visualRect(index)
        after = point.x() > rect.center().x() if self.columns > 1 else point.y() > rect.center().y()
        return index.row(), after

    def _paint_drop_indicator(self, painter: QPainter) -> None:
        row, after = self._drop_at
        item = self.item(row)
        if item is None:
            return
        rect = self.visualItemRect(item)
        accent = QColor(self.colors["chip_text"])
        painter.setPen(QPen(accent, 3))
        if self.columns > 1:
            x = rect.right() if after else rect.left() + 1
            painter.drawLine(x, rect.top() + 4, x, rect.bottom() - 4)
        else:
            y = rect.bottom() if after else rect.top() + 1
            painter.drawLine(rect.left() + 6, y, rect.right() - 6, y)

    def dragEnterEvent(self, event: QDragEnterEvent):  # noqa: N802
        if self._locked or event.source() is not self:
            event.ignore()
            return
        event.acceptProposedAction()

    def dragMoveEvent(self, event: QDragMoveEvent):  # noqa: N802
        if self._locked or event.source() is not self:
            event.ignore()
            return
        self._drop_at = self._drop_target(event.position().toPoint())
        self.viewport().update()
        event.acceptProposedAction()

    def dragLeaveEvent(self, event):  # noqa: N802
        self._drop_at = None
        self.viewport().update()
        super().dragLeaveEvent(event)

    def dropEvent(self, event: QDropEvent):  # noqa: N802
        self._drop_at = None
        self.viewport().update()
        if self._locked or event.source() is not self:
            event.ignore()
            return
        moving = self.selected_paths()
        if not moving:
            event.ignore()
            return
        dest_row, after = self._drop_target(event.position().toPoint())
        order = self.paths()
        moving_set = set(moving)
        rest = [p for p in order if p not in moving_set]
        insert_at = len(rest)
        target = self.path_at(dest_row) if dest_row >= 0 else ""
        if target and target not in moving_set:
            insert_at = rest.index(target) + (1 if after else 0)
        elif dest_row >= 0:
            insert_at = sum(1 for p in order[:dest_row] if p not in moving_set)
        new_order = rest[:insert_at] + moving + rest[insert_at:]
        if new_order != order:
            self.apply_order(new_order)
        event.setDropAction(Qt.DropAction.CopyAction)  # öğeleri kendimiz taşıdık; Qt silmesin
        event.accept()

    # ------------------------------------------------------------------ etkileşim
    def _emit_sel(self):
        self.selection_count_changed.emit(len(self.selectedItems()))

    def _shortcut_remove(self):
        if self._locked:
            return
        paths = self.selected_paths()
        if paths:
            self.remove_requested.emit(paths)

    def keyPressEvent(self, event):  # noqa: N802
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self._shortcut_remove()
            event.accept()
            return
        super().keyPressEvent(event)

    def _dbl(self, item: QListWidgetItem):
        path = item.data(ROLE_PATH) or ""
        if path:
            self.preview_requested.emit(path)  # resim de video da önizlenir

    def _editable(self, paths: list[str]) -> list[str]:
        """İstisnası değiştirilebilecekler: iş yokken hepsi, iş sürerken yalnızca henüz başlamamışlar."""
        if not self._locked:
            return paths
        return [p for p in paths if self.status_of(p) == "wait"]

    def _override_menu(self, menu: QMenu, paths: list[str], icon: QIcon) -> None:
        editable = self._editable(paths)
        sub = menu.addMenu(icon, t("ovr_menu", self.lang))
        sub.setEnabled(bool(editable))
        videos = [p for p in editable if is_video(p)]
        images = [p for p in editable if not is_video(p)]

        def choice_menu(title_key: str, key: str, targets: list[str], display) -> None:
            if not targets:
                return
            m = sub.addMenu(t(title_key, self.lang))
            group = QActionGroup(m)
            group.setExclusive(True)
            current = {self._overrides.get(p, {}).get(key) for p in targets}
            same = current.pop() if len(current) == 1 else "__mixed__"
            default = QAction(t("ovr_default", self.lang), m)
            default.setCheckable(True)
            default.setChecked(same is None)
            default.triggered.connect(lambda _=False, k=key, ts=list(targets): self.set_override(ts, k, None))
            group.addAction(default)
            m.addAction(default)
            m.addSeparator()
            for label, _value in OVERRIDE_CHOICES[key]:
                act = QAction(display(label), m)
                act.setCheckable(True)
                act.setChecked(same == label)
                act.triggered.connect(lambda _=False, k=key, lb=label, ts=list(targets): self.set_override(ts, k, lb))
                group.addAction(act)
                m.addAction(act)

        def res_text(label: str) -> str:
            return t("res_original", self.lang) if label == ORIGINAL else label

        def fps_text(label: str) -> str:
            return t("fps_original", self.lang) if label == ORIGINAL else t("fps_value", self.lang).format(label)

        def audio_text(label: str) -> str:
            return t("ovr_audio_mute_option" if label == "mute" else "ovr_audio_keep_option", self.lang)

        choice_menu("ovr_video_res", "video_res", videos, res_text)
        choice_menu("ovr_image_res", "image_res", images, res_text)
        choice_menu("ovr_fps", "fps", videos, fps_text)
        choice_menu("ovr_audio", "remove_audio", videos, audio_text)
        trimmed = [p for p in videos if self._overrides.get(p, {}).get("trim")]
        if trimmed:
            untrim = QAction(t("trim_remove", self.lang), sub)
            untrim.triggered.connect(lambda _=False, ts=list(trimmed): self.set_override(ts, "trim", None))
            sub.addAction(untrim)
        if any(self._overrides.get(p) for p in editable):
            sub.addSeparator()
            clear = QAction(t("ovr_clear", self.lang), sub)
            clear.triggered.connect(lambda _=False, ts=list(editable): self.clear_overrides(ts))
            sub.addAction(clear)

    def _menu(self, pos: QPoint):
        item = self.itemAt(pos)
        if item is not None and not item.isSelected():
            self.clearSelection()
            item.setSelected(True)
            self.setCurrentItem(item)
        paths = self.selected_paths()
        if not paths:
            return
        self.build_menu(paths).exec(self.viewport().mapToGlobal(pos))

    def build_menu(self, paths: list[str]) -> QMenu:
        """Sağ tık menüsü (seçili dosyalar için)."""
        menu = QMenu(self)
        n = len(paths)
        # Her satırın simgesi var (yalnızca ikisinde olunca metinler iki farklı hizada başlıyordu).
        icon_color = getattr(self, "_menu_icon_color", icons.DEFAULT_ICON_COLOR)  # menü simgeleri vurguya uyar
        if not self._locked:
            rem_text = (
                t("queue_remove", self.lang) if n == 1
                else t("queue_remove_n", self.lang).format(n)
            )
            remove = QAction(icons.trash_icon(icon_color), rem_text, menu)
            remove.triggered.connect(lambda: self.remove_requested.emit(paths))
            menu.addAction(remove)
            menu.addSeparator()

        # Önizleme hem resim hem video için (pencere videodan kare seçerek karşılaştırır).
        preview_act = QAction(icons.eye_icon(icon_color), t("preview_btn", self.lang), menu)
        preview_act.triggered.connect(lambda: self.preview_requested.emit(paths[0]))
        menu.addAction(preview_act)
        # Kırpma tek videoya (başlangıç-bitiş her videoda farklıdır).
        if len(paths) == 1 and is_video(paths[0]):
            trim_act = QAction(icons.scissors_icon(icon_color), t("trim_menu", self.lang), menu)
            trim_act.setEnabled(bool(self._editable(paths)))
            trim_act.triggered.connect(lambda: self.trim_requested.emit(paths[0]))
            menu.addAction(trim_act)
        self._override_menu(menu, paths, icons.sliders_icon(icon_color))
        menu.addSeparator()

        reveal = QAction(icons.folder_icon(icon_color), t("reveal_in_folder", self.lang), menu)
        reveal.triggered.connect(lambda: self.reveal_requested.emit(paths[0]))
        menu.addAction(reveal)
        open_act = QAction(icons.open_external_icon(icon_color), t("open_file", self.lang), menu)
        open_act.triggered.connect(lambda: self.open_requested.emit(paths[0]))
        menu.addAction(open_act)
        return menu
