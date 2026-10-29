"""Automatic updates from the GitHub releases of FileRing.

Only the installed copy updates itself: its version and folder come from the
uninstall entry the installer writes. The updater asks GitHub for the latest
release, downloads FileRing-Setup.exe to %TEMP% (checked against the SHA-256
GitHub publishes for it), then runs it silently once FileRing is idle. The
installer closes FileRing, upgrades it in place and the command starts it again.
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.request
import winreg
from dataclasses import dataclass
from pathlib import Path

REPO = "ME-JamesCarr/FileConverterRing"
LATEST_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
ASSET = "FileRing-Setup.exe"
# Must match AppId in installer.iss.
UNINSTALL_KEY = (r"Software\Microsoft\Windows\CurrentVersion\Uninstall"
                 r"\{6B0E3C9A-4F2D-4C1B-9E7A-2D5F8A1C3B47}_is1")


@dataclass
class Release:
    version: str
    url: str
    size: int
    sha256: str | None


def version_tuple(text: str) -> tuple[int, ...]:
    return tuple(int(n) for n in re.findall(r"\d+", text)[:3])


def installed_version() -> str | None:
    """This copy's version if it's the installed FileRing, else None (dev/test builds)."""
    if not getattr(sys, "frozen", False):
        return None
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY) as key:
            version = winreg.QueryValueEx(key, "DisplayVersion")[0]
            folder = winreg.QueryValueEx(key, "InstallLocation")[0]
    except OSError:
        return None
    same = Path(folder).resolve() == Path(sys.executable).parent.resolve()
    return version if same else None


def latest_release() -> Release:
    request = urllib.request.Request(LATEST_URL, headers={
        "Accept": "application/vnd.github+json", "User-Agent": "FileRing-updater"})
    with urllib.request.urlopen(request, timeout=20) as response:
        data = json.load(response)
    asset = next(a for a in data["assets"] if a["name"] == ASSET)
    digest = asset.get("digest") or ""
    return Release(version=data["tag_name"].lstrip("v"), url=asset["browser_download_url"],
                   size=asset["size"],
                   sha256=digest.removeprefix("sha256:") if digest.startswith("sha256:") else None)


def newer_release(current: str) -> Release | None:
    release = latest_release()
    return release if version_tuple(release.version) > version_tuple(current) else None


def download(release: Release) -> Path:
    """Download the installer (once per version) and check it. Returns its path."""
    path = Path(tempfile.gettempdir()) / f"FileRing-Setup-{release.version}.exe"
    if (path.exists() and path.stat().st_size == release.size
            and (not release.sha256 or _sha256(path) == release.sha256)):
        return path   # already downloaded earlier
    part = path.with_suffix(".part")
    sha = hashlib.sha256()
    request = urllib.request.Request(release.url, headers={"User-Agent": "FileRing-updater"})
    with urllib.request.urlopen(request, timeout=60) as response, part.open("wb") as f:
        while chunk := response.read(1 << 20):
            f.write(chunk)
            sha.update(chunk)
    if part.stat().st_size != release.size or (release.sha256
                                               and sha.hexdigest() != release.sha256):
        part.unlink(missing_ok=True)
        raise RuntimeError("the downloaded update didn't match GitHub's checksum")
    part.replace(path)
    return path


def _sha256(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(1 << 20):
            sha.update(chunk)
    return sha.hexdigest()


def apply(installer: Path):
    """Run the installer silently, then start FileRing again. The caller must quit
    straight away: the installer closes every FileRing.exe *and its child
    processes*, so this command waits a moment for FileRing to be gone first."""
    exe = sys.executable
    command = (f'cmd /c "ping -n 4 127.0.0.1 >nul & "{installer}" /VERYSILENT '
               f'/SUPPRESSMSGBOXES /NORESTART & start "" "{exe}""')
    subprocess.Popen(command, creationflags=subprocess.CREATE_NO_WINDOW
                     | subprocess.DETACHED_PROCESS, cwd=os.path.dirname(exe))
