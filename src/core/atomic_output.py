"""Atomik çıktı yardımcıları.

Çıktılar önce ``ad.mcpart.uzantı`` biçiminde geçici bir dosyaya yazılır; yalnızca
işlem başarılı olursa ``os.replace`` ile asıl ada taşınır. Böylece yarım kalmış
(çökme, iptal, disk dolu) bir dosya hiçbir zaman "zaten mevcut" sayılıp atlanmaz.

Geçici adın uzantısı korunur: ffmpeg çıktı biçimini uzantıdan, Pillow ise kayıt
biçimini (uzantısız çağrıldığında) uzantıdan çıkarır. İşaretçi bilerek ``.tmp``
değil ``.mcpart`` seçildi; kullanıcının meşru bir ``x.tmp.mp4`` dosyası süpürülmesin.
"""

from __future__ import annotations

import os

PART_MARKER = ".mcpart"

# Video ve resim sıkıştırıcılarının iptal sonucu olarak döndürdüğü ortak değer.
CANCELLED = "iptal"


def temp_path_for(dst: str) -> str:
    """``klasor/ad.mp4`` -> ``klasor/ad.mcpart.mp4`` (uzantı korunur)."""
    root, ext = os.path.splitext(dst)
    return f"{root}{PART_MARKER}{ext}"


def is_partial_name(name: str) -> bool:
    """Dosya adı (veya yolu) bu modülün geçici dosya biçiminde mi?"""
    root, _ = os.path.splitext(os.path.basename(name))
    return root.endswith(PART_MARKER)


def discard_temp(path: str) -> None:
    """Geçici dosyayı sessizce sil (yoksa sorun değil)."""
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


def commit_temp(tmp: str, dst: str) -> None:
    """Geçici dosyayı asıl ada atomik olarak taşı (varsa üzerine yazar)."""
    os.replace(tmp, dst)


def sweep_partial_files(folder: str) -> int:
    """Çıktı klasöründe (alt klasörler dahil) kalmış eski geçici dosyaları sil.

    Dönen değer: silinen dosya sayısı. Klasör yoksa 0.
    """
    removed = 0
    if not folder or not os.path.isdir(folder):
        return 0
    for current, _dirs, files in os.walk(folder):
        for name in files:
            if is_partial_name(name):
                path = os.path.join(current, name)
                discard_temp(path)
                if not os.path.exists(path):
                    removed += 1
    return removed
