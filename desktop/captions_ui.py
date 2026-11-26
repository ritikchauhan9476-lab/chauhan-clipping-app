"""Captions tab of every editing section: load an SRT / VTT / ASS file (or a subtitle track of the movie) and show it
as styled captions - word by word with the spoken word lit up, or line by line - in the preview, when playing and in
every export (parts, AI clips, Viral Clips, Auto Short)."""
import os
import threading
import tkinter as tk

import customtkinter as ctk
from tkinter import filedialog, messagebox

import captions as CAP
import engine as E
from widgets import NEON, GREY, TEXT, QUIET, QUIET_H, DANGER, DANGER_H

SUB_TYPES = [("Subtitles", "*.srt *.vtt *.ass *.ssa"), ("All files", "*.*")]


class CaptionsMixin:
    """Mixed into Studio. Needs: self.movie, self.after, self.schedule_render, self.scroll."""

    def cap_init(self):
        self.cap = dict(CAP.DEFAULT)
        self.cap_words, self.cap_cues = [], []
        self.cap_v = {}

    # ---------------------------------------------------------------- the tab
    def build_captions(self, tab):
        f = self.scroll(tab)
        v = self.cap_v
        c = self.cap

        def head(t):
            ctk.CTkLabel(f, text=t, font=ctk.CTkFont(size=13, weight="bold"), text_color=NEON,
                         anchor="w").pack(anchor="w", padx=8, pady=(12, 3))

        def row(label, make):
            r = ctk.CTkFrame(f, fg_color="transparent")
            r.pack(fill="x", padx=6, pady=2)
            ctk.CTkLabel(r, text=label, text_color=TEXT, anchor="w", width=150).pack(side="left")
            w = make(r)
            w.pack(side="left", fill="x", expand=True)
            return w

        v["on"] = tk.BooleanVar(value=bool(c["on"]))
        ctk.CTkSwitch(f, text="Show captions on the video", variable=v["on"], text_color=TEXT,
                      command=self.cap_changed).pack(anchor="w", padx=10, pady=(10, 4))
        head("SUBTITLE FILE")
        self.cap_file_lbl = ctk.CTkLabel(f, text="No subtitle file", text_color=GREY, anchor="w", wraplength=360,
                                         justify="left")
        self.cap_file_lbl.pack(anchor="w", padx=10)
        r = ctk.CTkFrame(f, fg_color="transparent")
        r.pack(fill="x", padx=6, pady=4)
        ctk.CTkButton(r, text="Load SRT / VTT ...", width=130, command=self.cap_browse).pack(side="left")
        ctk.CTkButton(r, text="From the movie", width=120, command=self.cap_from_movie).pack(side="left", padx=6)
        ctk.CTkButton(r, text="Remove", width=70, fg_color=DANGER, hover_color=DANGER_H, text_color=TEXT,
                      command=self.cap_clear).pack(side="left")
        ctk.CTkLabel(f, text="A file next to the movie with the same name (movie.srt, movie.hi.srt, movie.en.vtt) is "
                             "found by itself. 'From the movie' takes a subtitle track inside an MKV / MP4.",
                     text_color=GREY, wraplength=360, justify="left", anchor="w").pack(anchor="w", padx=8)

        head("LOOK")
        v["style"] = tk.StringVar(value=c["style"] if c["style"] in CAP.STYLES else next(iter(CAP.STYLES)))
        row("Style", lambda r: ctk.CTkOptionMenu(r, values=list(CAP.STYLES), variable=v["style"],
                                                 command=lambda _x: self.cap_changed(), dynamic_resizing=False))
        v["mode"] = tk.StringVar(value=CAP.MODES.get(c["mode"], CAP.MODES["word"]))
        row("Show", lambda r: ctk.CTkOptionMenu(r, values=list(CAP.MODES.values()), variable=v["mode"],
                                                command=lambda _x: self.cap_changed(), dynamic_resizing=False))
        v["pos"] = tk.StringVar(value=c["pos"])
        row("Place", lambda r: ctk.CTkOptionMenu(r, values=list(CAP.POSITIONS), variable=v["pos"],
                                                 command=lambda _x: self.cap_changed()))
        v["case"] = tk.StringVar(value=c["case"])
        row("Letters", lambda r: ctk.CTkOptionMenu(r, values=list(CAP.CASES), variable=v["case"],
                                                   command=lambda _x: self.cap_changed()))
        for key, label, val in (("per", "Words at a time (0 = style)", c["per"]),
                                ("size", "Size %", c["size"]),
                                ("y", "Height % (empty = place)", "" if c["y"] is None else c["y"]),
                                ("active", "Spoken word colour (#hex)", c["active"]),
                                ("shift", "Sync: move by (seconds)", c["shift"])):
            v[key] = tk.StringVar(value=str(val))
            row(label, lambda r, k=key: ctk.CTkEntry(r, textvariable=v[k]))
            v[key].trace_add("write", lambda *a: self.cap_changed())
        ctk.CTkLabel(f, text="Sync: if the captions come too early, type a positive number (0.5 = half a second "
                             "later); too late: a negative one. The captions show in the preview, when you press Play "
                             "and in every export of this section - and in Auto Short (from Simple Edit).",
                     text_color=GREY, wraplength=360, justify="left", anchor="w").pack(anchor="w", padx=8, pady=(6, 4))
        self.cap_info = ctk.CTkLabel(f, text="", text_color=GREY, anchor="w", wraplength=360, justify="left")
        self.cap_info.pack(anchor="w", padx=8)

    # ---------------------------------------------------------------- reading the vars
    def cap_changed(self, *_):
        v = self.cap_v
        if not v:
            return
        c = self.cap

        def num(key, default, lo, hi):
            try:
                return min(hi, max(lo, float(str(v[key].get()).strip() or default)))
            except ValueError:
                return default
        c["on"] = bool(v["on"].get())
        c["style"] = v["style"].get()
        c["mode"] = CAP.MODE_BY_LABEL.get(v["mode"].get(), "word")
        c["pos"] = v["pos"].get()
        c["case"] = v["case"].get()
        c["per"] = int(num("per", 0, 0, 12))
        c["size"] = num("size", 100, 20, 400)
        y = str(v["y"].get()).strip()
        try:
            c["y"] = min(98.0, max(2.0, float(y))) if y else None
        except ValueError:
            c["y"] = None
        a = str(v["active"].get()).strip()
        c["active"] = a if (len(a) == 7 and a.startswith("#")) else ""
        c["shift"] = num("shift", 0.0, -60, 60)
        try:
            self.schedule_render()
        except Exception:
            pass

    def cap_set_vars(self):
        v, c = self.cap_v, self.cap
        if not v:
            return
        v["on"].set(bool(c.get("on")))
        v["style"].set(c.get("style") if c.get("style") in CAP.STYLES else next(iter(CAP.STYLES)))
        v["mode"].set(CAP.MODES.get(c.get("mode"), CAP.MODES["word"]))
        v["pos"].set(c.get("pos") or "Lower third")
        v["case"].set(c.get("case") or "Like the style")
        v["per"].set(str(c.get("per") or 0))
        v["size"].set(f"{float(c.get('size') or 100):g}")
        v["y"].set("" if c.get("y") in (None, "") else f"{float(c['y']):g}")
        v["active"].set(c.get("active") or "")
        v["shift"].set(f"{float(c.get('shift') or 0):g}")

    # ---------------------------------------------------------------- the file
    def cap_load(self, path, quiet=False, turn_on=True):
        try:
            words, cues = CAP.parse(path)
        except Exception as e:
            if not quiet:
                messagebox.showerror("Captions", f"This subtitle file could not be read:\n{e}")
            return False
        if not words and not cues:
            if not quiet:
                messagebox.showerror("Captions", "No captions were found in this file.")
            return False
        self.cap_words, self.cap_cues = words, cues
        self.cap["file"] = path
        if turn_on and self.cap_v:
            self.cap_v["on"].set(True)
        self.cap_show_file()
        self.cap_changed()
        return True

    def cap_show_file(self):
        if not hasattr(self, "cap_file_lbl"):
            return
        p = self.cap.get("file") or ""
        if p and (self.cap_words or self.cap_cues):
            last = self.cap_cues[-1][1] if self.cap_cues else self.cap_words[-1][2]
            self.cap_file_lbl.configure(text=f"{os.path.basename(p)}  -  {len(self.cap_cues)} lines, "
                                             f"{len(self.cap_words)} words, until {int(last // 60)}:{int(last % 60):02d}",
                                        text_color=TEXT)
        else:
            self.cap_file_lbl.configure(text="No subtitle file", text_color=GREY)

    def cap_browse(self):
        start = os.path.dirname(self.movie) if self.movie else E.INPUT_DIR
        p = filedialog.askopenfilename(title="Choose the subtitle file", initialdir=start, filetypes=SUB_TYPES)
        if p:
            self.cap_load(p)

    def cap_from_movie(self):
        if not self.movie:
            messagebox.showwarning("Captions", "Choose a movie first.")
            return
        tracks = CAP.subtitle_streams(self.movie)
        if not tracks:
            messagebox.showinfo("Captions", "This movie has no subtitle track inside. Load an SRT file instead.")
            return
        names = [f"{t['n'] + 1}: {t['lang'] or '?'} {t['title']} ({t['codec']})".strip() for t in tracks]
        win = ctk.CTkToplevel(self)
        win.title("Subtitle track")
        win.geometry("420x170")
        win.transient(self.winfo_toplevel())
        ctk.CTkLabel(win, text="Which subtitle track of the movie?", text_color=TEXT).pack(padx=12, pady=(12, 4))
        var = tk.StringVar(value=names[0])
        ctk.CTkOptionMenu(win, values=names, variable=var, width=380).pack(padx=12, pady=4)

        def go():
            n = tracks[names.index(var.get())]["n"]
            win.destroy()
            base = os.path.splitext(self.movie)[0]
            lang = tracks[n]["lang"] or f"track{n + 1}"
            out = f"{base}.{lang}.srt"
            if os.path.exists(out):
                out = f"{base}.{lang}.{n + 1}.srt"
            try:
                CAP.extract_stream(self.movie, n, out)
            except Exception as e:
                messagebox.showerror("Captions", str(e))
                return
            self.cap_load(out)
        ctk.CTkButton(win, text="Use this track", command=go).pack(pady=10)

    def cap_clear(self):
        self.cap_words, self.cap_cues = [], []
        self.cap["file"] = ""
        if self.cap_v:
            self.cap_v["on"].set(False)
        self.cap_show_file()
        self.cap_changed()

    def cap_auto_find(self):
        """A new movie: its own subtitle file (next to it) is found and loaded, but not switched on."""
        if self.cap.get("file") and os.path.isfile(self.cap["file"]):
            base = os.path.splitext(self.movie or "")[0]
            if self.cap["file"].startswith(base + ".") or os.path.splitext(self.cap["file"])[0] == base:
                return
        self.cap_words, self.cap_cues = [], []
        self.cap["file"] = ""
        files = CAP.find_files(self.movie)
        if files:
            self.cap_load(files[0], quiet=True, turn_on=False)
            if hasattr(self, "cap_info"):
                self.cap_info.configure(text=f"Found next to the movie: {os.path.basename(files[0])} - switch on "
                                             "'Show captions on the video' to use it.")
        else:
            self.cap_show_file()

    # ---------------------------------------------------------------- what the engine gets
    def cap_full(self):
        """All captions (for Auto Short), or None."""
        if not self.cap.get("on") or not (self.cap_words or self.cap_cues):
            return None
        return dict(self.cap, words=[list(w) for w in self.cap_words], cues=[list(c) for c in self.cap_cues])

    def cap_extra(self, a, b):
        full = self.cap_full()
        return CAP.for_range(full, a, b) if full else None

    def cap_state(self):
        return dict(self.cap)

    def cap_restore(self, st):
        c = dict(CAP.DEFAULT)
        c.update({k: v for k, v in (st or {}).items() if k in CAP.DEFAULT})
        self.cap = c
        self.cap_words, self.cap_cues = [], []
        if c.get("file") and os.path.isfile(c["file"]):
            try:
                self.cap_words, self.cap_cues = CAP.parse(c["file"])
            except Exception:
                pass
        self.cap_set_vars()
        self.cap_show_file()
