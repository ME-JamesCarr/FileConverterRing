"""Merge into PDF: PDFs, images and documents dropped together become one PDF.

Files are taken in natural name order ("page 2" before "page 10"), since
Explorer doesn't pass on the order they were selected in. Images go on A4
pages (landscape for wide images); documents are converted to PDF first.
"""
import io
import re
import tempfile
from pathlib import Path

from formats import ext_of
from . import Cancelled, document, image

CATEGORY = "Document"
IMAGES = image.SOURCES
DOCUMENTS = document.SOURCES - {"pdf"}
SOURCES = {"pdf"} | IMAGES | DOCUMENTS
TARGETS = {"pdf-merged"}
COMBINES = True

A4 = (595, 842)        # points
MARGIN = 28


def _natural(path: Path):
    return [int(part) if part.isdigit() else part.lower()
            for part in re.split(r"(\d+)", path.name)]


def _add_image(out, src: Path):
    import pymupdf
    image._imports()
    from PIL import ImageOps
    if ext_of(src) == "svg":
        pic = image._render_svg(src)
    else:
        with image.Image.open(src) as im:
            pic = ImageOps.exif_transpose(im)
            pic.load()
    has_alpha = pic.mode in ("RGBA", "LA", "P")
    pic = pic.convert("RGBA" if has_alpha else "RGB")
    data = io.BytesIO()
    pic.save(data, "PNG" if has_alpha else "JPEG", quality=90)
    width, height = A4 if pic.height >= pic.width else A4[::-1]
    page = out.new_page(width=width, height=height)
    box = pymupdf.Rect(MARGIN, MARGIN, width - MARGIN, height - MARGIN)
    page.insert_image(box, stream=data.getvalue(), keep_proportion=True)


def convert_many(srcs: list[Path], dst: Path, progress, cancel) -> None:
    import pymupdf

    files = sorted(srcs, key=_natural)
    out = pymupdf.open()
    with tempfile.TemporaryDirectory() as tmp:
        for i, src in enumerate(files):
            if cancel and cancel.is_set():
                raise Cancelled()
            kind = ext_of(src)
            if kind in IMAGES:
                _add_image(out, src)
            else:
                pdf = src
                if kind in DOCUMENTS:
                    pdf = Path(tmp) / f"{i}.pdf"
                    document.convert(src, pdf)
                with pymupdf.open(pdf) as part:
                    out.insert_pdf(part)
            progress((i + 1) / len(files))
    out.save(dst, garbage=3, deflate=True)
    out.close()
