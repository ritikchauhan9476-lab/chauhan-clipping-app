"""Live preview: mirrors the export pipeline (colour -> chroma -> crop/aspect -> overlays -> text)
using PIL/numpy so every slider change shows up almost instantly. Runs in a background thread."""
import io, os, copy, subprocess, threading
from collections import OrderedDict
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import engine as E
import colour as CL

SHORT = 540                      # preview height/width of the short side
_frames = OrderedDict()
_flock = threading.Lock()
_stills = {}


def _q(t):
    return round(max(0.0, t) * 25) / 25


def frame_at(path, t, width=960):
    """One decoded frame of a video file at time t (cached)."""
    t = _q(t)
    key = (path, t, width)
    with _flock:
        if key in _frames:
            _frames.move_to_end(key)
            return _frames[key]
    cmd = ["ffmpeg", "-nostdin", "-v", "error", "-ss", f"{t:.3f}", "-i", path, "-frames:v", "1",
           "-vf", f"scale={width}:-2", "-f", "image2pipe", "-vcodec", "png", "-"]
    r = subprocess.run(cmd, capture_output=True, creationflags=E.NOWIN, timeout=60)
    if not r.stdout:
        raise RuntimeError("No frame at this time (outside the video or at the very end).")
    img = Image.open(io.BytesIO(r.stdout))
    img.load()
    img = img.convert("RGB")
    with _flock:
        _frames[key] = img
        while len(_frames) > 60:
            _frames.popitem(last=False)
    return img


def still_rgba(path):
    key = (path, os.path.getmtime(path))
    if key not in _stills:
        _stills[key] = Image.open(path).convert("RGBA")
    return _stills[key]


def _hex(c, default="00FF00"):
    c = str(c).strip().lstrip("#")
    if len(c) != 6:
        c = default
    try:
        return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return tuple(int(default[i:i + 2], 16) for i in (0, 2, 4))


def _key_rgb(s):
    return np.array(_hex(s["chroma_color"]), dtype=np.float32) / 255.0


def key_alpha(arr, s):
    """arr: float (h,w,3) 0..1 -> alpha (h,w): 0 = keyed (green), 1 = keep."""
    d = np.sqrt(((arr - _key_rgb(s)) ** 2).sum(-1)) / np.sqrt(3)
    sim = float(s["chroma_sim"])
    bl = max(float(s["chroma_blend"]), 1e-3)
    return np.clip((d - sim) / bl, 0, 1)


def cover(img, W, H):
    k = max(W / img.width, H / img.height)
    im = img.resize((max(W, round(img.width * k)), max(H, round(img.height * k))), Image.BILINEAR)
    x, y = (im.width - W) // 2, (im.height - H) // 2
    return im.crop((x, y, x + W, y + H))


def background(s, size, t):
    W, H = size
    if s["chroma_bg_type"] == "Color":
        return Image.new("RGB", size, _hex(s["chroma_bg_color"], "1E1E1E"))
    path = s["chroma_bg_file"]
    if not path or not os.path.isfile(path):
        return Image.new("RGB", size, (30, 30, 30))
    if path.lower().endswith(E.VIDEO_EXT):
        src = frame_at(path, t, 960)
    else:
        src = Image.open(path).convert("RGB")
    return cover(src, W, H)


def chroma_comp(fg, bg, s):
    a = key_alpha(np.asarray(fg, dtype=np.float32) / 255.0, s)[..., None]
    f = np.asarray(fg, dtype=np.float32)
    b = np.asarray(bg.resize(fg.size), dtype=np.float32)
    return Image.fromarray((f * a + b * (1 - a)).astype(np.uint8))


def apply_color(img, s):
    return CL.apply_colour(img, s)


def out_size(s, sw, sh, short=SHORT):
    if s["aspect"] == "Original":
        ratio = sw / sh
    else:
        a, b = (int(x) for x in s["aspect"].split(":"))
        ratio = a / b
    if ratio >= 1:
        W, H = int(round(short * ratio)), short
    else:
        W, H = short, int(round(short / ratio))
    return W // 2 * 2, H // 2 * 2


def source_crop_img(img, s):
    """Stage 1: the imported movie's crop (same maths as the export)."""
    x, y, w, h = E.source_crop_box(s, img.width, img.height)
    return img.crop((x, y, x + w, y + h)) if (w, h) != img.size else img


def fit(img, W, H, s):
    """Stage 2: fit the cropped picture into the final output frame (same modes as the export)."""
    iw, ih = img.size
    crop_mode = s["fit_mode"].startswith("Crop")
    pct = 100.0 if crop_mode else float(s.get("fit_scale", 100.0))
    if abs(W / H - iw / ih) < 0.01 and pct >= 99.5:
        return img.resize((W, H), Image.BILINEAR)
    if crop_mode:
        return cover(img, W, H)
    k = min(W / iw, H / ih) * pct / 100.0
    fw, fh = max(1, min(W, round(iw * k))), max(1, min(H, round(ih * k)))
    fg = img.resize((fw, fh), Image.BILINEAR)
    if s["fit_mode"].startswith("Blur"):
        bg = cover(img, W, H).filter(ImageFilter.GaussianBlur(max(1.0, float(s.get("blur_amount", 25)) * 0.56)))
    elif s["fit_mode"].startswith("Solid"):
        bg = Image.new("RGB", (W, H), _hex(s.get("bg_color", "#1E1E1E"), "1E1E1E"))
    else:
        bg = Image.new("RGB", (W, H), (0, 0, 0))
    bg.paste(fg, ((W - fw) // 2, int((H - fh) * float(s.get("fit_y", 50.0)) / 100.0)))
    return bg


def _pos(pos, x, y, W, H, w, h):
    if pos == "Custom":
        return int(W * x / 100), int(H * y / 100)
    if pos == "Center":
        return (W - w) // 2, (H - h) // 2
    mx, my = int(W * 0.03), int(H * 0.03)
    vert, horz = pos.split("-")
    px = {"Left": mx, "Center": (W - w) // 2, "Right": W - w - mx}[horz]
    py = {"Top": my, "Middle": (H - h) // 2, "Bottom": H - h - my}[vert]
    return px, py


def _layer(item):
    try:
        return int(item.get("layer", 1))
    except (TypeError, ValueError):
        return 1


def _visible(item, t):
    S = float(item.get("start", 0.0) or 0.0)
    en = float(item.get("end", 0.0) or 0.0)
    if en <= 0:
        en = 1e9
    return S <= t < en, S


def overlay_on(canvas, ov, t, s, W, H):
    ov = {**E.OVERLAY_DEFAULT, **ov}
    path = ov["path"]
    if not os.path.isfile(path):
        return
    ok, S = _visible(ov, t)
    if not ok:
        return
    local = t - S + float(ov.get("src_offset", 0.0) or 0.0)
    try:
        if path.lower().endswith(E.OVERLAY_VIDEO_EXT):
            img = frame_at(path, local, 640).convert("RGBA")
        else:
            img = still_rgba(path)
    except Exception:
        return
    ow = max(2, int(W * max(1, float(ov["scale"])) / 100))
    oh = max(2, int(img.height * ow / img.width))
    arr = np.asarray(img.resize((ow, oh), Image.BILINEAR), dtype=np.float32) / 255.0
    alpha = arr[..., 3] * float(ov["opacity"]) / 100.0
    if ov["chroma"]:
        ks = dict(s, chroma_color=ov.get("key_color", "#00FF00"), chroma_sim=ov.get("key_sim", 0.3),
                  chroma_blend=ov.get("key_blend", 0.1))
        alpha = alpha * key_alpha(arr[..., :3], ks)
    arr[..., 3] = alpha
    im = Image.fromarray((arr * 255).astype(np.uint8))
    x, y = _pos(ov["pos"], float(ov["x"]), float(ov["y"]), W, H, ow, oh)
    x, y = max(0, min(x, W - ow)), max(0, min(y, H - oh))
    canvas.alpha_composite(im, dest=(x, y))


def text_on(canvas, tx, W, H):
    tx = {**E.TEXT_DEFAULT, **tx}
    text = str(tx["text"]).strip("\n")
    if not text.strip():
        return
    fs = max(8, int(H * float(tx["size"]) / 100))
    path = E.resolve_font(tx["font"])
    try:
        font = ImageFont.truetype(path, fs) if path else ImageFont.load_default(size=fs)
    except Exception:
        font = ImageFont.load_default()
    ow = float(tx["outline"])
    sw = max(1, int(round(ow * H / 1080))) if ow > 0 else 0
    spacing = int(fs * 0.15)
    d0 = ImageDraw.Draw(canvas)
    bb = d0.multiline_textbbox((0, 0), text, font=font, spacing=spacing, align="center", stroke_width=sw)
    tw, th = bb[2] - bb[0], bb[3] - bb[1]
    mx, my = int(W * 0.04), int(H * 0.05)
    if tx["pos"] == "Custom":
        x, y = int(W * float(tx["x"]) / 100), int(H * float(tx["y"]) / 100)
    elif tx["pos"] == "Center":
        x, y = (W - tw) // 2, (H - th) // 2
    else:
        vert, horz = tx["pos"].split("-")
        x = {"Left": mx, "Center": (W - tw) // 2, "Right": W - tw - mx}[horz]
        y = {"Top": my, "Middle": (H - th) // 2, "Bottom": H - th - my}[vert]
    if tx.get("hcenter"):
        x = (W - tw) // 2
    if tx.get("vcenter"):
        y = (H - th) // 2
    pad = int(fs * 0.3)
    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    ox, oy = x - bb[0], y - bb[1]
    if tx["box"]:
        bc = _hex(tx["box_color"], "000000") + (int(float(tx["box_opacity"]) * 2.55),)
        d.rectangle((x - pad, y - pad, x + tw + pad, y + th + pad), fill=bc)
    if tx["shadow"]:
        sd = max(1, int(3 * H / 1080))
        d.multiline_text((ox + sd, oy + sd), text, font=font, fill=(0, 0, 0, 150), spacing=spacing, align="center")
    col = _hex(tx["color"], "FFFFFF") + (int(float(tx["opacity"]) * 2.55),)
    d.multiline_text((ox, oy), text, font=font, fill=col, spacing=spacing, align="center",
                     stroke_width=sw, stroke_fill=(0, 0, 0, 255))
    canvas.alpha_composite(layer)


def compose(movie, t, s, info, short=SHORT):
    """Full preview frame at movie time t, for the current settings s."""
    s = E.sanitize(s)
    dur = info["duration"]
    t = min(max(0.0, t), max(0.0, dur - 0.05))
    src = frame_at(movie, t, 960)
    if s["chroma_on"]:
        src = chroma_comp(src, background(s, src.size, t), s)
    src = apply_color(src, s)
    src = source_crop_img(src, s)
    W, H = out_size(s, *src.size, short=short)
    canvas = CL.apply_finish(fit(src, W, H, s), s).convert("RGBA")
    for ov in sorted(s["overlays"], key=_layer):
        overlay_on(canvas, ov, t, s, W, H)
    for tx in sorted(s["texts"], key=_layer):
        ok, _ = _visible(tx, t)
        if ok:
            text_on(canvas, tx, W, H)
    return canvas.convert("RGB")


class Renderer:
    """Background worker: always renders only the newest request (no backlog while dragging)."""

    def __init__(self, on_done):
        self.on_done = on_done
        self._job = None
        self._lock = threading.Lock()
        self._ev = threading.Event()
        self._info = {}
        threading.Thread(target=self._run, daemon=True).start()

    def submit(self, movie, t, s, token):
        with self._lock:
            self._job = (movie, t, copy.deepcopy(s), token)
        self._ev.set()

    def _info_for(self, movie):
        if movie not in self._info:
            self._info[movie] = E.probe_info(movie)
        return self._info[movie]

    def _run(self):
        while True:
            self._ev.wait()
            self._ev.clear()
            with self._lock:
                job = self._job
                self._job = None
            if not job:
                continue
            movie, t, s, token = job
            try:
                img, err = compose(movie, t, s, self._info_for(movie)), None
            except Exception as e:
                img, err = None, (str(e) or "Preview error")[-300:]
            self.on_done(img, token, err)


_vsize = {}


def overlay_box(ov, W, H):
    """Top-left and size (px, in preview coordinates) of an overlay, used for mouse handles."""
    ov = {**E.OVERLAY_DEFAULT, **ov}
    path = ov["path"]
    if path not in _vsize:
        try:
            if path.lower().endswith(E.OVERLAY_VIDEO_EXT):
                inf = E.probe_info(path)
                _vsize[path] = (inf["w"], inf["h"])
            else:
                _vsize[path] = still_rgba(path).size
        except Exception:
            _vsize[path] = (16, 9)
    w0, h0 = _vsize[path]
    ow = max(2, int(W * max(1, float(ov["scale"])) / 100))
    oh = max(2, int(h0 * ow / w0))
    x, y = _pos(ov["pos"], float(ov["x"]), float(ov["y"]), W, H, ow, oh)
    return x, y, ow, oh


def text_box(tx, W, H):
    """Top-left and ink size (px) of a text item, used for mouse handles."""
    tx = {**E.TEXT_DEFAULT, **tx}
    text = str(tx["text"]).strip("\n") or " "
    fs = max(8, int(H * float(tx["size"]) / 100))
    path = E.resolve_font(tx["font"])
    try:
        font = ImageFont.truetype(path, fs) if path else ImageFont.load_default(size=fs)
    except Exception:
        font = ImageFont.load_default()
    ow = float(tx["outline"])
    sw = max(1, int(round(ow * H / 1080))) if ow > 0 else 0
    d0 = ImageDraw.Draw(Image.new("RGB", (4, 4)))
    bb = d0.multiline_textbbox((0, 0), text, font=font, spacing=int(fs * 0.15), align="center", stroke_width=sw)
    tw, th = bb[2] - bb[0], bb[3] - bb[1]
    mx, my = int(W * 0.04), int(H * 0.05)
    if tx["pos"] == "Custom":
        x, y = int(W * float(tx["x"]) / 100), int(H * float(tx["y"]) / 100)
    elif tx["pos"] == "Center":
        x, y = (W - tw) // 2, (H - th) // 2
    else:
        vert, horz = tx["pos"].split("-")
        x = {"Left": mx, "Center": (W - tw) // 2, "Right": W - tw - mx}[horz]
        y = {"Top": my, "Middle": (H - th) // 2, "Bottom": H - th - my}[vert]
    if tx.get("hcenter"):
        x = (W - tw) // 2
    if tx.get("vcenter"):
        y = (H - th) // 2
    return x, y, tw, th
