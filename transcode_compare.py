#!/usr/bin/env python3
"""Compare transcoded video files against a source using VMAF or SSIM+PSNR quality analysis."""

import sys

from transcodeqa.cli import main

if __name__ == "__main__":
    sys.exit(main())
