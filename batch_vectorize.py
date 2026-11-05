#!/usr/bin/env python3
"""
VectorCraft Batch Trace Tool
============================
Automated vectorization, trimming, proportional scaling, and canvas padding
for raster images using the VectorCraft CLI engine.

Credits:
  Built on top of VectorCraft by ArtCraft
  Upstream Repository: https://github.com/storytold/vectorcraft

Repository: https://github.com/nooradn/vectorcraft-batch-trace-tool
License: MIT
"""

import os
import sys
import json
import glob
import shutil
import argparse
import tempfile
import subprocess
from pathlib import Path

# --- Windows Double-Click & Encoding Fixes ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
try:
    os.chdir(SCRIPT_DIR)
except Exception:
    pass

if sys.platform == "win32":
    try:
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
    except Exception:
        pass

# Default search paths for VectorCraft CLI binary
DEFAULT_CLI_PATHS = [
    r"C:\Program Files\VectorCraft\vectorcraft-cli.exe",
    r"C:\Program Files (x86)\VectorCraft\vectorcraft-cli.exe",
    os.path.expanduser(r"~\AppData\Local\Programs\VectorCraft\vectorcraft-cli.exe"),
    "/usr/local/bin/vectorcraft-cli",
    "/usr/bin/vectorcraft-cli",
    "/opt/vectorcraft/vectorcraft-cli",
]

SUPPORTED_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".gif"}


def find_vectorcraft_cli(custom_path=None):
    """Locate the VectorCraft CLI executable."""
    if custom_path and os.path.isfile(custom_path):
        return custom_path

    which_cli = shutil.which("vectorcraft-cli")
    if which_cli:
        return which_cli

    for p in DEFAULT_CLI_PATHS:
        if os.path.isfile(p):
            return p

    return None


def move_existing_vectorcraft_files(folder, vc_folder_name="vectorcraft_files"):
    """Organize loose .vectorcraft files into a dedicated subfolder."""
    target_dir = os.path.join(folder, vc_folder_name)
    moved_count = 0
    try:
        for item in os.listdir(folder):
            item_path = os.path.join(folder, item)
            if os.path.isfile(item_path) and item.lower().endswith(".vectorcraft"):
                os.makedirs(target_dir, exist_ok=True)
                dest_path = os.path.join(target_dir, item)
                shutil.move(item_path, dest_path)
                moved_count += 1
    except Exception as e:
        print(f"Warning: Could not move existing .vectorcraft files: {e}")
    return moved_count


def process_image(cli_path, input_path, output_dir=None, vc_dir_name="vectorcraft_files",
                  min_art_size=3000.0, padding=500.0, preset="Black and White Logo",
                  out_format="both", png_preview=False, force_square=False):
    """
    Vectorize an image, trim empty borders, scale proportionally, and pad the artboard.
    """
    input_path = os.path.abspath(input_path)
    base_name = Path(input_path).stem
    parent_dir = output_dir or os.path.dirname(input_path)
    os.makedirs(parent_dir, exist_ok=True)

    vc_dir = os.path.join(parent_dir, vc_dir_name)
    if out_format in ("vectorcraft", "both"):
        os.makedirs(vc_dir, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp_dir:
        temp_vc = os.path.join(tmp_dir, "trimmed.vectorcraft")
        cmd1_path = os.path.join(tmp_dir, "cmd1.json")
        cmd2_path = os.path.join(tmp_dir, "cmd2.json")

        # Step 1: Trace raster image and fit artboard to selection (trim margins)
        cmd1 = [
            {"command": "select.all"},
            {"command": "imageTrace.makeAndExpand", "params": {"preset": preset, "enhanced": True}},
            {"command": "select.all"},
            {"command": "artboard.fitToSelection"}
        ]
        with open(cmd1_path, "w", encoding="utf-8") as f:
            json.dump(cmd1, f)

        res1 = subprocess.run(
            [cli_path, "run", "--in", input_path, "--commands", cmd1_path, "--export", temp_vc],
            capture_output=True, text=True
        )
        if res1.returncode != 0:
            print(f"  [Error] Step 1 trace failed for {input_path}:\n{res1.stderr or res1.stdout}", file=sys.stderr)
            return False

        # Step 2: Read trimmed bounding dimensions
        res_info = subprocess.run([cli_path, "info", temp_vc], capture_output=True, text=True)
        if res_info.returncode != 0:
            print(f"  [Error] Failed to read info for {temp_vc}", file=sys.stderr)
            return False

        try:
            info_data = json.loads(res_info.stdout)
            rect = info_data["artboards"][0]["rect"]
            orig_w, orig_h = float(rect[2]), float(rect[3])
        except Exception as e:
            print(f"  [Error] Could not parse artboard bounds: {e}", file=sys.stderr)
            return False

        if orig_w <= 0 or orig_h <= 0:
            print(f"  [Error] Invalid bounds ({orig_w} x {orig_h})", file=sys.stderr)
            return False

        # Step 3: Compute proportional scaling and padded artboard dimensions
        if force_square:
            art_w = min_art_size
            art_h = min_art_size
        else:
            if orig_w <= orig_h:
                art_w = min_art_size
                art_h = orig_h * (min_art_size / orig_w)
            else:
                art_h = min_art_size
                art_w = orig_w * (min_art_size / orig_h)

        board_w = art_w + padding * 2
        board_h = art_h + padding * 2

        # Step 4: Scale art, expand canvas, and center art
        cmd2 = [
            {"command": "select.all"},
            {"command": "artboard.setProps", "params": {"index": 0, "width": art_w, "height": art_h, "scaleArt": True}},
            {"command": "artboard.setProps", "params": {"index": 0, "x": 0, "y": 0, "width": board_w, "height": board_h}},
            {"command": "select.all"},
            {"command": "object.align", "params": {"horizontal": "center", "vertical": "center", "to": "artboard"}}
        ]
        with open(cmd2_path, "w", encoding="utf-8") as f:
            json.dump(cmd2, f)

        target_svg = os.path.join(parent_dir, f"{base_name}.svg")
        target_vc = os.path.join(vc_dir, f"{base_name}.vectorcraft")
        target_png = os.path.join(parent_dir, f"{base_name}.png")

        run_args = [cli_path, "run", "--in", temp_vc, "--commands", cmd2_path]
        if out_format in ("svg", "both"):
            run_args.extend(["--export", target_svg])
        if out_format in ("vectorcraft", "both"):
            run_args.extend(["--export", target_vc])

        res2 = subprocess.run(run_args, capture_output=True, text=True)
        if res2.returncode != 0:
            print(f"  [Error] Step 2 transform failed for {input_path}:\n{res2.stderr or res2.stdout}", file=sys.stderr)
            return False

        if png_preview and os.path.isfile(target_svg):
            subprocess.run([cli_path, "convert", target_svg, target_png], capture_output=True)

        print(f"  [Success] {base_name}: trimmed -> art {art_w:.1f}x{art_h:.1f} -> canvas {board_w:.1f}x{board_h:.1f} px (padding {padding} px)")
        print(f"            SVG: {target_svg}")
        if out_format in ("vectorcraft", "both"):
            print(f"            VectorCraft: {target_vc}")
        return True


def collect_images(paths=None, scan_dir=None):
    """Collect image files from individual file paths, directories, or glob patterns."""
    collected = []
    if not paths and scan_dir:
        for f in os.listdir(scan_dir):
            full_p = os.path.join(scan_dir, f)
            if os.path.isfile(full_p) and Path(f).suffix.lower() in SUPPORTED_IMAGE_EXTS:
                collected.append(os.path.abspath(full_p))
        return sorted(collected)

    for p in (paths or []):
        if os.path.isdir(p):
            for root, _, files in os.walk(p):
                for f in files:
                    if Path(f).suffix.lower() in SUPPORTED_IMAGE_EXTS:
                        collected.append(os.path.join(root, f))
        elif "*" in p or "?" in p:
            for f in glob.glob(p):
                if Path(f).suffix.lower() in SUPPORTED_IMAGE_EXTS:
                    collected.append(os.path.abspath(f))
        elif os.path.isfile(p):
            if Path(p).suffix.lower() in SUPPORTED_IMAGE_EXTS:
                collected.append(os.path.abspath(p))
            else:
                print(f"Warning: {p} does not appear to be a supported image format. Skipping.")
        else:
            print(f"Warning: path not found: {p}")
    return sorted(list(set(collected)))


def main():
    is_interactive_double_click = (len(sys.argv) <= 1)

    parser = argparse.ArgumentParser(
        description="Batch vectorize images with VectorCraft, trim padding, scale proportionally, and add custom margins."
    )
    parser.add_argument("inputs", nargs="*", help="Image files, folders, or wildcards to process (default: scans current folder).")
    parser.add_argument("--cli", default=None, help="Path to vectorcraft-cli executable if not in default location.")
    parser.add_argument("--out-dir", default=None, help="Custom output directory (default: same as input image).")
    parser.add_argument("--vc-dir", default="vectorcraft_files", help="Folder name for .vectorcraft projects (default: 'vectorcraft_files').")
    parser.add_argument("--min-art-size", type=float, default=3000.0, help="Target size for the smaller side of the art (default: 3000).")
    parser.add_argument("--padding", type=float, default=500.0, help="Padding on each side in px (default: 500, so min canvas side = 4000).")
    parser.add_argument("--preset", default="Black and White Logo", help="VectorCraft tracing preset (default: 'Black and White Logo').")
    parser.add_argument("--format", choices=["svg", "vectorcraft", "both"], default="both", help="Output formats to export (default: both).")
    parser.add_argument("--png-preview", action="store_true", help="Also generate a rendered PNG preview.")
    parser.add_argument("--force-square", action="store_true", help="Force 1:1 square canvas even if artwork is rectangular.")

    args = parser.parse_args()

    cli_path = find_vectorcraft_cli(args.cli)
    if not cli_path:
        print("Error: Could not locate vectorcraft-cli executable. Please install VectorCraft or specify --cli path.", file=sys.stderr)
        if is_interactive_double_click:
            input("\nPress Enter to exit...")
        sys.exit(1)

    if args.inputs:
        images = collect_images(paths=args.inputs)
    else:
        print(f"No specific files provided. Auto-scanning current directory:\n  {SCRIPT_DIR}\n")
        images = collect_images(scan_dir=SCRIPT_DIR)

    scan_folders = {os.path.dirname(img) for img in images} if images else {SCRIPT_DIR}
    for folder in scan_folders:
        moved = move_existing_vectorcraft_files(folder, args.vc_dir)
        if moved > 0:
            print(f"Moved {moved} existing .vectorcraft file(s) into '{args.vc_dir}' subfolder.")

    if not images:
        print("No *.jpg or *.png image files found to process.")
        if is_interactive_double_click:
            input("\nPress Enter to exit...")
        sys.exit(0)

    print(f"Found {len(images)} image(s) to process using VectorCraft CLI ({cli_path})")
    print(f"Settings: Min Art Size={args.min_art_size}px, Padding={args.padding}px (Min Canvas={args.min_art_size + args.padding * 2}px), Preset='{args.preset}'")
    print(f"VectorCraft projects folder: '{args.vc_dir}'\n")

    successful = 0
    for idx, img_path in enumerate(images, 1):
        print(f"[{idx}/{len(images)}] Processing: {os.path.basename(img_path)}...")
        ok = process_image(
            cli_path=cli_path,
            input_path=img_path,
            output_dir=args.out_dir,
            vc_dir_name=args.vc_dir,
            min_art_size=args.min_art_size,
            padding=args.padding,
            preset=args.preset,
            out_format=args.format,
            png_preview=args.png_preview,
            force_square=args.force_square
        )
        if ok:
            successful += 1

    print(f"\nCompleted! Successfully processed {successful}/{len(images)} image(s).")

    if is_interactive_double_click:
        try:
            input("\nPress Enter to exit...")
        except Exception:
            pass


if __name__ == "__main__":
    main()
