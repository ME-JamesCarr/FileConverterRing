"""Categories, target formats and file-extension helpers."""
import os
from pathlib import Path


def _pictures_dir() -> Path:
    """The OneDrive Pictures folder if OneDrive is set up, otherwise the local one."""
    onedrive = os.environ.get("OneDrive")
    if onedrive and (Path(onedrive) / "Pictures").is_dir():
        return Path(onedrive) / "Pictures"
    return Path.home() / "Pictures"


DEFAULT_OUTPUT_DIR = _pictures_dir() / "Converted"

# Where converted files go. Set from the user's settings at startup.
OUTPUT_DIR = DEFAULT_OUTPUT_DIR
SAVE_NEXT_TO_ORIGINAL = False

CATEGORIES = ["Image", "Document", "Data", "Media", "Other"]

# Formats offered in Ring 2 for each category (in display order).
TARGETS = {
    "Image": ["png", "jpg", "webp", "bmp", "gif", "tiff", "ico", "pdf"],
    "Document": ["txt", "md", "html", "docx", "odt", "rtf", "epub", "pdf"],
    "Data": ["csv", "tsv", "json", "xlsx", "yaml", "xml", "toml"],
    "Media": ["mp3", "wav", "flac", "ogg", "m4a", "aac",
              "mp4", "mkv", "mov", "avi", "webm", "gif"],
    "Other": ["zip", "7z", "tar.gz", "ttf", "otf", "woff2"],
}

CATEGORY_COLOURS = {
    "Image": "#4f8cff",
    "Document": "#f2a33a",
    "Data": "#3cc48a",
    "Media": "#e0559a",
    "Other": "#9b7bf0",
}

# Alternative spellings normalised to one canonical extension.
ALIASES = {
    "jpeg": "jpg", "jpe": "jpg", "jfif": "jpg",
    "tif": "tiff",
    "heif": "heic",
    "yml": "yaml",
    "htm": "html",
    "markdown": "md",
    "tgz": "tar.gz",
}


def ext_of(path: Path) -> str:
    """Canonical lower-case extension without the dot, e.g. 'jpg' or 'tar.gz'."""
    name = path.name.lower()
    if name.endswith(".tar.gz"):
        return "tar.gz"
    ext = path.suffix.lower().lstrip(".")
    return ALIASES.get(ext, ext)


def stem_of(path: Path) -> str:
    if path.name.lower().endswith(".tar.gz"):
        return path.name[:-7]
    return path.stem


def output_path(src: Path, target_ext: str) -> Path:
    """Where src converted to target_ext goes, never overwriting an existing file."""
    folder = src.parent if SAVE_NEXT_TO_ORIGINAL else OUTPUT_DIR
    return unique_path(folder, stem_of(src), target_ext)


def unique_path(folder: Path, stem: str, target_ext: str) -> Path:
    """folder/stem.ext, or 'stem (n).ext' if that name is taken."""
    folder.mkdir(parents=True, exist_ok=True)
    candidate = folder / f"{stem}.{target_ext}"
    n = 1
    while candidate.exists():
        candidate = folder / f"{stem} ({n}).{target_ext}"
        n += 1
    return candidate
