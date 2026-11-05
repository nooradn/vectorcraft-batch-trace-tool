#!/usr/bin/env python3
"""
VectorCraft Batch Trace Tool
============================
Automated vectorization, trimming, proportional scaling, and canvas padding
for raster images using the VectorCraft CLI engine. Includes an optional
post-trace raster rendering step (SVG -> JPG/PNG) powered by ImageMagick
or VectorCraft CLI.

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
from concurrent.futures import ThreadPoolExecutor, as_completed

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


def move_existing_files(folder, extension, target_subfolder):
    """Organize loose files with a given extension into a dedicated subfolder."""
    target_dir = os.path.join(folder, target_subfolder)
    moved_count = 0
    try:
        for item in os.listdir(folder):
            item_path = os.path.join(folder, item)
            if os.path.isfile(item_path) and item.lower().endswith(extension.lower()):
                os.makedirs(target_dir, exist_ok=True)
                dest_path = os.path.join(target_dir, item)
                shutil.move(item_path, dest_path)
                moved_count += 1
    except Exception as e:
        print(f"Warning: Could not move existing {extension} files: {e}")
    return moved_count


def process_image(cli_path, input_path, output_dir=None, svg_dir_name="svg",
                  vc_dir_name="vectorcraft_files", min_art_size=3000.0, padding=500.0,
                  preset="Black and White Logo", out_format="both", force_square=False):
    """
    Vectorize an image, trim empty borders, scale proportionally, and pad the artboard.
    Returns (success: bool, svg_path: str or None).
    """
    input_path = os.path.abspath(input_path)
    base_name = Path(input_path).stem
    parent_dir = output_dir or os.path.dirname(input_path)
    os.makedirs(parent_dir, exist_ok=True)

    svg_dir = os.path.join(parent_dir, svg_dir_name)
    vc_dir = os.path.join(parent_dir, vc_dir_name)

    if out_format in ("svg", "both"):
        os.makedirs(svg_dir, exist_ok=True)
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
            return False, None

        # Step 2: Read trimmed bounding dimensions
        res_info = subprocess.run([cli_path, "info", temp_vc], capture_output=True, text=True)
        if res_info.returncode != 0:
            print(f"  [Error] Failed to read info for {temp_vc}", file=sys.stderr)
            return False, None

        try:
            info_data = json.loads(res_info.stdout)
            rect = info_data["artboards"][0]["rect"]
            orig_w, orig_h = float(rect[2]), float(rect[3])
        except Exception as e:
            print(f"  [Error] Could not parse artboard bounds: {e}", file=sys.stderr)
            return False, None

        if orig_w <= 0 or orig_h <= 0:
            print(f"  [Error] Invalid bounds ({orig_w} x {orig_h})", file=sys.stderr)
            return False, None

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

        target_svg = os.path.join(svg_dir, f"{base_name}.svg")
        target_vc = os.path.join(vc_dir, f"{base_name}.vectorcraft")

        run_args = [cli_path, "run", "--in", temp_vc, "--commands", cmd2_path]
        if out_format in ("svg", "both"):
            run_args.extend(["--export", target_svg])
        if out_format in ("vectorcraft", "both"):
            run_args.extend(["--export", target_vc])

        res2 = subprocess.run(run_args, capture_output=True, text=True)
        if res2.returncode != 0:
            print(f"  [Error] Step 2 transform failed for {input_path}:\n{res2.stderr or res2.stdout}", file=sys.stderr)
            return False, None

        print(f"  [Success] {base_name}: trimmed -> art {art_w:.1f}x{art_h:.1f} -> canvas {board_w:.1f}x{board_h:.1f} px (padding {padding} px)")
        if out_format in ("svg", "both"):
            print(f"            SVG: {target_svg}")
        if out_format in ("vectorcraft", "both"):
            print(f"            VectorCraft: {target_vc}")

        return True, (target_svg if os.path.isfile(target_svg) else None)


def render_single_svg(svg_path, out_format, out_dir, quality=95, background="white", cli_path=None):
    """
    Render a single SVG to JPG or PNG using ImageMagick (magick) with fallback to vectorcraft-cli.
    """
    base_name = Path(svg_path).stem
    ext = out_format.lower().lstrip(".")
    out_path = os.path.join(out_dir, f"{base_name}.{ext}")

    has_magick = bool(shutil.which("magick"))

    if has_magick:
        cmd = ["magick"]
        if ext in ("jpg", "jpeg"):
            cmd.extend(["-background", background, svg_path, "-flatten", "-quality", str(quality), out_path])
        else:  # png
            cmd.extend(["-background", "none", svg_path, out_path])
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            return False, svg_path, res.stderr.strip()
        return True, out_path, None

    # Fallback to VectorCraft CLI
    if cli_path and os.path.isfile(cli_path):
        res = subprocess.run([cli_path, "convert", svg_path, out_path], capture_output=True, text=True)
        if res.returncode != 0:
            return False, svg_path, res.stderr.strip()
        return True, out_path, None

    return False, svg_path, "Neither ImageMagick ('magick') nor VectorCraft CLI found for rendering."


def batch_render_svgs(svg_paths, formats, quality=95, background="white", workers=None, cli_path=None, base_out_dir=None):
    """
    Render a list of SVGs to JPG and/or PNG using a thread pool.
    """
    if not svg_paths or not formats:
        return

    workers = workers or min(8, os.cpu_count() or 4)
    tasks = []

    for svg in svg_paths:
        # Save renders alongside the svg subfolder (e.g. parent/jpg, parent/png)
        svg_parent = os.path.dirname(svg)
        if base_out_dir:
            root_parent = base_out_dir
        elif os.path.basename(svg_parent).lower() in ("svg", "svg_files"):
            root_parent = os.path.dirname(svg_parent)
        else:
            root_parent = svg_parent

        for fmt in formats:
            sub_dir = os.path.join(root_parent, fmt)
            os.makedirs(sub_dir, exist_ok=True)
            tasks.append((svg, fmt, sub_dir))

    total = len(tasks)
    print(f"\nRendering {len(svg_paths)} SVG(s) into {', '.join(f.upper() for f in formats)} ({total} file(s) total)...")
    print(f"Workers: {workers} | Engine: {'ImageMagick (magick)' if shutil.which('magick') else 'VectorCraft CLI'}")
    print("-" * 50)

    completed = 0
    failed = []

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(render_single_svg, svg, fmt, out_dir, quality, background, cli_path): (svg, fmt)
            for svg, fmt, out_dir in tasks
        }

        for future in as_completed(futures):
            success, path, err = future.result()
            completed += 1
            if success:
                if completed % 10 == 0 or completed == total:
                    print(f"  Progress: {completed}/{total} completed...")
            else:
                orig_svg, fmt = futures[future]
                print(f"  [Error] Failed to render {os.path.basename(orig_svg)} to {fmt}: {err}", file=sys.stderr)
                failed.append((orig_svg, err))

    print("-" * 50)
    print(f"Rendering complete! Successfully generated: {completed - len(failed)}/{total} file(s).")


def prompt_render_choice():
    """Interactive prompt asking the user if they wish to render SVGs into JPG/PNG."""
    print("\n" + "=" * 50)
    print("Render modified SVGs to raster images (JPG / PNG)?")
    print("  [1] Render to JPG (white background, quality 95)")
    print("  [2] Render to PNG (transparent)")
    print("  [3] Render both JPG & PNG")
    print("  [0 / Enter] Skip rendering")
    print("=" * 50)

    try:
        choice = input("Choose option [0-3] (default: 0): ").strip()
    except Exception:
        return []

    if choice in ("1", "jpg", "JPG"):
        return ["jpg"]
    elif choice in ("2", "png", "PNG"):
        return ["png"]
    elif choice in ("3", "both", "BOTH"):
        return ["jpg", "png"]
    return []


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
        description="Batch vectorize images with VectorCraft, trim padding, scale proportionally, and optionally render to JPG/PNG."
    )
    parser.add_argument("inputs", nargs="*", help="Image files, folders, or wildcards to process (default: scans current folder).")
    parser.add_argument("--cli", default=None, help="Path to vectorcraft-cli executable if not in default location.")
    parser.add_argument("--out-dir", default=None, help="Custom output directory (default: same as input image).")
    parser.add_argument("--svg-dir", default="svg", help="Subfolder name for SVG files (default: 'svg').")
    parser.add_argument("--vc-dir", default="vectorcraft_files", help="Subfolder name for .vectorcraft projects (default: 'vectorcraft_files').")
    parser.add_argument("--min-art-size", type=float, default=3000.0, help="Target size for the smaller side of the art (default: 3000).")
    parser.add_argument("--padding", type=float, default=500.0, help="Padding on each side in px (default: 500, so min canvas side = 4000).")
    parser.add_argument("--preset", default="Black and White Logo", help="VectorCraft tracing preset (default: 'Black and White Logo').")
    parser.add_argument("--format", choices=["svg", "vectorcraft", "both"], default="both", help="Vector formats to export (default: both).")
    parser.add_argument("--force-square", action="store_true", help="Force 1:1 square canvas even if artwork is rectangular.")

    # Duplicate check & overwrite options
    parser.add_argument("--overwrite", action="store_true", help="Automatically overwrite and re-trace existing SVGs without prompt.")
    parser.add_argument("--skip-existing", action="store_true", help="Automatically skip images that already have SVGs without prompt.")

    # Post-trace raster rendering options
    parser.add_argument(
        "--render",
        choices=["prompt", "jpg", "png", "both", "none"],
        default=None,
        help="Post-trace raster render mode (default: 'prompt' if interactive, else 'none')."
    )
    parser.add_argument("--raster-quality", type=int, default=95, help="JPEG quality 1-100 (default: 95).")
    parser.add_argument("--raster-bg", default="white", help="Canvas background color for transparent SVGs in JPG (default: white).")
    parser.add_argument("--workers", type=int, default=min(8, os.cpu_count() or 4), help="Parallel worker threads for rendering.")

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
        # Move existing loose files into their subfolders
        moved_vc = move_existing_files(folder, ".vectorcraft", args.vc_dir)
        if moved_vc > 0:
            print(f"Moved {moved_vc} existing .vectorcraft file(s) into '{args.vc_dir}' subfolder.")
        moved_svg = move_existing_files(folder, ".svg", args.svg_dir)
        if moved_svg > 0:
            print(f"Moved {moved_svg} existing .svg file(s) into '{args.svg_dir}' subfolder.")

    if not images:
        print("No *.jpg or *.png image files found to process.")
        if is_interactive_double_click:
            input("\nPress Enter to exit...")
        sys.exit(0)

    print(f"Found {len(images)} image(s) to process using VectorCraft CLI ({cli_path})")
    print(f"Settings: Min Art Size={args.min_art_size}px, Padding={args.padding}px (Min Canvas={args.min_art_size + args.padding * 2}px), Preset='{args.preset}'")
    print(f"Folders : SVGs -> '{args.svg_dir}/' | VectorCraft projects -> '{args.vc_dir}/'\n")

    # --- Pre-Trace Check for Existing SVGs ---
    existing_svg_map = {}
    for img_path in images:
        base_name = Path(img_path).stem
        parent_dir = args.out_dir or os.path.dirname(img_path)
        svg_path = os.path.join(parent_dir, args.svg_dir, f"{base_name}.svg")
        if os.path.isfile(svg_path):
            existing_svg_map[img_path] = svg_path

    images_to_trace = list(images)
    if existing_svg_map:
        count_exist = len(existing_svg_map)
        print("=" * 50)
        print(f"Notice: {count_exist}/{len(images)} image(s) already have an SVG in '{args.svg_dir}/'.")

        retrace = False
        if args.overwrite:
            retrace = True
            print("Flag --overwrite detected: will re-trace and overwrite all.")
        elif args.skip_existing:
            retrace = False
            print("Flag --skip-existing detected: skipping existing SVGs.")
        else:
            print("  [1 / Enter] Skip existing (default)")
            print("  [2] Re-trace and overwrite")
            print("=" * 50)
            try:
                choice = input("Choose option [1-2] (default: 1): ").strip()
            except Exception:
                choice = ""
            retrace = (choice == "2")

        if not retrace:
            images_to_trace = [img for img in images if img not in existing_svg_map]
            print(f"Skipping {count_exist} already-traced file(s). {len(images_to_trace)} remaining to trace.\n")
        else:
            print("Re-tracing all images (overwriting existing SVGs).\n")

    successful_svgs = []
    # Include existing SVGs if skipped so they can still be rendered if desired
    for img_path, svg_p in existing_svg_map.items():
        if img_path not in images_to_trace and os.path.isfile(svg_p):
            successful_svgs.append(svg_p)

    for idx, img_path in enumerate(images_to_trace, 1):
        print(f"[{idx}/{len(images_to_trace)}] Processing: {os.path.basename(img_path)}...")
        ok, svg_path = process_image(
            cli_path=cli_path,
            input_path=img_path,
            output_dir=args.out_dir,
            svg_dir_name=args.svg_dir,
            vc_dir_name=args.vc_dir,
            min_art_size=args.min_art_size,
            padding=args.padding,
            preset=args.preset,
            out_format=args.format,
            force_square=args.force_square
        )
        if ok and svg_path and svg_path not in successful_svgs:
            successful_svgs.append(svg_path)

    print(f"\nTracing complete! Total available SVG(s): {len(successful_svgs)}.")

    # Determine render mode
    render_mode = args.render
    if render_mode is None:
        render_mode = "prompt" if (is_interactive_double_click or len(sys.argv) <= 1) else "none"

    render_formats = []
    if render_mode == "prompt" and successful_svgs:
        render_formats = prompt_render_choice()
    elif render_mode == "jpg":
        render_formats = ["jpg"]
    elif render_mode == "png":
        render_formats = ["png"]
    elif render_mode == "both":
        render_formats = ["jpg", "png"]

    if render_formats and successful_svgs:
        batch_render_svgs(
            svg_paths=successful_svgs,
            formats=render_formats,
            quality=args.raster_quality,
            background=args.raster_bg,
            workers=args.workers,
            cli_path=cli_path,
            base_out_dir=args.out_dir
        )

    if is_interactive_double_click:
        try:
            input("\nPress Enter to exit...")
        except Exception:
            pass


if __name__ == "__main__":
    main()
