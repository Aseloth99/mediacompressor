"""Arayüz cilası: menüden sonra takılı hover, görev çubuğu ilerlemesi, "Geri Al" toast'u, yumuşatılmış kalan süre,
sürükleme vurgusu, bitişte kazanılan yer, imleçler, kısayollar, pencere konumunu hatırlama, kayan duyuru satırı."""

from __future__ import annotations

import os
import pathlib
import sys
import tempfile
import time
import unittest
from copy import deepcopy
from unittest import mock

sys.path.insert(0, os.path.dirname(__file__))
import _support  # noqa: E402,F401  (gerçek kullanıcı profiline yazılmasın)

from PyQt6.QtCore import QEvent, QMimeData, QPoint, QPointF, QRect, Qt, QTimer, QUrl  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtGui import QCursor, QDragEnterEvent, QDropEvent, QKeySequence, QShortcut  # noqa: E402
from PyQt6.QtWidgets import QApplication, QDialog, QPushButton  # noqa: E402

from src.core.eta import EtaSmoother, round_eta  # noqa: E402
from src.gui import anim  # noqa: E402
from src.gui import main_window as mw  # noqa: E402
from src.gui.main_window import MainWindow  # noqa: E402
from src.utils import taskbar  # noqa: E402
from src.utils.config import DEFAULTS, Config  # noqa: E402
from src.utils.helpers import format_eta  # noqa: E402
from src.utils.theme_manager import ThemeManager  # noqa: E402
from src.utils.window_geometry import fit_to_screens, parse_saved  # noqa: E402


def _memory_config(**values) -> Config:
    cfg = object.__new__(Config)
    cfg.path, cfg._seed_path, cfg.data = "", None, deepcopy(DEFAULTS)
    cfg.data.update({"language": "tr", "show_notifications": True})
    cfg.data.update(values)
    cfg.save = lambda *a, **k: None
    return cfg


class _FakeBackend:
    def __init__(self):
        self.calls: list[tuple] = []

    def set_value(self, hwnd, done, total):
        self.calls.append(("value", hwnd, done, total))

    def set_state(self, hwnd, state):
        self.calls.append(("state", hwnd, state))


class _Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def make_window(self, **config) -> MainWindow:
        theme = ThemeManager(self.app)
        theme.apply_from_setting("dark")
        with mock.patch.object(MainWindow, "_prepare_ffmpeg", lambda *a, **k: None):
            w = MainWindow(_memory_config(**config), theme, mock.MagicMock(), mock.MagicMock())
        w._quitting = True  # closeEvent tepsiye gizlemesin, gerçekten kapansın
        self.addCleanup(w.deleteLater)
        self.addCleanup(lambda: mw.MainWindow._shutdown_background(w))
        w.show()
        self.app.processEvents()
        return w

    def make_files(self, *names: str) -> list[str]:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        paths = []
        for name in names:
            p = pathlib.Path(tmp.name) / name
            p.write_bytes(b"x" * 4096)
            paths.append(str(p))
        return paths


# ------------------------------------------------------------------------------------------- 1. hover
class HoverSettleTests(_Base):
    def _enter(self, widget) -> None:
        widget.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, True)
        QApplication.sendEvent(widget, QEvent(QEvent.Type.Enter))

    def _close_popup_soon(self) -> None:
        def close():
            popup = self.app.activePopupWidget()
            if popup is not None:
                popup.close()
            else:
                QTimer.singleShot(20, close)

        QTimer.singleShot(50, close)

    def test_helper_clears_stale_hover_only_when_the_cursor_left(self):
        from src.gui.hover_fix import settle_hover

        btn = QPushButton("x")
        btn.resize(40, 30)
        btn.show()
        self.addCleanup(btn.deleteLater)
        self.app.processEvents()
        self._enter(btn)
        QCursor.setPos(btn.mapToGlobal(QPoint(5000, 5000)))
        settle_hover(btn)
        self.assertFalse(btn.underMouse())
        settle_hover(None)  # sessizce geçer

    def test_title_bar_menu_buttons_do_not_stay_hovered_after_the_menu_closes(self):
        w = self.make_window()
        bar = w.title_bar
        for btn in (bar.file_btn, bar.theme_btn, bar.lang_btn, bar.color_btn):
            self._enter(btn)
            QCursor.setPos(w.mapToGlobal(QPoint(w.width() // 2, w.height() - 40)))  # menü dışında boş bir yer
            self._close_popup_soon()
            btn.showMenu()  # Qt sürümüne göre exec (bloklar) ya da popup (hemen döner)
            deadline = time.monotonic() + 3.0
            while (self.app.activePopupWidget() is not None or btn.menu().isVisible()) and time.monotonic() < deadline:
                QTest.qWait(10)
            self.assertIsNone(self.app.activePopupWidget(), "menü açıldı ve kapandı")
            QTest.qWait(20)
            self.assertFalse(btn.underMouse(), f"{btn.text()}: menü kapandıktan sonra hover kalmamalı")

    def test_queue_context_menu_settles_the_row_hover(self):
        from src.gui import queue_panel

        w = self.make_window()
        w._add_sources(self.make_files("a.jpg"))
        with mock.patch.object(queue_panel, "settle_hover") as settle, \
                mock.patch.object(queue_panel.QMenu, "exec", lambda *a, **k: None):
            w.queue._menu(w.queue.visualItemRect(w.queue.item(0)).center())
        settle.assert_called_once_with(w.queue.viewport())


# ------------------------------------------------------------------------------------------- 2. görev çubuğu
class TaskbarProgressTests(unittest.TestCase):
    def _bar(self, hwnd=42):
        backend = _FakeBackend()
        return taskbar.TaskbarProgress(lambda: hwnd, enabled=True, backend_factory=lambda: backend), backend

    def test_fraction_sets_normal_state_and_value_once(self):
        bar, backend = self._bar()
        bar.set_fraction(0.25)
        bar.set_fraction(0.25)  # aynı değer: COM'a tekrar gidilmez
        self.assertEqual(backend.calls, [("state", 42, taskbar.NORMAL), ("value", 42, 250, 1000)])
        bar.set_state(taskbar.PAUSED)
        bar.set_fraction(0.5)  # duraklatılmışken değer değişir, durum sarı kalır
        self.assertEqual(bar.state, taskbar.PAUSED)
        bar.clear()
        self.assertEqual(backend.calls[-1], ("state", 42, taskbar.NO_PROGRESS))

    def test_no_window_or_broken_com_is_silent(self):
        bar, backend = self._bar(hwnd=0)
        bar.set_fraction(0.5)
        self.assertEqual(backend.calls, [])

        def boom():
            raise OSError("no COM")

        broken = taskbar.TaskbarProgress(lambda: 5, enabled=True, backend_factory=boom)
        broken.set_fraction(0.3, taskbar.ERROR)
        broken.clear()  # istisna yok

    def test_disabled_off_windows(self):
        bar = taskbar.TaskbarProgress(lambda: 5, enabled=False, backend_factory=lambda: self.fail("çağrılmamalı"))
        bar.set_fraction(0.5)

    @unittest.skipUnless(sys.platform == "win32", "ITaskbarList3 yalnızca Windows'ta")
    def test_real_com_object_can_be_created_and_released(self):
        com = taskbar._ComTaskbar()
        com.release()


class TaskbarMirroringTests(_Base):
    def _window_with_fake_taskbar(self):
        w = self.make_window()
        backend = _FakeBackend()
        w._taskbar = taskbar.TaskbarProgress(lambda: 7, enabled=True, backend_factory=lambda: backend)
        return w, backend

    def test_overall_progress_is_mirrored(self):
        from src.core.eta import JobEta

        w, backend = self._window_with_fake_taskbar()
        w._job_t0 = time.time() - 10
        w._eta = JobEta([("a.jpg", 100), ("b.jpg", 100)], w._job_t0)
        w._eta.started("a.jpg", w._job_t0)
        w._eta.finished("a.jpg", "ok", w._job_t0 + 5)
        w._refresh_job_stats()
        self.assertEqual(w._taskbar.state, taskbar.NORMAL)
        self.assertEqual(w._taskbar.value, round(w._eta.fraction() * 1000))

    def test_failed_job_turns_red_until_the_window_is_seen_and_alerts_when_in_background(self):
        w, backend = self._window_with_fake_taskbar()
        with mock.patch.object(w, "isActiveWindow", return_value=False), \
                mock.patch.object(mw.QApplication, "alert") as alert, \
                mock.patch.object(w.notifier, "notify", return_value=True):
            w._announce_job_finished(cancelled=False, failed=2, saved=0)
        alert.assert_called_once_with(w)
        self.assertEqual(w._taskbar.state, taskbar.ERROR)
        with mock.patch.object(w, "isActiveWindow", return_value=True):
            w.changeEvent(QEvent(QEvent.Type.ActivationChange))
        self.assertEqual(w._taskbar.state, taskbar.NO_PROGRESS)

    def test_successful_job_clears_the_taskbar(self):
        w, backend = self._window_with_fake_taskbar()
        w._taskbar.set_fraction(0.7)
        with mock.patch.object(w, "isActiveWindow", return_value=True), \
                mock.patch.object(mw.QApplication, "alert") as alert:
            w._announce_job_finished(cancelled=False, failed=0, saved=1000)
        alert.assert_not_called()
        self.assertEqual(w._taskbar.state, taskbar.NO_PROGRESS)


# ------------------------------------------------------------------------------------------- 3. geri al
class UndoToastTests(_Base):
    def test_removing_an_item_offers_undo_that_restores_order_and_overrides(self):
        w = self.make_window()
        a, b, c = self.make_files("a.jpg", "b.jpg", "c.jpg")
        w._add_sources([a, b, c])
        order = [c, a, b]
        w.queue.apply_order(order)
        w.queue.set_override([a], "image_res", "1920px")
        w._remove_from_queue([a])
        self.assertEqual(w.queue.paths(), [c, b])
        self.assertTrue(w.toast.is_showing())
        self.assertIn("a.jpg", w.toast.text())
        self.assertEqual(w.toast.action_btn.text(), "Geri Al")
        w.toast.action_btn.click()
        self.assertEqual(w.queue.paths(), order)
        self.assertEqual(w.queue.overrides_for(a), {"image_res": "1920px"})
        self.assertFalse(w.toast.is_showing())

    def test_clearing_the_queue_can_be_undone(self):
        w = self.make_window()
        paths = self.make_files("a.jpg", "b.jpg")
        w._add_sources(paths)
        w._clear_queue()
        self.assertEqual(w.queue.rowCount(), 0)
        self.assertIn("2", w.toast.text())
        w.toast.action_btn.click()
        self.assertEqual(sorted(w.queue.paths()), sorted(paths))
        self.assertTrue(w.start_btn.isEnabled())

    def test_removing_the_last_item_says_removed_not_cleared(self):
        w = self.make_window(language="en")
        (a,) = self.make_files("only.jpg")
        w._add_sources([a])
        w._remove_from_queue([a])
        self.assertEqual(w.queue.rowCount(), 0)
        self.assertIn("removed", w.toast.text())
        self.assertEqual(w.toast.action_btn.text(), "Undo")

    def test_adding_files_drops_the_stale_undo(self):
        w = self.make_window()
        a, b = self.make_files("a.jpg", "b.jpg")
        w._add_sources([a])
        w._clear_queue()
        w._add_sources([b])
        self.assertIsNone(w._undo_snapshot)
        w._undo_queue_change()  # eski toast'tan gelse bile hiçbir şey yapmaz
        self.assertEqual(w.queue.paths(), [b])

    def test_toast_follows_the_window_size_without_event_filters_on_other_widgets(self):
        w = self.make_window()
        w._add_sources(self.make_files("a.jpg"))
        w._clear_queue()
        w.resize(w.width() + 200, w.height() + 100)
        QTest.qWait(30)
        anchor = w.toast._anchor
        bottom = anchor.mapTo(w.toast.parentWidget(), anchor.rect().bottomLeft()).y()
        self.assertEqual(w.toast.geometry().bottom(), bottom - 16)  # QRect.bottom() = üst + yükseklik - 1
        center = anchor.mapTo(w.toast.parentWidget(), anchor.rect().center()).x()
        self.assertLessEqual(abs(w.toast.geometry().center().x() - center), 2)

    def test_empty_queue_clear_shows_nothing(self):
        w = self.make_window()
        w._clear_queue()
        self.assertFalse(w.toast.is_showing())


# ------------------------------------------------------------------------------------------- 4. kalan süre
class EtaSmoothingTests(unittest.TestCase):
    def test_jumpy_estimates_are_damped(self):
        s = EtaSmoother(tau=6.0)
        self.assertEqual(s.update(300, 0.0), 300)
        shown = [s.update(raw, t) for t, raw in ((1, 500), (2, 150), (3, 450), (4, 200))]
        for value in shown:
            self.assertLess(abs(value - 300), 120, shown)  # ham değerler 150-500 arasında zıplıyor

    def test_consistent_estimate_counts_down_in_real_time(self):
        s = EtaSmoother(tau=6.0)
        for t in range(0, 30):
            shown = s.update(600 - t, float(t))
        self.assertAlmostEqual(shown, 571, delta=0.5)

    def test_no_estimate_keeps_counting_down_the_last_one(self):
        s = EtaSmoother()
        self.assertIsNone(s.update(None, 0.0))
        s.update(100, 0.0)
        self.assertAlmostEqual(s.update(None, 10.0), 90.0)
        s.reset()
        self.assertIsNone(s.update(None, 11.0))

    def test_rounding_to_sensible_units(self):
        self.assertEqual(round_eta(3), 5)
        self.assertEqual(round_eta(43), 45)
        self.assertEqual(round_eta(187), 190)
        self.assertEqual(round_eta(1234), 1260)
        self.assertEqual(round_eta(5000), 5100)
        self.assertEqual(format_eta(43, "tr"), "45 sn")
        self.assertEqual(format_eta(187, "tr"), "3 dk 10 sn")
        self.assertEqual(format_eta(1234, "tr"), "21 dk")
        self.assertEqual(format_eta(5000, "en"), "1 h 25 m")
        self.assertEqual(format_eta(7200, "en"), "2 h")

    def test_row_eta_uses_the_rounded_text(self):
        w = _Base.make_window(self._base())
        clip = os.path.join(tempfile.gettempdir(), "klip.mp4")
        w.queue.set_files([clip])
        w._on_file_started(clip)
        w._file_t0 = time.time() - 61.0
        w._on_file_progress(clip, 0.25)  # ham kalan 183 sn
        self.assertIn("3 dk", w.queue.status_display(clip))

    def _base(self):
        base = _Base("run")
        base.app = QApplication.instance() or QApplication([])
        base.addCleanup = self.addCleanup
        return base


# ------------------------------------------------------------------------------------------- 5. sürükleme
def _mime(paths: list[str]) -> QMimeData:
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(p) for p in paths])
    return mime


class DragHighlightTests(_Base):
    def test_drop_zone_highlights_while_dragging_and_resets_on_leave_and_drop(self):
        w = self.make_window()
        zone = w.drop
        normal_hint = zone.hint_text.text()
        (a,) = self.make_files("a.jpg")
        mime = _mime([a])
        enter = QDragEnterEvent(QPoint(10, 10), Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton,
                                Qt.KeyboardModifier.NoModifier)
        QApplication.sendEvent(zone, enter)
        self.assertTrue(enter.isAccepted())
        self.assertTrue(zone.is_drag_active())
        self.assertNotEqual(zone.hint_text.text(), normal_hint)
        QApplication.sendEvent(zone, QEvent(QEvent.Type.DragLeave))
        self.assertFalse(zone.is_drag_active())
        self.assertEqual(zone.hint_text.text(), normal_hint)
        zone.set_drag_active(True)
        drop = QDropEvent(QPointF(10, 10), Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton,
                          Qt.KeyboardModifier.NoModifier)
        zone.dropEvent(drop)  # Qt, sürükleme yöneticisi dışından gelen Drop'u iletmez
        self.assertFalse(zone.is_drag_active())
        self.assertEqual(w.queue.paths(), [a])

    def test_highlight_has_its_own_style(self):
        from src.utils.theme_manager import DARK, LIGHT, _build, _with_accent

        for base, dark in ((DARK, True), (LIGHT, False)):
            qss = _build(_with_accent(base, "cyan", dark))
            self.assertIn('QFrame#DropZone[dragActive="true"]', qss)

    def test_dragging_over_the_window_highlights_the_zone_and_dropping_adds(self):
        w = self.make_window()
        (a,) = self.make_files("v.mp4")
        mime = _mime([a])
        enter = QDragEnterEvent(QPoint(5, 5), Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton,
                                Qt.KeyboardModifier.NoModifier)
        w.dragEnterEvent(enter)
        self.assertTrue(enter.isAccepted())
        self.assertTrue(w.drop.is_drag_active())
        w.dropEvent(QDropEvent(QPointF(5, 5), Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton,
                               Qt.KeyboardModifier.NoModifier))
        self.assertFalse(w.drop.is_drag_active())
        self.assertEqual(w.queue.paths(), [a])

    def test_plain_text_drag_is_refused(self):
        w = self.make_window()
        mime = QMimeData()
        mime.setText("merhaba")
        enter = QDragEnterEvent(QPoint(5, 5), Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton,
                                Qt.KeyboardModifier.NoModifier)
        w.dragEnterEvent(enter)
        self.assertFalse(enter.isAccepted())
        self.assertFalse(w.drop.is_drag_active())


# ------------------------------------------------------------------------------------------- 6. bitiş bildirimi
class FinishFeedbackTests(_Base):
    def test_active_window_gets_an_in_app_toast_with_the_saved_space_that_opens_the_folder(self):
        w = self.make_window()
        w.open_when_done.setChecked(False)
        with mock.patch.object(w, "isActiveWindow", return_value=True), \
                mock.patch.object(w.notifier, "notify") as notify, \
                mock.patch.object(w, "_open_folder") as open_folder:
            w._on_job_finished({"ok": 2, "bytes_in": 4 * 1024 * 1024, "bytes_out": 1024 * 1024, "elapsed": 12})
            self.assertTrue(w.toast.is_showing())
            self.assertIn("3.0 MB kazanıldı", w.toast.text())
            notify.assert_not_called()
            w.toast.action_btn.click()
            open_folder.assert_called_once_with(w._effective_output())

    def test_background_window_gets_a_system_notification_that_opens_the_folder_on_click(self):
        w = self.make_window(language="en")
        w.open_when_done.setChecked(False)
        with mock.patch.object(w, "isActiveWindow", return_value=False), \
                mock.patch.object(mw.QApplication, "alert"), \
                mock.patch.object(w.notifier, "notify", return_value=True) as notify, \
                mock.patch.object(w, "_open_folder") as open_folder:
            w._on_job_finished({"ok": 1, "bytes_in": 2 * 1024 * 1024, "bytes_out": 512 * 1024, "elapsed": 3})
            body = notify.call_args[0][1]
            self.assertIn("Saved 1.5 MB", body)
            w._on_notification_clicked()
            open_folder.assert_called_once_with(w._effective_output())
            w._on_notification_clicked()  # ikinci tık (ya da başka bildirim) klasörü yeniden açmaz
            open_folder.assert_called_once()

    def test_nothing_saved_means_no_saved_text(self):
        w = self.make_window()
        w.open_when_done.setChecked(False)
        with mock.patch.object(w, "isActiveWindow", return_value=True):
            w._on_job_finished({"cancelled": True, "ok": 0, "skip": 0, "fail": 0})
        self.assertNotIn("kazanıldı", w.toast.text())


# ------------------------------------------------------------------------------------------- 7. imleç
class CursorTests(_Base):
    def test_clickable_controls_use_the_pointing_hand(self):
        w = self.make_window()
        for widget in (w.retry_btn, w.adv_btn, w.ffmpeg_btn, w.open_when_done, w.toast.action_btn,
                       w.toast.close_btn):
            self.assertEqual(widget.cursor().shape(), Qt.CursorShape.PointingHandCursor, widget)


# ------------------------------------------------------------------------------------------- 8. kısayollar
class ShortcutTests(_Base):
    def _shortcut(self, w, keys: str) -> QShortcut:
        for sc in w.findChildren(QShortcut):
            if sc.key() == QKeySequence(keys):
                return sc
        self.fail(f"{keys} bağlı değil")

    def test_ctrl_enter_starts_only_when_the_button_is_enabled(self):
        w = self.make_window()
        with mock.patch.object(w, "_start_stop") as start:
            self._shortcut(w, "Ctrl+Return").activated.emit()
            self._shortcut(w, "Ctrl+Enter").activated.emit()
            start.assert_not_called()  # boş kuyruk: düğme pasif
            w._add_sources(self.make_files("a.jpg"))
            self._shortcut(w, "Ctrl+Return").activated.emit()
            start.assert_called_once()

    def test_ctrl_shift_e_opens_the_output_folder_and_is_listed(self):
        w = self.make_window()
        with mock.patch.object(w, "_open_folder") as open_folder:
            self._shortcut(w, "Ctrl+Shift+E").activated.emit()
            w.title_bar.open_output_action.trigger()
        self.assertEqual(open_folder.call_count, 2)
        self.assertIn("Ctrl+Shift+E", w.title_bar.open_output_action.text())
        self.assertIn("Ctrl+Shift+E", w.open_btn.toolTip())
        w._add_sources(self.make_files("a.jpg"))
        self.assertIn("Ctrl+Enter", w.start_btn.toolTip())


# ------------------------------------------------------------------------------------------- 9. pencere konumu
class GeometryTests(_Base):
    SCREENS = [(0, 0, 1920, 1040), (1920, 0, 1280, 984)]

    def test_fit_keeps_a_visible_rect_and_clamps_oversized_or_lost_ones(self):
        self.assertEqual(fit_to_screens((100, 80, 1200, 700), self.SCREENS), (100, 80, 1200, 700))
        self.assertEqual(fit_to_screens((2000, 50, 1200, 700), self.SCREENS), (2000, 50, 1200, 700))
        # ikinci monitör çıkarıldı: birincil ekranda ortalanır
        self.assertEqual(fit_to_screens((3500, 100, 1200, 700), self.SCREENS[:1]), (360, 170, 1200, 700))
        # ekrandan büyük: küçülür ve sığar
        self.assertEqual(fit_to_screens((-50, -40, 4000, 3000), self.SCREENS[:1]), (0, 0, 1920, 1040))
        # yarısı ekran dışında: içeri kaydırılır
        self.assertEqual(fit_to_screens((1500, 600, 1000, 700), self.SCREENS[:1]), (920, 340, 1000, 700))
        self.assertIsNone(parse_saved({"x": "a"}))
        self.assertIsNone(parse_saved(None))
        self.assertEqual(parse_saved({"x": 1, "y": 2, "w": 900, "h": 600, "maximized": True}),
                         ((1, 2, 900, 600), True))

    def test_window_saves_and_restores_geometry(self):
        w = self.make_window()
        avail = QApplication.primaryScreen().availableGeometry()
        w.setGeometry(avail.x() + 40, avail.y() + 30, 900, 600)
        self.app.processEvents()
        w._save_geometry()
        saved = w.config.get("window_geometry")
        self.assertEqual((saved["w"], saved["h"], saved["maximized"]), (900, 600, False))
        # offscreen ekranı 800 px genişliğinde (pencerenin en küçük genişliği 860): gerçek bir masaüstü taklit edilir
        desktop = mock.MagicMock()
        desktop.availableGeometry.return_value = QRect(0, 0, 1920, 1040)
        with mock.patch.object(mw.QApplication, "screens", return_value=[desktop]),                 mock.patch.object(mw.QApplication, "primaryScreen", return_value=desktop):
            w2 = self.make_window(window_geometry=dict(saved))
        self.assertEqual((w2.width(), w2.height()), (900, 600))
        self.assertEqual((w2.x(), w2.y()), (saved["x"], saved["y"]))

    def test_maximized_flag_is_restored_and_lost_positions_come_back_on_screen(self):
        w = self.make_window(window_geometry={"x": 90000, "y": 90000, "w": 900, "h": 600, "maximized": True})
        self.assertTrue(w.windowState() & Qt.WindowState.WindowMaximized)
        w.showNormal()
        self.app.processEvents()
        avail = QApplication.primaryScreen().availableGeometry()
        self.assertTrue(avail.intersects(w.geometry()), w.geometry())

    def test_closing_to_the_tray_saves_the_geometry(self):
        w = self.make_window()
        with mock.patch.object(w, "_save_geometry") as save:
            w._quitting = False
            with mock.patch.object(mw.TrayIcon, "isSystemTrayAvailable", return_value=True):
                w.tray = mock.MagicMock()
                w.close()
            save.assert_called_once()
        w.tray = None
        w._quitting = True


# ------------------------------------------------------------------------------------------- 10. kayan satırlar
class SlideAnimationTests(_Base):
    def test_notice_bar_slides_in_and_out_when_animations_are_on(self):
        from src.utils import remote_notice as rn

        w = self.make_window()
        bar = w.notice_bar
        with mock.patch.object(anim, "animations_enabled", return_value=True):
            w.show_notice(rn.Notice("n1", "Duyuru", ""))
            self.assertTrue(anim.is_animating(bar))
            self.assertLessEqual(anim.DURATION_MS, 250)
            anim.finish(bar)
            self.assertFalse(anim.is_animating(bar))
            self.assertEqual(bar.maximumHeight(), 16777215)
            self.assertIsNone(bar.graphicsEffect())
            bar.dismiss()
            self.assertTrue(anim.is_animating(bar))
            self.assertTrue(bar.isVisible(), "kapanırken önce kayar")
            anim.finish(bar)
            self.assertFalse(bar.isVisible())

    def test_new_notice_during_slide_out_reopens_the_bar(self):
        from src.utils import remote_notice as rn

        w = self.make_window()
        with mock.patch.object(anim, "animations_enabled", return_value=True):
            w.show_notice(rn.Notice("n1", "Bir", ""))
            anim.finish(w.notice_bar)
            w.notice_bar.dismiss()
            w.show_notice(rn.Notice("n2", "İki", ""))
            anim.finish(w.notice_bar)
            self.assertTrue(w.notice_bar.isVisible())

    def test_without_system_animations_everything_is_instant(self):
        from src.utils import remote_notice as rn

        w = self.make_window()
        with mock.patch.object(anim, "_system_animations_enabled", return_value=False):
            self.assertFalse(anim.animations_enabled())
            w.show_notice(rn.Notice("n1", "Duyuru", ""))
            self.assertFalse(anim.is_animating(w.notice_bar))
            self.assertTrue(w.notice_bar.isVisible())
            w.notice_bar.dismiss()
            self.assertFalse(w.notice_bar.isVisible())

    def test_ffmpeg_banner_uses_the_slide(self):
        w = self.make_window()
        manager = mock.MagicMock()
        manager.is_ready.return_value = False
        manager.missing_hint.return_value = "FFmpeg yok"
        with mock.patch.object(anim, "slide_in") as slide_in:
            w._on_prepared(manager, None)
        slide_in.assert_called_once_with(w.banner)


if __name__ == "__main__":
    unittest.main()
