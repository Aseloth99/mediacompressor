"""Platform tespiti — tek kaynak.

Tüm platforma bağımlı kod ``sys.platform`` yerine buradaki yardımcıları kullanır ve ``platform``
parametresini dışarıdan alabilir; böylece macOS/Linux/Windows dalları tek bir makinede (taklitle)
test edilebilir. Bu modül yalnızca standart kütüphaneyi kullanır ve import anında hiçbir
platforma özgü modül yüklemez.
"""

from __future__ import annotations

import sys

WINDOWS = "windows"
MACOS = "macos"
LINUX = "linux"
OTHER = "other"


def detect(platform: str | None = None) -> str:
    """``sys.platform`` (veya verilen değer) -> windows / macos / linux / other.

    ``"windows"``, ``"macos"``, ``"linux"`` gibi zaten normalleşmiş adlar da kabul edilir.
    """
    value = (sys.platform if platform is None else platform) or ""
    value = value.lower()
    if value in (WINDOWS, MACOS, LINUX):
        return value
    if value.startswith("win"):
        return WINDOWS
    if value.startswith("darwin"):
        return MACOS
    if value.startswith("linux"):
        return LINUX
    return OTHER


def is_windows(platform: str | None = None) -> bool:
    return detect(platform) == WINDOWS


def is_macos(platform: str | None = None) -> bool:
    return detect(platform) == MACOS


def is_linux(platform: str | None = None) -> bool:
    return detect(platform) == LINUX


def is_posix(platform: str | None = None) -> bool:
    """Windows dışındaki her şey (macOS, Linux, BSD...)."""
    return detect(platform) != WINDOWS
