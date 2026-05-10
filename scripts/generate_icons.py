#!/usr/bin/env python3
"""
Generate extension icons (16x16, 48x48, 128x128 PNG) using Pillow.
Run once before loading the extension in Chrome.

Usage:
    pip install Pillow
    python scripts/generate_icons.py
"""

import os
import sys

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("Installing Pillow...")
    os.system(f"{sys.executable} -m pip install Pillow --quiet")
    from PIL import Image, ImageDraw, ImageFont


def make_icon(size: int, output_path: str):
    """Generate a clean icon: dark background + white bank emoji-style glyph."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Rounded rectangle background
    bg_color = (26, 26, 46, 255)       # #1a1a2e
    accent = (96, 165, 250, 255)       # #60a5fa blue

    radius = size // 5
    draw.rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=bg_color)

    # Simple column chart icon (fintech / data feel)
    pad = size // 5
    bar_w = max(2, size // 10)
    gap = max(1, size // 14)
    bottom = size - pad
    bars = [
        (pad,                    int(size * 0.55)),  # short
        (pad + bar_w + gap,      int(size * 0.35)),  # medium
        (pad + 2 * (bar_w+gap),  int(size * 0.20)),  # tall
    ]
    for x, top in bars:
        draw.rectangle([x, top, x + bar_w, bottom], fill=accent)

    # Accent line at bottom
    line_h = max(1, size // 16)
    draw.rectangle([pad, bottom + 1, size - pad, bottom + line_h], fill=accent)

    img.save(output_path, "PNG")
    print(f"  Generated: {output_path} ({size}x{size})")


def main():
    icons_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "extension", "icons")
    os.makedirs(icons_dir, exist_ok=True)

    for size in [16, 48, 128]:
        make_icon(size, os.path.join(icons_dir, f"icon{size}.png"))

    print("\n✅ Icons generated in extension/icons/")
    print("   Now load the extension in Chrome:")
    print("   1. Open chrome://extensions")
    print("   2. Enable Developer mode")
    print("   3. Click 'Load unpacked' → select the extension/ folder")


if __name__ == "__main__":
    main()