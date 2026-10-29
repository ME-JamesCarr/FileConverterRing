"""Converter registry.

Each converter module exposes CATEGORY (the ring it belongs to), SOURCES,
TARGETS (sets of canonical extensions) and convert(src: Path, dst: Path).
convert() may return a list of paths when it writes several files
(e.g. one per PDF page); otherwise dst is the output.
Optional: supports(src_ext, target_ext) to rule out particular pairs, and
REPORTS_PROGRESS = True if convert() also takes progress(fraction) and a
cancel threading.Event (raising Cancelled when it is set).

A module with COMBINES = True turns all the dropped items into one output
(e.g. a ZIP) instead: it has convert_many(srcs, dst, progress, cancel).
SOURCES = ANY accepts any file type, and folders.
Add a new module to _MODULES to register it.
"""
from pathlib import Path

from formats import (CATEGORIES, TARGETS, combined_output_path, kind_of, output_path,
                     target_name)

ANY = "*"


class Cancelled(Exception):
    """The user cancelled the conversion. Defined before the converter imports
    below, because they import it from here."""


from . import archive, background, data, document, image, media, pdf_pages  # noqa: E402

_MODULES = [image, background, pdf_pages, document, data, media, archive]


def _find(src_ext: str, target_ext: str, category: str):
    for mod in _MODULES:
        combines = getattr(mod, "COMBINES", False)
        if src_ext == target_ext and not combines:   # a ZIP can go inside a ZIP
            continue
        if (mod.CATEGORY == category
                and (mod.SOURCES == ANY or src_ext in mod.SOURCES)
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
    mod = _find(kind_of(src), target_ext, category)
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


def run_job(srcs: list[Path], target: str, category: str, progress=None,
            cancel=None) -> tuple[list[Path], list[str]]:
    """Convert everything dropped in one go. Returns (outputs, error messages).

    Most converters handle each file separately; a COMBINES converter makes
    one output from all of them. Stops early (without an error) if cancelled.
    """
    report = progress or (lambda _: None)
    mod = _find(kind_of(srcs[0]), target, category)
    if mod is not None and getattr(mod, "COMBINES", False):
        dst = combined_output_path(srcs, target)
        try:
            mod.convert_many(srcs, dst, report, cancel)
            return [dst], []
        except Exception as exc:
            dst.unlink(missing_ok=True)
            return [], [] if isinstance(exc, Cancelled) else [str(exc)]

    outputs, errors = [], []
    n = len(srcs)
    for i, src in enumerate(srcs):
        if cancel and cancel.is_set():
            break
        try:
            outputs += convert(src, target, category,
                               lambda frac, i=i: report((i + frac) / n), cancel)
        except Cancelled:
            break
        except Exception as exc:
            errors.append(f"{src.name}: {exc}")
    return outputs, errors
