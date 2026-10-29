"""FileRing: press the hotkey, drag a file onto a format, get a converted copy.

This process is the tray icon, hotkey and ring. Conversions run in a separate
worker process (see worker.py) that quits when idle, to keep memory low.
"""
import sys

if __name__ == "__main__" and "--convert" in sys.argv:
    # From the Explorer right-click menu: pass the file to the running app.
    # Handled before the Qt imports so it starts and exits quickly.
    import handoff
    sys.exit(handoff.main(sys.argv))

import ctypes
import json
import os
import threading
import time
from pathlib import Path

from PySide6.QtCore import QObject, QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QCursor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon

import converters
import explorer
import formats
import shell_menu
import updater
from formats import CATEGORY_COLOURS, button_label, kind_of, target_name
from handoff import INSTANCE_NAME
from hotkey import GlobalHotkey
from progress import ProgressBadge
from ring import RingOverlay
from settings import Settings, SettingsDialog, refresh_autostart
from worker import ConversionService

BADGE_DELAY_MS = 600            # quick conversions finish before a progress badge would appear
IDLE_TRIM_MS = 3 * 60 * 1000    # give unused memory back to Windows after this long idle
BATCH_MS = 700                  # gather right-click hand-offs arriving this close together
MAX_LISTED = 8                  # skipped files named in the message before "and N more"
UPDATE_CHECK_MS = 6 * 60 * 60 * 1000   # look for a new release this often
FIRST_CHECK_MS = 60 * 1000             # ...and this long after starting
UPDATE_IDLE_S = 3 * 60                 # only update after this long without using FileRing


class _UpdateResult(QObject):
    """Carries update-check results from the background thread to the Qt thread."""
    ready = Signal(object)


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
        # Right-click requests: (category, target) -> files, sent as one job each.
        self.pending: dict[tuple[str, str], list[Path]] = {}
        self.batch = QTimer(singleShot=True, interval=BATCH_MS, timeout=self.run_pending)

        self.tray = QSystemTrayIcon(QIcon(app_icon()))
        menu = QMenu()
        self.show_action = QAction(menu, triggered=self.show_ring)
        open_dir = QAction("Open output folder", menu, triggered=self.open_output_dir)
        prefs = QAction("Settings…", menu, triggered=self.open_settings)
        self.version = updater.installed_version()
        updates = QAction(f"Check for updates (v{self.version or 'dev'})", menu,
                          triggered=lambda: self.check_for_updates(manual=True))
        quit_ = QAction("Quit", menu, triggered=self.quit)
        menu.addActions([self.show_action, open_dir, prefs, updates])
        menu.addSeparator()
        menu.addAction(quit_)
        self.menu = menu
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(
            lambda reason: reason == QSystemTrayIcon.DoubleClick and self.open_settings())
        self.tray.show()

        self.start_hotkey()
        self.touch()

        # Automatic updates (installed copy only).
        self.update_result = _UpdateResult()
        self.update_result.ready.connect(self.on_update_result)
        self.update_installer: Path | None = None
        self.update_checks = QTimer(interval=UPDATE_CHECK_MS, timeout=self.check_for_updates)
        self.update_checks.start()
        QTimer.singleShot(FIRST_CHECK_MS, self.check_for_updates)
        self.apply_update = QTimer(interval=30 * 1000, timeout=self.apply_update_if_idle)

    # ---- messages -----------------------------------------------------------------

    def show_message(self, title: str, text: str, info: bool = False):
        """A small dialog that doesn't block anything (problems, or an answer you asked for)."""
        icon = QMessageBox.Information if info else QMessageBox.Warning
        box = QMessageBox(icon, f"FileRing: {title}", text, QMessageBox.Ok)
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
        if dialog.exec():
            update_shell_menu(self.settings)
        self.start_hotkey()
        self.touch()

    # ---- conversions --------------------------------------------------------

    def show_ring(self):
        self.touch()
        self.ring.show_at(QCursor.pos())

    def start_conversion(self, files: list[Path], target: str, category: str):
        self.touch()
        job_id = self.service.convert(files, target, category)
        badge = ProgressBadge(button_label(target).replace("\n", " "), CATEGORY_COLOURS[category])
        badge.cancelRequested.connect(lambda: self.service.cancel(job_id))
        # Show the badge where the file was dropped, beside any still running.
        offset = sum(b.isVisible() for _, b in self.jobs.values()) * 86
        where = QCursor.pos() + QPoint(offset, 0)
        QTimer.singleShot(BADGE_DELAY_MS, lambda: job_id in self.jobs and badge.show_at(where))
        self.jobs[job_id] = (target, badge)
        self.tray.setToolTip(f"FileRing: converting to {target_name(target)}…")

    def handle_request(self, msg: dict):
        """A file from the Explorer right-click menu (one message per selected file)."""
        if msg.get("type") != "convert":
            return
        key = (msg["category"], msg["target"])
        self.pending.setdefault(key, []).extend(Path(f) for f in msg["files"])
        self.batch.start()   # restarts: wait until the last file of the selection arrives

    def run_pending(self):
        pending, self.pending = self.pending, {}
        for (category, target), files in pending.items():
            files = list(dict.fromkeys(files))   # drop repeats, keep order
            ok = [f for f in files if f.exists()
                  and converters.can_convert(kind_of(f), target, category)]
            skipped = [f for f in files if f not in ok]
            if ok:
                self.start_conversion(ok, target, category)
            if skipped:
                names = "\n".join(f.name for f in skipped[:MAX_LISTED])
                more = len(skipped) - MAX_LISTED
                if more > 0:
                    names += f"\n…and {more} more"
                self.show_message(f"Skipped {len(skipped)} file(s)",
                                  f"These can't be converted to {target_name(target)}:\n\n{names}")

    def on_progress(self, job_id: int, value: float):
        if job_id in self.jobs:
            target, badge = self.jobs[job_id]
            badge.set_value(value)
            self.tray.setToolTip(f"FileRing: converting to {target_name(target)}… "
                                 f"{round(value * 100)}%")

    def on_finished(self, job_id: int, outputs: list[Path], errors: list[str],
                    cancelled: bool):
        target, badge = self.jobs.pop(job_id)
        badge.close()
        badge.deleteLater()
        self.touch()
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

    def touch(self):
        """Note that FileRing was just used (for idle memory trimming and updates)."""
        self.last_used = time.monotonic()
        self.idle.start()

    # ---- updates ---------------------------------------------------------------------

    def check_for_updates(self, manual: bool = False):
        if not self.version:
            if manual:
                self.show_message("Updates", "This copy of FileRing isn't the installed one, "
                                  "so it doesn't update itself.", info=True)
            return
        if not (manual or self.settings.auto_update) or self.update_installer:
            return

        def work():
            try:
                release = updater.newer_release(self.version)
                path = updater.download(release) if release else None
                self.update_result.ready.emit((release, path, None, manual))
            except Exception as exc:   # offline, GitHub down...: try again next time
                self.update_result.ready.emit((None, None, str(exc), manual))
        threading.Thread(target=work, daemon=True).start()

    def on_update_result(self, result):
        release, path, error, manual = result
        if error:
            if manual:
                self.show_message("Update check failed", f"Couldn't check for updates:\n{error}")
        elif path:
            self.update_installer = path
            self.tray.setToolTip(f"FileRing: v{release.version} will install when idle")
            if manual:
                self.show_message("Update ready", f"FileRing v{release.version} has downloaded "
                                  "and will install as soon as nothing is converting. FileRing "
                                  "restarts by itself.", info=True)
                self.last_used = 0   # you asked: don't wait for the idle time
            self.apply_update.start()
            self.apply_update_if_idle()
        elif manual:
            self.show_message("Up to date", f"You have the latest version (v{self.version}).",
                              info=True)

    def apply_update_if_idle(self):
        busy = self.jobs or self.pending or self.ring.isVisible() or self.dialogs
        if busy or time.monotonic() - self.last_used < UPDATE_IDLE_S:
            return
        updater.apply(self.update_installer)
        self.quit()

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
    threading.excepthook = lambda args: hook(args.exc_type, args.exc_value, args.exc_traceback)


def listen_for_requests(file_ring: FileRingApp) -> QLocalServer:
    """Hand-offs from the right-click menu arrive here. A connection that sends
    nothing is a second copy of FileRing checking whether one is running."""
    server = QLocalServer()
    QLocalServer.removeServer(INSTANCE_NAME)
    server.listen(INSTANCE_NAME)

    def accept():
        sock = server.nextPendingConnection()
        buffer = bytearray()

        def read():
            buffer.extend(bytes(sock.readAll()))
            while b"\n" in buffer:
                line, _, rest = bytes(buffer).partition(b"\n")
                buffer[:] = rest
                try:
                    file_ring.handle_request(json.loads(line))
                except (ValueError, KeyError):
                    pass   # not a message we understand
        sock.readyRead.connect(read)
        sock.disconnected.connect(lambda: (read(), sock.deleteLater()))
    server.newConnection.connect(accept)
    return server


def update_now() -> int:
    """FileRing.exe --update: install the latest release if it's newer.
    Exit code 0 = updating or already up to date, 2 = not the installed copy."""
    version = updater.installed_version()
    if not version:
        return 2
    release = updater.newer_release(version)
    if release:
        updater.apply(updater.download(release))
    return 0


def update_shell_menu(settings: Settings):
    """Keep the right-click menu pointing at this copy of FileRing (packaged app only)."""
    if not getattr(sys, "frozen", False):
        return
    def run():   # a few hundred registry keys, so off the main thread
        result = (shell_menu.register() if settings.explorer_menu
                  else shell_menu.unregister() or "removed")
        log(f"right-click menu: {result}")
    threading.Thread(target=run, daemon=True).start()


def log(message: str):
    """One line in %LOCALAPPDATA%\\FileRing\\FileRing.log (startup decisions, for support)."""
    path = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "FileRing" / "FileRing.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n")


def main():
    log_crashes()
    if "--unregister-shell" in sys.argv:   # run by the uninstaller
        shell_menu.unregister()
        return
    if "--update" in sys.argv:             # update now, without waiting for the tray app
        sys.exit(update_now())
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
        if "--background" not in sys.argv:   # started by a right-click hand-off: stay quiet
            QMessageBox.information(None, "FileRing", "FileRing is already running.\n\n"
                                    "Look for its icon in the system tray.")
        return

    settings = Settings.load()
    settings.apply()
    refresh_autostart()
    update_shell_menu(settings)
    file_ring = FileRingApp(app, settings)
    _server = listen_for_requests(file_ring)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
