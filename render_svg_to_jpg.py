#!/usr/bin/env python3
"""
Batch SVG to JPG Renderer
=========================
Renders all SVG files in a directory to high-quality JPGs with custom background
color and multithreaded processing using ImageMagick (`magick`).

Usage:
    python render_svg_to_jpg.py
    python render_svg_to_jpg.py --input path/to/svg --output path/to/jpg --quality 95 --workers 8
"""

import os
import sys
import glob
import shutil
import argparse
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed

# Handle Windows UTF-8 stdout if needed
if sys.platform == "win32":
    try:
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
    except Exception:
        pass


def check_imagemagick():
    """Verify ImageMagick 'magick' executable is available in PATH."""
    if not shutil.which("magick"):
        print("Error: ImageMagick ('magick') command was not found in PATH.", file=sys.stderr)
        print("Please install ImageMagick from https://imagemagick.org/ and ensure it is added to your PATH.", file=sys.stderr)
        return False
    return True


def convert_svg(svg_path, out_dir, quality=95, background="white"):
    """Render a single SVG to JPG."""
    base_name = os.path.splitext(os.path.basename(svg_path))[0]
    out_path = os.path.join(out_dir, f"{base_name}.jpg")
    cmd = [
        "magick",
        "-background", background,
        svg_path,
        "-flatten",
        "-quality", str(quality),
        out_path
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        return False, svg_path, res.stderr.strip()
    return True, svg_path, None


def main():
    parser = argparse.ArgumentParser(description="Batch render SVG files to JPG format using ImageMagick.")
    parser.add_argument(
        "-i", "--input",
        default=os.getcwd(),
        help="Input directory containing SVG files (default: current directory)."
    )
    parser.add_argument(
        "-o", "--output",
        default=None,
        help="Output directory to save JPGs (default: <input>/jpg)."
    )
    parser.add_argument(
        "-q", "--quality",
        type=int,
        default=95,
        help="JPEG output quality between 1 and 100 (default: 95)."
    )
    parser.add_argument(
        "-b", "--background",
        default="white",
        help="Canvas background color for transparent SVGs (default: white)."
    )
    default_workers = max(1, (os.cpu_count() or 4) // 2)
    parser.add_argument(
        "-w", "--workers",
        type=int,
        default=default_workers,
        help=f"Number of parallel worker threads (default: CPU count / 2 = {default_workers})."
    )

    args = parser.parse_args()

    if not check_imagemagick():
        sys.exit(1)

    input_dir = os.path.abspath(args.input)
    if not os.path.isdir(input_dir):
        print(f"Error: Input directory does not exist: {input_dir}", file=sys.stderr)
        sys.exit(1)

    output_dir = os.path.abspath(args.output) if args.output else os.path.join(input_dir, "jpg")
    os.makedirs(output_dir, exist_ok=True)

    svg_files = sorted(glob.glob(os.path.join(input_dir, "*.svg")))
    if not svg_files:
        print(f"No SVG files found in: {input_dir}")
        return

    print(f"Found {len(svg_files)} SVG file(s) in: {input_dir}")
    print(f"Output directory : {output_dir}")
    print(f"Quality          : {args.quality}")
    print(f"Background       : {args.background}")
    print(f"Worker threads   : {args.workers}")
    print("-" * 50)

    completed = 0
    failed = []

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(convert_svg, svg, output_dir, args.quality, args.background): svg
            for svg in svg_files
        }

        for future in as_completed(futures):
            success, svg, err = future.result()
            completed += 1
            if success:
                if completed % 10 == 0 or completed == len(svg_files):
                    print(f"Progress: {completed}/{len(svg_files)} completed...")
            else:
                print(f"[Error] Failed to render {os.path.basename(svg)}:\n  {err}", file=sys.stderr)
                failed.append((svg, err))

    print("-" * 50)
    print(f"Done! Successfully converted: {completed - len(failed)}/{len(svg_files)}")
    if failed:
        print(f"Failed conversions: {len(failed)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
