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
    simple = [x for x in studios if x.mode == "simple"][0]
    tabs = list(simple.right._tab_dict.keys()) if hasattr(simple.right, "_tab_dict") else []
    assert "Silence" not in tabs and "Dialogue" not in tabs and "Export" in tabs, tabs
    assert not hasattr(simple, "cut_info"), "Simple Edit must not show the cutting switches"
    ai = [x for x in studios if x.mode == "ai"][0]
    assert "Silence" in list(ai.right._tab_dict.keys()), "AI Clipping lost its Silence tab"
    for st in [ai]:
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


def t_silence_per_part():
    import app as A
    import studio as S
    w = A.App()
    w.update()

    def walk(x):
        yield x
        for c in x.winfo_children():
            yield from walk(c)
    studs = [x for x in walk(w) if isinstance(x, S.Studio)]
    simple = [x for x in studs if x.mode == "simple"][0]
    simple.sil_on.set(True)
    assert simple.silence_prepare(movie, print) is None, "Simple Edit must never cut silence"
    st = [x for x in studs if x.mode == "ai"][0]
    st.sil_on.set(True); st.sil_min.set(0.5); st.head_on.set(False)
    logs = []
    prep = st.silence_prepare(movie, logs.append)
    plan = dict(file="x.mp4", start=0.0, end=12.0, pieces=[(0.0, 12.0)], sil=True)
    out = prep(plan)
    kept = sum(d for _, d in out["pieces"])
    assert 0 < kept < 11.5, f"silence not cut for this part: kept {kept}s"
    assert prep(dict(plan, sil=False))["pieces"] == [(0.0, 12.0)]
    st.head_on.set(True); st.head_sec.set("4")
    out2 = st.silence_prepare(movie, logs.append)(plan)
    assert out2["pieces"][-1] == (4.0, 8.0), out2["pieces"]
    w.destroy()
    return f"kept {kept:.1f}s of 12s; first-4s mode keeps the tail 4.0-12.0"


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


def t_simple_export_in_window():
    """The real Simple Edit export button path (Studio.export), as the user does it: load movie, parts, Export."""
    import time
    import app as A
    import studio as S
    import engine as E
    w = A.App()
    w.update()

    def walk(x):
        yield x
        for c in x.winfo_children():
            yield from walk(c)
    st = [x for x in walk(w) if isinstance(x, S.Studio) and x.mode == "simple"][0]
    errors = []
    S.messagebox.showerror = lambda *a, **k: errors.append(a)
    S.messagebox.showwarning = lambda *a, **k: errors.append(a)
    st.load_movie(movie)
    assert st.movie == movie and st.dur > 10, "movie did not load"
    st.parts = [{"on": True, "sil": True, "start": 1.0, "end": 7.0, "label": ""},
                {"on": True, "sil": True, "start": 7.0, "end": 11.0, "label": ""}]
    st.cfg.update(codec=[c for c in E.CODECS if "CPU" in c][0], resolution="480p", rate_mode=E.RATE_MODES[0], bitrate=2000)
    st.sync_export = lambda: None
    st.export()
    assert not errors, errors
    t0 = time.time()
    while st.eng is not None and time.time() - t0 < 240:
        w.update(); time.sleep(0.05)
    log = st.exp_log.get("1.0", "end")
    assert st.eng is None, "export did not finish:\n" + log[-800:]
    out = os.path.join(E.OUTPUT_DIR, f"{st.file_base()}_simple")
    files = sorted(f for f in os.listdir(out) if f.endswith(".mp4"))
    assert len(files) == 2, f"expected 2 parts, got {files}\n" + log[-800:]
    d = [float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", os.path.join(out, f)],
                              capture_output=True, text=True).stdout.strip()) for f in files]
    assert abs(d[0] - 6.0) < 0.4 and abs(d[1] - 4.0) < 0.4, d
    assert "ilence" not in log, log[-500:]
    w.destroy()
    return f"2 parts exported ({d[0]:.1f}s + {d[1]:.1f}s), nothing cut"


def t_many_pieces():
    import engine as E
    cpu = [c for c in E.CODECS if "CPU" in c][0]
    s = E.sanitize({"resolution": "480p", "codec": cpu, "rate_mode": E.RATE_MODES[0], "bitrate": 2000})
    out = os.path.join(tmp, "out_many")
    pieces = [(i * 0.02, 0.31) for i in range(400)]          # a graph of ~100 000 characters
    plans = [dict(file="many.mp4", start=0.0, end=12.0, label="", pieces=pieces, overlays=[], texts=[], number=1, single_pass=True)]
    logs = []
    eng = E.StudioEngine(s, logs.append, lambda fr, t: None, lambda c: None)
    eng.process(movie, plans, out)
    f = os.path.join(out, "many.mp4")
    assert os.path.exists(f) and os.path.getsize(f) > 5000, "\n".join(map(str, logs))[-800:]
    return f"{os.path.getsize(f) // 1024} KB from 400 pieces"


def t_autoshort_carry():
    import auto_short as AS
    import dialogue as D
    job = object.__new__(AS.AutoShortJob)
    
    made, logs = [], []
    job.min_len, job.max_len, job.chunk, job.opts, job.movie, job.work = 30.0, 40.0, 60.0, {}, "m.mp4", tmp
    job.stopped, job.keep_last, job.span_total, job.span_done, job.made = False, False, 1.0, 0.0, 0
    job.log, job.progress = logs.append, lambda *a: None
    job.mark = lambda *a, **k: None
    job.render = lambda group: (made.append(list(group)) or True)

    def fake(movie, a, b, opts, work, log):                     # 20 s of talking in every 45 s range
        return dict(regions=[(a + 2.0, a + 22.0)], contour=None, detector="fake")
    D.find_speech = fake
    D.split_long = lambda regs, contour, cap: regs
    ranges = [[i * 45.0, (i + 1) * 45.0] for i in range(6)]
    carry = []
    for ri, (a, b) in enumerate(ranges):
        joins = ri + 1 < len(ranges) and abs(ranges[ri + 1][0] - b) < 1.0
        carry = job.scan_range(a, b, carry, flush=not joins) or []
    assert made, "no short made from 6 contiguous 45 s ranges:\n" + "\n".join(logs)
    return f"{len(made)} short(s) from 6 x 45 s ranges with 20 s of talking each"


def t_retention_boost():
    import engine as E
    t = E.zoom_toggles([3, 4, 9, 10, 11, 25], 40)
    assert all(t[i] - t[i - 1] >= 2.5 - 1e-6 for i in range(1, len(t))), t
    assert 3 in t and 25 in t, t
    assert E.zoom_expr([], 8) == "1"
    cpu = [c for c in E.CODECS if "CPU" in c][0]
    s = E.sanitize({"resolution": "480p", "codec": cpu, "rate_mode": E.RATE_MODES[0], "bitrate": 2000, "aspect": "9:16",
                    "_boost": dict(E.BOOST_DEFAULT, hook="Wait {n}"), "_denoise": True, "_joint_fade": 0.02,
                    "texts": [dict(E.TEXT_DEFAULT, text="PART 1", start=0.0, end=3.0, pos="Top-Center", hcenter=True)]})
    out = os.path.join(tmp, "boost.mp4")
    info = E.probe_info(movie)
    pieces = [(0.5, 3.0), (5.0, 3.0), (10.0, 3.0)]
    r = E.Runner(s, lambda *_: None, lambda *a: None, lambda c: None)
    assert r.cut(movie, pieces[0][0], 9.0, out, info, None, s, pieces=pieces), "export with the retention boost failed"
    assert os.path.getsize(out) > 5000
    import subprocess
    px = subprocess.run(["ffmpeg", "-v", "error", "-sseof", "-0.3", "-i", out, "-frames:v", "1", "-vf", "crop=2:2:200:0",
                         "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, creationflags=E.NOWIN).stdout
    assert len(px) >= 3 and px[0] > 190 and px[1] > 140 and px[2] < 110, f"progress bar not at the end: {list(px)}"
    return "zoom + bar + loudness + PART label export OK, progress bar full at the end"


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
step("Simple Edit: export button, 2 parts", t_simple_export_in_window)
step("silence cut, one part at a time (AI Clipping)", t_silence_per_part)
step("plain parts export (nothing removed)", t_plain_export)
step("400 pieces in one clip (long filter graph)", t_many_pieces)
step("auto short: dialogue carried on between ranges", t_autoshort_carry)
step("auto short: retention boost export", t_retention_boost)
step("Silero speech detection", t_silero)
if os.path.isfile(os.path.join(HERE, "models", "whisper-small", "model.bin")):
    os.environ["HF_HUB_OFFLINE"] = "1"
    step("Whisper (bundled small model)", t_whisper)
else:
    print("SKIP  Whisper: the model pack is not installed (optional)")
shutil.rmtree(tmp, ignore_errors=True)
print("SELFCHECK " + ("FAILED: " + ", ".join(fails) if fails else "OK"))
sys.exit(1 if fails else 0)
