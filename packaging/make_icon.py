"""Draws the app icon: the notebook glyph from the panel and the extension's toolbar icon.

    uv run python packaging/make_icon.py build/inspectors-notebook.ico

Drawn at build time, like the toolbar icon, so the repository holds no image files for it.
"""

import sys
from pathlib import Path

from PIL import Image, ImageDraw

SIZES = [16, 24, 32, 48, 64, 128, 256]
BACKGROUND = "#0F1215"  # the panel's dark background
GLYPH = "#F2B544"  # amber, the connected colour


def draw(size: int) -> Image.Image:
    scale = 8  # draw large and shrink, for smooth edges
    s = size * scale / 24  # the glyph is designed on a 24 px grid
    image = Image.new("RGBA", (size * scale, size * scale), (0, 0, 0, 0))
    d = ImageDraw.Draw(image)
    d.rounded_rectangle([0, 0, size * scale - 1, size * scale - 1], radius=5 * s, fill=BACKGROUND)
    width = round(2.2 * s)
    d.rounded_rectangle([5 * s, 3 * s, 19 * s, 21 * s], radius=2 * s, outline=GLYPH, width=width)
    for x1, y in ((15, 8), (15, 12), (12, 16)):
        d.line([9 * s, y * s, x1 * s, y * s], fill=GLYPH, width=width)
        for x in (9, x1):  # round caps
            r = width / 2
            d.ellipse([x * s - r, y * s - r, x * s + r, y * s + r], fill=GLYPH)
    return image.resize((size, size), Image.Resampling.LANCZOS)


def main() -> None:
    out = Path(sys.argv[1])
    out.parent.mkdir(parents=True, exist_ok=True)
    images = [draw(n) for n in SIZES]
    images[-1].save(out, format="ICO", sizes=[(n, n) for n in SIZES], append_images=images[:-1])
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
