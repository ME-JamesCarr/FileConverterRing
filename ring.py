"""The two-ring overlay that appears around the cursor.

Ring 1 holds the categories. Holding a dragged file over a category for a
moment opens Ring 2: an arc of formats fanned out from that category.
Dropping on a format emits convertRequested.
"""
import math
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import (QEasingCurve, QPoint, QPointF, Qt, QTimer,
                            QVariantAnimation, Signal)
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget

import converters
from formats import CATEGORIES, CATEGORY_COLOURS, TARGETS, button_label, ext_of

R1, B1 = 88, 34     # ring 1: radius, button radius
R2, B2 = 178, 27    # ring 2: radius, button radius
HUB = 42
PAD = 16
SIZE = 2 * (R2 + B2 + PAD)

DWELL_MS = 280                 # hover time over a category before Ring 2 opens
DRAG_LEAVE_CLOSE_MS = 1200     # close this long after a drag leaves the ring
IDLE_CLOSE_MS = 20000          # close if nothing is dragged in

DISABLED = QColor("#5a5d66")
BACKDROP = QColor(18, 20, 26, 170)


@dataclass
class Button:
    kind: str        # "category" or "format"
    key: str
    centre: QPointF
    radius: float
    enabled: bool
    colour: QColor


def _anim(widget):
    a = QVariantAnimation(widget, startValue=0.0, endValue=1.0, duration=170,
                          easingCurve=QEasingCurve.OutCubic)
    a.valueChanged.connect(widget.update)
    return a


def _progress(anim) -> float:
    v = anim.currentValue()
    return 1.0 if v is None else float(v)


class RingOverlay(QWidget):
    convertRequested = Signal(list, str, str)   # [Path], target ext, category

    def __init__(self):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAcceptDrops(True)
        self.setMouseTracking(True)
        self.setFixedSize(SIZE, SIZE)
        self._centre = QPointF(SIZE / 2, SIZE / 2)
        self._files: list[Path] = []
        self._src_exts: set[str] = set()
        self._category: str | None = None
        self._hover: Button | None = None
        self._dwell = QTimer(self, singleShot=True, interval=DWELL_MS,
                             timeout=self._open_hovered_category)
        self._leave = QTimer(self, singleShot=True, interval=DRAG_LEAVE_CLOSE_MS,
                             timeout=self.close_ring)
        self._idle = QTimer(self, singleShot=True, interval=IDLE_CLOSE_MS,
                            timeout=self.close_ring)
        self._open_anim = _anim(self)
        self._ring2_anim = _anim(self)

    # ---- showing / hiding -------------------------------------------------

    def show_at(self, pos: QPoint):
        if self.isVisible():
            here = self.pos() + QPoint(SIZE // 2, SIZE // 2)
            if (pos - here).manhattanLength() < 60:
                self.close_ring()   # pressing the hotkey again on the ring toggles it off
                return
        self._reset()
        self.move(pos.x() - SIZE // 2, pos.y() - SIZE // 2)
        self.show()
        self.raise_()
        self.activateWindow()
        self._open_anim.start()
        self._idle.start()

    def close_ring(self):
        self.hide()
        self._reset()

    def _reset(self):
        for t in (self._dwell, self._leave, self._idle):
            t.stop()
        self._files, self._src_exts = [], set()
        self._category, self._hover = None, None

    # ---- layout -------------------------------------------------------------

    def _enabled_categories(self) -> set[str]:
        if not self._files:
            return set(CATEGORIES)
        return converters.enabled_categories(self._src_exts)

    @staticmethod
    def _category_angle(i: int) -> float:
        return -math.pi / 2 + 2 * math.pi * i / len(CATEGORIES)

    def _category_buttons(self) -> list[Button]:
        enabled = self._enabled_categories()
        out = []
        for i, cat in enumerate(CATEGORIES):
            a = self._category_angle(i)
            c = self._centre + QPointF(math.cos(a), math.sin(a)) * R1
            out.append(Button("category", cat, c, B1, cat in enabled,
                              QColor(CATEGORY_COLOURS[cat])))
        return out

    def _format_buttons(self) -> list[Button]:
        cat = self._category
        if not cat:
            return []
        targets = TARGETS[cat]
        enabled = (set(converters.enabled_targets(self._src_exts, cat))
                   if self._files else set(targets))
        n = len(targets)
        step = (2 * B2 + 10) / R2
        if n * step >= 2 * math.pi:
            step = 2 * math.pi / n
        anchor = self._category_angle(CATEGORIES.index(cat))
        start = anchor - step * (n - 1) / 2
        out = []
        for i, ext in enumerate(targets):
            a = start + step * i
            c = self._centre + QPointF(math.cos(a), math.sin(a)) * R2
            out.append(Button("format", ext, c, B2, ext in enabled,
                              QColor(CATEGORY_COLOURS[cat])))
        return out

    def _hit(self, pos: QPointF) -> Button | None:
        for b in self._format_buttons() + self._category_buttons():
            d = b.centre - pos
            if math.hypot(d.x(), d.y()) <= b.radius + 4:
                return b
        return None

    # ---- hover / dwell ------------------------------------------------------

    def _update_hover(self, pos: QPointF):
        b = self._hit(pos)
        same = (b and self._hover and b.kind == self._hover.kind and b.key == self._hover.key)
        if same or (b is None and self._hover is None):
            return
        self._hover = b
        self._dwell.stop()
        if b and b.kind == "category" and b.enabled and b.key != self._category:
            self._dwell.start()
        self.update()

    def _open_hovered_category(self):
        b = self._hover
        if b and b.kind == "category" and b.enabled:
            self._category = b.key
            self._ring2_anim.start()
            self.update()

    # ---- drag and drop ------------------------------------------------------

    def dragEnterEvent(self, e):
        paths = [Path(u.toLocalFile()) for u in e.mimeData().urls() if u.isLocalFile()]
        paths = [p for p in paths if p.is_file()]
        if not paths:
            e.ignore()
            return
        self._leave.stop()
        self._idle.stop()
        self._files = paths
        self._src_exts = {ext_of(p) for p in paths}
        enabled = self._enabled_categories()
        if self._category not in enabled:
            self._category = None
        if self._category is None and len(enabled) == 1:
            self._category = next(iter(enabled))   # only one choice: open it straight away
            self._ring2_anim.start()
        # Always copy: a "move" result would make Explorer delete the original.
        e.setDropAction(Qt.CopyAction)
        e.accept()
        self._update_hover(e.position())
        self.update()

    def dragMoveEvent(self, e):
        self._update_hover(e.position())
        b = self._hover
        if b and b.kind == "format" and b.enabled:
            e.setDropAction(Qt.CopyAction)
            e.accept()
        else:
            e.ignore()

    def dragLeaveEvent(self, e):
        self._hover = None
        self._dwell.stop()
        self._leave.start()
        self.update()

    def dropEvent(self, e):
        b = self._hit(e.position())
        if not (b and b.kind == "format" and b.enabled):
            e.ignore()
            return
        e.setDropAction(Qt.CopyAction)
        e.accept()
        files, category = list(self._files), self._category
        self.close_ring()
        self.convertRequested.emit(files, b.key, category)

    # ---- mouse / keyboard (no drag) ----------------------------------------

    def mouseMoveEvent(self, e):
        self._update_hover(e.position())

    def mousePressEvent(self, e):
        d = e.position() - self._centre
        on_hub = math.hypot(d.x(), d.y()) <= HUB
        if e.button() == Qt.RightButton or on_hub or self._hit(e.position()) is None:
            self.close_ring()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.close_ring()

    # ---- painting -----------------------------------------------------------

    def paintEvent(self, _):
        t = _progress(self._open_anim)
        t2 = _progress(self._ring2_anim) if self._category else 0.0
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setOpacity(t)
        p.translate(self._centre)
        p.scale(0.7 + 0.3 * t, 0.7 + 0.3 * t)
        p.translate(-self._centre)

        # Backdrop disc. It must be non-transparent everywhere we want drags,
        # because Windows lets fully transparent pixels fall through.
        inner, outer = R1 + B1 + 12, R2 + B2 + 10
        r = inner + (outer - inner) * t2
        p.setPen(Qt.NoPen)
        p.setBrush(BACKDROP)
        p.drawEllipse(self._centre, r, r)

        self._paint_hub(p)
        for b in self._category_buttons():
            self._paint_button(p, b, b.key, 9, 1.0)
        if self._category:
            origin = self._category_buttons()[CATEGORIES.index(self._category)].centre
            for b in self._format_buttons():
                b.centre = origin + (b.centre - origin) * t2
                label = button_label(b.key)
                self._paint_button(p, b, label, 8 if len(label) > 4 else 9, t2)
        p.end()

    def _paint_hub(self, p: QPainter):
        p.setPen(QPen(QColor(255, 255, 255, 60), 1.5))
        p.setBrush(QColor(255, 255, 255, 18))
        p.drawEllipse(self._centre, HUB, HUB)
        if self._hover and self._hover.kind == "format" and self._hover.enabled:
            text = f"→ {button_label(self._hover.key)}"
        elif len(self._files) == 1:
            text = ext_of(self._files[0]).upper() or "FILE"
        elif self._files:
            text = f"{len(self._files)} files"
        else:
            text = "Drag a\nfile here"
        p.setPen(QColor(235, 238, 245))
        p.setFont(QFont("Segoe UI", 8 if "\n" in text else 10, QFont.DemiBold))
        box = p.boundingRect(0, 0, 2 * HUB, 2 * HUB, Qt.AlignCenter, text)
        box.moveCenter(self._centre.toPoint())
        p.drawText(box, Qt.AlignCenter, text)

    def _paint_button(self, p: QPainter, b: Button, label: str, pt: int, opacity: float):
        hovered = (self._hover is not None and self._hover.kind == b.kind
                   and self._hover.key == b.key)
        active = b.kind == "category" and b.key == self._category
        r = b.radius * (1.12 if hovered and b.enabled else 1.0)
        p.save()
        p.setOpacity(p.opacity() * opacity * (1.0 if b.enabled else 0.45))
        fill = QColor(b.colour) if b.enabled else QColor(DISABLED)
        if b.kind == "format" and b.enabled:
            fill = fill.darker(115)
        if hovered and b.enabled:
            fill = fill.lighter(118)
        outline = QPen(QColor(255, 255, 255, 230), 2.5) if (hovered or active) and b.enabled \
            else QPen(QColor(255, 255, 255, 40), 1)
        p.setPen(outline)
        p.setBrush(fill)
        p.drawEllipse(b.centre, r, r)
        p.setPen(QColor("white"))
        p.setFont(QFont("Segoe UI", pt, QFont.Bold))
        rect = p.boundingRect(0, 0, int(2 * r), int(2 * r), Qt.AlignCenter, label)
        rect.moveCenter(b.centre.toPoint())
        p.drawText(rect, Qt.AlignCenter, label)
        p.restore()
