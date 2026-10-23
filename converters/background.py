"""Background removal: any photo to a PNG with a transparent background.

Uses the IS-Net "general use" segmentation model (Apache-2.0, the one rembg
ships) run with ONNX Runtime. The model (~170 MB) isn't bundled with the
installer: it's downloaded once, on first use, to
%LOCALAPPDATA%\\FileRing\\models and checked against MODEL_SHA256.
"""
import hashlib
import os
import threading
import urllib.request
from pathlib import Path

from . import Cancelled, image

CATEGORY = "Image"
SOURCES = {"png", "jpg", "webp", "bmp", "gif", "tiff", "heic"}
TARGETS = {"png-transparent"}
REPORTS_PROGRESS = True

MODEL_URL = ("https://github.com/danielgatis/rembg/releases/download/v0.0.0/"
             "isnet-general-use.onnx")
MODEL_SHA256 = "60920e99c45464f2ba57bee2ad08c919a52bbf852739e96947fbb4358c0d964a"
MODEL_SIZE = 178_648_008
MODEL_PATH = (Path(os.environ.get("LOCALAPPDATA", Path.home())) / "FileRing" / "models"
              / "isnet-general-use.onnx")
INPUT_SIZE = 1024
MEAN = (0.485, 0.456, 0.406)
DOWNLOAD_SHARE = 0.8     # part of the progress ring a first-time download takes

_session = None
_session_lock = threading.Lock()   # two drops at once mustn't both download


def _download(progress, cancel):
    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    part = MODEL_PATH.with_suffix(".part")
    sha = hashlib.sha256()
    done = 0
    try:
        with urllib.request.urlopen(MODEL_URL, timeout=30) as response, part.open("wb") as f:
            while chunk := response.read(1 << 20):
                if cancel and cancel.is_set():
                    raise Cancelled()
                f.write(chunk)
                sha.update(chunk)
                done += len(chunk)
                if progress:
                    progress(DOWNLOAD_SHARE * done / MODEL_SIZE)
    except OSError as exc:
        part.unlink(missing_ok=True)
        raise RuntimeError("Couldn't download the background-removal model (170 MB, "
                           "only needed once). Check your internet connection and "
                           "try again.") from exc
    except Cancelled:
        part.unlink(missing_ok=True)
        raise
    if sha.hexdigest() != MODEL_SHA256:
        part.unlink(missing_ok=True)
        raise RuntimeError("The background-removal model didn't download correctly. "
                           "Please try again.")
    part.replace(MODEL_PATH)


def _get_session(progress, cancel):
    global _session
    with _session_lock:
        if _session is None:
            if not MODEL_PATH.exists() or MODEL_PATH.stat().st_size != MODEL_SIZE:
                _download(progress, cancel)
            import onnxruntime
            _session = onnxruntime.InferenceSession(
                str(MODEL_PATH), providers=["CPUExecutionProvider"])
    return _session


def convert(src: Path, dst: Path, progress=None, cancel=None) -> None:
    import numpy as np
    from PIL import Image, ImageOps
    image._imports()   # Pillow plus the HEIC opener

    session = _get_session(progress, cancel)
    if progress:
        progress(0.85)
    with Image.open(src) as im:
        photo = ImageOps.exif_transpose(im).convert("RGB")

    # Same preprocessing as rembg uses for this model.
    x = np.asarray(photo.resize((INPUT_SIZE, INPUT_SIZE), Image.LANCZOS), dtype=np.float32)
    x = x / max(float(x.max()), 1e-6) - np.array(MEAN, dtype=np.float32)
    tensor = x.transpose(2, 0, 1)[None]
    pred = session.run(None, {session.get_inputs()[0].name: tensor})[0][0, 0]
    pred = (pred - pred.min()) / max(float(pred.max() - pred.min()), 1e-6)

    mask = Image.fromarray((pred * 255).astype(np.uint8)).resize(photo.size, Image.LANCZOS)
    cutout = photo.convert("RGBA")
    cutout.putalpha(mask)
    cutout.save(dst, "PNG", optimize=True)
    if progress:
        progress(1.0)
