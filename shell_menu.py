"""'Convert with FileRing' in the Explorer right-click menu.

Plain registry verbs under HKCU\\Software\\Classes (no admin rights, no
shell-extension DLL). Every file type FileRing can read gets a submenu that
lists only the formats that type can become, grouped by category, plus ZIP.
Folders get ZIP. Until the app is code-signed, Windows 11 shows these under
"Show more options".

Explorer runs a verb's command once per selected file, so the command is a
quick hand-off (FileRing.exe --convert <category> <target> "<file>", see
handoff.py) and the running app gathers the files into one batch.
"""
import ctypes
import hashlib
import sys
import winreg
from pathlib import Path

import converters
from formats import ALIASES, CATEGORIES, FOLDER, TARGETS, target_name

CLASSES = r"Software\Classes"
SIGNATURE_KEY = r"Software\FileRing"     # remembers what was last written
VERB = "FileRing"
MENU_TEXT = "Convert with FileRing"
ECF_SEPARATORBEFORE = 0x20               # CommandFlags: line above this item


def _command() -> str:
    if getattr(sys, "frozen", False):          # packaged FileRing.exe
        return f'"{sys.executable}"'
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    return f'"{pythonw}" "{Path(__file__).with_name("main.py")}"'


def source_kinds() -> list[str]:
    """Every file type some converter reads, plus folders."""
    kinds = {k for mod in converters._MODULES if mod.SOURCES != converters.ANY
             for k in mod.SOURCES}
    return sorted(kinds) + [FOLDER]


def menu_items(kind: str) -> list[tuple[str, str]]:
    """(category, target) pairs offered for this file type, in ring order."""
    return [(c, t) for c in CATEGORIES for t in TARGETS[c] if converters.can_convert(kind, t, c)]


def _menu_bases(root: str) -> list[tuple[str, str]]:
    """(registry key the menu hangs off, file type) for every type and its aliases."""
    bases = []
    for kind in source_kinds():
        if kind == FOLDER:
            bases.append((rf"{root}\Directory", kind))
            continue
        for ext in [kind] + [alias for alias, canon in ALIASES.items() if canon == kind]:
            bases.append((rf"{root}\SystemFileAssociations\.{ext}", kind))
    return bases


def entries(root: str = CLASSES) -> list[tuple[str, dict]]:
    """Every registry key to write, with its values ("" is the default value)."""
    command = _command()
    icon = sys.executable if getattr(sys, "frozen", False) else None
    out = []
    for base, kind in _menu_bases(root):
        items = menu_items(kind)
        if not items:
            continue
        menu = rf"{base}\shell\{VERB}"
        values = {"MUIVerb": MENU_TEXT, "SubCommands": "", "MultiSelectModel": "Player"}
        if icon:
            values["Icon"] = icon
        out.append((menu, values))
        previous = None
        for i, (category, target) in enumerate(items):
            # Subkeys are listed alphabetically, so the number keeps ring order.
            verb = rf"{menu}\shell\{i:02d}-{target}"
            values = {"MUIVerb": target_name(target)}
            if previous and category != previous:
                values["CommandFlags"] = ECF_SEPARATORBEFORE
            out.append((verb, values))
            out.append((rf"{verb}\command",
                        {"": f'{command} --convert {category} {target} "%1"'}))
            previous = category
    return out


def _delete_tree(path: str):
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_ALL_ACCESS) as key:
            while True:
                try:
                    child = winreg.EnumKey(key, 0)
                except OSError:
                    break
                _delete_tree(rf"{path}\{child}")
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path)
    except FileNotFoundError:
        pass


def _notify_explorer():
    SHCNE_ASSOCCHANGED = 0x08000000
    ctypes.windll.shell32.SHChangeNotify(SHCNE_ASSOCCHANGED, 0, None, None)


def unregister(root: str = CLASSES):
    for base, _ in _menu_bases(root):
        _delete_tree(rf"{base}\shell\{VERB}")
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, SIGNATURE_KEY, 0,
                            winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, "ShellMenu")
    except FileNotFoundError:
        pass
    _notify_explorer()


def register(root: str = CLASSES) -> str:
    """Write the menu. Skipped when nothing changed since last time (same exe, same formats).
    Returns what it did, for the log."""
    items = entries(root)
    signature = hashlib.sha256(repr((root, items)).encode()).hexdigest()
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, SIGNATURE_KEY) as key:
            if winreg.QueryValueEx(key, "ShellMenu")[0] == signature:
                return "up to date"
    except FileNotFoundError:
        pass
    unregister(root)   # clears anything stale from an older version
    for path, values in items:
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_SET_VALUE) as key:
            for name, value in values.items():
                kind = winreg.REG_DWORD if isinstance(value, int) else winreg.REG_SZ
                winreg.SetValueEx(key, name, 0, kind, value)
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, SIGNATURE_KEY, 0,
                            winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, "ShellMenu", 0, winreg.REG_SZ, signature)
    _notify_explorer()
    return f"written ({len(items)} keys)"
