# -*- coding: utf-8 -*-
"""Build sonrası EXE adını yerelleştirip ZIP paketler."""

import os
import time
import zipfile

from src.core.app_info import EXE_NAME

src = os.path.join("dist", "MediaCompressor.exe")
dst = os.path.join("dist", EXE_NAME)


def _try_remove(path: str, attempts: int = 12) -> bool:
    if not os.path.isfile(path):
        return True
    for _ in range(attempts):
        try:
            os.remove(path)
            return True
        except PermissionError:
            time.sleep(0.4)
        except OSError:
            time.sleep(0.4)
    return False


if not os.path.isfile(src) and not os.path.isfile(dst):
    raise SystemExit("dist içinde EXE bulunamadı.")

pack_from = dst
if os.path.isfile(src):
    if os.path.abspath(src) != os.path.abspath(dst):
        if os.path.isfile(dst) and not _try_remove(dst):
            print("UYARI: Eski 'Medya Sıkıştırıcı.exe' açık. ZIP mevcut yeni derlemeden oluşturulacak.")
            pack_from = src
        else:
            os.replace(src, dst)
            pack_from = dst
    else:
        pack_from = src

zip_path = os.path.join("dist", "MediaCompressor.zip")
with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
    archive.write(pack_from, EXE_NAME)

print(f"EXE: {dst if os.path.isfile(dst) else pack_from}")
print(f"ZIP: {zip_path}")
