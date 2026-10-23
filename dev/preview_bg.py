"""Dev check: render the Image ring for a JPG and a cut-out on a checkerboard."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
out = Path(sys.argv[1])
cutout = Path(sys.argv[2])

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication
app = QApplication([])
from PIL import Image

from ring import RingOverlay
r = RingOverlay()
r.show_at(QPoint(600, 500))
r._open_anim.setCurrentTime(1000)
r._files, r._src_exts = [Path("photo.jpg")], {"jpg"}
r._category = "Image"
r._ring2_anim.setCurrentTime(1000)
r._hover = [b for b in r._format_buttons() if b.key == "png-transparent"][0]
r.grab().save(str(out / "ring_bg.png"))

im = Image.open(cutout).convert("RGBA")
board = Image.new("RGBA", im.size, "white")
for y in range(0, im.height, 20):
    for x in range(0, im.width, 20):
        if (x // 20 + y // 20) % 2:
            board.paste((200, 200, 200, 255), (x, y, x + 20, y + 20))
Image.alpha_composite(board, im).save(out / "cutout_preview.png")
