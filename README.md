# FileRing

Drag-and-drop file converter that pops up as a ring around your cursor.

## Install

Download **[FileRing-Setup.exe](https://github.com/ME-JamesCarr/FileConverterRing/releases/latest/download/FileRing-Setup.exe)** (latest version) and run it.
No admin rights or other software needed. If Windows shows "Windows protected your PC",
click **More info → Run anyway** (the installer isn't code-signed).
To update, run the newest setup over the old one.

Or install (or update) from Command Prompt in one line. It installs silently, sets FileRing to start with Windows, and starts it:

```cmd
curl -L -o %TEMP%\FileRing-Setup.exe https://github.com/ME-JamesCarr/FileConverterRing/releases/latest/download/FileRing-Setup.exe && %TEMP%\FileRing-Setup.exe /VERYSILENT /SUPPRESSMSGBOXES /TASKS="autostart" && start "" "%LOCALAPPDATA%\Programs\FileRing\FileRing.exe"
```

Installer options: `/SILENT` shows only a progress bar; `/TASKS="autostart,desktopicon"` also adds a desktop shortcut, `/TASKS=""` neither.
Uninstall silently with `"%LOCALAPPDATA%\Programs\FileRing\unins000.exe" /VERYSILENT`.

## Use

1. Start dragging a file in Explorer.
2. While still holding it, press **Ctrl+Alt+R** (changeable in Settings). The ring appears at the cursor.
3. Hold the file over a category for a moment to open its formats. (If only one category fits, it opens by itself.)
4. Drop on a format. The converted copy is saved to `Pictures\Converted` (your OneDrive Pictures folder if OneDrive is set up) and File Explorer opens with it selected. The original is never changed. If a conversion fails, a small dialog says why.

You can also press the hotkey first and then drag a file onto the ring.
Close the ring with **Esc**, a right-click, a click on the centre, or the hotkey again.
Categories and formats the file can't be converted to are greyed out.

Longer conversions show a progress ring where you dropped the file. Click it to cancel.

## Memory

The tray app (hotkey, ring, settings) never loads the conversion libraries and
uses about 65 MB. Conversions run in a separate `FileRing.exe --worker` process
that starts when you drop a file and quits after 3 minutes with nothing to do
(about 250 MB while it runs). The first conversion after it has quit takes a
few seconds longer while it starts. The tray app also returns unused memory to
Windows after 3 idle minutes.

## Settings

Right-click the tray icon and choose **Settings…** (or double-click the icon):

- **Hotkey:** Ctrl, Alt or Win plus a letter, number, F-key or Space.
- **Save converted files:** a folder of your choice, or next to the original file.
- **Start FileRing when Windows starts.**

Settings are stored in the registry under `HKCU\Software\FileRing`.

## Run and build

- `run.bat` runs from source (creates `.venv` on first run).
- `build.bat` builds `dist\FileRing\FileRing.exe` (creates `.venv` and installs PyInstaller on first run), then `release\FileRing-Setup.exe` if Inno Setup is installed (`winget install JRSoftware.InnoSetup`). To publish a new version, push a tag: `git tag v1.0.1` then `git push origin v1.0.1`. The "Build installer" GitHub Actions workflow builds the exe, runs the self-test, builds the installer with that version number and attaches it to the release (about 15 minutes).

## Sharing with the team

Share the download link above, or send `release\FileRing-Setup.exe` (one file, about 270 MB). It installs per user into
`%LOCALAPPDATA%\Programs\FileRing` without admin rights, adds a Start menu entry and
an uninstaller, and offers "Start with Windows". Running a newer setup over an old one
closes FileRing and upgrades it in place. Nothing else (Python etc.) is needed.

The exe isn't code-signed, so the first run shows "Windows protected your PC":
click **More info → Run anyway**.
- `FileRing.exe --selftest <empty folder>` converts sample files with every converter and writes `report.txt` there.
- `python build.py --debug` builds a console copy in `build\debug-dist` that prints startup errors.
- `dev\test_worker.py` and `dev\test_memory.py` check the app-to-worker round trip, the idle exit and memory use.
- The packaged app writes unexpected errors to `%LOCALAPPDATA%\FileRing\error.log`.
- The build is about 1.1 GB, mostly Chromium (PDF output), Pandoc, OpenCV (PDF to DOCX) and FFmpeg.

## Status

| Phase | |
|---|---|
| 1. Hotkey and two-ring overlay | done |
| 2. Drag and drop and image conversions (PNG, JPG, WEBP, BMP, GIF, TIFF, ICO, HEIC/SVG input, PDF output) | done |
| 3. Document converters (TXT, MD, HTML, DOCX, ODT, RTF, EPUB, PDF) and Data converters (CSV, TSV, XLSX, JSON, YAML, XML, TOML); PDF pages to images | done |
| 4. Audio (MP3, WAV, FLAC, OGG, M4A, AAC) and video (MP4, MKV, MOV, AVI, WEBM, GIF) via FFmpeg, with a progress badge | done |
| 5. Settings, start with Windows, click-to-cancel, single instance, packaged .exe | done |

The "Other" category (archives, fonts) has no converters yet.

## Good to know

- PDF output is rendered by Qt's built-in Chromium engine. Normal documents (headings, lists, tables, images) come out well; complex Word layouts (text boxes, columns) are simplified.
- PDF to DOCX keeps the page layout (pdf2docx). PDF to other document formats goes via Markdown, which keeps structure but not exact layout. Scanned PDFs have no text to extract (OCR isn't included).
- A multi-page PDF dropped on an image format gives one image per page (`name - page 1.png`, ...).
- A multi-sheet XLSX converted to CSV/TSV gives one file per sheet. Converting to JSON/YAML/TOML/XML keeps all sheets.
- Nested JSON/YAML/XML is flattened into columns like `address.city` when converted to a spreadsheet.
- Audio files convert to other audio formats only. Videos convert to any audio or video format (audio formats extract the soundtrack). Animated GIFs convert to video formats.
- Only audio/video conversions can stop part-way when cancelled; others finish the current file first. FFmpeg comes bundled with the `imageio-ffmpeg` package.

## Adding a converter

Create `converters/<name>.py` with `CATEGORY`, `SOURCES`, `TARGETS` and
`convert(src, dst)`, then add it to `_MODULES` in `converters/__init__.py`.
