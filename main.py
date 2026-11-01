"""Medya Sıkıştırıcı"""

from __future__ import annotations

import os
import sys
import tempfile
import time

# Proje kökünü path'e ekle
ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _fix_cwd():
    # Kaynak dosyalar için CWD = uygulama klasörü. Ayarlar kullanıcı dizinine yazılır.
    if getattr(sys, "frozen", False):
        os.chdir(os.path.dirname(sys.executable))
    else:
        os.chdir(ROOT)


def _dpi():
    try:
        import ctypes
        try:
            ctypes.windll.user32.SetProcessDpiAwarenessContext(-4)
        except Exception:
            try:
                ctypes.windll.shcore.SetProcessDpiAwareness(2)
            except Exception:
                ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def _set_app_id():
    if sys.platform != "win32":
        return
    try:
        import ctypes
        set_app_id = ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID
        set_app_id.argtypes = [ctypes.c_wchar_p]
        set_app_id.restype = ctypes.HRESULT
        set_app_id("MediaCompressor.App")
    except Exception:
        pass


def _try_raise_existing() -> bool:
    from PyQt6.QtNetwork import QLocalSocket
    from src.core.app_info import SOCKET_NAME
    sock = QLocalSocket()
    sock.connectToServer(SOCKET_NAME)
    if sock.waitForConnected(250):
        sock.write(b"raise")
        sock.waitForBytesWritten(250)
        sock.disconnectFromServer()
        return True
    return False


def main():
    from src.utils.crashlog import install_crash_log
    install_crash_log()

    _fix_cwd()

    # Güncelleme sonrası yeniden başlatma (`--wait-pid`): önceki süreç çıkana kadar bekle; tek kopya kilidi ve tepsi
    # simgesi çakışmasın. Kilit/QApplication'dan ÖNCE olmalı.
    from src.utils import self_update
    self_update.wait_for_previous_instance(sys.argv)
    frozen = bool(getattr(sys, "frozen", False))
    updated_from = self_update.updated_from(sys.argv)
    show_window = self_update.wants_window(sys.argv)
    started_at = time.monotonic()

    # Oturum açılışındaki `--minimized` kabuğun (tepsi) hazır olmasını bekler; güncelleme yeniden başlatmasında gerekmez.
    if "--minimized" in sys.argv and not self_update.flag_value(sys.argv, "--wait-pid"):
        time.sleep(2)
    if sys.platform == "win32":
        _dpi()
        _set_app_id()

    from PyQt6.QtCore import Qt, QLockFile, QTimer
    from PyQt6.QtGui import QIcon
    from PyQt6.QtNetwork import QLocalServer
    from PyQt6.QtWidgets import QApplication

    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    from src.core.app_info import APP_NAME, LOCK_NAME, ORGANIZATION, SOCKET_NAME, VERSION
    from src.gui.main_window import MainWindow
    from src.utils.config import Config
    from src.utils.helpers import resource_path
    from src.utils.logger import log_info
    from src.utils.startup import is_in_startup, update_startup_path_if_needed
    from src.utils.theme_manager import DEFAULT_ACCENT, ThemeManager
    from src.utils.update_installer import UpdateInstaller
    from src.utils.updater import UpdateChecker

    lock_path = os.path.join(tempfile.gettempdir(), LOCK_NAME)
    lock = QLockFile(lock_path)
    lock.setStaleLockTime(10000)
    if not lock.tryLock(100):
        if _try_raise_existing():
            return 0
        lock.removeStaleLockFile()
        if not lock.tryLock(100):
            return 0  # çalışan kopya öne alınamadı: kutu açmadan sessizce çık (ikinci başlatma kullanıcıyı bölmesin)

    # Güncellemeden sonraki ilk açılışlar "deneme"dir: yeni sürüm iki kez açılışta ölürse eskisi geri gelir. Tek kopya
    # kilidi alındıktan SONRA çalışır: kilide takılıp çıkan ikinci başlatmalar (çift tık) "açılış" sayılıp ÇALIŞAN
    # sağlam yeni sürümü geri aldırmasın.
    if frozen and self_update.startup_guard(sys.executable, VERSION) == self_update.Guard.ROLLED_BACK:
        log_info("Yeni sürüm açılışta çalışmadı: önceki sürüm geri getirildi ve yeniden başlatılıyor")
        lock.unlock()  # eski sürüm kilidi alabilsin
        try:
            self_update.spawn(sys.executable, ["--minimized"])
        except self_update.PackageError as exc:
            log_info(f"Önceki sürüm başlatılamadı: {exc}")
        return 0

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(VERSION)
    app.setOrganizationName(ORGANIZATION)
    for effect in (
        Qt.UIEffect.UI_AnimateCombo,
        Qt.UIEffect.UI_AnimateMenu,
        Qt.UIEffect.UI_FadeMenu,
        Qt.UIEffect.UI_AnimateTooltip,
    ):
        app.setEffectEnabled(effect, False)
    icon_path = resource_path("assets", "icons", "app_icon.png")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    QLocalServer.removeServer(SOCKET_NAME)
    server = QLocalServer()
    server.listen(SOCKET_NAME)

    config = Config()
    theme = ThemeManager(app)
    theme.apply_from_setting(config.get("theme", "system"), config.get("accent", DEFAULT_ACCENT))

    if config.get("start_with_windows") or is_in_startup():
        update_startup_path_if_needed(minimized=True)

    updater = UpdateChecker(config)
    installer = UpdateInstaller()
    if frozen:
        # Yeni sürüm kendini kanıtlayınca (60 sn çalıştı ya da temiz çıktı) güncellemenin bıraktığı `.old` silinir.
        # Kendini güncelleyip çıkan süreç bunu YAPMAZ: yan dosyalar yeni sürümün denemesine aittir.
        exe_path = sys.executable

        def _confirm_healthy():
            if not installer.relaunching:
                self_update.confirm_healthy(exe_path)

        QTimer.singleShot(self_update.HEALTHY_AFTER_SECONDS * 1000, _confirm_healthy)
        app.aboutToQuit.connect(lambda: _confirm_healthy() if time.monotonic() - started_at >= 10 else None)
    window = MainWindow(config, theme, updater, installer)

    def _on_second():
        conn = server.nextPendingConnection()
        if conn:
            conn.disconnected.connect(conn.deleteLater)
            conn.readyRead.connect(lambda: window.raise_requested.emit())
            window.raise_requested.emit()

    server.newConnection.connect(_on_second)

    # `--show-window`: güncelleme öncesi pencere açıktı, yeni sürüm de açık başlar ("simge durumunda başlat"ı geçersiz kılar).
    if "--minimized" in sys.argv and not show_window:
        if window._ensure_tray():
            window.hide()
        else:
            window.showMinimized()  # sistem tepsisi yok: pencere gizlenirse kullanıcı ona ulaşamaz
    else:
        window.show()

    if updated_from is not None:
        QTimer.singleShot(1500, lambda: window.show_updated_notice(updated_from))
    QTimer.singleShot(2500, updater.start)
    log_info(f"{APP_NAME} {VERSION} başlatıldı")
    code = app.exec()
    lock.unlock()
    return code


if __name__ == "__main__":
    sys.exit(main())
