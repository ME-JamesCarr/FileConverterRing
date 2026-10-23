"""Image conversions with Pillow (HEIC via pillow-heif, SVG rendered by Qt)."""
from __future__ import annotations

from pathlib import Path

from formats import ext_of

Image = ImageOps = ImageSequence = None   # loaded by _imports()


def _imports():
    """Load Pillow on first use, so the tray app that reads SOURCES/TARGETS stays small."""
    global Image, ImageOps, ImageSequence
    if Image is None:
        import pillow_heif
        from PIL import Image, ImageOps, ImageSequence
        pillow_heif.register_heif_opener()


CATEGORY = "Image"
SOURCES = {"png", "jpg", "webp", "bmp", "gif", "tiff", "ico", "heic", "svg"}
TARGETS = {"png", "jpg", "webp", "bmp", "gif", "tiff", "ico", "pdf"}

# Formats that can hold several frames/pages.
MULTI_FRAME = {"gif", "webp", "tiff", "pdf"}
NO_ALPHA = {"jpg", "bmp", "pdf"}
PIL_FORMAT = {"jpg": "JPEG", "tiff": "TIFF", "png": "PNG", "webp": "WEBP",
              "bmp": "BMP", "gif": "GIF", "ico": "ICO", "pdf": "PDF"}
SVG_MIN_SIDE = 1024


def _render_svg(src: Path) -> Image.Image:
    from PySide6.QtCore import QSize
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer

    renderer = QSvgRenderer(str(src))
    if not renderer.isValid():
        raise ValueError(f"{src.name} is not a valid SVG")
    size = renderer.defaultSize()
    if size.isEmpty():
        size = QSize(SVG_MIN_SIDE, SVG_MIN_SIDE)
    longest = max(size.width(), size.height())
    if longest < SVG_MIN_SIDE:
        size = size * (SVG_MIN_SIDE / longest)
    img = QImage(size, QImage.Format_RGBA8888)
    img.fill(0)
    painter = QPainter(img)
    renderer.render(painter)
    painter.end()
    return Image.frombuffer("RGBA", (img.width(), img.height()), bytes(img.constBits()),
                            "raw", "RGBA", img.bytesPerLine(), 1).copy()


def _normalise(frame: Image.Image, target: str) -> Image.Image:
    if frame.mode not in ("RGB", "RGBA", "L", "LA", "P"):
        frame = frame.convert("RGBA" if "A" in frame.mode else "RGB")
    if target in NO_ALPHA:
        if frame.mode in ("RGBA", "LA", "P"):
            rgba = frame.convert("RGBA")
            flat = Image.new("RGB", rgba.size, "white")
            flat.paste(rgba, mask=rgba.getchannel("A"))
            return flat
        return frame.convert("RGB")
    if target == "ico":
        return frame.convert("RGBA")
    return frame


def convert(src: Path, dst: Path) -> None:
    _imports()
    target = ext_of(dst)
    if ext_of(src) == "svg":
        frames, durations = [_render_svg(src)], []
    else:
        im = Image.open(src)
        frames = [ImageOps.exif_transpose(f.copy()) for f in ImageSequence.Iterator(im)]
        durations = [f.info.get("duration", 100) for f in ImageSequence.Iterator(im)]
        if target not in MULTI_FRAME:
            frames = frames[:1]
    save(frames, dst, durations)


def save(frames: list[Image.Image], dst: Path, durations: list[int] | None = None) -> None:
    """Write one or more frames to dst in the format its extension names."""
    _imports()
    target = ext_of(dst)
    frames = [_normalise(f, target) for f in frames]
    first, rest = frames[0], frames[1:]
    options = {}
    if target == "jpg":
        options = {"quality": 92, "optimize": True}
    elif target == "webp":
        options = {"quality": 90}
    elif target == "ico":
        options = {"sizes": [(s, s) for s in (16, 24, 32, 48, 64, 128, 256)]}
    elif target == "pdf":
        options = {"resolution": 150}

    if rest:
        options.update(save_all=True, append_images=rest)
        if target in ("gif", "webp"):
            options.update(duration=durations, loop=0)
    first.save(dst, PIL_FORMAT[target], **options)
