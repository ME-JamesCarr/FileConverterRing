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
    "Image": ["png", "png-transparent", "jpg", "webp", "bmp", "gif", "tiff", "ico", "pdf"],
    "Document": ["txt", "md", "html", "docx", "odt", "rtf", "epub", "pdf"],
    "Data": ["csv", "tsv", "json", "xlsx", "yaml", "xml", "toml"],
    "Media": ["mp3", "wav", "flac", "ogg", "m4a", "aac",
              "mp4", "mkv", "mov", "avi", "webm", "gif"],
    "Other": ["zip", "7z", "tar.gz", "ttf", "otf", "woff2"],
}

# Targets that aren't simply a file extension: key -> (extension, suffix added
# to the file name, label on the ring button, longer name for messages).
SPECIAL_TARGETS = {
    "png-transparent": ("png", " (transparent)", "PNG\nNO BG", "PNG, background removed"),
}


def target_ext(target: str) -> str:
    return SPECIAL_TARGETS[target][0] if target in SPECIAL_TARGETS else target


def button_label(target: str) -> str:
    return SPECIAL_TARGETS[target][2] if target in SPECIAL_TARGETS else target.upper()


def target_name(target: str) -> str:
    return SPECIAL_TARGETS[target][3] if target in SPECIAL_TARGETS else target.upper()


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


FOLDER = "folder"   # what kind_of() calls a dragged folder


def kind_of(path: Path) -> str:
    """The file's canonical extension, or FOLDER for a folder."""
    return FOLDER if path.is_dir() else ext_of(path)


def output_path(src: Path, target: str) -> Path:
    """Where src converted to target goes, never overwriting an existing file."""
    folder = src.parent if SAVE_NEXT_TO_ORIGINAL else OUTPUT_DIR
    suffix = SPECIAL_TARGETS[target][1] if target in SPECIAL_TARGETS else ""
    return unique_path(folder, stem_of(src) + suffix, target_ext(target))


def combined_output_path(srcs: list[Path], target: str) -> Path:
    """Where several files/folders combined into one file (e.g. a ZIP) go.

    One item keeps its own name (Photos -> Photos.zip); several are named
    after the folder they came from (5 files from Invoices -> Invoices.zip).
    """
    first = srcs[0]
    if len(srcs) == 1:
        stem = first.name if first.is_dir() else stem_of(first)
    else:
        stem = first.parent.name or "Archive"   # a drive root has no name
    folder = first.parent if SAVE_NEXT_TO_ORIGINAL else OUTPUT_DIR
    return unique_path(folder, stem, target_ext(target))


def unique_path(folder: Path, stem: str, target_ext: str) -> Path:
    """folder/stem.ext, or 'stem (n).ext' if that name is taken."""
    folder.mkdir(parents=True, exist_ok=True)
    candidate = folder / f"{stem}.{target_ext}"
    n = 1
    while candidate.exists():
        candidate = folder / f"{stem} ({n}).{target_ext}"
        n += 1
    return candidate
