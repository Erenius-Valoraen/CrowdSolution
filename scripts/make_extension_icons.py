"""Draw the Trustify receipt logo as PNG toolbar icons for the browser extension. Standard library only.

  python scripts/make_extension_icons.py
"""
import math
import struct
import zlib
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "extension" / "icons"
SAMPLES = 4  # supersampling per axis, for smooth edges

# Receipt outline on a 32-unit grid (matches the SVG logo), rotated -8 degrees around the center.
RECEIPT = [(8.5, 3.5), (23.5, 3.5), (25.5, 5.5), (25.5, 27), (22.6, 29.4), (19.7, 27), (16.8, 29.4), (13.9, 27),
           (11.0, 29.4), (8.1, 27), (6.5, 27), (6.5, 5.5)]
CHECK = [(11, 15.5), (14.6, 19.1), (21.5, 11.5)]
TILE = (244, 243, 240)
INK = (17, 17, 17)
PAPER = (251, 251, 250)


def inside_polygon(x, y, points):
    hit = False
    for (x1, y1), (x2, y2) in zip(points, points[1:] + points[:1]):
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            hit = not hit
    return hit


def near_polyline(x, y, points, radius):
    for (x1, y1), (x2, y2) in zip(points, points[1:]):
        dx, dy = x2 - x1, y2 - y1
        t = max(0.0, min(1.0, ((x - x1) * dx + (y - y1) * dy) / (dx * dx + dy * dy)))
        if math.hypot(x - (x1 + t * dx), y - (y1 + t * dy)) <= radius:
            return True
    return False


def in_rounded_tile(x, y, size=32, radius=7):
    cx, cy = min(max(x, radius), size - radius), min(max(y, radius), size - radius)
    return math.hypot(x - cx, y - cy) <= radius


def color_at(u, v):
    """Color and alpha at a point on the 32-unit grid."""
    if not in_rounded_tile(u, v):
        return (0, 0, 0), 0
    angle = math.radians(8)  # undo the -8 degree tilt
    x = 16 + (u - 16) * math.cos(angle) - (v - 16) * math.sin(angle)
    y = 16 + (u - 16) * math.sin(angle) + (v - 16) * math.cos(angle)
    if near_polyline(x, y, CHECK, 1.4) and inside_polygon(x, y, RECEIPT):
        return PAPER, 255
    if inside_polygon(x, y, RECEIPT):
        return INK, 255
    return TILE, 255


def render(size):
    rows = []
    for py in range(size):
        row = bytearray([0])  # PNG filter: none
        for px in range(size):
            r = g = b = a = 0
            for sy in range(SAMPLES):
                for sx in range(SAMPLES):
                    u = (px + (sx + 0.5) / SAMPLES) * 32 / size
                    v = (py + (sy + 0.5) / SAMPLES) * 32 / size
                    (cr, cg, cb), ca = color_at(u, v)
                    r, g, b, a = r + cr * ca, g + cg * ca, b + cb * ca, a + ca
            n = SAMPLES * SAMPLES
            row += bytes([round(r / a) if a else 0, round(g / a) if a else 0, round(b / a) if a else 0, round(a / n)])
        rows.append(bytes(row))
    return b"".join(rows)


def png(size, pixels):
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    header = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(pixels, 9)) + chunk(b"IEND", b"")


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for size in (16, 32, 48, 128):
        (OUT / f"icon{size}.png").write_bytes(png(size, render(size)))
        print(f"wrote extension/icons/icon{size}.png")
