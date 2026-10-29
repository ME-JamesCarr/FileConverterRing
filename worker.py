"""Conversions run in a separate worker process, so the heavy libraries
(pandas, OpenCV, PyMuPDF, Chromium for PDFs) are only in memory while needed.

The tray app (ConversionService) starts the worker on demand and talks to it
over a local socket, one JSON message per line:

  app -> worker   {"type": "convert", "id", "files", "target", "category",
                   "output_dir", "next_to_original", "compress_mb"}
                  {"type": "cancel", "id"}
  worker -> app   {"id", "ack": true}
                  {"id", "progress": 0..1}
                  {"id", "done": true, "outputs", "errors", "cancelled"}

The worker quits after IDLE_EXIT_MS with no jobs, or when the app goes away.
"""
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

IDLE_EXIT_MS = int(os.environ.get("FILERING_WORKER_IDLE_MS", 3 * 60 * 1000))


def _write(sock: QLocalSocket, msg: dict):
    sock.write((json.dumps(msg) + "\n").encode())
    sock.flush()


# ---- worker process --------------------------------------------------------------

class _Outbox(QObject):
    """Job threads emit here; the socket is only touched on the Qt thread."""
    send = Signal(dict)


def run_worker(server_name: str) -> int:
    from PySide6 import QtWebEngineCore  # noqa: F401 (must load before QApplication)
    from PySide6.QtCore import QCoreApplication, Qt
    from PySide6.QtWidgets import QApplication

    QCoreApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
    app = QApplication([sys.argv[0]])
    app.setQuitOnLastWindowClosed(False)

    import converters
    import formats
    from converters import pdf_render
    pdf_render.install()

    sock = QLocalSocket()
    sock.connectToServer(server_name)
    if not sock.waitForConnected(5000):
        return 1

    jobs: dict[int, threading.Event] = {}
    idle = QTimer(singleShot=True, interval=IDLE_EXIT_MS, timeout=app.quit)
    outbox = _Outbox()

    def send(msg: dict):
        _write(sock, msg)
        if msg.get("done"):
            jobs.pop(msg["id"], None)
            if not jobs:
                idle.start()
    outbox.send.connect(send)

    def work(job: dict, cancel: threading.Event):
        outputs, errors = converters.run_job(
            [Path(f) for f in job["files"]], job["target"], job["category"],
            lambda v: outbox.send.emit({"id": job["id"], "progress": v}), cancel)
        outbox.send.emit({"id": job["id"], "done": True, "outputs": [str(o) for o in outputs],
                          "errors": errors, "cancelled": cancel.is_set()})

    def on_message(msg: dict):
        if msg["type"] == "convert":
            idle.stop()
            # Every job carries the current settings, so changes apply straight away.
            formats.OUTPUT_DIR = Path(msg["output_dir"])
            formats.SAVE_NEXT_TO_ORIGINAL = msg["next_to_original"]
            formats.COMPRESS_MB = msg.get("compress_mb", formats.COMPRESS_MB)
            cancel = threading.Event()
            jobs[msg["id"]] = cancel
            _write(sock, {"id": msg["id"], "ack": True})
            threading.Thread(target=work, args=(msg, cancel), daemon=True).start()
        elif msg["type"] == "cancel" and msg["id"] in jobs:
            jobs[msg["id"]].set()

    def on_ready():
        while sock.canReadLine():
            on_message(json.loads(bytes(sock.readLine()).decode()))

    sock.readyRead.connect(on_ready)
    sock.disconnected.connect(app.quit)
    on_ready()   # anything sent before we connected the signal
    idle.start()
    app.exec()
    for cancel in jobs.values():   # app closed mid-job: stop FFmpeg etc.
        cancel.set()
    return 0


# ---- app side ----------------------------------------------------------------------

def _worker_command(server_name: str) -> list[str]:
    if getattr(sys, "frozen", False):          # packaged FileRing.exe
        return [sys.executable, "--worker", server_name]
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    return [str(pythonw), str(Path(__file__).with_name("main.py")), "--worker", server_name]


class ConversionService(QObject):
    """Sends conversion jobs to the worker process, starting it when needed."""
    progress = Signal(int, float)                 # job id, 0..1
    finished = Signal(int, list, list, bool)      # job id, [Path], [str errors], cancelled

    def __init__(self):
        super().__init__()
        self._name = f"FileRing-worker-{os.getpid()}"
        self._server = QLocalServer(self)
        QLocalServer.removeServer(self._name)
        self._server.listen(self._name)
        self._server.newConnection.connect(self._on_connection)
        self._sock: QLocalSocket | None = None
        self._proc: subprocess.Popen | None = None
        self._next_id = 1
        self._unsent: list[dict] = []          # waiting for the worker to connect
        self._in_flight: dict[int, dict] = {}  # sent, not finished
        self._acked: set[int] = set()

    def convert(self, files: list[Path], target: str, category: str) -> int:
        import formats
        job_id = self._next_id
        self._next_id += 1
        msg = {"type": "convert", "id": job_id, "files": [str(f) for f in files],
               "target": target, "category": category,
               "output_dir": str(formats.OUTPUT_DIR),
               "next_to_original": formats.SAVE_NEXT_TO_ORIGINAL,
               "compress_mb": formats.COMPRESS_MB}
        self._in_flight[job_id] = msg
        self._send(msg)
        return job_id

    def cancel(self, job_id: int):
        if job_id in self._in_flight:
            self._send({"type": "cancel", "id": job_id})

    def shutdown(self):
        self._unsent.clear()
        if self._sock:
            self._sock.disconnectFromServer()   # the worker quits when we go

    def _send(self, msg: dict):
        if self._sock and self._sock.state() == QLocalSocket.ConnectedState:
            _write(self._sock, msg)
        else:
            self._unsent.append(msg)
            self._start_worker()

    def _start_worker(self):
        if self._proc is None or self._proc.poll() is not None:
            self._proc = subprocess.Popen(_worker_command(self._name),
                                          creationflags=subprocess.CREATE_NO_WINDOW)

    def _on_connection(self):
        self._sock = self._server.nextPendingConnection()
        self._sock.readyRead.connect(self._on_ready)
        self._sock.disconnected.connect(self._on_worker_gone)
        pending, self._unsent = self._unsent, []
        for msg in pending:
            _write(self._sock, msg)

    def _on_ready(self):
        while self._sock and self._sock.canReadLine():
            msg = json.loads(bytes(self._sock.readLine()).decode())
            job_id = msg["id"]
            if msg.get("ack"):
                self._acked.add(job_id)
            elif "progress" in msg:
                self.progress.emit(job_id, msg["progress"])
            elif msg.get("done"):
                self._in_flight.pop(job_id, None)
                self._acked.discard(job_id)
                self.finished.emit(job_id, [Path(p) for p in msg["outputs"]],
                                   msg["errors"], msg["cancelled"])

    def _on_worker_gone(self):
        self._sock.deleteLater()
        self._sock = None
        for job_id, msg in list(self._in_flight.items()):
            if job_id in self._acked:
                # It was working on this when it stopped (a crash, not idling).
                self._in_flight.pop(job_id)
                self._acked.discard(job_id)
                self.finished.emit(job_id, [], ["The converter stopped unexpectedly."], False)
            else:
                # Sent just as it was quitting from idle: send again to a new worker.
                self._send(msg)
