#!/usr/bin/env python3
"""Generate AgentStream.icns for the macOS app bundle.

Creates a lightning-bolt icon matching the AgentStream dark theme.
Requires Pillow: pip install Pillow

Usage:
    python macos/create_icon.py              # outputs assets/AgentStream.icns
    python macos/create_icon.py --png-only   # outputs PNGs without iconutil
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
ASSETS_DIR = os.path.join(PROJECT_ROOT, "assets")
ICNS_PATH = os.path.join(ASSETS_DIR, "AgentStream.icns")

# Theme colours
BG_COLOR = (15, 15, 23, 255)        # #0f0f17
ACCENT = (129, 140, 248, 255)       # #818cf8 (indigo accent)
GLOW = (129, 140, 248, 60)          # subtle glow layer

# Lightning bolt polygon (normalised to 0-1 canvas)
# A classic two-step zigzag bolt shape
BOLT = [
    (0.41, 0.08),   # top-left
    (0.64, 0.08),   # top-right
    (0.49, 0.44),   # right edge to mid-seam
    (0.60, 0.44),   # jog right at seam
    (0.36, 0.92),   # bottom point
    (0.51, 0.52),   # left edge back up from bottom
    (0.39, 0.52),   # jog left at seam
]

# Required icon sizes for a macOS .iconset
ICON_SIZES = [
    ("icon_16x16.png", 16),
    ("icon_16x16@2x.png", 32),
    ("icon_32x32.png", 32),
    ("icon_32x32@2x.png", 64),
    ("icon_128x128.png", 128),
    ("icon_128x128@2x.png", 256),
    ("icon_256x256.png", 256),
    ("icon_256x256@2x.png", 512),
    ("icon_512x512.png", 512),
    ("icon_512x512@2x.png", 1024),
]


def _draw_rounded_rect(draw, xy, radius, fill):
    """Draw a filled rounded rectangle (works on older Pillow too)."""
    try:
        draw.rounded_rectangle(xy, radius=radius, fill=fill)
    except AttributeError:
        # Pillow < 8.2 fallback: plain rectangle
        draw.rectangle(xy, fill=fill)


def render_icon(size):
    """Render a single icon at the given pixel size."""
    from PIL import Image, ImageDraw, ImageFilter

    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # --- Background with rounded corners ---
    margin = max(1, size // 32)
    radius = max(2, size // 5)
    _draw_rounded_rect(
        draw,
        [margin, margin, size - margin - 1, size - margin - 1],
        radius=radius,
        fill=BG_COLOR,
    )

    # --- Subtle glow behind the bolt ---
    if size >= 64:
        glow_img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        glow_draw = ImageDraw.Draw(glow_img)
        glow_pts = [(int(x * size), int(y * size)) for x, y in BOLT]
        glow_draw.polygon(glow_pts, fill=GLOW)
        glow_img = glow_img.filter(ImageFilter.GaussianBlur(radius=size // 8))
        img = Image.alpha_composite(img, glow_img)
        draw = ImageDraw.Draw(img)

    # --- Lightning bolt ---
    bolt_pts = [(int(x * size), int(y * size)) for x, y in BOLT]
    draw.polygon(bolt_pts, fill=ACCENT)

    return img


def create_iconset(output_dir):
    """Create all icon PNGs in an .iconset directory."""
    os.makedirs(output_dir, exist_ok=True)

    # Render at each unique pixel size once, then reuse
    cache = {}
    for filename, px in ICON_SIZES:
        if px not in cache:
            cache[px] = render_icon(px)
        cache[px].save(os.path.join(output_dir, filename))

    return output_dir


def build_icns(iconset_dir, output_path):
    """Convert an .iconset directory to .icns using macOS iconutil."""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    subprocess.run(
        ["iconutil", "-c", "icns", iconset_dir, "-o", output_path],
        check=True,
    )
    print(f"Created {output_path}")


def main():
    parser = argparse.ArgumentParser(description="Generate AgentStream app icon")
    parser.add_argument(
        "--png-only", action="store_true",
        help="Generate PNGs in assets/AgentStream.iconset without running iconutil",
    )
    args = parser.parse_args()

    try:
        import PIL  # noqa: F401
    except ImportError:
        print("Pillow is required:  pip install Pillow", file=sys.stderr)
        sys.exit(1)

    if args.png_only:
        iconset_dir = os.path.join(ASSETS_DIR, "AgentStream.iconset")
        create_iconset(iconset_dir)
        print(f"PNGs written to {iconset_dir}")
        return

    # Full build: temp iconset → .icns
    tmp_dir = tempfile.mkdtemp(suffix=".iconset")
    try:
        create_iconset(tmp_dir)

        if shutil.which("iconutil") is None:
            # Not on macOS — save PNGs instead
            dest = os.path.join(ASSETS_DIR, "AgentStream.iconset")
            if os.path.exists(dest):
                shutil.rmtree(dest)
            shutil.move(tmp_dir, dest)
            print(f"iconutil not found (not macOS?). PNGs saved to {dest}")
            print("Run 'iconutil -c icns' on a Mac to convert.")
            return

        build_icns(tmp_dir, ICNS_PATH)
    finally:
        if os.path.isdir(tmp_dir):
            shutil.rmtree(tmp_dir)


if __name__ == "__main__":
    main()
