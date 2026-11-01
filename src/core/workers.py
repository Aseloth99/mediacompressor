"""Arka plan işçileri ve güvenli kapanış yardımcıları.

``QThread`` çalışırken yok edilirse Qt süreci "Destroyed while thread is still running"
ile çökertir. Burada işçiler daemon ``threading.Thread`` üzerinde çalışır: çıkışta
beklenmeyen (ör. ağ okumasında takılmış) bir iş süreci asla kilitlemez ve QThread
yıkım çökmesi mümkün olmaz. Sinyaller bir QObject'ten yayınlandığı için ana iş
parçacığına kuyruklanarak iletilir.
"""

from __future__ import annotations

import threading
import time
from typing import Callable, Iterable, Optional

from PyQt6.QtCore import QObject, pyqtSignal

from ..utils.logger import log_error


class DaemonWorker(QObject):
    """QThread benzeri arayüz (start / isRunning / wait / finished) — daemon thread üstünde."""

    finished = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._thread: Optional[threading.Thread] = None

    def run(self) -> None:  # alt sınıflar uygular
        raise NotImplementedError

    def start(self) -> None:
        if self.isRunning():
            return
        self._thread = threading.Thread(target=self._bootstrap, name=type(self).__name__, daemon=True)
        self._thread.start()

    def _bootstrap(self) -> None:
        try:
            self.run()
        except Exception as exc:  # noqa: BLE001 - işçi hatası uygulamayı düşürmesin
            log_error(f"{type(self).__name__} beklenmeyen hata", exc)
        finally:
            try:
                self.finished.emit()
            except RuntimeError:
                # QObject çıkış sırasında yok edilmiş olabilir.
                pass

    def isRunning(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive()

    def wait(self, msecs: Optional[int] = None) -> bool:
        """İş bitince True; süre dolarsa False (QThread.wait ile uyumlu)."""
        thread = self._thread
        if thread is None or not thread.is_alive():
            return True
        if thread is threading.current_thread():
            return False
        thread.join(None if msecs is None else max(0.0, msecs / 1000.0))
        return not thread.is_alive()


StopEntry = tuple[str, Optional[object], Callable[[], None]]


def shutdown_workers(entries: Iterable[StopEntry], timeout_ms: int = 8000) -> list[str]:
    """Güvenli kapanış: önce HEPSİNE durdurma isteği, sonra ortak süre bütçesiyle bekle.

    ``entries``: (ad, işçi veya None, durdurma_çağrısı). Süre dolduğunda hâlâ çalışanların
    adlarını döndürür; işçiler daemon olduğundan süreç yine de güvenle çıkabilir.
    """
    active = [(name, worker, stop) for name, worker, stop in entries
              if worker is not None and _is_running(worker)]
    for name, _worker, stop in active:
        try:
            stop()
        except Exception as exc:  # noqa: BLE001
            log_error(f"{name} durdurma isteği başarısız", exc)

    deadline = time.monotonic() + max(0, timeout_ms) / 1000.0
    still_running: list[str] = []
    for name, worker, _stop in active:
        remaining_ms = max(0, int((deadline - time.monotonic()) * 1000))
        try:
            finished = worker.wait(remaining_ms)  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001
            log_error(f"{name} beklenirken hata", exc)
            finished = False
        if not finished and _is_running(worker):
            still_running.append(name)
    return still_running


def _is_running(worker: object) -> bool:
    try:
        return bool(worker.isRunning())  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        return False
