"""Render the Alexa+ add-on icons and carousel image into macro_desk/web/assets.

    python scripts/make_assets.py
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent.parent / "macro_desk" / "web" / "assets"
BG = (13, 17, 23)
PANEL = (21, 27, 35)
MUTED = (72, 86, 104)
ACCENT = (242, 179, 61)
TEXT = (230, 237, 243)
SUB = (139, 152, 168)
ICON_SIZES = (64, 72, 88, 126, 180, 241)
SCALE = 4  # draw large, downsample for clean edges


def font(weight: str, size: int) -> ImageFont.FreeTypeFont:
    for path in (f"/usr/share/fonts/opentype/inter/Inter-{weight}.otf",
                 "/System/Library/Fonts/Supplemental/Arial.ttf"):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default(size)


def draw_mark(d: ImageDraw.ImageDraw, x0: float, y0: float, w: float, h: float) -> None:
    """Four bars of ordinary size, one that breaks well above the dashed band."""
    heights = (0.34, 0.46, 0.38, 0.92)
    n = len(heights)
    gap = w * 0.08
    bw = (w - gap * (n - 1)) / n
    band = y0 + h * (1 - 0.55)
    dash = w / 22
    x = x0
    while x < x0 + w:  # the band goes behind the bars
        d.line((x, band, min(x + dash, x0 + w), band), fill=SUB, width=max(2, int(h * 0.018)))
        x += dash * 2
    for i, frac in enumerate(heights):
        x = x0 + i * (bw + gap)
        top = y0 + h * (1 - frac)
        d.rounded_rectangle((x, top, x + bw, y0 + h), radius=bw * 0.18,
                            fill=ACCENT if i == n - 1 else MUTED)


def icon(size: int) -> Image.Image:
    s = size * SCALE
    img = Image.new("RGB", (s, s), BG)
    d = ImageDraw.Draw(img)
    pad = s * 0.2
    draw_mark(d, pad, pad, s - 2 * pad, s - 2 * pad)
    return img.resize((size, size), Image.LANCZOS)


def carousel() -> Image.Image:
    w, h = 600 * SCALE, 900 * SCALE
    img = Image.new("RGB", (w, h), BG)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((60 * SCALE, 90 * SCALE, 540 * SCALE, 470 * SCALE), radius=24 * SCALE, fill=PANEL)
    draw_mark(d, 130 * SCALE, 150 * SCALE, 340 * SCALE, 260 * SCALE)
    d.text((60 * SCALE, 540 * SCALE), "Macro", font=font("SemiBold", 64 * SCALE), fill=TEXT)
    d.text((60 * SCALE, 610 * SCALE), "Desk", font=font("SemiBold", 64 * SCALE), fill=ACCENT)
    body = font("Regular", 26 * SCALE)
    for i, line in enumerate(("US inflation, jobs, growth and rates.", "The number, and whether it matters.")):
        d.text((60 * SCALE, (715 + i * 40) * SCALE), line, font=body, fill=SUB)
    return img.resize((600, 900), Image.LANCZOS)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for size in ICON_SIZES:
        icon(size).save(OUT / f"icon-{size}.png", optimize=True)
    carousel().save(OUT / "carousel-600x900.png", optimize=True)
    print("\n".join(sorted(p.name for p in OUT.iterdir())))


if __name__ == "__main__":
    main()
