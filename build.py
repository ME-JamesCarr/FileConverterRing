"""Package FileRing as dist/FileRing/FileRing.exe with PyInstaller.

Run via build.bat (which sets up .venv first), or: python build.py
"""
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BUILD = HERE / "build"


def make_icon() -> Path:
    from PIL import Image
    from PySide6.QtCore import QBuffer, QIODevice
    from PySide6.QtWidgets import QApplication
    from main import app_icon

    app = QApplication.instance() or QApplication([])  # noqa: F841 (needed for QPixmap)
    buf = QBuffer()
    buf.open(QIODevice.WriteOnly)
    app_icon(256).save(buf, "PNG")
    from io import BytesIO
    ico = BUILD / "FileRing.ico"
    BUILD.mkdir(exist_ok=True)
    Image.open(BytesIO(bytes(buf.data()))).save(
        ico, sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])
    return ico


def main():
    # --debug builds a console version into build/debug-dist, to see startup errors.
    debug = "--debug" in sys.argv
    sys.path.insert(0, str(HERE))
    icon = make_icon()
    dist = BUILD / "debug-dist" if debug else HERE / "dist"
    args = [
        sys.executable, "-m", "PyInstaller", str(HERE / "main.py"),
        "--name", "FileRing", "--console" if debug else "--windowed",
        "--onedir", "--noconfirm", "--clean",
        "--icon", str(icon),
        "--distpath", str(dist), "--workpath", str(BUILD / "pyinstaller"),
        "--specpath", str(BUILD),
        "--add-data", f"{HERE / 'converters' / 'document.css'};converters",
        "--hidden-import", "selftest",
        # Bundled executables and data the libraries load at run time.
        "--collect-data", "pypandoc",
        "--collect-binaries", "pypandoc",
        "--collect-data", "imageio_ffmpeg",
        "--collect-all", "pymupdf4llm",
        "--collect-data", "pymupdf",   # layout-analysis model loaded at import
        "--collect-all", "pdf2docx",
        "--collect-submodules", "pillow_heif",
        "--exclude-module", "tkinter",
    ]
    subprocess.run(args, check=True, cwd=HERE)
    trim(dist / "FileRing")
    print(f"\nBuilt {dist / 'FileRing' / 'FileRing.exe'}")


def trim(app: Path):
    """Remove parts of Qt that FileRing never uses (thousands of small files)."""
    qt = app / "_internal" / "PySide6"
    # Chromium's developer-tools resources (~80 MB).
    for pak in app.rglob("qtwebengine_devtools_resources*.pak"):
        pak.unlink()
    # Qt Quick (QML) modules: copied in because Chromium links Qt Quick, but
    # FileRing has no QML user interface.
    shutil.rmtree(qt / "qml", ignore_errors=True)
    # Translations other than English (Qt dialogs and Chromium's locale files).
    for f in (qt / "translations").rglob("*"):
        if f.is_file() and not (f.stem.endswith("_en") or f.stem in ("en-US", "en-GB")):
            f.unlink()


if __name__ == "__main__":
    main()
