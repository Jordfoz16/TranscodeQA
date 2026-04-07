"""Shared utilities: file discovery, ffprobe helpers, formatting, progress column."""

from __future__ import annotations

import re
import subprocess
from datetime import timedelta
from pathlib import Path
from typing import Optional

from rich.progress import ProgressColumn
from rich.text import Text

DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")
TIME_RE = re.compile(r"\btime=(\d+):(\d+):(\d+(?:\.\d+)?)")
DEFAULT_EXTENSIONS = ("mkv", "mp4", "webm", "mov")


def parse_ts(h: str, m: str, s: str) -> float:
    """Convert HH:MM:SS.xx timestamp components to total seconds."""
    return int(h) * 3600 + int(m) * 60 + float(s)


class ParallelTimeRemainingColumn(ProgressColumn):
    """ETA based on wall-clock elapsed/completed, accurate for parallel jobs."""

    max_refresh = 0.5

    def render(self, task) -> Text:
        if task.finished and task.finished_time is not None:
            delta = timedelta(seconds=int(task.finished_time))
            return Text(str(delta), style="progress.elapsed")
        if (
            task.total is None
            or task.total == 0
            or task.completed is None
            or task.completed <= 0
            or task.elapsed is None
        ):
            return Text("--:--", style="progress.remaining")

        remaining = task.total - task.completed
        if remaining <= 0:
            return Text("0:00:00", style="progress.remaining")

        eta_seconds = (task.elapsed / task.completed) * remaining
        minutes, seconds = divmod(int(eta_seconds), 60)
        hours, minutes = divmod(minutes, 60)
        formatted = f"{hours:d}:{minutes:02d}:{seconds:02d}"
        return Text(formatted, style="progress.remaining")


def format_size(size_bytes: int) -> str:
    """Format bytes as human-readable size (KB/MB/GB)."""
    for unit in ("B", "KB", "MB", "GB"):
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


def find_video_files(directory: Path, extensions: tuple) -> list:
    """Recursively find video files with given extensions."""
    files = []
    for ext in extensions:
        files.extend(directory.rglob(f"*.{ext}"))
    return sorted(files)


def get_codec(path: Path) -> str:
    """Get video codec from file using ffprobe. Returns e.g. h264, h265, av1."""
    codec_alias = {"hevc": "h265"}
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=codec_name",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            codec = result.stdout.strip().lower()
            return codec_alias.get(codec, codec)
    except Exception:
        pass
    return "?"


def get_duration(path: Path) -> Optional[float]:
    """Get video duration in seconds using ffprobe container metadata (fast, no decode)."""
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode == 0 and result.stdout.strip():
            val = result.stdout.strip()
            if val.lower() not in ("n/a", ""):
                return float(val)
    except Exception:
        pass
    return None
