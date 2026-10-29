"""Hand a file from the Explorer right-click menu to the running FileRing.

Explorer starts `FileRing.exe --convert <category> <target> "<file>"` once per
selected file. This passes the request to the running app over its local
pipe and exits; the app gathers the files into one batch. Nothing here
imports Qt, so each hand-off starts and finishes quickly. If FileRing isn't
running, it is started first.
"""
import ctypes
import getpass
import json
import os
import subprocess
import sys
import time
from pathlib import Path

# The running app listens on this name (QLocalServer = a named pipe on Windows).
INSTANCE_NAME = os.environ.get("FILERING_INSTANCE", f"FileRing-{getpass.getuser()}")
WAIT_S = 20     # a cold start of the app can take a few seconds


def _start_app():
    if getattr(sys, "frozen", False):
        cmd = [sys.executable, "--background"]
    else:
        cmd = [str(Path(sys.executable).with_name("pythonw.exe")),
               str(Path(__file__).with_name("main.py")), "--background"]
    subprocess.Popen(cmd, creationflags=subprocess.DETACHED_PROCESS
                     | subprocess.CREATE_NEW_PROCESS_GROUP)


def send(message: dict, name: str = INSTANCE_NAME) -> bool:
    pipe = rf"\\.\pipe\{name}"
    data = (json.dumps(message) + "\n").encode()
    deadline = time.monotonic() + WAIT_S
    started = False
    while time.monotonic() < deadline:
        try:
            with open(pipe, "wb", buffering=0) as f:
                f.write(data)
            return True
        except FileNotFoundError:          # FileRing isn't running
            if not started:
                _start_app()
                started = True
        except OSError:                    # busy with another hand-off: try again
            pass
        time.sleep(0.1)
    return False


def main(argv: list[str]) -> int:
    i = argv.index("--convert")
    category, target, path = argv[i + 1:i + 4]
    if send({"type": "convert", "category": category, "target": target, "files": [path]}):
        return 0
    ctypes.windll.user32.MessageBoxW(None, "FileRing didn't respond. Start it from the "
                                     "Start menu and try again.", "FileRing", 0x30)
    return 1
