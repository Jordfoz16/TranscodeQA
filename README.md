# VMAF Transcode Comparison

Compare transcoded video files against a source file using VMAF (Video Multi-Method Assessment Fusion) quality analysis. Produces a table with filename, compression ratio, file size, data saved, and VMAF score.

## Prerequisites

- **Python 3.8+**
- **ffmpeg** with libvmaf support (built with `--enable-libvmaf`)

Verify ffmpeg has libvmaf:

```bash
ffmpeg -filters 2>&1 | grep vmaf
```

You should see `libvmaf` in the output. If not, install a build of ffmpeg that includes it (e.g. via Homebrew on macOS: `brew install ffmpeg`).

## Installation

```bash
python -m venv .venv
source .venv/bin/activate   # On Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Usage

Activate the venv, then run:

```bash
source .venv/bin/activate   # On Windows: .venv\Scripts\activate
python vmaf_compare.py <source_file> <transcoded_path>
```

### Example

```bash
source .venv/bin/activate
python vmaf_compare.py samples/base.mkv samples/transcoded/
```

### Options

- `--extensions` – Comma-separated video extensions to search (default: `mkv,mp4,webm,mov`)
- `--no-progress` – Disable the progress bar (useful when piping output)
- `--n-subsample`, `-n` – Pass `n_subsample` to ffmpeg’s `libvmaf` filter: score every Nth frame (default: `1` = every frame). Speeds up long sources; scores are noisier on short clips. Odd values (e.g. 3, 5) are often preferable to even values for some encodes.
- `--jobs`, `-j` – Number of parallel VMAF jobs (default: 4). Pass `--jobs 1` for single-threaded.
- `--sort` – Sort table by `name`, `ratio`, `saved`, or `score` (default: `ratio`)
- `--output`, `-o` – Write results to a file (plain text) in addition to printing to the terminal. Progress bars are still shown; use `--no-progress` to suppress them.

## Output

The script shows:

1. A progress bar with estimated time remaining while processing
2. A VMAF scale guide explaining score interpretation
3. A table with:
   - **Filename** – Name of the transcoded file
   - **Codec** – Video codec (e.g. h264, h265, av1)
   - **Compression Ratio** – Source size ÷ transcoded size (e.g. 2.5x = transcoded is 2.5× smaller)
   - **File Size** – Size of the transcoded file
   - **Data Saved** – Bytes saved compared to the source
   - **VMAF Score** – Quality score (0–100)

Results are sorted by compression ratio by default; use `--sort` to sort by name, data saved, or VMAF score.

## Docker

### Pulling from GHCR

Pre-built multi-architecture images are published to [GitHub Container Registry](https://github.com/jordfoz16/TranscodeQA/pkgs/container/TranscodeQA):

```bash
docker pull ghcr.io/jordfoz16/TranscodeQA:latest
```

Supports **linux/amd64** (x86_64) and **linux/arm64** (Raspberry Pi 4/5). Docker automatically pulls the right image for your platform.

If the package is private, make it public via the package settings, or authenticate with `docker login ghcr.io -u USERNAME -p YOUR_GITHUB_PAT` before pulling.

### Building locally

```bash
docker build -t vmaf-compare .
```

### Running

Run with volume mounts for the source file and transcoded folder. The `-t` flag allocates a pseudo-TTY so the progress bars render correctly:

```bash
docker run --rm -t \
  -v "$(pwd)/samples:/input:ro" \
  ghcr.io/jordfoz16/transcodeqa:latest \
  /input/base.mkv /input/transcoded/codec/
```

To also save results to a file, add `-v` for the output directory and `--output`:

```bash
docker run --rm -t \
  -v "$(pwd)/samples:/input:ro" \
  -v "$(pwd)/output:/output" \
  ghcr.io/jordfoz16/transcodeqa:latest \
  /input/base.mkv /input/transcoded/codec/ \
  --output /output/results.txt
```

With a local build, replace `ghcr.io/jordfoz16/transcodeqa:latest` with `vmaf-compare`.

### Docker Compose

Two services are defined in [docker-compose.yml](docker-compose.yml) — update the `command` paths to match your files before running.

**Interactive** (live progress bars, results printed to terminal):

```bash
docker compose run --rm transcodeqa
```

**Unattended** (no TTY needed, results written to `./output/results.txt`):

```bash
docker compose run --rm transcodeqa-batch
```
