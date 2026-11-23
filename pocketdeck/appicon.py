"""Draws the home-screen icon (3x3 glowing keys) as a PNG – iOS needs a PNG apple-touch-icon."""
from .icons import encode_png

KEYS = [(255, 122, 69), (255, 196, 61), (72, 214, 140),
        (77, 163, 255), (156, 124, 255), (255, 92, 138),
        (60, 210, 220), (238, 238, 245), (255, 150, 60)]


def _rounded_box_dist(px, py, cx, cy, half, r):
    qx, qy = abs(px - cx) - half + r, abs(py - cy) - half + r
    ox, oy = max(qx, 0.0), max(qy, 0.0)
    return (ox * ox + oy * oy) ** 0.5 + min(max(qx, qy), 0.0) - r


def make_app_icon(size):
    pad, gap = size * 0.17, size * 0.045
    key = (size - 2 * pad - 2 * gap) / 3
    half, rad = key / 2, key * 0.26
    centers = [(pad + half + c * (key + gap), pad + half + r * (key + gap), KEYS[r * 3 + c])
               for r in range(3) for c in range(3)]
    px = bytearray(size * size * 4)
    for y in range(size):
        for x in range(size):
            fx, fy = x + 0.5, y + 0.5
            t = (fx + fy) / (2 * size)
            col = [16 + 10 * t, 18 + 8 * t, 26 + 10 * t]
            for cx, cy, kc in centers:
                d = _rounded_box_dist(fx, fy, cx, cy, half, rad)
                if d < size * 0.06:
                    glow = max(0.0, 1 - max(d, 0) / (size * 0.06)) * 0.22
                    a = min(1.0, max(0.0, 0.5 - d))
                    shade = 0.82 + 0.18 * (1 - (fy - (cy - half)) / key) if a else 1
                    for i in range(3):
                        target = kc[i] * shade
                        col[i] = col[i] * (1 - glow) + kc[i] * glow
                        col[i] = col[i] * (1 - a) + target * a
                    break
            o = (y * size + x) * 4
            px[o:o + 4] = bytes((int(min(255, col[0])), int(min(255, col[1])),
                                 int(min(255, col[2])), 255))
    return encode_png(size, size, px)
