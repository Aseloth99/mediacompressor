"""Kalan süre tahmini (src.core.eta): dosya sayısına değil iş miktarına göre, resim/video ayrı hızla.

Gerçek vaka (ekran görüntüsü): 84 dosya — 4 resim 23 sn'de bitti, 8.1 GB video 12 dk'da %33, kuyrukta 78 resim
ve 82 MB'lık bir video daha. Eski hesap "4.33/84 dosya bitti" deyip kalan ~3 sa 40 dk gösteriyordu.
"""

from __future__ import annotations

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from src.core.eta import JobEta, file_eta  # noqa: E402

MB = 1024 * 1024
GB = 1024 * MB


def _screenshot_job():
    files = [(f"a{i}.jpg", int(2.5 * MB)) for i in range(4)]
    files.append(("big.mp4", int(8.1 * GB)))
    files += [(f"b{i}.jpg", int(2.5 * MB)) for i in range(78)]
    files.append(("small.mp4", 82 * MB))
    eta = JobEta(files, now=0.0)
    for i in range(4):  # resimler paralel: aynı anda başlar
        eta.started(f"a{i}.jpg", 0.0)
    for i in range(4):
        eta.finished(f"a{i}.jpg", "ok", 23.0)
    eta.started("big.mp4", 23.0)
    return eta


class JobEtaTest(unittest.TestCase):
    def test_screenshot_case_is_about_half_an_hour_not_four_hours(self):
        eta = _screenshot_job()
        eta.progress("big.mp4", 0.33, 23.0 + 697.0)  # 12 dk sonra
        remaining = eta.remaining()
        self.assertIsNotNone(remaining)
        # video: kalan %67 ≈ 23.6 dk, küçük video ≈ 20 sn, 78 resim ≈ 7.5 dk -> ~31 dk
        self.assertGreater(remaining, 25 * 60)
        self.assertLess(remaining, 38 * 60)
        self.assertGreater(eta.fraction(), 0.2, "genel ilerleme dosya sayısı değil iş payı olmalı (%4 değil)")

    def test_nothing_is_shown_before_one_percent(self):
        files = [("v.mp4", 1 * GB)]
        eta = JobEta(files, now=0.0)
        eta.started("v.mp4", 0.0)
        eta.progress("v.mp4", 0.005, 10.0)
        self.assertIsNone(eta.remaining())
        eta.progress("v.mp4", 0.02, 40.0)
        self.assertAlmostEqual(eta.remaining(), 40.0 / 0.02 - 40.0, delta=1.0)

    def test_skipped_files_do_not_slow_the_measured_rate(self):
        files = [(f"i{i}.jpg", 4 * MB) for i in range(10)]
        eta = JobEta(files, now=0.0)
        for i in range(5):  # zaten var: anında atlanır
            eta.started(f"i{i}.jpg", 0.0)
            eta.finished(f"i{i}.jpg", "skip", 0.0)
        eta.started("i5.jpg", 0.0)
        eta.finished("i5.jpg", "ok", 4.0)  # 4 MB / 4 sn
        self.assertAlmostEqual(eta.remaining(), 4 * 4.0, delta=0.5)

    def test_unmeasured_kind_borrows_the_other_rate_until_it_starts(self):
        files = [("i.jpg", 10 * MB), ("v.mp4", 10 * MB)]
        eta = JobEta(files, now=0.0)
        eta.started("i.jpg", 0.0)
        eta.finished("i.jpg", "ok", 10.0)  # 1 MB/sn
        self.assertAlmostEqual(eta.remaining(), 10.0, delta=0.5)
        eta.started("v.mp4", 10.0)
        eta.progress("v.mp4", 0.5, 11.0)  # ilk saniye: henüz kendi hızı ölçülmedi, ödünç hız
        self.assertAlmostEqual(eta.remaining(), 5.0, delta=0.3)
        eta.progress("v.mp4", 0.5, 12.0)  # 2 sn ölçüm: video çok daha hızlı (5 MB / 2 sn)
        self.assertAlmostEqual(eta.remaining(), 2.0, delta=0.3)

    def test_fraction_is_monotonic_with_steady_rates(self):
        eta = _screenshot_job()
        last = eta.fraction()
        for step in range(1, 30):
            eta.progress("big.mp4", step / 30, 23.0 + step * 60.0)
            now = eta.fraction()
            self.assertGreaterEqual(now + 1e-9, last)
            last = now

    def test_file_eta(self):
        self.assertIsNone(file_eta(30.0, 0.005))
        self.assertIsNone(file_eta(1.0, 0.5), "çok erken")
        self.assertAlmostEqual(file_eta(60.0, 0.25), 180.0)


if __name__ == "__main__":
    unittest.main()
