"""Dev check for the Explorer right-click menu:
1. which formats each file type's submenu offers,
2. writing and removing the registry keys (under a test key, not the real menu),
3. hand-offs from several processes at once batching into jobs, with
   unconvertible files skipped.
Uses its own pipe name, so it never talks to a running FileRing.
"""
import os
import subprocess
import sys
import time
import winreg
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
os.environ["FILERING_INSTANCE"] = f"FileRing-test-{os.getpid()}"
work = Path(sys.argv[1])
work.mkdir(parents=True, exist_ok=True)

import shell_menu
from formats import target_name

# 1. Menu contents
for kind in ["jpg", "pdf", "docx", "csv", "mp3", "mp4", "folder"]:
    items = shell_menu.menu_items(kind)
    targets = [t for _, t in items]
    assert len(targets) == len(set(targets)), f"duplicate target for {kind}"
    groups = []
    for cat, t in items:
        if not groups or groups[-1][0] != cat:
            groups.append((cat, []))
        groups[-1][1].append(target_name(t))
    print(f"{kind:7}", " | ".join(f"{c}: {', '.join(ts)}" for c, ts in groups))

# 2. Registry round trip under a test root
root = r"Software\FileRingTest\Classes"
entries = shell_menu.entries(root)
shell_menu.register(root)
with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                    rf"{root}\SystemFileAssociations\.jpeg\shell\FileRing\shell") as key:
    verbs = [winreg.EnumKey(key, i) for i in range(winreg.QueryInfoKey(key)[0])]
with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                    rf"{root}\SystemFileAssociations\.jpeg\shell\FileRing\shell\{verbs[-1]}") as key:
    sep = winreg.QueryValueEx(key, "CommandFlags")[0]
with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                    rf"{root}\SystemFileAssociations\.jpeg\shell\FileRing\shell\{verbs[0]}\command") as key:
    cmd = winreg.QueryValueEx(key, "")[0]
print(f"\nregistry: {len(entries)} keys; .jpeg submenu = {verbs}; separator before ZIP = {sep == 0x20}")
print("command:", cmd)
shell_menu.unregister(root)
try:
    winreg.OpenKey(winreg.HKEY_CURRENT_USER, rf"{root}\SystemFileAssociations\.jpg\shell\FileRing")
    print("unregister: FAILED, key still there")
except FileNotFoundError:
    print("unregister: menu keys removed")
for path in [root, r"Software\FileRingTest"]:
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path)   # remove the (now empty) test key
    except OSError:
        pass

# 3. Hand-offs -> batches (real app object, with the hotkey, badges and Explorer stubbed out)
from PySide6.QtWidgets import QApplication
app = QApplication([])
import formats
import main as fr
from PIL import Image

formats.OUTPUT_DIR = work / "Converted"
shown, revealed = [], []


class NoHotkey:
    name = "Ctrl+Alt+R"
    def __init__(self, *_): pass
    pressed = failed = type("S", (), {"connect": lambda *a: None})()
    def start(self): pass
    def stop(self): pass


fr.GlobalHotkey = NoHotkey
fr.ProgressBadge.show_at = lambda *a: None
fr.explorer.reveal = lambda paths: revealed.append([p.name for p in paths])
ring = fr.FileRingApp(app, fr.Settings())
ring.tray.hide()
ring.show_message = lambda title, text: shown.append(f"{title}: {text!r}")
server = fr.listen_for_requests(ring)

src = work / "src"
src.mkdir(exist_ok=True)
for name in ("a.jpg", "b.jpg"):
    Image.new("RGB", (64, 48), "teal").save(src / name)
(src / "song.mp3").write_bytes(b"not really audio")
(src / "Folder").mkdir(exist_ok=True)
(src / "Folder" / "note.txt").write_text("hi")
done = []
ring.service.finished.connect(lambda *a: done.append(a))

requests = [("Image", "webp", "a.jpg"), ("Image", "webp", "b.jpg"), ("Image", "webp", "song.mp3"),
            ("Other", "zip", "a.jpg"), ("Other", "zip", "song.mp3"), ("Other", "zip", "Folder")]
t0 = time.time()
procs = [subprocess.Popen([sys.executable, str(HERE / "main.py"), "--convert", c, t, str(src / f)])
         for c, t, f in requests]
while (any(p.poll() is None for p in procs) or len(done) < 2) and time.time() - t0 < 90:
    app.processEvents()
    time.sleep(0.02)
print(f"\nhand-off processes: exit codes {[p.returncode for p in procs]}, "
      f"slowest {time.time() - t0:.1f}s until both jobs finished")
for job_id, outs, errs, cancelled in done:
    print(f"job {job_id}: {[o.name for o in outs]} errors={errs}")
print("Explorer would show:", revealed)
print("messages:", shown)
ring.service.shutdown()
