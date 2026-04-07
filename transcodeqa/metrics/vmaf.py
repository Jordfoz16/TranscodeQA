"""VMAF quality analysis via ffmpeg libvmaf."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Callable, Optional

from transcodeqa.utils import DURATION_RE, TIME_RE, parse_ts

VMAF_SCORE_RE = re.compile(r"VMAF score:\s*([\d.]+)")


def run_vmaf(
    source: Path,
    transcoded: Path,
    threads: int = 0,
    progress_callback: Optional[Callable[[float, float], None]] = None,
    n_subsample: int = 1,
) -> Optional[float]:
    """Run ffmpeg libvmaf and return the VMAF score, or None on failure.

    progress_callback(current_sec, total_sec) is called for each ffmpeg
    progress line so the caller can update a progress bar in real time.
    threads=0 lets ffmpeg choose automatically.
    n_subsample: libvmaf frame interval; 1 = every frame, N > 1 = every Nth frame.
    """
    lavfi = "libvmaf" if n_subsample <= 1 else f"libvmaf=n_subsample={n_subsample}"
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(source),
        "-i",
        str(transcoded),
        "-lavfi",
        lavfi,
        "-f",
        "null",
        "-",
    ]
    if threads > 0:
        cmd += ["-threads", str(threads)]
    try:
        proc = subprocess.Popen(
            cmd,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            text=True,
        )
        vmaf_score = None
        total_duration: Optional[float] = None
        for line in proc.stderr:
            if total_duration is None:
                m = DURATION_RE.search(line)
                if m:
                    total_duration = parse_ts(*m.groups())

            if progress_callback is not None and total_duration:
                m = TIME_RE.search(line)
                if m:
                    current = parse_ts(*m.groups())
                    progress_callback(current, total_duration)

            match = VMAF_SCORE_RE.search(line)
            if match:
                vmaf_score = float(match.group(1))

        proc.wait()
        return vmaf_score if proc.returncode == 0 else None
    except Exception:
        return None
