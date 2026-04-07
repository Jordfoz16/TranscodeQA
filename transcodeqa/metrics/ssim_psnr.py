"""SSIM and PSNR quality analysis via ffmpeg filters."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Callable, Optional

from transcodeqa.utils import DURATION_RE, TIME_RE, parse_ts

# ffmpeg ssim: "SSIM Y:... U:... V:... All:..." or "SSIM R:... G:... B:... All:..."
SSIM_SCORE_RE = re.compile(r"SSIM\s+.*\bAll:([\d.]+)")
# ffmpeg psnr: "PSNR y:... u:... v:... average:..." (plane labels vary: y/u/v or r/g/b)
PSNR_SCORE_RE = re.compile(r"PSNR\s+.*\baverage:([\d.]+|inf)\b")


def run_ssim_psnr(
    source: Path,
    transcoded: Path,
    threads: int = 0,
    progress_callback: Optional[Callable[[float, float], None]] = None,
) -> tuple[Optional[float], Optional[float]]:
    """Run ffmpeg ssim + psnr in one pass; return (ssim, psnr) or (None, None) on failure.

    Input order: -i source -i transcoded. SSIM/PSNR filters expect distorted first,
    reference second, so we split streams and wire [dist][ref] for each filter.
    """
    # [0:v] = reference (source), [1:v] = distorted (transcoded)
    filter_complex = (
        "[0:v]split=2[ref1][ref2];"
        "[1:v]split=2[dist1][dist2];"
        "[dist1][ref1]ssim;"
        "[dist2][ref2]psnr"
    )
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(source),
        "-i",
        str(transcoded),
        "-filter_complex",
        filter_complex,
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
        ssim_score: Optional[float] = None
        psnr_score: Optional[float] = None
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

            m = SSIM_SCORE_RE.search(line)
            if m:
                ssim_score = float(m.group(1))
            m = PSNR_SCORE_RE.search(line)
            if m:
                raw = m.group(1)
                psnr_score = float("inf") if raw == "inf" else float(raw)

        proc.wait()
        if proc.returncode != 0:
            return None, None
        return ssim_score, psnr_score
    except Exception:
        return None, None
