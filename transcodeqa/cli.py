"""CLI: compare transcoded videos against a source (VMAF or SSIM+PSNR)."""

from __future__ import annotations

import argparse
import math
import os
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from rich.console import Console
from rich.progress import BarColumn, Progress, TaskProgressColumn, TextColumn
from rich.table import Table

from transcodeqa.metrics.ssim_psnr import run_ssim_psnr
from transcodeqa.metrics.vmaf import run_vmaf
from transcodeqa.utils import ParallelTimeRemainingColumn, format_size, find_video_files, get_codec, get_duration


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare transcoded videos against a source using VMAF or SSIM+PSNR quality analysis."
    )
    parser.add_argument(
        "source",
        type=Path,
        help="Path to the base/source video file",
    )
    parser.add_argument(
        "transcoded_path",
        type=Path,
        help="Directory containing transcoded files (searched recursively)",
    )
    parser.add_argument(
        "--metric",
        choices=["vmaf", "ssim-psnr"],
        default="vmaf",
        help=(
            "Quality metric: vmaf (default, best for remux vs transcode) or "
            "ssim-psnr (better for transcode vs transcode)"
        ),
    )
    parser.add_argument(
        "--extensions",
        default="mkv,mp4,webm,mov",
        help="Comma-separated video extensions to search (default: mkv,mp4,webm,mov)",
    )
    parser.add_argument(
        "--no-progress",
        action="store_true",
        help="Disable progress bar (e.g. for piping)",
    )
    parser.add_argument(
        "--jobs",
        "-j",
        type=int,
        default=4,
        metavar="N",
        help="Number of parallel analysis jobs (default: 4)",
    )
    parser.add_argument(
        "--n-subsample",
        "-n",
        type=int,
        default=1,
        metavar="N",
        dest="n_subsample",
        help=(
            "VMAF only: frame subsampling — score every Nth frame via ffmpeg libvmaf "
            "(default: 1 = all frames). Larger N is faster but noisier on short clips; "
            "odd values (3, 5, 7) are often safer than even."
        ),
    )
    parser.add_argument(
        "--sort",
        choices=["name", "ratio", "saved", "score"],
        default="ratio",
        help=(
            "Sort table by: name, ratio (compression), saved (data saved), "
            "score (VMAF or SSIM depending on --metric) (default: ratio)"
        ),
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=None,
        metavar="FILE",
        help="Write results to file (plain text) in addition to printing to the terminal",
    )
    args = parser.parse_args()

    console = Console()

    if args.jobs < 1:
        console.print("[red]Error: --jobs must be at least 1[/red]")
        return 1

    if args.n_subsample < 1:
        console.print("[red]Error: --n-subsample must be at least 1[/red]")
        return 1

    if not args.source.is_file():
        console.print(f"[red]Error: Source file not found: {args.source}[/red]")
        return 1

    if not shutil.which("ffmpeg"):
        console.print("[red]Error: ffmpeg not found in PATH. Install ffmpeg.[/red]")
        return 1

    extensions = tuple(e.strip().lstrip(".").lower() for e in args.extensions.split(","))
    transcoded_files = find_video_files(args.transcoded_path, extensions)

    if not transcoded_files:
        console.print(
            f"[red]Error: No video files found in {args.transcoded_path} "
            f"(extensions: {', '.join(extensions)})[/red]"
        )
        return 1

    source_size = args.source.stat().st_size
    total_files = len(transcoded_files)
    results: list[dict] = []

    jobs = min(args.jobs, total_files)
    cpu_count = os.cpu_count() or 1
    threads_per_job = max(1, cpu_count // jobs)

    metric_label = "VMAF" if args.metric == "vmaf" else "SSIM+PSNR"

    if args.metric == "vmaf" and args.n_subsample > 1:
        console.print(
            f"[dim]VMAF frame subsampling: every {args.n_subsample}th frame (libvmaf n_subsample)[/dim]"
        )

    if not args.no_progress:
        console.print("[dim]Scanning file durations…[/dim]")
    with ThreadPoolExecutor(max_workers=jobs) as executor:
        durations: dict[Path, float | None] = dict(
            executor.map(lambda p: (p, get_duration(p)), transcoded_files)
        )

    known_durations = [d for d in durations.values() if d is not None]
    total_duration = sum(known_durations) if known_durations else None
    use_duration_mode = total_duration is not None and total_duration > 0

    progress_columns = (
        TextColumn("[bold blue]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        ParallelTimeRemainingColumn(),
    )

    with Progress(*progress_columns, console=console, disable=args.no_progress) as progress:
        if use_duration_mode:
            overall_task = progress.add_task(
                f"Computing {metric_label} (0/{total_files} files)",
                total=total_duration,
            )
        else:
            overall_task = progress.add_task(
                f"Computing {metric_label} (0/{total_files} files, {total_files} left)",
                total=total_files,
            )

        def process_file(transcoded: Path) -> dict:
            file_duration = durations.get(transcoded)
            last_reported = [0.0]

            file_task = progress.add_task(
                f"  [dim]{transcoded.name}[/dim]",
                total=file_duration if file_duration else 100,
                visible=not args.no_progress,
            )

            def on_progress(current_sec: float, _total_sec: float) -> None:
                delta = current_sec - last_reported[0]
                if delta <= 0:
                    return
                last_reported[0] = current_sec
                if use_duration_mode:
                    progress.advance(overall_task, delta)
                progress.update(file_task, completed=current_sec)

            cb = on_progress if not args.no_progress else None

            vmaf_score = None
            ssim_score = None
            psnr_score = None

            if args.metric == "vmaf":
                vmaf_score = run_vmaf(
                    args.source,
                    transcoded,
                    threads=threads_per_job,
                    progress_callback=cb,
                    n_subsample=args.n_subsample,
                )
            else:
                ssim_score, psnr_score = run_ssim_psnr(
                    args.source,
                    transcoded,
                    threads=threads_per_job,
                    progress_callback=cb,
                )

            if use_duration_mode and file_duration is not None:
                remaining = file_duration - last_reported[0]
                if remaining > 0:
                    progress.advance(overall_task, remaining)
            elif not use_duration_mode:
                progress.advance(overall_task, 1)

            progress.remove_task(file_task)

            transcoded_size = transcoded.stat().st_size
            compression_ratio = source_size / transcoded_size if transcoded_size > 0 else 0
            data_saved = source_size - transcoded_size
            codec = get_codec(transcoded)

            result = {
                "filename": transcoded.name,
                "codec": codec,
                "compression_ratio": compression_ratio,
                "file_size": transcoded_size,
                "data_saved": data_saved,
                "vmaf_score": vmaf_score,
                "ssim_score": ssim_score,
                "psnr_score": psnr_score,
            }

            completed_count = len(results) + 1
            if args.metric == "vmaf":
                score_str = f"{vmaf_score:.2f}" if vmaf_score is not None else "ERROR"
                progress.console.log(
                    f"[green]✓[/green] {transcoded.name}  "
                    f"[bold]VMAF:[/bold] {score_str}  "
                    f"({completed_count}/{total_files})"
                )
            else:
                if ssim_score is not None and psnr_score is not None:
                    psnr_disp = "inf dB" if math.isinf(psnr_score) else f"{psnr_score:.2f} dB"
                    score_str = f"SSIM: {ssim_score:.4f}  PSNR: {psnr_disp}"
                else:
                    score_str = "ERROR"
                progress.console.log(
                    f"[green]✓[/green] {transcoded.name}  "
                    f"[bold]{score_str}[/bold]  "
                    f"({completed_count}/{total_files})"
                )

            return result

        with ThreadPoolExecutor(max_workers=jobs) as executor:
            futures = {executor.submit(process_file, t): t for t in transcoded_files}
            for future in as_completed(futures):
                results.append(future.result())
                completed = len(results)
                left = total_files - completed
                if use_duration_mode:
                    progress.update(
                        overall_task,
                        description=f"Computing {metric_label} ({completed}/{total_files} files)",
                    )
                else:
                    progress.update(
                        overall_task,
                        description=(
                            f"Computing {metric_label} ({completed}/{total_files} files, {left} left)"
                        ),
                    )

    sort_key = args.sort
    if sort_key == "name":
        results.sort(key=lambda r: (r["filename"].lower(),))
    elif sort_key == "ratio":
        results.sort(
            key=lambda r: (
                r["compression_ratio"] is None or r["compression_ratio"] <= 0,
                -(r["compression_ratio"] or 0),
            )
        )
    elif sort_key == "saved":
        results.sort(key=lambda r: (False, -r["data_saved"]))
    elif args.metric == "vmaf":
        results.sort(key=lambda r: (r["vmaf_score"] is None, -(r["vmaf_score"] or 0)))
    else:
        results.sort(key=lambda r: (r["ssim_score"] is None, -(r["ssim_score"] or 0)))

    console.print()

    if args.metric == "vmaf":
        console.print(
            "VMAF Scale (0–100): 100 = identical to source | 93+ = perceptually transparent | "
            "80–93 = good | 60–80 = fair | <60 = poor"
        )
    else:
        console.print(
            "SSIM Scale (0–1): 1.000 = identical | 0.990+ = excellent | 0.950–0.990 = good | "
            "0.900–0.950 = fair | <0.900 = poor"
        )
        console.print(
            "PSNR Scale (dB): 50+ = excellent | 40–50 = good | 30–40 = fair | <30 = poor"
        )

    console.print()

    # expand=True uses full terminal width; Filename uses fold so long names wrap instead of "…"
    table = Table(show_header=True, header_style="bold", expand=True)
    table.add_column(
        "Filename",
        style="cyan",
        overflow="fold",
        ratio=3,
        min_width=24,
    )
    table.add_column("Codec", justify="center", ratio=1)
    table.add_column("Compression Ratio", justify="right", ratio=1)
    table.add_column("File Size", justify="right", ratio=1)
    table.add_column("Data Saved", justify="right", ratio=1)
    if args.metric == "vmaf":
        table.add_column("VMAF Score", justify="right", ratio=1)
    else:
        table.add_column("SSIM", justify="right", ratio=1)
        table.add_column("PSNR (dB)", justify="right", ratio=1)

    for r in results:
        if args.metric == "vmaf":
            vmaf_str = f"{r['vmaf_score']:.2f}" if r["vmaf_score"] is not None else "ERROR"
            table.add_row(
                r["filename"],
                r["codec"],
                f"{r['compression_ratio']:.2f}x",
                format_size(r["file_size"]),
                format_size(r["data_saved"]),
                vmaf_str,
            )
        else:
            ssim_str = f"{r['ssim_score']:.4f}" if r["ssim_score"] is not None else "ERROR"
            if r["psnr_score"] is None:
                psnr_str = "ERROR"
            elif math.isinf(r["psnr_score"]):
                psnr_str = "inf"
            else:
                psnr_str = f"{r['psnr_score']:.2f}"
            table.add_row(
                r["filename"],
                r["codec"],
                f"{r['compression_ratio']:.2f}x",
                format_size(r["file_size"]),
                format_size(r["data_saved"]),
                ssim_str,
                psnr_str,
            )

    console.print(table)

    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        max_fn_len = max((len(r["filename"]) for r in results), default=0)
        # Wide enough for full filenames + other columns (cap avoids huge lines on pathological names)
        file_width = min(max(max_fn_len + 72, 120), 400)
        with open(args.output, "w") as f:
            out_console = Console(
                file=f,
                no_color=True,
                force_terminal=False,
                width=file_width,
            )
            out_console.print()
            if args.metric == "vmaf":
                out_console.print(
                    "VMAF Scale (0–100): 100 = identical to source | 93+ = perceptually transparent | "
                    "80–93 = good | 60–80 = fair | <60 = poor"
                )
            else:
                out_console.print(
                    "SSIM Scale (0–1): 1.000 = identical | 0.990+ = excellent | 0.950–0.990 = good | "
                    "0.900–0.950 = fair | <0.900 = poor"
                )
                out_console.print(
                    "PSNR Scale (dB): 50+ = excellent | 40–50 = good | 30–40 = fair | <30 = poor"
                )
            out_console.print()
            out_console.print(table)

    return 0


if __name__ == "__main__":
    sys.exit(main())
