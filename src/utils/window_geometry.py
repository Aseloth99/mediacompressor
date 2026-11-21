"""Pencere konum/boyutunu hatırlama: kaydedilen dikdörtgeni şu anki ekranlara sığdırır (Qt'siz, saf hesap).

Monitör çıkarılmış, çözünürlük küçülmüş ya da ayar dosyası elle bozulmuş olabilir: pencere hiçbir zaman görünmeyen bir
yere ya da ekrandan büyük açılmaz. Dikdörtgenler (x, y, genişlik, yükseklik) dörtlüleridir; ekranlar "kullanılabilir
alan" (görev çubuğu hariç), ilki birincil ekran sayılır.
"""

from __future__ import annotations

Rect = tuple[int, int, int, int]

MIN_VISIBLE = 120  # kaydedilen ekranda bu kadarı görünmüyorsa (ör. monitör çıkarıldı) birincil ekranda ortalanır


def parse_saved(value) -> tuple[Rect, bool] | None:
    """Ayardaki {"x","y","w","h","maximized"} kaydını okur; eksik/bozuksa None."""
    if not isinstance(value, dict):
        return None
    try:
        rect = (int(value["x"]), int(value["y"]), int(value["w"]), int(value["h"]))
    except (KeyError, TypeError, ValueError):
        return None
    if rect[2] <= 0 or rect[3] <= 0:
        return None
    return rect, bool(value.get("maximized"))


def _overlap(a: Rect, b: Rect) -> tuple[int, int]:
    w = min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0])
    h = min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1])
    return max(0, w), max(0, h)


def fit_to_screens(rect: Rect, screens: list[Rect], min_size: tuple[int, int] = (0, 0)) -> Rect:
    """`rect`'i en çok örtüştüğü ekrana tamamen sığacak biçimde kaydırır/küçültür."""
    screens = [s for s in screens if s[2] > 0 and s[3] > 0]
    if not screens:
        return rect
    best, best_area = None, 0
    for screen in screens:
        w, h = _overlap(rect, screen)
        if w * h > best_area:
            best, best_area = screen, w * h
    x, y, width, height = rect
    if best is not None:
        vis_w, vis_h = _overlap(rect, best)
        if vis_w < min(MIN_VISIBLE, width) or vis_h < min(MIN_VISIBLE // 3, height):
            best = None
    center = best is None
    screen = best or screens[0]
    sx, sy, sw, sh = screen
    width = max(min(width, sw), min(min_size[0], sw))
    height = max(min(height, sh), min(min_size[1], sh))
    if center:
        x = sx + (sw - width) // 2
        y = sy + (sh - height) // 2
    x = min(max(x, sx), sx + sw - width)
    y = min(max(y, sy), sy + sh - height)
    return x, y, width, height
