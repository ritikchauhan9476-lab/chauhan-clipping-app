"""Dialogue detection: finds where people are TALKING in one time range of a movie.

For one range (only that range is read, so it is fast):
1. FFmpeg extracts the range's audio (16 kHz mono).
2. Speech detection. Silero VAD, a small neural network, runs through onnxruntime (no PyTorch needed).
   If it is not installed, a built-in voice-band detector is used instead.
3. Optional text editing: faster-whisper transcribes word by word and the words you list are cut out.
4. The result is a list of speech pieces. The export then cuts the PICTURE and the SOUND to exactly those pieces
   in one FFmpeg pass (see engine.build_command, pieces=...), so everything stays in sync.
"""
import os, re, subprocess, wave
import numpy as np
import engine as E

PAD_MS = 150          # speech padding on both sides of a detected speech region
MIN_SIL_MS = 300      # silences shorter than this are bridged (not cut)
FADE = 0.02           # 20 ms fade-out / fade-in at every cut
MIN_KEEP = 0.3        # pieces shorter than this are dropped (too short to be a word)
HOP = 0.03            # seconds per loudness frame (contour used to find quiet places)
MERGE_GAP = 0.15      # two pieces closer than this (after padding) are one piece: a cut this small is pointless
MIN_PIECE = 1.0       # no dialogue piece (= no shot in the result) is shorter than this many seconds
SCENE_THR = 0.25      # picture jump score (0-1) that counts as a cut between two shots
FLASH_SHOT = 0.30     # a shot shorter than this is a flash cut
MAX_CUT_RATE = 1.0    # more picture cuts per second than this = fast-cut montage
SNAP = 0.5            # a dialogue cut this close (s) to a shot change is moved onto the shot change


def _run(cmd):
    r = subprocess.run(cmd, capture_output=True, creationflags=E.NOWIN)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.decode(errors="ignore")[-400:] or "ffmpeg failed")


def extract_range(movie, start, length, wav):
    """Audio of [start, start+length] as 16 kHz mono 16-bit WAV (only that range is decoded)."""
    _run(["ffmpeg", "-nostdin", "-y", "-v", "error", "-ss", f"{start:.3f}", "-t", f"{length:.3f}",
          "-i", movie, "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", wav])


def read_wav(path):
    with wave.open(path, "rb") as w:
        sr, n = w.getframerate(), w.getnframes()
        data = np.frombuffer(w.readframes(n), dtype=np.int16).astype(np.float32) / 32768.0
    return data, sr


def frame_db(x, sr, hop=HOP):
    """Loudness (dB) of every 30 ms frame."""
    f = int(sr * hop)
    n = len(x) // f
    if n == 0:
        return np.zeros(0, dtype=np.float32)
    rms = np.sqrt((x[:n * f].reshape(n, f) ** 2).mean(1) + 1e-12)
    return (20 * np.log10(rms)).astype(np.float32)


# ------------------------------------------------------------------ speech detection
def finish_regions(regs, total, pad_ms, min_sil_ms):
    """Raw speech regions -> final pieces: bridge short silences, add padding, merge pieces that would
    be separated by a pointlessly small cut."""
    gap, pad = min_sil_ms / 1000.0, pad_ms / 1000.0
    merged = []
    for s, e in regs:
        if merged and s - merged[-1][1] < gap:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    padded = [[max(0.0, s - pad), min(total, e + pad)] for s, e in merged]
    out = []
    for s, e in padded:
        if out and s - out[-1][1] < MERGE_GAP:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return [(s, e) for s, e in out if e - s > 0.05]


def voice_band_regions(x, sr):
    """Fallback detector (no AI): a 30 ms frame is speech when its 250-3800 Hz energy is clearly above the
    room noise AND most of its energy is in the voice band. Worse than Silero with music in the background."""
    f = int(sr * HOP)
    n = len(x) // f
    if n < 3:
        return []
    frames = x[:n * f].reshape(n, f) * np.hanning(f)
    spec = np.abs(np.fft.rfft(frames, axis=1)) ** 2
    freqs = np.fft.rfftfreq(f, 1.0 / sr)
    band = (freqs >= 250) & (freqs <= 3800)
    e_band = spec[:, band].sum(1) + 1e-12
    e_all = spec.sum(1) + 1e-12
    db = 10 * np.log10(e_band)
    floor, peak = np.percentile(db, 10), np.percentile(db, 95)
    thr = floor + max(8.0, (peak - floor) * 0.35)
    active = (db > thr) & (e_band / e_all > 0.35)
    # close holes shorter than 90 ms
    i = 0
    while i < n:
        if not active[i]:
            j = i
            while j < n and not active[j]:
                j += 1
            if 0 < i and j < n and (j - i) * HOP < 0.09:
                active[i:j] = True
            i = j
        else:
            i += 1
    regs, start = [], None
    for i, a in enumerate(active):
        if a and start is None:
            start = i * HOP
        elif not a and start is not None:
            regs.append([start, i * HOP])
            start = None
    if start is not None:
        regs.append([start, n * HOP])
    return [(s, e) for s, e in regs if e - s >= 0.15]      # drop clicks / blips


class SileroOnnx:
    """Silero VAD v5/v6 run directly with onnxruntime (same maths as the silero-vad package, no torch)."""
    WIN, CTX = 512, 64                      # samples per step at 16 kHz, and the context carried between steps

    def __init__(self, path):
        import onnxruntime as ort
        so = ort.SessionOptions()
        so.inter_op_num_threads = 1
        so.intra_op_num_threads = 1
        self.sess = ort.InferenceSession(path, sess_options=so, providers=["CPUExecutionProvider"])

    def probs(self, x):
        """Speech probability for every 32 ms step of a 16 kHz mono float32 signal."""
        W, C = self.WIN, self.CTX
        n = int(np.ceil(len(x) / W))
        x = np.concatenate([x.astype(np.float32), np.zeros(n * W - len(x), np.float32)])
        state = np.zeros((2, 1, 128), np.float32)
        ctx = np.zeros((1, C), np.float32)
        sr = np.array(16000, dtype=np.int64)
        out = np.empty(n, np.float32)
        for i in range(n):
            inp = np.concatenate([ctx, x[i * W:(i + 1) * W][None, :]], axis=1)
            o, state = self.sess.run(None, {"input": inp, "state": state, "sr": sr})
            ctx = inp[:, -C:]
            out[i] = float(np.asarray(o).reshape(-1)[0])
        return out


def probs_to_regions(p, step, threshold=0.5, min_speech=0.2):
    """Silero's rule: speech starts when p >= threshold and ends when p drops below threshold - 0.15."""
    neg = max(threshold - 0.15, 0.01)
    regs, start = [], None
    for i, v in enumerate(p):
        if start is None:
            if v >= threshold:
                start = i * step
        elif v < neg:
            regs.append([start, i * step])
            start = None
    if start is not None:
        regs.append([start, len(p) * step])
    return [(s, e) for s, e in regs if e - s >= min_speech]


_models = {}          # loaded once and reused for every range


def silero_model_path():
    """models/silero_vad.onnx in the project folder, or the file that ships inside the silero-vad package."""
    mine = os.path.join(E.BASE, "models", "silero_vad.onnx")
    if os.path.isfile(mine):
        return mine
    try:
        import importlib.util
        spec = importlib.util.find_spec("silero_vad")       # finds the package without importing torch
    except Exception:
        spec = None
    for loc in (list(spec.submodule_search_locations or []) if spec else []):
        d = os.path.join(loc, "data")
        for name in ("silero_vad.onnx", "silero_vad_16k_op15.onnx"):
            if os.path.isfile(os.path.join(d, name)):
                return os.path.join(d, name)
        import glob                                           # different folder layout in a newer package
        for f in sorted(glob.glob(os.path.join(loc, "**", "silero_vad*.onnx"), recursive=True)):
            if "half" not in os.path.basename(f):
                return f
    return None


def _silero():
    if "silero" not in _models:
        path = silero_model_path()
        if not path:
            raise ImportError("Silero VAD model file not found")
        _models["silero"] = SileroOnnx(path)
    return _models["silero"]


def detect_speech(x, pad_ms, min_sil_ms, log):
    """x: 16 kHz mono float32. Returns ([(start, end), ...] in seconds, detector name)."""
    total = len(x) / 16000.0
    try:
        regs = probs_to_regions(_silero().probs(x), SileroOnnx.WIN / 16000.0)
        return finish_regions(regs, total, pad_ms, min_sil_ms), "Silero AI"
    except ImportError as e:
        if not _models.get("warned_silero"):
            _models["warned_silero"] = True
            log("Silero AI speech detector is not installed - using the built-in detector. "
                "Run install_ai.bat once for better accuracy.")
    except Exception as e:
        if not _models.get("warned_silero2"):
            _models["warned_silero2"] = True
            log(f"Silero AI failed ({str(e)[:120]}) - using the built-in detector instead.")
    return finish_regions(voice_band_regions(x, 16000), total, pad_ms, min_sil_ms), "built-in detector"


# ------------------------------------------------------------------ optional text editing (faster-whisper)
def _whisper(device="cpu"):
    """Loads faster-whisper once. CPU by default: it works on every PC without CUDA DLLs."""
    key = f"whisper_{device}"
    if key not in _models:
        from faster_whisper import WhisperModel
        ctype = "float16" if device == "cuda" else "int8"
        _models[key] = WhisperModel(E.whisper_source("small"), device=device, compute_type=ctype)
    return _models[key]


def transcribe_words(audio, language, log):
    """Word-level transcript of a 16 kHz mono float32 array. Returns [(start, end, word)] or None.
    A numpy array is passed (not a file path) because faster-whisper's file decoder breaks with some PyAV builds."""
    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        log("faster-whisper is not installed - text-based editing is skipped.")
        return None
    try:
        segs, _ = _whisper("cpu").transcribe(audio, language=(language or None), word_timestamps=True,
                                             vad_filter=False)
        words = []
        for seg in segs:
            for w in (seg.words or []):
                words.append((float(w.start), float(w.end), w.word.strip()))
        return words
    except Exception as e:
        log(f"Text editing skipped (Whisper failed: {str(e)[:150]}). Silence cutting still applied.")
        return None


def removal_spans(words, remove_list, pad=0.03):
    targets = {w.strip().lower() for w in remove_list if w.strip()}
    out = []
    for s, e, w in words or []:
        clean = re.sub(r"[^\w]", "", w).lower()
        if clean and clean in targets:
            out.append((max(0.0, s - pad), e + pad))
    return out


def subtract(spans, cuts):
    for cs, ce in sorted(cuts):
        nxt = []
        for s, e in spans:
            if ce <= s or cs >= e:
                nxt.append((s, e))
                continue
            if cs > s:
                nxt.append((s, cs))
            if ce < e:
                nxt.append((ce, e))
        spans = nxt
    return spans


# ------------------------------------------------------------------ smoother cuts
def smooth_pieces(regs, total, min_piece=MIN_PIECE):
    """No piece shorter than `min_piece`: a short piece is made longer with the surrounding sound and picture
    (half of the missing time on each side), and pieces that then touch are joined. Result: no 0.2 s flashes."""
    out = []
    for s, e in sorted(regs):
        if e - s < min_piece:
            extra = (min_piece - (e - s)) / 2.0
            s, e = max(0.0, s - extra), min(total, e + extra)
        if out and s <= out[-1][1] + MERGE_GAP:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return [(s, e) for s, e in out]


def _bars(movie):
    """Black bars of the movie (found once per movie): without removing them a letterboxed movie looks 'calm'."""
    key = "crop:" + movie
    if key not in _models:
        try:
            _models[key] = E.detect_crop(movie, float(E.probe_info(movie)["duration"]))
        except Exception:
            _models[key] = None
    return _models[key]


def scene_cuts(movie, start, end, thr=SCENE_THR):
    """Movie times (seconds) where the picture jumps to another shot, found by FFmpeg on a tiny copy of the picture
    (black bars removed first). Only the range is read."""
    crop = _bars(movie)
    vf = (crop + "," if crop else "") + f"scale=160:-2,select='gt(scene,{thr})',showinfo"
    r = subprocess.run(["ffmpeg", "-nostdin", "-v", "info", "-ss", f"{start:.3f}", "-t", f"{max(0.1, end - start):.3f}",
                        "-i", movie, "-an", "-sn", "-vf", vf, "-f", "null", "-"],
                       capture_output=True, creationflags=E.NOWIN)
    return sorted(start + float(m) for m in re.findall(r"pts_time:([0-9.]+)", r.stderr.decode(errors="ignore")))


def is_montage(s, e, cuts):
    """Fast-cut montage: a flash cut (a shot shorter than FLASH_SHOT) or more than MAX_CUT_RATE cuts per second."""
    inside = [c for c in cuts if s < c < e]
    if len(inside) < 2:
        return False
    gaps = [b - a for a, b in zip(inside, inside[1:])]
    if min(gaps) < FLASH_SHOT:
        return True
    return len(inside) >= 3 and (e - s) >= 2.0 and len(inside) / (e - s) > MAX_CUT_RATE


def picture_fix(regs, cuts, pad, lo, hi):
    """Looks at the picture cuts: drops pieces that are fast-cut montage, and moves every start / end onto a nearby
    shot change (so the cut hides in a real cut). Starts only move into the padding or outwards, so no word is lost.
    Returns (pieces, dropped, snapped)."""
    kept, dropped, snapped = [], 0, 0
    for s, e in regs:
        if is_montage(s, e, cuts):
            dropped += 1
            continue
        s0, e0 = s, e
        near = [c for c in cuts if s - SNAP <= c <= s + pad]
        if near:
            c = min(near, key=lambda c: abs(c - s))
            snapped += c != s
            s = c
        near = [c for c in cuts if e - pad < c <= e + SNAP]
        if near:
            c = min(near, key=lambda c: abs(c - e))
            snapped += c != e
            e = c
        # a sliver of the previous / next shot (shorter than a flash) at the start or end is cut off,
        # but only inside the padding, so no word is touched
        sliver = [c for c in cuts if s < c <= s + FLASH_SHOT and c <= s0 + pad]
        if sliver:
            s = max(sliver)
            snapped += 1
        sliver = [c for c in cuts if e - FLASH_SHOT <= c < e and c >= e0 - pad]
        if sliver:
            e = min(sliver)
            snapped += 1
        s, e = max(lo, s), min(hi, e)
        if e - s > 0.05:
            kept.append([s, e])
    out = []
    for s, e in kept:
        if out and s <= out[-1][1] + 0.02:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return [(s, e) for s, e in out], dropped, snapped


# ------------------------------------------------------------------ one range
def find_speech(movie, start, end, opts, work_dir, log):
    """Where is anyone talking between `start` and `end` (movie seconds)?
    Returns dict(regions=[(abs_start, abs_end), ...], contour=(abs_t0, hop, dB array), detector=name)."""
    os.makedirs(work_dir, exist_ok=True)
    length = max(0.1, end - start)
    raw = os.path.join(work_dir, f"raw_{int(start * 1000)}_{int(end * 1000)}.wav")
    extract_range(movie, start, length, raw)
    try:
        x, sr = read_wav(raw)
    finally:
        try:
            os.remove(raw)
        except OSError:
            pass
    total = len(x) / sr
    pad = int(opts.get("pad_ms", PAD_MS))
    minsil = int(opts.get("min_sil_ms", MIN_SIL_MS))
    if opts.get("vad", True):
        regs, name = detect_speech(x, pad, minsil, log)
    else:
        regs, name = [(0.0, total)], "off (whole range kept)"
    remove = [w for w in re.split(r"[,;]", opts.get("remove_words", "")) if w.strip()]
    if regs and opts.get("whisper") and remove:
        words = transcribe_words(x, opts.get("language", ""), log)
        if words:
            cuts = removal_spans(words, remove)
            regs = [(s, e) for s, e in subtract(regs, cuts) if e - s >= MIN_KEEP]
            log(f"  text editing: {len(words)} words, {len(cuts)} removed")
    regs = smooth_pieces(regs, total, float(opts.get("min_piece", MIN_PIECE)))
    abs_regs = [(start + s, start + e) for s, e in regs]
    if opts.get("scan_picture") and abs_regs:
        cuts = scene_cuts(movie, start, end)
        abs_regs, dropped, snapped = picture_fix(abs_regs, cuts, pad / 1000.0, start, end)
        log(f"  picture scan: {len(cuts)} shot changes, {dropped} fast-cut montage piece(s) skipped, "
            f"{snapped} cut(s) moved onto a shot change")
    return dict(regions=abs_regs, contour=(start, HOP, frame_db(x, sr)), detector=name)


def analyze(movie, start, end, opts, work_dir, log):
    """Simple Edit helper: dialogue pieces of ONE part. Returns (pieces, None) with pieces = [(start, length), ...]
    in movie time, or ([], None) when nobody talks in that range."""
    info = find_speech(movie, start, end, opts, work_dir, log)
    log(f"  speech detection: {info['detector']}, {len(info['regions'])} pieces "
        f"(padding {opts.get('pad_ms', PAD_MS)} ms, min silence {opts.get('min_sil_ms', MIN_SIL_MS)} ms)")
    pieces = [(s, e - s) for s, e in info["regions"] if e - s >= MIN_KEEP]
    return pieces, None


def trim_start(movie, a, b, seconds, voice, noise_db, work_dir, log):
    """Simple Edit 'clean start': where should a part really start? Looks ONLY at the first `seconds` seconds (plus a
    little margin) of the part [a, b] - the rest of the video is never touched. If the part begins with silence (or,
    with voice=True, with anything that is not talking: music, noise) that is cut, but never more than `seconds`.
    Returns (new_start, info_text); new_start == a when nothing needs cutting."""
    seconds = max(0.5, float(seconds))
    win_end = min(b, a + seconds + 1.5)
    if win_end - a < 1.0:
        return a, "part too short, left as it is"
    lead, how = 0.0, ""
    if voice:
        opts = dict(pad_ms=100, min_sil_ms=300, min_piece=0.3, vad=True, whisper=False, scan_picture=False)
        info = find_speech(movie, a, win_end, opts, work_dir, log)
        if str(info["detector"]).startswith("off"):
            voice = False                                    # no voice detector available: fall back to silence
        else:
            regs = [r for r in info["regions"] if r[1] - r[0] >= 0.15]
            lead = (regs[0][0] - a) if regs else seconds     # nobody talks in the window: all of it is "not talking"
            how = "first words"
    if not voice:
        sil = E.detect_silence(movie, noise_db, 0.3, None, [(a, win_end)])
        first = next((x for x in sil if x[0] <= a + 0.15), None)
        lead = max(0.0, first[1] - a - 0.12) if first else 0.0
        how = "end of the silence"
    lead = min(lead, seconds)
    if lead < 0.25 or (b - a - lead) < 1.0:
        return a, "starts with talking already"
    return a + lead, f"{lead:.2f}s cut ({how})"


# ------------------------------------------------------------------ helpers for building clips
def quietest_point(contour, lo, hi):
    """Time in [lo, hi] (movie seconds) where the sound is quietest (smoothed over ~90 ms)."""
    t0, hop, db = contour
    if len(db) < 3:
        return (lo + hi) / 2
    a, b = max(0, int((lo - t0) / hop)), min(len(db), int((hi - t0) / hop) + 1)
    if b - a < 3:
        return (lo + hi) / 2
    sm = np.convolve(db[a:b], np.ones(3) / 3, mode="same")
    return t0 + (a + int(np.argmin(sm))) * hop


def split_long(regions, contour, cap):
    """Regions longer than `cap` seconds are split at their quietest points (the pieces stay adjacent,
    so nothing is lost). This lets a clip be filled to an exact length."""
    out = []
    for s, e in regions:
        while e - s > cap * 1.15:
            t = quietest_point(contour, s + cap * 0.5, s + cap)
            t = min(max(t, s + 0.5), e - 0.5)
            out.append((s, t))
            s = t
        out.append((s, e))
    return out


def join_adjacent(pieces, eps=0.02):
    """[(s, e), ...] -> [(start, length), ...]; pieces that touch are one piece (no fade dip in the middle)."""
    out = []
    for s, e in pieces:
        if out and s - out[-1][1] <= eps:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return [(s, e - s) for s, e in out]
