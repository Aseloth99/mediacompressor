"""Zaman kodu: saniye <-> "1:23.4" (kırpma penceresi ve kuyruk etiketleri)."""

from __future__ import annotations

import re
from typing import Optional


def clock(seconds: float, tenths: bool = False) -> str:
    """83.4 -> "1:23.4" (tenths) / "1:23"; saatlik videoda "1:02:03"."""
    seconds = max(0.0, float(seconds))
    whole = int(seconds)
    frac = seconds - whole
    if tenths:
        tenth = int(round(frac * 10))
        if tenth == 10:
            whole, tenth = whole + 1, 0
    h, rem = divmod(whole, 3600)
    m, s = divmod(rem, 60)
    text = f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"
    return f"{text}.{tenth}" if tenths else text


def parse_clock(text: str) -> Optional[float]:
    """"1:23.4", "1:23,4", "83.4", "1:02:03" -> saniye; geçersizse None."""
    text = str(text).strip().replace(",", ".")
    if not re.fullmatch(r"\d+(?::\d{1,2}){0,2}(?:\.\d*)?", text):
        return None
    parts = text.split(":")
    total = 0.0
    for part in parts[:-1]:
        total = total * 60 + int(part)
    try:
        last = float(parts[-1]) if parts[-1] not in ("", ".") else 0.0
    except ValueError:
        return None
    if len(parts) > 1 and last >= 60:
        return None
    return total * 60 + last if len(parts) > 1 else last
