"""Viral Clips tab: a full editing studio (the same Aspect & Crop, Colour, Overlay, Text, Silence, Speed & Effects,
Dialogue and Export tabs as the other sections) whose clips are found by AI.

Left  : FIND VIRAL CLIPS / Stop / Find more, progress, and the clips list (each clip = one part you can tick, play,
        trim and edit like any other part).
Right : 'AI Clips' tab with the AI service, speech to text, platform, clip length, part-by-part, captions, hook,
        layout (follow the speaker / facecam / interview), retention boost, post kit and live-stream clipping.
Every clip is exported as soon as it is found (fast), with every edit of this section. Export (right) exports the
ticked clips again after you changed something.
"""
import copy
import os
import queue
import threading
import time
import traceback
import tkinter as tk

import customtkinter as ctk
from tkinter import messagebox

import engine as E
import project as PRJ
import viral as V
from studio import Studio, eff_item
from widgets import NEON, GREY, TEXT, QUIET, QUIET_H, DANGER, DANGER_H, open_path


class ViralStudio(Studio):
    def __init__(self, parent, app):
        self.vjob = None
        self.vrunner = None
        self.vrec = None
        self.vcache, self.vcache_key = {}, None
        self.vv = {}                     # tk variables of the AI Clips tab
        self.v_ready = False
        super().__init__(parent, app, "viral")
        self.sil_on.set(False)           # clips are exported as found; silence / dialogue cut stay OFF until you switch them on
        self.dl_on.set(False)
        self.update_cut_info()
        self.v_ready = True
        self.apply_platform(first=True)

    # ================================================================ left: run buttons + clips list
    def build_viral_left(self, p):
        row = ctk.CTkFrame(p, fg_color="transparent")
        row.pack(fill="x", padx=8, pady=(4, 2))
        self.v_go = ctk.CTkButton(row, text="FIND VIRAL CLIPS", height=40, font=ctk.CTkFont(size=14, weight="bold"),
                                  command=lambda: self.v_start(False))
        self.v_go.pack(side="left", fill="x", expand=True)
        self.v_stop = ctk.CTkButton(row, text="Stop", width=64, height=40, fg_color=DANGER, hover_color=DANGER_H,
                                    text_color=TEXT, state="disabled", command=self.v_stop_run)
        self.v_stop.pack(side="left", padx=(6, 0))
        row2 = ctk.CTkFrame(p, fg_color="transparent")
        row2.pack(fill="x", padx=8, pady=2)
        self.v_more = ctk.CTkButton(row2, text="Find more", width=100, fg_color=QUIET, hover_color=QUIET_H,
                                    text_color=TEXT, command=lambda: self.v_start(True))
        self.v_more.pack(side="left")
        ctk.CTkButton(row2, text="Open clips folder", fg_color=QUIET, hover_color=QUIET_H, text_color=TEXT,
                      command=self.v_open_folder).pack(side="left", padx=6, fill="x", expand=True)
        self.vv["auto"] = tk.BooleanVar(value=True)
        ctk.CTkCheckBox(p, text="Export every clip as soon as it is found", variable=self.vv["auto"],
                        text_color=TEXT).pack(anchor="w", padx=10, pady=(4, 0))
        self.v_bar = ctk.CTkProgressBar(p)
        self.v_bar.set(0)
        self.v_bar.pack(fill="x", padx=8, pady=(6, 2))
        self.v_status = ctk.CTkLabel(p, text="Choose a movie (or YouTube link) above, then FIND VIRAL CLIPS.",
                                     text_color=GREY, anchor="w", wraplength=300, justify="left")
        self.v_status.pack(fill="x", padx=10)
        self.v_usage = ctk.CTkLabel(p, text="", text_color=GREY, anchor="w", wraplength=300, justify="left")
        self.v_usage.pack(fill="x", padx=10)

    # ================================================================ right: the AI Clips tab
    def build_viral_tab(self, tab):
        f = self.scroll(tab)
        vv = self.vv
        prefs = getattr(self.app, "prefs", {}) or {}
        ai = dict(prefs.get("viral_ai") or {})

        def head(t):
            ctk.CTkLabel(f, text=t, font=ctk.CTkFont(size=13, weight="bold"), text_color=NEON,
                         anchor="w").pack(anchor="w", padx=8, pady=(12, 3))

        def note(t):
            ctk.CTkLabel(f, text=t, text_color=GREY, wraplength=360, justify="left", anchor="w").pack(
                anchor="w", padx=8, pady=(0, 4))

        def row(label, widget_fn, width=150):
            r = ctk.CTkFrame(f, fg_color="transparent")
            r.pack(fill="x", padx=6, pady=2)
            ctk.CTkLabel(r, text=label, text_color=TEXT, anchor="w", width=width).pack(side="left")
            w = widget_fn(r)
            w.pack(side="left", fill="x", expand=True)
            return w

        def menu(label, key, values, value, cmd=None):
            vv[key] = tk.StringVar(value=value if value in values else values[0])
            return row(label, lambda r: ctk.CTkOptionMenu(r, values=list(values), variable=vv[key],
                                                          command=cmd or (lambda _v: None)))

        def entry(label, key, value="", show=None, placeholder=""):
            vv[key] = tk.StringVar(value=str(value))
            return row(label, lambda r: ctk.CTkEntry(r, textvariable=vv[key], show=show or "",
                                                     placeholder_text=placeholder))

        def check(text, key, value):
            vv[key] = tk.BooleanVar(value=value)
            ctk.CTkCheckBox(f, text=text, variable=vv[key], text_color=TEXT).pack(anchor="w", padx=10, pady=2)

        head("AI SERVICE")
        note("Built-in works offline without any key (Whisper on this PC + the built-in viral scoring). With a key "
             "the AI reads the words and picks the best moments, and writes titles, hooks, descriptions and hashtags. "
             "Free keys: Google Gemini (aistudio.google.com) or Groq (console.groq.com). Keys stay on this PC.")
        labels = [v["label"] for v in V.PROVIDERS.values()]
        menu("Service", "provider", labels, V.PROVIDERS.get(ai.get("provider") or "offline", V.PROVIDERS["offline"])["label"],
             cmd=lambda _v: self.v_provider_changed())
        entry("Key", "key", ai.get("key", ""), show="*", placeholder="paste your key")
        entry("Model (empty = default)", "model", ai.get("model", ""))
        entry("Address (only 'Other')", "base", ai.get("base", ""))
        entry("Speech-to-text model", "stt", ai.get("stt", ""), placeholder="empty = default of the service")
        r = ctk.CTkFrame(f, fg_color="transparent")
        r.pack(fill="x", padx=6, pady=2)
        ctk.CTkButton(r, text="Test the key", width=120, command=self.v_test_key).pack(side="left")
        self.v_test_lbl = ctk.CTkLabel(r, text="", text_color=GREY, anchor="w", wraplength=230, justify="left")
        self.v_test_lbl.pack(side="left", padx=8)
        for k in ("key", "model", "base", "stt"):
            vv[k].trace_add("write", lambda *a: self.v_save_ai())

        head("SPEECH TO TEXT")
        menu("Words from", "speech", list(V.SPEECH.values()), V.SPEECH["local"])
        menu("Whisper model", "whisper", E.WHISPER, "small")
        entry("Speech language", "lang", "hi", placeholder="hi, en or auto")
        note("Whisper on this PC understands Hindi and English and needs no internet after the first start (small = "
             "fast, medium = more exact). The video's own captions: download the video with 'YouTube link' - its "
             "captions are saved next to it and used here (fastest).")

        head("PLATFORM AND CLIPS")
        menu("Platform", "platform", list(V.PLATFORMS), next(iter(V.PLATFORMS)), cmd=lambda _v: self.apply_platform())
        entry("Clips per part", "count", "3")
        entry("Shortest clip (s)", "min", "20")
        entry("Longest clip (s)", "max", "60")
        entry("Lowest score (0-100)", "min_score", "0")
        menu("Built-in focus", "focus_offline", E.FOCUS, "Funny + Emotional")
        entry("What to look for (AI)", "focus", "", placeholder="e.g. funny + emotional, fights, facts")
        entry("Language of titles / tags", "text_lang", "", placeholder="empty = like the speech; Hinglish, English ...")
        note("The platform sets the frame (Aspect & Crop > Output ratio) and the clip length. Every clip starts at "
             "the beginning of a sentence and ends after a finished sentence.")

        head("PART BY PART (fast)")
        entry("Part length (min)", "part_min", "10")
        entry("From (min)", "from_min", "0")
        entry("To (min, 0 = end)", "to_min", "0")
        note("The movie is worked on in parts: the clips of part 1 are exported while part 2 is already being "
             "listened to - you get the first clips after a few minutes, also for a 3-hour movie.")

        head("CAPTIONS (word by word)")
        check("Captions: the spoken word lights up", "captions", True)
        menu("Style", "cap_style", list(V.CAPTION_STYLES), next(iter(V.CAPTION_STYLES)))
        menu("Place", "cap_pos", list(V.CAPTION_POS), "Bottom")

        head("HOOK TITLE")
        check("Hook title for the first seconds (written by the AI, or the first words)", "hook", True)
        menu("Hook style", "hook_style", list(V.HOOK_STYLES), "White box")
        entry("Hook seconds", "hook_sec", "3")

        head("LAYOUT")
        menu("Layout", "layout", list(V.LAYOUTS), "Normal", cmd=lambda v: self.v_layout_note.configure(text=V.LAYOUTS[v]))
        self.v_layout_note = ctk.CTkLabel(f, text=V.LAYOUTS["Normal"], text_color=GREY, wraplength=360, justify="left",
                                          anchor="w")
        self.v_layout_note.pack(anchor="w", padx=8)
        entry("Facecam box % (optional)", "cam_box", "", placeholder="x, y, w, h  e.g. 70, 0, 30, 30")
        note("Follow the speaker: a 9:16 crop that moves with the face. Facecam: the streamer's face cam is found "
             "automatically (or type its box) and put above the game. Interview: two people, one in each half. "
             "When no face is found the clip keeps the normal picture. The layout shows in Play and in the export.")

        head("KEEP VIEWERS WATCHING")
        check("Punch-in zoom on the cuts", "b_zoom", False)
        check("Progress bar along the top", "b_bar", False)
        check("Even, loud speech", "b_loud", True)
        check("Crisp, vivid picture", "b_crisp", False)

        head("POST KIT")
        check("Cover picture + post text for every clip (always)", "kit_info", True)
        check("Also a ZIP kit per clip (video + cover + text)", "zip_kit", False)
        check("Add the platform's hashtags", "platform_tags", True)
        note("Every clip gets _cover.jpg and _post.txt (title, description, hashtags) next to it, and clips.csv "
             "lists all clips with their scores.")

        head("LIVE STREAM")
        entry("Live link", "live_url", "", placeholder="YouTube / Twitch / Kick live link")
        r = ctk.CTkFrame(f, fg_color="transparent")
        r.pack(fill="x", padx=6, pady=2)
        self.v_live_btn = ctk.CTkButton(r, text="Record + clip live", command=self.v_start_live)
        self.v_live_btn.pack(side="left")
        note("The stream is recorded into input_movies and clipped part by part while it is still running. Stop "
             "ends the recording.")

        head("LOG")
        self.v_log = ctk.CTkTextbox(f, height=160, wrap="word")
        self.v_log.pack(fill="x", padx=8, pady=(0, 10))
        note("Every other tab of this section (Aspect & Crop, Colour, Overlay, Text, Silence, Speed & Effects, "
             "Dialogue, Export) is used for every clip, exactly like in Simple Edit and AI Clipping.")
        self.v_provider_changed(save=False)

    # ---------------- settings helpers
    def v_ai(self):
        vv = self.vv
        prov = V.PROVIDER_BY_LABEL.get(vv["provider"].get(), "offline")
        return dict(provider=prov, key=vv["key"].get().strip(), model=vv["model"].get().strip(),
                    base=vv["base"].get().strip() if prov == "custom" or vv["base"].get().strip() else "",
                    stt=vv["stt"].get().strip())

    def v_save_ai(self):
        if not self.v_ready:
            return
        try:
            self.app.prefs["viral_ai"] = self.v_ai()
            PRJ.write_prefs(self.app.prefs)
        except Exception:
            pass

    def v_provider_changed(self, save=True):
        prov = V.PROVIDER_BY_LABEL.get(self.vv["provider"].get(), "offline")
        if prov != "offline" and self.vv["speech"].get() == V.SPEECH["gemini"] and prov != "gemini":
            self.vv["speech"].set(V.SPEECH["local"])
        if save:
            self.v_save_ai()

    def v_test_key(self):
        ai = self.v_ai()
        if ai["provider"] == "offline":
            self.v_test_lbl.configure(text="Built-in needs no key.")
            return
        self.v_test_lbl.configure(text="Testing ...")

        def work():
            try:
                ok = V.test_key(ai)
                msg = "The key works." if ok else "The AI answered, but not as expected."
            except Exception as e:
                msg = str(e)[:200]
            self.q.put(("vtest", msg))
        threading.Thread(target=work, daemon=True).start()

    def apply_platform(self, first=False):
        p = V.PLATFORMS.get(self.vv["platform"].get())
        if not p:
            return
        if not first or not self.parts:
            self.vv["min"].set(str(p["min"]))
            self.vv["max"].set(str(p["max"]))
        try:
            self.cfg_v["aspect"].set(p["aspect"])
            self.sync_cfg_and_render()
        except Exception:
            pass

    def _num(self, key, lo, hi, default):
        try:
            return min(hi, max(lo, float(str(self.vv[key].get()).strip() or default)))
        except ValueError:
            return default

    def v_opts(self):
        vv = self.vv
        mn, mx = self._num("min", 3, 600, 20), self._num("max", 5, 900, 60)
        cam = None
        txt = vv["cam_box"].get().strip()
        if txt:
            try:
                vals = [float(x) / 100 for x in txt.replace(";", ",").split(",")]
                if len(vals) == 4 and vals[2] > 0.02 and vals[3] > 0.02:
                    cam = [min(1, max(0, v)) for v in vals]
            except ValueError:
                cam = None
        to = self._num("to_min", 0, 100000, 0)
        return dict(
            platform=vv["platform"].get(), count=int(self._num("count", 1, 20, 3)), min=min(mn, mx), max=max(mn, mx),
            min_score=self._num("min_score", 0, 100, 0), focus=vv["focus"].get().strip(),
            focus_offline=vv["focus_offline"].get(), text_lang=vv["text_lang"].get().strip(),
            part_sec=self._num("part_min", 0.5, 120, 10) * 60, start=self._num("from_min", 0, 100000, 0) * 60,
            end=(to * 60) if to > 0 else None,
            speech=V.SPEECH_BY_LABEL.get(vv["speech"].get(), "local"), whisper_model=vv["whisper"].get(),
            lang=vv["lang"].get().strip(), captions=bool(vv["captions"].get()), cap_style=vv["cap_style"].get(),
            cap_pos=vv["cap_pos"].get(), hook=bool(vv["hook"].get()), hook_style=vv["hook_style"].get(),
            hook_sec=self._num("hook_sec", 1, 10, 3), layout=vv["layout"].get(), cam_box=cam,
            boost={k[2:]: True for k in ("b_zoom", "b_bar", "b_loud", "b_crisp") if vv[k].get()},
            zip_kit=bool(vv["zip_kit"].get()), platform_tags=bool(vv["platform_tags"].get()),
            title=os.path.splitext(os.path.basename(self.movie or "video"))[0])

    # ================================================================ running
    def v_log_add(self, m):
        self.q.put(("vlog", str(m)))

    def items_for_clip(self, items, clip, number):
        """Overlays + texts of this section for one clip (movie times), like every other part."""
        part = {"start": clip["start"], "end": clip["end"]}
        ovs, txs = [], []
        for it in items:
            it = eff_item(it, True, None)
            if it is None:
                continue
            d = self.localized_item(it, part, number)
            if d["end"] <= d["start"]:
                continue
            (ovs if it.get("kind") == "overlay" else txs).append(d)
        return ovs, txs

    def v_start(self, more=False, live=None):
        if self.vjob or self.eng:
            return
        if not self.movie and not live:
            messagebox.showwarning("Viral Clips", "Please choose a movie first (Browse..., YouTube link or a live link).")
            return
        o = self.v_opts()
        ai = self.v_ai()
        if ai["provider"] not in ("offline", "ollama", "lmstudio", "custom") and not ai["key"]:
            messagebox.showwarning("Viral Clips", "Paste the key of the AI service (or choose 'Built-in (offline, no key)').")
            return
        if o["speech"] == "gemini" and ai["provider"] != "gemini":
            messagebox.showwarning("Viral Clips", "'Gemini listens' needs the service Google Gemini and its key.")
            return
        if o["speech"] == "captions" and not live and not V.find_subtitles(self.movie):
            messagebox.showwarning("Viral Clips", "This video has no caption file next to it. Download it with "
                                                  "'YouTube link' (its captions come with it) or choose Whisper.")
            return
        if not more and self.parts and not live:
            if not messagebox.askyesno("Viral Clips", f"The list has {len(self.parts)} clip(s).\n\nStart again and "
                                                      "replace them?\n(No = keep them; use 'Find more' to add clips.)"):
                return
            self.parts, self.part_idx = [], 0
            self.refresh_parts()
        try:
            self.sync_export()
        except Exception:
            pass
        s = E.sanitize(dict(self.cfg))
        errs = E.validate(s, "simple")
        if errs:
            messagebox.showerror("Viral Clips", "\n".join(errs))
            return
        key = (self.movie, o["speech"], o["lang"], o["whisper_model"])
        if key != self.vcache_key:
            self.vcache, self.vcache_key = {}, key
        avoid = [(p["start"], p["end"]) for p in self.parts]
        items = copy.deepcopy(self.items)
        out_dir = self.out_dir_for(False)
        base = self.file_base()
        auto = bool(self.vv["auto"].get())
        movie = self.movie
        runner = E.Runner(s, self.v_log_add, None, None)
        self.vrunner = runner
        info_box = {}

        def export(clip):
            if "info" not in info_box:
                info_box["info"] = E.probe_info(movie)
            return V.export_clip(runner, movie, clip, s, o, out_dir, base, info_box["info"],
                                 lambda c: self.items_for_clip(items, c, c["n"]), self.v_log_add)

        first = self.part_number(len(self.parts))
        job = V.ViralJob(movie, o, ai, log=self.v_log_add, progress=lambda f, t: self.q.put(("vprog", (f, t))),
                         on_clip=lambda c: self.q.put(("vclip", c)), export=export if auto else None, live=live,
                         cache=self.vcache, avoid=avoid if more else [], first_number=first)
        self.vjob = job
        self.cur_out = out_dir
        self.v_go.configure(state="disabled")
        self.v_more.configure(state="disabled")
        self.v_stop.configure(state="normal")
        self.v_log.delete("1.0", "end")
        self.v_status.configure(text="Starting ...")
        self.v_usage.configure(text="")
        self.v_log_add(f"Viral Clips: {os.path.basename(movie)} | {o['platform']} | {V.PROVIDERS[ai['provider']]['label']}"
                       f" | words from: {V.SPEECH[o['speech']]}" + (" | every clip exported as it is found" if auto else ""))

        def work():
            err = None
            try:
                job.run()
            except Exception:
                err = traceback.format_exc()
                self.v_log_add("ERROR:\n" + err)
            self.q.put(("vdone", dict(n=len(job.found), usage=job.usage.text(), stopped=job.stop_flag, err=err,
                                      out=out_dir)))
        threading.Thread(target=work, daemon=True).start()

    def v_start_live(self):
        if self.vjob or self.eng:
            return
        url = self.vv["live_url"].get().strip()
        if not url.startswith("http"):
            messagebox.showwarning("Live", "Paste the link of a live stream first.")
            return
        import ytdl
        if not ytdl.available():
            messagebox.showerror("Live", "The downloader (yt-dlp) is not in this copy.")
            return
        os.makedirs(E.INPUT_DIR, exist_ok=True)
        path = os.path.join(E.INPUT_DIR, f"live_{time.strftime('%Y%m%d_%H%M%S')}.ts")
        rec = V.LiveRecorder(url, path, self.v_log_add)
        self.vrec = rec
        rec.start()
        # the recording is the movie of this section (it keeps growing)
        self.movie, self.info, self.dur = path, None, 0.0
        self.movie_menu.set(os.path.basename(path))
        self.info_lbl.configure(text="LIVE - recording ...")
        self.parts, self.part_idx = [], 0
        self.refresh_parts()
        self.v_start(False, live=rec)

    def v_stop_run(self):
        if self.vjob:
            self.vjob.stop()
        if self.vrunner:
            self.vrunner.stop()
        if self.vrec:
            self.vrec.stop()
        self.v_status.configure(text="Stopping ...")

    def v_open_folder(self):
        d = self.out_dir_for(False) if self.movie else E.OUTPUT_DIR
        os.makedirs(d, exist_ok=True)
        open_path(d)

    # ---------------- messages from the worker
    def on_other_msg(self, kind, v):
        if kind == "vlog":
            self.v_log.insert("end", v + "\n")
            self.v_log.see("end")
            self.v_status.configure(text=v.splitlines()[0][:120])
        elif kind == "vprog":
            if v[0] is not None:
                self.v_bar.set(max(0.0, min(1.0, v[0])))
            self.v_status.configure(text=v[1])
            if self.vrec and self.vrec.seconds:
                self.info_lbl.configure(text=f"LIVE - {V.tstr(self.vrec.seconds)} recorded")
                self.dur = max(self.dur, self.vrec.seconds)
        elif kind == "vtest":
            self.v_test_lbl.configure(text=v)
        elif kind == "vclip":
            self.v_add_clip(v)
        elif kind == "vdone":
            self.vjob, self.vrunner = None, None
            self.v_go.configure(state="normal")
            self.v_more.configure(state="normal")
            self.v_stop.configure(state="disabled")
            self.v_usage.configure(text=v["usage"])
            if self.vrec:
                self.vrec.stop()
                self.vrec = None
                self.v_live_finished()
            if v.get("err"):
                self.v_status.configure(text="Stopped by an error - see the LOG in the AI Clips tab.")
            elif v["stopped"]:
                self.v_status.configure(text=f"Stopped. {v['n']} clip(s) found. 'Find more' carries on.")
            else:
                self.v_status.configure(text=f"Done - {v['n']} clip(s). Tick / untick, edit, then Export "
                                             f"(right) to export the ticked clips again.")
            self.update_resume_label()

    def v_add_clip(self, c):
        label = f"{c.get('title') or 'Clip'}  |  score {int(c.get('score') or 0)}" + \
                (f"  |  {c['category']}" if c.get("category") else "")
        keep = {k: c.get(k) for k in ("title", "hook", "description", "hashtags", "category", "reason", "score",
                                      "words", "layout", "n")}
        part = {"on": True, "sil": False, "ov": True, "start": round(float(c["start"]), 3),
                "end": round(float(c["end"]), 3), "label": label, "viral": keep}
        self.parts.append(part)
        if self.vrec is None and self.dur and part["end"] > self.dur:
            part["end"] = self.dur
        if c.get("file") and self.cur_out:
            self.done_names.add(self.done_key(self.cur_out, os.path.basename(c["file"])))
            self.v_log.insert("end", f"Saved: {os.path.basename(c['file'])}\n")
            self.v_log.see("end")
        self.refresh_parts()
        if len(self.parts) == 1 and self.info:
            self.select_part(0)

    def v_live_finished(self):
        """The recording ended: open it as a normal movie (keeps the clips list)."""
        path = self.movie
        parts = self.parts
        try:
            self.info = E.probe_info(path)
            self.dur = self.info["duration"]
            self.info_lbl.configure(text=f"{self.info['w']}x{self.info['h']}  |  {self.dur / 60:.1f} min  |  live recording")
            self.pos_slider.configure(to=max(0.1, self.dur))
            self.parts = parts
            self.refresh_parts()
            if self.parts:
                self.select_part(0)
        except Exception as e:
            self.v_log.insert("end", f"The recording could not be opened: {e}\n")

    # ================================================================ export / preview of the clips
    def plan_file(self, idx, p):
        if p.get("viral"):
            return V.clip_file(self.file_base(), self.part_number(idx), p["viral"].get("title") or p.get("label"))
        return super().plan_file(idx, p)

    def _clip_of(self, p):
        return dict(p.get("viral") or {}, start=p["start"], end=p["end"])

    def build_plans(self, chosen):
        plans = super().build_plans(chosen)
        o = self.v_opts()
        movie = self.movie
        tags = (V.PLATFORMS.get(o["platform"]) or {}).get("tags", []) if o.get("platform_tags") else []
        for (idx, p), plan in zip(chosen, plans):
            clip = self._clip_of(p)
            plan["extra"] = dict(plan.get("extra") or {}, **V.clip_extras(clip, o))

            def after(f, clip=clip, zip_kit=o["zip_kit"]):
                V.make_kit(f, clip, movie, tags, zip_kit)
                V.append_csv(os.path.dirname(f), clip, f)
            plan["after"] = after
        return plans

    def preview_settings(self, part, number=1):
        s = super().preview_settings(part, number)
        if part.get("viral"):
            ex = V.clip_extras(self._clip_of(part), self.v_opts())
            ex.pop("_layout_req", None)
            if "_hook" in ex:
                ex["_hook"]["at"] = part["start"]
            s.update(ex)
        return s

    def render_now(self):
        """The still picture: captions and hook are shown as text layers (the layout shows when playing)."""
        self.render_after = None
        if not self.movie or not self.info:
            return
        part = self.current_part()
        t_abs = min(max(0.0, part["start"] + self.t_rel), max(0.0, self.dur - 0.05))
        self.pos_lbl.configure(text=f"Position: {V.tstr(self.t_rel)}")
        s = self.preview_settings(part, self.part_number(self.part_idx))
        texts = list(s.get("texts") or [])
        if s.get("_capwords"):
            st = V.CAPTION_STYLES.get(s["_capstyle"]) or next(iter(V.CAPTION_STYLES.values()))
            for t0, t1, text in V.caption_events([tuple(w) for w in s["_capwords"]], part["start"], part["end"], st):
                if t0 <= self.t_rel < t1:
                    texts.append(dict(V.caption_item(st, s["_cappos"], text), start=part["start"] + t0,
                                      end=part["start"] + t1))
                    break
        hk = s.get("_hook")
        if hk and self.t_rel < float(hk.get("sec", 3)):
            texts.append(dict(V.hook_item(hk.get("style"), hk["text"]), start=part["start"],
                              end=part["start"] + float(hk.get("sec", 3))))
        for k in ("_capwords", "_hook", "_layout", "_boost"):
            s.pop(k, None)
        s["texts"] = texts
        s = self.still_settings(s, part)
        self.token += 1
        self.renderer.submit(self.movie, t_abs, s, self.token)

    # ================================================================ project (save / open)
    def v_state(self):
        out = {}
        for k, var in self.vv.items():
            if k in ("key", "model", "base", "stt", "provider"):
                continue                       # the AI service and its key are kept on this PC, not in projects
            try:
                out[k] = var.get()
            except Exception:
                pass
        return out

    def get_state(self):
        st = super().get_state()
        st["viral"] = self.v_state()
        return st

    def set_state(self, st, movie_path=""):
        errs = super().set_state(st, movie_path)
        for k, val in ((st or {}).get("viral") or {}).items():
            if k in self.vv:
                try:
                    self.vv[k].set(val)
                except Exception:
                    pass
        try:
            self.v_layout_note.configure(text=V.LAYOUTS.get(self.vv["layout"].get(), ""))
        except Exception:
            pass
        return errs

    def on_close_cleanup(self):
        try:
            self.v_stop_run()
        except Exception:
            pass
        super().on_close_cleanup()
