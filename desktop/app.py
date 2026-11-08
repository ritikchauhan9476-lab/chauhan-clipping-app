"""Chauhan Clipping - CapCut-style editor: live preview, layered timeline (text / overlay / audio),
colour + crop + chroma with instant preview, export, and the AI viral clipper."""
import os, sys, json, math, copy, time, queue, shutil, subprocess, tempfile, threading, traceback, importlib.util


def _ensure_packages():
    """If the GUI packages are missing (e.g. app.py was started with the wrong Python), install them once."""
    if importlib.util.find_spec("customtkinter") is None or importlib.util.find_spec("PIL") is None:
        req = os.path.join(os.path.dirname(os.path.abspath(__file__)), "requirements.txt")
        print("Installing required packages (first run)...")
        subprocess.call([sys.executable, "-m", "pip", "install", "-r", req])


_ensure_packages()
try:
    import tkinter as tk
    import customtkinter as ctk
except ImportError as e:
    print(f"GUI packages are missing ({e}). Run run.bat or setup.bat once.")
    input("Press Enter to close...")
    sys.exit(1)
from tkinter import filedialog, messagebox, colorchooser
from PIL import Image
import engine as E
import preview as P
import model as M
import project as PRJ
import colour as CL
from widgets import *
from auto_short_ui import AutoShortFrame
from studio import Studio

TRACK_BG = ("#0B0B0B", "#121212")
ITEM_FILL = {"text": "#1B4D12", "overlay": "#0F3B1C", "audio": "#0E2F38"}
ITEM_LINE = {"text": "#C6FF9A", "overlay": NEON, "audio": "#4FE3FF"}

APP_NAME = "Chauhan Clipping"


def apply_theme():
    """Neon green + black: starts from CustomTkinter's own blue theme and recolours it."""
    ctk.set_appearance_mode("dark")
    base = os.path.join(os.path.dirname(ctk.__file__), "assets", "themes", "blue.json")
    try:
        with open(base, encoding="utf-8") as f:
            t = json.load(f)
    except Exception:
        ctk.set_default_color_theme("blue")
        return
    N = [NEON, NEON]; NH = [NEON_H, NEON_H]; ND = [NEON_D, NEON_D]; BK = [BLACK, BLACK]
    PN = [PANEL, PANEL]; FD = [FIELD, FIELD]; TX = [TEXT, TEXT]; EG = [EDGE, EDGE]; GR = [GREY, GREY]
    rules = {
        "CTkFrame": dict(fg_color=PN, top_fg_color=PN, border_color=EG),
        "CTkLabel": dict(text_color=TX),
        "CTkButton": dict(fg_color=N, hover_color=NH, text_color=BK, border_color=EG, text_color_disabled=GR),
        "CTkEntry": dict(fg_color=FD, border_color=EG, text_color=TX, placeholder_text_color=GR),
        "CTkTextbox": dict(fg_color=FD, border_color=EG, text_color=TX, scrollbar_button_color=ND,
                           scrollbar_button_hover_color=NH),
        "CTkScrollbar": dict(button_color=ND, button_hover_color=NH),
        "CTkScrollableFrame": dict(label_fg_color=FD, fg_color=PN, border_color=EG),
        "CTkCheckBox": dict(fg_color=N, border_color=EG, hover_color=NH, checkmark_color=BK, text_color=TX),
        "CTkRadioButton": dict(fg_color=N, border_color=EG, hover_color=NH, text_color=TX),
        "CTkSlider": dict(fg_color=FD, progress_color=ND, button_color=N, button_hover_color=NH, border_color=EG),
        "CTkProgressBar": dict(fg_color=FD, progress_color=N, border_color=EG),
        "CTkOptionMenu": dict(fg_color=ND, button_color=N, button_hover_color=NH, text_color=TX,
                              dropdown_fg_color=FD, dropdown_hover_color=ND, dropdown_text_color=TX),
        "CTkComboBox": dict(fg_color=FD, button_color=N, button_hover_color=NH, border_color=EG, text_color=TX,
                            dropdown_fg_color=FD, dropdown_hover_color=ND, dropdown_text_color=TX),
        "CTkSegmentedButton": dict(fg_color=FD, selected_color=N, selected_hover_color=NH, unselected_color=FD,
                                   unselected_hover_color=ND, text_color=TX, text_color_disabled=GR, border_color=EG),
        "CTkTabview": dict(fg_color=PN, border_color=EG, segmented_button_fg_color=FD,
                           segmented_button_selected_color=N, segmented_button_selected_hover_color=NH,
                           segmented_button_unselected_color=FD, segmented_button_unselected_hover_color=ND,
                           text_color=TX, text_color_disabled=GR),
    }
    for w, rule in rules.items():
        if w in t:
            for k, v in rule.items():
                if k in t[w]:
                    t[w][k] = v
    p = os.path.join(tempfile.gettempdir(), "chauhan_clipping_theme.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(t, f)
    ctk.set_default_color_theme(p)


# ------------------------------------------------------------------ item dialogs (overlay / text / audio)
class ItemDialog(ctk.CTkToplevel):
    TITLE = "Item"
    DEF = {}
    SIZE = "600x700"

    def __init__(self, app, item, on_ok):
        super().__init__(app)
        self.title(self.TITLE)
        self.geometry(self.SIZE)
        self.configure(fg_color=PANEL)
        self.on_ok = on_ok
        self.d = {**self.DEF, **(item or {})}
        self.v = {}
        self.body = ctk.CTkScrollableFrame(self)
        self.body.pack(fill="both", expand=True, padx=8, pady=8)
        self.f = Form(self.body, self.v, self.d)
        self.build()
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", padx=10, pady=8)
        ctk.CTkButton(bar, text="Save", width=120, command=self.ok).pack(side="right")
        ctk.CTkButton(bar, text="Cancel", width=120, fg_color="#2A2A2A", hover_color="#3A3A3A", text_color=TEXT,
                      command=self.destroy).pack(side="right", padx=6)
        self.transient(app)
        self.after(150, self.grab_set)

    def build(self):
        pass

    def extra(self):
        return {}

    def check(self, it):
        pass

    def ok(self):
        try:
            it = dict(self.d)
            for k, var in self.v.items():
                it[k] = conv(self.DEF[k], var.get())
            it.update(self.extra())
            if float(it["end"]) <= float(it["start"]):
                raise ValueError("End, Start se bada hona chahiye.")
            self.check(it)
        except ValueError as e:
            messagebox.showerror(self.TITLE, str(e), parent=self)
            return
        self.on_ok(it)
        self.destroy()


class OverlayDialog(ItemDialog):
    TITLE = "Overlay (photo / video / GIF)"
    DEF = E.OVERLAY_DEFAULT
    SIZE = "600x720"

    def build(self):
        f = self.f
        f.file("File", "path", IMG_VID)
        f.menu("Layer (3 = top)", "layer", [1, 2, 3])
        f.entry("Start (timeline sec)", "start")
        f.entry("End (timeline sec)", "end")
        f.menu("Position", "pos", E.POSITIONS)
        f.slider("Custom X %", "x", 0, 100, 1, "{:.0f}")
        f.slider("Custom Y %", "y", 0, 100, 1, "{:.0f}")
        f.slider("Size (% of width)", "scale", 3, 100, 1, "{:.0f}")
        f.slider("Opacity %", "opacity", 5, 100, 1, "{:.0f}")
        f.check("Loop (video / GIF)", "loop")
        f.check("Remove green screen (uses the colour set in the Chroma tab)", "chroma")

    def check(self, it):
        if not os.path.isfile(str(it["path"])):
            raise ValueError("Please select a file first.")


class TextDialog(ItemDialog):
    TITLE = "Text"
    DEF = E.TEXT_DEFAULT
    SIZE = "640x860"

    def build(self):
        f = self.f
        ctk.CTkLabel(self.body, text="Text (Enter = nayi line)", text_color=TEXT, anchor="w").grid(
            row=f.row, column=0, columnspan=2, sticky="w", padx=8, pady=(6, 0))
        f.row += 1
        self.tb = ctk.CTkTextbox(self.body, height=90)
        self.tb.grid(row=f.row, column=0, columnspan=2, sticky="ew", padx=8, pady=4)
        self.tb.insert("1.0", str(self.d.get("text", "")))
        f.row += 1
        f.header("Font (Windows ke installed fonts)")
        fv = tk.StringVar(value=str(self.d["font"]))
        self.v["font"] = fv
        FontPicker(self.body, fv).grid(row=f.row, column=0, columnspan=2, sticky="ew", padx=8)
        f.row += 1
        f.note("For Hindi text choose 'Nirmala UI' or 'Mangal'.")
        f.menu("Layer (3 = top)", "layer", [1, 2, 3])
        f.entry("Start (timeline sec)", "start")
        f.entry("End (timeline sec)", "end")
        f.slider("Size (% of height)", "size", 1, 20, 0.5, "{:.1f}")
        f.color("Text color", "color")
        f.slider("Opacity %", "opacity", 5, 100, 1, "{:.0f}")
        f.slider("Outline width", "outline", 0, 10, 1, "{:.0f}")
        f.color("Outline color", "outline_color")
        f.check("Shadow", "shadow")
        f.check("Background box", "box")
        f.color("Box color", "box_color")
        f.slider("Box opacity %", "box_opacity", 0, 100, 1, "{:.0f}")
        f.menu("Position", "pos", E.POSITIONS)
        f.slider("Custom X %", "x", 0, 100, 1, "{:.0f}")
        f.slider("Custom Y %", "y", 0, 100, 1, "{:.0f}")

    def extra(self):
        return {"text": self.tb.get("1.0", "end").strip("\n")}

    def check(self, it):
        if not str(it["text"]).strip():
            raise ValueError("Please type some text.")


class AudioDialog(ItemDialog):
    TITLE = "Audio (apne PC se)"
    DEF = E.AUDIO_DEFAULT
    SIZE = "600x560"

    def build(self):
        f = self.f
        f.file("Audio file", "path", AUDIO)
        f.menu("Audio layer (1 / 2 / 3)", "layer", [1, 2, 3])
        f.entry("Start (timeline sec)", "start")
        f.entry("End (timeline sec)", "end")
        f.slider("Volume %", "volume", 0, 200, 1, "{:.0f}")
        f.check("Loop (choti file repeat ho)", "loop")
        f.note("The movie's original sound is controlled in the Colour tab.")

    def check(self, it):
        if not os.path.isfile(str(it["path"])):
            raise ValueError("Please select an audio file.")


DIALOGS = {"overlay": OverlayDialog, "text": TextDialog, "audio": AudioDialog}


# ------------------------------------------------------------------ timeline (tk canvas)
PPS_MIN, PPS_MAX = 0.05, 600.0                       # timeline zoom: pixels per second
RULER_STEPS = (0.1, 0.2, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 1800, 3600, 7200)


def ruler_step(pps):
    for st in RULER_STEPS:
        if st * pps >= 70:
            return st
    return RULER_STEPS[-1]


def pps_to_slider(pps):
    return 100.0 * math.log(max(PPS_MIN, min(PPS_MAX, pps)) / PPS_MIN) / math.log(PPS_MAX / PPS_MIN)


def slider_to_pps(v):
    return PPS_MIN * (PPS_MAX / PPS_MIN) ** (float(v) / 100.0)


class Timeline(ctk.CTkFrame):
    """Timeline with a real zoom. Only the part you can see is drawn, so every zoom level (0.05 to 600 pixels per
    second) works for a movie of any length. Ctrl + mouse wheel zooms at the pointer, the wheel scrolls sideways."""

    def __init__(self, parent, app):
        super().__init__(parent, fg_color="#050505", corner_radius=8)
        self.app = app
        self.pps = 30.0
        self.off = 0.0                  # pixels of the timeline hidden on the left of the window
        self.drag = None
        H = M.canvas_h()
        self.lab = tk.Canvas(self, width=110, height=H, bg="#050505", highlightthickness=0)
        self.lab.grid(row=0, column=0, sticky="ns")
        self.cv = tk.Canvas(self, height=H, bg="#050505", highlightthickness=0, bd=0)
        self.cv.grid(row=0, column=1, sticky="nsew")
        self.hs = tk.Scrollbar(self, orient="horizontal", command=self.on_scrollbar)
        self.hs.grid(row=1, column=1, sticky="ew")
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self.cv.bind("<Button-1>", self.on_press)
        self.cv.bind("<B1-Motion>", self.on_drag)
        self.cv.bind("<ButtonRelease-1>", self.on_release)
        self.cv.bind("<Double-Button-1>", self.on_double)
        self.cv.bind("<MouseWheel>", self.on_wheel)
        self.cv.bind("<Button-4>", self.on_wheel)
        self.cv.bind("<Button-5>", self.on_wheel)
        self.cv.bind("<Enter>", lambda e: self.cv.focus_set())
        self.cv.bind("<Configure>", lambda e: self.redraw())
        self.after(120, self.redraw)

    # ---------------- view
    def view_w(self):
        return max(200, self.cv.winfo_width())

    def total_px(self):
        return M.x_of(max(self.app.duration(), 10.0) + 60, self.pps) + 40

    def clamp(self):
        self.off = min(max(0.0, self.off), max(0.0, self.total_px() - self.view_w()))

    def cur_pps(self):
        return self.pps

    def _cx(self, e):
        return e.x + self.off

    def _notify(self):
        cb = getattr(self.app, "on_timeline_zoom", None)
        if cb:
            cb(self.pps)

    # ---------------- zoom
    def zoom_to(self, pps, anchor_x):
        """New zoom; the time under `anchor_x` (window pixels) stays where it is."""
        pps = min(PPS_MAX, max(PPS_MIN, float(pps)))
        t = M.t_of(anchor_x + self.off, self.pps)
        self.pps = pps
        self.off = M.x_of(t, pps) - anchor_x
        self.clamp()
        self.redraw()
        self._notify()

    def _anchor(self):
        """Zoom around the playhead when it is visible, otherwise around the middle of the window."""
        ax = M.x_of(self.app.t, self.pps) - self.off
        return ax if 0 <= ax <= self.view_w() else self.view_w() / 2.0

    def set_pps(self, v):
        self.zoom_to(float(v), self._anchor())

    def zoom_by(self, factor):
        self.zoom_to(self.pps * factor, self._anchor())

    def fit(self):
        """The whole movie fits in the window."""
        dur = max(self.app.duration(), 5.0)
        self.pps = min(PPS_MAX, max(PPS_MIN, (self.view_w() - M.PAD_X - 24) / dur))
        self.off = 0.0
        self.redraw()
        self._notify()

    def follow(self):
        """Called after the playhead moved: scrolls only when it left the window, then redraws."""
        px = M.x_of(self.app.t, self.pps) - self.off
        if px < 0 or px > self.view_w():
            self.off = M.x_of(self.app.t, self.pps) - self.view_w() / 2.0
            self.clamp()
        self.redraw()

    def on_wheel(self, e):
        d = getattr(e, "delta", 0)
        if getattr(e, "num", 0) == 4:
            d = 120
        elif getattr(e, "num", 0) == 5:
            d = -120
        if e.state & 0x4:                                   # Ctrl + wheel = zoom at the pointer
            self.zoom_to(self.pps * (1.25 ** (d / 120.0)), e.x)
        else:                                               # wheel = scroll sideways
            self.off -= d / 120.0 * self.view_w() * 0.12
            self.clamp()
            self.redraw()

    def on_scrollbar(self, *args):
        total, vw = self.total_px(), self.view_w()
        if args and args[0] == "moveto":
            self.off = float(args[1]) * total
        elif args and args[0] == "scroll":
            self.off += int(args[1]) * (vw * 0.9 if args[2] == "pages" else vw * 0.1)
        self.clamp()
        self.redraw()

    # ---------------- drawing (window coordinates = timeline pixel - self.off)
    def _clip(self, x0, x1):
        a, b = x0 - self.off, x1 - self.off
        if b < -2 or a > self.view_w() + 2:
            return None
        return max(a, -2.0), min(b, self.view_w() + 2.0)

    def redraw(self):
        app = self.app
        dur = app.duration()
        H = M.canvas_h()
        self.clamp()
        pps, off, vw = self.pps, self.off, self.view_w()
        total = self.total_px()
        self.hs.set(max(0.0, off / total), min(1.0, (off + vw) / total))
        self.cv.delete("all")
        self.lab.delete("all")
        # ruler
        step = ruler_step(pps)
        t = math.floor(M.t_of(off, pps) / step) * step
        t_end = M.t_of(off + vw, pps) + step
        while t <= t_end:
            x = M.x_of(t, pps) - off
            self.cv.create_line(x, M.RULER_H - 8, x, M.RULER_H, fill=GREY)
            self.cv.create_text(x + 3, 2, text=M.fmt_time(t), anchor="nw", fill=GREY, font=("Segoe UI", 8))
            for k in range(1, 5):
                xm = x + k * step * pps / 5.0
                self.cv.create_line(xm, M.RULER_H - 4, xm, M.RULER_H, fill="#444444")
            t += step
        # tracks
        names = {"T": "Text", "O": "Overlay", "A": "Audio", "V": "Video"}
        for i, (letter, layer) in enumerate(M.TRACKS):
            y0 = M.RULER_H + i * M.TRACK_H
            self.cv.create_rectangle(0, y0, vw, y0 + M.TRACK_H, fill=TRACK_BG[i % 2], outline="")
            label = f"{letter}{layer}  {names[letter]}" if letter != "V" else "V1  Movie"
            self.lab.create_text(10, y0 + M.TRACK_H / 2, text=label, anchor="w", fill=TEXT, font=("Segoe UI", 9))
        self.lab.create_rectangle(0, 0, 110, H, fill="#050505", outline="")
        # base movie
        if app.movie:
            x0, y0, x1, y1 = M.base_rect(dur, pps)
            c = self._clip(x0, x1)
            if c:
                self.cv.create_rectangle(c[0], y0, c[1], y1, fill="#1C1C1C", outline=EDGE)
                self.cv.create_text(max(c[0], 0) + 6, (y0 + y1) / 2, text=os.path.basename(app.movie), anchor="w",
                                    fill=GREY, font=("Segoe UI", 9))
        # items
        lists = app.lists()
        for kind in ("audio", "overlay", "text"):
            for i, it in enumerate(lists[kind]):
                x0, y0, x1, y1 = M.rect(kind, it, pps, dur)
                c = self._clip(x0, x1)
                if not c:
                    continue
                sel = app.sel == (kind, i)
                self.cv.create_rectangle(c[0], y0, c[1], y1, fill=ITEM_FILL[kind],
                                         outline="#FFFFFF" if sel else ITEM_LINE[kind], width=2 if sel else 1)
                self.cv.create_text(max(c[0], 0) + 6, (y0 + y1) / 2, text=M.item_label(kind, it), anchor="w",
                                    fill=TEXT, width=max(20, int(c[1] - max(c[0], 0) - 10)), font=("Segoe UI", 9))
        # playhead
        px = M.x_of(app.t, pps) - off
        if -8 <= px <= vw + 8:
            self.cv.create_line(px, 0, px, H, fill="#FFFFFF", width=2)
            self.cv.create_polygon(px - 6, 0, px + 6, 0, px, 10, fill="#FFFFFF", outline="")

    # ---------------- mouse
    def on_press(self, e):
        cx, cy = self._cx(e), e.y
        app = self.app
        dur = app.duration()
        if cy < M.RULER_H:
            self.drag = {"mode": "seek"}
            app.seek(M.t_of(cx, self.pps))
            return
        hit = M.hit_test(cx, cy, self.pps, dur, app.lists())
        if not hit:
            self.drag = None
            app.select(None)
            app.seek(M.t_of(cx, self.pps))
            return
        kind, i = hit
        it = app.lists()[kind][i]
        r = M.rect(kind, it, self.pps, dur)
        self.drag = dict(mode=M.edge_mode(cx, r), kind=kind, i=i, x0=cx,
                         s0=float(it["start"]), e0=M.item_end(kind, it, dur),
                         o0=float(it.get("src_offset", 0.0) or 0.0))
        app.select(kind, i)

    def on_drag(self, e):
        d = self.drag
        if not d:
            return
        cx = self._cx(e)
        app = self.app
        if d["mode"] == "seek":
            app.seek(M.t_of(cx, self.pps))
            return
        dt = (cx - d["x0"]) / self.pps
        it = app.lists()[d["kind"]][d["i"]]
        s, en, dso = M.drag_result(d["mode"], d["s0"], d["e0"], d["o0"], dt, d["kind"], app.duration())
        it["start"], it["end"] = round(s, 3), round(en, 3)
        if d["mode"] == "trim_l":
            it["src_offset"] = round(d["o0"] + dso, 3)
        self.redraw()
        app.refresh_inspector_times()

    def on_release(self, e):
        d = self.drag
        self.drag = None
        if not d or d["mode"] == "seek":
            return
        app = self.app
        if d["mode"] == "move":
            tr = M.track_at(e.y)
            if tr is not None:
                letter, layer = M.TRACKS[tr]
                if letter == M.KIND_LETTER[d["kind"]]:
                    app.lists()[d["kind"]][d["i"]]["layer"] = layer
        app.on_items_changed()

    def on_double(self, e):
        cx, cy = self._cx(e), e.y
        hit = M.hit_test(cx, cy, self.pps, self.app.duration(), self.app.lists())
        if hit:
            self.app.select(*hit)
            self.app.edit_selected()


# ------------------------------------------------------------------ main window
class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP_NAME}")
        self.geometry("1380x880")
        self.minsize(1200, 760)
        self.configure(fg_color="#050505")
        self.s = E.load_settings()
        self.v = {}          # editor form variables (colour, crop, chroma, audio)
        self.movie, self.info = "", None
        self.t = 0.0
        self.sel = None
        self.playing = False
        self.render_after = None
        self.token = 0
        self.shown_token = -1
        self.render_q = queue.Queue()
        self.renderer = P.Renderer(lambda img, tok, err: self.render_q.put((img, tok, err)))
        self.movie_var = tk.StringVar(value="")
        self._img = None

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=0)
        self.grid_rowconfigure(1, weight=1)
        self.project_path = ""            # "" = not saved yet
        self.saved_fp = self.saved_view_fp = None
        self.dirty = False
        self.last_autosave = time.time()
        self._relocated = {}
        self.prefs = PRJ.read_prefs()
        self.build_project_bar()
        self.tabs = ctk.CTkTabview(self)
        self.tabs.grid(row=1, column=0, sticky="nsew", padx=8, pady=(6, 8))
        self.tabs.add("Simple Edit")
        self.tabs.add("AI Clipping")
        self.tabs.add("Timeline (advanced)")
        self.tabs.add("Auto Short")
        self.simple = Studio(self.tabs.tab("Simple Edit"), self, "simple")
        self.simple.pack(fill="both", expand=True)
        self.ai = Studio(self.tabs.tab("AI Clipping"), self, "ai")
        self.auto_short = AutoShortFrame(self.tabs.tab("Auto Short"), self, self.simple)
        self.auto_short.pack(fill="both", expand=True)
        self.ai.pack(fill="both", expand=True)
        self.build_editor(self.tabs.tab("Timeline (advanced)"))
        self.tabs.set("Simple Edit")

        self.bind_all("<space>", self.on_space)
        self.bind_all("<Control-s>", lambda e: self.guard(self.project_save, "Save")())
        self.bind_all("<Control-S>", lambda e: self.guard(self.project_save, "Save")())
        self.bind_all("<Control-o>", lambda e: self.guard(self.project_open, "Open")())
        self.bind_all("<Delete>", lambda e: None if self._typing() else self.delete_selected())
        self.bind_all("<s>", lambda e: None if self._typing() else self.split_selected())
        self.bind_all("<S>", lambda e: None if self._typing() else self.split_selected())
        self.bind_all("<Left>", lambda e: None if self._typing() else self.step(-1 / 25))
        self.bind_all("<Right>", lambda e: None if self._typing() else self.step(1 / 25))
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.refresh_media()
        self.refresh_inspector()
        self.baseline()
        self.after(60, self.poll)
        self.after(900, self.guard(self.startup_restore, "Opening the last project"))
        self.after(3000, self.project_tick)

    # ---------------- layout
    def build_editor(self, f):
        f.grid_columnconfigure(1, weight=1)
        f.grid_rowconfigure(0, weight=3)
        f.grid_rowconfigure(1, weight=2)

        left = ctk.CTkFrame(f, width=250, corner_radius=10)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8), pady=(0, 8))
        left.grid_propagate(False)
        ctk.CTkLabel(left, text="CHAUHAN CLIPPING", font=ctk.CTkFont(size=17, weight="bold"),
                     text_color=NEON).pack(pady=(12, 0))
        ctk.CTkLabel(left, text="Media", text_color=GREY).pack()
        self.media = ctk.CTkScrollableFrame(left, height=170)
        self.media.pack(fill="x", padx=8, pady=6)
        row = ctk.CTkFrame(left, fg_color="transparent")
        row.pack(fill="x", padx=8)
        ctk.CTkButton(row, text="Browse...", width=110, command=self.browse_movie).pack(side="left", padx=2)
        ctk.CTkButton(row, text="Refresh", width=110, command=self.refresh_media).pack(side="right", padx=2)
        ctk.CTkLabel(left, text="Add to timeline (at playhead)", text_color=GREY).pack(pady=(10, 2))
        ctk.CTkLabel(left, text="Layer", text_color=TEXT).pack()
        self.add_layer = tk.StringVar(value="1")
        ctk.CTkSegmentedButton(left, values=["1", "2", "3"], variable=self.add_layer).pack(pady=4)
        ctk.CTkButton(left, text="+ Overlay (photo / video)", command=lambda: self.add_item("overlay")).pack(
            fill="x", padx=10, pady=3)
        ctk.CTkButton(left, text="+ Text", command=lambda: self.add_item("text")).pack(fill="x", padx=10, pady=3)
        ctk.CTkButton(left, text="+ Audio (apne PC se)", command=lambda: self.add_item("audio")).pack(
            fill="x", padx=10, pady=3)
        ctk.CTkButton(left, text="EXPORT (goes to Simple Edit)", height=44, font=ctk.CTkFont(size=15, weight="bold"),
                      command=self.open_export).pack(fill="x", padx=10, pady=(18, 4), side="bottom")
        ctk.CTkButton(left, text="Save settings", fg_color="#2A2A2A", hover_color="#3A3A3A", text_color=TEXT,
                      command=self.save_all).pack(fill="x", padx=10, pady=4, side="bottom")

        mid = ctk.CTkFrame(f, corner_radius=10)
        mid.grid(row=0, column=1, sticky="nsew", pady=(0, 8))
        mid.grid_rowconfigure(0, weight=1)
        mid.grid_columnconfigure(0, weight=1)
        self.screen = ctk.CTkLabel(mid, text="Choose a movie on the left", text_color=GREY, fg_color="#000000",
                                   corner_radius=6)
        self.screen.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        tr = ctk.CTkFrame(mid, fg_color="transparent")
        tr.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 8))
        ctk.CTkButton(tr, text="|<", width=50, command=lambda: self.seek(0.0)).pack(side="left", padx=2)
        ctk.CTkButton(tr, text="<", width=50, command=lambda: self.step(-1 / 25)).pack(side="left", padx=2)
        self.play_btn = ctk.CTkButton(tr, text="Play (Space)", width=130, command=self.toggle_play)
        self.play_btn.pack(side="left", padx=6)
        ctk.CTkButton(tr, text=">", width=50, command=lambda: self.step(1 / 25)).pack(side="left", padx=2)
        self.time_lbl = ctk.CTkLabel(tr, text="00:00.0 / 00:00.0", text_color=TEXT,
                                     font=ctk.CTkFont(family="Consolas", size=14))
        self.time_lbl.pack(side="right", padx=8)

        right = ctk.CTkFrame(f, width=340, corner_radius=10)
        right.grid(row=0, column=2, sticky="nsew", padx=(8, 0), pady=(0, 8))
        self.rtabs = ctk.CTkTabview(right)
        self.rtabs.pack(fill="both", expand=True, padx=6, pady=6)
        for n in ("Inspector", "Color", "Size/Crop", "Chroma"):
            self.rtabs.add(n)
        self.insp = ctk.CTkScrollableFrame(self.rtabs.tab("Inspector"))
        self.insp.pack(fill="both", expand=True)
        self.build_global_form(ctk.CTkScrollableFrame(self.rtabs.tab("Color")), "color")
        self.build_global_form(ctk.CTkScrollableFrame(self.rtabs.tab("Size/Crop")), "size")
        self.build_global_form(ctk.CTkScrollableFrame(self.rtabs.tab("Chroma")), "chroma")

        bot = ctk.CTkFrame(f, corner_radius=10)
        bot.grid(row=1, column=0, columnspan=3, sticky="nsew")
        bot.grid_rowconfigure(1, weight=1)
        bot.grid_columnconfigure(0, weight=1)
        bar = ctk.CTkFrame(bot, fg_color="transparent")
        bar.grid(row=0, column=0, sticky="ew", padx=8, pady=4)
        ctk.CTkButton(bar, text="Split (S)", width=95, command=self.split_selected).pack(side="left")
        ctk.CTkButton(bar, text="Delete (Del)", width=110, fg_color="#B3261E", hover_color="#8E1D17",
                      text_color=TEXT, command=self.delete_selected).pack(side="left", padx=6)
        ctk.CTkButton(bar, text="Edit (double-click)", width=150, fg_color="#2A2A2A", hover_color="#3A3A3A",
                      text_color=TEXT, command=self.edit_selected).pack(side="left", padx=6)
        ctk.CTkLabel(bar, text="Zoom", text_color=GREY).pack(side="left", padx=(16, 4))
        ctk.CTkButton(bar, text="-", width=32, fg_color="#2A2A2A", hover_color="#3A3A3A", text_color=TEXT,
                      command=lambda: self.timeline.zoom_by(1 / 1.5)).pack(side="left")
        self.zoom_slider = ctk.CTkSlider(bar, from_=0, to=100, width=170,
                                         command=lambda v: self.timeline.set_pps(slider_to_pps(v)))
        self.zoom_slider.set(pps_to_slider(30))
        self.zoom_slider.pack(side="left", padx=4)
        ctk.CTkButton(bar, text="+", width=32, fg_color="#2A2A2A", hover_color="#3A3A3A", text_color=TEXT,
                      command=lambda: self.timeline.zoom_by(1.5)).pack(side="left")
        ctk.CTkButton(bar, text="Fit all", width=64, fg_color="#2A2A2A", hover_color="#3A3A3A", text_color=TEXT,
                      command=lambda: self.timeline.fit()).pack(side="left", padx=6)
        self.zoom_lbl = ctk.CTkLabel(bar, text="30 px/s", text_color=GREY, width=70)
        self.zoom_lbl.pack(side="left")
        ctk.CTkLabel(bar, text="Ctrl + mouse wheel = zoom | wheel = scroll | drag a block = move | block edge = trim | "
                               "ruler click = playhead",
                     text_color=GREY).pack(side="right", padx=8)
        self.timeline = Timeline(bot, self)
        self.timeline.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))

    def build_global_form(self, parent, which):
        parent.pack(fill="both", expand=True)
        f = Form(parent, self.v, self.s, self.on_global)
        if which == "color":
            f.header("Colour correction (live)")
            holder = ctk.CTkFrame(parent, fg_color="transparent")
            holder.grid(row=f.row, column=0, columnspan=2, sticky="ew")
            f.row += 1
            self.colour_fields = {}
            ctk.CTkLabel(holder, text="Every control: -100 to +100 (0 = no change). Double-click a name to reset it.",
                         text_color=GREY, anchor="w").pack(anchor="w", padx=8, pady=(0, 2))
            for section, items in CL.LAYOUT:
                ctk.CTkLabel(holder, text=section, font=ctk.CTkFont(size=12, weight="bold"), text_color=NEON,
                             anchor="w").pack(anchor="w", padx=8, pady=(10, 2))
                for key, label in items:
                    nf = NumField(holder, label, -100, 100, 1, CL.to_ui(key, self.s[key]), "{:.0f}",
                                  lambda v, k=key: self.set_colour(k, v), label_width=110, default=0)
                    nf.pack(fill="x", padx=2, pady=2)
                    self.colour_fields[key] = nf
            f.check("Remove black bars automatically", "auto_crop")
            f.header("Original audio (movie ka sound)")
            f.slider("Original volume %", "orig_volume", 0, 200, 1, "{:.0f}")
            f.menu("Audio mode", "music_mode", E.MUSIC_MODES)
            f.note("Mix = original + audio layers saath. Replace = sirf audio layers.")
            ctk.CTkButton(parent, text="Reset colour", fg_color="#2A2A2A", hover_color="#3A3A3A", text_color=TEXT,
                          command=self.reset_color).grid(row=f.row, column=0, sticky="w", padx=8, pady=8)
        elif which == "size":
            f.header("Aspect ratio & fit")
            f.menu("Aspect ratio", "aspect", E.ASPECTS)
            f.menu("Jab ratio alag ho", "fit_mode", E.FIT_MODES)
            f.header("Crop")
            f.slider("Zoom", "zoom", 1.0, 3.0, 0.05)
            f.slider("Crop position X % (0 = left, 100 = right)", "crop_x", 0, 100, 1, "{:.0f}")
            f.slider("Crop position Y % (0 = top, 100 = bottom)", "crop_y", 0, 100, 1, "{:.0f}")
            f.note("Resolution, fps, codec and bitrate are in the export settings.")
        else:
            f.header("Chroma key (green screen)")
            f.check("Chroma key ON (main video)", "chroma_on")
            f.color("Key color", "chroma_color")
            f.slider("Similarity", "chroma_sim", 0.01, 0.5, 0.01)
            f.slider("Edge blend", "chroma_blend", 0.0, 0.5, 0.01)
            f.check("Remove colour spill on edges", "chroma_spill")
            f.header("Naya background")
            f.menu("Background type", "chroma_bg_type", E.BG_TYPES)
            f.color("Background color", "chroma_bg_color")
            f.file("Background image / video", "chroma_bg_file", IMG_VID)
            f.note("To remove green screen from an overlay, tick 'Remove green screen' in the overlay dialog.")

    # ---------------- settings sync
    def sync_vars(self):
        for k, var in self.v.items():
            try:
                self.s[k] = conv(E.DEFAULTS[k], var.get())
            except (ValueError, tk.TclError):
                pass
        return self.s

    def save_all(self):
        self.sync_vars()
        E.save_settings(self.s)
        messagebox.showinfo(APP_NAME, "Settings saved.")

    def on_global(self):
        self.sync_vars()
        self.schedule_render()

    def on_timeline_zoom(self, pps):
        self.zoom_slider.set(pps_to_slider(pps))
        self.zoom_lbl.configure(text=(f"{pps:.0f} px/s" if pps >= 10 else f"{pps:.2f} px/s"))

    def set_colour(self, key, ui):
        self.s[key] = CL.to_cfg(key, ui)
        self.on_global()

    def refresh_colour_fields(self):
        for key, nf in getattr(self, "colour_fields", {}).items():
            nf.set(CL.to_ui(key, self.s[key]))

    def reset_color(self):
        for key, nf in getattr(self, "colour_fields", {}).items():
            nf.set(0, notify=True)

    # ---------------- media
    def lists(self):
        return {"text": self.s["texts"], "overlay": self.s["overlays"], "audio": self.s["audios"]}

    def duration(self):
        return self.info["duration"] if self.info else 10.0

    def refresh_media(self):
        for w in self.media.winfo_children():
            w.destroy()
        movies = E.list_movies()
        if not movies:
            ctk.CTkLabel(self.media, text="input_movies folder mein\nmovie daalo, phir Refresh.",
                         text_color=GREY).pack(pady=12)
        for m in movies:
            ctk.CTkRadioButton(self.media, text=os.path.basename(m)[:30], value=m, variable=self.movie_var,
                               command=lambda p=m: self.load_movie(p)).pack(anchor="w", pady=3, padx=4)

    def browse_movie(self):
        p = filedialog.askopenfilename(filetypes=MOVIES)
        if p:
            self.load_movie(p)

    def load_movie(self, path):
        try:
            info = E.probe_info(path)
        except Exception as e:
            messagebox.showerror(APP_NAME, f"This movie could not be opened:\n{e}")
            return
        self.movie, self.info = path, info
        self.movie_var.set(path)
        dur = info["duration"]
        for kind in ("text", "overlay", "audio"):
            key = M.KIND_KEY[kind]
            self.s[key] = [M.norm_item(kind, it, dur) for it in self.s[key]]
        self.select(None)
        self.seek(0.0, render=False)
        self.on_items_changed()

    # ---------------- selection / inspector
    def select(self, kind, i=None):
        self.sel = (kind, i) if kind else None
        self.refresh_inspector()
        self.timeline.redraw()

    def refresh_inspector(self):
        for w in self.insp.winfo_children():
            w.destroy()
        if not self.sel:
            ctk.CTkLabel(self.insp, text="Select an item on the timeline.\n\nClick an Overlay / Text / Audio block "
                         "to change its settings here.", text_color=GREY, justify="left",
                         wraplength=290).pack(anchor="w", padx=8, pady=10)
            return
        kind, i = self.sel
        lst = self.lists()[kind]
        if i is None or i >= len(lst):
            self.sel = None
            return
        it = lst[i]
        ctk.CTkLabel(self.insp, text=f"{M.KIND_NAME[kind]} #{i + 1}", font=ctk.CTkFont(size=16, weight="bold"),
                     text_color=NEON).pack(anchor="w", padx=8, pady=(8, 0))
        ctk.CTkLabel(self.insp, text=M.item_label(kind, it), text_color=GREY, wraplength=290,
                     justify="left").pack(anchor="w", padx=8)
        r = ctk.CTkFrame(self.insp, fg_color="transparent")
        r.pack(fill="x", padx=8, pady=6)
        ctk.CTkLabel(r, text="Layer", text_color=TEXT).pack(side="left")
        self.ins_layer = tk.StringVar(value=str(M.clamp_layer(it.get("layer", 1))))
        ctk.CTkOptionMenu(r, values=["1", "2", "3"], width=90, variable=self.ins_layer,
                          command=lambda v: self.set_layer(int(v))).pack(side="right")
        self.ins_start = tk.StringVar(value=f"{float(it['start']):.2f}")
        self.ins_end = tk.StringVar(value=f"{M.item_end(kind, it, self.duration()):.2f}")
        for label, var in (("Start (sec)", self.ins_start), ("End (sec)", self.ins_end)):
            rr = ctk.CTkFrame(self.insp, fg_color="transparent")
            rr.pack(fill="x", padx=8, pady=3)
            ctk.CTkLabel(rr, text=label, text_color=TEXT, width=100, anchor="w").pack(side="left")
            ctk.CTkEntry(rr, textvariable=var, width=130).pack(side="right")
        ctk.CTkButton(self.insp, text="Apply times", command=self.apply_times).pack(fill="x", padx=8, pady=6)
        ctk.CTkButton(self.insp, text="Edit all properties...", command=self.edit_selected).pack(
            fill="x", padx=8, pady=3)
        ctk.CTkButton(self.insp, text="Split at playhead (S)", fg_color="#2A2A2A", hover_color="#3A3A3A",
                      text_color=TEXT, command=self.split_selected).pack(fill="x", padx=8, pady=3)
        ctk.CTkButton(self.insp, text="Delete (Del)", fg_color="#B3261E", hover_color="#8E1D17", text_color=TEXT,
                      command=self.delete_selected).pack(fill="x", padx=8, pady=3)
        ctk.CTkLabel(self.insp, text=f"Layer {it.get('layer', 1)} (3 = top). Drag the block up/down "
                     "drag karke bhi layer badal sakte ho.", text_color=GREY, wraplength=290,
                     justify="left").pack(anchor="w", padx=8, pady=6)

    def refresh_inspector_times(self):
        if self.sel and hasattr(self, "ins_start"):
            kind, i = self.sel
            it = self.lists()[kind][i]
            try:
                self.ins_start.set(f"{float(it['start']):.2f}")
                self.ins_end.set(f"{M.item_end(kind, it, self.duration()):.2f}")
            except Exception:
                pass

    def set_layer(self, v):
        if self.sel:
            kind, i = self.sel
            self.lists()[kind][i]["layer"] = int(v)
            self.on_items_changed()

    def apply_times(self):
        if not self.sel:
            return
        kind, i = self.sel
        it = self.lists()[kind][i]
        try:
            s = float(self.ins_start.get())
            e = float(self.ins_end.get())
        except ValueError:
            messagebox.showerror(APP_NAME, "Enter Start / End as numbers (for example 12.5).")
            return
        if e <= s:
            messagebox.showerror(APP_NAME, "End, Start se bada hona chahiye.")
            return
        dur = self.duration()
        if kind != "audio" and dur > 0:
            e = min(e, dur)
        it["start"], it["end"] = max(0.0, s), e
        self.on_items_changed()

    def edit_selected(self):
        if not self.sel:
            return
        kind, i = self.sel
        cur = self.lists()[kind][i]

        def done(new):
            lst = self.lists()[kind]
            if i < len(lst):
                lst[i] = M.norm_item(kind, new, self.duration())
            self.on_items_changed()
        DIALOGS[kind](self, cur, done)

    def delete_selected(self):
        if not self.sel:
            return
        kind, i = self.sel
        del self.lists()[kind][i]
        self.select(None)
        self.on_items_changed()

    def split_selected(self):
        if not self.sel or not self.movie:
            return
        kind, i = self.sel
        lst = self.lists()[kind]
        parts = M.split_item(kind, lst[i], self.t, self.duration())
        if parts is None:
            return
        a, b = parts
        lst[i] = a
        lst.insert(i + 1, b)
        self.select(kind, i + 1)
        self.on_items_changed()

    def on_space(self, e):
        if not self._typing():
            self.toggle_play()

    def _typing(self):
        try:
            w = self.focus_get()
            return w is not None and w.winfo_class() in ("Entry", "Text", "TEntry", "TCombobox")
        except Exception:
            return False

    # ---------------- add items (playhead, chosen layer)
    def add_item(self, kind):
        if not self.movie:
            messagebox.showwarning(APP_NAME, "Please load a movie first.")
            return
        dur = self.duration()
        layer = int(self.add_layer.get())
        base = {"layer": layer, "start": round(self.t, 2)}
        if kind == "text":
            base.update(text="Your text", end=min(dur, self.t + 4))
        else:
            ft = OVERLAY_TYPES if kind == "overlay" else AUDIO
            path = filedialog.askopenfilename(filetypes=ft)
            if not path:
                return
            length = 5.0
            try:
                if kind == "audio" or path.lower().endswith(E.OVERLAY_VIDEO_EXT):
                    length = max(1.0, E.probe_duration(path))
            except Exception:
                length = 5.0
            base.update(path=path, end=round(self.t + length, 2))

        def done(new):
            lst = self.lists()[kind]
            lst.append(M.norm_item(kind, new, dur))
            self.select(kind, len(lst) - 1)
            self.on_items_changed()
        DIALOGS[kind](self, base, done)

    # ---------------- playback / render
    def seek(self, t, render=True):
        d = self.duration()
        self.t = min(max(0.0, t), max(0.0, d))
        self.time_lbl.configure(text=f"{M.fmt_time(self.t)} / {M.fmt_time(d)}")
        self.timeline.follow()
        if render:
            self.schedule_render()

    def step(self, dt):
        if self.movie:
            self.seek(self.t + dt)

    def toggle_play(self):
        if not self.movie:
            return
        self.playing = not self.playing
        self.play_btn.configure(text="Pause (Space)" if self.playing else "Play (Space)")
        if self.playing:
            self._tick()

    def _tick(self):
        if not self.playing:
            return
        if self.t >= self.duration() - 0.05:
            self.playing = False
            self.play_btn.configure(text="Play (Space)")
            return
        self.seek(self.t + 0.2)
        self.after(220, self._tick)

    def on_items_changed(self):
        self.timeline.redraw()
        self.refresh_inspector()
        self.schedule_render()

    def schedule_render(self):
        if self.render_after:
            self.after_cancel(self.render_after)
        self.render_after = self.after(70, self.render_now)

    def render_now(self):
        self.render_after = None
        if not self.movie:
            return
        self.token += 1
        self.sync_vars()
        self.renderer.submit(self.movie, self.t, self.s, self.token)

    def show_frame(self, img, err):
        if err:
            self.screen.configure(image=None, text="Preview error:\n" + err[-200:])
            return
        k = min(780 / img.width, 470 / img.height)
        self._img = ctk.CTkImage(light_image=img, dark_image=img, size=(int(img.width * k), int(img.height * k)))
        self.screen.configure(image=self._img, text="")

    # ---------------- export (now lives in the Simple Edit tab)
    def open_export(self):
        self.tabs.set("Simple Edit")

    # ================================================================ project (save / open)
    def build_project_bar(self):
        bar = ctk.CTkFrame(self, corner_radius=10)
        bar.grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 0))
        ctk.CTkLabel(bar, text="PROJECT", text_color=NEON, font=ctk.CTkFont(size=12, weight="bold")).pack(
            side="left", padx=(12, 6), pady=6)
        self.proj_lbl = ctk.CTkLabel(bar, text="Untitled", text_color=TEXT, anchor="w")
        self.proj_lbl.pack(side="left", padx=4)
        self.proj_note = ctk.CTkLabel(bar, text="", text_color=GREY, anchor="w")
        self.proj_note.pack(side="left", padx=10)
        for text, cmd, w in (("Save as", self.project_save_as, 80), ("Save  (Ctrl+S)", self.project_save, 120),
                             ("Open  (Ctrl+O)", self.project_open, 120), ("New project", self.project_new, 100)):
            ctk.CTkButton(bar, text=text, width=w, height=30, fg_color=QUIET, hover_color=QUIET_H, text_color=TEXT,
                          command=self.guard(cmd, text.split("  ")[0])).pack(side="right", padx=3, pady=6)
        self.recent_menu = ctk.CTkOptionMenu(bar, values=["(none yet)"], width=170, height=30, fg_color=QUIET,
                                             button_color=QUIET_H, text_color=TEXT,
                                             command=self.guard1(self.open_recent, "Open recent"))
        self.recent_menu.set("Recent projects")
        self.recent_menu.pack(side="right", padx=3, pady=6)
        self.refresh_recent()
        self.reopen_var = tk.BooleanVar(value=bool(self.prefs.get("reopen_last", True)))
        ctk.CTkCheckBox(bar, text="Open the last project at start", variable=self.reopen_var,
                        text_color=TEXT, command=self.save_prefs).pack(side="right", padx=10)

    # ---- every project action runs through a guard, so a problem is always shown (never silent)
    def guard(self, fn, what):
        def run(*a):
            try:
                return fn()
            except Exception:
                self.report_error(what)
        return run

    def guard1(self, fn, what):
        def run(arg):
            try:
                return fn(arg)
            except Exception:
                self.report_error(what)
        return run

    def report_error(self, what):
        tb = traceback.format_exc()
        try:
            os.makedirs(PRJ.PROJECT_DIR, exist_ok=True)
            with open(os.path.join(PRJ.PROJECT_DIR, "_error.log"), "a", encoding="utf-8") as f:
                f.write(f"--- {time.strftime('%Y-%m-%d %H:%M:%S')}  {what}\n{tb}\n")
        except OSError:
            pass
        messagebox.showerror(APP_NAME, f"{what} did not work.\n\n{tb[-700:]}\n\n(The same text is saved in "
                                       f"projects/_error.log. Please send it to us.)")

    def refresh_recent(self):
        paths = [p for p in self.prefs.get("recent", []) if os.path.isfile(p)][:8]
        self.recent_paths = {os.path.basename(p): p for p in paths}
        self.recent_menu.configure(values=list(self.recent_paths) or ["(none yet)"])

    def open_recent(self, name):
        self.recent_menu.set("Recent projects")
        path = self.recent_paths.get(name)
        if path and self.confirm_discard():
            self.open_project(path)

    def save_prefs(self):
        self.prefs["reopen_last"] = bool(self.reopen_var.get())
        PRJ.write_prefs(self.prefs)

    def remember_last(self, path):
        self.prefs["last_project"] = path
        self.prefs["recent"] = ([path] + [p for p in self.prefs.get("recent", []) if p != path])[:8]
        self.prefs["reopen_last"] = bool(self.reopen_var.get())
        PRJ.write_prefs(self.prefs)
        self.refresh_recent()

    @staticmethod
    def content_view(st):
        """The state without 'where you are looking' (tab, part, position): moving around is not a change."""
        c = copy.deepcopy(st)
        c.pop("active_tab", None)
        for k in ("simple", "ai"):
            sub = c.get(k) or {}
            for key in ("right_tab", "part_idx", "t_rel", "sel"):
                sub.pop(key, None)
        (c.get("timeline") or {}).pop("t", None)
        return c

    def blank_state(self):
        return dict(active_tab="Simple Edit", simple={}, ai={}, timeline={}, auto_short={})

    def collect_state(self):
        self.sync_vars()
        return dict(active_tab=self.tabs.get(), simple=self.simple.get_state(), ai=self.ai.get_state(),
                    timeline=dict(settings=copy.deepcopy(self.s), movie=self.movie, t=round(float(self.t), 3)),
                    auto_short=self.auto_short.get_state())

    def baseline(self):
        st = self.collect_state()
        self.saved_fp = PRJ.fingerprint(self.content_view(st))
        self.saved_view_fp = PRJ.fingerprint(st)
        self.dirty = False
        self.refresh_project_label()

    def refresh_project_label(self):
        name = PRJ.title_of(self.project_path)
        star = " *" if self.dirty else ""
        self.proj_lbl.configure(text=name + star + (f"     {self.project_path}" if self.project_path else ""))
        self.title(f"{APP_NAME} - {name}{star}")

    def note(self, text):
        self.proj_note.configure(text=text)
        self.after(4000, lambda: self.proj_note.configure(text=""))

    def resolve_movie(self, saved):
        """The saved movie path, or (if the file was moved) the file the user points to."""
        if not saved:
            return ""
        if saved in self._relocated:
            return self._relocated[saved]
        found = PRJ.find_movie(saved, self.project_path)
        if not found and messagebox.askyesno(APP_NAME, f"The movie of this project was not found:\n{saved}\n\n"
                                                       "Do you want to choose where it is now?"):
            found = filedialog.askopenfilename(title="Where is the movie?", filetypes=MOVIES) or ""
        self._relocated[saved] = found
        return found

    def apply_state(self, st):
        """Puts a saved project back into every tab. Returns a list of problems (empty = all restored)."""
        self._relocated = {}
        problems = []
        for key, studio in (("simple", self.simple), ("ai", self.ai)):
            sub = st.get(key) or {}
            try:
                problems += studio.set_state(sub, self.resolve_movie(sub.get("movie", ""))) or []
            except Exception as e:
                problems.append(f"{key} tab: {e}")
        try:
            self.apply_timeline_state(st.get("timeline") or {})
        except Exception as e:
            problems.append(f"timeline: {e}")
        try:
            self.auto_short.set_state(st.get("auto_short"))
            self.auto_short.refresh_movie()
        except Exception as e:
            problems.append(f"auto short tab: {e}")
        try:
            self.tabs.set(st.get("active_tab") or "Simple Edit")
        except Exception:
            pass
        return problems

    def apply_timeline_state(self, tl):
        saved_s = E.sanitize(dict(tl.get("settings") or {}))
        self.s.clear()
        self.s.update(saved_s)
        for k, var in self.v.items():
            try:
                var.set(self.s[k])
            except Exception:
                pass
        self.s.update(saved_s)
        self.refresh_colour_fields()
        mv = self.resolve_movie(tl.get("movie", ""))
        if mv:
            self.load_movie(mv)
        else:
            self.movie, self.info = "", None
            self.movie_var.set("")
            self.select(None)
            self.seek(0.0, render=False)
            self.on_items_changed()
        self.seek(float(tl.get("t", 0.0) or 0.0))

    def finish_load(self, restored):
        self.update_idletasks()
        self.baseline()
        if restored:                      # the recovered work is not saved in the project file yet
            self.saved_fp, self.dirty = None, True
            self.refresh_project_label()

    def confirm_discard(self):
        """Before New / Open / closing: offers to save changes. False = the user cancelled."""
        st = self.collect_state()
        if PRJ.fingerprint(self.content_view(st)) != self.saved_fp:
            name = PRJ.title_of(self.project_path)
            ans = messagebox.askyesnocancel(APP_NAME, f"Do you want to save the changes to '{name}'?")
            if ans is None:
                return False
            if ans:
                if not self.project_save():
                    return False
            else:
                PRJ.remove_autosave(self.project_path)       # thrown away on purpose
        elif self.project_path and PRJ.fingerprint(st) != self.saved_view_fp:
            self.write_project(self.project_path, quiet=True)   # only the place where you stopped changed
        return True

    def project_new(self):
        """New project, like in any editing software: name it, and it starts empty (and is saved at once)."""
        if not self.confirm_discard():
            return
        os.makedirs(PRJ.PROJECT_DIR, exist_ok=True)
        path = filedialog.asksaveasfilename(title="New project - choose a name", initialdir=PRJ.PROJECT_DIR,
                                            initialfile="New project" + PRJ.EXT, defaultextension=PRJ.EXT,
                                            filetypes=[("Chauhan Clipping project", "*" + PRJ.EXT)])
        if not path:
            return
        self.project_path = ""
        PRJ.remove_autosave("")
        problems = self.apply_state(self.blank_state())
        self.project_path = path
        if not self.write_project(path, quiet=True):
            return
        self.finish_load(False)
        self.note("New project created: " + PRJ.title_of(path))
        if problems:
            messagebox.showwarning(APP_NAME, "The new project is ready, but:\n" + "\n".join(problems[:6]))

    def project_open(self):
        if not self.confirm_discard():
            return
        os.makedirs(PRJ.PROJECT_DIR, exist_ok=True)
        path = filedialog.askopenfilename(title="Open project", initialdir=PRJ.PROJECT_DIR,
                                          filetypes=[("Chauhan Clipping project", "*" + PRJ.EXT), ("All files", "*.*")])
        if path:
            self.open_project(path)

    def open_project(self, path):
        try:
            st = PRJ.load(path)
        except PRJ.ProjectError as e:
            messagebox.showerror(APP_NAME, str(e))
            return False
        restored = False
        rec = PRJ.newer_autosave(path)
        if rec and messagebox.askyesno(APP_NAME, "Unsaved changes from your last session were found for this "
                                                 "project.\n\nDo you want to restore them?"):
            try:
                st, restored = PRJ.load(rec), True
            except PRJ.ProjectError:
                pass
        self.project_path = path
        problems = self.apply_state(st)
        self.finish_load(restored)
        self.remember_last(path)
        self.note("Project opened - you are back where you stopped.")
        if problems:
            messagebox.showwarning(APP_NAME, "The project was opened, but these parts could not be restored:\n"
                                   + "\n".join(problems[:6]))
        return True

    def project_save(self):
        if not self.project_path:
            return self.project_save_as()
        return self.write_project(self.project_path)

    def project_save_as(self):
        os.makedirs(PRJ.PROJECT_DIR, exist_ok=True)
        start = PRJ.title_of(self.project_path) if self.project_path else (
            PRJ.title_of(self.simple.movie) if self.simple.movie else "my project")
        path = filedialog.asksaveasfilename(title="Save project", initialdir=PRJ.PROJECT_DIR,
                                            initialfile=start + PRJ.EXT, defaultextension=PRJ.EXT,
                                            filetypes=[("Chauhan Clipping project", "*" + PRJ.EXT)])
        return self.write_project(path) if path else False

    def write_project(self, path, quiet=False):
        st = self.collect_state()
        try:
            PRJ.save(path, st)
        except OSError as e:
            messagebox.showerror(APP_NAME, f"The project could not be saved:\n{e}")
            return False
        old = self.project_path
        self.project_path = path
        for p in {path, old, ""}:
            PRJ.remove_autosave(p)
        self.saved_fp = PRJ.fingerprint(self.content_view(st))
        self.saved_view_fp = PRJ.fingerprint(st)
        self.dirty = False
        self.remember_last(path)
        self.refresh_project_label()
        if not quiet:
            self.note("Saved " + time.strftime("%H:%M:%S"))
        return True

    def project_tick(self):
        """Every 3 seconds: shows the * for unsaved changes and writes an autosave copy every 2 minutes."""
        try:
            st = self.collect_state()
            self.dirty = PRJ.fingerprint(self.content_view(st)) != self.saved_fp
            if self.dirty and time.time() - self.last_autosave > 120:
                PRJ.save(PRJ.autosave_path(self.project_path), st)
                self.last_autosave = time.time()
            self.refresh_project_label()
        except Exception:
            pass
        self.after(3000, self.project_tick)

    def startup_restore(self):
        """Opens the project you were working on when the app was closed."""
        last = self.prefs.get("last_project", "")
        if self.reopen_var.get() and last and os.path.isfile(last):
            self.open_project(last)
        elif PRJ.newer_autosave("") and messagebox.askyesno(APP_NAME, "Your last unsaved session was found.\n\n"
                                                                    "Do you want to restore it?"):
            try:
                self.project_path = ""
                self.apply_state(PRJ.load(PRJ.UNTITLED_AUTOSAVE))
                self.finish_load(True)
            except Exception:
                messagebox.showerror(APP_NAME, "The saved session could not be restored.")

    # ---------------- main loop
    def poll(self):
        latest = None
        while True:
            try:
                latest = self.render_q.get_nowait()
            except queue.Empty:
                break
        if latest is not None:
            img, tok, err = latest
            if tok >= self.shown_token:
                self.shown_token = tok
                try:
                    self.show_frame(img, err)
                except Exception:
                    pass
        self.after(60, self.poll)

    def on_close(self):
        try:
            if not self.confirm_discard():
                return
        except Exception:
            self.report_error("Saving before closing")
        try:
            for tab in (self.simple, self.ai):
                tab.on_close_cleanup()
            E.save_settings(self.sync_vars())
        finally:
            self.destroy()


OVERLAY_TYPES = IMG_VID


if __name__ == "__main__":
    os.makedirs(E.INPUT_DIR, exist_ok=True)
    os.makedirs(E.OUTPUT_DIR, exist_ok=True)
    apply_theme()
    App().mainloop()
