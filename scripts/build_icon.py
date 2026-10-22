"""
Build the S1 Command Center app icons.

Concept: a modern radar scope on a vivid violet aurora tile — a glass bezel
around a recessed dark scope, a glowing sweep that fades behind its bright
leading edge, a pinging blip, and "CC" (Command Center) on the hub at its
centre. The C's are drawn as round-capped arcs, so no font is needed. Below
48 px it simplifies to a bright ring, a solid sweep and the blip, so it still
reads at 16 px in a taskbar, a Finder list or a window title bar.

Every size is drawn for its own size (supersampled, then reduced) instead of
being shrunk from one big picture, and the small sizes get heavier strokes.
Each platform gets the layout its system expects:

  macOS    the Big Sur grid: an 824 px rounded plate inside the 1024 px
           canvas with a soft shadow, so it sits right in the Dock.
  Windows  the tile fills the canvas, no shadow, crisp at 16-48 px.

Writes:
  s1cc.ico                  Windows: 16 20 24 32 40 48 64 96 128 256
  s1cc.icns                 macOS: 16-512 at @1x and @2x (1024 px)
  scripts/icon_preview.png  the 1024 px macOS icon
  scripts/icon_strip.png    both platforms at 16-256 on dark and light

Run from the repo root:  venv/bin/python scripts/build_icon.py
(add --no-cc for a plain hub with a centre dot instead of CC)
"""
from __future__ import annotations

import math
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

REPO = Path(__file__).resolve().parent.parent

# ── SentinelOne-inspired palette ─────────────────────────────────────────────
BG_STOPS = [(0.0, (168, 85, 247)),
            (0.5, (109, 40, 217)),
            (1.0, (49, 46, 129))]
AURORA_PINK = (244, 114, 182)
AURORA_BLUE = (96, 165, 250)
DISC_IN = (46, 16, 101)
DISC_OUT = (17, 12, 52)
SWEEP_TRAIL = (124, 58, 237)
SWEEP_LEAD = (240, 236, 255)
SWEEP_GLOW = (167, 139, 250)
EDGE = (255, 255, 255)
BLIP = (255, 255, 255)
BLIP_GLOW = (196, 181, 253)
RING = (255, 255, 255)
HUB_IN = (46, 26, 110)
HUB_OUT = (24, 14, 66)
HUB_RIM = (221, 214, 254)
SHADOW = (14, 6, 40)

WINDOWS_SIZES = (16, 20, 24, 32, 40, 48, 64, 96, 128, 256)
MAC_SIZES = (16, 32, 64, 128, 256, 512, 1024)
STRIP_SIZES = (16, 24, 32, 48, 64, 128, 256)
ICNS_SPEC = (
    (16, "icon_16x16.png"), (32, "icon_16x16@2x.png"),
    (32, "icon_32x32.png"), (64, "icon_32x32@2x.png"),
    (128, "icon_128x128.png"), (256, "icon_128x128@2x.png"),
    (256, "icon_256x256.png"), (512, "icon_256x256@2x.png"),
    (512, "icon_512x512.png"), (1024, "icon_512x512@2x.png"),
)


# ── helpers ──────────────────────────────────────────────────────────────────

def _lerp(a, b, t):
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


def _ramp(stops, t):
    for (t0, c0), (t1, c1) in zip(stops, stops[1:]):
        if t <= t1:
            return _lerp(c0, c1, (t - t0) / (t1 - t0))
    return stops[-1][1]


def _diagonal(w, h, stops):
    grid = 96
    small = Image.new("RGB", (grid, grid))
    px = small.load()
    for y in range(grid):
        for x in range(grid):
            px[x, y] = _ramp(stops, (x + y) / (2 * (grid - 1)))
    return small.resize((max(1, int(w)), max(1, int(h))), Image.BICUBIC)


def _vertical(w, h, top, bottom):
    grid = 96
    small = Image.new("RGB", (1, grid))
    px = small.load()
    for y in range(grid):
        px[0, y] = _lerp(top, bottom, y / (grid - 1))
    return small.resize((max(1, int(w)), max(1, int(h))), Image.BICUBIC)


def _squircle(box, n=5.0, steps=720):
    x0, y0, x1, y1 = box
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    rx, ry = (x1 - x0) / 2, (y1 - y0) / 2
    pts = []
    for i in range(steps):
        a = 2 * math.pi * i / steps
        c, s = math.cos(a), math.sin(a)
        pts.append((cx + rx * math.copysign(abs(c) ** (2 / n), c),
                    cy + ry * math.copysign(abs(s) ** (2 / n), s)))
    return pts


def _mask(size, points):
    m = Image.new("L", (size, size), 0)
    ImageDraw.Draw(m).polygon(points, fill=255)
    return m


def _disc(size, cx, cy, r):
    m = Image.new("L", (size, size), 0)
    ImageDraw.Draw(m).ellipse([cx - r, cy - r, cx + r, cy + r], fill=255)
    return m


def _ring(size, cx, cy, r, width):
    m = Image.new("L", (size, size), 0)
    ImageDraw.Draw(m).ellipse([cx - r, cy - r, cx + r, cy + r],
                              outline=255, width=max(1, int(width)))
    return m


_conic_cache = {}


def _conic(n, trail, lead, power):
    key = (n, trail, lead, power)
    if key not in _conic_cache:
        img = Image.new("L", (n, n), 0)
        px = img.load()
        c = (n - 1) / 2
        span = (lead - trail) % 360
        for y in range(n):
            for x in range(n):
                d = (math.degrees(math.atan2(y - c, x - c)) - trail) % 360
                if d <= span:
                    px[x, y] = int(255 * (d / span) ** power)
        _conic_cache[key] = img
    return _conic_cache[key]


def _radial(n, inner, outer, power=1.0):
    grid = 96
    small = Image.new("RGB", (grid, grid))
    px = small.load()
    c = (grid - 1) / 2
    for y in range(grid):
        for x in range(grid):
            t = min(1.0, math.hypot(x - c, y - c) / c)
            px[x, y] = _lerp(inner, outer, t ** power)
    return small.resize((max(1, int(n)), max(1, int(n))), Image.BICUBIC)


def _blob(size, cx, cy, r, blur):
    return _disc(size, cx, cy, r).filter(ImageFilter.GaussianBlur(blur))


def _arc_c(size, cx, cy, r, w, opening=52):
    m = Image.new("L", (size, size), 0)
    d = ImageDraw.Draw(m)
    d.arc([cx - r, cy - r, cx + r, cy + r], opening, 360 - opening,
          fill=255, width=max(1, int(w)))
    rm = r - w / 2
    for ang in (opening, 360 - opening):
        a = math.radians(ang)
        ex, ey = cx + rm * math.cos(a), cy + rm * math.sin(a)
        d.ellipse([ex - w / 2, ey - w / 2, ex + w / 2, ey + w / 2], fill=255)
    return m


def _tint(size, color, alpha_mask, strength):
    layer = Image.new("RGBA", (size, size), (*color, 0))
    layer.putalpha(alpha_mask.point(lambda v: int(v * strength)))
    return layer


# ── rendering ────────────────────────────────────────────────────────────────

def render(size: int, mac: bool, cc: bool = True) -> Image.Image:
    ss = 8 if size <= 64 else (4 if size <= 256 else 2)
    S = size * ss
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))

    inset = S * 100 / 1024 if mac else math.floor(size * 0.03) * ss
    box = (inset, inset, S - inset, S - inset)
    side = box[2] - box[0]
    outline = _squircle(box)
    plate = _mask(S, outline)
    cx = cy = S / 2
    tiny, small = size <= 20, size <= 32
    clear = Image.new("RGBA", (S, S), (0, 0, 0, 0))

    def put(mask, color, strength, clip=plate):
        nonlocal img
        if clip is not None:
            mask = ImageChops.multiply(mask, clip)
        img = Image.alpha_composite(img, _tint(S, color, mask, strength))

    if mac and size >= 32:
        drop = plate.filter(ImageFilter.GaussianBlur(side * 0.022))
        drop = ImageChops.offset(drop, 0, int(side * 0.018))
        put(drop, (0, 0, 0), 0.40, clip=None)

    bg = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    bg.paste(_diagonal(side, side, BG_STOPS).convert("RGBA"),
             (int(box[0]), int(box[1])))
    img.paste(bg, (0, 0), plate)
    if size >= 24:
        put(_blob(S, box[2] - side * 0.12, box[1] + side * 0.10,
                  side * 0.42, side * 0.16), AURORA_PINK, 0.55)
        put(_blob(S, box[0] + side * 0.10, box[3] - side * 0.08,
                  side * 0.40, side * 0.16), AURORA_BLUE, 0.45)

    rD = side * (0.40 if tiny else 0.38 if small else 0.355)
    rB = rD + side * (0.0 if tiny else 0.035 if small else 0.045)
    disc = _disc(S, cx, cy, rD)
    bezel = ImageChops.subtract(_disc(S, cx, cy, rB), disc)

    if size >= 32:
        shade = _disc(S, cx, cy, rB).filter(
            ImageFilter.GaussianBlur(side * 0.03))
        put(ImageChops.offset(shade, 0, int(side * 0.022)), SHADOW, 0.55)

    if not tiny:
        glass = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        glass.paste(_vertical(2 * rB, 2 * rB, (255, 255, 255),
                              (196, 181, 253)).convert("RGBA"),
                    (int(cx - rB), int(cy - rB)))
        glass.putalpha(bezel.point(lambda v: int(v * 0.42)))
        img = Image.alpha_composite(img, glass)
        if size >= 48:
            hl = _ring(S, cx, cy, rB, side * 0.006)
            fade = _vertical(S, S, (255, 255, 255), (0, 0, 0)).convert("L")
            put(ImageChops.multiply(hl, fade), (255, 255, 255), 0.85)

    face = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    face.paste(_radial(2 * rD, DISC_IN, DISC_OUT, 1.2).convert("RGBA"),
               (int(cx - rD), int(cy - rD)))
    img = Image.alpha_composite(img, Image.composite(face, clear, disc))
    if size >= 48:
        inner = ImageChops.subtract(
            disc, _disc(S, cx, cy + side * 0.012, rD - side * 0.018))
        put(inner.filter(ImageFilter.GaussianBlur(side * 0.01)), SHADOW,
            0.75, clip=disc)
        for frac in (0.66, 0.33):
            put(_ring(S, cx, cy, rD * frac, side * 0.005), RING, 0.16)
        for deg in (0, 90, 180, 270):
            line = Image.new("L", (S, S), 0)
            a = math.radians(deg)
            ImageDraw.Draw(line).line(
                [(cx, cy), (cx + rD * math.cos(a), cy + rD * math.sin(a))],
                fill=255, width=max(1, int(side * 0.004)))
            put(line, RING, 0.08)

    if small:
        put(_ring(S, cx, cy, rD, side * (0.09 if tiny else 0.06)),
            (255, 255, 255), 0.95)

    trail, lead = (-140.0, -35.0) if small else (-125.0, -35.0)
    d2 = int(2 * rD)
    mix = _conic(384, trail, lead, 1.0).resize((d2, d2), Image.BICUBIC)
    alpha = _conic(384, trail, lead, 0.45 if small else 1.5).resize(
        (d2, d2), Image.BICUBIC)
    colour = Image.composite(Image.new("RGB", (d2, d2), SWEEP_LEAD),
                             Image.new("RGB", (d2, d2), SWEEP_TRAIL), mix)
    sweep = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    sweep.paste(colour.convert("RGBA"), (int(cx - rD), int(cy - rD)))
    sweep_a = Image.new("L", (S, S), 0)
    sweep_a.paste(alpha, (int(cx - rD), int(cy - rD)))
    sweep_a = ImageChops.multiply(sweep_a, disc)
    if size >= 32:
        put(sweep_a.filter(ImageFilter.GaussianBlur(side * 0.025)),
            SWEEP_GLOW, 0.45, clip=disc)
    sweep.putalpha(sweep_a.point(lambda v: int(v * (1.0 if small else 0.92))))
    img = Image.alpha_composite(img, sweep)

    hub_r = side * 0.12 if (cc and not small) else 0.0
    ang = math.radians(lead)
    tip = (cx + rD * math.cos(ang), cy + rD * math.sin(ang))
    start = (cx + hub_r * math.cos(ang), cy + hub_r * math.sin(ang))
    edge = Image.new("L", (S, S), 0)
    ImageDraw.Draw(edge).line(
        [start, tip], fill=255,
        width=max(1, int(side * (0.03 if small else 0.012))))
    if size >= 32:
        put(edge.filter(ImageFilter.GaussianBlur(side * 0.012)), EDGE, 0.7,
            clip=disc)
    put(edge, EDGE, 1.0, clip=disc)

    def blip(deg, frac, core, strength, pings=()):
        a = math.radians(deg)
        bx = cx + rD * frac * math.cos(a)
        by = cy + rD * frac * math.sin(a)
        put(_blob(S, bx, by, core * 2.4, core * 1.4), BLIP_GLOW,
            0.9 * strength, clip=disc)
        for rr, al in pings:
            put(_ring(S, bx, by, rr, side * 0.006), BLIP, al * strength,
                clip=disc)
        put(_disc(S, bx, by, core), BLIP, strength, clip=disc)

    if small:
        blip(-70, 0.60, side * (0.085 if tiny else 0.07), 1.0)
    else:
        blip(-62, 0.64, side * 0.026, 1.0,
             ((side * 0.055, 0.55), (side * 0.085, 0.25)))
        blip(150, 0.52, side * 0.016, 0.55)

    if size >= 48:
        dome = Image.new("L", (S, S), 0)
        ImageDraw.Draw(dome).ellipse(
            [cx - rD * 0.85, cy - rD * 0.98, cx + rD * 0.55, cy - rD * 0.05],
            fill=255)
        put(dome.filter(ImageFilter.GaussianBlur(rD * 0.18)),
            (255, 255, 255), 0.10, clip=disc)

    if cc and not small:
        hub = _disc(S, cx, cy, hub_r)
        put(ImageChops.offset(hub.filter(ImageFilter.GaussianBlur(
            side * 0.02)), 0, int(side * 0.012)), SHADOW, 0.8, clip=disc)
        hub_face = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        hub_face.paste(_radial(2 * hub_r, HUB_IN, HUB_OUT, 1.0)
                       .convert("RGBA"), (int(cx - hub_r), int(cy - hub_r)))
        img = Image.alpha_composite(img, Image.composite(hub_face, clear, hub))
        fade = _vertical(S, S, (255, 255, 255), (90, 90, 90)).convert("L")
        put(ImageChops.multiply(_ring(S, cx, cy, hub_r, side * 0.006), fade),
            HUB_RIM, 0.9)
        r, w, gap = side * 0.046, side * 0.021, side * 0.008
        letters = ImageChops.lighter(
            _arc_c(S, cx - r - gap / 2, cy, r, w),
            _arc_c(S, cx + r + gap / 2, cy, r, w))
        put(letters, (255, 255, 255), 1.0, clip=disc)
    elif not small:
        put(_blob(S, cx, cy, side * 0.03, side * 0.02), BLIP_GLOW, 0.8,
            clip=disc)
        put(_disc(S, cx, cy, side * 0.014), BLIP, 1.0, clip=disc)

    if size >= 64:
        rim = Image.new("L", (S, S), 0)
        ImageDraw.Draw(rim).line(outline + [outline[0]], fill=255,
                                 width=max(2, int(ss * 1.5)))
        fade = _vertical(S, S, (255, 255, 255), (20, 20, 20)).convert("L")
        put(ImageChops.multiply(rim, fade), (255, 255, 255), 0.55)
        sheen = Image.new("L", (S, S), 0)
        ImageDraw.Draw(sheen).ellipse(
            [box[0] - side * 0.2, box[1] - side * 0.62,
             box[2] + side * 0.2, box[1] + side * 0.32], fill=255)
        put(sheen.filter(ImageFilter.GaussianBlur(side * 0.08)),
            (255, 255, 255), 0.10)

    return img.convert("RGBa").reduce(ss).convert("RGBA")


# ── platform packagers ───────────────────────────────────────────────────────

def write_ico(icons, out: Path):
    sizes = sorted(icons)
    biggest = sizes[-1]
    icons[biggest].save(out, format="ICO", sizes=[(s, s) for s in sizes],
                        append_images=[icons[s] for s in sizes[:-1]])
    print(f"  wrote {out}  ({len(sizes)} sizes)")


def write_icns(icons, out: Path):
    if not shutil.which("iconutil"):
        print("  iconutil not found (macOS only) - skipping .icns")
        return
    with tempfile.TemporaryDirectory() as td:
        iconset = Path(td) / "s1cc.iconset"
        iconset.mkdir()
        for px, name in ICNS_SPEC:
            icons[px].save(iconset / name, format="PNG")
        subprocess.check_call(
            ["iconutil", "-c", "icns", "-o", str(out), str(iconset)])
    print(f"  wrote {out}  ({len(ICNS_SPEC)} entries)")


def write_strip(rows, out: Path):
    pad = 20
    width = sum(STRIP_SIZES) + pad * (len(STRIP_SIZES) + 1)
    row_h = max(STRIP_SIZES) + pad * 2
    strip = Image.new("RGBA", (width, row_h * len(rows)), (0, 0, 0, 255))
    for r, (icons, bg) in enumerate(rows):
        y0 = r * row_h
        strip.paste(Image.new("RGBA", (width, row_h), (*bg, 255)), (0, y0))
        x = pad
        for s in STRIP_SIZES:
            strip.alpha_composite(
                icons[s], (x, y0 + pad + (max(STRIP_SIZES) - s) // 2))
            x += s + pad
    strip.save(out, format="PNG")
    print(f"  wrote {out}")


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    cc = "--no-cc" not in sys.argv
    print("Rendering every size…")
    win = {s: render(s, mac=False, cc=cc) for s in WINDOWS_SIZES}
    mac = {s: render(s, mac=True, cc=cc) for s in MAC_SIZES}
    preview = REPO / "scripts" / "icon_preview.png"
    mac[1024].save(preview, format="PNG")
    print(f"  preview → {preview}")
    print("Packaging icons…")
    write_ico(win, REPO / "s1cc.ico")
    write_icns(mac, REPO / "s1cc.icns")
    mac_strip = {s: render(s, mac=True, cc=cc) for s in STRIP_SIZES}
    dark, light = (31, 32, 41), (244, 245, 247)
    write_strip([(win, dark), (win, light), (mac_strip, dark),
                 (mac_strip, light)], REPO / "scripts" / "icon_strip.png")
    print("Done.")


if __name__ == "__main__":
    main()
