"""Self check of the portable Windows version (run by the build on a Windows machine, and usable by hand):
  python selfcheck.py
Checks: FFmpeg, every module, the window with the Cutting ON/OFF switches, a real plain-parts export,
Silero speech detection and the bundled Whisper model."""
import os, sys, subprocess, tempfile, traceback, shutil

HERE = os.path.dirname(os.path.abspath(__file__))
FF = os.path.join(HERE, "ffmpeg")
if os.path.isdir(FF):
    os.environ["PATH"] = FF + os.pathsep + os.environ["PATH"]
os.chdir(HERE)
sys.path.insert(0, HERE)

fails = []


def step(name, fn):
    try:
        r = fn()
        print(f"OK    {name}" + (f" - {r}" if r else ""), flush=True)
    except Exception:
        fails.append(name)
        print(f"FAIL  {name}\n{traceback.format_exc()}", flush=True)


tmp = tempfile.mkdtemp(prefix="cc_check_")
movie = os.path.join(tmp, "talk.mp4")


def t_ffmpeg():
    v = subprocess.run(["ffmpeg", "-hide_banner", "-version"], capture_output=True, text=True).stdout.splitlines()[0]
    enc = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True).stdout
    assert "libx264" in enc, "libx264 missing"
    r = subprocess.run(["ffmpeg", "-nostdin", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=25:duration=12",
                        "-f", "lavfi", "-i", "sine=frequency=300:duration=12", "-af", "volume='if(lt(mod(t,3),2),1,0)':eval=frame",
                        "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest", movie], capture_output=True, text=True)
    assert r.returncode == 0 and os.path.getsize(movie) > 1000, r.stderr[-300:]
    return v


def t_silence_windows():
    import engine as E
    full = E.detect_silence(movie, -35, 0.5, 12)
    win = E.detect_silence(movie, -35, 0.5, None, [(0.0, 7.0)])
    assert full and win, (full, win)
    assert any(abs(a - fa) < 0.3 and abs(b - fb) < 0.3 for a, b in win for fa, fb in full), (win, full)
    assert all(b <= 7.3 for _, b in win), win
    return f"{len(win)} stretch(es) in the first 7 s"


def t_modules():
    import engine, dialogue, colour, project, model, scoring, preview, widgets, auto_short, auto_short_ui, studio  # noqa: F401
    import app  # noqa: F401


def t_window():
    import app as A
    import studio as S
    w = A.App()
    w.update()

    def walk(x):
        yield x
        for c in x.winfo_children():
            yield from walk(c)
    # the project bar: New project / Open / Save / Save as must be on screen (not cut off) at the smallest window size
    w.geometry("1200x760"); w.update_idletasks(); w.update()
    bar = w.project_bar
    texts = {}
    for x in walk(bar):
        try:
            t = x.cget("text")
        except Exception:
            continue
        if t:
            texts[t] = x
    # a very long project name and a long hint must not push any button out
    w.proj_lbl.configure(text="Immortal.2026.1080p.AMZN.WEB-DL.HIN-TAM-TEL-KAN-MAL.DDP5.1.H.264-JeRi.mkv     D:/zoya/Immortal.2026.1080p.AMZN.WEB-DL.HIN-TAM-TEL-KAN-MAL.DDP5.1.H.264-JeRi.mkv.ccproj" * 2)
    w.proj_note.configure(text="Saved: D:/zoya/Immortal.2026.1080p.AMZN.WEB-DL.HIN-TAM-TEL-KAN-MAL.ccproj")
    w.update_idletasks(); w.update()
    for label in ("New project", "Open  (Ctrl+O)", "Save  (Ctrl+S)", "Save as"):
        x = texts.get(label)
        assert x is not None, f"project bar button missing: {label}"
        assert x.winfo_ismapped() and x.winfo_x() + x.winfo_width() <= bar.winfo_width() + 2 and x.winfo_width() > 30, \
            f"project bar button cut off: {label} x={x.winfo_x()} w={x.winfo_width()} bar={bar.winfo_width()}"
    studios = [x for x in walk(w) if isinstance(x, S.Studio)]
    assert studios, "no Simple Edit / AI studio found"
    for st in studios:
        st.sil_on.set(False); st.dl_on.set(False); st.update_cut_info()
        assert "PLAIN PARTS" in st.exp_go.cget("text"), st.exp_go.cget("text")
        st.dl_on.set(True); st.update_cut_info()
        assert "DIALOGUE" in st.exp_go.cget("text")
        st.dl_on.set(False); st.sil_on.set(True); st.update_cut_info()
        assert "SILENCE" in st.exp_go.cget("text")
        st.head_on.set(True); st.head_sec.set("3")
        assert st.with_tail([(10.0, 1.0)], 10.0, 20.0) == [(10.0, 1.0), (13.0, 7.0)], st.with_tail([(10.0, 1.0)], 10.0, 20.0)
        assert st.with_tail([(10.0, 1.0)], 10.0, 12.0) == [(10.0, 1.0)]
        st.head_on.set(False)
    w.update()
    w.destroy()
    return f"{len(studios)} studio(s)"


def t_plain_export():
    import engine as E
    cpu = [c for c in E.CODECS if "CPU" in c][0]
    s = E.sanitize({"resolution": "480p", "codec": cpu, "rate_mode": E.RATE_MODES[0], "bitrate": 2000})
    out = os.path.join(tmp, "out")
    plans = [dict(file="t_part01.mp4", start=1.0, end=7.0, label="", pieces=[(1.0, 6.0)], overlays=[], texts=[], number=1)]
    logs = []
    eng = E.StudioEngine(s, logs.append, lambda fr, t: None, lambda c: None)
    eng.process(movie, plans, out)
    f = os.path.join(out, "t_part01.mp4")
    assert os.path.exists(f) and os.path.getsize(f) > 5000, "\n".join(map(str, logs))[-600:]
    d = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", f],
                             capture_output=True, text=True).stdout.strip())
    assert abs(d - 6.0) < 0.3, f"plain part length {d}s, expected 6s (nothing removed)"
    return f"6.0s part, {d:.2f}s"


def t_silero():
    import dialogue
    p = dialogue.silero_model_path()
    assert p and os.path.exists(p), "Silero model file not found"
    opts = dict(denoise=False, vad=True, whisper=False, remove_words="", language="", pad_ms=150, min_sil_ms=300,
                min_piece=1.0, scan_picture=False)
    msgs = []
    pieces, _ = dialogue.analyze(movie, 0, 12, opts, os.path.join(tmp, "work"), msgs.append)
    assert isinstance(pieces, list)
    return f"{len(pieces)} pieces ({'; '.join(m.strip() for m in msgs)[:120]})"


def t_whisper():
    import numpy as np
    import dialogue
    words = dialogue.transcribe_words(np.zeros(16000, dtype="float32"), "en", print)
    assert words is not None, "Whisper did not load"
    return "bundled model loads offline"


step("ffmpeg + test movie", t_ffmpeg)
step("all modules import", t_modules)
step("silence scan of only the start of parts", t_silence_windows)
step("window and Cutting ON/OFF switches", t_window)
step("plain parts export (nothing removed)", t_plain_export)
step("Silero speech detection", t_silero)
if os.path.isfile(os.path.join(HERE, "models", "whisper-small", "model.bin")):
    os.environ["HF_HUB_OFFLINE"] = "1"
    step("Whisper (bundled small model)", t_whisper)
else:
    print("SKIP  Whisper: the model pack is not installed (optional)")
shutil.rmtree(tmp, ignore_errors=True)
print("SELFCHECK " + ("FAILED: " + ", ".join(fails) if fails else "OK"))
sys.exit(1 if fails else 0)
