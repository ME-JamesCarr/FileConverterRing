"""HTML to PDF with Qt WebEngine (Chromium).

WebEngine only runs on the GUI thread, so converter threads hand the job to a
renderer living there and wait for it to finish. Call install() once on the
GUI thread after the QApplication exists.
"""
import threading
from pathlib import Path

from PySide6.QtCore import (QCoreApplication, QMarginsF, QObject, QThread, QUrl,
                            Signal, Slot)
from PySide6.QtGui import QPageLayout, QPageSize
from PySide6.QtWebEngineCore import QWebEnginePage

LAYOUT = QPageLayout(QPageSize(QPageSize.A4), QPageLayout.Portrait,
                     QMarginsF(15, 15, 15, 15), QPageLayout.Millimeter)
TIMEOUT_S = 120


class _Job:
    def __init__(self, html: Path, pdf: Path):
        self.html, self.pdf = html, pdf
        self.done = threading.Event()
        self.error = ""


class _Renderer(QObject):
    requested = Signal(object)

    def __init__(self):
        super().__init__()
        self.requested.connect(self._render)
        self._pages = set()   # keep pages alive until they finish

    @Slot(object)
    def _render(self, job: _Job):
        page = QWebEnginePage(self)
        self._pages.add(page)
        started = False

        def finish(error=""):
            job.error = error
            job.done.set()
            self._pages.discard(page)
            page.deleteLater()

        def loaded(ok):
            nonlocal started
            if started:
                return
            started = True
            if ok:
                page.printToPdf(str(job.pdf), LAYOUT)
            else:
                finish("couldn't load the document to render it as PDF")

        page.loadFinished.connect(loaded)
        page.pdfPrintingFinished.connect(
            lambda _path, ok: finish("" if ok else "PDF rendering failed"))
        page.load(QUrl.fromLocalFile(str(job.html)))


_renderer: _Renderer | None = None


def install():
    global _renderer
    _renderer = _Renderer()


def html_to_pdf(html: Path, pdf: Path) -> None:
    if _renderer is None:
        raise RuntimeError("PDF renderer not installed")
    job = _Job(html, pdf)
    _renderer.requested.emit(job)
    app = QCoreApplication.instance()
    if QThread.currentThread() == app.thread():
        # Called on the GUI thread (e.g. from tests): keep events flowing while we wait.
        while not job.done.wait(0.02):
            app.processEvents()
    elif not job.done.wait(TIMEOUT_S):
        raise TimeoutError("PDF rendering took too long")
    if job.error:
        raise RuntimeError(job.error)
