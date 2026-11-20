"""
Redraws the KeyParse logo sharply at Store sizes (logo.png is only 400x400; enlarging it would blur).
Shapes, colours and positions are measured from logo.png (in its 400x400 coordinates).

  python store\\make_store_art.py      -> store\\listing\\BoxArt_2160x2160.png, PosterArt_1440x2160.png
                                         (+ store\\build\\compare_400.png: redraw next to the original, for checking)
"""
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

STORE = Path(__file__).resolve().parent
ROOT = STORE.parent
OUT = STORE / "listing"
FONT = r"C:\Windows\Fonts\verdanab.ttf"
SUB_FONT = r"C:\Windows\Fonts\verdana.ttf"

BG_EDGE, BG_CENTER = (6, 7, 10), (40, 30, 66)
GOLD, GOLD_DIM, RING, FILL = (229, 204, 128), (123, 107, 64), (42, 30, 70), (22, 24, 36)
SUB = (170, 170, 180)
BARS = [(159, 159, 159), (30, 255, 0), (0, 112, 255), (163, 53, 238), (255, 128, 0)]
CX, CY = 199.5, 150.0                      # hexagon centre
R_GOLD_OUT, R_GOLD_IN, R_THIN_OUT, R_THIN_IN = 111.4, 101.6, 92.4, 88.3


def hexagon(cx, cy, r):
    return [(cx + r * math.cos(math.radians(a)), cy + r * math.sin(math.radians(a))) for a in range(-90, 270, 60)]


def smoothstep(e0, e1, x):
    t = min(1.0, max(0.0, (x - e0) / (e1 - e0)))
    return t * t * (3 - 2 * t)


def background(w, h, cx, cy, s):
    """Radial glow centred on the hexagon, fading to near black (fit to logo.png: full until ~120, dark by ~215)."""
    small = Image.new("RGB", (w // 8 + 1, h // 8 + 1))
    px = small.load()
    for y in range(small.size[1]):
        for x in range(small.size[0]):
            d = math.hypot(x * 8 - cx, y * 8 - cy) / s
            k = 1 - smoothstep(120, 215, d)
            px[x, y] = tuple(round(e + (c - e) * k) for e, c in zip(BG_EDGE, BG_CENTER))
    return small.resize((w, h), Image.BICUBIC)


def draw_logo(img, ox, oy, s, text=True):
    """Draw the logo (400x400 design units) onto img with its top-left at (ox, oy), scale s pixels per unit."""
    ss = 2  # draw shapes at 2x and shrink, for smooth edges
    layer = Image.new("RGBA", (img.size[0] * ss, img.size[1] * ss), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    P = lambda x, y: ((ox + x * s) * ss, (oy + y * s) * ss)
    for r, col in ((R_GOLD_OUT, GOLD), (R_GOLD_IN, RING), (R_THIN_OUT, GOLD_DIM), (R_THIN_IN, FILL)):
        d.polygon([P(x, y) for x, y in hexagon(CX, CY, r)], fill=col)
    for i, col in enumerate(BARS):                      # 18 wide, 8 apart, bottoms at y=199, each 18 taller
        x0, top = 139 + 26 * i, 174 - 18 * i
        (a, b), (c, e) = P(x0, top), P(x0 + 18, 199)
        d.rounded_rectangle((a, b, c, e), radius=3 * s * ss, fill=col)
    layer = layer.resize(img.size, Image.LANCZOS)
    img.alpha_composite(layer)
    if not text:
        return
    for label, font_path, size, cy, col, shadow in (("KeyParse", FONT, 58, 313, GOLD, True),
                                                    ("same-key M+ parses", SUB_FONT, 18, 365, SUB, False)):
        font = ImageFont.truetype(font_path, round(size * s))
        t = Image.new("RGBA", img.size, (0, 0, 0, 0))
        td = ImageDraw.Draw(t)
        x, y = ox + 200 * s, oy + cy * s
        if shadow:
            sh = Image.new("RGBA", img.size, (0, 0, 0, 0))
            ImageDraw.Draw(sh).text((x + 3 * s, y + 3 * s), label, font=font, fill=(0, 0, 0, 200), anchor="mm")
            img.alpha_composite(sh.filter(ImageFilter.GaussianBlur(1.5 * s)))
        td.text((x, y), label, font=font, fill=col, anchor="mm")
        img.alpha_composite(t)


def render(w, h, s, oy):
    ox = (w - 400 * s) / 2
    img = background(w, h, ox + CX * s, oy + CY * s, s).convert("RGBA")
    draw_logo(img, ox, oy, s)
    return img.convert("RGB")


def render_icon(size, fill=0.94):
    """Just the hexagon (no text), centred, transparent outside: Store display images (300/150/71)."""
    s = size * fill / (2 * R_GOLD_OUT)          # hexagon is 2R tall
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw_logo(img, size / 2 - CX * s, size / 2 - CY * s, s, text=False)
    return img


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for size in (300, 150, 71):
        render_icon(size).save(OUT / f"Tile_{size}x{size}.png")
    render(2160, 2160, 5.4, 0).save(OUT / "BoxArt_2160x2160.png")
    render(1440, 2160, 4.2, (2160 - 400 * 4.2) / 2).save(OUT / "PosterArt_1440x2160.png")
    mine = render(400, 400, 1, 0)
    cmp = Image.new("RGB", (800, 400))
    cmp.paste(Image.open(ROOT / "logo.png").convert("RGB"), (0, 0))
    cmp.paste(mine, (400, 0))
    (STORE / "build").mkdir(exist_ok=True)
    cmp.save(STORE / "build" / "compare_400.png")
    print("wrote", ", ".join(p.name for p in sorted(OUT.glob("*.png"))))


if __name__ == "__main__":
    main()
