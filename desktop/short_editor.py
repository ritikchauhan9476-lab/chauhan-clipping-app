"""Short editor (Auto Short review): see a short before it is exported and edit it on a timeline, like CapCut.

  MOVIE strip  : the stretch of the movie around the short with its sound wave. Green = in the short, dark = cut out.
                 Click a dark part (or drag over it) and press 'Bring back' to put it back.
  SHORT timeline: the pieces one after another. Click = move the playhead. Drag a piece's EDGE outward to bring
                 back what was cut there (inward to cut more). Drag a piece's middle to move it. Split (S),
                 Delete (Del), Undo (Ctrl+Z), Redo (Ctrl+Y), Play / Pause (Space), arrows = step.
The preview shows the short with every edit (colour, crop, text, captions ...); Play plays it with sound.
"""
import tkinter as tk

import numpy as np
import customtkinter as ctk
from PIL import Image, ImageTk

import captions as CAP
import engine as E
import player as PL
import pq
import preview as P
from short_model import ShortModel
from widgets import NEON, GREY, TEXT, QUIET, QUIET_H, DANGER, DANGER_H

PIECE_COLORS = ("#2E7D5B", "#2B6CB0", "#8E5BB5", "#B7791F", "#2C7A7B", "#9B2C2C")


def tstr(t):
    t = max(0.0, float(t))
    return f"{int(t // 60):02d}:{t % 60:04.1f}"


class ShortEditor(ctk.CTkToplevel):
    def __init__(self, master, movie, short, job, on_save, min_len=45.0, max_len=59.0):
        """short: the planned short (dict with pieces, auto_pieces, number, name). job: the AutoShortJob that makes
        the settings and exports. on_save(pieces, export_now) is called when the user saves."""
        super().__init__(master)
        self.movie, self.short, self.job, self.on_save = movie, short, job, on_save
        self.min_len, self.max_len = float(min_len), float(max_len)
        self.info = E.probe_info(movie)
        self.m = ShortModel(short["pieces"], self.info["duration"], short.get("auto_pieces"))
        self.title(f"Short {short['number']} - check and edit before export")
        self.geometry("1180x800")
        self.minsize(980, 680)
        self.t = 0.0                     # playhead (short time)
        self.sel = 0                     # selected piece
        self.gap_sel = None              # (a, b) movie stretch chosen on the movie strip
        self.zoom = 1.0
        self.scroll_x = 0.0
        self.drag = None
        self.playing = False
        self.play_after = None
        self.player = PL.LivePlayer()
        self.q_img = None
        self.token, self.shown = 0, -1
        import queue
        self.rq = queue.Queue()          # still pictures from the render thread (tkinter only in this thread)
        self.renderer = P.Renderer(lambda img, tok, err: self.rq.put((img, tok, err)))
        self.wave_ready = False
        self.env = None                  # sound wave of the movie strip
        self.env_span = None
        self.view = None                 # the movie stretch shown on the strip (None = around the short)
        self.span = self.calc_span()
        self.photo = None
        self.render_after = None
        self.build()
        self.bind_keys()
        self.after(50, self.load_wave)
        self.after(120, self.refresh)
        self.after(40, self.poll)
        self.protocol("WM_DELETE_WINDOW", self.close)
        try:
            self.transient(master.winfo_toplevel())
            self.lift()
            self.focus_force()
        except Exception:
            pass

    # ================================================================ layout
    def build(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.grid(row=0, column=0, sticky="nsew", padx=8, pady=(8, 4))
        top.grid_columnconfigure(0, weight=1)
        top.grid_rowconfigure(0, weight=1)
        self.cv = tk.Canvas(top, bg="#000000", highlightthickness=0)
        self.cv.grid(row=0, column=0, sticky="nsew")
        self.cv.bind("<Configure>", lambda e: self.schedule_still())
        side = ctk.CTkFrame(top, width=300)
        side.grid(row=0, column=1, sticky="ns", padx=(8, 0))
        side.grid_propagate(False)
        ctk.CTkLabel(side, text=f"SHORT {self.short['number']}", text_color=NEON,
                     font=ctk.CTkFont(size=15, weight="bold")).pack(anchor="w", padx=10, pady=(10, 2))
        self.len_lbl = ctk.CTkLabel(side, text="", anchor="w", justify="left", wraplength=280)
        self.len_lbl.pack(anchor="w", padx=10)
        self.sel_lbl = ctk.CTkLabel(side, text="", text_color=GREY, anchor="w", justify="left", wraplength=280)
        self.sel_lbl.pack(anchor="w", padx=10, pady=(6, 4))
        for text, cmd, kw in (("Split at playhead  (S)", self.do_split, {}),
                              ("Delete piece  (Del)", self.do_delete, dict(fg_color=DANGER, hover_color=DANGER_H)),
                              ("+ Add a new part from the movie", self.do_add_dialog, {}),
                              ("Add the chosen movie part at playhead", self.do_add_chosen, {}),
                              ("Bring back the chosen cut part (in place)", self.do_bring_back,
                               dict(fg_color=QUIET, hover_color=QUIET_H)),
                              ("Move piece left", lambda: self.do_move(-1), dict(fg_color=QUIET, hover_color=QUIET_H)),
                              ("Move piece right", lambda: self.do_move(1), dict(fg_color=QUIET, hover_color=QUIET_H)),
                              ("Undo  (Ctrl+Z)", self.do_undo, dict(fg_color=QUIET, hover_color=QUIET_H)),
                              ("Redo  (Ctrl+Y)", self.do_redo, dict(fg_color=QUIET, hover_color=QUIET_H)),
                              ("Back to the automatic cut", self.do_reset, dict(fg_color=QUIET, hover_color=QUIET_H))):
            ctk.CTkButton(side, text=text, command=cmd, text_color=TEXT, **kw).pack(fill="x", padx=10, pady=3)
        ctk.CTkLabel(side, text="Drag the EDGE of a piece outward to bring back what was cut (the short gets longer, "
                                "the other pieces stay as they are), inward to cut more. Drag the middle of a piece "
                                "to move it. New part: drag over ANY part of the MOVIE strip and press 'Add the "
                                "chosen movie part at playhead', or use '+ Add a new part' with times. The arrows "
                                "above the movie strip move it through the whole movie.", text_color=GREY,
                     wraplength=280, justify="left").pack(anchor="w", padx=10, pady=(8, 4))
        # transport
        tr = ctk.CTkFrame(self, fg_color="transparent")
        tr.grid(row=1, column=0, sticky="ew", padx=8)
        self.play_btn = ctk.CTkButton(tr, text="▶  Play", width=100, command=self.toggle_play)
        self.play_btn.pack(side="left")
        ctk.CTkButton(tr, text="|◀", width=44, fg_color=QUIET, hover_color=QUIET_H, text_color=TEXT,
                      command=lambda: self.seek(0)).pack(side="left", padx=4)
        self.time_lbl = ctk.CTkLabel(tr, text="", width=170)
        self.time_lbl.pack(side="left", padx=8)
        self.mute = tk.BooleanVar(value=False)
        ctk.CTkCheckBox(tr, text="Mute", variable=self.mute, width=70).pack(side="left", padx=4)
        ctk.CTkLabel(tr, text="Zoom", text_color=GREY).pack(side="left", padx=(20, 4))
        ctk.CTkButton(tr, text="-", width=34, command=lambda: self.set_zoom(self.zoom / 1.5)).pack(side="left")
        ctk.CTkButton(tr, text="+", width=34, command=lambda: self.set_zoom(self.zoom * 1.5)).pack(side="left", padx=4)
        ctk.CTkLabel(tr, text="Preview", text_color=GREY).pack(side="left", padx=(16, 2))
        pq.menu(tr, self.pq_changed, width=70).pack(side="left")
        self.note = ctk.CTkLabel(tr, text="", text_color=GREY, anchor="w")
        self.note.pack(side="left", padx=12, fill="x", expand=True)
        # movie strip + short timeline
        mrow = ctk.CTkFrame(self, fg_color="transparent")
        mrow.grid(row=2, column=0, sticky="ew", padx=8, pady=(6, 0))
        ctk.CTkLabel(mrow, text="MOVIE (green = in the short, dark = not in it - drag over it to choose a part)",
                     text_color=GREY, anchor="w", font=ctk.CTkFont(size=11)).pack(side="left", padx=2)
        for txt, cmd in (("Whole movie", self.span_whole), ("Around the short", self.span_reset),
                         ("Zoom in", lambda: self.span_zoom(0.5)), ("Zoom out", lambda: self.span_zoom(2.0)),
                         ("▶", lambda: self.span_shift(0.5)), ("◀", lambda: self.span_shift(-0.5))):
            ctk.CTkButton(mrow, text=txt, width=40 if len(txt) < 3 else 96, height=24, fg_color=QUIET,
                          hover_color=QUIET_H, text_color=TEXT, command=cmd).pack(side="right", padx=2)
        self.strip = tk.Canvas(self, height=70, bg="#15171A", highlightthickness=0)
        self.strip.grid(row=3, column=0, sticky="ew", padx=8)
        ctk.CTkLabel(self, text="SHORT TIMELINE", text_color=GREY, anchor="w",
                     font=ctk.CTkFont(size=11)).grid(row=4, column=0, sticky="w", padx=10, pady=(6, 0))
        self.tl = tk.Canvas(self, height=96, bg="#101215", highlightthickness=0)
        self.tl.grid(row=5, column=0, sticky="ew", padx=8)
        self.hbar = ctk.CTkScrollbar(self, orientation="horizontal", command=self.on_hscroll)
        self.hbar.grid(row=6, column=0, sticky="ew", padx=8)
        for c in (self.strip, self.tl):
            c.bind("<Configure>", lambda e: self.redraw())
        self.strip.bind("<ButtonPress-1>", self.strip_down)
        self.strip.bind("<B1-Motion>", self.strip_move)
        self.strip.bind("<ButtonRelease-1>", self.strip_up)
        self.tl.bind("<ButtonPress-1>", self.tl_down)
        self.tl.bind("<B1-Motion>", self.tl_move)
        self.tl.bind("<ButtonRelease-1>", self.tl_up)
        self.tl.bind("<Motion>", self.tl_hover)
        self.tl.bind("<MouseWheel>", lambda e: self.set_zoom(self.zoom * (1.2 if e.delta > 0 else 1 / 1.2)))
        # bottom
        bot = ctk.CTkFrame(self, fg_color="transparent")
        bot.grid(row=7, column=0, sticky="ew", padx=8, pady=8)
        ctk.CTkButton(bot, text="SAVE + EXPORT THIS SHORT", height=38, font=ctk.CTkFont(size=13, weight="bold"),
                      command=lambda: self.save(True)).pack(side="right", padx=4)
        ctk.CTkButton(bot, text="Save changes", height=38, command=lambda: self.save(False)).pack(side="right", padx=4)
        ctk.CTkButton(bot, text="Cancel", height=38, fg_color=QUIET, hover_color=QUIET_H, text_color=TEXT,
                      command=self.close).pack(side="right", padx=4)

    def bind_keys(self):
        self.bind("<space>", lambda e: self.toggle_play())
        self.bind("<s>", lambda e: self.do_split())
        self.bind("<S>", lambda e: self.do_split())
        self.bind("<Delete>", lambda e: self.do_delete())
        self.bind("<Control-z>", lambda e: self.do_undo())
        self.bind("<Control-y>", lambda e: self.do_redo())
        self.bind("<Left>", lambda e: self.seek(self.t - 0.1))
        self.bind("<Right>", lambda e: self.seek(self.t + 0.1))
        self.bind("<Home>", lambda e: self.seek(0))

    # ================================================================ geometry helpers
    def calc_span(self):
        if self.view:
            return self.view
        lo = min(s for s, _ in self.m.p)
        hi = max(e for _, e in self.m.p)
        pad = max(10.0, (hi - lo) * 0.15)
        return max(0.0, lo - pad), min(self.info["duration"], hi + pad)

    def strip_x(self, src):
        a, b = self.span
        w = max(10, self.strip.winfo_width())
        return (src - a) / max(0.01, b - a) * w

    def strip_t(self, x):
        a, b = self.span
        w = max(10, self.strip.winfo_width())
        return a + x / w * (b - a)

    def px_per_sec(self):
        w = max(10, self.tl.winfo_width())
        return w / max(1.0, self.m.total * 1.08) * self.zoom

    def tl_x(self, t):
        return 6 + t * self.px_per_sec() - self.scroll_x

    def tl_t(self, x):
        return (x - 6 + self.scroll_x) / self.px_per_sec()

    # ================================================================ sound wave
    # ---------------- moving the movie strip through the movie
    def set_view(self, a, b):
        dur = self.info["duration"]
        L = min(dur, max(5.0, b - a))
        a = min(max(0.0, a), max(0.0, dur - L))
        self.view = (a, a + L)
        self.span = self.view
        self.redraw()
        if L <= 900:
            self.load_wave()
        else:
            self.env = None

    def span_whole(self):
        self.set_view(0.0, self.info["duration"])

    def span_reset(self):
        self.view = None
        self.span = self.calc_span()
        self.redraw()
        self.load_wave()

    def span_zoom(self, k):
        a, b = self.span
        c, L = (a + b) / 2, (b - a) * k
        self.set_view(c - L / 2, c + L / 2)

    def span_shift(self, k):
        a, b = self.span
        L = b - a
        self.set_view(a + L * k, b + L * k)

    def load_wave(self):
        import threading
        a, b = self.span
        if b - a > 900:
            self.env = None
            return
        if self.env is not None and self.env_span == (a, b):
            return
        self.env, self.env_span = None, (a, b)

        def work():
            try:
                x = E.read_audio(self.movie, a, b - a)
                hop = 800                                    # 20 values per second
                n = len(x) // hop
                env = np.sqrt((x[:n * hop].reshape(n, hop) ** 2).mean(axis=1)) if n else np.zeros(1)
                env = env / (np.percentile(env, 98) + 1e-6)
                self.env = np.clip(env, 0, 1)
            except Exception:
                self.env = None
            self.wave_ready = True
        threading.Thread(target=work, daemon=True).start()

    def poll(self):
        """Results of the worker threads, handled in the window's own thread."""
        try:
            while True:
                self.show_still(*self.rq.get_nowait())
        except Exception:
            pass
        if self.wave_ready:
            self.wave_ready = False
            self.redraw()
        try:
            self.poll_after = self.after(40, self.poll)
        except Exception:
            pass

    # ================================================================ drawing
    def refresh(self):
        self.span = self.calc_span() if not self.drag else self.span
        self.redraw()
        self.update_labels()
        self.schedule_still()

    def update_labels(self):
        tot = self.m.total
        ok = self.min_len - 0.5 <= tot <= self.max_len + 0.5
        self.len_lbl.configure(text=f"Length: {tot:.1f} s   ({len(self.m.p)} piece(s))\nTarget: {self.min_len:.0f}-"
                                    f"{self.max_len:.0f} s" + ("" if ok else "   <- outside the target"),
                               text_color=TEXT if ok else "#FFB347")
        if 0 <= self.sel < len(self.m.p):
            s, e = self.m.p[self.sel]
            self.sel_lbl.configure(text=f"Selected piece {self.sel + 1}: movie {tstr(s)} - {tstr(e)} ({e - s:.1f} s)")
        gap = f"   |   chosen cut part: {tstr(self.gap_sel[0])} - {tstr(self.gap_sel[1])}" if self.gap_sel else ""
        self.time_lbl.configure(text=f"{tstr(self.t)} / {tstr(tot)}")
        self.note.configure(text=gap)

    def redraw(self):
        self.draw_strip()
        self.draw_timeline()

    def draw_strip(self):
        c = self.strip
        c.delete("all")
        w, h = max(10, c.winfo_width()), max(10, c.winfo_height())
        a, b = self.span
        c.create_rectangle(0, 0, w, h, fill="#1B1D21", outline="")
        for i, (s, e) in enumerate(self.m.p):
            x0, x1 = self.strip_x(s), self.strip_x(e)
            c.create_rectangle(x0, 0, x1, h, fill="#1F5F3A" if i != self.sel else "#2F8F57", outline="")
        if self.env is not None and len(self.env):
            n = len(self.env)
            step = max(1, int(n / max(1, w)))
            pts = []
            ea = self.env_span[0] if self.env_span else a
            for x in range(0, w, 2):
                k = int((self.strip_t(x) - ea) * 20)
                if 0 <= k < n:
                    v = float(self.env[max(0, k - step // 2):k + step // 2 + 1].max())
                    pts.append((x, v))
            for x, v in pts:
                c.create_line(x, h / 2 - v * h * 0.42, x, h / 2 + v * h * 0.42, fill="#9AA5B1")
        if self.gap_sel:
            g0, g1 = self.strip_x(self.gap_sel[0]), self.strip_x(self.gap_sel[1])
            c.create_rectangle(g0, 1, g1, h - 1, outline="#FFD400", width=2)
        i, src = self.m.locate(self.t)
        x = self.strip_x(src)
        c.create_line(x, 0, x, h, fill="#FF3B3B", width=2)
        for k in range(0, 9):
            tt = a + (b - a) * k / 8
            c.create_text(self.strip_x(tt) + 2, h - 2, text=tstr(tt), fill="#6B7280", anchor="sw", font=("Segoe UI", 8))

    def draw_timeline(self):
        c = self.tl
        c.delete("all")
        w, h = max(10, c.winfo_width()), max(10, c.winfo_height())
        pps = self.px_per_sec()
        full = 12 + self.m.total * pps
        self.scroll_x = max(0.0, min(self.scroll_x, max(0.0, full - w)))
        try:
            self.hbar.set(self.scroll_x / max(full, w), (self.scroll_x + w) / max(full, w))
        except Exception:
            pass
        # ruler
        step = next((s for s in (0.5, 1, 2, 5, 10, 15, 30, 60) if s * pps >= 60), 60)
        t = 0.0
        while t <= self.m.total + step:
            x = self.tl_x(t)
            if -40 < x < w + 40:
                c.create_line(x, 0, x, 8, fill="#4B5563")
                c.create_text(x + 2, 9, text=tstr(t), fill="#6B7280", anchor="nw", font=("Segoe UI", 8))
            t += step
        y0, y1 = 26, h - 8
        acc = 0.0
        for i, (s, e) in enumerate(self.m.p):
            x0, x1 = self.tl_x(acc), self.tl_x(acc + e - s)
            col = PIECE_COLORS[i % len(PIECE_COLORS)]
            c.create_rectangle(x0, y0, x1 - 1, y1, fill=col, outline="#FFD400" if i == self.sel else "#0B0C0E",
                               width=3 if i == self.sel else 1)
            if x1 - x0 > 46:
                c.create_text(x0 + 6, y0 + 4, text=f"{i + 1}", fill="white", anchor="nw", font=("Segoe UI", 9, "bold"))
                c.create_text(x0 + 6, y1 - 4, text=f"{e - s:.1f}s", fill="#E5E7EB", anchor="sw", font=("Segoe UI", 8))
            for xe in (x0 + 3, x1 - 4):                       # edge handles
                c.create_rectangle(xe - 2, y0 + 10, xe + 2, y1 - 10, fill="#F3F4F6", outline="")
            acc += e - s
        if self.drag and self.drag.get("kind") == "move" and self.drag.get("moved"):
            xi = self.drag.get("ins_x")
            if xi is not None:
                c.create_line(xi, y0 - 6, xi, y1 + 4, fill="#FFD400", width=3)
        x = self.tl_x(self.t)
        c.create_line(x, 0, x, h, fill="#FF3B3B", width=2)
        c.create_polygon(x - 6, 0, x + 6, 0, x, 8, fill="#FF3B3B")

    # ================================================================ still preview
    def settings(self):
        n = self.short["number"]
        return E.sanitize(self.job.settings_for(self.m.as_pieces(), n, self.short.get("words")))

    def schedule_still(self):
        if self.playing:
            return
        if self.render_after:
            self.after_cancel(self.render_after)
        self.render_after = self.after(60, self.render_still)

    def render_still(self):
        self.render_after = None
        s = self.settings()
        i, src = self.m.locate(self.t)
        # the texts and captions that show at this moment of the short, timed around this movie moment
        texts = []
        for tx in s.get("texts") or []:
            if tx["start"] <= self.t < (tx["end"] if tx["end"] > tx["start"] else 1e9):
                texts.append(dict(tx, start=src - 0.01, end=src + 0.5))
        cap = s.pop("_captions", None)
        if cap:
            starts = self.m.starts()
            pieces = self.m.as_pieces()

            def map_t(x):
                for (a, d), st in zip(pieces, starts):
                    if a - 0.01 <= x <= a + d + 0.01:
                        return st + min(max(0.0, x - a), d)
                return None
            lo, hi = min(a for a, _ in pieces), max(a + d for a, d in pieces)
            for t0, t1, text in CAP.events(cap, lo, hi, map_t):
                if t0 <= self.t < t1:
                    texts.append(dict(CAP.item(cap, text), start=src - 0.01, end=src + 0.5))
                    break
        s["texts"] = texts
        s["overlays"] = [dict(o, start=src - 0.01, end=src + 0.5) for o in (s.get("overlays") or [])
                         if o["start"] <= self.t < (o["end"] if o["end"] > o["start"] else 1e9)]
        for k in ("_boost", "_denoise", "_joint_fade"):
            s.pop(k, None)
        s["_pq"] = pq.factor()
        self.token += 1
        self.renderer.submit(self.movie, min(src, self.info["duration"] - 0.05), s, self.token)

    def show_still(self, img, tok, err):
        if tok < self.shown or self.playing:
            return
        self.shown = tok
        if err or img is None:
            self.cv.delete("all")
            self.cv.create_text(10, 10, text="Preview error: " + str(err)[-200:], fill="white", anchor="nw")
            return
        self.draw_image(img)

    def draw_image(self, img):
        cw, ch = max(50, self.cv.winfo_width()), max(50, self.cv.winfo_height())
        r = min(cw / img.width, ch / img.height)
        im = img.resize((max(1, int(img.width * r)), max(1, int(img.height * r))), Image.BILINEAR)
        self.photo = ImageTk.PhotoImage(im)
        self.cv.delete("all")
        self.cv.create_image(cw // 2, ch // 2, image=self.photo)

    # ================================================================ playing
    def pq_changed(self):
        try:
            if not self.winfo_exists():
                return
        except Exception:
            return
        if self.playing:
            self.stop_play()
            self.start_play()
        else:
            self.schedule_still()

    def toggle_play(self):
        if self.playing:
            self.stop_play()
        else:
            self.start_play()

    def start_play(self):
        if self.t >= self.m.total - 0.2:
            self.t = 0.0
        pieces = self.m.as_pieces()
        starts = self.m.starts()
        sub = []                                     # the pieces from the playhead on
        for (a, d), st in zip(pieces, starts):
            if st + d <= self.t:
                continue
            off = max(0.0, self.t - st)
            sub.append((a + off, d - off))
        if not sub:
            return
        s = self.settings()
        t0 = self.t
        s["texts"] = [dict(x, start=max(0.0, x["start"] - t0), end=(x["end"] - t0) if x["end"] > 0 else 0)
                      for x in s.get("texts") or [] if (x["end"] <= 0 or x["end"] > t0)]
        s["overlays"] = [dict(x, start=max(0.0, x["start"] - t0), end=(x["end"] - t0) if x["end"] > 0 else 0)
                         for x in s.get("overlays") or [] if (x["end"] <= 0 or x["end"] > t0)]
        s["_pq"] = pq.factor()
        s["_fast"] = True
        s.pop("_denoise", None)
        cw, ch = max(200, self.cv.winfo_width()), max(150, self.cv.winfo_height())
        try:
            self.player.start(self.movie, sub[0][0], sum(d for _, d in sub), s, self.info, (cw, ch),
                              mute=bool(self.mute.get()), pieces=sub)
        except Exception as e:
            self.note.configure(text=f"Could not play: {e}")
            return
        self.play_from = t0
        self.playing = True
        self.play_btn.configure(text="❚❚  Pause")
        self.tick_play()

    def tick_play(self):
        self.play_after = None
        if not self.playing:
            return
        img, t_out, finished = self.player.tick()
        if self.player.error and finished:
            self.note.configure(text="The player stopped: " + self.player.error[-200:])
            self.stop_play()
            return
        if img is not None:
            sp = self.player.live.get("speed", 1.0)
            self.t = min(self.m.total, self.play_from + t_out * sp)
            self.draw_image(img)
            self.draw_timeline()
            self.time_lbl.configure(text=f"{tstr(self.t)} / {tstr(self.m.total)}")
            self.frames_shown = getattr(self, "frames_shown", 0) + 1
        if finished:
            self.stop_play()
            return
        self.play_after = self.after(12, self.tick_play)

    def stop_play(self):
        if self.play_after:
            self.after_cancel(self.play_after)
            self.play_after = None
        self.player.stop()
        if self.playing:
            self.playing = False
            self.play_btn.configure(text="▶  Play")
            self.refresh()

    # ================================================================ edits
    def edited(self):
        self.sel = max(0, min(self.sel, len(self.m.p) - 1))
        self.t = max(0.0, min(self.t, self.m.total))
        self.refresh()

    def seek(self, t):
        if self.playing:
            self.stop_play()
        self.t = max(0.0, min(self.m.total, t))
        self.sel = self.m.locate(self.t)[0]
        self.redraw()
        self.update_labels()
        self.schedule_still()

    def do_split(self):
        self.stop_play()
        k = self.m.split(self.t)
        if k is None:
            self.note.configure(text="Move the playhead inside a piece (not at its edge) to split it.")
            return
        self.sel = k
        self.edited()

    def do_delete(self):
        self.stop_play()
        if self.m.delete(self.sel):
            self.edited()

    def do_move(self, d):
        self.stop_play()
        if 0 <= self.sel + d < len(self.m.p):
            self.sel = self.m.move(self.sel, self.sel + d)
            self.edited()

    def do_bring_back(self):
        self.stop_play()
        if not self.gap_sel:
            self.note.configure(text="First click a dark (cut) part of the MOVIE strip, or drag over it.")
            return
        k = self.m.bring_back(*self.gap_sel)
        self.gap_sel = None
        if k is not None:
            self.sel = min(k, len(self.m.p) - 1)
        self.edited()

    def do_add_chosen(self):
        """The movie part chosen on the strip becomes a new piece at the playhead."""
        self.stop_play()
        if not self.gap_sel:
            self.note.configure(text="First drag over a part of the MOVIE strip (use the arrows / 'Whole movie' to go "
                                     "anywhere in the movie).")
            return
        k = self.m.insert(self.gap_sel[0], self.gap_sel[1], self.t)
        if k is not None:
            self.sel = k
            self.t = self.m.starts()[k]
        self.gap_sel = None
        self.edited()

    def do_add_dialog(self):
        """'+ Add a new part': type the movie times (mm:ss or seconds) and where it goes."""
        self.stop_play()
        win = ctk.CTkToplevel(self)
        win.title("Add a new part")
        win.geometry("420x260")
        win.transient(self)
        a0, b0 = self.gap_sel or (self.m.locate(self.t)[1], min(self.info["duration"], self.m.locate(self.t)[1] + 5))
        ctk.CTkLabel(win, text="Movie part to add (minutes:seconds or seconds)", text_color=TEXT).pack(padx=12,
                                                                                                    pady=(12, 6))
        r = ctk.CTkFrame(win, fg_color="transparent")
        r.pack(padx=12, pady=4)
        ctk.CTkLabel(r, text="From").pack(side="left")
        ea = ctk.CTkEntry(r, width=110)
        ea.insert(0, tstr(a0))
        ea.pack(side="left", padx=6)
        ctk.CTkLabel(r, text="To").pack(side="left")
        eb = ctk.CTkEntry(r, width=110)
        eb.insert(0, tstr(b0))
        eb.pack(side="left", padx=6)
        where = tk.StringVar(value="At the playhead")
        ctk.CTkOptionMenu(win, values=["At the playhead", "At the start", "At the end"], variable=where).pack(pady=6)
        msg = ctk.CTkLabel(win, text="", text_color="#FFB347")
        msg.pack()

        def secs(txt):
            txt = txt.strip()
            if ":" in txt:
                parts = [float(x) for x in txt.split(":")]
                v = 0.0
                for x in parts:
                    v = v * 60 + x
                return v
            return float(txt)

        def go():
            try:
                a, b = secs(ea.get()), secs(eb.get())
            except ValueError:
                msg.configure(text="Please type times like 12:30 or 750.")
                return
            if b - a < 0.2:
                msg.configure(text="'To' must be after 'From'.")
                return
            t = {"At the playhead": self.t, "At the start": 0.0, "At the end": None}[where.get()]
            k = self.m.insert(a, b, t)
            win.destroy()
            if k is not None:
                self.sel = k
                self.t = self.m.starts()[k]
            self.edited()
        ctk.CTkButton(win, text="ADD", command=go).pack(pady=8)

    def do_undo(self):
        self.stop_play()
        if self.m.undo():
            self.edited()

    def do_redo(self):
        self.stop_play()
        if self.m.redo():
            self.edited()

    def do_reset(self):
        self.stop_play()
        self.m.reset()
        self.edited()

    def set_zoom(self, z):
        self.zoom = max(1.0, min(40.0, z))
        x = self.tl_x(self.t)
        w = self.tl.winfo_width()
        if not (0 <= x <= w):
            self.scroll_x = max(0.0, self.t * self.px_per_sec() - w / 2)
        self.draw_timeline()

    def on_hscroll(self, *args):
        w = max(10, self.tl.winfo_width())
        full = 12 + self.m.total * self.px_per_sec()
        if args and args[0] == "moveto":
            self.scroll_x = float(args[1]) * full
        elif args and args[0] == "scroll":
            self.scroll_x += int(args[1]) * w * 0.2
        self.draw_timeline()

    # ---------------- movie strip mouse
    def strip_down(self, e):
        self.stop_play()
        self.drag = dict(kind="range", t0=self.strip_t(e.x), x0=e.x, moved=False)

    def strip_move(self, e):
        d = self.drag
        if d and d.get("kind") == "range":
            if abs(e.x - d["x0"]) > 4:
                d["moved"] = True
            if d["moved"]:
                a, b = sorted((d["t0"], self.strip_t(e.x)))
                self.gap_sel = (max(self.span[0], a), min(self.span[1], b))
                self.update_labels()
                self.draw_strip()

    def strip_up(self, e):
        d = self.drag
        self.drag = None
        if not d or d.get("kind") != "range":
            return
        if d["moved"] and self.gap_sel and self.gap_sel[1] - self.gap_sel[0] >= 0.2:
            self.update_labels()          # any part of the movie (also one already in the short) is chosen
            self.draw_strip()
            return
        t = d["t0"]
        for i, (s, en) in enumerate(self.m.p):     # a click on a green part: that piece
            if s <= t <= en:
                self.sel = i
                self.gap_sel = None
                self.seek(self.m.out_of(t) or 0.0)
                return
        g = [x for x in self.m.gaps(*self.span) if x[0] <= t <= x[1]]   # a click on a dark part: that cut part
        self.gap_sel = g[0] if g else None
        self.update_labels()
        self.draw_strip()

    # ---------------- short timeline mouse
    def hit(self, x, y):
        """('l'|'r'|'body', index) under the mouse, or None."""
        if y < 22:
            return None
        acc = 0.0
        for i, (s, e) in enumerate(self.m.p):
            x0, x1 = self.tl_x(acc), self.tl_x(acc + e - s)
            grip = max(3.0, min(8.0, (x1 - x0) / 3))          # each piece has its own edge handles, inside it
            if x0 - (3 if i == 0 else 0) <= x <= x0 + grip:
                return ("l", i)
            if x1 - grip <= x <= x1 + (3 if i == len(self.m.p) - 1 else 0):
                return ("r", i)
            if x0 < x < x1:
                return ("body", i)
            acc += e - s
        return None

    def tl_hover(self, e):
        h = self.hit(e.x, e.y)
        self.tl.configure(cursor="sb_h_double_arrow" if h and h[0] in ("l", "r") else
                          ("fleur" if h else "arrow"))

    def tl_down(self, e):
        self.stop_play()
        h = self.hit(e.x, e.y)
        if h is None:
            self.seek(self.tl_t(e.x))
            self.drag = None
            return
        side, i = h
        self.sel = i
        if side in ("l", "r"):
            self.m.snap()
            self.drag = dict(kind="edge", side=side, i=i, x0=e.x, src0=self.m.p[i][0 if side == "l" else 1],
                             orig=[list(p) for p in self.m.p])
        else:
            self.drag = dict(kind="move", i=i, x0=e.x, moved=False, t=self.tl_t(e.x))
        self.update_labels()
        self.redraw()

    def tl_move(self, e):
        d = self.drag
        if not d:
            return
        if d["kind"] == "edge":
            dt = (e.x - d["x0"]) / self.px_per_sec()
            self.m.p = [list(p) for p in d["orig"]]
            i = d["i"]
            if d["side"] == "l":
                self.m.p[i][0] = min(max(0.0, d["src0"] - dt), self.m.p[i][1] - 0.15)
            else:
                self.m.p[i][1] = max(min(self.info["duration"], d["src0"] + dt), self.m.p[i][0] + 0.15)
            self.redraw()
            self.update_labels()
        elif d["kind"] == "move":
            if abs(e.x - d["x0"]) > 6:
                d["moved"] = True
            if d["moved"]:
                t = self.tl_t(e.x)
                starts = self.m.starts()
                j = sum(1 for k, st in enumerate(starts) if st + (self.m.p[k][1] - self.m.p[k][0]) / 2 < t)
                d["j"] = j
                d["ins_x"] = self.tl_x(starts[j] if j < len(starts) else self.m.total)
                self.draw_timeline()

    def tl_up(self, e):
        d = self.drag
        self.drag = None
        if not d:
            return
        if d["kind"] == "edge":
            if self.m.p == d["orig"]:
                self.m.undo_stack.pop() if self.m.undo_stack else None
            if d["side"] == "l":
                self.t = self.m.starts()[min(d["i"], len(self.m.p) - 1)]
            self.edited()
        elif d["kind"] == "move":
            if d["moved"] and "j" in d:
                j = d["j"]
                i = d["i"]
                self.sel = self.m.move(i, j if j <= i else j - 1)
                self.edited()
            else:
                self.seek(d["t"])

    # ================================================================ save / close
    def save(self, export_now):
        self.stop_play()
        self.on_save(self.m.as_pieces(), export_now)
        self.close()

    def close(self):
        try:
            self.stop_play()
        except Exception:
            pass
        try:
            self.destroy()
        except Exception:
            pass
