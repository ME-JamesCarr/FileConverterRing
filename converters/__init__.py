"""Converter registry.

Each converter module exposes CATEGORY (the ring it belongs to), SOURCES,
TARGETS (sets of canonical extensions) and convert(src: Path, dst: Path).
convert() may return a list of paths when it writes several files
(e.g. one per PDF page); otherwise dst is the output.
Optional: supports(src_ext, target_ext) to rule out particular pairs, and
REPORTS_PROGRESS = True if convert() also takes progress(fraction) and a
cancel threading.Event (raising Cancelled when it is set).
Add a new module to _MODULES to register it.
"""
from pathlib import Path

from formats import CATEGORIES, TARGETS, ext_of, output_path, target_name


class Cancelled(Exception):
    """The user cancelled the conversion. Defined before the converter imports
    below, because they import it from here."""


from . import background, data, document, image, media, pdf_pages  # noqa: E402

_MODULES = [image, background, pdf_pages, document, data, media]


def _find(src_ext: str, target_ext: str, category: str):
    if src_ext == target_ext:
        return None
    for mod in _MODULES:
        if (mod.CATEGORY == category and src_ext in mod.SOURCES
                and target_ext in mod.TARGETS
                and getattr(mod, "supports", lambda s, t: True)(src_ext, target_ext)):
            return mod
    return None


def can_convert(src_ext: str, target_ext: str, category: str) -> bool:
    return _find(src_ext, target_ext, category) is not None


def enabled_targets(src_exts: set[str], category: str) -> list[str]:
    """Targets in this category that every one of the given source types can become."""
    return [t for t in TARGETS[category]
            if src_exts and all(can_convert(s, t, category) for s in src_exts)]


def enabled_categories(src_exts: set[str]) -> set[str]:
    return {c for c in CATEGORIES if enabled_targets(src_exts, c)}


def convert(src: Path, target_ext: str, category: str, progress=None,
            cancel=None) -> list[Path]:
    mod = _find(ext_of(src), target_ext, category)
    if mod is None:
        raise ValueError(f"Can't convert {src.name} to {target_name(target_ext)}")
    dst = output_path(src, target_ext)
    try:
        if getattr(mod, "REPORTS_PROGRESS", False):
            written = mod.convert(src, dst, progress, cancel)
        else:
            written = mod.convert(src, dst)
    except Exception:
        dst.unlink(missing_ok=True)  # don't leave a half-written file behind
        raise
    return written or [dst]
