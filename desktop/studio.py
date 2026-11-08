"""Studio: the easy editor used by the Simple Edit and AI Clipping tabs.

Left   : movie range, parts (or AI clips) with on/off and per-part silence cut.
Centre : live preview. Drag overlays and text with the mouse; pick a colour from the picture for chroma key.
Right  : Aspect & Crop, Colour, Overlay, Text, Silence, Export.
"""
import os, re, math, copy, queue, shutil, subprocess, threading, traceback
import dialogue
import auto_short
import colour as CL
import tkinter as tk
import customtkinter as ctk
from tkinter import filedialog, messagebox
from PIL import Image, ImageTk
import engine as E
import preview as P
from widgets import (NEON, NEON_D, NEON_H, BLACK, PANEL, FIELD, GREY, TEXT, EDGE, DANGER, DANGER_H,
                     QUIET, QUIET_H, IMG_VID, NumField, Form, FontPicker, conv, open_path, hex_to_rgb)

ENCODE_KEYS = ("resolution", "fps", "codec", "quality", "rate_mode", "bitrate", "audio_bitrate")


def play_file(path):
    """Plays a file with sound in a small window (ffplay ships with the FFmpeg full build)."""
    player = shutil.which("ffplay")
    if player:
        subprocess.Popen([player, "-autoexit", "-loglevel", "error",
                          "-window_title", "Chauhan Clipping - Preview", path], creationflags=E.NOWIN)
    else:
        from widgets import open_path
        open_path(path)


def tstr(t):
    t = max(0.0, float(t))
    m, s = divmod(t, 60)
    return f"{int(m):02d}:{s:04.1f}"


class Studio(ctk.CTkFrame):
    def __init__(self, parent, app, mode):
        super().__init__(parent, fg_color="transparent")
        self.app = app
        self.mode = mode                      # "simple" or "ai"
        self.movie, self.info, self.dur = "", None, 0.0
        self.cfg = E.sanitize({})             # every setting of this tab (colour, crop, export, AI, ...)
        self.cfg["orig_volume"] = 100
        self.items = []                       # overlays and texts; rel_start/rel_end are relative to the part
        self.sel = None
        self.parts = []                       # {"on", "sil", "start", "end", "label"} in movie seconds
        self.part_idx, self.t_rel = 0, 0.0
        self.sil_list, self.sil_key, self.sil_then = [], None, None
        self.pick_mode, self.drag, self.view, self.last_img = False, None, None, None
        self.q = queue.Queue()
        self.eng = None
        self.ai_eng = None
        self.renderer = P.Renderer(lambda img, tok, err: self.q.put(("frame", (img, tok, err))))
        self.token, self.shown = 0, -1
        self.render_after = None
        self._photo = None
        self.movie_paths = {}
        self.boxes = []
        self.sel_vars = {}
        self.build()
        self.refresh_movies()
        self.redraw_items()
        self.after(60, self.poll)

    # ================================================================ layout
    def build(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(1, weight=1)

        top = ctk.CTkFrame(self, corner_radius=10)
        top.grid(row=0, column=0, columnspan=3, sticky="ew", padx=6, pady=(4, 6))
        ctk.CTkLabel(top, text="Movie:", text_color=TEXT).pack(side="left", padx=(10, 4))
        self.movie_menu = ctk.CTkOptionMenu(top, values=["(no movie)"], width=340, command=self.on_movie_choice)
        self.movie_menu.pack(side="left", padx=4, pady=8)
        ctk.CTkButton(top, text="Browse...", width=90, command=self.browse).pack(side="left", padx=4)
        ctk.CTkButton(top, text="Refresh", width=80, fg_color=QUIET, hover_color=QUIET_H, text_color=TEXT,
                      command=self.refresh_movies).pack(side="left", padx=4)
        self.info_lbl = ctk.CTkLabel(top, text="No movie loaded", text_color=GREY)
        self.info_lbl.pack(side="left", padx=12)
        ctk.CTkButton(top, text="Open output folder", width=150, fg_color=QUIET, hover_color=QUIET_H,
                      text_color=TEXT, command=self.open_output).pack(side="right", padx=10)

        self.left = ctk.CTkFrame(self, width=330, corner_radius=10)
        self.left.grid(row=1, column=0, sticky="nsew", padx=(6, 4), pady=(0, 6))
        self.left.grid_propagate(False)
        self.build_left(self.left)

        centre = ctk.CTkFrame(self, corner_radius=10)
        centre.grid(row=1, column=1, sticky="nsew", padx=4, pady=(0, 6))
        centre.grid_rowconfigure(0, weight=1)
        centre.grid_columnconfigure(0, weight=1)
        self.cv = tk.Canvas(centre, bg="#000000", highlightthickness=0, bd=0)
        self.cv.grid(row=0, column=0, sticky="nsew", padx=8, pady=(8, 4))
        self.cv.bind("<Button-1>", self.on_press)
        self.cv.bind("<B1-Motion>", self.on_drag)
        self.cv.bind("<ButtonRelease-1>", self.on_release)
        self.cv.bind("<Configure>", lambda e: self.refresh_view())
        bar = ctk.CTkFrame(centre, fg_color="transparent")
        bar.grid(row=1, column=0, sticky="ew", padx=8, pady=(0, 2))
        bar.grid_columnconfigure(1, weight=1)
        self.pos_lbl = ctk.CTkLabel(bar, text="Position: 00:00.0", text_color=TEXT, width=150, anchor="w")
        self.pos_lbl.grid(row=0, column=0, padx=4)
        self.pos_slider = ctk.CTkSlider(bar, from_=0, to=1, command=self.on_pos_slider)
        self.pos_slider.set(0)
        self.pos_slider.grid(row=0, column=1, sticky="ew", padx=6)
        self.pick_btn = ctk.CTkButton(bar, text="Pick colour from picture", width=190,
                                      fg_color=QUIET, hover_color=QUIET_H, text_color=TEXT,
                                      command=self.toggle_pick)
        self.pick_btn.grid(row=0, column=2, padx=4)
        self.hint = ctk.CTkLabel(centre, text="Tip: drag an overlay or text on the picture to move it. "
                                              "Use the numbers on the right for exact position.",
                                 text_color=GREY, anchor="w")
        self.hint.grid(row=2, column=0, sticky="ew", padx=10, pady=(0, 6))

        self.head_on = tk.BooleanVar(value=False)      # cut only the first N seconds of every part
        self.head_sec = tk.StringVar(value="3")
        self.dl_on = tk.BooleanVar(value=False)        # dialogue clean-up ON / OFF (same switch in several tabs)
        self.right = ctk.CTkTabview(self, width=410)
        self.right.grid(row=1, column=2, sticky="nsew", padx=(4, 6), pady=(0, 6))
        for name in ("Aspect & Crop", "Colour", "Overlay", "Text", "Silence", "Export", "Dialogue"):
            self.right.add(name)
        self.build_aspect(self.right.tab("Aspect & Crop"))
        self.build_colour(self.right.tab("Colour"))
        self.build_overlay(self.right.tab("Overlay"))
        self.build_text(self.right.tab("Text"))
        self.build_silence(self.right.tab("Silence"))
        self.build_export(self.right.tab("Export"))
        self.build_dialogue(self.right.tab("Dialogue"))

    def scroll(self, parent):
        f = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        f.pack(fill="both", expand=True, padx=2, pady=2)
        return f

    # ---------------- left: range / parts (or AI)
    def build_left(self, p):
        ctk.CTkLabel(p, text=("1. AI FINDS THE CLIPS" if self.mode == "ai" else "1. RANGE AND PARTS"),
                     font=ctk.CTkFont(size=13, weight="bold"), text_color=NEON).pack(anchor="w", padx=10, pady=(10, 2))
        if self.mode == "simple":
            self.p_start = tk.StringVar(value="0")
            self.p_end = tk.StringVar(value="")
            self.p_count = tk.StringVar(value="3")
            self.p_len = tk.StringVar(value="0")
            grid = ctk.CTkFrame(p, fg_color="transparent")
            grid.pack(fill="x", padx=8)
            rows = [("Start (sec)", self.p_start, "Movie ka kahan se shuru (0 = start)"),
                    ("End (sec)", self.p_end, "Kahan tak (khali = poora movie)"),
                    ("Number of parts", self.p_count, "Kitne parts (ya niche length)"),
                    ("OR part length (sec)", self.p_len, "0 = use the count above")]
            for r, (lbl, var, tip) in enumerate(rows):
                ctk.CTkLabel(grid, text=lbl, text_color=TEXT, anchor="w", width=150).grid(
                    row=r, column=0, sticky="w", pady=3)
                ctk.CTkEntry(grid, textvariable=var, width=110, placeholder_text=tip).grid(
                    row=r, column=1, sticky="w", pady=3)
            ctk.CTkButton(p, text="Make parts", height=36, command=self.make_parts).pack(fill="x", padx=8, pady=6)
        else:
            self.ai_v = {}
            fm = Form(ctk.CTkFrame(p, fg_color="transparent"), self.ai_v, self.cfg)
            box = fm.p
            box.pack(fill="x", padx=8)
            fm.menu("Focus", "focus", E.FOCUS)
            fm.entry("Min clip (sec)", "min_dur")
            fm.entry("Max clip (sec)", "max_dur")
            fm.entry("Min viral score", "min_score")
            fm.entry("Max clips / 10 min", "max_per_chunk")
            fm.entry("Max total (0 = no limit)", "max_total")
            fm.menu("Language", "language", E.LANGS)
            fm.menu("Speech model", "whisper_model", E.WHISPER)
            fm.note("Small model = fast. Medium = more accurate but slower.")
            row = ctk.CTkFrame(p, fg_color="transparent")
            row.pack(fill="x", padx=8, pady=4)
            self.ai_go = ctk.CTkButton(row, text="Find clips with AI", height=36, command=self.find_clips_ai)
            self.ai_go.pack(side="left", fill="x", expand=True)
            self.ai_stop_btn = ctk.CTkButton(row, text="Stop", width=70, height=36, fg_color=DANGER,
                                             hover_color=DANGER_H, text_color=TEXT, state="disabled",
                                             command=self.stop_ai)
            self.ai_stop_btn.pack(side="left", padx=(6, 0))
            self.ai_bar = ctk.CTkProgressBar(p)
            self.ai_bar.set(0)
            self.ai_bar.pack(fill="x", padx=8, pady=(4, 2))
            self.ai_status = ctk.CTkLabel(p, text="Ready", text_color=GREY, anchor="w")
            self.ai_status.pack(fill="x", padx=10)

        ctk.CTkLabel(p, text="PARTS", font=ctk.CTkFont(size=13, weight="bold"), text_color=NEON).pack(
            anchor="w", padx=10, pady=(10, 2))
        bar = ctk.CTkFrame(p, fg_color="transparent")
        bar.pack(fill="x", padx=8)
        ctk.CTkButton(bar, text="Add part", width=90, fg_color=QUIET, hover_color=QUIET_H, text_color=TEXT,
                      command=self.add_part).pack(side="left")
        ctk.CTkButton(bar, text="All on", width=70, fg_color=QUIET, hover_color=QUIET_H, text_color=TEXT,
                      command=lambda: self.set_all_parts(True)).pack(side="left", padx=4)
        ctk.CTkButton(bar, text="All off", width=70, fg_color=QUIET, hover_color=QUIET_H, text_color=TEXT,
                      command=lambda: self.set_all_parts(False)).pack(side="left")
        numrow = ctk.CTkFrame(p, fg_color="transparent")
        numrow.pack(fill="x", padx=8, pady=(4, 0))
        ctk.CTkLabel(numrow, text="First part number", text_color=TEXT, width=150, anchor="w").pack(side="left")
        self.num_start = tk.StringVar(value="1")
        ctk.CTkEntry(numrow, textvariable=self.num_start, width=70).pack(side="left")
        self.parts_box = ctk.CTkScrollableFrame(p, height=220)
        self.parts_box.pack(fill="both", expand=True, padx=6, pady=6)
        self.parts_sum = ctk.CTkLabel(p, text="No parts yet", text_color=GREY, anchor="w")
        self.parts_sum.pack(fill="x", padx=10, pady=(0, 8))

    # ---------------- right: aspect & crop (two separate stages)
    def build_aspect(self, tab):
        f = self.scroll(tab)
        self.cfg_v = {}
        inner = ctk.CTkFrame(f, fg_color="transparent")
        inner.pack(fill="x")
        fm = Form(inner, self.cfg_v, self.cfg, self.sync_cfg_and_render)
        fm.header("1. IMPORTED MOVIE - crop it here")
        fm.menu("Crop ratio of the movie", "src_aspect", E.ASPECTS)
        fm.note("This crops the movie you imported. 1:1 = square picture from a 16:9 movie.")
        self.f_zoom = NumField(f, "Zoom in", 1.0, 3.0, 0.05, self.cfg["zoom"], "{:.2f}",
                               lambda v: self.set_cfg("zoom", v))
        self.f_zoom.pack(fill="x", padx=6, pady=3)
        self.f_cx = NumField(f, "Move left-right %", 0, 100, 1, self.cfg["crop_x"], "{:.0f}",
                             lambda v: self.set_cfg("crop_x", v))
        self.f_cx.pack(fill="x", padx=6, pady=3)
        self.f_cy = NumField(f, "Move up-down %", 0, 100, 1, self.cfg["crop_y"], "{:.0f}",
                             lambda v: self.set_cfg("crop_y", v))
        self.f_cy.pack(fill="x", padx=6, pady=3)
        ff = ctk.CTkFrame(f, fg_color="transparent")
        ff.pack(fill="x")
        fm2 = Form(ff, self.cfg_v, self.cfg, self.sync_cfg_and_render)
        fm2.check("Remove black bars from the movie automatically", "auto_crop")
        fm2.header("2. FINAL OUTPUT - the video you export")
        fm2.menu("Output ratio", "aspect", E.ASPECTS)
        fm2.menu("Background of the frame", "fit_mode", E.FIT_MODES)
        fm2.color("Background colour", "bg_color")
        fm2.note("Blur = blurred copy of the movie behind it, Black bars = black, Solid colour = the colour picked "
                 "above, Crop = fill the frame (cuts the edges). Example: movie cropped to 1:1 + output 9:16 = a tall "
                 "video with the square picture in the middle and the background around it.")
        gg = ctk.CTkFrame(f, fg_color="transparent")
        gg.pack(fill="x")
        self.f_blur = NumField(gg, "Blur strength", 5, 60, 1, self.cfg["blur_amount"], "{:.0f}",
                               lambda v: self.set_cfg("blur_amount", v))
        self.f_blur.pack(fill="x", padx=6, pady=3)
        self.f_fscale = NumField(gg, "Movie size in frame %", 30, 100, 1, self.cfg["fit_scale"], "{:.0f}",
                                 lambda v: self.set_cfg("fit_scale", v))
        self.f_fscale.pack(fill="x", padx=6, pady=3)
        self.f_fy = NumField(gg, "Movie up-down in frame %", 0, 100, 1, self.cfg["fit_y"], "{:.0f}",
                             lambda v: self.set_cfg("fit_y", v))
        self.f_fy.pack(fill="x", padx=6, pady=3)
        ctk.CTkLabel(gg, text="Blur strength is used with Blur background. Movie size and up-down position work with "
                              "Blur, Black bars and Solid colour (100 % = as big as the frame allows).",
                     text_color=GREY, wraplength=330, justify="left", anchor="w").pack(anchor="w", padx=8, pady=(0, 6))

    # ---------------- right: colour correction (live)
    def build_colour(self, tab):
        f = self.scroll(tab)
        ctk.CTkLabel(f, text="COLOUR CORRECTION (live preview)", font=ctk.CTkFont(size=13, weight="bold"),
                     text_color=NEON).pack(anchor="w", padx=10, pady=(10, 0))
        ctk.CTkLabel(f, text="Every control goes from -100 to +100 (0 = no change). Drag the slider or type a number. "
                             "Double-click a name to reset that control.", text_color=GREY, wraplength=330,
                     justify="left", anchor="w").pack(anchor="w", padx=10, pady=(0, 4))
        self.colour_fields = {}
        for section, items in CL.LAYOUT:
            ctk.CTkLabel(f, text=section, font=ctk.CTkFont(size=12, weight="bold"), text_color=NEON,
                         anchor="w").pack(anchor="w", padx=10, pady=(12, 2))
            for key, label in items:
                nf = NumField(f, label, -100, 100, 1, CL.to_ui(key, self.cfg[key]), "{:.0f}",
                              lambda v, k=key: self.set_cfg(k, CL.to_cfg(k, v)), label_width=110, default=0)
                nf.pack(fill="x", padx=6, pady=2)
                self.colour_fields[key] = nf
        ctk.CTkButton(f, text="Reset all colour", fg_color=QUIET, hover_color=QUIET_H, text_color=TEXT,
                      command=self.reset_colour).pack(anchor="w", padx=10, pady=12)

    def reset_colour(self):
        for key, nf in self.colour_fields.items():
            nf.set(0, notify=True)

    # ---------------- right: overlays (photo / video / GIF with background removal)
    def build_overlay(self, tab):
        self.ov_tab = tab
        bar = ctk.CTkFrame(tab, fg_color="transparent")
        bar.pack(fill="x", padx=6, pady=(8, 2))
        ctk.CTkButton(bar, text="+ Add photo / video", command=lambda: self.add_item("overlay")).pack(side="left")
        ctk.CTkButton(bar, text="Remove", width=90, fg_color=DANGER, hover_color=DANGER_H, text_color=TEXT,
                      command=self.remove_selected).pack(side="right")
        self.ov_list = ctk.CTkScrollableFrame(tab, height=110, label_text="Overlays on this part")
        self.ov_list.pack(fill="x", padx=6, pady=4)
        self.ov_editor = ctk.CTkScrollableFrame(tab)
        self.ov_editor.pack(fill="both", expand=True, padx=6, pady=(2, 6))

    def build_text(self, tab):
        self.tx_tab = tab
        bar = ctk.CTkFrame(tab, fg_color="transparent")
        bar.pack(fill="x", padx=6, pady=(8, 2))
        ctk.CTkButton(bar, text="+ Add text", command=lambda: self.add_item("text")).pack(side="left")
        ctk.CTkButton(bar, text="+ Add part number", command=lambda: self.add_item("number")).pack(
            side="left", padx=6)
        ctk.CTkButton(bar, text="Remove", width=90, fg_color=DANGER, hover_color=DANGER_H, text_color=TEXT,
                      command=self.remove_selected).pack(side="right")
        ctk.CTkLabel(tab, text="Part number: every part gets its own number in order (1, 2, 3 ...), starting from "
                               "'First part number' in the Parts panel. Drag it with the mouse in the preview. It is "
                               "a normal text, so font, colour, size, outline, shadow and box all work. Write "
                               "{n} anywhere in a text (for example Part {n}).",
                     text_color=GREY, wraplength=360, justify="left", anchor="w").pack(anchor="w", padx=8, pady=(0, 2))
        self.tx_list = ctk.CTkScrollableFrame(tab, height=110, label_text="Texts on this part")
        self.tx_list.pack(fill="x", padx=6, pady=4)
        self.tx_editor = ctk.CTkScrollableFrame(tab)
        self.tx_editor.pack(fill="both", expand=True, padx=6, pady=(2, 6))

    # ---------------- right: silence
    def build_silence(self, tab):
        f = self.scroll(tab)
        self.sil_on = tk.BooleanVar(value=True)
        ctk.CTkSwitch(f, text="Cut long silent pauses (only in ticked parts)", variable=self.sil_on,
                      text_color=TEXT, command=lambda: self.update_cut_info()).pack(anchor="w", padx=10, pady=(10, 4))
        self.head_row(f)
        ctk.CTkLabel(f, text="SETTINGS", font=ctk.CTkFont(size=13, weight="bold"), text_color=NEON).pack(
            anchor="w", padx=10, pady=(6, 2))
        self.sil_db = NumField(f, "Quiet below (dB)", -60, -20, 1, -35, "{:.0f}", self.sil_changed, label_width=150)
        self.sil_db.pack(fill="x", padx=6, pady=3)
        self.sil_min = NumField(f, "Silence longer than (s)", 0.5, 10, 0.5, 2.0, "{:.1f}", self.sil_changed,
                                label_width=150)
        self.sil_min.pack(fill="x", padx=6, pady=3)
        self.sil_pad = NumField(f, "Keep around speech (s)", 0.0, 1.0, 0.05, 0.25, "{:.2f}", self.sil_changed,
                                label_width=150)
        self.sil_pad.pack(fill="x", padx=6, pady=3)
        ctk.CTkLabel(f, text="Default: silence of 2 seconds or more (quieter than -35 dB) is cut. The amount kept "
                             "around speech stops words from being clipped.",
                     text_color=GREY, wraplength=340, justify="left").pack(anchor="w", padx=10, pady=4)
        ctk.CTkButton(f, text="Scan this movie for silence", height=36, command=self.scan_silence).pack(
            fill="x", padx=10, pady=(8, 4))
        self.sil_summary = ctk.CTkLabel(f, text="Not scanned yet", text_color=GREY, wraplength=340,
                                        justify="left", anchor="w")
        self.sil_summary.pack(fill="x", padx=10, pady=4)
        self.sil_text = ctk.CTkTextbox(f, height=160)
        self.sil_text.pack(fill="x", padx=10, pady=(4, 10))

    # ---------------- right: export
    def build_export(self, tab):
        f = self.scroll(tab)
        self.exp_v = {}
        ctk.CTkLabel(f, text="CUTTING (ON / OFF)", font=ctk.CTkFont(size=13, weight="bold"),
                     text_color=NEON).pack(anchor="w", padx=10, pady=(10, 2))
        ctk.CTkSwitch(f, text="Cut silent pauses", variable=self.sil_on, text_color=TEXT,
                      command=self.update_cut_info).pack(anchor="w", padx=10, pady=4)
        ctk.CTkSwitch(f, text="Dialogue clean-up (keep only talking)", variable=self.dl_on, text_color=TEXT,
                      command=self.update_cut_info).pack(anchor="w", padx=10, pady=4)
        self.head_row(f)
        self.cut_info = ctk.CTkLabel(f, text="", text_color=GREY, wraplength=360, justify="left", anchor="w")
        self.cut_info.pack(fill="x", padx=10, pady=(0, 6))
        self.preset_menu = ctk.CTkOptionMenu(f, values=list(E.EXPORT_PRESETS), command=self.apply_export_preset)
        self.preset_menu.set("Quick preset - choose one ...")
        self.preset_menu.pack(fill="x", padx=10, pady=(10, 0))
        inner = ctk.CTkFrame(f, fg_color="transparent")   # grid rows live here, pack rows below
        inner.pack(fill="x")
        fm = Form(inner, self.exp_v, self.cfg)
        fm.header("Video quality")
        fm.menu("Resolution (short side)", "resolution", E.RES)
        fm.menu("Frame rate", "fps", E.FPS)
        fm.menu("Codec", "codec", E.CODECS)
        fm.menu("Quality (encoder speed / detail)", "quality", list(E.QUALITY))
        fm.menu("Bitrate mode", "rate_mode", E.RATE_MODES)
        fm.combo("Bitrate (kbps)", "bitrate", E.BITRATES)
        fm.menu("Audio bitrate", "audio_bitrate", E.ABR)
        fm.note("Exact bitrate: the file gets the bitrate you type (50000 kbps = 50 Mbps) - this is what the file's "
                "Properties > Details shows. The file size is bitrate x length. Quality mode: constant quality, the "
                "number is only an upper limit, so simple scenes can end up far below it. "
                "Resolution 'Original' keeps your movie's own size. NVIDIA codecs use the GTX GPU; if the GPU fails "
                "the CPU codec is used automatically.")
        ctk.CTkLabel(f, text="PREVIEW (see your edit before exporting)", font=ctk.CTkFont(size=13, weight="bold"),
                     text_color=NEON).pack(anchor="w", padx=10, pady=(12, 2))
        ctk.CTkButton(f, text="Play selected part with sound", height=36, fg_color=QUIET, hover_color=QUIET_H,
                      text_color=TEXT, command=lambda: self.play_preview(False)).pack(fill="x", padx=10, pady=3)
        ctk.CTkButton(f, text="Play whole edit (all ticked parts)", height=36, fg_color=QUIET, hover_color=QUIET_H,
                      text_color=TEXT, command=lambda: self.play_preview(True)).pack(fill="x", padx=10, pady=3)
        self.exp_go = ctk.CTkButton(f, text="EXPORT SELECTED PARTS", height=44,
                                    font=ctk.CTkFont(size=14, weight="bold"), command=lambda: self.export())
        self.exp_go.pack(fill="x", padx=10, pady=(14, 4))
        self.exp_stop = ctk.CTkButton(f, text="Stop", height=34, fg_color=DANGER, hover_color=DANGER_H,
                                      text_color=TEXT, state="disabled", command=self.stop_export)
        self.exp_stop.pack(fill="x", padx=10, pady=4)
        self.exp_bar = ctk.CTkProgressBar(f)
        self.exp_bar.set(0)
        self.exp_bar.pack(fill="x", padx=10, pady=(8, 2))
        self.exp_status = ctk.CTkLabel(f, text="Ready", text_color=GREY, anchor="w")
        self.exp_status.pack(fill="x", padx=10)
        self.exp_log = ctk.CTkTextbox(f, height=180)
        self.exp_log.pack(fill="x", padx=10, pady=(4, 10))
        self.update_cut_info()

    def head_row(self, parent):
        """'Only the first N seconds of every part' - the same two variables are shown in the Export, Silence and
        Dialogue tabs."""
        hr = ctk.CTkFrame(parent, fg_color="transparent")
        hr.pack(fill="x", padx=10, pady=4)
        ctk.CTkSwitch(hr, text="Apply only to the first", variable=self.head_on, text_color=TEXT,
                      command=self.cut_changed).pack(side="left")
        ctk.CTkEntry(hr, width=48, textvariable=self.head_sec).pack(side="left", padx=6)
        ctk.CTkLabel(hr, text="seconds of every part (rest stays normal)", text_color=TEXT).pack(side="left")
        if not getattr(self, "_head_traced", False):
            self._head_traced = True
            self.head_sec.trace_add("write", lambda *a: self.cut_changed())

    def cut_changed(self):
        try:
            self.update_cut_info()
            self.update_sil_summary()
        except Exception:
            pass

    def head_seconds(self):
        try:
            return max(0.5, float(str(self.head_sec.get()).replace(",", ".")))
        except ValueError:
            return 3.0

    def head_end(self, start, end):
        """End of the part that gets cut (None = the whole part)."""
        if not self.head_on.get():
            return None
        h = start + self.head_seconds()
        return h if h < end - 0.05 else None

    def with_tail(self, pieces, start, end):
        h = self.head_end(start, end)
        return pieces if h is None else list(pieces) + [(h, end - h)]

    def update_cut_info(self):
        """Shows what the export button will do with the two switches."""
        dl, sl = bool(self.dl_on.get()), bool(self.sil_on.get())
        if dl:
            msg = ("Dialogue clean-up is ON: only the talking is kept in every ticked part (silence and pauses are "
                   "removed).")
        elif sl:
            msg = "Silence cut is ON: long silent pauses are removed from the ticked parts (parts with 'cut silence' ticked)."
        else:
            msg = "Both OFF: the movie is only converted into parts. Nothing is removed - no silence, no dialogue cut."
        if (dl or sl) and self.head_on.get():
            msg += f"  Only the first {self.head_seconds():g} s of every part is cut; the rest of the part stays as it is."
        try:
            self.cut_info.configure(text=msg)
            self.exp_go.configure(text="EXPORT SELECTED PARTS" + (" (DIALOGUE CLEAN-UP)" if dl else " (SILENCE CUT)" if sl else " (PLAIN PARTS)"))
        except Exception:
            pass

    # ---------------- right: dialogue clean-up (only the selected parts)
    def apply_export_preset(self, name):
        for k, v in E.EXPORT_PRESETS.get(name, {}).items():
            if k in self.exp_v:
                self.exp_v[k].set(v)

    def build_dialogue(self, tab):
        f = self.scroll(tab)
        ctk.CTkLabel(f, text="DIALOGUE CLEAN-UP (selected parts only)", font=ctk.CTkFont(size=13, weight="bold"),
                     text_color=NEON).pack(anchor="w", padx=10, pady=(10, 2))
        ctk.CTkLabel(f, text="Works only on the ticked parts' time ranges, so it is fast. Every ticked part gets "
                             "its own clean-up and is exported with it.", text_color=GREY, wraplength=360,
                     justify="left").pack(anchor="w", padx=10, pady=(0, 6))
        ctk.CTkSwitch(f, text="Dialogue clean-up ON (the Export tab's export button uses it)", variable=self.dl_on,
                      text_color=TEXT, command=lambda: self.update_cut_info()).pack(anchor="w", padx=10, pady=(0, 6))
        self.head_row(f)
        self.dl_denoise = tk.BooleanVar(value=True)
        self.dl_vad = tk.BooleanVar(value=True)
        self.dl_whisper = tk.BooleanVar(value=False)
        for var, text in ((self.dl_denoise, "Noise reduction (FFmpeg)"),
                          (self.dl_vad, "Keep only talking (Silero AI, else built-in detector)"),
                          (self.dl_whisper, "Text editing with faster-whisper (word list below)")):
            ctk.CTkCheckBox(f, text=text, variable=var, text_color=TEXT).pack(anchor="w", padx=10, pady=3)
        self.dl_pad = NumField(f, "Speech padding (ms)", 0, 500, 10, 150, "{:.0f}", None, label_width=170)
        self.dl_pad.pack(fill="x", padx=6, pady=3)
        self.dl_minsil = NumField(f, "Minimum silence (ms)", 50, 1000, 10, 300, "{:.0f}", None, label_width=170)
        self.dl_minsil.pack(fill="x", padx=6, pady=3)
        self.dl_minpiece = NumField(f, "Shortest clip (s)", 0, 5, 0.1, dialogue.MIN_PIECE, "{:.1f}", None,
                                    label_width=170)
        self.dl_minpiece.pack(fill="x", padx=6, pady=3)
        ctk.CTkLabel(f, text="Shortest clip: a dialogue piece shorter than this is made longer with the sound and "
                             "picture around it, so no 0.2 second flash cuts are left (1.0 is a good value).",
                     text_color=GREY, wraplength=360, justify="left").pack(anchor="w", padx=10, pady=(0, 4))
        self.dl_scan = tk.BooleanVar(value=False)
        ctk.CTkCheckBox(f, text="Scan the picture: skip fast-cut montage, cut on shot changes (slower)",
                        variable=self.dl_scan, text_color=TEXT).pack(anchor="w", padx=10, pady=3)
        ctk.CTkLabel(f, text="Words to remove (comma separated)", text_color=TEXT, anchor="w").pack(
            anchor="w", padx=10, pady=(8, 0))
        self.dl_remove = tk.StringVar(value="um, uh")
        ctk.CTkEntry(f, textvariable=self.dl_remove).pack(fill="x", padx=10, pady=2)
        ctk.CTkLabel(f, text="Language code (blank = auto, e.g. hi or en)", text_color=TEXT, anchor="w").pack(
            anchor="w", padx=10, pady=(6, 0))
        self.dl_lang = tk.StringVar(value="")
        ctk.CTkEntry(f, textvariable=self.dl_lang, width=120).pack(anchor="w", padx=10, pady=2)
        ctk.CTkLabel(f, text="Wherever nobody is talking, BOTH the picture and the sound are cut, so you get one "
                             "continuous talking video. Picture and sound are cut together in one pass (always in "
                             "sync) and every cut has a 20 ms fade (no clicks). Overlay and text times count from "
                             "the start of the joined clip. Parts exported this way skip the silence cut, because "
                             "the dialogue detection already removes the silence.",
                     text_color=GREY, wraplength=360, justify="left").pack(anchor="w", padx=10, pady=6)
        ctk.CTkButton(f, text="EXPORT TICKED PARTS WITH DIALOGUE CLEAN-UP", height=44,
                      font=ctk.CTkFont(size=13, weight="bold"),
                      command=lambda: self.export(with_dialogue=True)).pack(fill="x", padx=10, pady=(8, 6))

    def dialogue_opts(self):
        try:
            return dict(denoise=bool(self.dl_denoise.get()), vad=bool(self.dl_vad.get()),
                        whisper=bool(self.dl_whisper.get()), remove_words=self.dl_remove.get(),
                        language=self.dl_lang.get().strip(), pad_ms=int(self.dl_pad.get()),
                        min_sil_ms=int(self.dl_minsil.get()), min_piece=float(self.dl_minpiece.get()),
                        scan_picture=bool(self.dl_scan.get()))
        except ValueError:
            raise ValueError("Enter the padding and silence values as numbers.")

    # ================================================================ movie
    def refresh_movies(self):
        names, self.movie_paths = [], {}
        for p in E.list_movies():
            n = os.path.basename(p)
            names.append(n)
            self.movie_paths[n] = p
        if not names:
            names = ["(no movie - put files in input_movies)"]
        self.movie_menu.configure(values=names)
        if self.movie:
            self.movie_menu.set(os.path.basename(self.movie))

    def browse(self):
        p = filedialog.askopenfilename(filetypes=[("Video", "*.mp4 *.mkv *.avi *.mov *.wmv *.webm *.m4v *.ts")])
        if p:
            self.load_movie(p)

    def on_movie_choice(self, name):
        if name in self.movie_paths:
            self.load_movie(self.movie_paths[name])

    def load_movie(self, path):
        try:
            info = E.probe_info(path)
        except Exception as e:
            messagebox.showerror("Movie", f"This movie could not be opened:\n{e}")
            return
        self.movie, self.info, self.dur = path, info, float(info["duration"])
        if os.path.basename(path) in self.movie_paths:
            self.movie_menu.set(os.path.basename(path))
        self.info_lbl.configure(text=f"{info['w']}x{info['h']}  |  {self.dur / 60:.1f} min  |  "
                                     f"{'with audio' if info.get('has_audio') else 'NO audio'}")
        self.items, self.sel = [], None
        self.parts, self.part_idx, self.t_rel = [], 0, 0.0
        self.sil_list, self.sil_key = [], None
        self.sil_summary.configure(text="Not scanned yet")
        self.sil_text.delete("1.0", "end")
        if self.mode == "simple":
            self.p_end.set("")
        self.refresh_parts()
        self.redraw_items()
        self.refresh_editors()
        self.select_part(0)

    def open_output(self):
        os.makedirs(E.OUTPUT_DIR, exist_ok=True)
        open_path(E.OUTPUT_DIR)

    # ================================================================ cfg helpers
    def set_cfg(self, key, value):
        self.cfg[key] = value
        self.schedule_render()

    def sync_cfg_and_render(self):
        for k, var in self.cfg_v.items():
            try:
                self.cfg[k] = conv(E.DEFAULTS[k], var.get())
            except (ValueError, Exception):
                pass
        self.schedule_render()

    def sync_export(self):
        for k, var in self.exp_v.items():
            self.cfg[k] = conv(E.DEFAULTS[k], var.get())

    # ================================================================ parts
    def make_parts(self):
        if not self.movie:
            messagebox.showwarning("Parts", "Please choose a movie first (top bar).")
            return
        try:
            a = max(0.0, float(self.p_start.get() or 0))
            b = float(self.p_end.get()) if self.p_end.get().strip() else self.dur
            b = min(b, self.dur)
            count = int(float(self.p_count.get() or 1))
            length = float(self.p_len.get() or 0)
        except ValueError:
            messagebox.showerror("Parts", "Enter Start, End, count and length as numbers.")
            return
        if b <= a + 0.5:
            messagebox.showerror("Parts", "End, Start se kaafi bada hona chahiye.")
            return
        spans = []
        if length > 0:
            if length < 2:
                messagebox.showerror("Parts", "Part length kam se kam 2 second honi chahiye.")
                return
            t = a
            while t < b - 0.5:
                spans.append((t, min(length, b - t)))
                t += length
        else:
            count = max(1, min(count, 500))
            piece = (b - a) / count
            spans = [(a + i * piece, piece) for i in range(count)]
        self.parts = [{"on": True, "sil": True, "start": round(t, 3), "end": round(t + d, 3), "label": ""}
                      for t, d in spans]
        self.refresh_parts()
        self.select_part(0)

    def add_part(self):
        if not self.movie:
            return
        last = self.parts[-1]["end"] if self.parts else 0.0
        st = min(last, max(0.0, self.dur - 1))
        self.parts.append({"on": True, "sil": True, "start": round(st, 3),
                           "end": round(min(self.dur, st + 30), 3), "label": ""})
        self.refresh_parts()

    def set_all_parts(self, on):
        for p in self.parts:
            p["on"] = on
        self.refresh_parts()

    def refresh_parts(self):
        for w in self.parts_box.winfo_children():
            w.destroy()
        for i, p in enumerate(self.parts):
            row = ctk.CTkFrame(self.parts_box, corner_radius=8,
                               fg_color=("#1B2E16" if i == self.part_idx else "#141414"))
            row.pack(fill="x", padx=3, pady=3)
            on = tk.BooleanVar(value=bool(p["on"]))
            on.trace_add("write", lambda *a, p=p, v=on: self._set_flag(p, "on", v))
            ctk.CTkCheckBox(row, text=f"Part {i + 1}", variable=on, width=90).grid(row=0, column=0, padx=6, pady=(6, 0),
                                                                                   sticky="w")
            sil = tk.BooleanVar(value=bool(p["sil"]))
            sil.trace_add("write", lambda *a, p=p, v=sil: self._set_flag(p, "sil", v))
            ctk.CTkCheckBox(row, text="cut silence", variable=sil, width=110).grid(row=0, column=1, padx=4,
                                                                                   pady=(6, 0), sticky="w")
            ctk.CTkButton(row, text="Show", width=60, height=26, fg_color=QUIET, hover_color=QUIET_H,
                          text_color=TEXT, command=lambda i=i: self.select_part(i)).grid(row=0, column=2, padx=4,
                                                                                         pady=(6, 0))
            ctk.CTkButton(row, text="x", width=28, height=26, fg_color=DANGER, hover_color=DANGER_H,
                          text_color=TEXT, command=lambda i=i: self.remove_part(i)).grid(row=0, column=3, padx=(0, 6),
                                                                                         pady=(6, 0))
            ctk.CTkLabel(row, text=f"{tstr(p['start'])}  to  {tstr(p['end'])}   ({p['end'] - p['start']:.1f}s)",
                         text_color=GREY).grid(row=1, column=0, columnspan=4, sticky="w", padx=6, pady=(0, 6))
        n_on = sum(1 for p in self.parts if p["on"])
        self.parts_sum.configure(text=f"{n_on} of {len(self.parts)} parts will be exported" if self.parts
                                 else "No parts yet. Make parts above.")
        self.update_sil_summary()

    def _set_flag(self, p, key, var):
        try:
            p[key] = bool(var.get())
        except Exception:
            return
        self.refresh_parts_summary_only()

    def refresh_parts_summary_only(self):
        n_on = sum(1 for p in self.parts if p["on"])
        self.parts_sum.configure(text=f"{n_on} of {len(self.parts)} parts will be exported" if self.parts
                                 else "No parts yet. Make parts above.")
        self.update_sil_summary()

    def remove_part(self, i):
        del self.parts[i]
        self.part_idx = min(self.part_idx, max(0, len(self.parts) - 1))
        self.refresh_parts()
        self.select_part(self.part_idx)

    def current_part(self):
        if self.parts:
            return self.parts[min(self.part_idx, len(self.parts) - 1)]
        return {"start": 0.0, "end": self.dur, "on": True, "sil": False, "label": "whole movie"}

    def select_part(self, i):
        self.part_idx = i if self.parts else 0
        self.t_rel = 0.0
        p = self.current_part()
        length = max(0.1, p["end"] - p["start"])
        self.pos_slider.configure(to=length)
        self.pos_slider.set(0)
        self.pos_lbl.configure(text="Position: 00:00.0")
        self.refresh_parts()
        self.schedule_render()

    def on_pos_slider(self, v):
        self.t_rel = float(v)
        self.pos_lbl.configure(text=f"Position: {tstr(self.t_rel)}")
        self.schedule_render()

    # ================================================================ items (overlay / text)
    def part_number(self, index):
        """Sequence number of a part: first number + its position (1, 2, 3, ...)."""
        try:
            first = int(float(self.num_start.get() or 1))
        except ValueError:
            first = 1
        return first + index

    def localized_item(self, it, part, number=1):
        d = dict(it)
        rs = float(it.get("rel_start", 0.0) or 0.0)
        re_ = float(it.get("rel_end", 0.0) or 0.0)
        d["start"] = part["start"] + rs
        d["end"] = part["start"] + re_ if re_ > 0 else part["end"]
        if it.get("kind") == "text":
            d["text"] = str(it.get("text", "")).replace("{n}", str(number))
        return d

    def localized(self, part, number=1):
        ovs, txs = [], []
        for it in self.items:
            d = self.localized_item(it, part, number)
            if d["end"] <= d["start"]:
                continue
            (ovs if it["kind"] == "overlay" else txs).append(d)
        return ovs, txs

    def add_item(self, kind):
        if not self.movie:
            messagebox.showwarning("Add", "Please choose a movie first.")
            return
        if kind == "overlay":
            path = filedialog.askopenfilename(filetypes=IMG_VID)
            if not path:
                return
            it = dict(E.OVERLAY_DEFAULT, kind="overlay", path=path, pos="Top-Right", x=70, y=5, scale=25,
                      opacity=100, chroma=False, loop=True, key_color="#00FF00", key_sim=0.30, key_blend=0.10,
                      key_spill=True, rel_start=0.0, rel_end=0.0)
        elif kind == "number":
            it = dict(E.TEXT_DEFAULT, kind="text", text="{n}", auto_number=True, pos="Top-Center", x=45, y=6,
                      size=9.0, color="#FFFFFF", opacity=100, outline=3, outline_color="#000000",
                      shadow=True, box=False, box_color="#000000", box_opacity=60, font=E.TEXT_DEFAULT["font"],
                      rel_start=0.0, rel_end=0.0)
        else:
            it = dict(E.TEXT_DEFAULT, kind="text", text="Your text", pos="Bottom-Center", x=10, y=80,
                      size=5.0, color="#FFFFFF", opacity=100, outline=2, outline_color="#000000",
                      shadow=True, box=False, box_color="#000000", box_opacity=60, font=E.TEXT_DEFAULT["font"],
                      rel_start=0.0, rel_end=0.0)
        self.items.append(it)
        self.select(len(self.items) - 1)

    def remove_selected(self):
        if self.sel is None:
            return
        del self.items[self.sel]
        self.select(None)

    def select(self, idx):
        self.sel = idx
        self.redraw_items()
        self.refresh_editors()
        self.draw_boxes()

    def refresh_editors(self):
        self.refresh_item_list(self.ov_list, "overlay")
        self.refresh_item_list(self.tx_list, "text")
        self.build_editor(self.ov_editor, "overlay")
        self.build_editor(self.tx_editor, "text")

    def refresh_item_list(self, box, kind):
        for w in box.winfo_children():
            w.destroy()
        n = 0
        for idx, it in enumerate(self.items):
            if it["kind"] != kind:
                continue
            n += 1
            label = (os.path.basename(it["path"]) if kind == "overlay" else str(it["text"]).strip()[:36] or "(empty)")
            ctk.CTkRadioButton(box, text=f"{n}. {label}", value=idx, variable=self._sel_var(kind),
                               command=lambda i=idx: self.select(i)).pack(anchor="w", padx=6, pady=2)
        if n == 0:
            ctk.CTkLabel(box, text="Nothing added yet", text_color=GREY).pack(anchor="w", padx=6)

    def _sel_var(self, kind):
        if kind not in self.sel_vars:
            self.sel_vars[kind] = tk.IntVar(value=-1)
        var = self.sel_vars[kind]
        var.set(self.sel if (self.sel is not None and self.items[self.sel]["kind"] == kind) else -1)
        return var

    def build_editor(self, box, kind):
        for w in box.winfo_children():
            w.destroy()
        if self.sel is None or self.items[self.sel]["kind"] != kind:
            ctk.CTkLabel(box, text=("Select an overlay in the list, or click '+ Add photo / video'."
                                    if kind == "overlay" else
                                    "Select a text in the list, or click '+ Add text'."),
                         text_color=GREY, wraplength=330, justify="left").pack(anchor="w", padx=8, pady=10)
            return
        self.field_refs = {}
        it = self.items[self.sel]
        if kind == "overlay":
            self._build_overlay_editor(box, it)
        else:
            self._build_text_editor(box, it)

    def _changed(self):
        self.schedule_render()
        self.draw_boxes()

    def _build_overlay_editor(self, box, it):
        ctk.CTkLabel(box, text=os.path.basename(it["path"]), text_color=NEON, anchor="w").pack(
            fill="x", padx=8, pady=(6, 2))
        ctk.CTkButton(box, text="Change file", width=120, fg_color=QUIET, hover_color=QUIET_H, text_color=TEXT,
                      command=lambda: self._change_file(it)).pack(anchor="w", padx=8, pady=2)
        ctk.CTkLabel(box, text="POSITION AND SIZE", font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=NEON).pack(anchor="w", padx=8, pady=(8, 2))
        self._preset_row(box, it)
        self._num(box, "Left-right X %", 0, 100, 0.5, it, "x", "{:.1f}", custom=True)
        self._num(box, "Up-down Y %", 0, 100, 0.5, it, "y", "{:.1f}", custom=True)
        self._num(box, "Size (% of width)", 3, 100, 1, it, "scale", "{:.0f}")
        self._num(box, "Opacity %", 5, 100, 1, it, "opacity", "{:.0f}")
        self._timing(box, it)
        var = tk.BooleanVar(value=bool(it["loop"]))
        ctk.CTkCheckBox(box, text="Loop (video / GIF)", variable=var, text_color=TEXT,
                        command=lambda: self._flag(it, "loop", var)).pack(anchor="w", padx=8, pady=3)
        ctk.CTkLabel(box, text="REMOVE BACKGROUND (green / blue screen)", font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=NEON).pack(anchor="w", padx=8, pady=(10, 2))
        var2 = tk.BooleanVar(value=bool(it["chroma"]))
        ctk.CTkCheckBox(box, text="Remove the colour I pick (background becomes transparent)", variable=var2,
                        text_color=TEXT, command=lambda: self._flag(it, "chroma", var2)).pack(
            anchor="w", padx=8, pady=3)
        row = ctk.CTkFrame(box, fg_color="transparent")
        row.pack(fill="x", padx=8, pady=3)
        sw = ctk.CTkButton(row, text=it["key_color"].upper(), width=110, fg_color=it["key_color"],
                           hover_color=it["key_color"], text_color=self._txt_for(it["key_color"]),
                           command=lambda: self._pick_key_colour(it))
        sw.pack(side="left")
        ctk.CTkButton(row, text="Pick from picture", width=150, fg_color=QUIET, hover_color=QUIET_H,
                      text_color=TEXT, command=self.toggle_pick).pack(side="left", padx=6)
        self._num(box, "Colour match (more = more removed)", 0.01, 0.6, 0.01, it, "key_sim", "{:.2f}")
        self._num(box, "Edge softness", 0.0, 0.5, 0.01, it, "key_blend", "{:.2f}")
        var3 = tk.BooleanVar(value=bool(it["key_spill"]))
        ctk.CTkCheckBox(box, text="Remove colour spill on edges", variable=var3, text_color=TEXT,
                        command=lambda: self._flag(it, "key_spill", var3)).pack(anchor="w", padx=8, pady=3)
        ctk.CTkButton(box, text="Delete this overlay", fg_color=DANGER, hover_color=DANGER_H, text_color=TEXT,
                      command=self.remove_selected).pack(anchor="w", padx=8, pady=(10, 6))

    def _build_text_editor(self, box, it):
        ctk.CTkLabel(box, text="TEXT", font=ctk.CTkFont(size=12, weight="bold"), text_color=NEON).pack(
            anchor="w", padx=8, pady=(6, 2))
        tb = ctk.CTkTextbox(box, height=70)
        tb.pack(fill="x", padx=8, pady=2)
        tb.insert("1.0", str(it["text"]))

        def typed(_=None):
            it["text"] = tb.get("1.0", "end").strip("\n")
            self._changed()
            self._refresh_list_labels()
        tb.bind("<KeyRelease>", typed)

        def make_number():
            inner = getattr(tb, "_textbox", tb)
            try:
                rng = inner.tag_ranges("sel")
            except Exception:
                rng = ()
            if rng:
                a, b = str(rng[0]), str(rng[1])
            else:                                    # nothing selected: use the first number in the text
                m = re.search(r"\d+", inner.get("1.0", "end"))
                if not m:
                    messagebox.showinfo("Part number", "First select the number inside the text (for example the 1 "
                                                       "in 'Part 1 ...'), then press this button.")
                    return
                a, b = f"1.0+{m.start()}c", f"1.0+{m.end()}c"
            inner.delete(a, b)
            inner.insert(a, "{n}")
            typed()
        ctk.CTkButton(box, text="Make selected number = part number", command=make_number).pack(
            anchor="w", padx=8, pady=(4, 0))
        ctk.CTkLabel(box, text="Select only the number in your text (the 1 in 'Part 1 finding best movie') and press "
                               "the button. It becomes {n}: 1 in the first part, 2 in the second, 3 ... The rest of "
                               "the text stays the same in every video. You can also type {n} yourself.",
                     text_color=GREY, wraplength=340, justify="left", anchor="w").pack(anchor="w", padx=8, pady=(2, 4))
        ctk.CTkLabel(box, text="Font (Hindi: Nirmala UI, Mangal)", text_color=TEXT, anchor="w").pack(
            fill="x", padx=8, pady=(6, 0))
        fvar = tk.StringVar(value=str(it["font"]))
        fvar.trace_add("write", lambda *a: self._set_key(it, "font", fvar.get()))
        FontPicker(box, fvar).pack(fill="x", padx=8, pady=2)
        self._preset_row(box, it)
        crow = ctk.CTkFrame(box, fg_color="transparent")
        crow.pack(fill="x", padx=8, pady=(2, 0))
        state = ctk.CTkLabel(box, text="", text_color=GREY, anchor="w")

        def show_state():
            h, v = it.get("hcenter"), it.get("vcenter")
            state.configure(text=("Centred: " + ("left-right  " if h else "") + ("up-down" if v else ""))
                            if (h or v) else "Free position (drag it with the mouse or use the sliders)")

        def center(h=None, v=None):
            if h is not None:
                it["hcenter"] = h
            if v is not None:
                it["vcenter"] = v
            show_state()
            self._changed()
        self._center_state = show_state
        for i, (label, args) in enumerate((("Center left-right", dict(h=True)), ("Center up-down", dict(v=True)),
                                           ("Center on screen", dict(h=True, v=True)),
                                           ("Unlock (move freely)", dict(h=False, v=False)))):
            ctk.CTkButton(crow, text=label, width=150, fg_color=(NEON_D if i == 2 else QUIET),
                          hover_color=QUIET_H, text_color=TEXT,
                          command=lambda a=args: center(**a)).grid(row=i // 2, column=i % 2, padx=2, pady=2)
        state.pack(anchor="w", padx=10, pady=(0, 2))
        show_state()
        self._num(box, "Left-right X %", 0, 100, 0.5, it, "x", "{:.1f}", custom=True)
        self._num(box, "Up-down Y %", 0, 100, 0.5, it, "y", "{:.1f}", custom=True)
        self._num(box, "Size (% of height)", 1, 20, 0.5, it, "size", "{:.1f}")
        self._num(box, "Opacity %", 5, 100, 1, it, "opacity", "{:.0f}")
        self._num(box, "Outline thickness", 0, 10, 1, it, "outline", "{:.0f}")
        self._timing(box, it)
        row = ctk.CTkFrame(box, fg_color="transparent")
        row.pack(fill="x", padx=8, pady=3)
        self._colour_btn(row, "Text colour", it, "color")
        self._colour_btn(row, "Outline colour", it, "outline_color")
        var = tk.BooleanVar(value=bool(it["shadow"]))
        ctk.CTkCheckBox(box, text="Shadow", variable=var, text_color=TEXT,
                        command=lambda: self._flag(it, "shadow", var)).pack(anchor="w", padx=8, pady=3)
        var2 = tk.BooleanVar(value=bool(it["box"]))
        ctk.CTkCheckBox(box, text="Background box behind text", variable=var2, text_color=TEXT,
                        command=lambda: self._flag(it, "box", var2)).pack(anchor="w", padx=8, pady=3)
        self._colour_btn(box, "Box colour", it, "box_color")
        self._num(box, "Box opacity %", 0, 100, 1, it, "box_opacity", "{:.0f}")
        ctk.CTkButton(box, text="Delete this text", fg_color=DANGER, hover_color=DANGER_H, text_color=TEXT,
                      command=self.remove_selected).pack(anchor="w", padx=8, pady=(10, 6))

    def _preset_row(self, box, it):
        row = ctk.CTkFrame(box, fg_color="transparent")
        row.pack(fill="x", padx=8, pady=3)
        ctk.CTkLabel(row, text="Position", text_color=TEXT, width=118, anchor="w").pack(side="left")
        var = tk.StringVar(value=str(it["pos"]))

        def chosen(v):
            it["pos"] = v
            it["hcenter"] = it["vcenter"] = False
            try:
                self._center_state()
            except Exception:
                pass
            self._changed()
        ctk.CTkOptionMenu(row, values=E.POSITIONS, variable=var, command=chosen, width=170).pack(side="left")

    def _timing(self, box, it):
        ctk.CTkLabel(box, text="WHEN IT APPEARS (seconds from the start of this part)", text_color=GREY,
                     anchor="w", wraplength=330, justify="left").pack(anchor="w", padx=8, pady=(8, 0))
        self._num(box, "Appears at (s)", 0, 3600, 0.5, it, "rel_start", "{:.1f}")
        self._num(box, "Until (s, 0 = part end)", 0, 3600, 0.5, it, "rel_end", "{:.1f}")

    def _num(self, box, label, lo, hi, step, it, key, fmt, custom=False):
        def changed(v, it=it, key=key, custom=custom):
            it[key] = round(float(v), 3)
            if custom:
                it["pos"] = "Custom"
                if key == "x":
                    it["hcenter"] = False
                if key == "y":
                    it["vcenter"] = False
                try:
                    self._center_state()
                except Exception:
                    pass
            self._changed()
        nf = NumField(box, label, lo, hi, step, it[key], fmt, changed, label_width=150)
        nf.pack(fill="x", padx=6, pady=2)
        self.field_refs[key] = nf
        return nf

    def _flag(self, it, key, var):
        it[key] = bool(var.get())
        self._changed()

    def _set_key(self, it, key, value):
        it[key] = value
        self._changed()

    def _txt_for(self, colour):
        r, g, b = hex_to_rgb(colour)
        return BLACK if (r * 0.3 + g * 0.59 + b * 0.11) > 140 else "#FFFFFF"

    def _colour_btn(self, parent, label, it, key):
        from tkinter import colorchooser
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=2)
        ctk.CTkLabel(row, text=label, text_color=TEXT, width=118, anchor="w").pack(side="left")
        btn = ctk.CTkButton(row, text=str(it[key]).upper(), width=110, fg_color=it[key], hover_color=it[key],
                            text_color=self._txt_for(it[key]))

        def pick():
            res = colorchooser.askcolor(color=it[key], title=label)
            if res and res[1]:
                it[key] = res[1]
                btn.configure(text=res[1].upper(), fg_color=res[1], hover_color=res[1],
                              text_color=self._txt_for(res[1]))
                self._changed()
        btn.configure(command=pick)
        btn.pack(side="left")

    def _pick_key_colour(self, it):
        from tkinter import colorchooser
        res = colorchooser.askcolor(color=it["key_color"], title="Background colour to remove")
        if res and res[1]:
            it["key_color"] = res[1]
            self._changed()
            self.build_editor(self.ov_editor, "overlay")

    def _change_file(self, it):
        p = filedialog.askopenfilename(filetypes=IMG_VID)
        if p:
            it["path"] = p
            self._changed()
            self.refresh_editors()

    def _refresh_list_labels(self):
        self.refresh_item_list(self.tx_list, "text")

    # ---------------- drawing on the preview
    def redraw_items(self):
        if hasattr(self, "ov_list"):
            self.refresh_item_list(self.ov_list, "overlay")
            self.refresh_item_list(self.tx_list, "text")

    def refresh_view(self):
        if self.last_img is not None:
            self.draw_image(self.last_img)
        else:
            self.draw_placeholder()

    def draw_placeholder(self, msg="Choose a movie above to start"):
        self.cv.delete("all")
        w, h = max(100, self.cv.winfo_width()), max(100, self.cv.winfo_height())
        self.cv.create_text(w // 2, h // 2, text=msg, fill=GREY, font=("Segoe UI", 12))
        self.view = None

    def draw_image(self, img):
        cw, ch = max(200, self.cv.winfo_width()), max(150, self.cv.winfo_height())
        W, H = img.size
        k = min(cw / W, ch / H)
        dw, dh = max(1, int(W * k)), max(1, int(H * k))
        ox, oy = (cw - dw) // 2, (ch - dh) // 2
        self.view = (ox, oy, dw, dh, W, H)
        self._photo = ImageTk.PhotoImage(img.resize((dw, dh), Image.BILINEAR))
        self.cv.delete("all")
        self.cv.create_image(ox, oy, anchor="nw", image=self._photo, tags=("frame",))
        self.draw_boxes()

    def item_visible(self, d, t):
        return d["start"] <= t < d["end"]

    def draw_boxes(self):
        self.cv.delete("box")
        self.boxes = []
        if not self.view or self.last_img is None:
            return
        ox, oy, dw, dh, W, H = self.view
        part = self.current_part()
        t_abs = part["start"] + self.t_rel
        for idx, it in enumerate(self.items):
            d = self.localized_item(it, part, self.part_number(self.part_idx))
            if not self.item_visible(d, t_abs):
                continue
            if it["kind"] == "overlay":
                x, y, w, h = P.overlay_box(d, W, H)
            else:
                x, y, w, h = P.text_box(d, W, H)
            x0, y0 = ox + x * dw / W, oy + y * dh / H
            x1, y1 = ox + (x + w) * dw / W, oy + (y + h) * dh / H
            selected = idx == self.sel
            self.cv.create_rectangle(x0, y0, x1, y1, outline=("#FFFFFF" if selected else NEON),
                                     width=2 if selected else 1, tags=("box",))
            self.cv.create_text(x0 + 3, y0 - 9, text=("Overlay" if it["kind"] == "overlay" else "Text"),
                                anchor="sw", fill=NEON, font=("Segoe UI", 8), tags=("box",))
            self.boxes.append((idx, x0, y0, x1, y1))

    def hit(self, x, y):
        for idx, x0, y0, x1, y1 in reversed(getattr(self, "boxes", [])):
            if x0 <= x <= x1 and y0 <= y <= y1:
                return idx, x0, y0
        return None

    def on_press(self, e):
        if self.pick_mode:
            self.pick_colour(e.x, e.y)
            return
        if not self.view:
            return
        h = self.hit(e.x, e.y)
        if h is None:
            self.select(None)
            return
        idx, x0, y0 = h
        if idx != self.sel:
            self.select(idx)
        self.drag = {"idx": idx, "gx": e.x - x0, "gy": e.y - y0}

    def on_drag(self, e):
        if not self.drag or not self.view:
            return
        ox, oy, dw, dh, W, H = self.view
        it = self.items[self.drag["idx"]]
        left = e.x - self.drag["gx"]
        top = e.y - self.drag["gy"]
        if not it.get("hcenter"):                       # a centred axis stays centred while dragging
            it["x"] = round(min(100.0, max(0.0, (left - ox) / dw * 100)), 2)
        if not it.get("vcenter"):
            it["y"] = round(min(100.0, max(0.0, (top - oy) / dh * 100)), 2)
        it["pos"] = "Custom"
        fx, fy = self.field_refs.get("x"), self.field_refs.get("y")
        if fx:
            fx.set(it["x"])
        if fy:
            fy.set(it["y"])
        self.draw_boxes()
        self.schedule_render()

    def on_release(self, e):
        if self.drag:
            self.drag = None
            self.refresh_editors()
            self.schedule_render()

    def toggle_pick(self):
        self.pick_mode = not self.pick_mode
        self.pick_btn.configure(text=("Click on the picture..." if self.pick_mode else "Pick colour from picture"),
                                fg_color=(NEON_D if self.pick_mode else QUIET))
        self.cv.configure(cursor="crosshair" if self.pick_mode else "")
        if self.pick_mode and (self.sel is None or self.items[self.sel]["kind"] != "overlay"):
            self.hint.configure(text="Select an overlay first, then click the colour to remove on the picture.")

    def pick_colour(self, x, y):
        self.pick_mode = False
        self.pick_btn.configure(text="Pick colour from picture", fg_color=QUIET)
        self.cv.configure(cursor="")
        if not self.view or self.last_img is None:
            return
        if self.sel is None or self.items[self.sel]["kind"] != "overlay":
            self.hint.configure(text="Select an overlay in the Overlay tab first, then pick again.")
            return
        ox, oy, dw, dh, W, H = self.view
        ix = min(W - 1, max(0, int((x - ox) / dw * W)))
        iy = min(H - 1, max(0, int((y - oy) / dh * H)))
        r, g, b = self.last_img.getpixel((ix, iy))[:3]
        it = self.items[self.sel]
        it["key_color"] = "#%02X%02X%02X" % (r, g, b)
        it["chroma"] = True
        self.hint.configure(text=f"Colour picked: {it['key_color']}. Background of this overlay is now removed.")
        self.refresh_editors()
        self.schedule_render()

    # ================================================================ live preview
    def schedule_render(self):
        if self.render_after:
            self.after_cancel(self.render_after)
        self.render_after = self.after(70, self.render_now)

    def preview_settings(self, part, number=1):
        s = dict(self.cfg)
        ovs, txs = self.localized(part, number)
        s["overlays"], s["texts"] = ovs, txs
        return E.sanitize(s)

    def render_now(self):
        self.render_after = None
        if not self.movie:
            return
        part = self.current_part()
        t_abs = min(max(0.0, part["start"] + self.t_rel), max(0.0, self.dur - 0.05))
        self.pos_lbl.configure(text=f"Position: {tstr(self.t_rel)}")
        self.token += 1
        self.renderer.submit(self.movie, t_abs, self.preview_settings(part, self.part_number(self.part_idx)),
                             self.token)

    def show_frame(self, img, tok, err):
        if tok < self.shown:
            return
        self.shown = tok
        if err:
            self.draw_placeholder("Preview error:\n" + err[-160:])
            return
        self.last_img = img
        self.draw_image(img)

    # ================================================================ silence
    def scan_key(self):
        return (self.movie, round(float(self.sil_db.get()), 1), round(float(self.sil_min.get()), 2))

    def sil_changed(self, _=None):
        self.sil_key = None
        self.sil_summary.configure(text="Settings changed. Scan again to update.")
        self.update_sil_summary()

    def scan_silence(self, then=None):
        if not self.movie:
            messagebox.showwarning("Silence", "Please choose a movie first.")
            return
        if self.info and not self.info.get("has_audio"):
            messagebox.showerror("Silence", "This movie has no audio track.")
            return
        key = self.scan_key()
        self.sil_then = then
        self.sil_summary.configure(text="Scanning audio (fast mode)...")
        movie, dur = self.movie, self.dur
        noise, mn = float(self.sil_db.get()), float(self.sil_min.get())

        def work():
            try:
                self.q.put(("scan", (key, E.detect_silence(movie, noise, mn, dur), None)))
            except Exception as e:
                self.q.put(("scan", (key, None, str(e))))
        threading.Thread(target=work, daemon=True).start()

    def update_sil_summary(self):
        if not self.movie:
            return
        if self.sil_key is None:
            if not self.sil_list:
                self.sil_summary.configure(text="Not scanned yet")
            else:
                self.sil_summary.configure(text="Settings changed. Scan again to update.")
            return
        removed = self.removed_seconds()
        n = len(self.sil_list)
        scope = f" (only the first {self.head_seconds():g} s of every part)" if self.head_on.get() else ""
        self.sil_summary.configure(text=f"Found {n} silent pauses in the movie. Selected parts will lose about "
                                        f"{removed:.1f} s of silence{scope}.")
        self.sil_text.delete("1.0", "end")
        for a, b in self.sil_list[:400]:
            self.sil_text.insert("end", f"{tstr(a)}  to  {tstr(b)}   ({b - a:.1f}s)\n")

    def removed_seconds(self):
        if not self.sil_on.get() or not self.sil_list:
            return 0.0
        total = 0.0
        for p in self.parts:
            if not (p["on"] and p["sil"]):
                continue
            he = self.head_end(p["start"], p["end"])
            keep = self.with_tail(E.silence_keep_ranges(self.sil_list, p["start"], he or p["end"], float(self.sil_pad.get()), 0.3), p["start"], p["end"])
            total += (p["end"] - p["start"]) - sum(d for _, d in keep)
        return total

    # ================================================================ export
    def export(self, with_dialogue=None):
        if with_dialogue is None:
            with_dialogue = bool(self.dl_on.get())
        if not self.movie:
            messagebox.showwarning("Export", "Please choose a movie first.")
            return
        if self.eng:
            return
        chosen = [p for p in self.parts if p["on"]]
        if not chosen:
            messagebox.showwarning("Export", "No part is selected. Tick at least one part.")
            return
        for i, p in enumerate(self.parts, 1):
            if p["on"] and (p["end"] <= p["start"] + 0.5 or p["start"] < 0 or p["end"] > self.dur + 0.05):
                messagebox.showerror("Export", f"Part {i} has invalid times. Check its Start and End.")
                return
        try:
            dl_opts = self.dialogue_opts() if with_dialogue else None
        except ValueError as e:
            messagebox.showerror("Dialogue", str(e))
            return
        needs_silence = (not with_dialogue) and self.sil_on.get() and any(p["sil"] for p in chosen)
        if needs_silence and self.sil_key != self.scan_key():
            self.exp_status_set("Scanning silence first, then exporting...")
            self.scan_silence(then=lambda: self.export(with_dialogue))
            return
        try:
            self.sync_export()
            s = E.sanitize(dict(self.cfg))
        except ValueError as e:
            messagebox.showerror("Export", str(e))
            return
        errs = E.validate(s, "simple")
        if errs:
            messagebox.showerror("Export", "\n".join(errs))
            return
        if with_dialogue:
            s["fade_sec"] = dialogue.FADE          # 20 ms fades at every cut
            s["_joint_fade"] = dialogue.FADE
            s["_denoise"] = bool(dl_opts["denoise"])
        items_snapshot = copy.deepcopy(self.items)
        for k in ENCODE_KEYS:
            self.app.s[k] = s[k]
        E.save_settings(self.app.sync_vars())
        plans = self.build_plans([(i, p) for i, p in enumerate(self.parts) if p["on"]])
        out_dir = os.path.join(E.OUTPUT_DIR, f"{self.file_base()}_{'simple' if self.mode == 'simple' else 'ai'}"
                                             + ("_dialogue" if with_dialogue else ""))
        self.exp_log.delete("1.0", "end")
        self.exp_go.configure(state="disabled")
        self.exp_stop.configure(state="normal")
        self.eng = E.StudioEngine(s, lambda m: self.q.put(("elog", m)),
                                  lambda fr, t: self.q.put(("eprog", (fr, t))),
                                  lambda c: self.q.put(("eclip", c)))
        movie, eng = self.movie, self.eng

        def log(m):
            self.q.put(("elog", m))

        def work():
            work_dir = os.path.join(out_dir, "_dialogue_work")
            try:
                prepare = None
                if dl_opts:
                    def prepare(plan):
                        log(f"Dialogue: finding the talking in {plan['file']} "
                            f"({plan['start']:.1f}s - {plan['end']:.1f}s)")
                        he = self.head_end(plan["start"], plan["end"])
                        pieces, _ = dialogue.analyze(movie, plan["start"], he or plan["end"], dl_opts, work_dir, log)
                        if he is not None:
                            if not pieces:      # nothing to keep in the first seconds: leave the part as it is
                                pieces = [(plan["start"], he - plan["start"])]
                            pieces = self.with_tail(pieces, plan["start"], plan["end"])
                        if not pieces:
                            return None
                        total = sum(d for _, d in pieces)
                        ovs, txs = auto_short.relative_items(items_snapshot, total, plan["number"])
                        log(f"  {len(pieces)} dialogue pieces, {total:.1f}s of talking "
                            f"(from {plan['end'] - plan['start']:.1f}s) - shortest piece "
                            f"{min(d for _, d in pieces):.1f}s, average {total / len(pieces):.1f}s")
                        return dict(plan, pieces=pieces, single_pass=True, overlays=ovs, texts=txs)
                eng.process(movie, plans, out_dir, prepare=prepare)
                shutil.rmtree(work_dir, ignore_errors=True)
            except Exception:
                log("ERROR:\n" + traceback.format_exc())
            self.q.put(("edone", out_dir))
        threading.Thread(target=work, daemon=True).start()

    def file_base(self):
        base = os.path.splitext(os.path.basename(self.movie))[0]
        return "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in base)[:40]

    def build_plans(self, chosen):
        """chosen: [(index, part)]. Returns one output plan per part (silence cut and numbering applied)."""
        base = self.file_base()
        pad = float(self.sil_pad.get())
        plans = []
        for idx, p in chosen:
            number = self.part_number(idx)
            ovs, txs = self.localized(p, number)
            if self.sil_on.get() and p["sil"]:
                he = self.head_end(p["start"], p["end"])
                pieces = self.with_tail(E.silence_keep_ranges(self.sil_list, p["start"], he or p["end"], pad, 0.3), p["start"], p["end"])
            else:
                pieces = [(p["start"], p["end"] - p["start"])]
            mm, ss = divmod(int(p["start"]), 60)
            plans.append(dict(file=f"{base}_part{number:02d}_{mm:02d}m{ss:02d}s.mp4", start=p["start"],
                              end=p["end"], label=p.get("label", ""), pieces=pieces, overlays=ovs, texts=txs,
                              number=number))
        return plans

    def exp_status_set(self, text):
        self.exp_status.configure(text=text)

    def play_preview(self, whole):
        """Renders a fast, low-quality preview with the same edits, then plays it with audio."""
        if not self.movie:
            messagebox.showwarning("Preview", "Please choose a movie first.")
            return
        if self.eng:
            messagebox.showinfo("Preview", "Wait until the current export or preview has finished.")
            return
        chosen = ([(i, p) for i, p in enumerate(self.parts) if p["on"]] if whole
                  else [(self.part_idx, self.current_part())])
        if not chosen:
            messagebox.showwarning("Preview", "No part is selected.")
            return
        if self.sil_on.get() and any(p["sil"] for _, p in chosen) and self.sil_key != self.scan_key():
            messagebox.showinfo("Preview", "Scan the silence first (Silence tab), then preview again.")
            return
        s = E.sanitize(dict(self.cfg))
        s["_fast"] = True
        plans = self.build_plans(chosen)
        out_dir = os.path.join(E.OUTPUT_DIR, "_preview")
        shutil.rmtree(out_dir, ignore_errors=True)
        self.exp_log.delete("1.0", "end")
        self.exp_go.configure(state="disabled")
        self.exp_stop.configure(state="normal")
        self.eng = E.StudioEngine(s, lambda m: self.q.put(("elog", m)),
                                  lambda fr, t: self.q.put(("eprog", (fr, t))), lambda c: None)
        movie, eng = self.movie, self.eng

        def work():
            try:
                eng.process(movie, plans, out_dir)
                files = [os.path.join(out_dir, p["file"]) for p in plans]
                files = [f for f in files if os.path.isfile(f)]
                if not files:
                    raise RuntimeError("No preview could be rendered (see the log).")
                if len(files) == 1:
                    target = files[0]
                else:
                    target = os.path.join(out_dir, "preview_full.mp4")
                    ok, err = E.concat_files(files, target)
                    if not ok:
                        raise RuntimeError("Joining the preview failed: " + err)
                self.q.put(("pdone", target))
            except Exception:
                self.q.put(("elog", "ERROR:\n" + traceback.format_exc()))
                self.q.put(("pdone", None))
        threading.Thread(target=work, daemon=True).start()

    def stop_export(self):
        if self.eng:
            self.eng.stop()
            self.exp_status.configure(text="Stopping...")

    # ================================================================ AI
    def find_clips_ai(self):
        if not self.movie:
            messagebox.showwarning("AI", "Please choose a movie first.")
            return
        if self.ai_eng:
            return
        try:
            s = E.sanitize(dict(self.cfg))
            for k, var in self.ai_v.items():
                s[k] = conv(E.DEFAULTS[k], var.get())
            s = E.sanitize(s)
        except ValueError as e:
            messagebox.showerror("AI", str(e))
            return
        errs = E.validate(s, "ai")
        if errs:
            messagebox.showerror("AI", "\n".join(errs))
            return
        self.ai_go.configure(state="disabled")
        self.ai_stop_btn.configure(state="normal")
        self.ai_status.configure(text="Starting AI...")
        self.ai_found = []
        self.ai_eng = E.AIEngine(s, lambda m: self.q.put(("alog", m)),
                                 lambda fr, t: self.q.put(("aprog", (fr, t))),
                                 lambda c: self.q.put(("aclip", c)))
        self.ai_eng.detect_only = True
        movie, eng = self.movie, self.ai_eng

        def work():
            try:
                eng.process(movie)
            except Exception:
                self.q.put(("alog", "ERROR:\n" + traceback.format_exc()))
            self.q.put(("adone", None))
        threading.Thread(target=work, daemon=True).start()

    def stop_ai(self):
        if self.ai_eng:
            self.ai_eng.stop()
            self.ai_status.configure(text="Stopping...")

    # ================================================================ message loop
    def poll(self):
        frame = None
        try:
            while True:
                try:
                    kind, v = self.q.get_nowait()
                except queue.Empty:
                    break
                if kind == "frame":
                    frame = v
                elif kind == "scan":
                    self.on_scan(*v)
                elif kind in ("elog", "eprog", "eclip", "edone", "pdone"):
                    self.on_export_msg(kind, v)
                elif kind in ("alog", "aprog", "aclip", "adone"):
                    self.on_ai_msg(kind, v)
            if frame:
                self.show_frame(*frame)
        except Exception as e:
            self.exp_status.configure(text=f"UI error: {e}")
        self.after(60, self.poll)

    def on_scan(self, key, segs, err):
        if err or segs is None:
            self.sil_summary.configure(text=f"Scan failed: {err}")
            self.sil_then = None
            return
        self.sil_list, self.sil_key = segs, key
        self.update_sil_summary()
        then, self.sil_then = self.sil_then, None
        if then:
            then()

    def on_export_msg(self, kind, v):
        if kind == "elog":
            self.exp_log.insert("end", v + "\n")
            self.exp_log.see("end")
        elif kind == "eprog":
            self.exp_bar.set(v[0])
            self.exp_status.configure(text=v[1])
        elif kind == "eclip":
            self.exp_log.insert("end", f"Saved: {v['path']}\n")
            self.exp_log.see("end")
        elif kind == "pdone":
            self.eng = None
            self.exp_go.configure(state="normal")
            self.exp_stop.configure(state="disabled")
            if v:
                self.exp_status.configure(text="Playing preview...")
                play_file(v)
            else:
                self.exp_status.configure(text="Preview failed - see the log.")
        elif kind == "edone":
            self.eng = None
            self.exp_go.configure(state="normal")
            self.exp_stop.configure(state="disabled")
            self.exp_status.configure(text="Finished. Output folder opened.")
            try:
                open_path(v)
            except Exception:
                pass

    def on_ai_msg(self, kind, v):
        if kind == "alog":
            self.ai_status.configure(text=str(v)[:90])
        elif kind == "aprog":
            self.ai_bar.set(v[0])
            self.ai_status.configure(text=v[1])
        elif kind == "aclip":
            self.ai_found.append({"on": True, "sil": True, "start": round(float(v["start"]), 3),
                                  "end": round(float(v["end"]), 3),
                                  "label": f"{v.get('category', '')} (score {int(v.get('score') or 0)})"})
        elif kind == "adone":
            self.ai_eng = None
            self.ai_go.configure(state="normal")
            self.ai_stop_btn.configure(state="disabled")
            found = sorted(self.ai_found, key=lambda p: p["start"])
            self.parts = found
            self.part_idx = 0
            self.refresh_parts()
            self.select_part(0)
            self.ai_status.configure(text=f"Found {len(found)} clips. Untick any you don't want, then export.")

    # ================================================================ project (save / open)
    def _var_groups(self):
        return [self.cfg_v, self.exp_v] + ([self.ai_v] if self.mode == "ai" else [])

    def get_state(self):
        """Everything of this tab that a project file must remember. Read-only: it does not touch the preview."""
        cfg = dict(self.cfg)
        for group in self._var_groups():
            for k, var in group.items():
                try:
                    cfg[k] = conv(E.DEFAULTS[k], var.get())
                except Exception:
                    pass
        st = dict(
            movie=self.movie, cfg=cfg, items=copy.deepcopy(self.items), parts=copy.deepcopy(self.parts),
            part_idx=self.part_idx, t_rel=round(float(self.t_rel), 3), sel=self.sel,
            num_start=self.num_start.get(),
            silence=dict(on=bool(self.sil_on.get()), db=float(self.sil_db.get()), min=float(self.sil_min.get()),
                         pad=float(self.sil_pad.get()), key=list(self.sil_key) if self.sil_key else None,
                         list=[list(x) for x in self.sil_list]),
            dialogue=dict(head_on=bool(self.head_on.get()), head_sec=self.head_seconds(), on=bool(self.dl_on.get()), denoise=bool(self.dl_denoise.get()), vad=bool(self.dl_vad.get()),
                          whisper=bool(self.dl_whisper.get()), pad=float(self.dl_pad.get()),
                          minsil=float(self.dl_minsil.get()), remove=self.dl_remove.get(), lang=self.dl_lang.get(),
                          minpiece=float(self.dl_minpiece.get()), scan=bool(self.dl_scan.get())),
            right_tab=self.right.get())
        if self.mode == "simple":
            st["range"] = dict(start=self.p_start.get(), end=self.p_end.get(), count=self.p_count.get(),
                               length=self.p_len.get())
        return st

    def clear_movie(self):
        """Back to 'no movie loaded' (used by New project)."""
        self.movie, self.info, self.dur = "", None, 0.0
        self.movie_menu.set("(no movie - put files in input_movies)")
        self.info_lbl.configure(text="No movie loaded")
        self.items, self.sel = [], None
        self.parts, self.part_idx, self.t_rel = [], 0, 0.0
        self.sil_list, self.sil_key = [], None
        self.last_img = None
        self.sil_summary.configure(text="Not scanned yet")
        self.sil_text.delete("1.0", "end")
        self.pos_slider.configure(to=1)
        self.pos_slider.set(0)
        self.pos_lbl.configure(text="Position: 00:00.0")
        self.refresh_parts()
        self.redraw_items()
        self.refresh_editors()
        self.draw_placeholder()

    def _try(self, label, fn, *a, **k):
        """Runs one restore step; if it fails the other steps still run and the problem is reported."""
        try:
            return fn(*a, **k)
        except Exception as e:
            self.restore_errors.append(f"{self.mode} tab, {label}: {e}")
            return None

    def set_state(self, st, movie_path=""):
        """Puts a saved state back: movie, settings, texts, parts and the exact place where the work stopped.
        movie_path "" = no movie (the settings, texts and parts are still restored).
        Returns a list of problems (empty = everything was restored)."""
        st = st or {}
        self.restore_errors = []
        self._try("movie", self.load_movie, movie_path) if movie_path else self._try("clear", self.clear_movie)
        self._try("colour and settings", self._restore_settings, st)
        self._try("texts and parts", self._restore_items, st)
        self._try("silence", self._restore_silence, st)
        self._try("dialogue", self._restore_dialogue, st)
        self._try("position", self._restore_view, st)
        return self.restore_errors

    def _restore_settings(self, st):
        def put(var, value):
            try:
                var.set(value)
            except Exception:
                pass
        cfg = E.sanitize(dict(st.get("cfg") or {}))
        for group in self._var_groups():
            for k, var in group.items():
                if k in cfg:
                    put(var, cfg[k])
        for key, nf in (("zoom", self.f_zoom), ("crop_x", self.f_cx), ("crop_y", self.f_cy),
                        ("blur_amount", self.f_blur), ("fit_scale", self.f_fscale), ("fit_y", self.f_fy)):
            nf.set(cfg[key])
        for key, nf in self.colour_fields.items():
            nf.set(CL.to_ui(key, cfg[key]))
        self.cfg.clear()                       # after the variables: their callbacks also write into self.cfg
        self.cfg.update(cfg)

    def _restore_items(self, st):
        self.items = copy.deepcopy(st.get("items") or [])
        base = {"on": True, "sil": True, "start": 0.0, "end": 0.0, "label": ""}
        self.parts = []
        for p in (st.get("parts") or []):
            q = dict(base, **p)
            if self.dur > 0:
                q["start"] = min(float(q["start"]), self.dur)
                q["end"] = min(float(q["end"]), self.dur)
            self.parts.append(q)
        self.num_start.set(str(st.get("num_start", "1")))
        if self.mode == "simple":
            r = st.get("range") or {}
            self.p_start.set(str(r.get("start", "0")))
            self.p_end.set(str(r.get("end", "")))
            self.p_count.set(str(r.get("count", "3")))
            self.p_len.set(str(r.get("length", "0")))

    def _restore_silence(self, st):
        sl = st.get("silence") or {}
        self.sil_on.set(bool(sl.get("on", True)))
        self.sil_db.set(float(sl.get("db", -35)))
        self.sil_min.set(float(sl.get("min", 2.0)))
        self.sil_pad.set(float(sl.get("pad", 0.25)))
        self.sil_list, self.sil_key = [], None
        if self.movie and sl.get("key") and sl.get("list") is not None:
            key = tuple(sl["key"])
            if len(key) == 3 and key == self.scan_key():          # the scan still matches this movie and settings
                self.sil_list, self.sil_key = [tuple(x) for x in sl["list"]], key
        self.update_sil_summary()

    def _restore_dialogue(self, st):
        dl = st.get("dialogue") or {}
        self.dl_on.set(bool(dl.get("on", False)))
        self.head_on.set(bool(dl.get("head_on", False)))
        self.head_sec.set(f"{float(dl.get('head_sec', 3)):g}")
        self.dl_denoise.set(bool(dl.get("denoise", True)))
        self.dl_vad.set(bool(dl.get("vad", True)))
        self.dl_whisper.set(bool(dl.get("whisper", False)))
        self.dl_pad.set(float(dl.get("pad", 150)))
        self.dl_minsil.set(float(dl.get("minsil", 300)))
        self.dl_minpiece.set(float(dl.get("minpiece", dialogue.MIN_PIECE)))
        self.dl_scan.set(bool(dl.get("scan", False)))
        self.dl_remove.set(str(dl.get("remove", "um, uh")))
        self.dl_lang.set(str(dl.get("lang", "")))
        self.update_cut_info()

    def _restore_view(self, st):
        self.sel = None
        self.refresh_parts()
        self.redraw_items()
        self.refresh_editors()
        idx = int(st.get("part_idx", 0) or 0)
        self.select_part(min(max(0, idx), max(0, len(self.parts) - 1)))
        length = max(0.1, self.current_part()["end"] - self.current_part()["start"])
        t = min(max(0.0, float(st.get("t_rel", 0.0) or 0.0)), length)
        self.pos_slider.set(t)                 # exactly where the work stopped
        self.on_pos_slider(t)
        sel = st.get("sel")
        if isinstance(sel, int) and 0 <= sel < len(self.items):
            self.select(sel)
        try:
            if st.get("right_tab"):
                self.right.set(st["right_tab"])
        except Exception:
            pass

    def on_close_cleanup(self):
        for eng in (self.eng, self.ai_eng):
            if eng:
                eng.stop()
