"""'Audio tracks' window (MKVToolNix-style): keep / remove audio languages and subtitle tracks, choose the main
language, rename tracks, save a new file in seconds (copied, same quality), or save one track alone."""
import os
import queue
import threading
import tkinter as tk

import customtkinter as ctk
from tkinter import messagebox

import tracks as T
from widgets import NEON, GREY, TEXT, QUIET, QUIET_H


class TracksWindow(ctk.CTkToplevel):
    def __init__(self, master, movie, on_saved=None):
        super().__init__(master)
        self.title("Audio tracks - " + os.path.basename(movie))
        self.geometry("820x560")
        self.minsize(700, 420)
        self.movie, self.on_saved = movie, on_saved
        self.q = queue.Queue()
        self.stop_ev = threading.Event()
        self.busy = False
        try:
            self.tracks, self.duration = T.probe(movie)
        except Exception as e:
            messagebox.showerror("Audio tracks", f"The tracks could not be read:\n{e}", parent=self)
            self.after(10, self.destroy)
            return
        auds = [t for t in self.tracks if t["type"] == "audio"]
        subs = [t for t in self.tracks if t["type"] == "subtitle"]
        ctk.CTkLabel(self, text=f"{os.path.basename(movie)}  -  {len(auds)} audio track(s), {len(subs)} subtitle "
                                f"track(s)", font=ctk.CTkFont(size=14, weight="bold"), text_color=NEON,
                     anchor="w").pack(fill="x", padx=12, pady=(12, 2))
        ctk.CTkLabel(self, text="Untick what you do not want. 'Main' = the language that plays first (track 1, "
                                "default) - the editor and every export use it. Nothing is re-encoded: the new file is "
                                "ready in seconds, same quality.", text_color=GREY, wraplength=780, justify="left",
                     anchor="w").pack(fill="x", padx=12)
        body = ctk.CTkScrollableFrame(self)
        body.pack(fill="both", expand=True, padx=10, pady=8)
        hdr = ctk.CTkFrame(body, fg_color="transparent")
        hdr.pack(fill="x")
        for txt, w in (("Keep", 50), ("Main", 50), ("Track", 300), ("Language code", 110), ("Name", 150), ("", 90)):
            ctk.CTkLabel(hdr, text=txt, width=w, anchor="w", text_color=GREY).pack(side="left", padx=2)
        self.keep, self.lang, self.name = {}, {}, {}
        main0 = next((t["index"] for t in auds if t["default"]), auds[0]["index"] if auds else -1)
        self.main = tk.IntVar(value=main0)
        for t in auds + subs:
            r = ctk.CTkFrame(body, fg_color="transparent")
            r.pack(fill="x", pady=1)
            self.keep[t["index"]] = tk.BooleanVar(value=True)
            ctk.CTkCheckBox(r, text="", width=50, variable=self.keep[t["index"]]).pack(side="left", padx=2)
            if t["type"] == "audio":
                ctk.CTkRadioButton(r, text="", width=50, variable=self.main, value=t["index"]).pack(side="left", padx=2)
            else:
                ctk.CTkLabel(r, text="", width=50).pack(side="left", padx=2)
            ctk.CTkLabel(r, text=T.describe(t), width=300, anchor="w", text_color=TEXT).pack(side="left", padx=2)
            self.lang[t["index"]] = tk.StringVar(value=t["lang"])
            ctk.CTkEntry(r, width=110, textvariable=self.lang[t["index"]]).pack(side="left", padx=2)
            self.name[t["index"]] = tk.StringVar(value=t["title"])
            ctk.CTkEntry(r, width=150, textvariable=self.name[t["index"]]).pack(side="left", padx=2)
            ctk.CTkButton(r, text="Save alone", width=90, fg_color=QUIET, hover_color=QUIET_H, text_color=TEXT,
                          command=lambda t=t: self.save_alone(t)).pack(side="left", padx=2)
        if not auds and not subs:
            ctk.CTkLabel(body, text="This file has no audio or subtitle tracks.", text_color=GREY).pack(pady=10)
        bottom = ctk.CTkFrame(self, fg_color="transparent")
        bottom.pack(fill="x", padx=12, pady=(0, 6))
        ext = os.path.splitext(movie)[1].lower() or ".mkv"
        self.fmt = tk.StringVar(value=f"Same as the movie ({ext})")
        ctk.CTkLabel(bottom, text="Save as", text_color=TEXT).pack(side="left")
        ctk.CTkOptionMenu(bottom, values=[f"Same as the movie ({ext})", "MKV (.mkv)", "MP4 (.mp4)"],
                          variable=self.fmt, width=180).pack(side="left", padx=6)
        self.open_new = tk.BooleanVar(value=True)
        ctk.CTkCheckBox(bottom, text="Open the new file here", variable=self.open_new,
                        text_color=TEXT).pack(side="left", padx=10)
        self.go = ctk.CTkButton(bottom, text="SAVE NEW FILE", width=150, height=36,
                                font=ctk.CTkFont(size=13, weight="bold"), command=self.save)
        self.go.pack(side="right")
        self.bar = ctk.CTkProgressBar(self)
        self.bar.set(0)
        self.bar.pack(fill="x", padx=12, pady=(2, 2))
        self.status = ctk.CTkLabel(self, text="", text_color=GREY, anchor="w", wraplength=780, justify="left")
        self.status.pack(fill="x", padx=12, pady=(0, 10))
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.after(100, self.poll)
        try:
            self.transient(master.winfo_toplevel())
            self.lift()
        except Exception:
            pass

    def edits(self):
        out = {}
        for t in self.tracks:
            i = t["index"]
            if i in self.lang:
                lang, name = self.lang[i].get().strip(), self.name[i].get().strip()
                e = {}
                if lang != t["lang"]:
                    e["lang"] = lang or "und"
                if name != t["title"]:
                    e["title"] = name
                if e:
                    out[i] = e
        return out

    def out_path(self):
        f = self.fmt.get()
        p = T.out_name(self.movie)
        if f.startswith("MKV"):
            return os.path.splitext(p)[0] + ".mkv"
        if f.startswith("MP4"):
            return os.path.splitext(p)[0] + ".mp4"
        return p

    def save(self):
        if self.busy:
            self.stop_ev.set()
            return
        keep = {i for i, v in self.keep.items() if v.get()}
        auds = [t for t in self.tracks if t["type"] == "audio"]
        if auds and not any(t["index"] in keep for t in auds):
            if not messagebox.askyesno("Audio tracks", "No audio track is ticked - the new file will have NO sound.\n\n"
                                                       "Continue?", parent=self):
                return
        main = self.main.get()
        if main not in keep:
            kept = [t["index"] for t in auds if t["index"] in keep]
            main = kept[0] if kept else -1
        out = self.out_path()
        cmd, na, ns = T.build_cmd(self.movie, self.tracks, keep, main, out, self.edits())
        self.busy = True
        self.stop_ev.clear()
        self.go.configure(text="Stop")
        self.status.configure(text=f"Saving {os.path.basename(out)} ({na} audio, {ns} subtitle track(s)) ...")

        def work():
            ok, err = T.run(cmd, self.duration, lambda f: self.q.put(("prog", f)), self.stop_ev)
            self.q.put(("done", (ok, err, out)))
        threading.Thread(target=work, daemon=True).start()

    def save_alone(self, t):
        try:
            p = T.save_track(self.movie, t)
            self.status.configure(text=f"Saved: {p}")
        except Exception as e:
            messagebox.showerror("Audio tracks", f"This track could not be saved:\n{e}", parent=self)

    def poll(self):
        try:
            while True:
                kind, v = self.q.get_nowait()
                if kind == "prog":
                    self.bar.set(v)
                elif kind == "done":
                    ok, err, out = v
                    self.busy = False
                    self.go.configure(text="SAVE NEW FILE")
                    if ok and os.path.isfile(out):
                        self.bar.set(1)
                        self.status.configure(text=f"Saved: {out}")
                        if self.open_new.get() and self.on_saved:
                            self.on_saved(out)
                            self.close()
                            return
                    else:
                        try:
                            os.remove(out)
                        except OSError:
                            pass
                        self.bar.set(0)
                        self.status.configure(text="Stopped." if err == "stopped" else f"Failed: {err}")
        except queue.Empty:
            pass
        except tk.TclError:
            return
        self.after(100, self.poll)

    def close(self):
        self.stop_ev.set()
        try:
            self.destroy()
        except Exception:
            pass
