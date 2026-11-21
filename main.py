#!/usr/bin/env python3
"""ONDARA — poster for a place that doesn't exist.
Pure Python 3 stdlib only. Deterministic, fixed seed, no network.
Renders a clean, painterly, 3D-layered travel poster (1024x1024)
mirroring the MARELUNE composition: dusk sky, giant stone arch
framing a RISING waterfall, hillside houses, glittering sea,
terrace couple. Writes /output/entry.png.
"""
import array
import hashlib
import math
import os
import random
import struct
import zlib

SEED = 20261121
W = H = 1024
SS = 2
W2 = H2 = 2048
rng = random.Random(SEED)

# ---------------------------------------------------------------- buffer
# Pixels packed little-endian RGBA: value = 0xFF000000 | (b<<16)|(g<<8)|r
# so the array's raw bytes ARE the PNG RGBA scanlines.
buf = array.array("I", [0]) * (W2 * H2)


def P(r, g, b):
    return 0xFF000000 | ((int(b) & 255) << 16) | ((int(g) & 255) << 8) | (int(r) & 255)


def _clip_span(x0, x1):
    a = int(math.ceil(x0))
    b = int(math.ceil(x1))
    if a < 0:
        a = 0
    if b > W2:
        b = W2
    return a, b


def fill_span(y, x0, x1, val):
    """Solid horizontal span on 2x buffer row y (ints, x in 2x coords)."""
    if y < 0 or y >= H2:
        return
    a, b = _clip_span(x0, x1)
    if b <= a:
        return
    base = y * W2
    buf[base + a:base + b] = array.array("I", [val]) * (b - a)


def blend_span(y, x0, x1, r, g, b, a):
    """Alpha-blended horizontal span (a in 0..1)."""
    if y < 0 or y >= H2 or a <= 0:
        return
    aa, bb = _clip_span(x0, x1)
    if bb <= aa:
        return
    ia = 1.0 - a
    base = y * W2
    for x in range(aa, bb):
        v = buf[base + x]
        orr = v & 255
        og = (v >> 8) & 255
        ob = (v >> 16) & 255
        buf[base + x] = 0xFF000000 | (
            (int(b * a + ob * ia) << 16)
            | (int(g * a + og * ia) << 8)
            | int(r * a + orr * ia)
        )


def lerp(c0, c1, t):
    return (
        c0[0] + (c1[0] - c0[0]) * t,
        c0[1] + (c1[1] - c0[1]) * t,
        c0[2] + (c1[2] - c0[2]) * t,
    )


def grad_at(stops, t):
    """stops: list of (pos, (r,g,b)) with pos in 0..1."""
    if t <= stops[0][0]:
        return stops[0][1]
    for i in range(1, len(stops)):
        if t <= stops[i][0]:
            p0, c0 = stops[i - 1]
            p1, c1 = stops[i]
            return lerp(c0, c1, (t - p0) / (p1 - p0))
    return stops[-1][1]


# ------------------------------------------------------------- 1x helpers
# All geometry below is in 1024-space; helpers scale by SS=2.

def rect(x, y, w, h, rgb, alpha=1.0):
    val = P(*rgb)
    y0 = int(round(y * SS))
    y1 = int(round((y + h) * SS))
    x0 = x * SS
    x1 = (x + w) * SS
    for yy in range(max(0, y0), min(H2, y1)):
        if alpha >= 1.0:
            fill_span(yy, x0, x1, val)
        else:
            blend_span(yy, x0, x1, rgb[0], rgb[1], rgb[2], alpha)


def ell(cx, cy, rx, ry, rgb, alpha=1.0):
    val = P(*rgb)
    y0 = int((cy - ry) * SS)
    y1 = int((cy + ry) * SS) + 1
    for yy in range(max(0, y0), min(H2, y1)):
        dy = ((yy + 0.5) / SS - cy) / ry
        if abs(dy) >= 1.0:
            continue
        dx = rx * math.sqrt(1.0 - dy * dy)
        if alpha >= 1.0:
            fill_span(yy, (cx - dx) * SS, (cx + dx) * SS, val)
        else:
            blend_span(yy, (cx - dx) * SS, (cx + dx) * SS,
                       rgb[0], rgb[1], rgb[2], alpha)


def dot(x, y, r, rgb, alpha=1.0):
    ell(x, y, r, r, rgb, alpha)


def poly(pts, rgb, alpha=1.0, colfn=None):
    """Even-odd polygon fill. pts in 1x coords. colfn(y1x)->(r,g,b)."""
    sp = [(px * SS, py * SS) for px, py in pts]
    edges = []
    n = len(sp)
    for i in range(n):
        x0, y0 = sp[i]
        x1, y1 = sp[(i + 1) % n]
        if y0 != y1:
            edges.append((x0, y0, x1, y1))
    if not edges:
        return
    ys = [p[1] for p in sp]
    y0 = max(0, int(min(ys)))
    y1 = min(H2 - 1, int(max(ys)) + 1)
    for yy in range(y0, y1 + 1):
        yc = yy + 0.5
        xs = []
        for x0, ya, x1, yb in edges:
            if (ya <= yc < yb) or (yb <= yc < ya):
                t = (yc - ya) / (yb - ya)
                xs.append(x0 + t * (x1 - x0))
        xs.sort()
        if colfn is not None:
            rgb = colfn((yy + 0.5) / SS)
        val = P(*[int(c) for c in rgb])
        for i in range(0, len(xs) - 1, 2):
            if alpha >= 1.0:
                fill_span(yy, xs[i], xs[i + 1], val)
            else:
                blend_span(yy, xs[i], xs[i + 1], rgb[0], rgb[1], rgb[2], alpha)


def line(x0, y0, x1, y1, w, rgb, alpha=1.0):
    dx, dy = x1 - x0, y1 - y0
    L = math.hypot(dx, dy) or 1.0
    nx, ny = -dy / L * w / 2.0, dx / L * w / 2.0
    poly([(x0 + nx, y0 + ny), (x1 + nx, y1 + ny),
          (x1 - nx, y1 - ny), (x0 - nx, y0 - ny)], rgb, alpha)


def soft_ell(cx, cy, rx, ry, rgb, alpha, steps=3):
    """Soft-edged ellipse: concentric shrinking ellipses, fading alpha."""
    for i in range(steps, 0, -1):
        f = i / steps
        ell(cx, cy, rx * (0.6 + 0.4 * f), ry * (0.6 + 0.4 * f),
            rgb, alpha * f / steps)


def hgrad_rect(x, y, w, h, stops):
    """Vertical gradient fill of a rect (1x coords)."""
    for yy in range(int(y), int(y + h) + 1):
        t = (yy - y) / max(1.0, h)
        rect(x, yy, w, 1, grad_at(stops, t))


# ------------------------------------------------------------- glyphs
# Unit space: 100 wide x 140 tall. Each glyph = list of contours
# (contour = list of (x, y)); filled even-odd.

def ell_pts(cx, cy, rx, ry, n=44, a0=0.0, a1=360.0):
    pts = []
    for i in range(n + 1):
        a = math.radians(a0 + (a1 - a0) * i / n)
        pts.append((cx + rx * math.cos(a), cy + ry * math.sin(a)))
    return pts


def ring(cx, cy, rx, ry, t, a0=0.0, a1=360.0, n=44):
    outer = ell_pts(cx, cy, rx, ry, n, a0, a1)
    inner = ell_pts(cx, cy, rx - t, ry - t, n, a1, a0)
    return outer + inner


def arc_band(cx, cy, rx, ry, a0, a1, t, icx, icy, irx, iry, n=30):
    outer = ell_pts(cx, cy, rx, ry, n, a0, a1)
    inner = ell_pts(icx, icy, irx, iry, n, a1, a0)
    return outer + inner


def _rect(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def _serif_pair(x0, x1):
    # top + bottom serif slabs for a stem spanning x0..x1
    return [
        [(x0 - 4, 0), (x1 + 4, 0), (x1 + 2, 7), (x0 - 2, 7)],
        [(x0 - 4, 133), (x1 + 4, 133), (x1 + 2, 140), (x0 - 2, 140)],
    ]


GL = {}
GL["O"] = [ring(50, 70, 48, 68, 16)]
GL["N"] = [
    _rect(4, 0, 20, 140), _rect(80, 0, 96, 140),
    [(4, 0), (20, 0), (96, 140), (80, 140)],
] + _serif_pair(4, 20) + _serif_pair(80, 96)
GL["D"] = [
    _rect(4, 0, 20, 140),
    arc_band(20, 70, 78, 68, -90, 90, 16, 36, 70, 46, 52),
] + _serif_pair(4, 20)
GL["A"] = [
    [(42, 0), (58, 0), (20, 140), (0, 140)],
    [(42, 0), (58, 0), (100, 140), (80, 140)],
    _rect(24, 88, 76, 104),
    [(50, 30), (28, 88), (72, 88)],  # counter (hole, even-odd)
    [(0, 133), (24, 133), (22, 140), (2, 140)],
    [(76, 133), (100, 133), (98, 140), (78, 140)],
]
GL["R"] = [
    _rect(4, 0, 20, 140),
    arc_band(20, 35, 78, 34, -90, 90, 15, 36, 35, 46, 19),
    [(24, 62), (42, 62), (100, 140), (82, 140)],
] + _serif_pair(4, 20)
# small caps for the tagline (thin strokes)
GL["T"] = [_rect(0, 0, 100, 14), _rect(45, 0, 55, 140),
          [(38, 133), (62, 133), (62, 140), (38, 140)]]
GL["H"] = [_rect(4, 0, 16, 140), _rect(84, 0, 96, 140), _rect(4, 63, 96, 77)]
GL["E"] = [_rect(4, 0, 16, 140), _rect(4, 0, 96, 14),
          _rect(4, 63, 78, 77), _rect(4, 126, 96, 140)]
GL["F"] = [_rect(4, 0, 16, 140), _rect(4, 0, 96, 14), _rect(4, 63, 72, 77)]
GL["L"] = [_rect(4, 0, 16, 140), _rect(4, 126, 96, 140)]
GL["S"] = [ring(50, 38, 44, 34, 13, 180, 390),
          ring(50, 102, 44, 34, 13, -30, 210)]
GL["I"] = [_rect(44, 0, 56, 140), _rect(36, 0, 64, 8), _rect(36, 132, 64, 140)]


def draw_text(text, cx, y_top, cap_h, widen=1.0, tracking=0.0,
              rgb=(245, 230, 180), shadow=None, colfn=None):
    """Draw text centered on cx, top at y_top. Returns (x_start, x_end)."""
    sy = cap_h / 140.0
    sx = sy * widen
    widths = []
    for ch in text:
        if ch == " ":
            widths.append(60.0 * sx)
        else:
            widths.append(100.0 * sx)
    total = sum(widths) + tracking * max(0, len(text) - 1)
    x = cx - total / 2.0
    x0_total = x
    for ch, wdt in zip(text, widths):
        if ch != " " and ch in GL:
            for contour in GL[ch]:
                pts = [(x + px * sx, y_top + py * sy) for px, py in contour]
                if shadow is not None:
                    sh = [(px + shadow[0], py + shadow[1]) for px, py in pts]
                    poly(sh, shadow[2], shadow[3])
                poly(pts, rgb, 1.0, colfn)
        x += wdt + tracking
    return x0_total, x0_total + total


# ------------------------------------------------------------- scene

def draw_sky():
    stops = [
        (0.00, (27, 42, 82)), (0.28, (58, 47, 99)), (0.48, (91, 58, 110)),
        (0.66, (140, 66, 110)), (0.82, (198, 90, 122)),
        (0.93, (240, 138, 78)), (1.00, (240, 150, 90)),
    ]
    for y in range(16, 563):
        t = (y - 16) / 546.0
        rect(16, y, 992, 1, grad_at(stops, t))
    # stars in the upper indigo zone
    for _ in range(46):
        sx = rng.uniform(24, 1000)
        sy = rng.uniform(24, 290)
        r = rng.uniform(0.8, 1.8)
        dot(sx, sy, r, (255, 244, 220), rng.uniform(0.3, 0.75))
    # thin cloud bands (soft, blurred edges via layered ellipses)
    bands = [
        (220, 318, 185, 7, (244, 150, 140), 0.32),
        (180, 356, 150, 6, (250, 170, 150), 0.28),
        (180, 392, 120, 6, (245, 160, 150), 0.22),
        (945, 330, 60, 7, (244, 150, 140), 0.28),
        (950, 372, 55, 6, (250, 170, 150), 0.22),
    ]
    for cx, cy, rx, ry, col, a in bands:
        soft_ell(cx, cy, rx, ry, col, a, steps=3)
        soft_ell(cx, cy, rx * 0.55, ry * 1.6, col, a * 0.6, steps=2)
    # warm horizon glow
    soft_ell(660, 548, 420, 34, (255, 190, 130), 0.22, steps=3)


def draw_sea():
    stops = [
        (0.00, (42, 138, 138)), (0.32, (30, 110, 118)),
        (0.68, (18, 80, 92)), (1.00, (13, 63, 76)),
    ]
    for y in range(560, 1009):
        t = (y - 560) / 448.0
        rect(16, y, 992, 1, grad_at(stops, t))
    # arch reflections under the base
    rect(452, 700, 70, 110, (20, 70, 84), 0.18)
    rect(820, 700, 70, 110, (20, 70, 84), 0.18)
    # glittering light-path: white/gold dashes, brightest near horizon
    for i in range(46):
        y = 712 + i * 6.4 + rng.uniform(-2, 2)
        if y > 1000:
            break
        t = (y - 712) / 288.0
        half = 18 + t * 150
        cx = 657 + rng.uniform(-half, half) * 0.7
        ln = rng.uniform(8, 40) * (1.0 - t * 0.45)
        a = 0.85 * (1.0 - t * 0.72)
        col = (255, 242, 205) if rng.random() < 0.55 else (235, 250, 245)
        rect(cx - ln / 2, y, ln, 2.2, col, a)
    # gentle wave strokes (irregular, darker teal)
    for _ in range(70):
        y = rng.uniform(566, 1000)
        x = rng.uniform(20, 980)
        ln = rng.uniform(20, 95)
        rect(x, y, ln, 1.6, (16, 70, 84), rng.uniform(0.25, 0.5))


def draw_sailboat(cx, cy, s=1.0):
    # hull + two white sails + warm light dot
    hull = [(cx - 15 * s, cy), (cx + 15 * s, cy), (cx + 9 * s, cy + 7 * s),
            (cx - 9 * s, cy + 7 * s)]
    poly(hull, (52, 44, 40))
    line(cx, cy - 34 * s, cx, cy, 2 * s, (70, 58, 48))
    poly([(cx + 1.5 * s, cy - 33 * s), (cx + 1.5 * s, cy - 2 * s),
          (cx + 20 * s, cy - 2 * s)], (250, 246, 232))
    poly([(cx - 1.5 * s, cy - 28 * s), (cx - 1.5 * s, cy - 2 * s),
          (cx - 14 * s, cy - 2 * s)], (242, 236, 220))
    dot(cx + 4 * s, cy - 2 * s, 1.8 * s, (255, 205, 110), 0.95)
    rect(cx - 12 * s, cy + 9 * s, 24 * s, 2, (200, 230, 225), 0.25)


def draw_house(x, y, w, h, body, roof_col, roof_kind="gable"):
    j = lambda: rng.uniform(-2, 2)
    poly([(x + j(), y), (x + w + j(), y), (x + w + j(), y + h),
          (x + j(), y + h)], body)
    # soft shadow under the eaves
    rect(x + 1, y + h - 4, w - 2, 4, (60, 30, 20), 0.18)
    if roof_kind == "gable":
        poly([(x - 3, y), (x + w / 2, y - 13 - rng.uniform(0, 4)),
              (x + w + 3, y)], roof_col)
    else:  # flat with slight pitch
        poly([(x - 2, y), (x + w + 2, y), (x + w, y - 7), (x, y - 7)],
             roof_col)
    # lit windows with warm glow
    nw = 1 if w < 52 else 2
    for i in range(nw):
        wx = x + w * (0.22 + 0.5 * i) if nw == 2 else x + w / 2 - 5
        wy = y + h * 0.3
        soft_ell(wx + 5, wy + 6, 11, 11, (255, 200, 105), 0.35, steps=2)
        rect(wx, wy, 10, 12, (255, 205, 110), 0.95)
        rect(wx, wy, 10, 2, (255, 230, 160), 0.9)
    if rng.random() < 0.5:
        rect(x + w / 2 - 4, y + h - 16, 9, 16, (96, 62, 44), 0.9)


def draw_hillside():
    # slope polygon: left edge x=16, right edge steps down to the sea
    edge = [(16, 372), (120, 392), (210, 430), (290, 500), (330, 580),
            (330, 700)]
    for y in range(372, 701):
        # right edge x by piecewise interpolation
        xr = 330.0
        for i in range(len(edge) - 1):
            (x0, y0), (x1, y1) = edge[i], edge[i + 1]
            if y0 <= y < y1:
                xr = x0 + (x1 - x0) * (y - y0) / (y1 - y0)
                break
        t = (y - 372) / 328.0
        col = lerp((138, 74, 50), (108, 52, 36), t)
        rect(16, y, xr - 16, 1, col)
    # speckled texture
    for _ in range(260):
        y = rng.uniform(380, 695)
        xr = 330.0
        for i in range(len(edge) - 1):
            (x0, y0), (x1, y1) = edge[i], edge[i + 1]
            if y0 <= y < y1:
                xr = x0 + (x1 - x0) * (y - y0) / (y1 - y0)
                break
        x = rng.uniform(18, max(20, xr - 4))
        dot(x, y, rng.uniform(0.8, 2.2), (88, 44, 30),
            rng.uniform(0.2, 0.5))
    # warm light along the slope crest
    for i in range(len(edge) - 1):
        (x0, y0), (x1, y1) = edge[i], edge[i + 1]
        line(x0, y0, x1, y1, 3, (214, 140, 96), 0.25)
    # cascade of houses stepping down the slope
    bodies = [(245, 238, 220), (244, 205, 190), (200, 228, 205),
              (250, 230, 190), (238, 214, 196)]
    roofs = [(176, 84, 52), (90, 60, 50), (150, 70, 48)]
    spots = [
        (30, 398, 56, 34), (105, 402, 48, 32),
        (25, 448, 60, 36), (100, 452, 52, 34), (165, 456, 46, 32),
        (30, 498, 58, 36), (105, 502, 50, 34), (170, 506, 48, 32),
        (225, 512, 44, 30),
        (40, 548, 56, 36), (115, 552, 52, 34), (180, 556, 48, 32),
        (240, 560, 44, 30),
        (60, 602, 54, 36), (130, 606, 50, 34), (195, 610, 46, 32),
        (90, 652, 52, 34), (160, 656, 48, 32),
    ]
    for (hx, hy, hw, hh) in spots:
        draw_house(hx + rng.uniform(-3, 3), hy + rng.uniform(-2, 2), hw, hh,
                   bodies[rng.randrange(len(bodies))],
                   roofs[rng.randrange(len(roofs))],
                   "gable" if rng.random() < 0.7 else "flat")
    # string lights draped between houses
    for (x0, y0, x1, y1) in [(60, 430, 150, 436), (90, 480, 210, 488),
                             (120, 532, 250, 540), (150, 584, 260, 592)]:
        for k in range(11):
            t = k / 10.0
            lx = x0 + (x1 - x0) * t
            ly = y0 + (y1 - y0) * t + 7 * math.sin(math.pi * t)
            dot(lx, ly, 1.7, (255, 210, 120), 0.95)


def arch_xl(y):
    """Left outer edge of the arch at 1x row y."""
    if y < 335:
        dy = (y - 335) / 92.0
        if abs(dy) >= 1.0:
            return 657.0
        return 657.0 - 205.0 * math.sqrt(1.0 - dy * dy)
    return 452.0 + 10.0 * (1.0 - (y - 335) / 365.0)


def arch_xr(y):
    return 657.0 + (657.0 - arch_xl(y)) + 6.0 * (700.0 - y) / 365.0


def draw_arch():
    # stone body, per-row gradient + left-lit / right-shaded faces
    for y in range(243, 701):
        xl = arch_xl(y)
        xr = arch_xr(y)
        t = (y - 243) / 457.0
        base = lerp(lerp((222, 168, 96), (201, 141, 78), t),
                    (160, 106, 53), max(0.0, t - 0.55) / 0.45)
        w = xr - xl
        left = tuple(min(255, c + 16) for c in base)
        right = tuple(max(0, c - 26) for c in base)
        rect(xl, y, w * 0.30, 1, left)
        rect(xl + w * 0.30, y, w * 0.45, 1, base)
        rect(xl + w * 0.75, y, w * 0.25, 1, right)
    # horizontal stone courses (slightly curved)
    for y in range(268, 700, 28):
        xl = arch_xl(y) + 5
        xr = arch_xr(y) - 5
        pts = []
        for k in range(9):
            t = k / 8.0
            pts.append((xl + (xr - xl) * t, y + 2.5 * math.sin(math.pi * t)))
        for k in range(len(pts) - 1):
            line(pts[k][0], pts[k][1], pts[k + 1][0], pts[k + 1][1],
                 1.8, (140, 90, 45), 0.5)
    # stone speckles
    for _ in range(130):
        y = rng.uniform(250, 695)
        xl = arch_xl(y) + 4
        xr = arch_xr(y) - 4
        x = rng.uniform(xl, xr)
        dot(x, y, rng.uniform(0.8, 2.0),
            (120, 78, 40) if rng.random() < 0.5 else (235, 185, 115),
            rng.uniform(0.2, 0.4))
    # ---- opening (shadow rim, then sky/sea seen through it)
    def opening_hw(y):
        if y < 425:
            dy = (y - 425) / 90.0
            if abs(dy) >= 1.0:
                return 0.0
            return 100.0 * math.sqrt(1.0 - dy * dy)
        return 100.0

    for y in range(335, 701):
        hw = opening_hw(y)
        if hw <= 0:
            continue
        # shadow rim: wider, darker, behind the opening fill
        rect(657 - hw - 7, y, 2 * (hw + 7), 1, (110, 66, 30), 0.5)
        if y < 560:
            t = (y - 335) / 225.0
            col = grad_at([(0.0, (91, 58, 110)), (0.45, (160, 76, 112)),
                           (0.8, (210, 100, 120)), (1.0, (240, 140, 82))], t)
        else:
            t = (y - 560) / 140.0
            col = lerp((42, 138, 138), (30, 110, 118), t)
        rect(657 - hw, y, 2 * hw, 1, col)
    draw_falls(opening_hw)


def draw_falls(opening_hw):
    # golden glow behind the top of the falls
    soft_ell(657, 365, 120, 62, (255, 200, 140), 0.20, steps=3)
    # rising column: pale aqua-white, widening slightly toward the sea
    for y in range(345, 701):
        hw = 49.0 + 16.0 * (y - 345) / 355.0
        cx = 657.0 + 6.0 * math.sin((y - 345) / 355.0 * math.pi)
        t = (y - 345) / 355.0
        col = lerp(lerp((240, 248, 245), (198, 230, 226), t),
                   (226, 244, 240), max(0.0, t - 0.7) / 0.3)
        w = 2 * hw
        rect(cx - hw, y, w * 0.30, 1, tuple(min(255, c + 10) for c in col))
        rect(cx - hw + w * 0.30, y, w * 0.45, 1, col)
        rect(cx - hw + w * 0.75, y, w * 0.25, 1,
             tuple(max(0, c - 12) for c in col))
    # vertical streaks inside the column
    for _ in range(26):
        x = rng.uniform(600, 714)
        y0 = rng.uniform(350, 640)
        ln = rng.uniform(40, 180)
        col = (255, 255, 255) if rng.random() < 0.6 else (170, 215, 210)
        rect(x, y0, rng.uniform(1.5, 3.5), ln, col, rng.uniform(0.25, 0.45))
    # mist dissolving into cloud at the top of the opening
    for (mx, my, mr) in [(640, 352, 34), (675, 345, 30), (657, 368, 40),
                         (620, 372, 26), (692, 372, 26)]:
        soft_ell(mx, my, mr, mr * 0.55, (245, 250, 248), 0.30, steps=3)
    # rising spray + golden droplets catching the dusk light
    for _ in range(95):
        x = rng.uniform(598, 716)
        y = rng.uniform(338, 430)
        dot(x, y, rng.uniform(1.0, 3.0), (255, 255, 255),
            rng.uniform(0.45, 0.9))
    for _ in range(26):
        x = rng.uniform(606, 708)
        y = rng.uniform(380, 520)
        dot(x, y, rng.uniform(1.2, 2.4), (255, 215, 130),
            rng.uniform(0.6, 0.9))
    # foam ring at the sea base
    for (rx, ry, a) in [(96, 12, 0.85), (76, 9, 0.6), (56, 6, 0.45)]:
        ell(657, 700, rx, ry, (255, 255, 255), a)
    for _ in range(42):
        ang = rng.uniform(0, 2 * math.pi)
        rr = rng.uniform(40, 100)
        dot(657 + rr * math.cos(ang), 700 + rr * 0.28 * math.sin(ang),
            rng.uniform(1.0, 3.0), (255, 255, 255), rng.uniform(0.5, 0.95))


def draw_crown_houses():
    bodies = [(245, 238, 220), (244, 205, 190), (200, 228, 205),
              (250, 230, 190)]
    roofs = [(176, 84, 52), (90, 60, 50)]
    # dome top at x: base y for a house centered at hx
    def dome_y(hx):
        d = (hx - 657.0) / 205.0
        if abs(d) >= 1.0:
            return 335.0
        return 335.0 - 92.0 * math.sqrt(1.0 - d * d)

    spots = [(505, 40, 30), (552, 36, 28), (600, 38, 30),
             (700, 38, 30), (748, 36, 28), (795, 40, 30)]
    for hx, hw, hh in spots:
        by = dome_y(hx)
        draw_house(hx - hw / 2, by - hh, hw, hh,
                   bodies[rng.randrange(len(bodies))],
                   roofs[rng.randrange(len(roofs))], "gable")
    # one taller tower house near the crown centre
    by = dome_y(657)
    poly([(640, by - 52), (674, by - 52), (674, by), (640, by)],
         (250, 232, 196))
    poly([(636, by - 52), (657, by - 70), (678, by - 52)], (176, 84, 52))
    soft_ell(657, by - 34, 10, 10, (255, 200, 105), 0.35, steps=2)
    rect(652, by - 40, 10, 12, (255, 205, 110), 0.95)
    rect(652, by - 14, 10, 14, (96, 62, 44), 0.9)
    # string lights along the crown edge
    for k in range(26):
        t = k / 25.0
        hx = 468 + t * (846 - 468)
        dot(hx, dome_y(hx) + 3, 1.7, (255, 210, 120), 0.95)


def draw_terrace():
    # floor
    hgrad_rect(16, 900, 992, 109,
               [(0.0, (214, 190, 160)), (1.0, (168, 138, 108))])
    # balusters + rails (cream stone)
    rect(16, 878, 992, 12, (238, 224, 196))
    rect(16, 878, 992, 2, (252, 242, 220))
    for x in range(30, 1000, 26):
        poly([(x, 890), (x + 10, 890), (x + 8, 960), (x + 2, 960)],
             (226, 208, 178))
        rect(x + 2, 890, 2, 70, (250, 238, 214), 0.6)
    rect(16, 960, 992, 10, (210, 186, 152))


def draw_couple():
    # soft shadow on the floor
    soft_ell(215, 1002, 95, 10, (60, 40, 25), 0.18, steps=2)
    # --- woman, red dress + wide straw hat
    # dress (back view, slight waist curve)
    poly([(158, 842), (204, 842), (212, 905), (216, 1008),
          (146, 1008), (150, 905)], (205, 70, 50))
    poly([(186, 842), (204, 842), (212, 905), (216, 1008),
          (196, 1008), (192, 905)], (178, 56, 42), 0.55)
    poly([(158, 842), (172, 842), (168, 1008), (146, 1008), (150, 905)],
         (228, 96, 66), 0.45)
    # head + hair
    dot(182, 822, 13, (58, 40, 32))
    # straw hat: brim + dome + red band
    ell(182, 806, 42, 9, (232, 205, 140))
    ell(182, 800, 22, 12, (240, 216, 152))
    rect(160, 800, 44, 5, (200, 60, 50))
    # --- man, white shirt, dark hair
    dot(250, 818, 14, (40, 32, 26))
    rect(244, 830, 12, 12, (210, 170, 140))
    poly([(222, 842), (278, 842), (288, 1008), (212, 1008)], (242, 236, 222))
    poly([(262, 842), (278, 842), (288, 1008), (268, 1008)],
         (214, 206, 190), 0.5)
    poly([(222, 842), (236, 842), (228, 1008), (212, 1008)],
         (250, 244, 232), 0.5)
    # collar hint
    poly([(242, 842), (258, 842), (250, 856)], (226, 218, 200))
    # warm rim light on the outer edges
    line(150, 905, 146, 1008, 3, (255, 190, 140), 0.3)
    line(288, 1008, 278, 842, 3, (255, 200, 150), 0.25)


def draw_table():
    # round table + 2 wine glasses + bottle
    ell(375, 986, 22, 5, (120, 84, 48))
    rect(370, 918, 10, 66, (120, 84, 48))
    ell(375, 912, 48, 10, (150, 105, 60))
    ell(375, 910, 48, 8, (182, 132, 80))
    # bottle
    poly([(371, 872), (379, 872), (379, 908), (371, 908)], (52, 74, 46))
    rect(373, 862, 4, 12, (52, 74, 46))
    rect(372, 858, 6, 5, (200, 170, 110))
    # wine glasses
    for gx in (350, 396):
        poly([(gx - 7, 884), (gx + 7, 884), (gx + 4, 896), (gx - 4, 896)],
             (250, 244, 228), 0.9)
        rect(gx - 5, 890, 10, 4, (240, 205, 130), 0.95)
        rect(gx - 1, 896, 2, 10, (250, 244, 228), 0.9)
        ell(gx, 907, 6, 2, (250, 244, 228), 0.9)


def draw_bougainvillea():
    pinks = [(230, 60, 120), (240, 90, 140), (210, 40, 110),
             (245, 120, 160), (225, 70, 135)]
    for (cx, cy, rx, ry, n) in [(45, 940, 48, 70, 170),
                                (520, 925, 42, 60, 140)]:
        for _ in range(n):
            ang = rng.uniform(0, 2 * math.pi)
            rr = math.sqrt(rng.random())
            x = cx + rr * rx * math.cos(ang)
            y = cy + rr * ry * math.sin(ang)
            dot(x, y, rng.uniform(1.8, 4.2),
                pinks[rng.randrange(len(pinks))], rng.uniform(0.85, 1.0))
        for _ in range(22):
            ang = rng.uniform(0, 2 * math.pi)
            rr = math.sqrt(rng.random())
            x = cx + rr * rx * math.cos(ang)
            y = cy + rr * ry * math.sin(ang)
            ell(x, y, rng.uniform(3, 6), rng.uniform(2, 3.5),
                (60, 110, 60), 0.8)


def draw_frame():
    rect(0, 0, 1024, 14, (242, 230, 200))
    rect(0, 1010, 1024, 14, (242, 230, 200))
    rect(0, 0, 14, 1024, (242, 230, 200))
    rect(1010, 0, 14, 1024, (242, 230, 200))
    # thin inner dark line
    rect(18, 18, 988, 2, (60, 45, 25), 0.55)
    rect(18, 1004, 988, 2, (60, 45, 25), 0.55)
    rect(18, 18, 2, 988, (60, 45, 25), 0.55)
    rect(1004, 18, 2, 988, (60, 45, 25), 0.55)


def draw_type():
    # tagline above the name, with rules left and right
    x0, x1 = draw_text("THE FALLS THAT RISE", 512, 42, 22, widen=1.0,
                       tracking=9.0, rgb=(245, 233, 200))
    line(100, 53, x0 - 22, 53, 2, (245, 233, 200), 0.9)
    line(x1 + 22, 53, 924, 53, 2, (245, 233, 200), 0.9)
    # name: huge smooth gold serif with warm drop shadow + vertical gradient
    def gold(y):
        t = (y - 78) / 130.0
        return grad_at([(0.0, (252, 240, 196)), (0.55, (240, 210, 130)),
                        (1.0, (222, 182, 92))], t)

    draw_text("ONDARA", 512, 78, 130, widen=1.45, tracking=18.0,
              rgb=(240, 210, 130),
              shadow=(5, 6, (118, 78, 38), 0.5), colfn=gold)


# ------------------------------------------------------------- downsample
def downsample():
    out = array.array("I", [0]) * (W * H)
    mask = 0xFEFEFEFE
    for y in range(H):
        r0 = 2 * y
        r1 = r0 + 1
        b0 = r0 * W2
        b1 = r1 * W2
        ob = y * W
        for x in range(W):
            i = 2 * x
            a = buf[b0 + i]
            b = buf[b0 + i + 1]
            c = buf[b1 + i]
            d = buf[b1 + i + 1]
            h0 = (a & b) + (((a ^ b) & mask) >> 1)
            h1 = (c & d) + (((c ^ d) & mask) >> 1)
            out[ob + x] = (h0 & h1) + (((h0 ^ h1) & mask) >> 1)
    return out


def write_png(path, w, h, px):
    raw = bytearray()
    rowbytes = w * 4
    data = px.tobytes()
    for y in range(h):
        raw.append(0)
        raw += data[y * rowbytes:(y + 1) * rowbytes]
    comp = zlib.compress(bytes(raw), 9)

    def chunk(typ, payload):
        c = struct.pack(">I", len(payload)) + typ + payload
        return c + struct.pack(">I", zlib.crc32(typ + payload) & 0xFFFFFFFF)

    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
    png += chunk(b"IDAT", comp)
    png += chunk(b"IEND", b"")
    with open(path, "wb") as f:
        f.write(png)
    return len(png)


def main():
    draw_sky()
    draw_sea()
    draw_hillside()
    draw_arch()
    draw_crown_houses()
    draw_sailboat(385, 688, 1.0)
    draw_sailboat(878, 678, 0.9)
    draw_terrace()
    draw_couple()
    draw_table()
    draw_bougainvillea()
    draw_type()
    draw_frame()
    px = downsample()
    os.makedirs("/output", exist_ok=True)
    size = write_png("/output/entry.png", W, H, px)
    digest = hashlib.sha256(open("/output/entry.png", "rb").read()).hexdigest()
    print("wrote /output/entry.png %dx%d %d bytes sha256=%s"
          % (W, H, size, digest))


if __name__ == "__main__":
    main()
