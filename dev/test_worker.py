"""Dev check: tray-side ConversionService <-> worker process round trip."""
import sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
work = Path(sys.argv[1]); work.mkdir(parents=True, exist_ok=True)

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
app = QApplication([])
import formats, worker
worker.IDLE_EXIT_MS = 4000   # only affects this process; worker uses its own default
formats.OUTPUT_DIR = work / "Converted"

src = work / "a.csv"; src.write_text("x,y\n1,2\n")
md = work / "b.md"; md.write_text("# Hi\n\ntext\n")
svc = worker.ConversionService()
events = []
svc.progress.connect(lambda i, v: events.append(("progress", i, round(v, 2))))
def done(i, outs, errs, cancelled):
    events.append(("done", i, [o.name for o in outs], errs, cancelled, round(time.time() - t0, 1)))
svc.finished.connect(done)
t0 = time.time()
svc.convert([src], "json", "Data")
svc.convert([md], "pdf", "Document")
svc.convert([src], "pdf", "Document")   # not convertible -> error message back
QTimer.singleShot(1, lambda: None)
deadline = time.time() + 120
while sum(e[0] == "done" for e in events) < 3 and time.time() < deadline:
    app.processEvents(); time.sleep(0.02)
for e in events:
    print(e)
print("worker pid alive:", svc._proc.poll() is None)
svc.shutdown()
for _ in range(100):
    app.processEvents(); time.sleep(0.05)
    if svc._proc.poll() is not None:
        break
print("worker exited after app shutdown:", svc._proc.poll() is not None)
