"""PeakCut section: the open-source PeakCut clipper (MIT licence, github.com/haziqahmedqasmi/PeakCut) runs inside
this program. It turns YouTube links / movies into captioned vertical clips: transcript, AI picks the best moments,
word-by-word captions, hook, facecam layout, live-stream clipping and posting. It is a small local web server; this
tab starts and stops it and opens it in the browser. Everything it needs is in the portable folder:
peakcut\\ (the program), peakcut-data\\ (its videos, clips and the speech model), ffmpeg\\ and deno\\."""
import os
import queue
import socket
import subprocess
import sys
import threading
import time
import webbrowser
import tkinter as tk
import customtkinter as ctk
from tkinter import messagebox
import engine as E

BASE = os.path.dirname(os.path.abspath(__file__))
PK_DIR = os.path.join(BASE, "peakcut")
PK_DATA = os.path.join(BASE, "peakcut-data")
NEON, GREY, TEXT = "#39FF14", "#9A9A9A", "#EDEDED"

FEATURES = [
    ("Clips from a YouTube link or a movie", "Paste a YouTube / Twitch / Kick link or upload a movie. PeakCut reads "
     "what is said, finds the moments worth clipping and cuts them to 9:16."),
    ("AI picks the best moments", "Your own AI key (Gemini, OpenAI, Grok, Groq, OpenRouter, Claude or a local "
     "Ollama model). Without a key the loudest / most exciting moments are picked."),
    ("Word-by-word captions + hook", "Animated captions in three styles and a hook title at the start of each clip."),
    ("Facecam / gaming layouts", "Finds the streamer's face cam and stacks it above the game."),
    ("Live stream clipping", "Records a creator's live stream and clips the highlights while it is still running."),
    ("Posting", "Connect YouTube, Instagram and TikTok and queue or auto-post the finished clips."),
    ("Titles, hashtags, AI usage", "Titles and hashtags for every clip; a page shows how much AI each video used."),
]


def free_port(pref=8765):
    for p in [pref] + list(range(8766, 8800)):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", p))
                return p
            except OSError:
                continue
    return pref


def port_open(p):
    with socket.socket() as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", p)) == 0


class PeakCutFrame(ctk.CTkFrame):
    def __init__(self, parent, app):
        super().__init__(parent, fg_color="transparent")
        self.app = app
        self.proc = None
        self.port = None
        self.q = queue.Queue()
        self.build()
        self.after(200, self.poll)

    # ------------------------------------------------------------------ layout
    def build(self):
        top = ctk.CTkFrame(self)
        top.pack(fill="x", padx=8, pady=(8, 4))
        ctk.CTkLabel(top, text="PEAKCUT  -  AI clips from YouTube links and movies", text_color=NEON,
                     font=ctk.CTkFont(size=18, weight="bold")).pack(anchor="w", padx=12, pady=(10, 0))
        ctk.CTkLabel(top, text="Open-source PeakCut (MIT) built into this program. It opens in your web browser; "
                               "everything runs on this computer.", text_color=GREY).pack(anchor="w", padx=12)
        row = ctk.CTkFrame(top, fg_color="transparent")
        row.pack(fill="x", padx=12, pady=10)
        self.go = ctk.CTkButton(row, text="START PEAKCUT", height=44, width=200,
                                font=ctk.CTkFont(size=14, weight="bold"), command=self.start)
        self.go.pack(side="left")
        self.open_btn = ctk.CTkButton(row, text="Open in browser", height=44, state="disabled", command=self.open)
        self.open_btn.pack(side="left", padx=8)
        self.stop_btn = ctk.CTkButton(row, text="Stop", height=44, width=90, fg_color="#5A1A1A",
                                      hover_color="#7A2222", state="disabled", command=self.stop)
        self.stop_btn.pack(side="left")
        ctk.CTkButton(row, text="Clips folder", height=44, width=120, fg_color="#222", hover_color="#333",
                      command=lambda: self.open_folder(PK_DATA)).pack(side="left", padx=8)
        self.status = ctk.CTkLabel(top, text="Stopped.", text_color=TEXT, anchor="w")
        self.status.pack(fill="x", padx=12, pady=(0, 10))

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=8, pady=4)
        feats = ctk.CTkScrollableFrame(body, width=520, label_text="What PeakCut does")
        feats.pack(side="left", fill="both", padx=(0, 8))
        for title, text in FEATURES:
            ctk.CTkLabel(feats, text=title, text_color=NEON, font=ctk.CTkFont(size=13, weight="bold"),
                         anchor="w").pack(fill="x", padx=8, pady=(8, 0))
            ctk.CTkLabel(feats, text=text, text_color=TEXT, wraplength=470, justify="left", anchor="w").pack(
                fill="x", padx=8)
        ctk.CTkLabel(feats, text="First time: in PeakCut open Settings, AI, choose a service, paste your key and press "
                                 "'Save and test'. The English speech model is already included. Its speech "
                                 "recognition understands English (and Arabic after a download); for Hindi videos "
                                 "from YouTube it reads YouTube's own transcript. For Hindi movies use the AI "
                                 "Clipping and Auto Short tabs of this program.",
                     text_color=GREY, wraplength=470, justify="left", anchor="w").pack(fill="x", padx=8, pady=(12, 8))
        right = ctk.CTkFrame(body)
        right.pack(side="left", fill="both", expand=True)
        ctk.CTkLabel(right, text="PeakCut messages", text_color=GREY, anchor="w").pack(fill="x", padx=8, pady=(6, 0))
        self.log = ctk.CTkTextbox(right, font=ctk.CTkFont(family="Consolas", size=12))
        self.log.pack(fill="both", expand=True, padx=8, pady=8)
        if not os.path.isdir(PK_DIR):
            self.status.configure(text="PeakCut is not in this folder (peakcut\\ is missing). Use the latest "
                                       "ChauhanClipping-Windows.zip.")
            self.go.configure(state="disabled")
        elif len(BASE) > 110:
            self.add(f"Note: this folder's path is long ({len(BASE)} characters). If PeakCut's speech model does "
                     "not load, move the whole ChauhanClipping folder to a short place like C:\\ChauhanClipping.")

    def add(self, line):
        try:
            self.log.insert("end", line.rstrip() + "\n")
            self.log.see("end")
        except Exception:
            pass

    # ------------------------------------------------------------------ server
    def env(self):
        env = dict(os.environ)
        paths = [os.path.join(BASE, d) for d in ("ffmpeg", "deno") if os.path.isdir(os.path.join(BASE, d))]
        env["PATH"] = os.pathsep.join(paths + [env.get("PATH", "")])
        env.update(PEAKCUT_DATA=PK_DATA, PEAKCUT_PORT=str(self.port), PEAKCUT_HOST="127.0.0.1",
                   PEAKCUT_FFMPEG_DIR=os.path.join(BASE, "ffmpeg"), PYTHONNOUSERSITE="1", PYTHONIOENCODING="utf-8",
                   PYTHONUNBUFFERED="1")
        env.pop("PEAKCUT_ACCOUNTS", None)
        return env

    def start(self):
        if self.proc and self.proc.poll() is None:
            self.open()
            return
        os.makedirs(PK_DATA, exist_ok=True)
        self.port = free_port()
        self.add(f"Starting PeakCut on http://127.0.0.1:{self.port} ...")
        try:
            self.proc = subprocess.Popen([sys.executable, "-m", "studio.server"], cwd=PK_DIR, env=self.env(),
                                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                         creationflags=E.NOWIN)
        except Exception as e:
            messagebox.showerror("PeakCut", f"PeakCut could not start:\n{e}")
            return
        self.go.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.status.configure(text="Starting ... (the first start takes up to a minute)")
        threading.Thread(target=self._read, args=(self.proc,), daemon=True).start()
        self.started_at = time.time()
        self.opened = False

    def _read(self, proc):
        for raw in iter(proc.stdout.readline, b""):
            self.q.put(raw.decode("utf-8", errors="replace"))
        self.q.put(None)

    def poll(self):
        try:
            while True:
                line = self.q.get_nowait()
                if line is None:
                    code = self.proc.poll() if self.proc else None
                    self.add(f"PeakCut stopped (code {code}).")
                    self.status.configure(text="Stopped." if code in (0, None, 1, -15, 15) and getattr(self, "stopping", False)
                                          else "PeakCut stopped. See the messages on the right.")
                    self.go.configure(state="normal")
                    self.open_btn.configure(state="disabled")
                    self.stop_btn.configure(state="disabled")
                    self.stopping = False
                else:
                    self.add(line)
        except queue.Empty:
            pass
        if self.proc and self.proc.poll() is None and not getattr(self, "opened", True):
            if port_open(self.port):
                self.opened = True
                self.status.configure(text=f"Running:  http://127.0.0.1:{self.port}   (it opened in your browser)")
                self.open_btn.configure(state="normal")
                self.open()
            elif time.time() - self.started_at > 240:
                self.opened = True
                self.status.configure(text="PeakCut is taking very long to start. See the messages on the right.")
        self.after(400, self.poll)

    def open(self):
        if self.port:
            webbrowser.open(f"http://127.0.0.1:{self.port}")

    def stop(self):
        self.stopping = True
        p = self.proc
        if p and p.poll() is None:
            try:
                p.terminate()
                p.wait(timeout=8)
            except Exception:
                try:
                    p.kill()
                except Exception:
                    pass
        self.status.configure(text="Stopped.")
        self.go.configure(state="normal")
        self.open_btn.configure(state="disabled")
        self.stop_btn.configure(state="disabled")

    def open_folder(self, path):
        os.makedirs(path, exist_ok=True)
        try:
            os.startfile(path)                      # Windows
        except Exception:
            subprocess.Popen(["xdg-open", path])

    def on_close_cleanup(self):
        if self.proc and self.proc.poll() is None:
            self.stop()
