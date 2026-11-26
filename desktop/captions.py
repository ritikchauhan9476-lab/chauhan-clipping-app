"""Captions from a subtitle file (.srt / .vtt) or from speech: word-by-word or line-by-line, in many styles
(bold pop, karaoke, neon glow, boxes, typewriter, cinema ...). Used by every editing section (Captions tab), by
Auto Short and by Viral Clips. The words keep their movie times, so they stay in sync in every part / short,
also when silence or dialogue pieces are cut out."""
import os
import re
import subprocess

import engine as E

# 'active' = colour of the word being spoken ("" = no highlight); per = words on screen at a time
STYLES = {
    "Bounce (white, cyan word)": dict(font="Arial Black", size=6.0, color="#FFFFFF", active="#00F0FF", outline=7,
                                      upper=True, per=3, anim_loop="Bounce"),
    "Hype (big, yellow word)": dict(font="Impact", size=7.6, color="#FFFFFF", active="#FFD400", outline=8,
                                    upper=True, per=2, anim_in="Pop", anim_in_dur=0.12),
    "Pop word (one at a time)": dict(font="Arial Black", size=8.0, color="#FFFFFF", active="#FFD400", outline=9,
                                     upper=True, per=1, anim_in="Pop", anim_in_dur=0.10),
    "Karaoke (green word)": dict(font="Arial Black", size=6.2, color="#FFFFFF", active="#3CFF64", outline=6,
                                 upper=True, per=3),
    "Beast (yellow + red word)": dict(font="Impact", size=8.0, color="#FFE600", active="#FF2D2D", outline=10,
                                      upper=True, per=2, anim_in="Pop", anim_in_dur=0.12),
    "Neon glow": dict(font="Arial Black", size=6.0, color="#FFFFFF", active="#FF4FD8", outline=0, glow=True,
                      glow_color="#00E5FF", glow_size=10.0, upper=True, per=3),
    "Bubble (white box)": dict(font="Arial", bold=True, size=5.0, color="#111111", active="#E1306C", outline=0,
                               box=True, box_color="#FFFFFF", box_opacity=100, box_pad=30, upper=False, per=4),
    "Black box (TikTok)": dict(font="Arial", bold=True, size=5.0, color="#FFFFFF", active="#FFD400", outline=0,
                               box=True, box_color="#000000", box_opacity=75, box_pad=28, upper=False, per=4),
    "Shadow drop": dict(font="Arial Black", size=6.0, color="#FFFFFF", active="#FF8A00", outline=0, shadow=True,
                        shadow_dist=6.0, shadow_opacity=90, upper=True, per=3),
    "Slide up": dict(font="Arial", bold=True, size=5.4, color="#FFFFFF", active="#7CFF4F", outline=5, upper=False,
                     per=3, anim_in="Slide up", anim_in_dur=0.2),
    "Pulse (on the beat)": dict(font="Impact", size=6.8, color="#FFFFFF", active="#FF3B3B", outline=7, upper=True,
                                per=2, anim_loop="Pulse"),
    "Comic": dict(font="Comic Sans MS", bold=True, size=6.0, color="#FFFFFF", active="#00C2FF", outline=7,
                  upper=False, per=3, anim_loop="Bounce"),
    "Gold luxury": dict(font="Georgia", bold=True, size=5.6, color="#F7D774", active="#FFFFFF", outline=2,
                        outline_color="#3A2A00", shadow=True, upper=False, per=4),
    "Fade in words": dict(font="Segoe UI", bold=True, size=5.0, color="#FFFFFF", active="", outline=4, upper=False,
                          per=4, anim_in="Fade", anim_in_dur=0.25),
    "Typewriter": dict(font="Courier New", bold=True, size=4.8, color="#FFFFFF", active="", outline=3, upper=False,
                       per=6, anim_in="Typewriter", anim_in_dur=0.4),
    "Minimal lowercase": dict(font="Segoe UI", size=4.6, color="#FFFFFF", active="", outline=0, shadow=True,
                              case="lowercase", upper=False, per=5),
    "Clean (small, blue word)": dict(font="Segoe UI", bold=True, size=4.6, color="#FFFFFF", active="#6BD7FF",
                                     outline=5, upper=False, per=4),
    "Editorial": dict(font="Georgia", italic=True, size=4.8, color="#FFFFFF", active="#FFB4A2", outline=0,
                      shadow=True, upper=False, per=5),
    "Street": dict(font="Impact", size=6.6, color="#FFFFFF", active="#39FF14", outline=6, shadow=True, upper=True,
                   per=2, anim_loop="Shake"),
    "News": dict(font="Arial", bold=True, size=4.2, color="#FFFFFF", active="#FFD400", outline=0, box=True,
                 box_color="#C8102E", box_opacity=90, box_pad=25, upper=False, per=6),
    "Hindi (Devanagari)": dict(font="Nirmala UI", bold=True, size=5.6, color="#FFFFFF", active="#FFD400", outline=6,
                               upper=False, per=3),
    "Hindi neon": dict(font="Nirmala UI", bold=True, size=5.8, color="#FFFFFF", active="#FFE600", outline=0,
                       glow=True, glow_color="#FF2BD6", glow_size=10.0, upper=False, per=3),
    "Hindi bubble": dict(font="Nirmala UI", bold=True, size=5.2, color="#111111", active="#D6005C", outline=0,
                         box=True, box_color="#FFFFFF", box_opacity=100, box_pad=30, upper=False, per=4),
    "Cinema": dict(font="Times New Roman", size=4.0, color="#F5F5F0", active="", outline=0, shadow=True,
                   upper=False, per=8),
    "Classic subtitles": dict(font="Arial", size=4.4, color="#FFFFFF", active="", outline=3, upper=False, per=8),
}
MODES = {
    "word": "Word by word (the spoken word lights up)",
    "line": "Line by line (exactly as in the subtitle file)",
}
MODE_BY_LABEL = {v: k for k, v in MODES.items()}
POSITIONS = {"Bottom": 80.0, "Lower third": 72.0, "Lower middle": 62.0, "Middle": 48.0, "Top": 16.0}
CASES = ("Like the style", "UPPERCASE", "lowercase", "As written")

DEFAULT = dict(on=False, file="", style="Bounce (white, cyan word)", mode="word", per=0, size=100.0, pos="Lower third",
               y=None, shift=0.0, active="", case="Like the style")


# ------------------------------------------------------------------ reading subtitle files
TS = re.compile(r"(?:(\d+):)?(\d\d):(\d\d)[.,](\d{1,3})")


def _ts(s):
    m = TS.search(s)
    if not m:
        return None
    h = int(m.group(1) or 0)
    return h * 3600 + int(m.group(2)) * 60 + int(m.group(3)) + int(m.group(4).ljust(3, "0")) / 1000


def _clean(text):
    text = re.sub(r"<[^>]+>", "", text)                 # <i>, <b>, <font ...>, <c>
    text = re.sub(r"\{\\[^}]*\}", "", text)              # {\an8} ASS tags
    text = text.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    return re.sub(r"\s+", " ", text).strip()


def parse_ass(raw):
    cues = []
    fmt = None
    for line in raw.split("\n"):
        if line.startswith("Format:") and fmt is None and "Text" in line:
            fmt = [x.strip().lower() for x in line[7:].split(",")]
        elif line.startswith("Dialogue:") and fmt:
            parts = line[9:].split(",", len(fmt) - 1)
            d = dict(zip(fmt, parts))
            a, b = _ts(d.get("start", "")), _ts(d.get("end", ""))
            text = _clean(d.get("text", "").replace("\\N", " ").replace("\\n", " "))
            if a is not None and b is not None and text:
                cues.append((a, b, text))
    return cues


def parse(path):
    """A subtitle file -> (words [(word, start, end)], cues [(start, end, line)]). SRT, VTT (also YouTube's
    word-timed automatic captions) and ASS / SSA."""
    import viral as V
    raw = open(path, "rb").read()
    for enc in ("utf-8-sig", "utf-16", "cp1252"):
        try:
            txt = raw.decode(enc)
            if enc == "utf-16" and "-->" not in txt and "Dialogue:" not in txt:
                continue
            break
        except UnicodeDecodeError:
            continue
    else:
        txt = raw.decode("utf-8", "replace")
    txt = txt.replace("\r", "")
    if path.lower().endswith((".ass", ".ssa")) or "[Events]" in txt:
        cues = parse_ass(txt)
        return V.words_from_segments(cues), cues
    tmp = path
    if raw[:3] == b"\xef\xbb\xbf" or "\ufeff" in txt[:2]:
        txt = txt.lstrip("\ufeff")
    # cues (lines as written)
    cues, seen = [], ""
    for bl in re.split(r"\n\s*\n", txt):
        lines = [x for x in bl.split("\n") if x.strip()]
        tl = next((i for i, x in enumerate(lines) if "-->" in x), None)
        if tl is None:
            continue
        a, b = (_ts(p) for p in lines[tl].split("-->")[:2])
        if a is None or b is None or b - a < 0.05:
            continue
        text = _clean(" ".join(lines[tl + 1:]))
        if not text or text == seen:
            continue
        if seen and text.startswith(seen):                # YouTube 'rolling' lines repeat the line before
            text = text[len(seen):].strip()
        seen = _clean(" ".join(lines[tl + 1:]))
        if text:
            cues.append((a, b, text))
    words = V.parse_subtitles(tmp) if "<c>" in txt or re.search(r"<\d\d:\d\d", txt) else V.words_from_segments(cues)
    if not cues and words:
        cues = V.segments_from_words(words)
    return words, cues


def find_files(movie):
    """Subtitle files next to the movie: 'movie.srt', 'movie.en.srt', 'movie.hi.vtt' ..."""
    if not movie:
        return []
    base = os.path.splitext(movie)[0]
    d = os.path.dirname(movie) or "."
    out = []
    try:
        for f in os.listdir(d):
            p = os.path.join(d, f)
            if (p == base + os.path.splitext(f)[1] or p.startswith(base + ".")) and \
                    f.lower().endswith((".srt", ".vtt", ".ass", ".ssa")):
                out.append(p)
    except OSError:
        pass
    return sorted(out, key=lambda p: (0 if ".hi" in p else 1 if ".en" in p else 2, len(p)))


def subtitle_streams(movie):
    """Subtitle tracks inside the movie (MKV / MP4): [{index, lang, title, codec}] (index = 0:s:N)."""
    import json
    try:
        out = subprocess.check_output(["ffprobe", "-v", "error", "-select_streams", "s", "-show_entries",
                                       "stream=index,codec_name:stream_tags=language,title", "-of", "json", movie],
                                      creationflags=E.NOWIN)
        st = json.loads(out.decode("utf-8", "ignore")).get("streams", [])
    except Exception:
        return []
    res = []
    for n, s in enumerate(st):
        tags = s.get("tags") or {}
        res.append(dict(n=n, lang=tags.get("language", ""), title=tags.get("title", ""), codec=s.get("codec_name", "")))
    return res


def extract_stream(movie, n, out_path):
    """Saves subtitle track 0:s:n of the movie as .srt (text subtitles only - pictures like PGS cannot)."""
    r = subprocess.run(["ffmpeg", "-nostdin", "-y", "-v", "error", "-i", movie, "-map", f"0:s:{n}", "-c:s", "srt",
                        out_path], capture_output=True, creationflags=E.NOWIN)
    if r.returncode != 0 or not os.path.isfile(out_path) or os.path.getsize(out_path) < 10:
        raise RuntimeError("this subtitle track could not be saved as text (picture subtitles like PGS / DVD "
                           "cannot be turned into text): " + r.stderr.decode(errors="ignore")[-200:])
    return out_path


def write_srt(cues, path):
    def ts(x):
        x = max(0.0, x)
        h, r = divmod(x, 3600)
        m, s = divmod(r, 60)
        return f"{int(h):02d}:{int(m):02d}:{int(s):02d},{int(round((s % 1) * 1000)) % 1000:03d}"
    with open(path, "w", encoding="utf-8") as f:
        for i, (a, b, t) in enumerate(cues, 1):
            f.write(f"{i}\n{ts(a)} --> {ts(b)}\n{t}\n\n")
    return path


# ------------------------------------------------------------------ turning words into caption pages
def style_of(cap):
    st = dict(STYLES.get(cap.get("style")) or next(iter(STYLES.values())))
    if cap.get("per"):
        st["per"] = int(cap["per"])
    if cap.get("active"):
        st["active"] = cap["active"]
    c = cap.get("case") or "Like the style"
    if c == "UPPERCASE":
        st["upper"], st["case"] = True, "As typed"
    elif c == "lowercase":
        st["upper"], st["case"] = False, "lowercase"
    elif c == "As written":
        st["upper"], st["case"] = False, "As typed"
    st["size"] = float(st.get("size", 6)) * float(cap.get("size") or 100) / 100.0
    return st


def pos_y(cap):
    if cap.get("y") not in (None, ""):
        return float(cap["y"])
    return POSITIONS.get(cap.get("pos"), 72.0)


def events(cap, a, b, map_t=None):
    """Caption pages of one clip (movie a..b): [(t0, t1, text)] in clip seconds (map_t: movie time -> clip time,
    for clips made of pieces)."""
    import viral as V
    st = style_of(cap)
    shift = float(cap.get("shift") or 0.0)
    if cap.get("mode") == "line":
        out = []
        for s, e, text in cap.get("cues") or []:
            s, e = s + shift, e + shift
            if e <= a or s >= b:
                continue
            if map_t:
                ms, me = map_t(max(s, a)), map_t(min(e, b))
                if ms is None and me is None:
                    continue
                ms = ms if ms is not None else max(0.0, me - (e - s))
                me = me if me is not None else ms + (e - s)
            else:
                ms, me = max(s, a) - a, min(e, b) - a
            text = text.upper() if st.get("upper") else text
            out.append((max(0.0, ms), me, text))
        return [x for x in out if x[1] - x[0] > 0.05]
    words = [(w, s + shift, e + shift) for w, s, e in (cap.get("words") or [])]
    return V.caption_events(words, a, b, st, map_t)


def item(cap, text):
    st = style_of(cap)
    t = {k: v for k, v in st.items() if k in E.TEXT_DEFAULT}
    t.update(text=text, pos="Custom", x=50, y=pos_y(cap), hcenter=True, layer=99)
    return t


def for_range(cap, a, b, pad=2.0):
    """The caption settings with only the words / lines of a..b (keeps project files and commands small)."""
    if not cap or not cap.get("on"):
        return None
    sh = float(cap.get("shift") or 0.0)
    c = dict(cap)
    c["words"] = [list(w) for w in (cap.get("words") or []) if w[2] + sh > a - pad and w[1] + sh < b + pad]
    c["cues"] = [list(x) for x in (cap.get("cues") or []) if x[1] + sh > a - pad and x[0] + sh < b + pad]
    return c if (c["words"] or c["cues"]) else None


def still_item(cap, a, b, t_rel):
    """The caption page shown at t_rel of the clip a..b, as a normal text item with movie times (still preview)."""
    for t0, t1, text in events(cap, a, b):
        if t0 <= t_rel < t1:
            return dict(item(cap, text), start=a + t0, end=a + t1)
    return None
