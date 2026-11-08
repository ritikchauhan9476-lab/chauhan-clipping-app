"""Shared UI pieces: colours, form rows, number fields (slider + typed value), font picker."""
import os, sys, subprocess
import tkinter as tk
import customtkinter as ctk
from tkinter import filedialog, colorchooser
import engine as E

NEON = "#39FF14"
NEON_D = "#1E8A0C"
NEON_H = "#7BFF5C"
BLACK = "#000000"
PANEL = "#0E0E0E"
FIELD = "#171717"
GREY = "#8C8C8C"
TEXT = "#EAFFEA"
EDGE = "#1F5C12"
DANGER = "#B3261E"
DANGER_H = "#8E1D17"
QUIET = "#2A2A2A"
QUIET_H = "#3A3A3A"

IMG_VID = [("Photo / Video / GIF", "*.png *.jpg *.jpeg *.webp *.bmp *.gif *.mp4 *.mov *.mkv *.avi *.webm *.m4v"),
           ("All files", "*.*")]
AUDIO = [("Audio", "*.mp3 *.wav *.m4a *.aac *.flac *.ogg *.wma"), ("All files", "*.*")]
MOVIES = [("Video", "*.mp4 *.mkv *.avi *.mov *.wmv *.webm *.m4v *.ts"), ("All files", "*.*")]


def conv(default, val):
    if isinstance(default, bool):
        return bool(val)
    if isinstance(default, int):
        return int(float(val))
    if isinstance(default, float):
        return float(val)
    return str(val)


def open_path(p):
    if sys.platform.startswith("win"):
        os.startfile(p)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", p])
    else:
        subprocess.Popen(["xdg-open", p])


def hex_to_rgb(c, default="#000000"):
    c = str(c).strip().lstrip("#")
    if len(c) != 6:
        c = default.lstrip("#")
    try:
        return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
    except ValueError:
        return 0, 0, 0


class NumField(ctk.CTkFrame):
    """Label + slider + typed number box. Moving the slider updates the box and vice versa."""

    def __init__(self, parent, label, lo, hi, step, value, fmt="{:.2f}", on_change=None, label_width=118,
                 default=None):
        super().__init__(parent, fg_color="transparent")
        self.lo, self.hi, self.fmt, self.on_change = float(lo), float(hi), fmt, on_change
        self.default = default
        self.grid_columnconfigure(1, weight=1)
        self.lbl = ctk.CTkLabel(self, text=label, text_color=TEXT, anchor="w", width=label_width)
        self.lbl.grid(row=0, column=0, sticky="w", padx=(4, 4))
        if default is not None:                      # double-click the name = back to the default value
            self.lbl.bind("<Double-Button-1>", lambda e: self.set(self.default, notify=True))
        self.sl = ctk.CTkSlider(self, from_=self.lo, to=self.hi,
                                number_of_steps=max(1, int(round((self.hi - self.lo) / float(step)))),
                                command=self._from_slider)
        self.sl.grid(row=0, column=1, sticky="ew", padx=4)
        self.txt = tk.StringVar(value=self._fmt(value))
        self.ent = ctk.CTkEntry(self, textvariable=self.txt, width=72, justify="right")
        self.ent.grid(row=0, column=2, padx=(4, 4))
        self.ent.bind("<Return>", lambda e: self._from_entry())
        self.ent.bind("<FocusOut>", lambda e: self._from_entry())
        self.value = self._clamp(value)
        self.sl.set(self.value)

    def _clamp(self, v):
        return min(self.hi, max(self.lo, float(v)))

    def _fmt(self, v):
        return self.fmt.format(float(v))

    def get(self):
        return self.value

    def set(self, v, notify=False):
        self.value = self._clamp(v)
        self.sl.set(self.value)
        self.txt.set(self._fmt(self.value))
        if notify and self.on_change:
            self.on_change(self.value)

    def _from_slider(self, v):
        self.value = self._clamp(v)
        self.txt.set(self._fmt(self.value))
        if self.on_change:
            self.on_change(self.value)

    def _from_entry(self):
        try:
            v = float(self.txt.get())
        except ValueError:
            self.txt.set(self._fmt(self.value))
            return
        self.set(v, notify=True)


class Form:
    """Label + widget rows. Values go into `vars_`; `on_change` fires whenever a value changes."""

    def __init__(self, parent, vars_, data, on_change=None):
        self.p, self.v, self.d, self.cb, self.row = parent, vars_, data, on_change, 0
        parent.grid_columnconfigure(1, weight=1)

    def _watch(self, var):
        if self.cb:
            var.trace_add("write", lambda *a: self.cb())

    def _lbl(self, t):
        ctk.CTkLabel(self.p, text=t, anchor="w", text_color=TEXT).grid(
            row=self.row, column=0, sticky="w", padx=8, pady=4)

    def header(self, t):
        ctk.CTkLabel(self.p, text=t.upper(), font=ctk.CTkFont(size=13, weight="bold"), text_color=NEON,
                     anchor="w").grid(row=self.row, column=0, columnspan=2, sticky="w", padx=8, pady=(12, 4))
        self.row += 1

    def note(self, t):
        ctk.CTkLabel(self.p, text=t, anchor="w", justify="left", wraplength=300, text_color=GREY).grid(
            row=self.row, column=0, columnspan=2, sticky="w", padx=8, pady=(0, 6))
        self.row += 1

    def menu(self, t, k, vals):
        self._lbl(t)
        var = tk.StringVar(value=str(self.d[k]))
        self.v[k] = var
        ctk.CTkOptionMenu(self.p, values=[str(x) for x in vals], variable=var).grid(
            row=self.row, column=1, sticky="ew", padx=8)
        self._watch(var)
        self.row += 1

    def combo(self, t, k, vals):
        self._lbl(t)
        var = tk.StringVar(value=str(self.d[k]))
        self.v[k] = var
        ctk.CTkComboBox(self.p, values=[str(x) for x in vals], variable=var).grid(
            row=self.row, column=1, sticky="ew", padx=8)
        self._watch(var)
        self.row += 1

    def check(self, t, k):
        var = tk.BooleanVar(value=bool(self.d[k]))
        self.v[k] = var
        ctk.CTkCheckBox(self.p, text=t, variable=var, text_color=TEXT).grid(
            row=self.row, column=0, columnspan=2, sticky="w", padx=8, pady=4)
        self._watch(var)
        self.row += 1

    def color(self, t, k):
        self._lbl(t)
        var = tk.StringVar(value=str(self.d[k]))
        self.v[k] = var
        btn = ctk.CTkButton(self.p, text="", width=130)
        btn.grid(row=self.row, column=1, sticky="w", padx=8)

        def paint(*a):
            c = var.get()
            r, g, b = hex_to_rgb(c)
            btn.configure(text=c.upper(), fg_color=c, hover_color=c,
                          text_color=BLACK if (r * 0.3 + g * 0.59 + b * 0.11) > 140 else "#FFFFFF")

        def pick():
            res = colorchooser.askcolor(color=var.get(), parent=self.p, title=t)
            if res and res[1]:
                var.set(res[1])
        btn.configure(command=pick)
        paint()
        var.trace_add("write", paint)
        self._watch(var)
        self.row += 1

    def entry(self, t, k):
        self._lbl(t)
        var = tk.StringVar(value=str(self.d[k]))
        self.v[k] = var
        ctk.CTkEntry(self.p, textvariable=var).grid(row=self.row, column=1, sticky="ew", padx=8)
        self._watch(var)
        self.row += 1

    def check(self, t, k):
        var = tk.BooleanVar(value=bool(self.d[k]))
        self.v[k] = var
        ctk.CTkCheckBox(self.p, text=t, variable=var, text_color=TEXT).grid(
            row=self.row, column=0, columnspan=2, sticky="w", padx=8, pady=4)
        self._watch(var)
        self.row += 1

    def slider(self, t, k, lo, hi, step, fmt="{:.2f}"):
        var = tk.DoubleVar(value=float(self.d[k]))
        self.v[k] = var
        lbl = ctk.CTkLabel(self.p, anchor="w", text_color=TEXT)
        lbl.grid(row=self.row, column=0, sticky="w", padx=8)

        def show(*a):
            try:
                lbl.configure(text=f"{t}: " + fmt.format(var.get()))
            except Exception:
                pass
        show()
        var.trace_add("write", show)
        ctk.CTkSlider(self.p, from_=lo, to=hi, number_of_steps=max(1, int(round((hi - lo) / step))),
                      variable=var).grid(row=self.row, column=1, sticky="ew", padx=8)
        self._watch(var)
        self.row += 1

    def color(self, t, k):
        self._lbl(t)
        var = tk.StringVar(value=str(self.d[k]))
        self.v[k] = var
        btn = ctk.CTkButton(self.p, text="", width=130)
        btn.grid(row=self.row, column=1, sticky="w", padx=8)

        def paint(*a):
            c = var.get()
            try:
                r, g, b = int(c[1:3], 16), int(c[3:5], 16), int(c[5:7], 16)
                btn.configure(text=c.upper(), fg_color=c, hover_color=c,
                              text_color="#000000" if (r * 0.3 + g * 0.59 + b * 0.11) > 140 else "#FFFFFF")
            except Exception:
                pass

        def pick():
            res = colorchooser.askcolor(color=var.get(), parent=self.p, title=t)
            if res and res[1]:
                var.set(res[1])
        btn.configure(command=pick)
        paint()
        var.trace_add("write", paint)
        self._watch(var)
        self.row += 1

    def file(self, t, k, types):
        self._lbl(t)
        var = tk.StringVar(value=str(self.d[k]))
        self.v[k] = var
        fr = ctk.CTkFrame(self.p, fg_color="transparent")
        fr.grid(row=self.row, column=1, sticky="ew", padx=8)
        fr.grid_columnconfigure(0, weight=1)
        ctk.CTkEntry(fr, textvariable=var).grid(row=0, column=0, sticky="ew")

        def browse():
            pth = filedialog.askopenfilename(filetypes=types)
            if pth:
                var.set(pth)
        ctk.CTkButton(fr, text="...", width=36, command=browse).grid(row=0, column=1, padx=(4, 0))
        self._watch(var)
        self.row += 1


class FontPicker(ctk.CTkFrame):
    """Searchable list of the fonts installed on Windows (Hindi-capable fonts such as Nirmala UI)."""

    def __init__(self, parent, var):
        super().__init__(parent, fg_color="transparent")
        self.var = var
        self.names = list(E.get_system_fonts())
        self.shown = []
        self.filter = tk.StringVar()
        ctk.CTkEntry(self, textvariable=self.filter, placeholder_text="Search font...").pack(fill="x")
        fr = tk.Frame(self, bg=FIELD)
        fr.pack(fill="x", pady=4)
        self.lb = tk.Listbox(fr, height=6, exportselection=False, bg=FIELD, fg=TEXT,
                             selectbackground=NEON_D, highlightthickness=0, borderwidth=0, activestyle="none")
        sb = tk.Scrollbar(fr, command=self.lb.yview)
        self.lb.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.lb.pack(side="left", fill="x", expand=True)
        self.lb.bind("<<ListboxSelect>>", self.on_pick)
        self.filter.trace_add("write", lambda *a: self.fill())
        self.fill()

    def fill(self):
        q = self.filter.get().lower().strip()
        self.shown = [n for n in self.names if q in n.lower()]
        self.lb.delete(0, "end")
        for n in self.shown:
            self.lb.insert("end", n)
        cur = self.var.get()
        if cur in self.shown:
            i = self.shown.index(cur)
            self.lb.selection_set(i)
            self.lb.see(i)

    def on_pick(self, _=None):
        sel = self.lb.curselection()
        if sel:
            self.var.set(self.shown[sel[0]])
