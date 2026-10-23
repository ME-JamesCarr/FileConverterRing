"""PDF pages to images (one image per page), rendered with PyMuPDF."""
from pathlib import Path

from formats import ext_of, stem_of, unique_path
from . import image

CATEGORY = "Image"
SOURCES = {"pdf"}
TARGETS = {"png", "jpg", "webp", "bmp", "tiff"}
DPI = 150


def convert(src: Path, dst: Path) -> list[Path]:
    import pymupdf   # imported here so the tray app never loads it
    from PIL import Image

    target = ext_of(dst)
    outputs = []
    with pymupdf.open(src) as doc:
        for i, page in enumerate(doc):
            pix = page.get_pixmap(dpi=DPI, alpha=False)
            frame = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            # A single-page PDF keeps the plain name; longer ones get "- page N".
            path = dst if doc.page_count == 1 else unique_path(
                dst.parent, f"{stem_of(src)} - page {i + 1}", target)
            image.save([frame], path)
            outputs.append(path)
    return outputs
