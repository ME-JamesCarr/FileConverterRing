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


def _check_zip(src: Path, converters) -> tuple[bool, str]:
    """Several files and a folder dropped on ZIP make one archive holding all of them."""
    import zipfile
    folder = src / "Reports"
    (folder / "2026" / "empty").mkdir(parents=True, exist_ok=True)
    (folder / "2026" / "q1.txt").write_text("quarter one\n" * 200)
    outs, errors = converters.run_job([src / "photo.png", src / "notes.md", folder],
                                      "zip", "Other")
    if errors or len(outs) != 1:
        return False, f"outputs {outs}, errors {errors}"
    with zipfile.ZipFile(outs[0]) as zf:
        names = sorted(zf.namelist())
        intact = zf.testzip() is None
    expected = ["Reports/2026/empty/", "Reports/2026/q1.txt", "notes.md", "photo.png"]
    return intact and names == expected, f"{outs[0].name}: {names}"


def _check_merge(src: Path, converters) -> tuple[bool, str]:
    """A PDF, an image, a Word file and a photo merge into one PDF, one page each."""
    import pymupdf
    files = [src / "notes.pdf", src / "photo.png", src / "notes.docx", src / "subject.jpg"]
    outs, errors = converters.run_job(files, "pdf-merged", "Document")
    if errors or len(outs) != 1:
        return False, f"outputs {outs}, errors {errors}"
    with pymupdf.open(outs[0]) as doc:
        pages = doc.page_count
    return pages == 4, f"{outs[0].name}: {pages} pages"


def _check_compress(src: Path, converters) -> list[tuple[str, tuple[bool, str]]]:
    """Big photo, PDF, video and audio files each come out under the limit."""
    import os
    import subprocess
    import formats
    import pymupdf
    from PIL import Image
    from converters import media

    noise = Image.frombytes("RGB", (2400, 1600), os.urandom(2400 * 1600 * 3))
    noise.save(src / "big photo.jpg", quality=95)
    pdf = pymupdf.open()
    pdf.new_page().insert_image(pymupdf.Rect(36, 36, 559, 806), filename=src / "big photo.jpg")
    pdf.save(src / "big scan.pdf")
    ff = [media.FFMPEG, "-hide_banner", "-loglevel", "error", "-y"]
    flags = subprocess.CREATE_NO_WINDOW
    subprocess.run(ff + ["-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30:duration=20",
                         "-f", "lavfi", "-i", "sine=duration=20", "-c:v", "libx264", "-crf", "8",
                         "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
                         str(src / "big video.mp4")], check=True, creationflags=flags)
    subprocess.run(ff + ["-f", "lavfi", "-i", "sine=duration=90", "-c:a", "libmp3lame",
                         "-b:a", "320k", str(src / "big song.mp3")], check=True, creationflags=flags)

    results = []
    for name, category, mb in [("big photo.jpg", "Image", 1), ("big scan.pdf", "Document", 1),
                               ("big video.mp4", "Media", 2), ("big song.mp3", "Media", 1),
                               ("tone.mp3", "Media", 1)]:
        formats.COMPRESS_MB = mb
        path = src / name
        before = path.stat().st_size / 2**20
        outs, errors = converters.run_job([path], "compress", category)
        if name == "tone.mp3":   # already small: left alone, with a note
            ok = not outs and errors and "already under" in errors[0]
            results.append((f"{name} -> compress {mb} MB", (bool(ok), f"note: {errors}")))
            continue
        if errors or not outs:
            results.append((f"{name} -> compress {mb} MB", (False, f"errors {errors}")))
            continue
        after = outs[0].stat().st_size / 2**20
        results.append((f"{name} -> compress {mb} MB",
                        (after <= mb, f"{before:.1f} MB -> {outs[0].name} {after:.2f} MB")))
    formats.COMPRESS_MB = 10.0
    return results


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
            ok, detail = _check_zip(src, converters)
            lines.append(f"{'ok  ' if ok else 'FAIL'} 2 files + folder -> zip: {detail}")
            failures[0] += not ok
            for label, (ok, detail) in [("merge 4 files -> pdf", _check_merge(src, converters)),
                                        *_check_compress(src, converters)]:
                lines.append(f"{'ok  ' if ok else 'FAIL'} {label}: {detail}")
                failures[0] += not ok
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
