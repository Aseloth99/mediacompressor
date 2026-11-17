"""GERÇEK platformda (offscreen DEĞİL) kuyruk başlığı sığma denetimi: pencere x=-6000'de gösterilir, ekranda görünmez.

test_progress_rows.RealPlatformHeaderFit tarafından alt süreç olarak çalıştırılır; sorun yoksa son satır "FIT-OK" olur.
Offscreen'de yazı tipi yoktur (her harf 13 px'lik kutu), bu yüzden genişlik ölçümü yalnızca burada anlamlıdır.
"""
import os
import sys
import tempfile

SANDBOX = tempfile.mkdtemp(prefix="mc_header_fit_")
for name in ("APPDATA", "LOCALAPPDATA"):
    os.environ[name] = SANDBOX
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from copy import deepcopy  # noqa: E402
from unittest import mock  # noqa: E402

from PyQt6.QtCore import QEventLoop, QTimer  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

app = QApplication([])
if app.platformName() == "offscreen":
    print("gerçek platform gerekir")
    os._exit(3)

from src.gui.main_window import MainWindow  # noqa: E402
from src.utils.config import DEFAULTS, Config  # noqa: E402
from src.utils.theme_manager import ThemeManager  # noqa: E402


def wait(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


problems = []
for lang in ("tr", "en"):
    cfg = object.__new__(Config)
    cfg.path, cfg._seed_path, cfg.data = "", None, deepcopy(DEFAULTS)
    cfg.save = lambda *a, **k: None
    cfg.data.update(show_notifications=False, language=lang)
    theme = ThemeManager(app)
    theme.apply_from_setting("dark")
    with mock.patch.object(MainWindow, "_prepare_ffmpeg", lambda *a, **k: None):
        w = MainWindow(cfg, theme, mock.MagicMock(), mock.MagicMock())
    paths = []
    for i in range(2):
        path = os.path.join(SANDBOX, f"f{i}.mp4")
        with open(path, "wb") as f:
            f.write(b"\0" * 64)
        paths.append(path)
    w.queue.set_files(paths)
    w.move(-6000, 0)
    w.show()
    w.resize(w.minimumSize())
    w.retry_btn.show()
    w._update_queue_actions()
    wait(300)
    for btn in (w.panel_toggle, w.retry_btn, w.remove_btn, w.clear_btn, w.log_toggle):
        if btn.width() < btn.minimumSizeHint().width():
            problems.append(f"{lang} {btn.text()!r}: {btn.width()} < {btn.minimumSizeHint().width()}")
    if w.queue_title.width() < w.queue_title.sizeHint().width():
        problems.append(f"{lang} başlık: {w.queue_title.width()} < {w.queue_title.sizeHint().width()}")
    w.close()

for line in problems:
    print(line)
print("FIT-OK" if not problems else "FIT-FAIL", flush=True)
os._exit(0)
