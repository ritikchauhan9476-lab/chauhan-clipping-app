"""Download a YouTube (or Instagram, Facebook, X ...) video from a link into input_movies, with yt-dlp.
YouTube needs a JavaScript runtime for yt-dlp nowadays: the portable folder carries deno.exe (deno\\ folder)."""
import os
import re
import threading
import engine as E

BASE = os.path.dirname(os.path.abspath(__file__))
QUALITIES = {"Best up to 1080p": 1080, "Best up to 720p": 720, "Best up to 4K": 2160}


def _env_path():
    for d in (os.path.join(BASE, "deno"), os.path.join(BASE, "ffmpeg")):
        if os.path.isdir(d) and d not in os.environ.get("PATH", ""):
            os.environ["PATH"] = d + os.pathsep + os.environ.get("PATH", "")


def available():
    try:
        import yt_dlp  # noqa: F401
        return True
    except Exception:
        return False


def download(url, max_h=1080, progress=None, stop=None, log=None):
    """Downloads the video, returns the path of the .mp4 (or .mkv) file in input_movies. Raises on error."""
    import yt_dlp
    _env_path()
    os.makedirs(E.INPUT_DIR, exist_ok=True)
    progress = progress or (lambda f, t: None)
    log = log or (lambda m: None)
    done = {}

    def hook(d):
        if stop is not None and stop.is_set():
            raise yt_dlp.utils.DownloadCancelled("stopped")
        if d.get("status") == "downloading":
            tot = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            got = d.get("downloaded_bytes") or 0
            sp = d.get("speed") or 0
            progress(got / tot if tot else None,
                     f"Downloading {got / 1e6:.0f} / {tot / 1e6:.0f} MB" + (f"  ({sp / 1e6:.1f} MB/s)" if sp else ""))
        elif d.get("status") == "finished":
            done["file"] = d.get("filename")
            progress(None, "Joining picture and sound ...")

    class Log:
        def debug(self, m):
            pass

        def info(self, m):
            pass

        def warning(self, m):
            log("note: " + str(m)[:300])

        def error(self, m):
            log(str(m)[:500])

    ffdir = os.path.join(BASE, "ffmpeg")
    opts = {
        "format": f"bv*[height<={max_h}][ext=mp4]+ba[ext=m4a]/bv*[height<={max_h}]+ba/b[height<={max_h}]/b",
        "merge_output_format": "mp4",
        "outtmpl": os.path.join(E.INPUT_DIR, "%(title).90B [%(id)s].%(ext)s"),
        "restrictfilenames": False, "windowsfilenames": True, "noplaylist": True,
        "progress_hooks": [hook], "logger": Log(), "quiet": True, "no_warnings": False,
        "concurrent_fragment_downloads": 4, "retries": 5, "fragment_retries": 5,
    }
    if os.path.isfile(os.path.join(ffdir, "ffmpeg.exe")) or os.path.isfile(os.path.join(ffdir, "ffmpeg")):
        opts["ffmpeg_location"] = ffdir
    with yt_dlp.YoutubeDL(opts) as y:
        info = y.extract_info(url, download=True)
        path = y.prepare_filename(info)
    base = os.path.splitext(path)[0]
    for ext in (".mp4", ".mkv", ".webm", os.path.splitext(path)[1]):
        if os.path.isfile(base + ext):
            progress(1.0, "Downloaded")
            return base + ext
    if done.get("file") and os.path.isfile(done["file"]):
        return done["file"]
    raise RuntimeError("The download finished but the file was not found.")


LINK = re.compile(r"^https?://\S+$")


def ask_and_download(parent, on_done):
    """Small window: paste a link, choose the quality, download; on_done(path) in the UI thread."""
    import tkinter as tk
    import customtkinter as ctk
    from tkinter import messagebox
    if not available():
        messagebox.showerror("YouTube", "The YouTube downloader (yt-dlp) is not installed in this copy.\n"
                                        "Use the latest ChauhanClipping-Windows.zip.")
        return
    w = ctk.CTkToplevel(parent)
    w.title("Download a video from a link")
    w.geometry("560x290")
    w.transient(parent.winfo_toplevel())
    ctk.CTkLabel(w, text="YouTube / Instagram / Facebook / X link:", anchor="w").pack(fill="x", padx=14, pady=(14, 2))
    ent = ctk.CTkEntry(w, placeholder_text="https://www.youtube.com/watch?v=...")
    ent.pack(fill="x", padx=14)
    try:
        clip = parent.clipboard_get()
        if LINK.match(clip.strip()):
            ent.insert(0, clip.strip())
    except Exception:
        pass
    q = tk.StringVar(value="Best up to 1080p")
    ctk.CTkOptionMenu(w, values=list(QUALITIES), variable=q).pack(anchor="w", padx=14, pady=8)
    bar = ctk.CTkProgressBar(w)
    bar.set(0)
    bar.pack(fill="x", padx=14, pady=4)
    st = ctk.CTkLabel(w, text="The video is saved in input_movies and opened in the editor.", anchor="w",
                      wraplength=520, justify="left")
    st.pack(fill="x", padx=14, pady=4)
    stop = threading.Event()
    row = ctk.CTkFrame(w, fg_color="transparent")
    row.pack(fill="x", padx=14, pady=8)
    state = {"busy": False}

    def ui(fn):
        try:
            w.after(0, fn)
        except Exception:
            pass

    def go():
        url = ent.get().strip()
        if not LINK.match(url):
            messagebox.showwarning("Link", "Please paste a full link (starting with https://).", parent=w)
            return
        state["busy"] = True
        btn.configure(state="disabled")
        stop.clear()

        def prog(f, t):
            ui(lambda: (bar.set(f) if f is not None else None, st.configure(text=t)))

        def work():
            try:
                path = download(url, QUALITIES[q.get()], prog, stop, lambda m: ui(lambda: st.configure(text=m)))
            except Exception as e:
                msg = str(e)
                ui(lambda: (st.configure(text=("Stopped." if stop.is_set() else "Download failed: " + msg[-300:])),
                            btn.configure(state="normal")))
                state["busy"] = False
                return
            state["busy"] = False
            ui(lambda: (w.destroy(), on_done(path)))
        threading.Thread(target=work, daemon=True).start()

    btn = ctk.CTkButton(row, text="Download and open", command=go)
    btn.pack(side="left")
    ctk.CTkButton(row, text="Stop", fg_color="#5A1A1A", hover_color="#7A2222", command=stop.set).pack(side="left", padx=8)
    w.protocol("WM_DELETE_WINDOW", lambda: (stop.set(), w.destroy()))
    w.after(200, ent.focus_set)
