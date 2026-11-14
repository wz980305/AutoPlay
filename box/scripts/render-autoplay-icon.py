#!/usr/bin/env python3
"""Render the AutoPlay icon (box/assets/autoplay-icon.svg) to the PNG the receiver gives the iPhone for CarPlay's home
screen: drawn by Chromium at 1024 x 1024 (the SVG's gradients, translucency and shadow), scaled to 180 x 180 with
Pillow (Lanczos), RGB with no alpha (the icon is full-bleed; iOS rounds its corners). Needs Python's playwright with
its Chromium, and Pillow. See box/assets/ICON-SOURCE.md.

    python3 box/scripts/render-autoplay-icon.py            # writes box/assets/autoplay-icon.png and the receiver's copy
"""
import argparse
import io
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "box/assets/autoplay-icon.svg"
OUTPUTS = (ROOT / "box/assets/autoplay-icon.png", ROOT / "receiver/server/src/main/resources/autoplay-icon.png")


def render(svg, size=180):
    with sync_playwright() as play:
        browser = play.chromium.launch()
        page = browser.new_page(viewport={"width": 1024, "height": 1024})
        page.set_content(f'<html><body style="margin:0">{svg}</body></html>')
        shot = page.screenshot(clip={"x": 0, "y": 0, "width": 1024, "height": 1024})
        browser.close()
    return Image.open(io.BytesIO(shot)).convert("RGB").resize((size, size), Image.LANCZOS)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("out", nargs="*", type=Path, default=list(OUTPUTS))
    args = parser.parse_args()
    image = render(SOURCE.read_text())
    for path in args.out:
        image.save(path, optimize=True)
        print(f"{path}: {image.size[0]} x {image.size[1]} {image.mode}")


if __name__ == "__main__":
    main()
