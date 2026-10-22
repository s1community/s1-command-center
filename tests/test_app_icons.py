import os
import struct

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ICO = os.path.join(ROOT, "s1cc.ico")
ICNS = os.path.join(ROOT, "s1cc.icns")
WINDOWS_SIZES = (16, 20, 24, 32, 40, 48, 64, 96, 128, 256)


def _ico_frame(size):
    with Image.open(ICO) as im:
        im.size = (size, size)
        im.load()
        return im.convert("RGBA")


def _icns_frame(size, scale):
    with Image.open(ICNS) as im:
        im.size = (size * scale, size * scale)
        im.load()
        return im.convert("RGBA")


def _pixels(im):
    return [im.getpixel((x, y)) for y in range(im.height)
            for x in range(im.width)]


def test_the_windows_icon_has_every_size_windows_asks_for():
    with Image.open(ICO) as im:
        sizes = set(im.info["sizes"])
    assert {(s, s) for s in WINDOWS_SIZES} <= sizes


def test_the_small_windows_icon_is_a_bright_mark_not_a_dark_blob():
    for size in (16, 24, 32):
        px = _pixels(_ico_frame(size))
        opaque = [p for p in px if p[3] > 200]
        bright = [p for p in opaque if min(p[:3]) > 200]
        assert len(opaque) >= 0.85 * len(px), size
        assert len(bright) >= 0.08 * len(px), size


def test_the_macos_icon_has_every_size_up_to_1024():
    with open(ICNS, "rb") as f:
        data = f.read()
    assert data[:4] == b"icns"
    kinds, i = set(), 8
    while i < len(data):
        kinds.add(data[i:i + 4].decode("latin1"))
        i += struct.unpack(">I", data[i + 4:i + 8])[0]
    assert {"ic04", "ic05", "ic07", "ic08", "ic09", "ic10", "ic11",
            "ic12", "ic13", "ic14"} <= kinds


def test_the_macos_icon_sits_on_the_dock_grid():
    big = _icns_frame(512, 2)
    assert big.size == (1024, 1024)
    assert big.getpixel((40, 512))[3] < 20
    assert big.getpixel((512, 40))[3] < 20
    assert big.getpixel((512, 512))[3] == 255
    assert big.getpixel((112, 512))[3] == 255
