"""Open File Explorer with files selected (reusing a window already showing that folder)."""
import ctypes
from collections import defaultdict
from ctypes import POINTER, c_uint, c_ulong, c_void_p, c_wchar_p
from pathlib import Path

_shell32 = ctypes.windll.shell32
_shell32.ILCreateFromPathW.argtypes = [c_wchar_p]
_shell32.ILCreateFromPathW.restype = c_void_p
_shell32.ILFindLastID.argtypes = [c_void_p]
_shell32.ILFindLastID.restype = c_void_p
_shell32.ILFree.argtypes = [c_void_p]
_shell32.SHOpenFolderAndSelectItems.argtypes = [c_void_p, c_uint, POINTER(c_void_p), c_ulong]


def reveal(paths: list[Path]):
    """Select every path in Explorer: one window per folder."""
    by_folder: dict[Path, list[Path]] = defaultdict(list)
    for p in paths:
        if p.exists():
            by_folder[p.parent].append(p)
    for folder, files in by_folder.items():
        folder_id = _shell32.ILCreateFromPathW(str(folder))
        file_ids = [_shell32.ILCreateFromPathW(str(f)) for f in files]
        children = (c_void_p * len(file_ids))(*[_shell32.ILFindLastID(i) for i in file_ids])
        try:
            _shell32.SHOpenFolderAndSelectItems(folder_id, len(file_ids), children, 0)
        finally:
            for i in file_ids + [folder_id]:
                _shell32.ILFree(i)


def open_folder(folder: Path):
    import os
    os.startfile(folder)
