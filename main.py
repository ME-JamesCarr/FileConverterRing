"""FileRing: press the hotkey, drag a file onto a format, get a converted copy.

This process is the tray icon, hotkey and ring. Conversions run in a separate
worker process (see worker.py) that quits when idle, to keep memory low.
"""
import ctypes
import getpass
import sys
from pathlib import Path

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QAction, QColor, QCursor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon

import explorer
import formats
from formats import CATEGORY_COLOURS
from hotkey import GlobalHotkey
from progress import ProgressBadge
from ring import RingOverlay
from settings import Settings, SettingsDialog, refresh_autostart
from worker import ConversionService

BADGE_DELAY_MS = 600            # quick conversions finish before a progress badge would appear
IDLE_TRIM_MS = 3 * 60 * 1000    # give unused memory back to Windows after this long idle
INSTANCE_NAME = f"FileRing-{getpass.getuser()}"


def app_icon(size: int = 64) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(QColor(0, 0, 0, 0))
    s = size / 64
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.scale(s, s)
    p.setPen(QPen(QColor("#4f8cff"), 9))
    p.drawEllipse(10, 10, 44, 44)
    p.setPen(QPen(QColor("#e0559a"), 9))
    p.drawArc(10, 10, 44, 44, 30 * 16, 120 * 16)
    p.end()
    return pm


def trim_memory():
    """Release this process's unused pages back to Windows."""
    kernel32 = ctypes.windll.kernel32
    kernel32.GetCurrentProcess.restype = ctypes.c_void_p
    kernel32.SetProcessWorkingSetSize.argtypes = [ctypes.c_void_p, ctypes.c_size_t,
                                                  ctypes.c_size_t]
    kernel32.SetProcessWorkingSetSize(kernel32.GetCurrentProcess(),
                                      ctypes.c_size_t(-1), ctypes.c_size_t(-1))


class FileRingApp:
    def __init__(self, app: QApplication, settings: Settings):
        self.app = app
        self.settings = settings
        self.ring = RingOverlay()
        self.ring.convertRequested.connect(self.start_conversion)
        self.last_output: Path | None = None
        self.service = ConversionService()
        self.service.progress.connect(self.on_progress)
        self.service.finished.connect(self.on_finished)
        self.jobs: dict[int, tuple[str, ProgressBadge]] = {}   # id -> (target, badge)
        self.dialogs: list[QMessageBox] = []
        self.hotkey: GlobalHotkey | None = None
        self.idle = QTimer(singleShot=True, interval=IDLE_TRIM_MS,
                           timeout=lambda: self.jobs or trim_memory())

        self.tray = QSystemTrayIcon(QIcon(app_icon()))
        menu = QMenu()
        self.show_action = QAction(menu, triggered=self.show_ring)
        open_dir = QAction("Open output folder", menu, triggered=self.open_output_dir)
        prefs = QAction("Settings…", menu, triggered=self.open_settings)
        quit_ = QAction("Quit", menu, triggered=self.quit)
        menu.addActions([self.show_action, open_dir, prefs])
        menu.addSeparator()
        menu.addAction(quit_)
        self.menu = menu
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(
            lambda reason: reason == QSystemTrayIcon.DoubleClick and self.open_settings())
        self.tray.show()

        self.start_hotkey()
        self.idle.start()

    # ---- messages -----------------------------------------------------------------

    def show_message(self, title: str, text: str):
        """A small dialog that doesn't block anything (used only for problems)."""
        box = QMessageBox(QMessageBox.Warning, f"FileRing: {title}", text, QMessageBox.Ok)
        box.setWindowFlag(Qt.WindowStaysOnTopHint)
        box.setAttribute(Qt.WA_DeleteOnClose)
        box.finished.connect(lambda _: self.dialogs.remove(box))
        self.dialogs.append(box)
        box.show()

    # ---- hotkey / settings ----------------------------------------------------

    def start_hotkey(self):
        self.hotkey = GlobalHotkey(self.settings.hotkey)
        self.hotkey.pressed.connect(self.show_ring)
        self.hotkey.failed.connect(lambda msg: self.show_message("Hotkey unavailable", msg))
        self.hotkey.start()
        self.show_action.setText(f"Show ring  ({self.hotkey.name})")
        self.idle_tooltip()

    def idle_tooltip(self):
        self.tray.setToolTip(f"FileRing: {self.hotkey.name}")

    def open_settings(self):
        # Release the hotkey while the dialog is open so it can be typed into the box.
        self.hotkey.stop()
        dialog = SettingsDialog(self.settings)
        dialog.setWindowIcon(QIcon(app_icon()))
        dialog.exec()
        self.start_hotkey()
        self.idle.start()

    # ---- conversions --------------------------------------------------------

    def show_ring(self):
        self.idle.start()
        self.ring.show_at(QCursor.pos())

    def start_conversion(self, files: list[Path], target: str, category: str):
        self.idle.start()
        job_id = self.service.convert(files, target, category)
        badge = ProgressBadge(target.upper(), CATEGORY_COLOURS[category])
        badge.cancelRequested.connect(lambda: self.service.cancel(job_id))
        # Show the badge where the file was dropped, beside any still running.
        offset = sum(b.isVisible() for _, b in self.jobs.values()) * 86
        where = QCursor.pos() + QPoint(offset, 0)
        QTimer.singleShot(BADGE_DELAY_MS, lambda: job_id in self.jobs and badge.show_at(where))
        self.jobs[job_id] = (target, badge)
        self.tray.setToolTip(f"FileRing: converting to {target.upper()}…")

    def on_progress(self, job_id: int, value: float):
        if job_id in self.jobs:
            target, badge = self.jobs[job_id]
            badge.set_value(value)
            self.tray.setToolTip(f"FileRing: converting to {target.upper()}… "
                                 f"{round(value * 100)}%")

    def on_finished(self, job_id: int, outputs: list[Path], errors: list[str],
                    cancelled: bool):
        target, badge = self.jobs.pop(job_id)
        badge.close()
        badge.deleteLater()
        self.idle.start()
        if not self.jobs:
            self.idle_tooltip()
        if outputs:
            self.last_output = outputs[-1]
            explorer.reveal(outputs)
        if errors and not cancelled:
            self.show_message("Conversion failed" if not outputs else "Some files failed",
                              "\n".join(errors[:6]))

    def open_output_dir(self):
        if formats.SAVE_NEXT_TO_ORIGINAL:
            if self.last_output:
                explorer.reveal([self.last_output])
            else:
                self.show_message("No output folder",
                                  "Converted files are saved next to the original file.")
            return
        formats.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        explorer.open_folder(formats.OUTPUT_DIR)

    def quit(self):
        for job_id in list(self.jobs):
            self.service.cancel(job_id)
        self.service.shutdown()
        self.hotkey.stop()
        self.tray.hide()
        self.app.quit()


def already_running() -> bool:
    socket = QLocalSocket()
    socket.connectToServer(INSTANCE_NAME)
    return socket.waitForConnected(300)


def log_crashes():
    """A windowed app has no console, so write unhandled errors to a log file."""
    import os
    import traceback
    log = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "FileRing" / "error.log"

    def hook(exc_type, exc, tb):
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a", encoding="utf-8") as f:
            f.write("".join(traceback.format_exception(exc_type, exc, tb)) + "\n")
    sys.excepthook = hook


def main():
    log_crashes()
    if "--worker" in sys.argv:
        import worker
        sys.exit(worker.run_worker(sys.argv[sys.argv.index("--worker") + 1]))
    if "--selftest" in sys.argv:
        import selftest
        sys.exit(selftest.run(Path(sys.argv[sys.argv.index("--selftest") + 1])))

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("FileRing")
    app.setWindowIcon(QIcon(app_icon()))
    if already_running():
        QMessageBox.information(None, "FileRing", "FileRing is already running.\n\n"
                                "Look for its icon in the system tray.")
        return

    settings = Settings.load()
    settings.apply()
    refresh_autostart()
    _ = FileRingApp(app, settings)

    server = QLocalServer()
    QLocalServer.removeServer(INSTANCE_NAME)
    server.listen(INSTANCE_NAME)
    server.newConnection.connect(lambda: server.nextPendingConnection().close())
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
