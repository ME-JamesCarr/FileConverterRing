"""System-wide hotkey using the Win32 RegisterHotKey API.

Runs its own message loop on a background thread and emits `pressed`
(delivered to the Qt main thread as a queued signal). WM_HOTKEY still
arrives while you're dragging a file in Explorer.
"""
import ctypes
import threading
from ctypes import wintypes

from PySide6.QtCore import QObject, Signal

MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x8, 0x4000
WM_HOTKEY, WM_QUIT = 0x0312, 0x0012
_HOTKEY_ID = 1

DEFAULT_HOTKEY = "Ctrl+Alt+R"
_MODIFIERS = {"Ctrl": MOD_CONTROL, "Alt": MOD_ALT, "Shift": MOD_SHIFT, "Meta": MOD_WIN}
_NAMED_KEYS = {"Space": 0x20, "Insert": 0x2D, "Home": 0x24, "End": 0x23,
               "PgUp": 0x21, "PgDown": 0x22, "Pause": 0x13}

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32


def parse_hotkey(text: str) -> tuple[int, int] | None:
    """'Ctrl+Alt+R' (Qt's portable key-sequence text) -> (modifiers, virtual key).

    Returns None unless it has Ctrl, Alt or Win plus a single letter, digit,
    F-key or one of _NAMED_KEYS.
    """
    *mods, key = text.split("+") if text else [""]
    if not key or any(m not in _MODIFIERS for m in mods):
        return None
    modifiers = 0
    for m in mods:
        modifiers |= _MODIFIERS[m]
    if not modifiers & (MOD_CONTROL | MOD_ALT | MOD_WIN):
        return None   # Shift+letter alone would hijack normal typing
    if len(key) == 1 and key.isascii() and key.isalnum():
        vk = ord(key.upper())
    elif key[0] == "F" and key[1:].isdigit() and 1 <= int(key[1:]) <= 24:
        vk = 0x6F + int(key[1:])
    elif key in _NAMED_KEYS:
        vk = _NAMED_KEYS[key]
    else:
        return None
    return modifiers, vk


def display_name(text: str) -> str:
    return text.replace("Meta", "Win")


class GlobalHotkey(QObject):
    pressed = Signal()
    failed = Signal(str)

    def __init__(self, text: str = DEFAULT_HOTKEY):
        super().__init__()
        parsed = parse_hotkey(text) or parse_hotkey(DEFAULT_HOTKEY)
        self.name = display_name(text)
        self._modifiers = parsed[0] | MOD_NOREPEAT
        self._vk = parsed[1]
        self._thread_id = None
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self._thread.start()

    def stop(self):
        """Unregister the hotkey and wait for the listener thread to finish."""
        if not self._thread.is_alive():
            return
        self._ready.wait(timeout=1)
        user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
        self._thread.join(timeout=1)

    def _run(self):
        # Create the thread's message queue before publishing its id, so a
        # stop() that arrives straight away isn't lost.
        msg = wintypes.MSG()
        user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0)
        self._thread_id = kernel32.GetCurrentThreadId()
        self._ready.set()
        if not user32.RegisterHotKey(None, _HOTKEY_ID, self._modifiers, self._vk):
            self.failed.emit(f"{self.name} is already in use by another app. "
                             "Choose a different hotkey in FileRing's settings.")
            return
        try:
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == WM_HOTKEY and msg.wParam == _HOTKEY_ID:
                    self.pressed.emit()
        finally:
            user32.UnregisterHotKey(None, _HOTKEY_ID)
