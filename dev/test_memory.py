"""Dev check: worker memory while busy, and that it quits after the idle timeout."""
import os, sys, time
from pathlib import Path
os.environ["FILERING_WORKER_IDLE_MS"] = "5000"   # inherited by the worker
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
work = Path(sys.argv[1]); work.mkdir(parents=True, exist_ok=True)

from PySide6.QtWidgets import QApplication
app = QApplication([])
import formats, worker
formats.OUTPUT_DIR = work / "Converted"


def mb(pid):
    import subprocess
    out = subprocess.run(["powershell", "-NoProfile", "-c",
                          f"(Get-Process -Id {pid} -ErrorAction SilentlyContinue).WorkingSet64"],
                         capture_output=True, text=True).stdout.strip()
    return round(int(out) / 2**20) if out else None


def wait(cond, secs):
    end = time.time() + secs
    while not cond() and time.time() < end:
        app.processEvents(); time.sleep(0.05)

md = work / "c.md"; md.write_text("# Hi\n\n| a | b |\n|---|---|\n| 1 | 2 |\n")
csv = work / "c.csv"; csv.write_text("x,y\n1,2\n")
svc = worker.ConversionService()
done = []
svc.finished.connect(lambda *a: done.append(a))
for f, t, c in [(md, "pdf", "Document"), (csv, "xlsx", "Data"), (md, "docx", "Document")]:
    svc.convert([f], t, c)
wait(lambda: len(done) == 3, 120)
pid = svc._proc.pid
print("this test process (tray-like, no converters loaded):", mb(os.getpid()), "MB")
print("worker after PDF + XLSX + DOCX:", mb(pid), "MB")
t0 = time.time()
wait(lambda: svc._proc.poll() is not None, 30)
print(f"worker exited on its own after {time.time() - t0:.1f}s idle:", svc._proc.poll() is not None)
svc.convert([csv], "json", "Data")
wait(lambda: len(done) == 4, 60)
print("new worker started on demand for the next job:", done[-1][1][0].name, "| pid changed:",
      svc._proc.pid != pid)
svc.shutdown()
