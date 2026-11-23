"""AutoClip section: the open-source AutoClip desktop app (MIT licence, github.com/zhouxiaoka/autoclip) is included
in the portable folder (autoclip\\) and opened from this tab. Paste a link or choose a movie, pick a platform and get
the clip video, its cover, title, description and hashtags. It has its own editor, settings and publishing."""
import glob
import os
import subprocess
import tkinter as tk
import customtkinter as ctk
from tkinter import messagebox

BASE = os.path.dirname(os.path.abspath(__file__))
AC_DIR = os.path.join(BASE, "autoclip")
NEON, GREY, TEXT = "#39FF14", "#9A9A9A", "#EDEDED"

FEATURES = [
    ("One link, one click", "Paste a YouTube / Bilibili link or choose a movie file. AutoClip finds the highlights and "
     "makes up to 10 ranked clips per platform, more on demand."),
    ("Ready to post", "Every clip comes with a cover, a title, a description, hashtags and a ZIP publish kit."),
    ("Platforms", "TikTok, Instagram Reels, YouTube Shorts, YouTube (landscape), Douyin, Xiaohongshu, Bilibili - each "
     "with its own frame and length rules."),
    ("Layouts and framing", "Interview or full-screen podcast vertical layouts, or landscape. The framing follows the "
     "speaker; full frames stay when no person is found."),
    ("Captions and styles", "Burned-in captions with pagination and editing styles (editorial, street, news, cinema, "
     "classic)."),
    ("Your choice of AI", "Cloud models (OpenAI-compatible, Gemini, Qwen, DeepSeek, Grok ...) with your key, or local "
     "Ollama / LM Studio. Speech to text with local Whisper (understands Hindi) or the video's own captions."),
    ("Editor and publishing", "Open the editor to adjust any clip; connect accounts to publish."),
]


def exe_path():
    for p in sorted(glob.glob(os.path.join(AC_DIR, "*.exe"))):
        n = os.path.basename(p).lower()
        if not n.startswith("uninstall") and "setup" not in n:
            return p
    return None


class AutoClipFrame(ctk.CTkFrame):
    def __init__(self, parent, app):
        super().__init__(parent, fg_color="transparent")
        self.app = app
        self.proc = None
        top = ctk.CTkFrame(self)
        top.pack(fill="x", padx=8, pady=(8, 4))
        ctk.CTkLabel(top, text="AUTOCLIP  -  one link, one click: clips + cover + post text", text_color=NEON,
                     font=ctk.CTkFont(size=18, weight="bold")).pack(anchor="w", padx=12, pady=(10, 0))
        ctk.CTkLabel(top, text="Open-source AutoClip (MIT) included in this folder. It opens in its own window; "
                               "cutting and rendering run on this computer.", text_color=GREY).pack(anchor="w", padx=12)
        row = ctk.CTkFrame(top, fg_color="transparent")
        row.pack(fill="x", padx=12, pady=10)
        self.go = ctk.CTkButton(row, text="OPEN AUTOCLIP", height=44, width=200,
                                font=ctk.CTkFont(size=14, weight="bold"), command=self.open)
        self.go.pack(side="left")
        self.status = ctk.CTkLabel(top, text="", text_color=TEXT, anchor="w", wraplength=900, justify="left")
        self.status.pack(fill="x", padx=12, pady=(0, 10))
        feats = ctk.CTkScrollableFrame(self, label_text="What AutoClip does")
        feats.pack(fill="both", expand=True, padx=8, pady=4)
        for title, text in FEATURES:
            ctk.CTkLabel(feats, text=title, text_color=NEON, font=ctk.CTkFont(size=13, weight="bold"),
                         anchor="w").pack(fill="x", padx=8, pady=(8, 0))
            ctk.CTkLabel(feats, text=text, text_color=TEXT, wraplength=900, justify="left", anchor="w").pack(
                fill="x", padx=8)
        ctk.CTkLabel(feats, text="First time: in AutoClip open Settings, choose a model service, paste its key, test "
                                 "and save (or start Ollama for a free local model). Then choose a movie from "
                                 "input_movies (videos downloaded with the 'YouTube link' button are there too) or "
                                 "paste a link. For Hindi movies choose local Whisper for speech to subtitles.",
                     text_color=GREY, wraplength=900, justify="left", anchor="w").pack(fill="x", padx=8, pady=(12, 8))
        if not exe_path():
            self.go.configure(state="disabled")
            self.status.configure(text="AutoClip is not in this folder (autoclip\\ is missing). Use the latest "
                                       "ChauhanClipping-Windows.zip.")
        else:
            self.status.configure(text="Ready. The first start takes a little longer.")

    def open(self):
        exe = exe_path()
        if not exe:
            return
        if self.proc and self.proc.poll() is None:
            self.status.configure(text="AutoClip is already open (look for its window on the taskbar).")
            return
        try:
            self.proc = subprocess.Popen([exe], cwd=AC_DIR)
            self.status.configure(text="AutoClip is opening in its own window ...")
        except Exception as e:
            messagebox.showerror("AutoClip", f"AutoClip could not start:\n{e}")

    def on_close_cleanup(self):
        pass                      # AutoClip keeps running in its own window if the user wants
