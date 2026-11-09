"""Auto Short tab: pick a movie (Simple Edit tab), press one button, get continuous-dialogue shorts one by one.

Silence is cut from the picture AND the sound. Shorts appear in the list on the right as soon as each one is
finished, while the scan of the rest of the movie goes on. Colour, Aspect & Crop, Overlay, Text and Export
settings come from the Simple Edit tab, so the look is the same as in manual editing.
"""
import copy
import json
import os
import queue
import threading
import traceback

import customtkinter as ctk
from tkinter import messagebox

import auto_short
import dialogue
import engine as E
from studio import play_file
from widgets import (NEON, GREY, TEXT, QUIET, QUIET_H, DANGER, DANGER_H, NumField, open_path)


class AutoShortFrame(ctk.CTkFrame):
    def __init__(self, parent, app, simple):
        super().__init__(parent, corner_radius=10)
        self.app = app
        self.simple = simple
        self.q = queue.Queue()
        self.running = False
        self.job = None
        self.resume = None                  # where a stopped run carries on (also saved in the project)
        self.out_dir = ""
        self.shown_movie = None
        self.grid_columnconfigure(0, weight=0, minsize=400)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # ---------------- top bar
        top = ctk.CTkFrame(self, corner_radius=10)
        top.grid(row=0, column=0, columnspan=2, sticky="ew", padx=8, pady=8)
        self.movie_lbl = ctk.CTkLabel(top, text="Movie: (choose a movie in the Simple Edit tab)", anchor="w")
        self.movie_lbl.pack(side="left", padx=10, pady=8)
        self.go_btn = ctk.CTkButton(top, text="CREATE AUTO SHORTS", width=210, height=38,
                                    font=ctk.CTkFont(size=14, weight="bold"), command=self.start)
        self.go_btn.pack(side="right", padx=(6, 10))
        self.stop_btn = ctk.CTkButton(top, text="Stop", width=80, height=38, fg_color=DANGER, hover_color=DANGER_H,
                                      text_color=TEXT, state="disabled", command=self.stop)
        self.stop_btn.pack(side="right", padx=6)
        self.cont_btn = ctk.CTkButton(top, text="Continue", width=110, height=38, state="disabled",
                                      command=self.continue_run)
        self.cont_btn.pack(side="right", padx=6)
        self.resume_lbl = ctk.CTkLabel(top, text="", text_color=GREY, anchor="w")
        self.resume_lbl.pack(side="left", padx=10)
        ctk.CTkButton(top, text="Open folder", width=110, height=38, fg_color=QUIET, hover_color=QUIET_H,
                      text_color=TEXT, command=self.open_folder).pack(side="right", padx=6)

        # ---------------- left: settings
        left = ctk.CTkScrollableFrame(self, fg_color="transparent", width=380)
        left.grid(row=1, column=0, sticky="nsew", padx=(8, 4), pady=(0, 8))
        self.build_settings(left)

        # ---------------- right: progress, finished shorts, log
        right = ctk.CTkFrame(self, fg_color="transparent")
        right.grid(row=1, column=1, sticky="nsew", padx=(4, 8), pady=(0, 8))
        right.grid_columnconfigure(0, weight=1)
        right.grid_rowconfigure(2, weight=1)
        right.grid_rowconfigure(4, weight=1)
        self.bar = ctk.CTkProgressBar(right)
        self.bar.set(0)
        self.bar.grid(row=0, column=0, sticky="ew", padx=4, pady=(2, 2))
        self.status = ctk.CTkLabel(right, text="Ready", text_color=GREY, anchor="w")
        self.status.grid(row=1, column=0, sticky="ew", padx=6)
        self.list_box = ctk.CTkScrollableFrame(right, label_text="SHORTS READY (they appear one by one)",
                                               label_text_color=NEON)
        self.list_box.grid(row=2, column=0, sticky="nsew", padx=4, pady=(6, 4))
        self.empty_lbl = ctk.CTkLabel(self.list_box, text="No short yet.", text_color=GREY)
        self.empty_lbl.pack(anchor="w", padx=8, pady=6)
        ctk.CTkLabel(right, text="LOG", text_color=NEON, anchor="w",
                     font=ctk.CTkFont(size=12, weight="bold")).grid(row=3, column=0, sticky="w", padx=6)
        self.log_box = ctk.CTkTextbox(right, wrap="word", height=150)
        self.log_box.grid(row=4, column=0, sticky="nsew", padx=4, pady=(0, 2))

        self.after(200, self.poll)
        self.after(800, self.tick)

    # ================================================================ settings panel
    def build_settings(self, f):
        def head(text):
            ctk.CTkLabel(f, text=text, font=ctk.CTkFont(size=13, weight="bold"), text_color=NEON,
                         anchor="w").pack(anchor="w", padx=8, pady=(12, 3))

        def note(text):
            ctk.CTkLabel(f, text=text, text_color=GREY, wraplength=340, justify="left",
                         anchor="w").pack(anchor="w", padx=8, pady=(0, 4))

        head("WHICH PART OF THE MOVIE")
        self.use_parts = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(f, text="Only the parts ticked in the Simple Edit tab", variable=self.use_parts,
                        text_color=TEXT).pack(anchor="w", padx=8, pady=3)
        row = ctk.CTkFrame(f, fg_color="transparent")
        row.pack(fill="x", padx=8, pady=2)
        ctk.CTkLabel(row, text="Start (sec)", text_color=TEXT, width=80, anchor="w").pack(side="left")
        self.r_start = ctk.CTkEntry(row, width=80)
        self.r_start.insert(0, "0")
        self.r_start.pack(side="left", padx=(0, 12))
        ctk.CTkLabel(row, text="End (sec)", text_color=TEXT, width=70, anchor="w").pack(side="left")
        self.r_end = ctk.CTkEntry(row, width=80, placeholder_text="movie end")
        self.r_end.pack(side="left")
        note("Leave End empty to scan to the end of the movie. With 'ticked parts', every ticked part is "
             "scanned on its own, one after the other.")

        head("SHORT LENGTH")
        self.min_len = NumField(f, "Minimum (sec)", 5, 120, 1, auto_short.MIN_LEN, "{:.0f}", None, label_width=130)
        self.min_len.pack(fill="x", padx=2, pady=2)
        self.max_len = NumField(f, "Maximum (sec)", 10, 180, 1, auto_short.MAX_LEN, "{:.0f}", None, label_width=130)
        self.max_len.pack(fill="x", padx=2, pady=2)
        self.keep_last = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(f, text="Keep the last short even if it is shorter than the minimum", variable=self.keep_last,
                        text_color=TEXT).pack(anchor="w", padx=8, pady=4)

        head("TALKING DETECTION (AI)")
        self.pad = NumField(f, "Speech padding (ms)", 0, 500, 10, dialogue.PAD_MS, "{:.0f}", None, label_width=150)
        self.pad.pack(fill="x", padx=2, pady=2)
        self.minsil = NumField(f, "Minimum silence (ms)", 50, 1000, 10, dialogue.MIN_SIL_MS, "{:.0f}", None,
                               label_width=150)
        self.minsil.pack(fill="x", padx=2, pady=2)
        self.minpiece = NumField(f, "Shortest clip (s)", 0, 5, 0.1, dialogue.MIN_PIECE, "{:.1f}", None,
                                 label_width=150)
        self.minpiece.pack(fill="x", padx=2, pady=2)
        self.denoise = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(f, text="Noise reduction on the sound", variable=self.denoise,
                        text_color=TEXT).pack(anchor="w", padx=8, pady=4)
        self.scan_pic = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(f, text="Scan the picture: skip fast-cut montage, cut on shot changes",
                        variable=self.scan_pic, text_color=TEXT).pack(anchor="w", padx=8, pady=4)
        note("Everything where nobody is talking is cut from the picture AND the sound. Smaller padding = tighter, "
             "faster talking. Shortest clip: no piece is shorter than this, so there are no 0.2 s flashes. Scan the "
             "picture: parts with very fast picture cuts (action montage, music) are skipped and every cut is moved "
             "onto a real shot change (a little slower). The detector is the Silero AI model (run install_ai.bat once); without it a simpler "
             "built-in detector is used.")

        head("KEEP VIEWERS WATCHING (retention boost)")
        self.bo = {}
        for key, text, default in (
                ("zoom", "Punch-in zoom on the cuts (the picture switches wide / close, so jump cuts look planned)", True),
                ("bar", "Progress bar along the top (people stay to see it fill)", True),
                ("loud", "Even, loud speech (quiet parts are lifted - nobody swipes away because of low volume)", True),
                ("crisp", "Crisp and vivid picture (a little sharper, a little more colour)", True),
                ("part_label", "'PART n' label for the first 3 seconds (makes people look for the next part)", True)):
            self.bo[key] = ctk.BooleanVar(value=default)
            ctk.CTkCheckBox(f, text=text, variable=self.bo[key], text_color=TEXT).pack(anchor="w", padx=8, pady=3)
        self.bo_pct = NumField(f, "Zoom strength (%)", 2, 20, 1, 8, "{:.0f}", None, label_width=150)
        self.bo_pct.pack(fill="x", padx=2, pady=2)
        row = ctk.CTkFrame(f, fg_color="transparent")
        row.pack(fill="x", padx=8, pady=2)
        ctk.CTkLabel(row, text="Opening text", text_color=TEXT, width=100, anchor="w").pack(side="left")
        self.bo_hook = ctk.CTkEntry(row, width=300, placeholder_text="optional, shown for the first 3 s, e.g. Wait for it ...")
        self.bo_hook.pack(side="left")
        note("All of this is done in the same single export pass with light filters, so exporting is only a little "
             "slower. Switch everything off and the shorts are exactly as before. Opening text can use {n} for the "
             "short number.")

        head("LOOK OF THE SHORTS")
        note("Colour, Aspect & Crop, Overlay, Text and Export (quality, codec) settings come from the Simple Edit "
             "tab. Overlay and text times count from the start of each short. Use {n} with Auto-number in a text to "
             "get Part 1, Part 2, ... Text editing with Whisper (words to remove) uses the Simple Edit > Dialogue tab.")

    # ================================================================ project (save / open)
    def get_state(self):
        return dict(resume=copy.deepcopy(self.resume), use_parts=bool(self.use_parts.get()), start=self.r_start.get(), end=self.r_end.get(),
                    min_len=float(self.min_len.get()), max_len=float(self.max_len.get()),
                    keep_last=bool(self.keep_last.get()), pad=float(self.pad.get()),
                    minsil=float(self.minsil.get()), denoise=bool(self.denoise.get()),
                    min_piece=float(self.minpiece.get()), scan_picture=bool(self.scan_pic.get()),
                    boost=self.boost_opts(True))

    def boost_opts(self, always=False):
        """Retention boost settings. Empty dict = everything off (unless always: for saving the project)."""
        d = {k: bool(v.get()) for k, v in self.bo.items()}
        d.update(zoom_pct=float(self.bo_pct.get()), hook=self.bo_hook.get().strip())
        if not always and not (any(d[k] for k in self.bo) or d["hook"]):
            return {}
        return d

    def set_state(self, st):
        st = st or {}
        self.set_resume(st.get("resume"))
        self.use_parts.set(bool(st.get("use_parts", False)))
        for entry, key, default in ((self.r_start, "start", "0"), (self.r_end, "end", "")):
            entry.delete(0, "end")
            entry.insert(0, str(st.get(key, default)))
        self.min_len.set(float(st.get("min_len", auto_short.MIN_LEN)))
        self.max_len.set(float(st.get("max_len", auto_short.MAX_LEN)))
        self.keep_last.set(bool(st.get("keep_last", False)))
        self.pad.set(float(st.get("pad", dialogue.PAD_MS)))
        self.minsil.set(float(st.get("minsil", dialogue.MIN_SIL_MS)))
        self.denoise.set(bool(st.get("denoise", True)))
        self.minpiece.set(float(st.get("min_piece", dialogue.MIN_PIECE)))
        self.scan_pic.set(bool(st.get("scan_picture", True)))
        bo = st.get("boost") or {}
        for k, v in self.bo.items():
            v.set(bool(bo.get(k, True)))
        self.bo_pct.set(float(bo.get("zoom_pct", 8)))
        self.bo_hook.delete(0, "end")
        self.bo_hook.insert(0, str(bo.get("hook", "")))

    # ================================================================ helpers
    def refresh_movie(self):
        name = os.path.basename(self.simple.movie) if self.simple.movie else None
        if name != self.shown_movie:
            self.shown_movie = name
            self.movie_lbl.configure(text=f"Movie: {name}" if name else
                                     "Movie: (choose a movie in the Simple Edit tab)")
            if not self.running:                      # another movie: show its own Continue point, if any
                try:
                    self.set_resume(self.find_resume())
                except Exception:
                    self.set_resume(None)

    def tick(self):
        self.refresh_movie()
        self.after(800, self.tick)

    def open_folder(self):
        folder = self.out_dir if self.out_dir and os.path.isdir(self.out_dir) else E.OUTPUT_DIR
        os.makedirs(folder, exist_ok=True)
        open_path(folder)

    def log(self, msg):
        self.q.put(("log", str(msg)))

    def add_short_row(self, d):
        if self.empty_lbl is not None:
            self.empty_lbl.destroy()
            self.empty_lbl = None
        row = ctk.CTkFrame(self.list_box, fg_color="transparent")
        row.pack(fill="x", padx=2, pady=2)
        ctk.CTkLabel(row, text=f"Short {d['number']}  -  {d['length']:.0f} s  -  {d['name']}", text_color=TEXT,
                     anchor="w").pack(side="left", padx=4)
        ctk.CTkButton(row, text="Folder", width=64, fg_color=QUIET, hover_color=QUIET_H, text_color=TEXT,
                      command=lambda p=os.path.dirname(d["path"]): open_path(p)).pack(side="right", padx=2)
        ctk.CTkButton(row, text="Play", width=64, command=lambda p=d["path"]: play_file(p)).pack(side="right", padx=2)

    def clear_list(self):
        for w in self.list_box.winfo_children():
            w.destroy()
        self.empty_lbl = ctk.CTkLabel(self.list_box, text="No short yet.", text_color=GREY)
        self.empty_lbl.pack(anchor="w", padx=8, pady=6)

    # ================================================================ run
    # ================================================================ continue after Stop
    def set_resume(self, r):
        """r: dict from AutoShortJob.mark(), or None. Shows the Continue button when there is work left."""
        if r and not r.get("finished") and r.get("ranges"):
            self.resume = dict(r)
            self.cont_btn.configure(state="normal" if not self.running else "disabled")
            m, sec = divmod(int(float(r.get("pos", 0))), 60)
            h, m = divmod(m, 60)
            at = f"{h}:{m:02d}:{sec:02d}" if h else f"{m:02d}:{sec:02d}"
            self.resume_lbl.configure(text=f"Stopped at {at} - press Continue (next short: "
                                           f"{int(r.get('next_number', 1))})")
        else:
            self.resume = None
            self.cont_btn.configure(state="disabled")
            self.resume_lbl.configure(text="")

    def find_resume(self):
        """The Continue point for the movie now chosen: from this session/project, else from _resume.json."""
        mv = self.simple.movie
        r = self.resume
        if r and os.path.normcase(os.path.abspath(r.get("movie", ""))) == os.path.normcase(os.path.abspath(mv or "")):
            return r
        if mv:
            f = os.path.join(E.OUTPUT_DIR, f"{self.simple.file_base()}_auto_short", "_resume.json")
            try:
                with open(f, "r", encoding="utf-8") as fh:
                    d = json.load(fh)
                if not d.get("finished") and os.path.normcase(os.path.abspath(d.get("movie", ""))) == \
                        os.path.normcase(os.path.abspath(mv)):
                    return d
            except (OSError, ValueError):
                pass
        return None

    def continue_run(self):
        r = self.find_resume()
        if not r:
            messagebox.showinfo("Auto Short", "There is nothing to continue for this movie.")
            self.set_resume(None)
            return
        self.start(resume=r)

    def start(self, resume=None):
        if self.running:
            return
        sm = self.simple
        self.refresh_movie()
        if not sm.movie:
            messagebox.showwarning("Auto Short", "Choose a movie in the Simple Edit tab first.")
            return
        try:
            min_len, max_len = float(self.min_len.get()), float(self.max_len.get())
            if max_len - min_len < 3:
                raise ValueError("Maximum length must be at least 3 seconds longer than the minimum.")
            if resume:
                all_ranges = [tuple(map(float, x)) for x in resume["ranges"]]
                ri = min(max(0, int(resume.get("range_index", 0))), len(all_ranges) - 1)
                pos = float(resume.get("pos", all_ranges[ri][0]))
                a, b = all_ranges[ri]
                ranges = [(max(a, min(pos, b)), b)] + all_ranges[ri + 1:]
                ranges = [(x, y) for x, y in ranges if y - x > 0.5]
                if not ranges:
                    self.set_resume(None)
                    raise ValueError("This run was already finished - nothing is left to continue.")
            elif self.use_parts.get():
                ranges = [(float(p["start"]), float(p["end"])) for p in sm.parts if p["on"]]
                if not ranges:
                    raise ValueError("No part is ticked in the Simple Edit tab.")
            else:
                a = max(0.0, float(self.r_start.get().strip() or 0))
                b = float(self.r_end.get().strip()) if self.r_end.get().strip() else sm.dur
                b = min(b, sm.dur)
                if b - a < min_len:
                    raise ValueError("The range is shorter than the minimum short length.")
                ranges = [(a, b)]
            opts = dict(sm.dialogue_opts())
            opts.update(pad_ms=int(self.pad.get()), min_sil_ms=int(self.minsil.get()),
                        denoise=bool(self.denoise.get()), vad=True, min_piece=float(self.minpiece.get()),
                        scan_picture=bool(self.scan_pic.get()), boost=self.boost_opts())
        except ValueError as e:
            messagebox.showerror("Auto Short", str(e) if str(e) and "could not convert" not in str(e)
                                 else "Please enter the Start / End values as numbers.")
            return
        try:
            sm.sync_export()
            s = E.sanitize(dict(sm.cfg))
        except ValueError as e:
            messagebox.showerror("Export", str(e))
            return
        errs = E.validate(s, "simple")
        if errs:
            messagebox.showerror("Export", "\n".join(errs))
            return
        self.out_dir = os.path.join(E.OUTPUT_DIR, f"{sm.file_base()}_auto_short")
        self.log_box.delete("1.0", "end")
        self.clear_list()
        self.bar.set(0)
        self.running = True
        self.go_btn.configure(state="disabled")
        self.cont_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        if resume:
            first = int(resume.get("next_number", sm.part_number(0)))
            prior = [d for d in resume.get("made", []) if os.path.isfile(d.get("path", ""))]
            for d in prior:
                self.add_short_row(d)
            all_ranges, base = resume["ranges"], ri
            self.status.configure(text="Continuing ...")
            self.log(f"Continuing from {ranges[0][0]:.0f}s - {len(prior)} short(s) were already made, "
                     f"the next one is number {first}.")
        else:
            first, prior, all_ranges, base = sm.part_number(0), [], [list(x) for x in ranges], 0
            self.status.configure(text="Starting ...")
        job = auto_short.AutoShortJob(
            sm.movie, ranges, opts, s, copy.deepcopy(sm.items), self.out_dir, self.log,
            lambda fr, t: self.q.put(("prog", (fr, t))), lambda d: self.q.put(("short", d)),
            min_len=min_len, max_len=max_len, first_number=first, keep_last=bool(self.keep_last.get()),
            all_ranges=all_ranges, index_base=base, prior_made=prior,
            on_resume=lambda info: self.q.put(("resume", info)))
        self.job = job
        threading.Thread(target=self.work, args=(job,), daemon=True).start()

    def work(self, job):
        try:
            job.run()
        except Exception:
            self.log("ERROR:\n" + traceback.format_exc())
        self.q.put(("done", None))

    def stop(self):
        if self.job:
            self.status.configure(text="Stopping ...")
            self.job.stop()

    def poll(self):
        try:
            while True:
                kind, v = self.q.get_nowait()
                if kind == "log":
                    self.log_box.insert("end", v + "\n")
                    self.log_box.see("end")
                elif kind == "prog":
                    self.bar.set(max(0.0, min(1.0, v[0])))
                    self.status.configure(text=v[1])
                elif kind == "short":
                    self.add_short_row(v)
                elif kind == "resume":
                    self.resume = v
                elif kind == "done":
                    self.running = False
                    self.job = None
                    self.go_btn.configure(state="normal")
                    self.stop_btn.configure(state="disabled")
                    self.set_resume(self.resume)
        except queue.Empty:
            pass
        except Exception as e:
            self.status.configure(text=f"UI error: {e}")
        self.after(200, self.poll)
