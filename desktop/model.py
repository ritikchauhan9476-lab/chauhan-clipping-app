"""Timeline data model - pure Python (no GUI). Times are movie-absolute seconds."""
import os
import engine as E

RULER_H = 26
TRACK_H = 34
PAD_X = 12
MIN_LEN = 0.2
# top -> bottom, like a CapCut / Premiere timeline
TRACKS = [("T", 3), ("T", 2), ("T", 1), ("O", 3), ("O", 2), ("O", 1), ("V", 1), ("A", 1), ("A", 2), ("A", 3)]
TRACK_INDEX = {t: i for i, t in enumerate(TRACKS)}
KIND_KEY = {"text": "texts", "overlay": "overlays", "audio": "audios"}
KIND_LETTER = {"text": "T", "overlay": "O", "audio": "A"}
KIND_NAME = {"text": "Text", "overlay": "Overlay", "audio": "Audio"}
DEFAULTS_BY_KIND = {"text": E.TEXT_DEFAULT, "overlay": E.OVERLAY_DEFAULT, "audio": E.AUDIO_DEFAULT}


def canvas_h():
    return RULER_H + len(TRACKS) * TRACK_H + 4


def x_of(t, pps):
    return PAD_X + t * pps


def t_of(x, pps):
    return max(0.0, (x - PAD_X) / pps)


def clamp_layer(v):
    try:
        v = int(float(v))
    except (TypeError, ValueError):
        v = 1
    return min(3, max(1, v))


def track_of(kind, item):
    return TRACK_INDEX[(KIND_LETTER[kind], clamp_layer(item.get("layer", 1)))]


def item_end(kind, item, duration):
    e = float(item.get("end", 0.0) or 0.0)
    return e if e > 0 else duration


def norm_item(kind, item, duration):
    it = {**DEFAULTS_BY_KIND[kind], **item}
    it["layer"] = clamp_layer(it["layer"])
    it["start"] = max(0.0, float(it["start"]))
    end = float(it["end"])
    if end <= 0:
        end = duration if duration > 0 else it["start"] + 5.0
    if end < it["start"] + MIN_LEN:
        end = it["start"] + MIN_LEN
    it["end"] = end
    return it


def base_rect(duration, pps):
    y0 = RULER_H + TRACK_INDEX[("V", 1)] * TRACK_H + 3
    return (x_of(0, pps), y0, x_of(duration, pps), y0 + TRACK_H - 6)


def rect(kind, item, pps, duration):
    y0 = RULER_H + track_of(kind, item) * TRACK_H + 3
    s = float(item["start"])
    e = item_end(kind, item, duration)
    x0 = x_of(s, pps)
    return (x0, y0, max(x0 + 4, x_of(e, pps)), y0 + TRACK_H - 6)


def hit_test(cx, cy, pps, duration, lists):
    """Returns (kind, index) of the item under the pointer. Text is above overlay above audio."""
    if cy < RULER_H:
        return None
    best = None
    for kind in ("audio", "overlay", "text"):
        for i, it in enumerate(lists.get(kind, [])):
            r = rect(kind, it, pps, duration)
            if r[0] <= cx <= r[2] and r[1] <= cy <= r[3]:
                best = (kind, i)
    return best


def edge_mode(cx, r, edge=7):
    if abs(cx - r[0]) <= edge:
        return "trim_l"
    if abs(cx - r[2]) <= edge:
        return "trim_r"
    return "move"


def track_at(cy):
    if cy < RULER_H:
        return None
    i = int((cy - RULER_H) // TRACK_H)
    return i if 0 <= i < len(TRACKS) else None


def drag_result(mode, s0, e0, o0, dt, kind, duration):
    """New (start, end, change_in_source_offset) for a move / trim drag."""
    dt = round(dt * 20) / 20.0
    cap = duration if (kind != "audio" and duration > 0) else None
    if mode == "move":
        L = e0 - s0
        s = max(0.0, s0 + dt)
        if cap is not None:
            s = min(s, max(0.0, cap - L))
        return s, s + L, 0.0
    if mode == "trim_l":
        lo = max(0.0, s0 - o0)
        s = min(max(lo, s0 + dt), e0 - MIN_LEN)
        return s, e0, s - s0
    if mode == "trim_r":
        e = max(s0 + MIN_LEN, e0 + dt)
        if cap is not None:
            e = min(e, max(cap, s0 + MIN_LEN))
        return s0, e, 0.0
    return s0, e0, 0.0


def split_item(kind, item, t, duration):
    s = float(item["start"])
    e = item_end(kind, item, duration)
    if not (s + MIN_LEN <= t <= e - MIN_LEN):
        return None
    a = dict(item)
    a["end"] = round(t, 3)
    b = dict(item)
    b["start"] = round(t, 3)
    b["end"] = e
    b["src_offset"] = float(item.get("src_offset", 0.0) or 0.0) + (t - s)
    return a, b


def item_label(kind, item):
    if kind == "text":
        first = str(item.get("text", "")).strip().split("\n")[0]
        return first[:40] or "(empty text)"
    return os.path.basename(str(item.get("path", ""))) or "(no file)"


def fmt_time(t):
    t = max(0.0, float(t))
    m, s = divmod(t, 60)
    return f"{int(m):02d}:{s:04.1f}"


def ruler_step(pps):
    for st in (0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300):
        if st * pps >= 70:
            return st
    return 600
