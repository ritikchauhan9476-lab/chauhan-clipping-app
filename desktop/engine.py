"""Viral Clipper - engine: ffmpeg edit pipeline + AI clip finder + Simple part-by-part editor."""
import os, re, sys, json, math, shutil, subprocess, csv, site, tempfile
import numpy as np
import scoring as SC
import colour as CL

BASE = os.path.dirname(os.path.abspath(__file__))
INPUT_DIR = os.path.join(BASE, "input_movies")
OUTPUT_DIR = os.path.join(BASE, "exported_clips")
SETTINGS_FILE = os.path.join(BASE, "settings.json")
VIDEO_EXT = (".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm", ".m4v", ".ts")
IMAGE_EXT = (".png", ".jpg", ".jpeg", ".webp", ".bmp")
OVERLAY_VIDEO_EXT = VIDEO_EXT + (".gif",)
AUDIO_EXT = (".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".wma")
NOWIN = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0

FOCUS = ["Funny", "Emotional", "Funny + Emotional"]
LANGS = ["hi", "en", "auto"]
WHISPER = ["tiny", "base", "small", "medium"]
ASPECTS = ["Original", "1:1", "4:3", "3:2", "16:9", "9:16", "4:5", "21:9"]
FIT_MODES = ["Crop (fill frame)", "Blur background", "Black bars", "Solid colour"]
RES = ["Original", "480p", "720p", "1080p", "1440p", "2160p (4K)"]
FPS = ["Original", "24", "25", "30", "50", "60"]
CODECS = ["H.264 (NVIDIA GPU - fast)", "H.265 (NVIDIA GPU)", "H.264 (CPU)", "H.265 (CPU - slow)"]
ABR = ["96k", "128k", "192k", "256k", "320k"]
BITRATES = ["2000", "4000", "6000", "8000", "12000", "16000", "20000", "25000", "30000", "40000", "50000",
            "60000", "80000", "100000", "150000"]
MAX_BITRATE = 150000
RATE_MODES = ["Exact bitrate (use my number)", "Quality (bitrate is only a limit)"]
# one-click export settings (Export tab > Quick preset)
EXPORT_PRESETS = {
    "Reels / Shorts - best quality (1080p, 12 Mbps)": dict(resolution="1080p", fps="Original", quality="High",
                                                           rate_mode=RATE_MODES[0], bitrate=12000, audio_bitrate="192k"),
    "YouTube 1080p (16 Mbps)": dict(resolution="1080p", fps="Original", quality="High",
                                    rate_mode=RATE_MODES[0], bitrate=16000, audio_bitrate="192k"),
    "Small file for WhatsApp (720p, 3 Mbps)": dict(resolution="720p", fps="Original", quality="Balanced",
                                                   rate_mode=RATE_MODES[0], bitrate=3000, audio_bitrate="128k"),
}
MUSIC_MODES = ["Mix with original audio", "Replace original audio"]
BG_TYPES = ["Color", "Image", "Video"]
POSITIONS = ["Top-Left", "Top-Center", "Top-Right", "Middle-Left", "Center", "Middle-Right",
             "Bottom-Left", "Bottom-Center", "Bottom-Right", "Custom"]

OVERLAY_DEFAULT = dict(path="", pos="Top-Right", x=70, y=5, scale=20, opacity=100,
                       start=0.0, end=0.0, chroma=False, loop=True)
TEXT_DEFAULT = dict(text="Your text", font="Arial", size=6.0, color="#FFFFFF", opacity=100,
                    outline=2, outline_color="#000000", shadow=False, box=False,
                    box_color="#000000", box_opacity=50, pos="Bottom-Center", x=50, y=80,
                    start=0.0, end=0.0)

OVERLAY_DEFAULT = {**OVERLAY_DEFAULT, "layer": 1, "src_offset": 0.0, "key_color": "#00FF00", "key_sim": 0.30, "key_blend": 0.10, "key_spill": True}
TEXT_DEFAULT = {**TEXT_DEFAULT, "layer": 1, "hcenter": False, "vcenter": False}
AUDIO_DEFAULT = dict(path="", layer=1, start=0.0, end=0.0, src_offset=0.0, volume=100, loop=True)

DEFAULTS = dict(
    # AI clip finding
    focus="Funny + Emotional", min_dur=30, max_dur=60, min_score=40, max_per_chunk=3,
    max_total=0, language="hi", whisper_model="small", use_llm=False, llm_model="qwen2.5:3b",
    # simple editor
    part_len=60, trim_start=0.0, trim_end=0.0, min_last=5,
    # colour
    brightness=0.0, contrast=1.0, saturation=1.0, gamma=1.0, sharpness=0.0, hue=0.0,
    warmth=0.0, auto_crop=True,
    # size / crop
    src_aspect="Original", aspect="Original", fit_mode="Blur background", resolution="Original", fps="Original",
    zoom=1.0, crop_x=50, crop_y=50,
    bg_color="#1E1E1E", blur_amount=25, fit_scale=100.0, fit_y=50.0,   # background of the final frame
    **CL.NEW_DEFAULTS,                                                  # tint, exposure, shadows, ... (colour.py)
    # chroma key
    chroma_on=False, chroma_color="#00FF00", chroma_sim=0.15, chroma_blend=0.10,
    chroma_spill=True, chroma_bg_type="Color", chroma_bg_color="#1E1E1E", chroma_bg_file="",
    # overlays / text (lists of dicts)
    overlays=[], texts=[], audios=[],
    # music
    music_file="", music_mode="Mix with original audio", music_volume=60, orig_volume=100,
    music_loop=True,
    # export
    codec="H.264 (NVIDIA GPU - fast)", quality="High", bitrate=20000, audio_bitrate="192k",
    rate_mode="Exact bitrate (use my number)",
    fade_sec=0.15,
)
CHOICES = {"src_aspect": ASPECTS, "aspect": ASPECTS, "fit_mode": FIT_MODES, "resolution": RES, "fps": FPS,
           "codec": CODECS, "rate_mode": RATE_MODES, "audio_bitrate": ABR, "focus": FOCUS, "language": LANGS,
           "whisper_model": WHISPER, "music_mode": MUSIC_MODES, "chroma_bg_type": BG_TYPES}


def sanitize(s):
    s = dict(s)
    for k, d in DEFAULTS.items():
        if k not in s:
            s[k] = json.loads(json.dumps(d))
            continue
        if isinstance(d, bool):
            s[k] = bool(s[k])
        elif isinstance(d, (int, float)):
            try:
                s[k] = type(d)(float(s[k]))
            except (ValueError, TypeError):
                s[k] = d
        elif isinstance(d, list):
            if not isinstance(s[k], list):
                s[k] = []
        else:
            s[k] = str(s[k])
    for k, vals in CHOICES.items():
        if s[k] not in vals:
            s[k] = DEFAULTS[k]
    s["bitrate"] = int(min(MAX_BITRATE, max(500, s["bitrate"])))
    s["blur_amount"] = int(min(60, max(5, s["blur_amount"])))
    s["fit_scale"] = float(min(100.0, max(30.0, s["fit_scale"])))
    s["fit_y"] = float(min(100.0, max(0.0, s["fit_y"])))
    CL.clamp(s)
    if s.get("music_file") and not s["audios"]:
        s["audios"] = [dict(AUDIO_DEFAULT, path=s["music_file"], volume=int(s.get("music_volume", 60)),
                            loop=bool(s.get("music_loop", True)))]
        s["music_file"] = ""
    s["audios"] = [dict(AUDIO_DEFAULT, **a) for a in s["audios"] if isinstance(a, dict)]
    s["overlays"] = [dict(OVERLAY_DEFAULT, **a) for a in s["overlays"] if isinstance(a, dict)]
    s["texts"] = [dict(TEXT_DEFAULT, **a) for a in s["texts"] if isinstance(a, dict)]
    return s


SETTINGS_VERSION = 2


def load_settings():
    s = {}
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as f:
            s = json.load(f)
    except Exception:
        pass
    if s.get("_version", 1) < SETTINGS_VERSION:
        # older builds saved 9:16 / 1080p / 8 Mbps, which made exports look soft: start from the new defaults
        for k in ("aspect", "fit_mode", "resolution", "quality", "bitrate", "fade_sec"):
            s.pop(k, None)
        s["_version"] = SETTINGS_VERSION
    return sanitize(s)


def save_settings(s):
    data = sanitize(s)
    data["_version"] = SETTINGS_VERSION
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def list_movies():
    os.makedirs(INPUT_DIR, exist_ok=True)
    return sorted(os.path.join(INPUT_DIR, f) for f in os.listdir(INPUT_DIR)
                  if f.lower().endswith(VIDEO_EXT))


def validate(s, mode):
    s = sanitize(s)
    errs = []
    if s["music_file"] and not os.path.isfile(s["music_file"]):
        errs.append(f"Music file not found: {s['music_file']}")
    for i, ov in enumerate(s["overlays"], 1):
        if not os.path.isfile(ov.get("path", "")):
            errs.append(f"Overlay #{i} file not found: {ov.get('path', '')}")
    for i, a in enumerate(s["audios"], 1):
        if not os.path.isfile(a.get("path", "")):
            errs.append(f"Audio layer #{i} file not found: {a.get('path', '')}")
    if s["chroma_on"] and s["chroma_bg_type"] != "Color" and not os.path.isfile(s["chroma_bg_file"]):
        errs.append("Choose a background image or video for the chroma key.")
    if mode == "ai" and s["min_dur"] >= s["max_dur"]:
        errs.append("AI clip: Min length, Max length se chhoti honi chahiye.")
    if mode == "simple" and 0 < s["part_len"] < 2:
        errs.append("Part length kam se kam 2 second honi chahiye.")
    return errs


def whisper_source(name):
    """models/whisper-<name> next to the program (the portable version ships it) - otherwise the model name, which
    faster-whisper downloads once."""
    d = os.path.join(BASE, "models", "whisper-" + str(name))
    return d if os.path.isfile(os.path.join(d, "model.bin")) else name


def setup_cuda_paths():
    """Make pip-installed NVIDIA cuBLAS/cuDNN DLLs visible (Windows). Returns True when such DLLs were found."""
    found = False
    if os.name != "nt":
        return found
    try:
        for sp in site.getsitepackages() + [site.getusersitepackages()]:
            nv = os.path.join(sp, "nvidia")
            if os.path.isdir(nv):
                for d in os.listdir(nv):
                    b = os.path.join(nv, d, "bin")
                    if os.path.isdir(b):
                        os.add_dll_directory(b)
                        os.environ["PATH"] = b + os.pathsep + os.environ["PATH"]
                        found = True
    except Exception:
        pass
    return found


# ---------------------------------------------------------------- system fonts
_FONTS = None

def get_system_fonts():
    """{display name: font file path} - Windows registry (system + per-user) / font folders."""
    global _FONTS
    if _FONTS is not None:
        return _FONTS
    fonts = {}
    exts = (".ttf", ".otf", ".ttc")
    if os.name == "nt":
        win_fonts = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
        try:
            import winreg
            for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                try:
                    k = winreg.OpenKey(root, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts")
                except OSError:
                    continue
                i = 0
                while True:
                    try:
                        name, val, _ = winreg.EnumValue(k, i)
                    except OSError:
                        break
                    i += 1
                    if not isinstance(val, str):
                        continue
                    name = re.sub(r"\s*\((TrueType|OpenType|All res|Type 1)\)\s*$", "", name).strip()
                    path = val if os.path.isabs(val) else os.path.join(win_fonts, val)
                    if path.lower().endswith(exts) and os.path.isfile(path):
                        fonts[name] = path
        except Exception:
            pass
        dirs = [win_fonts, os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "Windows", "Fonts")]
    elif sys.platform == "darwin":
        dirs = ["/Library/Fonts", "/System/Library/Fonts", os.path.expanduser("~/Library/Fonts")]
    else:
        dirs = ["/usr/share/fonts", os.path.expanduser("~/.fonts"), os.path.expanduser("~/.local/share/fonts")]
    for d in dirs:
        for rootd, _, files in os.walk(d) if d and os.path.isdir(d) else []:
            for f in files:
                if f.lower().endswith(exts):
                    fonts.setdefault(os.path.splitext(f)[0], os.path.join(rootd, f))
    _FONTS = dict(sorted(fonts.items(), key=lambda kv: kv[0].lower()))
    return _FONTS


def resolve_font(name):
    fonts = get_system_fonts()
    if name in fonts:
        return fonts[name]
    for n, p in fonts.items():
        if n.lower() == str(name).lower():
            return p
    for cand in ("arial", "Arial", "DejaVuSans"):
        if cand in fonts:
            return fonts[cand]
    return next(iter(fonts.values()), None)


# ---------------------------------------------------------------- ffmpeg helpers
def ev(x):
    return max(2, int(round(x / 2.0)) * 2)

def ev_up(x):
    return max(2, int(math.ceil(x / 2.0)) * 2)

def hex0x(c, default="FFFFFF"):
    c = str(c).strip().lstrip("#")
    return "0x" + (c.upper() if re.fullmatch(r"[0-9a-fA-F]{6}", c) else default)

def fe(path):
    """Escape a file path for use inside an ffmpeg filter option."""
    p = os.path.abspath(path).replace("\\", "/")
    return "'" + p.replace(":", "\\:") + "'"

def probe_info(path):
    out = subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height,r_frame_rate",
         "-show_entries", "format=duration", "-of", "json", path], creationflags=NOWIN)
    d = json.loads(out.decode("utf-8", "ignore"))
    st = d.get("streams", [])
    v = next((x for x in st if x.get("codec_type") == "video" and x.get("width")), None)
    if not v:
        raise ValueError("No video stream found in this file.")
    fps = v.get("r_frame_rate", "25/1")
    try:
        n, dn = fps.split("/")
        if not (0 < float(n) / float(dn) <= 240):
            fps = "25/1"
    except Exception:
        fps = "25/1"
    return dict(w=int(v["width"]), h=int(v["height"]), fps=fps,
                has_audio=any(x.get("codec_type") == "audio" for x in st),
                duration=float(d["format"]["duration"]))

probe_duration = lambda p: probe_info(p)["duration"]

def read_audio(path, start, length):
    cmd = ["ffmpeg", "-nostdin", "-v", "error", "-ss", f"{start:.2f}", "-t", f"{length:.2f}", "-i", path,
           "-map", "0:a:0", "-vn", "-ac", "1", "-ar", "16000", "-f", "f32le", "-"]
    raw = subprocess.run(cmd, capture_output=True, creationflags=NOWIN).stdout
    return np.frombuffer(raw, dtype=np.float32)

def detect_crop(path, dur):
    """Find black bars (letterbox) so they can be removed."""
    try:
        r = subprocess.run(["ffmpeg", "-nostdin", "-ss", f"{dur*0.3:.0f}", "-t", "20", "-i", path,
                            "-vf", "cropdetect=24:2:0", "-f", "null", "-"],
                           capture_output=True, text=True, creationflags=NOWIN, timeout=180)
        m = re.findall(r"crop=(\d+:\d+:\d+:\d+)", r.stderr)
        return "crop=" + SC.Counter(m).most_common(1)[0][0] if m else None
    except Exception:
        return None

_AMIX = None
def amix_has_normalize():
    global _AMIX
    if _AMIX is None:
        try:
            r = subprocess.run(["ffmpeg", "-hide_banner", "-h", "filter=amix"], capture_output=True,
                               text=True, creationflags=NOWIN, timeout=20)
            _AMIX = "normalize" in (r.stdout + r.stderr)
        except Exception:
            _AMIX = False
    return _AMIX

def color_filters(s, width=1920):
    """Main colour stage (before crop / fit): see colour.py for every control."""
    return CL.ffmpeg_colour(s, width)

def key_chain(s):
    col = hex0x(s["chroma_color"], "00FF00")
    c = f"chromakey=color={col}:similarity={float(s['chroma_sim']):.3f}:blend={float(s['chroma_blend']):.3f}"
    if s["chroma_spill"]:
        r, g, b = int(col[2:4], 16), int(col[4:6], 16), int(col[6:8], 16)
        if g >= b and g > r:
            c += ",despill=type=green"
        elif b > g and b > r:
            c += ",despill=type=blue"
    return c

def source_crop_box(s, sw, sh):
    """Crop of the imported movie: ratio (src_aspect), zoom and position (crop_x / crop_y in %).
    Returns (x, y, w, h), all even numbers, inside the source frame."""
    a = str(s.get("src_aspect", "Original"))
    if a == "Original":
        ratio = sw / sh
    else:
        p, q = (int(v) for v in a.split(":"))
        ratio = p / q
    if sw / sh > ratio:
        bh, bw = sh, sh * ratio
    else:
        bw, bh = sw, sw / ratio
    z = max(1.0, float(s.get("zoom", 1.0)))
    w = min(sw, max(2, int(bw / z) // 2 * 2))
    h = min(sh, max(2, int(bh / z) // 2 * 2))
    cx = min(100, max(0, float(s.get("crop_x", 50))))
    cy = min(100, max(0, float(s.get("crop_y", 50))))
    x = int((sw - w) * cx / 100) // 2 * 2
    y = int((sh - h) * cy / 100) // 2 * 2
    return x, y, w, h


def out_size(s, sw, sh):
    short = {"480p": 480, "720p": 720, "1080p": 1080, "1440p": 1440, "2160p (4K)": 2160}.get(s["resolution"])
    if s["aspect"] == "Original":
        if short is None:
            return ev(sw), ev(sh)
        return (ev(sw * short / sh), ev(short)) if sw >= sh else (ev(short), ev(sh * short / sw))
    a, b = (int(x) for x in s["aspect"].split(":"))
    if short is None:                         # "Original" resolution: keep the (cropped) picture's own size
        short = min(sw, sh)
    return (ev(short * a / b), ev(short)) if a >= b else (ev(short), ev(short * b / a))

QUALITY = {"High": dict(crf=18, cq=19, x264="slow", nv="p6"),
           "Balanced": dict(crf=21, cq=23, x264="medium", nv="p5"),
           "Small file": dict(crf=24, cq=27, x264="fast", nv="p4")}


def encoder_args(s, codec=None):
    """Video + audio encoder options.
    rate_mode 'Exact bitrate': the bitrate you type is the bitrate you get (the file's properties show it).
    rate_mode 'Quality': constant quality (CRF / CQ); the bitrate is only an upper limit, so simple scenes
    end up far below it."""
    codec = codec or s["codec"]
    q = QUALITY.get(s.get("quality", "High"), QUALITY["High"])
    br = int(min(MAX_BITRATE, max(500, int(float(s["bitrate"])))))
    exact = str(s.get("rate_mode", RATE_MODES[0])).startswith("Exact")
    cap = ["-maxrate", f"{br}k", "-bufsize", f"{br * 2}k"]
    # CPU encoders: average bitrate with some room above it, so the average really lands on the number
    abr = ["-b:v", f"{br}k", "-maxrate", f"{int(br * 1.5)}k", "-bufsize", f"{br * 2}k"]
    if s.get("_fast"):                       # low-cost preview render
        v = ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "28"]
    elif "NVIDIA" in codec:
        h265 = "265" in codec
        if exact:
            rc = ["-rc", "cbr", "-b:v", f"{br}k", "-maxrate", f"{br}k", "-bufsize", f"{br}k"]
        else:
            rc = ["-rc", "vbr", "-cq", str(q["cq"]), "-b:v", "0"] + cap
        v = ["-c:v", "hevc_nvenc" if h265 else "h264_nvenc", "-preset", q["nv"]] + rc + \
            (["-tag:v", "hvc1"] if h265 else ["-profile:v", "high"])
    elif "265" in codec:
        rc = abr if exact else ["-crf", str(q["crf"] + 2)] + cap
        v = ["-c:v", "libx265", "-preset", q["x264"]] + rc + ["-tag:v", "hvc1"]
    else:
        if exact:       # constant bitrate with filler, so even simple scenes really reach the number
            rc = ["-b:v", f"{br}k", "-minrate", f"{br}k", "-maxrate", f"{br}k", "-bufsize", f"{br * 2}k",
                  "-x264-params", "nal-hrd=cbr"]
        else:
            rc = ["-crf", str(q["crf"])] + cap
        v = ["-c:v", "libx264", "-preset", q["x264"]] + rc + ["-profile:v", "high"]
    if str(s["fps"]) != "Original":
        v += ["-r", str(s["fps"])]
    return v + ["-c:a", "aac", "-b:a", s["audio_bitrate"], "-ac", "2"]


def _layer_key(item):
    try:
        return int(item.get("layer", 1))
    except (TypeError, ValueError):
        return 1


def _span(item, t0, d):
    """Timeline item -> (delay, end) inside clip [t0, t0+d], relative to clip start. None = not visible."""
    st = float(item.get("start", 0.0) or 0.0)
    en = float(item.get("end", 0.0) or 0.0)
    if en <= 0:
        en = 1e9
    if en <= t0 or st >= t0 + d:
        return None
    return max(0.0, st - t0), min(en, t0 + d) - t0


def frame_rate(info):
    try:
        n, d = str(info["fps"]).split("/")
        return float(n) / float(d)
    except Exception:
        return 25.0


def pieces_graph(pieces, base, fr, has_audio, fade=0.02):
    """Filter lines that keep only `pieces` ([(abs_start, length), ...]) of the input and join them.
    Picture and sound are cut and joined in the SAME concat filter, so they can never drift apart.
    `base` is the movie time the input was seeked to. Returns (lines, video_label, audio_label, total_seconds)."""
    n = len(pieces)
    rel = []
    for a, d in pieces:
        s = round((a - base) * fr) / fr
        e = round((a - base + d) * fr) / fr
        if e - s < 1.0 / fr:
            e = s + 1.0 / fr
        rel.append((max(0.0, s), max(0.0, s) + (e - s)))
    fl = []
    if n == 1:
        vsrc = ["[0:v:0]"]
        if has_audio:
            fl.append("[0:a:0]aformat=sample_rates=48000:channel_layouts=stereo[as0]")
    else:
        fl.append(f"[0:v:0]split={n}" + "".join(f"[vs{i}]" for i in range(n)))
        vsrc = [f"[vs{i}]" for i in range(n)]
        if has_audio:
            fl.append("[0:a:0]aformat=sample_rates=48000:channel_layouts=stereo,"
                      f"asplit={n}" + "".join(f"[as{i}]" for i in range(n)))
    joined = ""
    total = 0.0
    for i, (s, e) in enumerate(rel):
        L = e - s
        total += L
        fl.append(f"{vsrc[i]}trim=start={s:.5f}:end={e:.5f},setpts=PTS-STARTPTS[vt{i}]")
        joined += f"[vt{i}]"
        if has_audio:
            f = max(0.001, min(fade, L / 2))
            fl.append(f"[as{i}]atrim=start={s:.5f}:end={e:.5f},asetpts=PTS-STARTPTS,"
                      f"afade=t=in:d={f:.3f},afade=t=out:st={max(0.0, L - f):.5f}:d={f:.3f}[at{i}]")
            joined += f"[at{i}]"
    fl.append(f"{joined}concat=n={n}:v=1:a={1 if has_audio else 0}[vcat]" + ("[acat]" if has_audio else ""))
    return fl, "[vcat]", ("[acat]" if has_audio else None), total


_FF_NEW_SYNTAX = None


def filter_complex_args(graph, tmp):
    """The filter graph as ffmpeg arguments. A long graph (hundreds of dialogue pieces) does not fit on the Windows
    command line (32 767 characters: 'filename or extension is too long'), so it is written to a file instead."""
    global _FF_NEW_SYNTAX
    if len(graph) < 12000:
        return ["-filter_complex", graph]
    if _FF_NEW_SYNTAX is None:
        try:
            v = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True, errors="ignore",
                               creationflags=NOWIN).stdout
            m = re.search(r"version\s+n?(\d+)\.", v)
            _FF_NEW_SYNTAX = (int(m.group(1)) >= 7) if m else True       # git builds ("N-12345-g...") are new
        except Exception:
            _FF_NEW_SYNTAX = True
    fd, path = tempfile.mkstemp(prefix="cc_graph_", suffix=".txt")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(graph)
    tmp.append(path)
    return ["-/filter_complex", path] if _FF_NEW_SYNTAX else ["-filter_complex_script", path]


def build_command(movie, start, dur, out, s, info, crop=None, codec=None, preview_t=None, pieces=None):
    """One ffmpeg command for the clip [start, start+dur]. Timeline items are movie-absolute and are
    shifted to clip time here. Order: auto-crop > colour > chroma > aspect/crop > overlays > text > audio.

    pieces=[(abs_start, length), ...]: keep only these pieces of the movie and join them in one pass (dialogue
    cut / Auto Short). The overlay, text and audio items are then relative to the START OF THE JOINED CLIP."""
    s = sanitize(s)
    tmp, inp, fl = [], [], []
    vin, ain, ss_base, read_len = "[0:v:0]", "[0:a:0]", None, 0.0
    if pieces:
        pieces = [(float(a), float(d)) for a, d in pieces if float(d) > 0.02]
        ss_base = max(0.0, pieces[0][0])
        gl, vin, ain, total = pieces_graph(pieces, ss_base, frame_rate(info), info["has_audio"],
                                           float(s.get("_joint_fade", 0.02)))
        fl.extend(gl)
        start, dur = 0.0, total
        read_len = max(a + d for a, d in pieces) - ss_base + 0.3
    st = dict(idx=1, n=0, cur="[v0]")
    fps = info["fps"]
    sw, sh = info["w"], info["h"]
    pre = []
    if crop and s["auto_crop"]:
        m = re.match(r"crop=(\d+):(\d+):", crop)
        if m:
            sw, sh = int(m.group(1)), int(m.group(2))
            pre.append(crop)
    pre.append("setsar=1")
    fl.append(f"{vin}{','.join(pre)}[v0]")

    def newlab():
        st["n"] += 1
        return f"[s{st['n']}]"

    def add(chain):
        lab = newlab()
        fl.append(f"{st['cur']}{chain}{lab}")
        st["cur"] = lab

    def add_input(args):
        i = st["idx"]
        inp.append(args)
        st["idx"] += 1
        return i

    # chroma key (green screen) + new background
    if s["chroma_on"]:
        add(key_chain(s) + ",format=yuva420p")
        fg = st["cur"]
        if s["chroma_bg_type"] == "Color":
            fl.append(f"color=c={hex0x(s['chroma_bg_color'], '1E1E1E')}:s={sw}x{sh}:r={fps}[bg]")
        else:
            i = add_input((["-loop", "1"] if s["chroma_bg_type"] == "Image" else ["-stream_loop", "-1"])
                          + ["-i", s["chroma_bg_file"]])
            fl.append(f"[{i}:v:0]scale={sw}:{sh}:force_original_aspect_ratio=increase,crop={sw}:{sh},"
                      f"setsar=1,fps={fps},format=yuv420p[bg]")
        lab = newlab()
        fl.append(f"[bg]{fg}overlay=0:0:shortest=1:format=auto{lab}")
        st["cur"] = lab

    # colour correction
    cf = color_filters(s, sw)
    if cf:
        add(",".join(cf))

    # 1) IMPORTED MOVIE crop: ratio, zoom and position (this is the picture you see inside the frame)
    cx, cy, cw, ch = source_crop_box(s, sw, sh)
    if (cw, ch) != (sw, sh):
        add(f"crop={cw}:{ch}:{cx}:{cy},setsar=1")
    sw, sh = cw, ch

    # 2) FINAL OUTPUT frame: its own ratio + resolution. The cropped picture is fitted into it.
    OW, OH = out_size(s, sw, sh)
    crop_mode = s["fit_mode"].startswith("Crop")
    pct = 100.0 if crop_mode else float(s["fit_scale"])
    same_ratio = abs(OW / OH - sw / sh) < 0.01
    if same_ratio and pct >= 99.5:
        add(f"scale={OW}:{OH}:flags=lanczos,setsar=1")
    elif crop_mode:
        f = max(OW / sw, OH / sh)
        nw, nh = max(OW, ev_up(sw * f)), max(OH, ev_up(sh * f))
        add(f"scale={nw}:{nh}:flags=lanczos,crop={OW}:{OH}:{(nw - OW) // 2}:{(nh - OH) // 2},setsar=1")
    else:
        # the movie sits inside the frame: size = fit_scale % of the biggest size that fits, position = fit_y %
        k = min(OW / sw, OH / sh) * pct / 100.0
        fw, fh = min(OW, ev(sw * k)), min(OH, ev(sh * k))
        fy = float(s["fit_y"]) / 100.0
        if s["fit_mode"].startswith("Blur"):
            n = st["n"] + 1
            amt = max(2, min(int(s["blur_amount"]), min(OW, OH) // 4))
            fl.append(f"{st['cur']}split=2[ga{n}][gb{n}]")
            fl.append(f"[ga{n}]scale={OW}:{OH}:force_original_aspect_ratio=increase,crop={OW}:{OH},"
                      f"boxblur={amt}:3[gk{n}]")
            fl.append(f"[gb{n}]scale={fw}:{fh}:flags=lanczos[gf{n}]")
            lab = newlab()
            fl.append(f"[gk{n}][gf{n}]overlay=(W-w)/2:(H-h)*{fy:.4f}{lab}")
            st["cur"] = lab
        else:
            col = "black" if s["fit_mode"].startswith("Black") else hex0x(s["bg_color"], "1E1E1E")
            add(f"scale={fw}:{fh}:flags=lanczos,pad={OW}:{OH}:(ow-iw)/2:(oh-ih)*{fy:.4f}:{col},setsar=1")

    # finishing look on the final frame: particles (grain), vignette
    ff = CL.ffmpeg_finish(s)
    if ff:
        add(",".join(ff))

    # overlays (photo / video / GIF) - higher layer is drawn on top
    for ov in sorted(s["overlays"], key=_layer_key):
        ov = {**OVERLAY_DEFAULT, **ov}
        path = ov["path"]
        if not os.path.isfile(path):
            continue
        sp = _span(ov, start, dur)
        if sp is None:
            continue
        ost, oen = sp
        S = float(ov["start"])
        O = float(ov.get("src_offset", 0.0) or 0.0)
        voff = O + max(0.0, start - S)
        isvid = path.lower().endswith(OVERLAY_VIDEO_EXT)
        if isvid:
            args = (["-stream_loop", "-1"] if ov["loop"] else []) + (["-ss", f"{voff:.3f}"] if voff > 0 else [])
            args += ["-i", path]
        else:
            args = ["-loop", "1", "-i", path]
        i = add_input(args)
        steps = []
        if isvid:
            steps.append(f"setpts=PTS-STARTPTS+{ost:.3f}/TB")
        steps += [f"scale={ev(OW * max(1, float(ov['scale'])) / 100)}:-2", "format=yuva420p"]
        if ov["chroma"]:
            steps.append(key_chain(dict(s, chroma_color=ov["key_color"], chroma_sim=ov["key_sim"],
                                        chroma_blend=ov["key_blend"], chroma_spill=ov["key_spill"])))
        if float(ov["opacity"]) < 100:
            steps.append(f"colorchannelmixer=aa={max(0.0, float(ov['opacity'])) / 100:.2f}")
        fl.append(f"[{i}:v:0]{','.join(steps)}[o{i}]")
        mx, my = int(OW * 0.03), int(OH * 0.03)
        px = {"Left": str(mx), "Center": "(W-w)/2", "Right": f"W-w-{mx}"}
        py = {"Top": str(my), "Middle": "(H-h)/2", "Bottom": f"H-h-{my}"}
        if ov["pos"] == "Custom":
            xe, ye = f"W*{float(ov['x'])/100:.4f}", f"H*{float(ov['y'])/100:.4f}"
        elif ov["pos"] == "Center":
            xe, ye = px["Center"], py["Middle"]
        else:
            vert, horz = ov["pos"].split("-")
            xe, ye = px[horz], py[vert]
        lab = newlab()
        fl.append(f"{st['cur']}[o{i}]overlay=x={xe}:y={ye}:enable='between(t,{ost:.3f},{oen:.3f})'"
                  f":eof_action=pass:format=auto{lab}")
        st["cur"] = lab

    # text layers (system fonts)
    for t in sorted(s["texts"], key=_layer_key):
        t = {**TEXT_DEFAULT, **t}
        if not str(t["text"]).strip():
            continue
        sp = _span(t, start, dur)
        if sp is None:
            continue
        tst, ten = sp
        fd, tp = tempfile.mkstemp(suffix=".txt", prefix="vc_")
        os.write(fd, str(t["text"]).strip("\n").encode("utf-8"))
        os.close(fd)
        tmp.append(tp)
        fs = max(8, int(OH * float(t["size"]) / 100))
        sc = OH / 1080.0
        parts = []
        ff = resolve_font(t["font"])
        if ff:
            parts.append(f"fontfile={fe(ff)}")
        parts += [f"textfile={fe(tp)}", f"fontsize={fs}",
                  f"fontcolor={hex0x(t['color'])}@{max(0, min(100, float(t['opacity'])))/100:.2f}"]
        if float(t["outline"]) > 0:
            parts += [f"borderw={max(1, int(round(float(t['outline']) * sc)))}",
                      f"bordercolor={hex0x(t['outline_color'], '000000')}"]
        if t["shadow"]:
            parts += [f"shadowx={max(1, int(3*sc))}", f"shadowy={max(1, int(3*sc))}", "shadowcolor=0x000000@0.6"]
        if t["box"]:
            parts += ["box=1", f"boxcolor={hex0x(t['box_color'], '000000')}@{max(0, min(100, float(t['box_opacity'])))/100:.2f}",
                      f"boxborderw={int(fs*0.3)}"]
        mx, my = int(OW * 0.04), int(OH * 0.05)
        px = {"Left": str(mx), "Center": "(w-text_w)/2", "Right": f"w-text_w-{mx}"}
        py = {"Top": str(my), "Middle": "(h-text_h)/2", "Bottom": f"h-text_h-{my}"}
        if t["pos"] == "Custom":
            xe, ye = f"w*{float(t['x'])/100:.4f}", f"h*{float(t['y'])/100:.4f}"
        elif t["pos"] == "Center":
            xe, ye = px["Center"], py["Middle"]
        else:
            vert, horz = t["pos"].split("-")
            xe, ye = px[horz], py[vert]
        if t.get("hcenter"):
            xe = px["Center"]                       # one-click centring: exactly in the middle of the frame
        if t.get("vcenter"):
            ye = py["Middle"]
        parts += [f"x={xe}", f"y={ye}", f"enable='between(t,{tst:.3f},{ten:.3f})'"]
        add("drawtext=" + ":".join(parts))

    fl.append(f"{st['cur']}format=yuv420p[vout]")

    # audio: original track (optional) + any number of audio layers, mixed
    ff = max(0.005, float(s.get("fade_sec", 0.15)))
    fades = f"afade=t=in:d={ff:.3f},afade=t=out:st={max(0.0, dur - ff):.3f}:d={ff:.3f}"
    amap = ["-an"]
    if preview_t is None:
        auds = []
        for a in sorted(s["audios"], key=_layer_key):
            a = {**AUDIO_DEFAULT, **a}
            if not os.path.isfile(a["path"]):
                continue
            sp = _span(a, start, dur)
            if sp is None:
                continue
            ast, aen = sp
            off = float(a.get("src_offset", 0.0) or 0.0) + max(0.0, start - float(a["start"]))
            auds.append((a, ast, off, aen - ast))
        replace = str(s["music_mode"]).startswith("Replace") and bool(auds)
        labels = []
        if info["has_audio"] and not replace:
            ov_vol = max(0.0, float(s["orig_volume"])) / 100.0
            clean = "highpass=f=70,afftdn=nf=-25," if s.get("_denoise") else ""
            fl.append(f"{ain}aformat=sample_rates=48000:channel_layouts=stereo,{clean}volume={ov_vol:.3f}[oa]")
            labels.append("[oa]")
        for k, (a, ast, off, L) in enumerate(auds):
            i = add_input((["-stream_loop", "-1"] if a["loop"] else []) + ["-i", a["path"]])
            vol = max(0.0, float(a["volume"])) / 100.0
            fl.append(f"[{i}:a:0]aformat=sample_rates=48000:channel_layouts=stereo,"
                      f"atrim=start={off:.3f}:duration={L:.3f},asetpts=PTS-STARTPTS,"
                      f"adelay={int(round(ast * 1000))}:all=1,volume={vol:.3f}[ax{k}]")
            labels.append(f"[ax{k}]")
        if labels:
            if len(labels) == 1:
                fl.append(f"{labels[0]}atrim=0:{dur:.3f},{fades}[aout]")
            else:
                has_norm = amix_has_normalize()
                norm = ":normalize=0" if has_norm else ""
                boost = "" if has_norm else f",volume={len(labels)}"
                fl.append("".join(labels) + f"amix=inputs={len(labels)}:duration=longest:dropout_transition=0"
                          f"{norm}{boost},atrim=0:{dur:.3f},{fades}[aout]")
            amap = ["-map", "[aout]"]

    if ss_base is not None:
        cmd = ["ffmpeg", "-nostdin", "-y", "-v", "error", "-ss", f"{ss_base:.3f}", "-t", f"{read_len:.3f}", "-i", movie]
    else:
        cmd = ["ffmpeg", "-nostdin", "-y", "-v", "error", "-ss", f"{start:.2f}", "-t", f"{dur:.2f}", "-i", movie]
    for a in inp:
        cmd += a
    cmd += filter_complex_args(";".join(fl), tmp) + ["-map", "[vout]"]
    if preview_t is not None:
        cmd += ["-an", "-ss", f"{preview_t:.2f}", "-frames:v", "1", "-q:v", "3", out]
    else:
        cmd += amap + ["-t", f"{dur:.3f}"] + encoder_args(s, codec) + ["-movflags", "+faststart", out]
    return cmd, tmp


def render_preview(movie, s, movie_pos, part_t, out_jpg):
    """Render one frame through the full edit pipeline (colour, crop, overlays, text, chroma)."""
    info = probe_info(movie)
    crop = detect_crop(movie, info["duration"]) if s.get("auto_crop") else None
    pos = movie_pos if movie_pos is not None else info["duration"] * 0.3
    pos = max(0.0, min(pos, info["duration"] - part_t - 2))
    cmd, tmp = build_command(movie, pos, part_t + 2, out_jpg, s, info, crop, preview_t=part_t)
    try:
        r = subprocess.run(cmd, capture_output=True, creationflags=NOWIN, timeout=180)
        if r.returncode != 0 or not os.path.isfile(out_jpg):
            raise RuntimeError(r.stderr.decode(errors="ignore")[-600:] or "Preview fail hua.")
    finally:
        for t in tmp:
            try: os.remove(t)
            except OSError: pass
    return out_jpg


# ---------------------------------------------------------------- runners
class Runner:
    def __init__(self, settings, log, progress, on_clip):
        self.s = sanitize(settings)
        self.log, self.progress, self.on_clip = log, progress, on_clip
        self.stop_flag = False
        self.proc = None

    def stop(self):
        self.stop_flag = True
        if self.proc and self.proc.poll() is None:
            self.proc.kill()

    def cut(self, movie, start, dur, out, info, crop, settings=None, pieces=None):
        S = settings or self.s

        def run(codec):
            cmd, tmp = build_command(movie, start, dur, out, S, info, crop, codec, pieces=pieces)
            try:
                self.proc = subprocess.Popen(cmd, stderr=subprocess.PIPE, creationflags=NOWIN)
                err = self.proc.communicate()[1]
                return self.proc.returncode == 0, err.decode(errors="ignore")
            finally:
                for t in tmp:
                    try: os.remove(t)
                    except OSError: pass
        ok, err = run(S["codec"])
        if not ok and not self.stop_flag and "NVIDIA" in S["codec"]:
            self.log("GPU encoder failed, retrying with CPU encoder (libx264)...")
            ok, err = run("H.264 (CPU)")
        if not ok and not self.stop_flag:
            self.log("ffmpeg error: " + err[-600:])
        return ok

    @staticmethod
    def safe_name(movie):
        return re.sub(r"[^\w\-]+", "_", os.path.splitext(os.path.basename(movie))[0])[:50]


def make_ranges(a, b, part, min_last):
    """Split [a, b] into (start, length) pieces of `part` seconds (0 = one piece).
    A final piece shorter than min_last is merged into the previous part (no footage is lost).
    Returns (ranges, merged_seconds)."""
    part = float(part) or max(1.0, b - a)
    pieces, t = [], a
    while t < b - 0.5:
        d = min(part, b - t)
        pieces.append([t, d])
        t += part
    merged = 0.0
    threshold = min(float(min_last), part)
    if len(pieces) > 1 and pieces[-1][1] < threshold - 1e-6:
        merged = pieces[-1][1]
        pieces[-2][1] += merged
        pieces.pop()
    return [(t0, d) for t0, d in pieces if d > 0.5], merged


class SimpleEngine(Runner):
    """No AI: cut the whole movie into equal parts and apply the edit settings to each part."""

    def process(self, movie):
        s = self.s
        info = probe_info(movie)
        dur = info["duration"]
        out_dir = os.path.join(OUTPUT_DIR, self.safe_name(movie) + "_parts")
        os.makedirs(out_dir, exist_ok=True)
        self.log(f"Movie: {os.path.basename(movie)}  ({dur/60:.1f} min)")
        a = max(0.0, s["trim_start"] * 60)
        b = min(dur, s["trim_end"] * 60) if s["trim_end"] > 0 else dur
        starts, merged = make_ranges(a, b, s["part_len"], s["min_last"])
        if merged:
            self.log(f"The last {merged:.1f}s piece (shorter than {s['min_last']}s) was merged into the previous part.")
        self.log(f"{len(starts)} parts of ~{float(s['part_len']) or b - a:.0f}s will be edited.")
        return self.run_parts(movie, starts, info, None, out_dir)

    def run_parts(self, movie, ranges, info=None, crop=None, out_dir=None):
        """ranges: list of (start_sec, length_sec) in movie time. Exports each one with current settings."""
        s = self.s
        info = info or probe_info(movie)
        if crop is None and s["auto_crop"]:
            crop = detect_crop(movie, info["duration"])
            if crop:
                self.log(f"Black bars detection: {crop}")
        out_dir = out_dir or os.path.join(OUTPUT_DIR, self.safe_name(movie) + "_parts")
        os.makedirs(out_dir, exist_ok=True)
        total, done = len(ranges), 0
        for i, (t0, d) in enumerate(ranges, 1):
            if self.stop_flag:
                break
            self.progress((i - 1) / max(1, total), f"Editing part {i}/{total}")
            mm, ss = divmod(int(t0), 60)
            fname = f"part_{i:03d}_at{mm}m{ss:02d}s.mp4"
            path = os.path.join(out_dir, fname)
            self.log(f"Exporting {fname} ...")
            if self.cut(movie, t0, d, path, info, crop):
                done += 1
                self.on_clip(dict(path=path, n=i, start=t0, end=t0 + d, score=None,
                                  category="Part", text=f"Part {i} of {total}", reason=""))
            else:
                self.log(f"Part {i} failed (see the error above).")
        self.progress(1.0 if not self.stop_flag else done / max(1, total),
                      "Stopped." if self.stop_flag else f"Done - {done}/{total} parts exported.")
        self.log(f"Finished. {done}/{total} parts in: {out_dir}")
        return done


class AIEngine(Runner):
    CHUNK, OVER = 600, 60

    def __init__(self, *a):
        super().__init__(*a)
        self.model, self.device = None, "cuda"
        self.detect_only = False      # True: only report candidate clips, the caller exports them

    def _load_model(self, force_cpu=False):
        from faster_whisper import WhisperModel
        has_cuda_dlls = setup_cuda_paths()      # the portable version ships without the 700 MB NVIDIA libraries: CPU then
        name = self.s["whisper_model"]
        if not force_cpu and has_cuda_dlls:
            try:
                self.model = WhisperModel(whisper_source(name), device="cuda", compute_type="int8_float16")
                self.device = "cuda"
                self.log(f"Whisper '{name}' loaded on GPU (CUDA).")
                return
            except Exception as e:
                self.log(f"GPU not available for Whisper ({e}). Using CPU (slower).")
        self.model = WhisperModel(whisper_source(name), device="cpu", compute_type="int8")
        self.device = "cpu"

    def _transcribe(self, audio, offset):
        lang = None if self.s["language"] == "auto" else self.s["language"]
        def run():
            segs, _ = self.model.transcribe(audio, language=lang, vad_filter=True, beam_size=1,
                                            condition_on_previous_text=False)
            return [SC.Seg(offset + x.start, offset + x.end, x.text.strip()) for x in segs if x.text.strip()]
        try:
            return run()
        except Exception as e:
            if self.device == "cuda":
                self.log(f"GPU transcription failed ({e}); switching to CPU.")
                self._load_model(force_cpu=True)
                return run()
            raise

    def process(self, movie):
        s = self.s
        out_dir = os.path.join(OUTPUT_DIR, self.safe_name(movie) + "_AI")
        os.makedirs(out_dir, exist_ok=True)
        csv_path = os.path.join(out_dir, "clips_log.csv")
        info = probe_info(movie)
        dur = info["duration"]
        self.log(f"Movie: {os.path.basename(movie)}  ({dur/60:.1f} min)")
        crop = detect_crop(movie, dur) if s["auto_crop"] else None
        if crop:
            self.log(f"Black bars detection: {crop}")
        self.log("Loading AI speech model (first time it downloads ~0.5-1.5 GB)...")
        self._load_model()
        taken, count, t, ci = [], 0, 0.0, 0
        n_chunks = max(1, math.ceil(dur / self.CHUNK))
        min_d, max_d = float(s["min_dur"]), float(s["max_dur"])
        per_chunk, max_total = int(s["max_per_chunk"]), int(s["max_total"])
        while t < dur - 5 and not self.stop_flag:
            ci += 1
            last = t + self.CHUNK >= dur
            length = min(self.CHUNK + self.OVER, dur - t)
            self.progress(t / dur, f"Analysing {t/60:.0f}-{(t+length)/60:.0f} min  (part {ci}/{n_chunks})")
            audio = read_audio(movie, t, length)
            if len(audio) > 16000 * 5:
                segs = self._transcribe(audio, t)
                rms = SC.rms_frames(audio)
                med = float(np.median(rms[rms > 1e-4])) if np.any(rms > 1e-4) else 1e-3
                scored = []
                for i, j in SC.make_candidates(segs, min_d, max_d):
                    if not last and segs[i].start >= t + self.CHUNK:
                        continue
                    scored.append(SC.score_window(segs, i, j, t, rms, med, s["focus"]))
                scored.sort(key=lambda c: -c["score"])
                pool, rng = [], []
                limit = per_chunk * 2 if s["use_llm"] else per_chunk
                for c in scored:
                    if c["score"] < s["min_score"] - (10 if s["use_llm"] else 0):
                        break
                    if SC.overlaps(c["start"], c["end"], taken + rng):
                        continue
                    pool.append(c); rng.append((c["start"], c["end"]))
                    if len(pool) >= limit:
                        break
                if s["use_llm"] and pool:
                    for c in pool:
                        try:
                            ls, why = SC.llm_score(c["text"], s["llm_model"], s["focus"])
                            c["score"] = 0.5 * c["score"] + 0.5 * ls
                            c["reason"] += f" | AI: {why}"
                        except Exception as e:
                            self.log(f"Ollama skipped ({e})"); break
                    pool = [c for c in sorted(pool, key=lambda c: -c["score"]) if c["score"] >= s["min_score"]]
                for c in pool[:per_chunk]:
                    if self.stop_flag or (max_total and count >= max_total):
                        break
                    st = max(0.0, c["start"] - 0.3)
                    d = min(c["end"] + 0.5 - st, max_d)
                    count += 1
                    mm, ss = divmod(int(st), 60)
                    fname = f"clip_{count:03d}_{c['category']}_score{int(c['score'])}_at{mm}m{ss:02d}s.mp4"
                    path = os.path.join(out_dir, fname)
                    if self.detect_only:
                        count_det = len(taken)
                        taken.append((st, st + d))
                        self.on_clip(dict(path=None, n=count_det + 1, start=st, end=st + d, score=c["score"],
                                          category=c["category"], text=c["text"], reason=c["reason"]))
                        continue
                    self.log(f"Exporting {fname} ...")
                    if self.cut(movie, st, d, path, info, crop):
                        taken.append((st, st + d))
                        new = not os.path.exists(csv_path)
                        with open(csv_path, "a", newline="", encoding="utf-8-sig") as f:
                            w = csv.writer(f)
                            if new:
                                w.writerow(["file", "start_sec", "end_sec", "score", "category", "reason", "text"])
                            w.writerow([fname, f"{st:.1f}", f"{st+d:.1f}", f"{c['score']:.0f}",
                                        c["category"], c["reason"], c["text"]])
                        self.on_clip(dict(path=path, n=count, start=st, end=st + d, score=c["score"],
                                          category=c["category"], text=c["text"], reason=c["reason"]))
                    else:
                        count -= 1
                if max_total and count >= max_total:
                    self.log("Reached max total clips."); break
            t += self.CHUNK
        self.progress(1.0 if not self.stop_flag else t / dur,
                      "Stopped." if self.stop_flag else f"Done - {count} clips exported.")
        self.log(f"Finished. {count} clips in: {out_dir}")
        return count


Engine = AIEngine


# ============================================================ auto silence cut
SIL_RE = re.compile(r"silence_(start|end):\s*(-?[\d.]+)")


def detect_silence(path, noise_db=-35.0, min_sec=2.0, dur=None, windows=None):
    """Scan the movie's audio. Returns [(start, end), ...] of silent stretches >= min_sec long.
    windows=[(a, b), ...]: scan ONLY these time ranges (jumps straight to them - a 2-hour movie is not read at all)."""
    if windows is not None:
        res = []
        for a, b in windows:
            res += [(x + a, y + a) for x, y in _detect_silence(path, noise_db, min_sec, b - a, start=a, length=b - a)]
        return res
    return _detect_silence(path, noise_db, min_sec, dur)


def _detect_silence(path, noise_db, min_sec, dur, start=None, length=None):
    pre = ["-ss", f"{start:.3f}", "-t", f"{length:.3f}"] if start is not None else []
    cmd = ["ffmpeg", "-nostdin", "-hide_banner", "-v", "info", *pre, "-i", path, "-vn",
           "-af", f"aresample=8000,aformat=channel_layouts=mono,"
                  f"silencedetect=noise={float(noise_db):g}dB:d={float(min_sec):g}", "-f", "null", "-"]
    r = subprocess.run(cmd, capture_output=True, text=True, errors="ignore", creationflags=NOWIN, timeout=7200)
    res, cur = [], None
    for m in SIL_RE.finditer(r.stderr or ""):
        kind, val = m.group(1), float(m.group(2))
        if kind == "start":
            cur = max(0.0, val)
        elif cur is not None:
            res.append((cur, val))
            cur = None
    if cur is not None:                      # silence runs until the end of the file
        res.append((cur, dur if dur else cur))
    return res


def silence_keep_ranges(silences, a, b, pad=0.25, min_keep=0.3, flags=None):
    """Silent stretches (only those with flags[i] True) are cut, keeping `pad` seconds of
    silence on both sides so words are not clipped. Returns [(start, length), ...] to keep inside [a, b]."""
    cuts = []
    for i, (s, e) in enumerate(silences):
        if flags is not None and not flags[i]:
            continue
        cs, ce = s + pad, e - pad
        if ce - cs > 0.05:
            cuts.append((max(cs, a), min(ce, b)))
    keep, t = [], a
    for cs, ce in sorted(cuts):
        if ce <= cs:
            continue
        if cs - t >= min_keep:
            keep.append((t, cs - t))
        t = max(t, ce)
    if b - t >= min_keep:
        keep.append((t, b - t))
    return keep


class SilenceEngine(SimpleEngine):
    """Exports each kept piece with the current edit settings, then joins them into one clean file."""

    def process(self, movie, keeps):
        info = probe_info(movie)
        name = self.safe_name(movie)
        base = os.path.join(OUTPUT_DIR, name + "_silencecut")
        seg_dir = os.path.join(base, "segments")
        shutil.rmtree(seg_dir, ignore_errors=True)
        os.makedirs(seg_dir, exist_ok=True)
        if not keeps:
            self.log("No piece is left to keep (all silence?). Change the padding or threshold.")
            return 0
        kept_total = sum(d for _, d in keeps)
        self.log(f"{len(keeps)} pieces rakhenge, total ~{kept_total:.1f}s (silence hatakar).")
        final_cb = self.on_clip
        self.on_clip = lambda c: None           # intermediate pieces are deleted below; don't show them
        try:
            done = self.run_parts(movie, keeps, info, None, seg_dir)
        finally:
            self.on_clip = final_cb
        if self.stop_flag:
            return done
        if done < len(keeps):
            self.log(f"{len(keeps) - done} piece(s) failed, so the final file was not created. See the error above.")
            return done
        final = os.path.join(base, f"{name}_clean.mp4")
        listf = os.path.join(seg_dir, "_list.txt")
        files = sorted(f for f in os.listdir(seg_dir) if f.lower().endswith(".mp4"))
        with open(listf, "w", encoding="utf-8") as f:
            for fn in files:
                p = os.path.join(seg_dir, fn).replace("\\", "/").replace("'", "'\\''")
                f.write(f"file '{p}'\n")
        self.progress(0.99, "Joining the pieces...")
        cmd = ["ffmpeg", "-nostdin", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", listf,
               "-c", "copy", "-movflags", "+faststart", final]
        r = subprocess.run(cmd, capture_output=True, creationflags=NOWIN)
        if r.returncode != 0 or not os.path.isfile(final):
            self.log("Error while joining the pieces: " + r.stderr.decode(errors="ignore")[-400:])
            return done
        shutil.rmtree(seg_dir, ignore_errors=True)
        self.log(f"Clean video ready: {final}")
        self.on_clip(dict(path=final, n=1, start=keeps[0][0], end=keeps[-1][0] + keeps[-1][1], score=None,
                          category="Clean", text=f"Silence hata di - {len(keeps)} pieces joined", reason=""))
        self.progress(1.0, "Done - clean video ban gayi.")
        return done


# ============================================================ Studio export (Simple Edit + AI Clipping)
def concat_files(paths, out):
    """Join already-encoded pieces with the concat demuxer (stream copy, no re-encode)."""
    listf = os.path.join(os.path.dirname(os.path.abspath(paths[0])), f"_list_{os.path.basename(out)}.txt")
    with open(listf, "w", encoding="utf-8") as f:
        for p in paths:
            q = os.path.abspath(p).replace("\\", "/").replace("'", "'\\''")
            f.write(f"file '{q}'\n")
    cmd = ["ffmpeg", "-nostdin", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", listf,
           "-c", "copy", "-movflags", "+faststart", out]
    r = subprocess.run(cmd, capture_output=True, creationflags=NOWIN)
    ok = r.returncode == 0 and os.path.isfile(out)
    return ok, r.stderr.decode(errors="ignore")[-400:]


class StudioEngine(Runner):
    """plans: [{file, start, end, label, pieces: [(t0, d), ...], overlays, texts}]
    Each plan becomes one output file.
    - Normal / silence-cut plans: several pieces are exported one by one and joined at the end.
    - plan["single_pass"] = True (dialogue cut): picture and sound are cut and joined in ONE ffmpeg pass,
      so they stay in sync; overlay / text times are relative to the start of the joined clip.
    prepare(plan) -> plan or None: optional hook called right before each plan is rendered (used by the
    dialogue cut to analyse that part only), so the first clip is ready while the next one is still waiting."""

    def process(self, movie, plans, out_dir, prepare=None):
        info = probe_info(movie)
        crop = detect_crop(movie, info["duration"]) if self.s["auto_crop"] else None
        os.makedirs(out_dir, exist_ok=True)
        total, done = len(plans), 0
        for i, p in enumerate(plans, 1):
            if self.stop_flag:
                break
            self.progress((i - 1) / max(1, total), f"Part {i}/{total}: {p['file']}")
            if prepare:
                try:
                    p = prepare(p)
                except Exception as e:
                    self.log(f"Part {i}: analysis failed ({str(e)[:200]}) - skipped.")
                    p = None
                if not p:
                    self.log(f"Part {i}: no dialogue found - skipped.")
                    continue
            final = os.path.join(out_dir, p["file"])
            pieces = [pc for pc in p["pieces"] if pc[1] > 0.3]
            if not pieces:
                self.log(f"Part {i}: nothing is left after removing silence - skipped.")
                continue
            S = dict(self.s, overlays=p["overlays"], texts=p["texts"])
            if p.get("single_pass"):
                self.log(f"Part {i}: cutting {len(pieces)} dialogue piece(s) into one clip ...")
                ok = bool(self.cut(movie, pieces[0][0], 0, final, info, crop, S, pieces=pieces))
            elif len(pieces) == 1:
                ok = bool(self.cut(movie, pieces[0][0], pieces[0][1], final, info, crop, S))
            else:
                seg = os.path.join(out_dir, f"_seg{i:03d}")
                shutil.rmtree(seg, ignore_errors=True)
                os.makedirs(seg)
                ok, segs = True, []
                for k, (t0, d) in enumerate(pieces, 1):
                    sp = os.path.join(seg, f"p{k:03d}.mp4")
                    self.log(f"Part {i}: piece {k}/{len(pieces)} ...")
                    ok = bool(self.cut(movie, t0, d, sp, info, crop, S)) and ok
                    segs.append(sp)
                    if self.stop_flag:
                        break
                if ok and not self.stop_flag:
                    ok, err = concat_files(segs, final)
                    if not ok:
                        self.log("Join error: " + err)
                shutil.rmtree(seg, ignore_errors=True)
            if self.stop_flag:
                break
            if ok:
                done += 1
                self.on_clip(dict(path=final, n=i, start=p["start"], end=p["end"], score=None,
                                  category="Clip", text=p.get("label", ""), reason=""))
            else:
                self.log(f"Part {i} failed (see the error above).")
        self.progress(1.0 if not self.stop_flag else done / max(1, total),
                      "Stopped." if self.stop_flag else f"Done - {done}/{total} parts exported.")
        self.log(f"Finished. {done}/{total} parts in: {out_dir}")
        return done
