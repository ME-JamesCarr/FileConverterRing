"""Small floating progress ring shown where a file was dropped.

Never takes focus. Shows a percentage when the converter reports progress,
otherwise a spinning arc. Hovering shows a cancel cross; clicking cancels.
"""
from PySide6.QtCore import QPoint, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget

SIZE = 78
RING = 6


class ProgressBadge(QWidget):
    cancelRequested = Signal()

    def __init__(self, label: str, colour: str):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
                         | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFixedSize(SIZE, SIZE)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Click to cancel")
        self._label = label
        self._colour = QColor(colour)
        self._value: float | None = None
        self._hover = False
        self._cancelling = False
        self._spin = 0
        self._spinner = QTimer(self, interval=30, timeout=self._tick)
        self._spinner.start()

    def show_at(self, centre: QPoint):
        self.move(centre.x() - SIZE // 2, centre.y() - SIZE // 2)
        self.show()

    def set_value(self, value: float):
        if self._cancelling:
            return
        self._value = max(0.0, min(1.0, value))
        self._spinner.stop()
        self.update()

    def _tick(self):
        self._spin = (self._spin + 12) % 360
        self.update()

    def enterEvent(self, _):
        self._hover = True
        self.update()

    def leaveEvent(self, _):
        self._hover = False
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and not self._cancelling:
            self._cancelling = True
            self._label = "Cancelling"
            self._value = None
            self._spinner.start()
            self.setCursor(Qt.ArrowCursor)
            self.cancelRequested.emit()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(18, 20, 26, 200))
        p.drawEllipse(self.rect().adjusted(1, 1, -1, -1))

        arc = QRectF(RING + 3, RING + 3, SIZE - 2 * RING - 6, SIZE - 2 * RING - 6)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(255, 255, 255, 40), RING))
        p.drawEllipse(arc)
        colour = QColor("#8a8f99") if self._cancelling else self._colour
        p.setPen(QPen(colour, RING, Qt.SolidLine, Qt.RoundCap))
        if self._value is None:
            p.drawArc(arc, (90 - self._spin) * 16, -100 * 16)
        else:
            p.drawArc(arc, 90 * 16, int(-360 * 16 * self._value))

        p.setPen(QColor(240, 242, 247))
        if self._hover and not self._cancelling:
            big, small = "✕", "Cancel"
        else:
            big = "" if self._value is None else f"{round(self._value * 100)}%"
            small = self._label
        p.setFont(QFont("Segoe UI", 10, QFont.Bold))
        p.drawText(self.rect().adjusted(0, -8, 0, -8), Qt.AlignCenter, big)
        p.setFont(QFont("Segoe UI", 7, QFont.DemiBold))
        shift = 14 if big else 0
        p.drawText(self.rect().adjusted(0, shift, 0, shift), Qt.AlignCenter, small)
        p.end()
