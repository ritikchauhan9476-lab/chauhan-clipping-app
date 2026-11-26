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
    import viral, viral_ui, ytdl, captions, captions_ui, tracks, tracks_ui, short_model, short_editor, pq, smartcut  # noqa: F401
    import cv2  # noqa: F401  (faces for the Viral Clips layouts)
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


def t_clean_start_and_overlay_flags():
    """Simple Edit: (1) the silent start of a video is cut, only the start; (2) overlays only on ticked videos."""
    import time
    import app as A
    import studio as S
    import engine as E
    import dialogue
    # the test movie: tone 0-2 s, silence 2-3 s, tone 3-5 s, silence 5-6 s ...
    new, why = dialogue.trim_start(movie, 2.0, 8.0, 3.0, False, -35.0, os.path.join(tmp, "tw"), print)
    assert 2.6 < new < 3.0, (new, why)
    same, why2 = dialogue.trim_start(movie, 0.0, 6.0, 3.0, False, -35.0, os.path.join(tmp, "tw"), print)
    assert same == 0.0, (same, why2)
    cap, _ = dialogue.trim_start(movie, 5.2, 11.0, 0.5, False, -35.0, os.path.join(tmp, "tw"), print)
    assert cap <= 5.2 + 0.5 + 1e-6, cap                     # never more than the chosen seconds
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
    from PIL import Image
    png = os.path.join(tmp, "ov.png")
    Image.new("RGBA", (80, 80), (255, 0, 0, 255)).save(png)
    st.items = [dict(E.OVERLAY_DEFAULT, kind="overlay", path=png, rel_start=0.0, rel_end=0.0)] \
        if hasattr(E, "OVERLAY_DEFAULT") else [dict(kind="overlay", path=png, rel_start=0.0, rel_end=0.0)]
    st.parts = [{"on": True, "sil": True, "ov": True, "start": 2.0, "end": 8.0, "label": ""},
                {"on": True, "sil": True, "ov": False, "start": 9.0, "end": 12.0, "label": ""}]
    plans = st.build_plans([(0, st.parts[0]), (1, st.parts[1])])
    assert len(plans[0]["overlays"]) == 1 and plans[1]["overlays"] == [], [len(p["overlays"]) for p in plans]
    shutil.rmtree(os.path.join(E.OUTPUT_DIR, f"{st.file_base()}_simple"), ignore_errors=True)   # leftovers of the earlier test
    st.trim_on.set(True)
    st.trim_voice.set(False)
    st.trim_sec.set("3")
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
    assert 5.0 < d[0] < 5.6, ("part 1 starts in silence: about 0.9 s must be cut from 6 s", d, log[-600:])
    assert abs(d[1] - 3.0) < 0.5, ("part 2 starts with talking: untouched", d, log[-600:])
    assert "Clean start" in log, log[-500:]
    w.destroy()
    return f"start trimmed ({d[0]:.1f}s of 6.0s), second part untouched ({d[1]:.1f}s), overlay only on ticked video"


def t_resume_and_text_per_video():
    """Simple Edit: (1) a stopped export continues where it stopped; (2) a text can be hidden on some videos and have its
    own words on others."""
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
    errors, asked = [], []
    S.messagebox.showerror = lambda *a, **k: errors.append(a)
    S.messagebox.showwarning = lambda *a, **k: errors.append(a)
    S.messagebox.askyesno = lambda *a, **k: asked.append(a) or False
    st.load_movie(movie)
    txt = dict(E.TEXT_DEFAULT, kind="text", text="Main {n}", pos="Bottom-Center", x=10, y=80, size=5.0, color="#FFFFFF",
               opacity=100, outline=2, outline_color="#000000", shadow=True, box=False, box_color="#000000",
               box_opacity=60, font=E.TEXT_DEFAULT["font"], rel_start=0.0, rel_end=0.0, uid="t1")
    st.items = [txt]
    st.parts = [{"on": True, "sil": True, "ov": True, "start": float(i), "end": float(i) + 6.0, "label": ""} for i in range(6)]
    st.parts[0]["txo"] = {"t1": {"show": True, "text": "Alpha {n}"}}
    st.parts[1]["txo"] = {"t1": {"show": False, "text": ""}}
    plans = st.build_plans([(i, p) for i, p in enumerate(st.parts)])
    assert plans[0]["texts"][0]["text"] == "Alpha 1", plans[0]["texts"]
    assert plans[1]["texts"] == [], plans[1]["texts"]
    assert plans[2]["texts"][0]["text"] == "Main 3", plans[2]["texts"]
    st.select(0)
    st.refresh_pv()                                          # the 'this video' box builds without errors
    st.cfg.update(codec=[c for c in E.CODECS if "CPU" in c][0], resolution="480p", rate_mode=E.RATE_MODES[0], bitrate=2000)
    st.sync_export = lambda: None
    out = st.out_dir_for(False)
    shutil.rmtree(out, ignore_errors=True)
    st.done_names = set()
    st.export()
    assert not errors, errors
    t0 = time.time()
    while st.eng is not None and not st.done_names and time.time() - t0 < 240:
        w.update(); time.sleep(0.02)
    st.stop_export()                                         # stop after the first part is finished
    while st.eng is not None and time.time() - t0 < 240:
        w.update(); time.sleep(0.05)
    assert st.eng is None, "export did not stop"
    n_done = len(st.done_names)
    assert 1 <= n_done, "no part counted as exported"
    first = sorted(st.done_names)[0].split("/")[1]
    m1 = os.path.getmtime(os.path.join(out, first))
    stopped_status = st.exp_status.cget("text")
    st.export()                                              # second click: continues
    t0 = time.time()
    while st.eng is not None and time.time() - t0 < 300:
        w.update(); time.sleep(0.05)
    log = st.exp_log.get("1.0", "end")
    assert st.eng is None, "second export did not finish:\n" + log[-600:]
    files = sorted(f for f in os.listdir(out) if f.endswith(".mp4"))
    assert len(files) == 6 and len(st.done_names) == 6, (files, sorted(st.done_names), log[-600:])
    if n_done < 6:
        assert "Continuing where the last export stopped" in log, log[-600:]
        assert os.path.getmtime(os.path.join(out, first)) == m1, "an exported part was exported again"
    assert not asked, "asked to export everything again although the last part was not finished"
    w.destroy()
    return f"stopped after {n_done} part(s) ('{stopped_status[:30]}'), second export did the rest (6 files); text hidden / own words per video OK"


def t_word_colour_and_clean_end():
    """Simple Edit: (1) only the selected words get their colour; (2) the silent end of a video is cut, only the end.
    Auto Short: a short ends at the biggest pause, tiny pauses are not cut (no flash cuts)."""
    import engine as E
    import dialogue as D
    import auto_short as AS
    # (2) test movie: tone 0-2 s, silence 2-3 s, tone 3-5 s, silence 5-6 s ...
    new_b, why = D.trim_end(movie, 0.0, 6.0, 3.0, False, -35.0, os.path.join(tmp, "te"), print)
    assert 5.0 < new_b < 5.6, (new_b, why)
    same, why2 = D.trim_end(movie, 0.0, 4.8, 3.0, False, -35.0, os.path.join(tmp, "te"), print)
    assert same == 4.8, (same, why2)
    # Auto Short helpers
    assert D.tidy([(0, 1), (1.3, 2), (2.1, 2.3), (5, 9)], 0, 10, 1.0, 0.5) == [(0, 2.3), (5, 9)]
    g, rest = AS.pick_group([(0, 10), (10, 20), (20.2, 30), (30, 40), (41.5, 50), (50, 55), (55.1, 62)], 30, 59)
    assert g[-1] == (30, 40) and rest[0] == (41.5, 50), (g, rest)
    # (1) a red word on a black picture
    black = os.path.join(tmp, "black.mp4")
    subprocess.run(["ffmpeg", "-nostdin", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=640x360:r=25:d=3",
                    "-c:v", "libx264", "-preset", "ultrafast", black], check=True, creationflags=E.NOWIN)
    info = E.probe_info(black)
    cpu = [c for c in E.CODECS if "CPU" in c][0]
    s = E.sanitize({"resolution": "480p", "codec": cpu, "aspect": "9:16"})
    s["texts"] = [dict(E.TEXT_DEFAULT, kind="text", text="Part 1 {c=#FF0000}finding{/c} best", pos="Center", size=4.0,
                       outline=0, shadow=False, start=0.0, end=3.0)]
    jpg = os.path.join(tmp, "colour.jpg")
    cmd, tmpf = E.build_command(black, 0.0, 2.0, jpg, s, info, None, preview_t=1.0)
    r = subprocess.run(cmd, capture_output=True, creationflags=E.NOWIN)
    assert r.returncode == 0, r.stderr.decode(errors="ignore")[-600:]
    from PIL import Image
    im = Image.open(jpg).convert("RGB")
    px = list(im.getdata())
    red = sum(1 for r_, g_, b_ in px if r_ > 170 and g_ < 90 and b_ < 90)
    white = sum(1 for r_, g_, b_ in px if r_ > 200 and g_ > 200 and b_ > 200)
    assert red > 80 and white > 80, f"red word {red} px, white words {white} px"
    from PIL import features
    return (f"clean end {6.0 - new_b:.2f}s cut; red word {red} px + white words {white} px; "
            f"short ends at the biggest pause; Pillow text shaping (Hindi widths): {features.check('raqm')}")


def t_capcut_text():
    """Text options: the editor builds, every style applies, every animation / effect exports."""
    import app as A
    import studio as S
    import engine as E
    bold = E.styled_font("Arial", True, False)
    ital = E.styled_font("Arial", False, True)
    hindi_b = E.styled_font("Nirmala UI", True, False)
    hindi_names = [n for n in E.get_system_fonts() if n.lower().startswith("nirmala")]
    assert "nirmala" in os.path.basename(E.resolve_font("Nirmala UI") or "").lower(), (E.resolve_font("Nirmala UI"), hindi_names)
    assert "nirmala" in os.path.basename(hindi_b[0] or "").lower(), (hindi_b, hindi_names)
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
    S.messagebox.showinfo = lambda *a, **k: None
    st.load_movie(movie)
    st.parts = [{"on": True, "sil": True, "ov": True, "start": 0.0, "end": 6.0, "label": ""}]
    st.add_item("text")
    w.update()
    it = st.items[-1]
    for name, style in S.Studio.TEXT_STYLES:
        st._apply_style(it, style)
        w.update()
    st._duplicate_text(it)
    st._style_to_all(it)
    w.update()
    assert not errors, errors
    cpu = [c for c in E.CODECS if "CPU" in c][0]
    s = E.sanitize({"resolution": "480p", "codec": cpu, "rate_mode": E.RATE_MODES[0], "bitrate": 2000, "aspect": "9:16"})
    T = lambda **k: dict(dict(E.TEXT_DEFAULT, kind="text", font="Arial", start=0.0, end=6.0, size=4.0), **k)
    texts = []
    for i, a_in in enumerate(E.ANIM_IN):
        texts.append(T(text=f"in {a_in} words here", anim_in=a_in, anim_out=E.ANIM_OUT[i % len(E.ANIM_OUT)],
                       anim_loop=E.ANIM_LOOP[i % len(E.ANIM_LOOP)], pos="Custom", x=5, y=5 + i * 8,
                       bold=i % 2 == 0, italic=i % 3 == 0, underline=i == 3, glow=i == 4, box=i == 5, shadow=i == 6,
                       case=E.TEXT_CASES[i % 4], align=E.TEXT_ALIGNS[i % 3]))
    texts.append(T(text="Hindi {c=#FF0000}\u0928\u092e\u0938\u094d\u0924\u0947{/c} \u0926\u094b\u0938\u094d\u0924\u094b\u0902",
                   font="Nirmala UI", bold=True, pos="Bottom-Center"))
    s["texts"] = texts
    out = os.path.join(tmp, "text_fx.mp4")
    info = E.probe_info(movie)
    cmd, tmpf = E.build_command(movie, 0.0, 4.0, out, s, info, None)
    r = subprocess.run(cmd, capture_output=True, creationflags=E.NOWIN)
    assert r.returncode == 0 and os.path.getsize(out) > 5000, r.stderr.decode(errors="ignore")[-800:]
    w.destroy()
    return (f"{len(S.Studio.TEXT_STYLES)} styles, {len(E.ANIM_IN)} in / {len(E.ANIM_OUT)} out / {len(E.ANIM_LOOP)} loop "
            f"animations export OK; bold {os.path.basename(bold[0] or '-')}{' (drawn thicker)' if bold[1] else ''}, "
            f"italic {os.path.basename(ital[0] or '-')}, Hindi bold {os.path.basename(hindi_b[0] or '-')}")


def t_pro_edit_and_player():
    """Rotate / flip / free crop / speed / fades / effects export, and the live player plays in the window."""
    import time
    import app as A
    import studio as S
    import engine as E
    cpu = [c for c in E.CODECS if "CPU" in c][0]
    s = E.sanitize({"resolution": "480p", "codec": cpu, "rate_mode": E.RATE_MODES[0], "bitrate": 2000, "aspect": "9:16",
                    "rotate": "90° right", "flip_h": True, "crop_l": 10, "crop_t": 5, "speed": 2.0, "vfade_in": 0.5,
                    "vfade_out": 0.5, "fx_sepia": True, "fx_blur": 2, "fx_denoise": True, "fx_stab": True})
    out = os.path.join(tmp, "pro.mp4")
    info = E.probe_info(movie)
    cmd, tmpf = E.build_command(movie, 0.0, 8.0, out, s, info, None)
    r = subprocess.run(cmd, capture_output=True, creationflags=E.NOWIN)
    assert r.returncode == 0, r.stderr.decode(errors="ignore")[-600:]
    d = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", out],
                             capture_output=True, text=True, creationflags=E.NOWIN).stdout.strip())
    assert abs(d - 4.0) < 0.3, f"8 s at 2x speed should be 4 s, got {d}"
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
    st.parts = [{"on": True, "sil": True, "ov": True, "start": 0.0, "end": 10.0, "label": ""}]
    st.cfg.update(rotate="90° left", fx_bw=True, speed=1.5)
    st.items = [dict(E.TEXT_DEFAULT, kind="text", text="Play test", anim_in="Pop", rel_start=0.0, rel_end=0.0, uid="p1")]
    st.select_part(0)
    w.update()
    st.frames_shown = 0
    st.toggle_play()
    t0 = time.time()
    while time.time() - t0 < 5:
        w.update()
        time.sleep(0.01)
    shown, pos = st.frames_shown, st.t_rel
    st.toggle_play()                                          # pause
    w.update()
    assert not errors, errors
    assert shown >= 20, f"only {shown} frames were shown in 5 s"
    assert pos > 1.0, f"the position did not move ({pos})"
    assert not st.playing
    w.destroy()
    return f"pro export 8 s -> {d:.1f}s at 2x; live player showed {shown} frames, reached {pos:.1f}s in 5 s"


def _viral_movie():
    """72 s test movie with a caption file next to it (like a YouTube download)."""
    vm = os.path.join(tmp, "viral_talk.mp4")
    if not os.path.isfile(vm):
        subprocess.run(["ffmpeg", "-nostdin", "-y", "-v", "error", "-stream_loop", "5", "-i", movie, "-c", "copy", vm],
                       check=True)
        words = ("this is the moment everyone was waiting for and nobody believed it would happen but here we are "
                 "today laughing together").split()
        ts = lambda x: f"{int(x // 3600):02d}:{int(x % 3600 // 60):02d}:{x % 60:06.3f}"
        lines, t, k = ["WEBVTT", "Kind: captions", "Language: en", ""], 0.0, 0
        while t < 70:
            ws = [words[(k + i) % len(words)] for i in range(4)]
            k += 4
            body = ws[0] + "".join(f"<{ts(t + 0.5 * (i + 1))}><c> {w}</c>" for i, w in enumerate(ws[1:]))
            lines += [f"{ts(t)} --> {ts(t + 2)} align:start position:0%", body, ""]
            t += 2.0
        with open(os.path.join(tmp, "viral_talk.en.vtt"), "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
    return vm


def t_viral_engine():
    """Viral Clips engine: captions file -> built-in scoring -> export with captions + hook + kit; the three
    layouts render; the AI services (OpenAI-style, Gemini, Claude) through a local stand-in server; faces."""
    import json, threading, http.server
    import engine as E
    import viral as V
    vm = _viral_movie()
    words = V.parse_subtitles(V.find_subtitles(vm)[0])
    assert len(words) > 100 and words[1][1] > words[0][1], words[:3]
    cpu = [c for c in E.CODECS if "CPU" in c][0]
    s = E.sanitize({"resolution": "480p", "codec": cpu, "rate_mode": E.RATE_MODES[0], "bitrate": 2000, "aspect": "9:16"})
    o = dict(platform=next(iter(V.PLATFORMS)), count=1, min=8, max=14, part_sec=35, start=0, end=None,
             speech="captions", captions=True, cap_style="Hindi (Devanagari)", cap_pos="Bottom", hook=True,
             hook_style="Yellow box", layout="Normal", boost={"bar": True}, title="viral talk", zip_kit=True)
    out = os.path.join(tmp, "viral_out")
    runner = E.Runner(s, print, None, None)
    info = E.probe_info(vm)
    made = []
    job = V.ViralJob(vm, o, {"provider": "offline"}, log=lambda m: None, on_clip=made.append,
                     export=lambda c: V.export_clip(runner, vm, c, s, o, out, "vt", info))
    job.run()
    assert len(made) == 2 and all(c.get("file") and os.path.isfile(c["file"]) for c in made), made
    for c in made:
        for ext in ("_cover.jpg", "_post.txt", "_kit.zip"):
            assert os.path.isfile(os.path.splitext(c["file"])[0] + ext), ext
    assert made[1]["start"] >= 34, "part 2's clip must come from part 2"
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                        "-of", "csv=p=0", made[0]["file"]], capture_output=True, text=True).stdout.strip()
    assert r == "480,854", r
    # layouts
    lays = [V.plan_speaker([(t, [(0.2 + 0.01 * t, 0.4, 0.1, 0.15)]) for t in range(10, 30)]),
            V.plan_facecam([(t, [(0.85, 0.15, 0.08, 0.12)]) for t in range(10, 30)]),
            V.plan_interview([(t, [(0.25, 0.4, 0.1, 0.15), (0.75, 0.42, 0.1, 0.15)]) for t in range(10, 30)])]
    assert [l["mode"] for l in lays] == ["speaker", "facecam", "interview"], lays
    for k, lay in enumerate(lays):
        f = os.path.join(tmp, f"lay{k}.mp4")
        assert runner.cut(vm, 10, 4, f, info, None, dict(s, _layout=lay)), lay
    assert V.faces_available() or os.name != "nt", "face finding (OpenCV) missing"
    faces = V.sample_faces(vm, 0, 6, 2.0, info=info) if V.faces_available() else [1, 2]
    assert len(faces) >= 2, faces
    # AI services through a stand-in server
    seen = {}

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
            seen[self.path.split("?")[0]] = 1
            clips = {"clips": [{"start": 10, "end": 22, "score": 88, "title": "Big moment", "hook": "Wait for it",
                                "description": "Test.", "hashtags": ["movie", "#clip"]}]}
            if "generateContent" in self.path:
                parts = json.loads(body)["contents"][0]["parts"]
                if any("inline_data" in p for p in parts):
                    out = {"segments": [{"start": i * 4, "end": i * 4 + 3.5, "text": f"line {i} here."} for i in range(8)]}
                else:
                    out = {"ok": True} if '{"ok": true}' in parts[0]["text"] else clips
                d = {"candidates": [{"content": {"parts": [{"text": json.dumps(out)}]}}]}
            elif self.path.endswith("/messages"):
                d = {"content": [{"type": "text", "text": json.dumps(clips)}], "usage": {"input_tokens": 5, "output_tokens": 1}}
            elif self.path.endswith("/audio/transcriptions"):
                d = {"words": [{"word": f"w{i}", "start": i * 0.4, "end": i * 0.4 + 0.3} for i in range(80)]}
            else:
                d = {"choices": [{"message": {"content": json.dumps(clips)}}]}
            b = json.dumps(d).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    res = []
    for ai, speech in [({"provider": "custom", "base": base + "/v1", "stt": "whisper-1"}, "cloud"),
                       ({"provider": "gemini", "base": base + "/v1beta", "key": "k"}, "gemini"),
                       ({"provider": "anthropic", "base": base + "/v1", "key": "k"}, "captions")]:
        got = []
        V.ViralJob(vm, dict(o, speech=speech, end=35), ai, log=lambda m: None, on_clip=got.append).run()
        assert got and got[0]["title"] == "Big moment" and "#movie" in got[0]["hashtags"], (ai, got)
        res.append(ai["provider"])
    assert V.test_key({"provider": "gemini", "base": base + "/v1beta", "key": "k"})
    srv.shutdown()
    return f"2 clips with captions + hook + kit; 3 layouts; faces sampled; AI: {', '.join(res)}"


def t_viral_window():
    """The Viral Clips tab as the user does it: movie, FIND VIRAL CLIPS (every clip exported as found), then the
    Export button of the same tab exports the ticked clips again with the tab's colour; the project keeps it."""
    import time
    import app as A
    import engine as E
    import viral_ui as VU
    vm = _viral_movie()
    w = A.App()
    w.update()
    st = w.viral
    tabs = list(st.right._tab_dict.keys())
    for t in ("AI Clips", "Aspect & Crop", "Colour", "Overlay", "Text", "Silence", "Speed & Effects", "Export", "Dialogue"):
        assert t in tabs, (t, tabs)
    msgs = []
    for m in ("showerror", "showwarning", "showinfo"):
        setattr(VU.messagebox, m, lambda *a, **k: msgs.append(a))
    VU.messagebox.askyesno = lambda *a, **k: True
    st.load_movie(vm)
    st.cfg.update(codec=[c for c in E.CODECS if "CPU" in c][0], resolution="480p", rate_mode=E.RATE_MODES[0],
                  bitrate=2000, brightness=0.1)
    st.sync_export = lambda: None
    vv = st.vv
    vv["provider"].set(VU.V.PROVIDERS["offline"]["label"])
    vv["speech"].set(VU.V.SPEECH["captions"])
    for k, v in (("count", "1"), ("min", "8"), ("max", "14"), ("part_min", "0.6")):
        vv[k].set(v)
    vv["layout"].set("Follow the speaker")
    st.v_start(False)
    assert not msgs, msgs
    t0 = time.time()
    while st.vjob is not None and time.time() - t0 < 600:
        w.update()
        time.sleep(0.05)
    log = st.v_log.get("1.0", "end")
    assert st.vjob is None, "viral clips did not finish:\n" + log[-1500:]
    assert len(st.parts) >= 2 and all(p.get("viral") for p in st.parts), (st.parts, log[-1500:])
    out = st.out_dir_for(False)
    files = sorted(f for f in os.listdir(out) if f.endswith(".mp4"))
    assert len(files) == len(st.parts), (files, log[-1500:])
    # the still preview and the Export button (exports the ticked clips again)
    st.select_part(0)
    w.update()
    for p in st.parts[1:]:
        p["on"] = False
    st.done_names = set()
    st.export()
    t0 = time.time()
    while st.eng is not None and time.time() - t0 < 300:
        w.update()
        time.sleep(0.05)
    elog = st.exp_log.get("1.0", "end")
    assert st.eng is None and "Saved:" in elog, elog[-1500:]
    state = st.get_state()
    assert state["viral"]["layout"] == "Follow the speaker" and state["parts"][0]["viral"]["title"]
    w.destroy()
    return f"{len(st.parts)} clips found + exported ({', '.join(files)[:120]}); Export again OK"


def _pump(w, sec, until=None):
    import time
    t0 = time.time()
    while time.time() - t0 < sec:
        w.update()
        if until is not None and until():
            return True
        time.sleep(0.03)
    return until() if until is not None else True


def _dur(p):
    return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", p],
                                capture_output=True, text=True).stdout.strip() or 0)


def t_audio_tracks():
    """MKVToolNix-style tracks: 3 languages + subtitles -> keep 2, Tamil first and default, from the window too."""
    import app as A
    import tracks as T
    import tracks_ui as TU
    srt = os.path.join(tmp, "tr.srt")
    with open(srt, "w", encoding="utf-8") as f:
        f.write("1\n00:00:01,000 --> 00:00:03,000\nHello there\n")
    multi = os.path.join(tmp, "multi_lang.mkv")
    subprocess.run(["ffmpeg", "-nostdin", "-y", "-v", "error", "-i", movie, "-f", "lavfi", "-i", "sine=f=500:d=12",
                    "-f", "lavfi", "-i", "sine=f=800:d=12", "-i", srt, "-map", "0:v", "-map", "0:a", "-map", "1:a",
                    "-map", "2:a", "-map", "3", "-c:v", "copy", "-c:a", "aac", "-c:s", "srt",
                    "-metadata:s:a:0", "language=hin", "-metadata:s:a:1", "language=eng", "-metadata:s:a:2",
                    "language=tam", "-shortest", multi], check=True)
    tr, d = T.probe(multi)
    assert [t["lang"] for t in tr if t["type"] == "audio"] == ["hin", "eng", "tam"], tr
    w = A.App()
    w.update()
    st = w.simple
    st.load_movie(multi)
    win = TU.TracksWindow(st, multi, lambda p: st.load_movie(p))
    _pump(w, 0.5)
    hin = [t["index"] for t in tr if t["lang"] == "hin"][0]
    tam = [t["index"] for t in tr if t["lang"] == "tam"][0]
    win.keep[hin].set(False)
    win.main.set(tam)
    win.name[tam].set("Tamil main")
    win.save()
    ok = _pump(w, 60, lambda: st.movie != multi)
    assert ok, "the new file was not made / opened: " + win.status.cget("text")
    t2, _ = T.probe(st.movie)
    auds = [t for t in t2 if t["type"] == "audio"]
    assert [t["lang"] for t in auds] == ["tam", "eng"] and auds[0]["default"] and auds[0]["title"] == "Tamil main", auds
    assert any(t["type"] == "subtitle" for t in t2)
    one = T.save_track(multi, [t for t in tr if t["type"] == "audio"][1])
    assert os.path.getsize(one) > 1000
    w.destroy()
    return f"{os.path.basename(st.movie)}: Tamil (main) + English kept, Hindi removed, subtitle kept; one track saved alone"


def t_captions():
    """Captions from an SRT next to the movie: found, switched on, in the preview / plans / export, many styles."""
    import app as A
    import engine as E
    import captions as CAP
    import shutil as SH
    cm = os.path.join(tmp, "cap_movie.mp4")
    SH.copyfile(movie, cm)
    with open(os.path.join(tmp, "cap_movie.srt"), "w", encoding="utf-8") as f:
        f.write("1\n00:00:01,000 --> 00:00:04,000\n<i>Ye hai woh pal</i> jiska sabko intezaar tha\n\n"
                "2\n00:00:05,000 --> 00:00:08,000\nNobody believed it would happen\n")
    w = A.App()
    w.update()
    st = w.simple
    st.load_movie(cm)
    assert st.cap.get("file", "").endswith("cap_movie.srt") and len(st.cap_cues) == 2, st.cap
    st.cap_v["on"].set(True)
    st.cap_v["style"].set("Neon glow")
    st.cap_changed()
    st.parts = [{"on": True, "sil": True, "ov": True, "start": 0.5, "end": 9.0, "label": ""}]
    st.part_idx, st.t_rel = 0, 1.5
    ps = st.preview_settings(st.parts[0])
    assert ps.get("_captions") and ps["_captions"]["words"], "no captions in the preview"
    st.shown = -1
    st.render_now()
    assert _pump(w, 30, lambda: st.shown >= 0), "the still preview did not come"
    plans = st.build_plans([(0, st.parts[0])])
    assert plans[0]["extra"].get("_captions")
    cpu = [c for c in E.CODECS if "CPU" in c][0]
    s = E.sanitize({"resolution": "480p", "codec": cpu, "rate_mode": E.RATE_MODES[0], "bitrate": 2000, "aspect": "9:16"})
    r = E.Runner(s, lambda *_: None, None, None)
    info = E.probe_info(cm)
    names = list(CAP.STYLES)
    for k, (style, mode) in enumerate([(names[0], "word"), ("Bubble (white box)", "word"), ("Typewriter", "word"),
                                       ("Hindi neon", "word"), ("Cinema", "line")]):
        cap = CAP.for_range(dict(st.cap_full(), style=style, mode=mode), 0.5, 9.0)
        out = os.path.join(tmp, f"cap{k}.mp4")
        assert r.cut(cm, 0.5, 8.5, out, info, None, dict(s, _captions=cap)), style
        # the same with pieces (Auto Short / dialogue cut)
        out2 = os.path.join(tmp, f"capp{k}.mp4")
        assert r.cut(cm, 0.5, 5, out2, info, None, dict(s, _captions=cap), pieces=[(5.0, 2.5), (1.0, 2.5)]), style
    w.destroy()
    return f"SRT found next to the movie, preview + plans + export OK; {len(CAP.STYLES)} styles, 5 checked (also in pieces)"


def t_short_editor():
    """Auto Short review: a planned short is checked and edited on the timeline (split, delete, drag an edge to
    bring back, bring back a cut part, move, undo / redo, play), then exported from the list."""
    import app as A
    import engine as E
    import auto_short_ui as AU
    import auto_short as AS
    from short_model import ShortModel
    w = A.App()
    w.update()
    sm, af = w.simple, w.auto_short
    errs = []
    AU.messagebox.showerror = lambda *a, **k: errs.append(a)
    sm.load_movie(movie)
    sm.cfg.update(codec=[c for c in E.CODECS if "CPU" in c][0], resolution="480p", rate_mode=E.RATE_MODES[0], bitrate=2000)
    sm.sync_export = lambda: None
    af.review.set(True)
    # review mode of the job: shorts are planned, not exported
    planned = []
    job = AS.AutoShortJob(movie, [(0, 12)], {}, E.sanitize(dict(sm.cfg)), [], os.path.join(tmp, "as_rev"),
                          lambda *_: None, lambda *a: None, planned.append, min_len=3, max_len=5, review=True)
    job.prepare()
    assert job.render([(1.0, 2.0), (4.0, 2.5)]) and planned and planned[0]["planned"], planned
    assert not os.path.exists(planned[0]["path"])
    af.out_dir = os.path.join(E.OUTPUT_DIR, f"{sm.file_base()}_auto_short")
    d = dict(number=7, name="x.mp4", path=os.path.join(af.out_dir, "x.mp4"), planned=True, start=1.0,
             pieces=[[1.0, 2.0], [4.0, 3.0], [8.0, 2.0]], auto_pieces=[[1.0, 2.0], [4.0, 3.0], [8.0, 2.0]])
    af.add_plan_row(d)
    assert af.exp_all_btn.cget("state") == "normal"
    af.open_editor(d)
    ed = af.editor
    _pump(w, 1.0)
    m = ed.m
    assert abs(m.total - 7.0) < 0.01
    assert _pump(w, 30, lambda: ed.shown >= 0), "no still picture in the editor"
    ed.seek(1.0)
    ed.do_split()
    assert len(m.p) == 4, m.p
    ed.sel = 1
    ed.do_delete()
    assert len(m.p) == 3 and abs(m.total - 6.0) < 0.01, m.p
    ed.do_undo()
    assert len(m.p) == 4
    ed.do_redo()
    # drag the right edge of the last piece 40 px to the right: brings back what came after it
    ed.update()

    class Ev:
        pass
    e = Ev()
    e.x, e.y = int(ed.tl_x(m.total)) - 2, 60
    before = m.total
    ed.tl_down(e)
    e.x += 40
    ed.tl_move(e)
    ed.tl_up(e)
    assert m.total > before + 0.2, (before, m.total, m.p)
    # bring back a cut part chosen on the movie strip
    gaps = m.gaps(*ed.span)
    ed.gap_sel = [g for g in gaps if g[0] >= 2.0][0]
    n0 = m.total
    ed.do_bring_back()
    assert m.total > n0, m.p
    ed.sel = 0
    ed.do_move(1)
    # play a little
    ed.seek(0)
    ed.start_play()
    _pump(w, 4.0)
    shown = getattr(ed, "frames_shown", 0)
    ed.stop_play()
    assert shown > 5, f"the editor played only {shown} frames ({ed.player.error[-200:]})"
    final = m.total
    ed.save(True)
    assert _pump(w, 300, lambda: d.get("exported")), "the edited short was not exported"
    got = _dur(d["path"])
    assert abs(got - final) < 0.6, (got, final)
    # the project can be saved and opened again with reviewed shorts in the list (Save did not work before)
    import project as PRJ
    pf = os.path.join(tmp, "with_plans.ccproj")
    PRJ.save(pf, w.collect_state())
    w.apply_state(PRJ.load(pf))
    assert af.plans and af.plans[0]["pieces"], "the planned shorts were not restored"
    assert not errs, errs
    w.destroy()
    return f"planned (not exported) -> split / delete / undo / drag edge / bring back / move / play ({shown} frames) -> exported {got:.1f}s"


def t_cc_presets():
    """CC presets (HDR CC ...), vibrance / HDR detail / split toning, a .cube LUT with strength, before / after."""
    import numpy as np
    import app as A
    import engine as E
    import colour as CL
    import preview as P
    cube = os.path.join(tmp, "warm.cube")
    n = 9
    with open(cube, "w") as f:
        f.write(f"TITLE \"warm\"\nLUT_3D_SIZE {n}\n")
        for b in range(n):
            for g in range(n):
                for r in range(n):
                    f.write(f"{min(1, r / (n - 1) * 1.1):.5f} {g / (n - 1):.5f} {b / (n - 1) * 0.85:.5f}\n")
    info = E.probe_info(movie)
    cpu = [c for c in E.CODECS if "CPU" in c][0]
    base = dict(resolution="480p", codec=cpu, rate_mode=E.RATE_MODES[0], bitrate=3000)
    r = E.Runner(E.sanitize(base), lambda *_: None, None, None)
    means = {}
    for k, name in enumerate(["HDR CC", "HDR CC warm (games / trailers)", "Teal & Orange (cinematic)", "Black & white HDR"]):
        cfg = {key: CL.to_cfg(key, v) for key, v in CL.preset_ui(name).items()}
        S = E.sanitize(dict(base, **cfg))
        out = os.path.join(tmp, f"cc{k}.mp4")
        assert r.cut(movie, 1, 2, out, info, None, S), name
        img = P.compose(movie, 1.5, S, info)
        means[name] = float(np.asarray(img.convert("RGB"), dtype=np.float32).mean())
    for mix in (0.5, 1.0):
        S = E.sanitize(dict(base, lut_path=cube, lut_mix=mix))
        assert r.cut(movie, 1, 2, os.path.join(tmp, f"lut{mix}.mp4"), info, None, S), mix
    a = np.asarray(P.compose(movie, 1.5, E.sanitize(dict(base, lut_path=cube)), info).convert("RGB"), dtype=np.float32)
    b0 = np.asarray(P.compose(movie, 1.5, E.sanitize(base), info).convert("RGB"), dtype=np.float32)
    assert a[..., 2].mean() < b0[..., 2].mean() - 3, "the LUT did not change the preview"
    cmp_img = P.compose(movie, 1.5, dict(E.sanitize(dict(base, **{k: CL.to_cfg(k, v) for k, v in CL.preset_ui("HDR CC").items()})),
                                         _compare=True), info)
    assert cmp_img.size[0] > 100
    w = A.App()
    w.update()
    st = w.simple
    st.load_movie(movie)
    st.apply_cc_preset("HDR CC")
    assert st.cfg["hdr"] > 0.3 and st.cfg["vibrance"] > 0.3, {k: st.cfg[k] for k in ("hdr", "vibrance")}
    st.cc_strength.set(50)
    st.apply_cc_preset("HDR CC")
    assert abs(st.cfg["hdr"] - 0.25) < 0.02, st.cfg["hdr"]
    w.prefs.setdefault("cc_presets", {})["Mine"] = {"warmth": 40}
    st.cc_fill_grid()
    st.apply_cc_preset("Mine")
    assert st.cfg["warmth"] > 0.1 and st.cfg["hdr"] == 0.0
    st.cc_compare.set(True)
    st.shown = -1
    st.render_now()
    assert _pump(w, 30, lambda: st.shown >= 0), "no before / after preview"
    del w.prefs["cc_presets"]["Mine"]
    w.destroy()
    return f"{len(CL.PRESETS)} presets; 4 exported; LUT 50% / 100% OK; before / after preview OK"


def t_preview_quality():
    """Preview quality Full / 1/2 / 1/4 / 1/8: Play works at every setting (smaller = faster), the still picture
    follows, one setting for every tab, remembered in the settings."""
    import time
    import app as A
    import engine as E
    import pq
    import preview as P
    info = E.probe_info(movie)
    sizes, speed = {}, {}
    for name, q in pq.QUALITIES.items():
        s = E.sanitize({"resolution": "1080p", "aspect": "9:16", "fit_mode": "Blur background", "_pq": q, "_fast": True})
        live = dict(box=(2000, 2000), wav=os.path.join(tmp, "pq.wav"))
        cmd, _ = E.build_command(movie, 0.0, 4.0, "-", s, info, None, live=live)
        t0 = time.time()
        r = subprocess.run(cmd, capture_output=True, creationflags=E.NOWIN)
        n = len(r.stdout) // (live["w"] * live["h"] * 3)
        assert n > 50, (name, n, r.stderr[-300:])
        sizes[name] = (live["w"], live["h"])
        speed[name] = n / max(0.01, time.time() - t0)
        img = P.compose(movie, 1.0, s, info)
        assert img.size[1] > 100
    assert sizes["Full"][1] == 1920 and sizes["1/2"][1] == 960 and sizes["1/4"][1] == 480 and 230 <= sizes["1/8"][1] <= 250, sizes
    w = A.App()
    w.update()
    st = w.simple
    st.load_movie(movie)
    st.parts = [{"on": True, "sil": True, "ov": True, "start": 0.0, "end": 10.0, "label": ""}]
    st.select_part(0)
    pq.set_value("1/8")
    assert w.prefs.get("preview_quality") == "1/8"
    st.frames_shown = 0
    st.toggle_play()
    _pump(w, 3.0)
    small = st.player.live.get("h")
    pq.set_value("1/2")                                   # while playing: restarts at the new quality
    _pump(w, 3.0)
    big = st.player.live.get("h")
    shown = st.frames_shown
    st.toggle_play()
    assert small and big and big > small and shown > 20, (small, big, shown)
    pq.set_value(pq.DEFAULT)
    w.destroy()
    return "frames/s: " + ", ".join(f"{k} {v:.0f}" for k, v in speed.items()) + f"; play switched {small}p -> {big}p"


def t_smart_edit():
    """Auto Short AI smart edit: words heard (stand-in speech + AI service), silence cut between words with breaths
    kept, AI cut of a stammered line, AI captions in Devanagari on the shorts, every switch saved in the project."""
    import json, threading, http.server
    import app as A
    import engine as E
    import auto_short as AS
    import smartcut as SCX
    sc = SCX.SmartCut(dict(smart=True, fillers=True, ai_cut=False, captions=True), {"provider": "offline"}, print)
    words = [("Hello", 1.0, 1.3), ("there", 1.4, 1.7), ("umm", 2.6, 2.9), ("friend.", 3.0, 3.4), ("This", 5.0, 5.2),
             ("is", 5.25, 5.4), ("great.", 5.5, 5.9)]
    regs, cw = sc.refine([(0.8, 6.2)], words, 0, 10)
    assert len(regs) == 3 and regs[0][1] < 2.6 and all(not (r[0] < 2.75 < r[1]) for r in regs), regs
    seen = {}

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length") or 0))
            seen[self.path] = seen.get(self.path, 0) + 1
            if self.path.endswith("/audio/transcriptions"):
                ws, t = [], 0.2
                for k in range(60):
                    ws.append({"word": ("umm" if k % 15 == 7 else f"w{k}") + ("." if k % 6 == 5 else ""),
                               "start": t, "end": t + 0.3})
                    t += 0.45 if k % 6 != 5 else 1.2
                d = {"words": ws}
            else:
                d = {"choices": [{"message": {"content": json.dumps({"cut": [1], "lines": [{"id": 0, "text": "नमस्ते दोस्तों"}]})}}]}
            o = json.dumps(d).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(o)))
            self.end_headers()
            self.wfile.write(o)
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}/v1"
    cpu = [c for c in E.CODECS if "CPU" in c][0]
    s = E.sanitize({"resolution": "480p", "codec": cpu, "rate_mode": E.RATE_MODES[0], "bitrate": 2000, "aspect": "9:16"})
    vm = _viral_movie()
    got = []
    opts = dict(denoise=False, vad=True, smart_edit=dict(smart=True, ai_cut=True, fillers=True, captions=True,
                                                          script="Hindi (Devanagari)", speech="cloud",
                                                          cap_style="Hindi neon"),
                ai={"provider": "custom", "base": base, "stt": "whisper-1"})
    job = AS.AutoShortJob(vm, [(0, 40)], opts, s, [], os.path.join(tmp, "as_smart"), lambda *_: None,
                          lambda *a: None, got.append, min_len=8, max_len=14, review=True)
    job.run()
    srv.shutdown()
    assert seen.get("/v1/audio/transcriptions") and seen.get("/v1/chat/completions"), seen
    assert got and got[0].get("words"), got[:1]
    assert any("नमस्ते" in w[0] for w in got[0]["words"]), got[0]["words"][:5]
    S = job.settings_for([tuple(p) for p in got[0]["pieces"]], 1, got[0]["words"])
    assert S.get("_captions") and S["_captions"]["style"] == "Hindi neon"
    path = job.export_planned([tuple(p) for p in got[0]["pieces"]], got[0]["number"], words=got[0]["words"])
    assert path and os.path.isfile(path)
    # the switches in the window, saved with the project
    w = A.App()
    w.update()
    af = w.auto_short
    af.ai_v["smart"].set(True)
    af.ai_v["captions"].set(True)
    af.ai_v["script"].set("Hinglish (Roman letters)")
    st = af.get_state()
    af.ai_v["smart"].set(False)
    af.set_state(st)
    assert af.ai_v["smart"].get() and af.smart_opts()["script"] == "Hinglish (Roman letters)"
    w.destroy()
    return f"refine OK; {len(got)} short(s) planned with AI cut + Devanagari captions; exported; switches saved"


def t_youtube():
    """yt-dlp + deno are in the folder. A real YouTube download is tried; YouTube often blocks cloud machines, so a
    refusal there is only reported."""
    import ytdl
    assert ytdl.available(), "yt-dlp missing"
    deno = os.path.join(ytdl.BASE, "deno", "deno.exe")
    assert os.path.isfile(deno), "deno.exe missing"
    import yt_dlp
    try:
        p = ytdl.download("https://www.youtube.com/watch?v=jNQXAC9IVRw", 360)
        ok = f"downloaded {os.path.basename(p)} ({os.path.getsize(p) // 1024} KB)"
        os.remove(p)
    except Exception as e:
        ok = "YouTube refused this cloud machine (normal on CI): " + str(e)[:160]
    return f"yt-dlp {yt_dlp.version.__version__}; {ok}"


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
    import viral as V
    heard = V.Listener("local", {}, "en", "small", print).listen(movie, 0.0, 10.0)
    assert isinstance(heard, list), heard
    return f"bundled model loads offline; Viral Clips listening with word times works ({len(heard)} words in a tone)"


step("ffmpeg + test movie", t_ffmpeg)
step("all modules import", t_modules)
step("silence scan of only the start of parts", t_silence_windows)
step("window and Cutting ON/OFF switches", t_window)
step("Simple Edit: export button, 2 parts", t_simple_export_in_window)
step("Simple Edit: clean start + overlay only on ticked videos", t_clean_start_and_overlay_flags)
step("Simple Edit: stop + continue, text per video", t_resume_and_text_per_video)
step("word colour, clean end, auto short ends", t_word_colour_and_clean_end)
step("CapCut text options (styles, effects, animations)", t_capcut_text)
step("pro edit (rotate, crop, speed, effects) + live player", t_pro_edit_and_player)
step("Viral Clips engine (captions, hook, layouts, AI services, kit)", t_viral_engine)
step("Viral Clips tab (find + export as found, Export again, project)", t_viral_window)
step("Audio tracks: keep / remove languages (MKVToolNix style)", t_audio_tracks)
step("Captions from SRT (styles, preview, export, pieces)", t_captions)
step("Auto Short: check + edit on the timeline before export", t_short_editor)
step("CC presets (HDR CC, LUT, before / after)", t_cc_presets)
step("Preview quality (Full / 1/2 / 1/4 / 1/8)", t_preview_quality)
step("Auto Short AI smart edit (cut by words, AI captions)", t_smart_edit)
step("YouTube link download (yt-dlp + deno)", t_youtube)
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
