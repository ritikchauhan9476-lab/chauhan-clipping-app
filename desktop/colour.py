"""Colour correction in one place: the controls (every one is a number from -100 to +100, 0 = no change),
the FFmpeg filters used by the export, and the matching maths used by the live preview.

Stored settings (cfg keys) keep their old units so old projects still open: warmth -1..1, saturation 0..2.5,
contrast 0.5..1.8, brightness -0.4..0.4, gamma 0.5..2, sharpness -2..2, hue -45..45 degrees. The new controls are
stored as -1..1 (= the number / 100). The window shows everything as -100..100 through to_ui / to_cfg.

Order (export and preview): tone curve (exposure, shadows, highlights, whites, blacks, brilliance, fade)
-> contrast / brightness / gamma / saturation -> temperature + tint -> hue -> clarity -> sharpen,
then, on the finished frame: particles (grain) -> vignette.
"""
import math
import numpy as np

try:
    from PIL import Image, ImageFilter
except ImportError:                      # the export does not need PIL; only the preview does
    Image = ImageFilter = None

NEW_DEFAULTS = dict(tint=0.0, exposure=0.0, highlights=0.0, shadows=0.0, whites=0.0, blacks=0.0,
                    brilliance=0.0, clarity=0.0, grain=0.0, fade=0.0, vignette=0.0,
                    vibrance=0.0, hdr=0.0, split_shadows=0.0, split_highlights=0.0)

# (section, key, label)
LAYOUT = [
    ("COLOUR", [("warmth", "Temperature"), ("tint", "Tint"), ("saturation", "Saturation"), ("vibrance", "Vibrance"),
                ("hue", "Hue")]),
    ("CC LOOK", [("hdr", "HDR detail"), ("split_shadows", "Shadows teal"), ("split_highlights", "Highlights orange")]),
    ("LIGHTNESS", [("exposure", "Exposure"), ("contrast", "Contrast"), ("highlights", "Highlights"),
                   ("shadows", "Shadows"), ("whites", "Whites"), ("blacks", "Blacks"),
                   ("brilliance", "Brilliance")]),
    ("EFFECTS", [("sharpness", "Sharpen"), ("clarity", "Clarity"), ("grain", "Particles"), ("fade", "Fade"),
                 ("vignette", "Vignette")]),
    ("ADVANCED", [("brightness", "Brightness"), ("gamma", "Gamma")]),
]
KEYS = [k for _, items in LAYOUT for k, _ in items]
NEUTRAL = dict(NEW_DEFAULTS, warmth=0.0, saturation=1.0, hue=0.0, contrast=1.0, sharpness=0.0,
               brightness=0.0, gamma=1.0)


def _two_sided(neg, pos):
    """cfg = 1 + ui/100*pos (ui > 0) or 1 + ui/100*neg (ui < 0), and the inverse."""
    return (lambda u: 1.0 + u / 100.0 * (pos if u > 0 else neg),
            lambda c: (c - 1.0) / pos * 100.0 if c > 1.0 else (c - 1.0) / neg * 100.0)


_MAP = {
    "saturation": _two_sided(1.0, 1.5),            # 0 .. 2.5
    "contrast": _two_sided(0.5, 0.8),              # 0.5 .. 1.8
    "gamma": _two_sided(0.5, 1.0),                 # 0.5 .. 2.0
    "hue": (lambda u: u / 100.0 * 45.0, lambda c: c / 45.0 * 100.0),
    "sharpness": (lambda u: u / 100.0 * 2.0, lambda c: c / 2.0 * 100.0),
    "brightness": (lambda u: u / 100.0 * 0.4, lambda c: c / 0.4 * 100.0),
}


def to_cfg(key, ui):
    ui = max(-100.0, min(100.0, float(ui)))
    return float(_MAP[key][0](ui)) if key in _MAP else ui / 100.0


def to_ui(key, cfg_value):
    v = float(cfg_value)
    ui = _MAP[key][1](v) if key in _MAP else v * 100.0
    return max(-100.0, min(100.0, ui))


def clamp(s):
    """Keeps every colour setting inside its range (used by engine.sanitize)."""
    for k in KEYS:
        lo, hi = {"saturation": (0.0, 2.5), "contrast": (0.5, 1.8), "gamma": (0.5, 2.0), "hue": (-45.0, 45.0),
                  "sharpness": (-2.0, 2.0), "brightness": (-0.4, 0.4)}.get(k, (-1.0, 1.0))
        s[k] = float(min(hi, max(lo, float(s.get(k, NEUTRAL[k])))))
    return s


# ------------------------------------------------------------------ tone curve (shared by export and preview)
def _bump(x, c, w):
    return np.exp(-((x - c) / w) ** 2)


def tone_active(s):
    return any(abs(float(s.get(k, 0.0))) > 1e-6 for k in ("exposure", "shadows", "highlights", "whites", "blacks",
                                                         "brilliance", "fade"))


def tone(x, s):
    """The tone curve y = f(x) for x in 0..1: exposure (+-1.5 stops), then lifts / drops of the shadows, highlights,
    whites and blacks, brilliance (opens shadows and midtones, calms highlights), then fade (matte look)."""
    e, sh, hi = float(s["exposure"]), float(s["shadows"]), float(s["highlights"])
    wh, bl, br, fa = float(s["whites"]), float(s["blacks"]), float(s["brilliance"]), float(s["fade"])
    y = x * (2.0 ** (1.5 * e))
    y = y + 0.22 * sh * _bump(x, 0.22, 0.20) + 0.22 * hi * _bump(x, 0.78, 0.20)
    y = y + 0.18 * wh * _bump(x, 0.90, 0.15) + 0.14 * bl * _bump(x, 0.08, 0.12)
    y = y + br * (0.14 * _bump(x, 0.33, 0.28) - 0.07 * _bump(x, 0.85, 0.15))
    if fa >= 0:
        y = y * (1.0 - 0.30 * fa) + 0.14 * fa
    else:
        k = 0.12 * (-fa)
        y = (y - k) / (1.0 - k)
    y = np.clip(y, 0.0, 1.0)
    return np.maximum.accumulate(y)                 # never goes backwards, whatever the sliders do


def tone_points(s, n=33):
    if not tone_active(s):
        return None
    xs = np.linspace(0.0, 1.0, n)
    return xs, tone(xs, s)


# ------------------------------------------------------------------ split toning (teal shadows / orange highlights)
def split_points(s, n=17):
    """Per-channel curves (r, g, b) of the split toning, or None. + shadows = teal, - = warm;
    + highlights = orange, - = cool blue."""
    ss, hh = float(s.get("split_shadows", 0.0)), float(s.get("split_highlights", 0.0))
    if abs(ss) < 1e-6 and abs(hh) < 1e-6:
        return None
    xs = np.linspace(0.0, 1.0, n)
    ws, wh = _bump(xs, 0.18, 0.24), _bump(xs, 0.82, 0.24)
    r = xs - 0.10 * ss * ws + 0.09 * hh * wh
    g = xs + 0.025 * ss * ws + 0.025 * hh * wh
    b = xs + 0.09 * ss * ws - 0.10 * hh * wh
    fix = lambda y: np.maximum.accumulate(np.clip(y, 0.0, 1.0))
    return xs, fix(r), fix(g), fix(b)


# ------------------------------------------------------------------ vibrance (same maths as FFmpeg's vibrance filter)
VIB_R, VIB_G, VIB_B = 0.072186, 0.715158, 0.212656          # FFmpeg's default luma weights of the filter


def vibrance_np(a, intensity):
    mx, mn = a.max(axis=-1), a.min(axis=-1)
    sat = mx - mn
    luma = a[..., 0] * VIB_R + a[..., 1] * VIB_G + a[..., 2] * VIB_B
    k = 1.0 + intensity * (1.0 - np.sign(intensity) * sat)
    return luma[..., None] + (a - luma[..., None]) * k[..., None]


def hdr_sigma(width):
    return max(2.0, width / 80.0)


# ------------------------------------------------------------------ .cube LUTs
_LUTS = {}


def read_cube(path):
    """A .cube 3D LUT -> (size, table [b][g][r][3], domain min, max). Cached."""
    import os
    key = (path, os.path.getmtime(path))
    if key in _LUTS:
        return _LUTS[key]
    size, vals, dmin, dmax = 0, [], [0.0, 0.0, 0.0], [1.0, 1.0, 1.0]
    with open(path, encoding="utf-8", errors="ignore") as f:
        for line in f:
            t = line.strip()
            if not t or t.startswith("#"):
                continue
            u = t.upper()
            if u.startswith("LUT_3D_SIZE"):
                size = int(t.split()[1])
            elif u.startswith("DOMAIN_MIN"):
                dmin = [float(x) for x in t.split()[1:4]]
            elif u.startswith("DOMAIN_MAX"):
                dmax = [float(x) for x in t.split()[1:4]]
            elif u[0].isdigit() or u[0] in "-.":
                p = t.split()
                if len(p) >= 3:
                    vals.append([float(p[0]), float(p[1]), float(p[2])])
    if size < 2 or len(vals) < size ** 3:
        raise ValueError("not a 3D .cube LUT")
    table = np.array(vals[:size ** 3], dtype=np.float32).reshape(size, size, size, 3)   # [b][g][r]
    out = (size, table, np.array(dmin, np.float32), np.array(dmax, np.float32))
    _LUTS.clear()
    _LUTS[key] = out
    return out


def apply_lut_np(a, path, mix=1.0):
    size, table, dmin, dmax = read_cube(path)
    x = np.clip((a - dmin) / np.maximum(1e-6, dmax - dmin), 0, 1) * (size - 1)
    i0 = np.floor(x).astype(np.int32)
    i0 = np.minimum(i0, size - 2)
    f = x - i0
    r0, g0, b0 = i0[..., 0], i0[..., 1], i0[..., 2]
    fr, fg, fb = f[..., 0:1], f[..., 1:2], f[..., 2:3]
    out = 0.0
    for db in (0, 1):
        wb = fb if db else 1 - fb
        for dg in (0, 1):
            wg = fg if dg else 1 - fg
            for dr in (0, 1):
                wr = fr if dr else 1 - fr
                out = out + table[b0 + db, g0 + dg, r0 + dr] * (wr * wg * wb)
    return a + (out - a) * float(mix)


def lut_ok(s):
    import os
    p = str(s.get("lut_path") or "")
    return bool(p) and os.path.isfile(p) and float(s.get("lut_mix", 1.0)) > 0.005


# ------------------------------------------------------------------ eq model (FFmpeg's eq works on limited-range luma)
def eq_luma(y_full, contrast, brightness, gamma):
    """Full-range luma 0..1 -> the same after eq: contrast, then brightness, then gamma."""
    y = (16.0 + 219.0 * y_full) / 255.0
    y = np.clip((y - 0.5) * contrast + 0.5, 0, 1)
    y = np.clip(y + brightness, 0, 1)
    y = y ** (1.0 / gamma)
    return np.clip((y * 255.0 - 16.0) / 219.0, 0, 1)


def mixer_gains(s):
    t, n = float(s["warmth"]), float(s["tint"])
    return 1.0 + 0.15 * t + 0.06 * n, 1.0 - 0.12 * n, 1.0 - 0.15 * t + 0.06 * n


def hue_rotate(a, deg):
    """a: float (h,w,3) 0..1. Rotates the colour vector like FFmpeg's hue filter (measured, error < 1 level)."""
    th = math.radians(-deg)
    y = _luma(a)
    u, v = (a[..., 2] - y) / 1.772, (a[..., 0] - y) / 1.402
    u2, v2 = u * math.cos(th) + v * math.sin(th), v * math.cos(th) - u * math.sin(th)
    r, b = y + 1.402 * v2, y + 1.772 * u2
    g = (y - 0.299 * r - 0.114 * b) / 0.587
    return np.stack([r, g, b], axis=-1)


def msize(width):
    """Clarity radius = FFmpeg unsharp matrix size. FFmpeg refuses anything above 13 x 13 (limit on the sum of the two
    sides), so it is 13 for pictures 1280 px wide or more and smaller for smaller pictures."""
    return max(5, int(round(13.0 * min(1.0, width / 1280.0))) | 1)


# ------------------------------------------------------------------ FFmpeg filters
def ffmpeg_colour(s, width):
    """Filters for the main colour stage (before crop / fit). `width` = width of the picture in pixels."""
    f = []
    pts = tone_points(s)
    if pts is not None:
        xs, ys = pts
        f.append("curves=all='" + " ".join(f"{x:.4f}/{y:.4f}" for x, y in zip(xs, ys)) + "'")
    c, b, sat, g = (float(s["contrast"]), float(s["brightness"]), float(s["saturation"]), float(s["gamma"]))
    if abs(c - 1) > 1e-6 or abs(b) > 1e-6 or abs(sat - 1) > 1e-6 or abs(g - 1) > 1e-6:
        f.append(f"eq=brightness={b:.3f}:contrast={c:.3f}:saturation={sat:.3f}:gamma={g:.3f}")
    if abs(float(s["warmth"])) > 1e-6 or abs(float(s["tint"])) > 1e-6:
        r, gg, bb = mixer_gains(s)
        f.append(f"colorchannelmixer=rr={r:.4f}:gg={gg:.4f}:bb={bb:.4f}")
    if abs(float(s["hue"])) > 1e-6:
        f.append(f"hue=h={float(s['hue']):.1f}")
    sp = split_points(s)
    if sp is not None:
        xs, r, g, b = sp
        pts = lambda ys: " ".join(f"{x:.4f}/{y:.4f}" for x, y in zip(xs, ys))
        f.append(f"curves=r='{pts(r)}':g='{pts(g)}':b='{pts(b)}'")
    vb = float(s.get("vibrance", 0.0))
    if abs(vb) > 1e-6:
        f.append(f"vibrance=intensity={vb:.3f}")
    cl = float(s["clarity"])
    if abs(cl) > 1e-6:
        m = msize(width)
        f.append(f"unsharp={m}:{m}:{cl * 1.5:.3f}:5:5:0")
    sh = float(s["sharpness"])
    if abs(sh) > 1e-6:
        f.append(f"unsharp=5:5:{sh:.2f}:5:5:0")
    return f


def ffmpeg_local(s, width, cur, newlab, fe):
    """The stages that need a second copy of the picture: LUT (with strength) and HDR detail (big-radius local
    contrast on the brightness only). Returns (graph lines, new label). They come after the main colour stage."""
    lines = []
    if lut_ok(s):
        mix = min(1.0, float(s.get("lut_mix", 1.0)))
        lut = f"lut3d=file={fe(s['lut_path'])}:interp=tetrahedral"
        lab = newlab()
        if mix >= 0.995:
            lines.append(f"{cur}{lut},format=yuv444p{lab}")
        else:
            n = lab[2:-1]
            lines.append(f"{cur}format=yuv444p,split[lta{n}][ltb{n}]")
            lines.append(f"[ltb{n}]{lut},format=yuv444p[ltc{n}]")
            lines.append(f"[lta{n}][ltc{n}]blend=all_mode=normal:all_opacity={mix:.3f}{lab}")
        cur = lab
    h = float(s.get("hdr", 0.0))
    if abs(h) > 1e-6:
        lab = newlab()
        n = lab[2:-1]
        k = 1.4 * h
        lines.append(f"{cur}format=yuv444p,split[hda{n}][hdb{n}]")
        lines.append(f"[hdb{n}]gblur=sigma={hdr_sigma(width):.1f}:planes=1[hdc{n}]")
        lines.append(f"[hda{n}][hdc{n}]blend=c0_expr='clip(A+(A-B)*{k:.3f},0,255)':c1_expr='A':c2_expr='A'{lab}")
        cur = lab
    return lines, cur


def vignette_angle(p):
    return 0.9 * abs(p)


def ffmpeg_finish(s):
    """Filters for the finished frame (after crop / fit, before overlays and text): particles, vignette."""
    f = []
    g = float(s["grain"])
    if g > 1e-6:
        f.append(f"noise=alls={max(1, round(35 * g))}:allf=t+u")
    elif g < -1e-6:
        a = abs(g)
        f.append(f"hqdn3d={10 * a:.1f}:{10 * a:.1f}:{8 * a:.1f}:{8 * a:.1f}")
    v = float(s["vignette"])
    if v > 1e-6:
        f.append(f"vignette=angle={vignette_angle(v):.4f}:dither=0")
    elif v < -1e-6:
        f.append(f"negate,vignette=angle={vignette_angle(v):.4f}:dither=0,negate")
    return f


# ------------------------------------------------------------------ preview (numpy / PIL)
def _luma(a):
    return a[..., 0] * 0.299 + a[..., 1] * 0.587 + a[..., 2] * 0.114


def apply_colour(img, s):
    """PIL RGB image -> PIL RGB image with the main colour stage applied (same maths as the export)."""
    a = np.asarray(img, dtype=np.float32) / 255.0
    pts = tone_points(s)
    if pts is not None:
        a = np.interp(a, pts[0], pts[1]).astype(np.float32)
    c, b, sat, g = (float(s["contrast"]), float(s["brightness"]), float(s["saturation"]), float(s["gamma"]))
    if abs(c - 1) > 1e-6 or abs(b) > 1e-6 or abs(g - 1) > 1e-6:
        y = _luma(a)
        a = a + (eq_luma(y, c, b, g) - y)[..., None]          # luma changes, the colour (chroma) stays
    if abs(sat - 1) > 1e-6:
        y = _luma(a)[..., None]
        a = y + (a - y) * sat
    if abs(float(s["warmth"])) > 1e-6 or abs(float(s["tint"])) > 1e-6:
        r, gg, bb = mixer_gains(s)
        a = a * np.array([r, gg, bb], dtype=np.float32)
    if abs(float(s["hue"])) > 1e-6:
        a = hue_rotate(a, float(s["hue"]))
    sp = split_points(s)
    if sp is not None:
        xs, r, g, b = sp
        a = np.stack([np.interp(a[..., 0], xs, r), np.interp(a[..., 1], xs, g), np.interp(a[..., 2], xs, b)],
                     axis=-1).astype(np.float32)
    vb = float(s.get("vibrance", 0.0))
    if abs(vb) > 1e-6:
        a = vibrance_np(np.clip(a, 0, 1), vb)
    out = Image.fromarray((np.clip(a, 0, 1) * 255 + 0.5).astype(np.uint8))
    m = msize(out.width)
    cl = float(s["clarity"])
    if cl > 1e-6:
        out = out.filter(ImageFilter.UnsharpMask(radius=0.154 * m, percent=int(cl * 117), threshold=0))
    elif cl < -1e-6:
        out = out.filter(ImageFilter.GaussianBlur(max(0.5, -cl / 0.6 * m / 13.0)))
    sh = float(s["sharpness"])
    if sh > 1e-6:
        out = out.filter(ImageFilter.UnsharpMask(radius=2, percent=int(sh * 60), threshold=0))
    elif sh < -1e-6:
        out = out.filter(ImageFilter.GaussianBlur(-sh * 1.15))
    if lut_ok(s):
        try:
            a = apply_lut_np(np.asarray(out, dtype=np.float32) / 255.0, s["lut_path"], min(1.0, float(s["lut_mix"])))
            out = Image.fromarray((np.clip(a, 0, 1) * 255 + 0.5).astype(np.uint8))
        except Exception:
            pass
    h = float(s.get("hdr", 0.0))
    if abs(h) > 1e-6:
        a = np.asarray(out, dtype=np.float32) / 255.0
        y = _luma(a)
        yi = Image.fromarray((np.clip(y, 0, 1) * 255).astype(np.uint8), "L")
        yb = np.asarray(yi.filter(ImageFilter.GaussianBlur(hdr_sigma(out.width))), dtype=np.float32) / 255.0
        a = a + ((y - yb) * 1.4 * h)[..., None]
        out = Image.fromarray((np.clip(a, 0, 1) * 255 + 0.5).astype(np.uint8))
    return out


def vignette_map(w, h, p):
    """FFmpeg's vignette falloff (measured on real output): cos(angle * r / half-diagonal) ^ 4, 1 in the middle.
    The same factor for every colour channel."""
    yy, xx = np.mgrid[0:h, 0:w]
    r = np.hypot(xx - w / 2 + 0.5, yy - h / 2 + 0.5)
    return np.cos(np.minimum(vignette_angle(p) * r / math.hypot(w / 2.0, h / 2.0), math.pi / 2)) ** 4


def apply_finish(img, s):
    """PIL RGB image of the finished frame -> particles and vignette applied."""
    g, v = float(s["grain"]), float(s["vignette"])
    if abs(g) < 1e-6 and abs(v) < 1e-6:
        return img
    a = np.asarray(img, dtype=np.float32) / 255.0
    if g > 1e-6:
        rng = np.random.default_rng(1)
        a = a + rng.uniform(-1, 1, a.shape[:2])[..., None].astype(np.float32) * (35 * g / 2.0 / 255.0)
    out = Image.fromarray((np.clip(a, 0, 1) * 255 + 0.5).astype(np.uint8))
    if g < -1e-6:
        out = out.filter(ImageFilter.GaussianBlur(0.6 * -g * max(1.0, out.width / 720.0)))
    if abs(v) > 1e-6:
        m = vignette_map(out.width, out.height, v)[..., None].astype(np.float32)
        a = np.asarray(out, dtype=np.float32) / 255.0
        a = a * m if v > 0 else 1.0 - (1.0 - a) * m
        out = Image.fromarray((np.clip(a, 0, 1) * 255 + 0.5).astype(np.uint8))
    return out


# ------------------------------------------------------------------ CC presets (one-click looks, 0 = no change)
PRESETS = {
    "HDR CC": dict(exposure=6, contrast=22, highlights=-35, shadows=35, blacks=-15, vibrance=55, saturation=15,
                   warmth=6, hdr=50, clarity=35, sharpness=22, split_shadows=20, split_highlights=15),
    "HDR CC warm (games / trailers)": dict(exposure=14, contrast=20, highlights=-25, shadows=40, blacks=-10,
                                           vibrance=70, saturation=30, warmth=12, hdr=45, clarity=30, sharpness=20,
                                           split_shadows=-45, split_highlights=-45),
    "HDR Strong": dict(exposure=6, contrast=30, highlights=-55, shadows=50, blacks=-25, vibrance=65, saturation=15,
                       warmth=6, hdr=90, clarity=55, sharpness=32, split_shadows=22, split_highlights=18),
    "Teal & Orange (cinematic)": dict(contrast=20, blacks=-15, highlights=-15, vibrance=25, saturation=-6, warmth=4,
                                      split_shadows=60, split_highlights=55, clarity=15),
    "Punchy (social media)": dict(contrast=25, vibrance=50, saturation=10, clarity=30, sharpness=30, shadows=15,
                                  highlights=-15, hdr=20),
    "Bright & clean (vlog)": dict(exposure=12, shadows=30, highlights=-20, whites=10, vibrance=30, contrast=8,
                                  sharpness=15),
    "Golden hour": dict(warmth=38, tint=6, vibrance=25, contrast=10, highlights=-18, shadows=10, split_highlights=38),
    "Sunset orange": dict(warmth=48, tint=10, contrast=16, vibrance=20, split_highlights=42, split_shadows=-10),
    "Cold blue": dict(warmth=-32, saturation=-8, contrast=16, split_shadows=40, split_highlights=-25),
    "Moody dark": dict(exposure=-12, contrast=30, blacks=-35, highlights=-20, saturation=-25, split_shadows=35,
                       clarity=20, vignette=35),
    "Cinematic film": dict(contrast=16, fade=22, saturation=-15, split_shadows=30, split_highlights=25, grain=14,
                           vignette=20),
    "Night neon": dict(tint=14, vibrance=60, contrast=22, blacks=-25, split_shadows=45, hdr=30, clarity=20),
    "Cyberpunk": dict(tint=32, warmth=-12, vibrance=45, contrast=24, blacks=-20, split_shadows=50,
                      split_highlights=-20, hdr=25),
    "Anime vivid": dict(saturation=40, vibrance=40, contrast=15, sharpness=40, shadows=15, whites=10),
    "Green nature": dict(vibrance=40, saturation=8, tint=-10, contrast=12, shadows=20, highlights=-20, hdr=25),
    "Vintage fade": dict(fade=40, warmth=15, saturation=-25, grain=20, vignette=25, contrast=-10),
    "Matte soft": dict(fade=35, contrast=-15, saturation=-10, highlights=-10),
    "Black & white HDR": dict(saturation=-100, contrast=35, hdr=60, clarity=40, blacks=-20, sharpness=20),
}


def preset_ui(name, strength=100.0, user=None):
    """The -100..100 value of every colour control for a preset at a strength (%). Controls not in the preset = 0."""
    p = (user or {}).get(name) or PRESETS.get(name) or {}
    k = float(strength) / 100.0
    return {key: max(-100.0, min(100.0, float(p.get(key, 0.0)) * k)) for key in KEYS}
