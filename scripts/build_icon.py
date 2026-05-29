"""
Build S1 Command Center app icons.

Concept: a command-center radar scope in SentinelOne brand purple on a deep
near-black background. Concentric range rings, crosshairs, a sweeping radar
arc, and three target blips — clearly reads as an ops/console tool with no
monogram.

Produces:
  s1cc.ico              — Windows multi-size (16/32/48/64/128/256)
  s1cc.icns             — macOS bundle (16…1024 incl. @2x)
  scripts/icon_preview.png — 1024×1024 preview
  scripts/icon_strip.png   — 16/32/64/128/256 preview strip

Run from repo root:  python3 scripts/build_icon.py
"""
from __future__ import annotations

import math
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

REPO = Path(__file__).resolve().parent.parent
CANVAS = 1024

# ── SentinelOne-inspired palette ─────────────────────────────────────────────
BG_TOP        = (16,  10,  34)    # #100A22  near-black with violet tint
BG_BOT        = (4,   2,   12)    # #04020C  deep black
PURPLE        = (124, 58,  237)   # #7C3AED  S1 brand purple
PURPLE_BRIGHT = (167, 100, 255)   # lighter / glow
PURPLE_DEEP   = (66,  26,  138)   # rim / shadow
WHITE         = (255, 255, 255)
LAVENDER      = (220, 200, 255)
BLIP_HOT      = (240, 230, 255)   # near-white blip core
BLIP_GLOW     = (180, 130, 255)   # purple glow around blips


# ── helpers ──────────────────────────────────────────────────────────────────

def squircle_mask(size: int, radius_ratio: float = 0.225) -> Image.Image:
    m = Image.new("L", (size, size), 0)
    ImageDraw.Draw(m).rounded_rectangle(
        [0, 0, size - 1, size - 1],
        radius=int(size * radius_ratio),
        fill=255,
    )
    return m


def vertical_gradient(size: int, top, bottom) -> Image.Image:
    img = Image.new("RGB", (1, size))
    px = img.load()
    for y in range(size):
        t = y / max(1, size - 1)
        px[0, y] = (
            int(top[0] + (bottom[0] - top[0]) * t),
            int(top[1] + (bottom[1] - top[1]) * t),
            int(top[2] + (bottom[2] - top[2]) * t),
        )
    return img.resize((size, size))


def radial_glow(size, cx_r, cy_r, radius_r, color, peak_alpha):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    cx, cy = int(size * cx_r), int(size * cy_r)
    rmax = int(size * radius_r)
    steps = 60
    for i in range(steps, 0, -1):
        r = int(rmax * i / steps)
        a = int(peak_alpha * (1 - i / steps) ** 1.6)
        if a <= 0:
            continue
        d.ellipse([cx - r, cy - r, cx + r, cy + r],
                  fill=(color[0], color[1], color[2], a))
    return img.filter(ImageFilter.GaussianBlur(size * 0.025))


# ── radar scope ──────────────────────────────────────────────────────────────

def draw_radar(size: int) -> Image.Image:
    """A command-center radar scope, sized `size`×`size`."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    cx = cy = size / 2
    R = size * 0.46   # outer scope radius

    # 1) scope disc — slightly lighter than background, with subtle inner gradient
    disc = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    dd = ImageDraw.Draw(disc)
    # outer dark rim
    rim_w = max(3, int(size * 0.022))
    dd.ellipse([cx - R, cy - R, cx + R, cy + R],
               fill=(22, 14, 44, 255))
    # inner radial brightening at center
    inner_glow = radial_glow(size, 0.5, 0.5, 0.42,
                             PURPLE, peak_alpha=70)
    # mask the glow to the scope disc
    disc_mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(disc_mask).ellipse(
        [cx - R + rim_w, cy - R + rim_w, cx + R - rim_w, cy + R - rim_w],
        fill=255,
    )
    disc.paste(inner_glow, (0, 0), disc_mask)
    img = Image.alpha_composite(img, disc)

    # 2) concentric range rings (3 of them)
    d = ImageDraw.Draw(img)
    ring_w = max(2, int(size * 0.006))
    for frac, alpha in [(1.00, 230), (0.70, 170), (0.42, 140), (0.16, 200)]:
        rr = R * frac
        d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr],
                  outline=(*PURPLE, alpha),
                  width=ring_w if frac == 1.00 else max(2, int(size * 0.004)))

    # 3) crosshair — horizontal + vertical, with a small gap at center
    cross_w = max(2, int(size * 0.005))
    gap = R * 0.06
    # horizontal
    d.line([(cx - R, cy), (cx - gap, cy)],
           fill=(*PURPLE, 200), width=cross_w)
    d.line([(cx + gap, cy), (cx + R, cy)],
           fill=(*PURPLE, 200), width=cross_w)
    # vertical
    d.line([(cx, cy - R), (cx, cy - gap)],
           fill=(*PURPLE, 200), width=cross_w)
    d.line([(cx, cy + gap), (cx, cy + R)],
           fill=(*PURPLE, 200), width=cross_w)

    # 4) tick marks at the 4 cardinal positions, just outside the rings
    tick_len = R * 0.06
    tick_w = max(2, int(size * 0.006))
    for ang_deg in (0, 90, 180, 270):
        a = math.radians(ang_deg)
        x0 = cx + (R + tick_len * 0.4) * math.cos(a)
        y0 = cy + (R + tick_len * 0.4) * math.sin(a)
        x1 = cx + (R + tick_len * 1.4) * math.cos(a)
        y1 = cy + (R + tick_len * 1.4) * math.sin(a)
        d.line([(x0, y0), (x1, y1)], fill=(*LAVENDER, 160), width=tick_w)

    # 5) sweep arc — gradient sector from 12 o'clock clockwise to ~2 o'clock,
    #    with brightness peaking at the leading edge.
    sweep_layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    sl = ImageDraw.Draw(sweep_layer)
    sweep_span = 70          # degrees
    sweep_lead = -30         # leading edge angle (PIL convention: 0°=3o'clock, CW)
    sweep_trail = sweep_lead - sweep_span   # = -100° (~10 o'clock-ish; we want
                                            # it going from top→right, so flip)
    # Actually we want sweep going clockwise from 12 (-90°) → 2 (-20°).
    sweep_trail = -90
    sweep_lead = -20
    bbox = [cx - R + rim_w, cy - R + rim_w, cx + R - rim_w, cy + R - rim_w]
    slices = 36
    for i in range(slices):
        a0 = sweep_trail + (sweep_lead - sweep_trail) * (i / slices)
        a1 = sweep_trail + (sweep_lead - sweep_trail) * ((i + 1) / slices)
        # brightness ramps up toward the leading edge
        t = (i + 1) / slices
        alpha = int(180 * t ** 2.2)
        if alpha <= 0:
            continue
        # color brightens too
        col = (
            int(PURPLE[0] + (PURPLE_BRIGHT[0] - PURPLE[0]) * t),
            int(PURPLE[1] + (PURPLE_BRIGHT[1] - PURPLE[1]) * t),
            int(PURPLE[2] + (PURPLE_BRIGHT[2] - PURPLE[2]) * t),
            alpha,
        )
        sl.pieslice(bbox, a0, a1, fill=col)
    # constrain sweep to the scope disc
    sweep_mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(sweep_mask).ellipse(bbox, fill=255)
    sweep_masked = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    sweep_masked.paste(sweep_layer, (0, 0), sweep_mask)
    # add a bright leading-edge line
    lead_x = cx + R * math.cos(math.radians(sweep_lead))
    lead_y = cy + R * math.sin(math.radians(sweep_lead))
    ld = ImageDraw.Draw(sweep_masked)
    ld.line([(cx, cy), (lead_x, lead_y)],
            fill=(*PURPLE_BRIGHT, 255), width=max(3, int(size * 0.012)))
    img = Image.alpha_composite(img, sweep_masked)

    # 6) target blips — soft glow + bright core
    def blip(px_r, py_r, core_r_ratio=0.018):
        ax, ay = cx + R * px_r, cy + R * py_r
        glow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        gd = ImageDraw.Draw(glow)
        for k in range(8, 0, -1):
            rg = size * 0.045 * (k / 8)
            ag = int(110 * (1 - k / 8) ** 1.4)
            gd.ellipse([ax - rg, ay - rg, ax + rg, ay + rg],
                       fill=(*BLIP_GLOW, ag))
        glow = glow.filter(ImageFilter.GaussianBlur(size * 0.012))
        core = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        cd = ImageDraw.Draw(core)
        rc = size * core_r_ratio
        cd.ellipse([ax - rc, ay - rc, ax + rc, ay + rc],
                   fill=(*BLIP_HOT, 255))
        return Image.alpha_composite(glow, core)

    blip_mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(blip_mask).ellipse(bbox, fill=255)
    blips = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    blips = Image.alpha_composite(blips, blip(0.45, -0.32))   # upper right (recently swept)
    blips = Image.alpha_composite(blips, blip(-0.55, 0.18))   # left mid
    blips = Image.alpha_composite(blips, blip(0.18, 0.55, core_r_ratio=0.014))  # lower
    blips_masked = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    blips_masked.paste(blips, (0, 0), blip_mask)
    img = Image.alpha_composite(img, blips_masked)

    # 7) outer rim highlight (top-left arc) for depth
    rim = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    rd = ImageDraw.Draw(rim)
    rd.arc([cx - R, cy - R, cx + R, cy + R],
           start=190, end=320,
           fill=(*PURPLE_BRIGHT, 200),
           width=max(2, int(size * 0.006)))
    img = Image.alpha_composite(img, rim)

    return img


# ── master ───────────────────────────────────────────────────────────────────

def draw_master(size: int = CANVAS) -> Image.Image:
    # 1) squircle background with vertical gradient
    bg = vertical_gradient(size, BG_TOP, BG_BOT).convert("RGBA")
    mask = squircle_mask(size)
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.paste(bg, (0, 0), mask)

    # 2) ambient purple glow (top-left) for brand mood
    glow = radial_glow(size, 0.30, 0.25, 0.65, PURPLE, peak_alpha=80)
    glow_m = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    glow_m.paste(glow, (0, 0), mask)
    canvas = Image.alpha_composite(canvas, glow_m)

    # 3) subtle vignette (darken corners) — masked to squircle
    vignette = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    vd = ImageDraw.Draw(vignette)
    steps = 80
    for i in range(steps):
        inset = int(size * 0.50 * (i / steps))
        a = int(60 * (i / steps) ** 2)
        vd.rectangle([inset, inset, size - inset, size - inset],
                     outline=(0, 0, 0, a), width=2)
    vignette = vignette.filter(ImageFilter.GaussianBlur(size * 0.05))
    vm = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    vm.paste(vignette, (0, 0), mask)
    canvas = Image.alpha_composite(canvas, vm)

    # 4) the radar — centered, sized to fill most of the canvas
    radar = draw_radar(size)
    canvas = Image.alpha_composite(canvas, radar)

    # 5) hairline border inside the squircle for crispness
    border = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(border).rounded_rectangle(
        [2, 2, size - 3, size - 3],
        radius=int(size * 0.225),
        outline=(*PURPLE, 50),
        width=max(1, int(size * 0.004)),
    )
    canvas = Image.alpha_composite(canvas, border)

    return canvas


# ── platform packagers ───────────────────────────────────────────────────────

def write_ico(master: Image.Image, out: Path):
    sizes = [(s, s) for s in (16, 32, 48, 64, 128, 256)]
    master.save(out, format="ICO", sizes=sizes)
    print(f"  wrote {out}  ({len(sizes)} sizes)")


def write_icns(master: Image.Image, out: Path):
    if not shutil.which("iconutil"):
        print("  ⚠ iconutil not found — skipping .icns")
        return
    spec = [
        (16,   "icon_16x16.png"),
        (32,   "icon_16x16@2x.png"),
        (32,   "icon_32x32.png"),
        (64,   "icon_32x32@2x.png"),
        (128,  "icon_128x128.png"),
        (256,  "icon_128x128@2x.png"),
        (256,  "icon_256x256.png"),
        (512,  "icon_256x256@2x.png"),
        (512,  "icon_512x512.png"),
        (1024, "icon_512x512@2x.png"),
    ]
    with tempfile.TemporaryDirectory() as td:
        iconset = Path(td) / "s1cc.iconset"
        iconset.mkdir()
        for px, name in spec:
            master.resize((px, px), Image.LANCZOS).save(
                iconset / name, format="PNG")
        subprocess.check_call(
            ["iconutil", "-c", "icns", "-o", str(out), str(iconset)]
        )
    print(f"  wrote {out}  ({len(spec)} entries)")


def write_strip(master: Image.Image, out: Path):
    """Side-by-side small-size preview strip."""
    sizes = [16, 32, 64, 128, 256]
    pad = 24
    bg_color = (40, 40, 50, 255)
    total_w = sum(sizes) + pad * (len(sizes) + 1)
    total_h = max(sizes) + pad * 2
    strip = Image.new("RGBA", (total_w, total_h), bg_color)
    x = pad
    for s in sizes:
        im = master.resize((s, s), Image.LANCZOS)
        y = pad + (max(sizes) - s) // 2
        strip.alpha_composite(im, (x, y))
        x += s + pad
    strip.save(out, format="PNG")
    print(f"  wrote {out}")


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    print(f"Rendering master @ {CANVAS}×{CANVAS}…")
    master = draw_master(CANVAS)

    preview = REPO / "scripts" / "icon_preview.png"
    master.save(preview, format="PNG")
    print(f"  preview → {preview}")

    print("Packaging icons…")
    write_ico(master, REPO / "s1cc.ico")
    write_icns(master, REPO / "s1cc.icns")
    write_strip(master, REPO / "scripts" / "icon_strip.png")
    print("Done.")


if __name__ == "__main__":
    main()
