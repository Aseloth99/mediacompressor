"""İş süresi tahmini: dosya SAYISINA göre değil, iş MİKTARINA (bayt) göre; resim ve video ayrı hızla.

Eskiden kalan süre "biten dosya / toplam dosya" oranından çıkarılıyordu: 4 resim 23 sn'de bitip 8 GB'lık
video 12 dk'da %33'e geldiğinde iş %5 bitmiş sayılıyor ve kalan ~3 sa 40 dk gösteriliyordu (gerçekte ~35 dk).

Model: her tür (resim / video) için ölçülen hız = işlenen bayt / o türün çalıştığı duvar saati süresi
(resimler paralel işlendiği için paralellik hıza kendiliğinden yansır; video ilerlemesi oranla sayılır).
Kalan süre = Σ tür kalan baytı / tür hızı. Henüz hiç ölçülmemiş türün kalanı ölçülmüş türün hızıyla kabaca
tahmin edilir; o tür başlayınca kendi hızıyla düzelir.
"""

from __future__ import annotations

from pathlib import Path

from .image_compressor import IMAGE_EXTS

IMAGE, VIDEO = "image", "video"
MIN_FRACTION = 0.01  # ilk %1 bitmeden kalan süre gösterilmez (kullanıcı isteği)
MIN_MEASURED_SECONDS = 2.0  # ve en az bu kadar ölçüm olmalı (ilk saniyelerin gürültüsü)


def kind_of(path: str) -> str:
    return IMAGE if Path(path).suffix.lower() in IMAGE_EXTS else VIDEO


def file_eta(elapsed: float, ratio: float) -> float | None:
    """Tek dosyanın (video) kalan süresi; %1'den önce ya da çok erken ise None."""
    if ratio < MIN_FRACTION or elapsed < MIN_MEASURED_SECONDS or ratio <= 0:
        return None
    return max(0.0, elapsed / ratio - elapsed)


class JobEta:
    def __init__(self, files: list[tuple[str, int]], now: float):
        """`files`: (yol, bayt) listesi (kuyruk sırası)."""
        self._size: dict[str, int] = {}
        self._kind: dict[str, str] = {}
        self._total = {IMAGE: 0, VIDEO: 0}
        for path, size in files:
            k = kind_of(path)
            s = max(1, int(size or 0))
            self._size[path] = s
            self._kind[path] = k
            self._total[k] += s
        self._finished = {IMAGE: 0, VIDEO: 0}  # bitmiş/atlanmış/başarısız (artık iş yok)
        self._processed = {IMAGE: 0, VIDEO: 0}  # gerçekten işlenmiş (hız ölçümü; atlananlar hariç)
        self._busy = {IMAGE: 0.0, VIDEO: 0.0}  # o türün çalıştığı duvar saati
        self._active: dict[str, float] = {}  # sürmekte olan dosya -> oran (resimlerde 0)
        self._kind_now: str | None = None
        self._last = now
        self._t0 = now

    # ------------------------------------------------------------------ olaylar
    def _tick(self, now: float) -> None:
        if self._kind_now is not None and now > self._last:
            self._busy[self._kind_now] += now - self._last
        self._last = max(self._last, now)

    def started(self, path: str, now: float) -> None:
        self._tick(now)
        self._kind_now = self._kind.get(path, kind_of(path))
        self._active[path] = 0.0

    def progress(self, path: str, ratio: float, now: float) -> None:
        self._tick(now)
        if path in self._active:
            self._active[path] = max(0.0, min(1.0, float(ratio)))

    def finished(self, path: str, status: str, now: float) -> None:
        self._tick(now)
        self._active.pop(path, None)
        k = self._kind.get(path, kind_of(path))
        size = self._size.get(path, 1)
        self._finished[k] += size
        if status in ("ok", "fail"):
            self._processed[k] += size

    # ------------------------------------------------------------------ hesap
    def _in_progress(self, k: str) -> float:
        return sum(self._size.get(p, 1) * r for p, r in self._active.items() if self._kind.get(p) == k)

    def _rate(self, k: str) -> float | None:
        """bayt/sn; yeterli ölçüm yoksa None."""
        busy = self._busy[k]
        work = self._processed[k] + self._in_progress(k)
        if busy < MIN_MEASURED_SECONDS or work <= 0:
            return None
        return work / busy

    def _remaining_bytes(self, k: str) -> float:
        return max(0.0, self._total[k] - self._finished[k] - self._in_progress(k))

    def _rates(self) -> dict[str, float | None]:
        rates = {k: self._rate(k) for k in (IMAGE, VIDEO)}
        known = [r for r in rates.values() if r]
        for k in rates:
            if rates[k] is None and known:
                rates[k] = known[0]  # henüz ölçülmemiş tür: diğerinin hızıyla kaba tahmin
        return rates

    def fraction(self) -> float:
        """Bitmiş işin payı (0..1), süreye göre ağırlıklı; hız yoksa bayta göre."""
        rates = self._rates()
        done = total = 0.0
        for k in (IMAGE, VIDEO):
            if not self._total[k]:
                continue
            weight = 1.0 / rates[k] if rates[k] else 1.0
            done += (self._finished[k] + self._in_progress(k)) * weight
            total += self._total[k] * weight
        return min(1.0, done / total) if total else 0.0

    def remaining(self) -> float | None:
        """Kalan saniye; ilk %1'den önce ya da hiç ölçüm yoksa None."""
        if self.fraction() < MIN_FRACTION:
            return None
        rates = self._rates()
        seconds = 0.0
        for k in (IMAGE, VIDEO):
            left = self._remaining_bytes(k)
            if left <= 0:
                continue
            if not rates[k]:
                return None
            seconds += left / rates[k]
        return seconds
