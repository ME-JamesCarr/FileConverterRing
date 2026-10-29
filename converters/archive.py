"""Archives: any number of files and folders into one ZIP (Python's zipfile)."""
import os
import zipfile
from pathlib import Path

from formats import ext_of
from . import ANY, Cancelled

CATEGORY = "Other"
SOURCES = ANY
TARGETS = {"zip"}
COMBINES = True

CHUNK = 1 << 20
# Already compressed: storing them as-is is much faster and barely bigger.
STORE = {"jpg", "png", "gif", "webp", "heic", "mp3", "m4a", "aac", "ogg", "flac",
         "mp4", "mkv", "mov", "webm", "avi", "zip", "7z", "gz", "tar.gz", "rar",
         "docx", "xlsx", "pptx", "odt", "epub", "woff2"}


def _unique(name: str, used: set[str]) -> str:
    """'photo.jpg', then 'photo (2).jpg'... (two dropped files can share a name)."""
    stem, dot, ext = name.rpartition(".") if "." in name else (name, "", "")
    candidate, n = name, 2
    while candidate.lower() in used:
        candidate = f"{stem} ({n}){dot}{ext}"
        n += 1
    used.add(candidate.lower())
    return candidate


def _entries(srcs: list[Path], dst: Path) -> tuple[list[tuple[Path, str]], list[str]]:
    """Files to add as (path, name in the archive), plus empty folders to keep."""
    files, empty_dirs, used = [], [], set()
    for src in srcs:
        if not src.is_dir():
            files.append((src, _unique(src.name, used)))
            continue
        top = _unique(src.name, used)
        for root, dirs, names in os.walk(src):
            dirs.sort()
            rel = Path(root).relative_to(src).as_posix()
            prefix = top if rel == "." else f"{top}/{rel}"
            kept = [n for n in sorted(names) if Path(root, n) != dst]   # never zip the ZIP itself
            files += [(Path(root, n), f"{prefix}/{n}") for n in kept]
            if not kept and not dirs:
                empty_dirs.append(prefix + "/")
    return files, empty_dirs


def convert_many(srcs: list[Path], dst: Path, progress, cancel) -> None:
    files, empty_dirs = _entries(srcs, dst)
    total = sum(p.stat().st_size for p, _ in files) or 1
    done = 0
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED, compresslevel=6,
                         strict_timestamps=False) as zf:
        for path, name in files:
            info = zipfile.ZipInfo.from_file(path, name, strict_timestamps=False)
            info.compress_type = (zipfile.ZIP_STORED if ext_of(path) in STORE
                                  else zipfile.ZIP_DEFLATED)
            with path.open("rb") as f, zf.open(info, "w", force_zip64=True) as out:
                while chunk := f.read(CHUNK):
                    if cancel and cancel.is_set():
                        raise Cancelled()
                    out.write(chunk)
                    done += len(chunk)
                    progress(done / total)
        for name in empty_dirs:
            zf.writestr(name, b"")
