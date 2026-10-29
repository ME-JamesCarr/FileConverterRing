"""Compress to size: make a file fit under formats.COMPRESS_MB.

Registers one converter per ring (IMAGE, PDF, MEDIA), all with the
"compress" target:
- photos: the best JPG (or WEBP) quality that fits, scaled down only if needed
- PDFs: embedded images downsampled step by step
- video: MP4 encoded in two passes at the bitrate that fits; audio: MP3
A file already under the limit is left alone (reported, not converted).
"""
import io
import tempfile
from pathlib import Path
from types import SimpleNamespace

import formats
from formats import ext_of
from . import Cancelled, image, media

MB = 1024 * 1024
IMAGE_SOURCES = {"jpg", "png", "webp", "bmp", "tiff", "heic"}
AUDIO_KBPS = 96               # soundtrack bitrate for compressed video
MIN_VIDEO_KBPS = 120          # below this the picture is unwatchable
MIN_AUDIO_KBPS = 32
PDF_STEPS = [(150, 80), (110, 70), (80, 60), (72, 40)]   # (image dpi, JPEG quality)


def _limit() -> int:
    return int(formats.COMPRESS_MB * MB)


def _check_needed(src: Path):
    if src.stat().st_size <= _limit():
        raise ValueError(f"already under {formats.COMPRESS_MB:g} MB, so it was left as it is")


def _too_big(src: Path, smallest: int | None = None) -> RuntimeError:
    best = f" (the smallest it got was {smallest / MB:.1f} MB)" if smallest else ""
    return RuntimeError(f"couldn't get it under {formats.COMPRESS_MB:g} MB{best}. "
                        "Try a bigger size in Settings.")


# ---- photos ------------------------------------------------------------------------

def _image_ext(src_ext: str) -> str:
    return "webp" if src_ext == "webp" else "jpg"


def _compress_image(src: Path, dst: Path, progress=None, cancel=None) -> None:
    _check_needed(src)
    image._imports()
    from PIL import Image, ImageOps

    with Image.open(src) as im:
        picture = ImageOps.exif_transpose(im)
        picture.load()
    webp = ext_of(dst) == "webp"
    picture = picture.convert("RGBA") if webp else image._normalise(picture, "jpg")
    limit = _limit()

    def encode(pic, quality) -> bytes:
        data = io.BytesIO()
        pic.save(data, "WEBP" if webp else "JPEG", quality=quality, optimize=True)
        return data.getvalue()

    scale = 1.0
    for step in range(12):
        if cancel and cancel.is_set():
            raise Cancelled()
        pic = picture if scale == 1.0 else picture.resize(
            (max(1, int(picture.width * scale)), max(1, int(picture.height * scale))),
            Image.LANCZOS)
        best, low, high = None, 35, 92    # binary search for the best quality that fits
        while low <= high:
            quality = (low + high) // 2
            data = encode(pic, quality)
            if len(data) <= limit:
                best, low = data, quality + 1
            else:
                high = quality - 1
        if best:
            dst.write_bytes(best)
            return
        scale *= 0.8
        if progress:
            progress((step + 1) / 12)
    raise _too_big(src)


# ---- PDFs ----------------------------------------------------------------------------

def _compress_pdf(src: Path, dst: Path, progress=None, cancel=None) -> None:
    _check_needed(src)
    import pymupdf

    smallest = None
    for i, (dpi, quality) in enumerate(PDF_STEPS):
        if cancel and cancel.is_set():
            raise Cancelled()
        with pymupdf.open(src) as doc:
            doc.rewrite_images(dpi_threshold=dpi + 10, dpi_target=dpi, quality=quality)
            data = doc.tobytes(garbage=4, deflate=True, clean=True)
        smallest = min(smallest or len(data), len(data))
        if len(data) <= _limit():
            dst.write_bytes(data)
            return
        if progress:
            progress((i + 1) / len(PDF_STEPS))
    raise _too_big(src, smallest)


# ---- audio and video -----------------------------------------------------------------

def _media_ext(src_ext: str) -> str:
    return "mp3" if src_ext in media.AUDIO else "mp4"


def _compress_media(src: Path, dst: Path, progress=None, cancel=None) -> None:
    _check_needed(src)
    duration, has_audio = media._probe(src)
    if not duration:
        raise RuntimeError("couldn't read how long it is")
    budget_kbps = _limit() * 8 / 1000 / duration * 0.93   # leave room for the container

    if ext_of(dst) == "mp3":
        kbps = int(min(budget_kbps, 192))
        if kbps < MIN_AUDIO_KBPS:
            raise _too_big(src)
        media.run_ffmpeg(["-i", str(src), "-vn", "-c:a", "libmp3lame", "-b:a", f"{kbps}k",
                          str(dst)], duration, progress, cancel)
        return

    audio = AUDIO_KBPS if has_audio else 0
    video_kbps = int(budget_kbps - audio)
    if video_kbps < MIN_VIDEO_KBPS:
        raise _too_big(src)
    # Less data means fewer pixels look better than more blurry ones.
    height = 480 if video_kbps < 700 else 720 if video_kbps < 1800 else 1080
    video = ["-c:v", "libx264", "-preset", "medium", "-b:v", f"{video_kbps}k",
             "-vf", f"scale=-2:'min(ih,{height})',scale=trunc(iw/2)*2:trunc(ih/2)*2",
             "-pix_fmt", "yuv420p"]
    with tempfile.TemporaryDirectory() as tmp:
        log = str(Path(tmp) / "pass")
        first = lambda v: progress and progress(v / 2)
        second = lambda v: progress and progress(0.5 + v / 2)
        media.run_ffmpeg(["-i", str(src), *video, "-pass", "1", "-passlogfile", log, "-an",
                          "-f", "mp4", "NUL"], duration, first, cancel)
        sound = ["-c:a", "aac", "-b:a", f"{audio}k"] if audio else ["-an"]
        media.run_ffmpeg(["-i", str(src), *video, "-pass", "2", "-passlogfile", log, *sound,
                          "-movflags", "+faststart", str(dst)], duration, second, cancel)
    if dst.stat().st_size > _limit():
        raise _too_big(src, dst.stat().st_size)


IMAGE = SimpleNamespace(CATEGORY="Image", SOURCES=IMAGE_SOURCES, TARGETS={"compress"},
                        REPORTS_PROGRESS=True, output_ext=_image_ext, convert=_compress_image)
PDF = SimpleNamespace(CATEGORY="Document", SOURCES={"pdf"}, TARGETS={"compress"},
                      REPORTS_PROGRESS=True, output_ext=lambda _: "pdf", convert=_compress_pdf)
MEDIA = SimpleNamespace(CATEGORY="Media", SOURCES=media.AUDIO | media.VIDEO,
                        TARGETS={"compress"}, REPORTS_PROGRESS=True, output_ext=_media_ext,
                        convert=_compress_media)
