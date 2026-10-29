"""Audio and video conversions with FFmpeg (bundled by imageio-ffmpeg)."""
import re
import subprocess
import tempfile
from pathlib import Path

import imageio_ffmpeg

from formats import ext_of
from . import Cancelled

CATEGORY = "Media"
AUDIO = {"mp3", "wav", "flac", "ogg", "m4a", "aac"}
VIDEO = {"mp4", "mkv", "mov", "avi", "webm"}
SOURCES = AUDIO | VIDEO | {"gif"}
TARGETS = AUDIO | VIDEO | {"gif"}
REPORTS_PROGRESS = True

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
_NO_WINDOW = subprocess.CREATE_NO_WINDOW

# H.264 needs even width/height.
_EVEN = ["-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2"]
_H264 = ["-c:v", "libx264", "-preset", "medium", "-crf", "23", "-pix_fmt", "yuv420p", *_EVEN]
ARGS = {
    "mp3": ["-vn", "-c:a", "libmp3lame", "-q:a", "2"],
    "wav": ["-vn", "-c:a", "pcm_s16le"],
    "flac": ["-vn", "-c:a", "flac"],
    "ogg": ["-vn", "-c:a", "libvorbis", "-q:a", "5"],
    "m4a": ["-vn", "-c:a", "aac", "-b:a", "192k"],
    "aac": ["-vn", "-c:a", "aac", "-b:a", "192k"],
    "mp4": [*_H264, "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart"],
    "mov": [*_H264, "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart"],
    "mkv": [*_H264, "-c:a", "aac", "-b:a", "160k"],
    "avi": ["-c:v", "mpeg4", "-q:v", "3", *_EVEN, "-c:a", "libmp3lame", "-q:a", "3"],
    "webm": ["-c:v", "libvpx-vp9", "-crf", "32", "-b:v", "0", "-row-mt", "1",
             "-deadline", "good", "-cpu-used", "4", "-c:a", "libopus", "-b:a", "128k"],
    # Two-pass palette in one filter graph: much better colours than the default.
    "gif": ["-an", "-vf", "fps=12,scale='min(640,iw)':-2:flags=lanczos,"
                          "split[a][b];[a]palettegen[p];[b][p]paletteuse", "-loop", "0"],
}

_DURATION = re.compile(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)")


def supports(src_ext: str, target_ext: str) -> bool:
    if src_ext in AUDIO:
        return target_ext in AUDIO       # no picture to make a video from
    if src_ext == "gif":
        return target_ext in VIDEO       # a GIF has no sound
    return True


def _probe(src: Path) -> tuple[float | None, bool]:
    """(duration in seconds, has an audio stream), read from FFmpeg's input summary."""
    info = subprocess.run([FFMPEG, "-hide_banner", "-i", str(src)], capture_output=True,
                          text=True, errors="replace", creationflags=_NO_WINDOW).stderr
    m = _DURATION.search(info)
    duration = int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3]) if m else None
    return duration, bool(re.search(r"Stream #.*: Audio:", info))


def convert(src: Path, dst: Path, progress=None, cancel=None) -> None:
    target = ext_of(dst)
    duration, has_audio = _probe(src)
    if target in AUDIO and not has_audio:
        raise ValueError(f"{src.name} has no audio track")
    run_ffmpeg(["-i", str(src), *ARGS[target], str(dst)], duration, progress, cancel)


def run_ffmpeg(args: list[str], duration: float | None, progress=None, cancel=None) -> None:
    """Run FFmpeg with these arguments, reporting progress and stopping if cancelled."""
    cmd = [FFMPEG, "-hide_banner", "-nostdin", "-y", "-progress", "pipe:1", "-nostats", *args]
    with tempfile.TemporaryFile() as err:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=err, text=True,
                                creationflags=_NO_WINDOW)
        for line in proc.stdout:   # FFmpeg writes a progress block about twice a second
            if cancel and cancel.is_set():
                proc.kill()
                proc.wait()
                raise Cancelled()
            if progress and duration and line.startswith("out_time_us="):
                value = line.split("=", 1)[1].strip()
                if value.isdigit():
                    progress(min(1.0, int(value) / 1e6 / duration))
        proc.wait()
        if proc.returncode:
            err.seek(0)
            lines = err.read().decode(errors="replace").strip().splitlines()
            raise RuntimeError(lines[-1] if lines else f"FFmpeg exited with {proc.returncode}")
