"""Smoke test of every converter, runnable from the packaged app:

    FileRing.exe --selftest <empty folder>

Writes sample files, converts them, and saves report.txt in that folder.
Exit code is the number of failures.
"""
import json
import subprocess
import threading
import traceback
from pathlib import Path

from PySide6 import QtWebEngineCore  # noqa: F401
from PySide6.QtCore import QCoreApplication, Qt, QTimer
from PySide6.QtWidgets import QApplication

CASES = [
    ("photo.png", ["jpg", "webp", "ico", "pdf"], "Image"),
    ("logo.svg", ["png"], "Image"),
    ("subject.jpg", ["png-transparent"], "Image"),   # downloads the model on first run
    ("notes.md", ["docx", "html", "pdf"], "Document"),
    ("notes.docx", ["pdf", "txt", "odt"], "Document"),
    ("notes.pdf", ["txt", "md", "docx"], "Document"),
    ("notes.pdf", ["png"], "Image"),
    ("people.csv", ["xlsx", "json"], "Data"),
    ("people.xlsx", ["csv", "yaml", "xml", "toml"], "Data"),
    ("tone.mp3", ["wav", "ogg"], "Media"),
    ("clip.mp4", ["mp3", "mov", "gif"], "Media"),
]


def _make_samples(src: Path):
    from PIL import Image, ImageDraw
    import pypandoc
    from converters import media

    im = Image.new("RGBA", (200, 120), (0, 0, 0, 0))
    ImageDraw.Draw(im).ellipse((10, 10, 190, 110), fill=(79, 140, 255, 220))
    im.save(src / "photo.png")
    # A simple figure on a plain light background, for background removal.
    bg = Image.new("RGB", (480, 360), (236, 238, 242))
    d = ImageDraw.Draw(bg)
    d.ellipse((200, 60, 280, 140), fill=(196, 140, 110))               # head
    d.rounded_rectangle((170, 140, 310, 330), 40, fill=(40, 70, 140))  # body
    bg.save(src / "subject.jpg", quality=92)
    (src / "logo.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg" width="40" '
                                  'height="40"><circle cx="20" cy="20" r="18" fill="#e0559a"/></svg>')
    (src / "notes.md").write_text("# Notes\n\nSome **bold** text.\n\n- one\n- two\n\n"
                                  "| A | B |\n|---|---|\n| 1 | 2 |\n", encoding="utf-8")
    pypandoc.convert_file(str(src / "notes.md"), "docx", outputfile=str(src / "notes.docx"))
    (src / "people.csv").write_text("id,name,age\n007,Ann,31\n012,Bob,\n", encoding="utf-8")
    import pandas as pd
    pd.DataFrame({"id": ["007"], "name": ["Ann"]}).to_excel(src / "people.xlsx", index=False)
    ff = [media.FFMPEG, "-hide_banner", "-loglevel", "error", "-y"]
    flags = subprocess.CREATE_NO_WINDOW
    subprocess.run(ff + ["-f", "lavfi", "-i", "sine=duration=2", "-c:a", "libmp3lame",
                         str(src / "tone.mp3")], check=True, creationflags=flags)
    subprocess.run(ff + ["-f", "lavfi", "-i", "testsrc=size=320x240:rate=15:duration=2",
                         "-f", "lavfi", "-i", "sine=duration=2", "-c:v", "libx264",
                         "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
                         str(src / "clip.mp4")], check=True, creationflags=flags)


def _check_cutout(path: Path) -> tuple[bool, str]:
    """The background corner should be see-through and the figure solid."""
    from PIL import Image
    with Image.open(path) as im:
        alpha = im.getchannel("A")
        corner, body = alpha.getpixel((10, 10)), alpha.getpixel((240, 240))
    return corner < 40 and body > 200, f"corner alpha {corner}, subject alpha {body}"


def run(folder: Path) -> int:
    QCoreApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
    app = QApplication.instance() or QApplication([])
    import converters
    import formats
    from converters import pdf_render

    folder.mkdir(parents=True, exist_ok=True)
    src = folder / "samples"
    src.mkdir(exist_ok=True)
    formats.OUTPUT_DIR = folder / "Converted"
    formats.SAVE_NEXT_TO_ORIGINAL = False
    pdf_render.install()
    lines, failures = [], [0]

    def work():
        try:
            _make_samples(src)
            # PDF input is made by our own Markdown -> PDF conversion.
            pdf = converters.convert(src / "notes.md", "pdf", "Document")[0]
            (src / "notes.pdf").write_bytes(pdf.read_bytes())
            for name, targets, category in CASES:
                for t in targets:
                    try:
                        outs = converters.convert(src / name, t, category)
                        sizes = ", ".join(f"{o.name} ({o.stat().st_size} B)" for o in outs)
                        ok = all(o.stat().st_size > 0 for o in outs)
                        if t == "png-transparent":
                            ok, detail = _check_cutout(outs[0])
                            sizes += f" [{detail}]"
                        lines.append(f"{'ok  ' if ok else 'FAIL'} {name} -> {t}: {sizes}")
                        failures[0] += not ok
                    except Exception as exc:
                        lines.append(f"FAIL {name} -> {t}: {type(exc).__name__}: {exc}")
                        failures[0] += 1
        except Exception:
            lines.append("FAIL setup:\n" + traceback.format_exc())
            failures[0] += 1

    worker = threading.Thread(target=work, daemon=True)
    worker.start()
    poll = QTimer(interval=200, timeout=lambda: worker.is_alive() or app.quit())
    poll.start()
    app.exec()
    lines.append(f"\n{failures[0]} failure(s)")
    (folder / "report.txt").write_text("\n".join(lines), encoding="utf-8")
    (folder / "report.json").write_text(json.dumps({"failures": failures[0]}))
    return failures[0]
