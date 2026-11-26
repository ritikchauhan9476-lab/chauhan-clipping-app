"""Audio / subtitle tracks of a movie (like MKVToolNix): see every track, keep or remove each one, choose the main
(default) audio language, rename / re-label tracks and save a new file - copied, not re-encoded, so it takes
seconds and the quality stays exactly the same. A single track can also be saved on its own."""
import json
import os
import subprocess

import engine as E

LANGS = {"hin": "Hindi", "eng": "English", "tam": "Tamil", "tel": "Telugu", "mal": "Malayalam", "kan": "Kannada",
         "ben": "Bengali", "mar": "Marathi", "guj": "Gujarati", "pan": "Punjabi", "urd": "Urdu", "jpn": "Japanese",
         "kor": "Korean", "chi": "Chinese", "zho": "Chinese", "spa": "Spanish", "fre": "French", "fra": "French",
         "ger": "German", "deu": "German", "rus": "Russian", "ara": "Arabic", "ita": "Italian", "por": "Portuguese",
         "und": "unknown"}
TEXT_SUBS = {"subrip", "srt", "ass", "ssa", "webvtt", "mov_text", "text"}


def lang_name(code):
    code = (code or "").lower()
    return LANGS.get(code, code or "unknown")


def probe(movie):
    """All tracks: [{index, type ('video'/'audio'/'subtitle'/...), n (number inside its type), codec, channels,
    lang, title, default}]"""
    out = subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries",
         "stream=index,codec_type,codec_name,channels,width,height:stream_tags=language,title:stream_disposition=default",
         "-show_entries", "format=duration,format_name", "-of", "json", movie], creationflags=E.NOWIN)
    d = json.loads(out.decode("utf-8", "ignore"))
    res, count = [], {}
    for s in d.get("streams", []):
        t = s.get("codec_type", "")
        n = count.get(t, 0)
        count[t] = n + 1
        tags = s.get("tags") or {}
        res.append(dict(index=int(s["index"]), type=t, n=n, codec=s.get("codec_name", ""),
                        channels=int(s.get("channels") or 0), w=s.get("width"), h=s.get("height"),
                        lang=tags.get("language", tags.get("LANGUAGE", "")),
                        title=tags.get("title", tags.get("TITLE", "")),
                        default=bool((s.get("disposition") or {}).get("default"))))
    return res, float((d.get("format") or {}).get("duration") or 0)


def describe(t):
    if t["type"] == "audio":
        ch = {1: "mono", 2: "stereo", 6: "5.1", 8: "7.1"}.get(t["channels"], f"{t['channels']} ch")
        return f"Audio {t['n'] + 1}: {lang_name(t['lang'])} {('- ' + t['title']) if t['title'] else ''} ({t['codec']}, {ch})"
    if t["type"] == "subtitle":
        return f"Subtitle {t['n'] + 1}: {lang_name(t['lang'])} {('- ' + t['title']) if t['title'] else ''} ({t['codec']})"
    if t["type"] == "video":
        return f"Video: {t['codec']} {t.get('w')}x{t.get('h')}"
    return f"{t['type'].title()} {t['n'] + 1}: {t['codec']}"


def out_name(movie, suffix="tracks"):
    base, ext = os.path.splitext(movie)
    p = f"{base} ({suffix}){ext}"
    k = 2
    while os.path.exists(p):
        p = f"{base} ({suffix} {k}){ext}"
        k += 1
    return p


def build_cmd(movie, tracks, keep, main_audio, out, edits=None):
    """keep: set of stream indexes to keep. main_audio: index of the audio that becomes track 1 + default.
    edits: {index: {"lang": .., "title": ..}}. Video, attachments (fonts) and chapters are always kept."""
    edits = edits or {}
    ext = os.path.splitext(out)[1].lower()
    mp4 = ext in (".mp4", ".m4v", ".mov")
    vids = [t for t in tracks if t["type"] == "video"]
    auds = [t for t in tracks if t["type"] == "audio" and t["index"] in keep]
    subs = [t for t in tracks if t["type"] == "subtitle" and t["index"] in keep]
    if mp4:
        subs = [t for t in subs if t["codec"] in TEXT_SUBS]          # picture subtitles cannot go into MP4
    auds.sort(key=lambda t: (t["index"] != main_audio, t["index"]))
    cmd = ["ffmpeg", "-nostdin", "-y", "-v", "error", "-progress", "pipe:1", "-i", movie]
    for t in vids:
        cmd += ["-map", f"0:{t['index']}"]
    for t in auds + subs:
        cmd += ["-map", f"0:{t['index']}"]
    if not mp4:
        cmd += ["-map", "0:t?"]                                      # fonts of MKV subtitles
    cmd += ["-map_chapters", "0", "-c", "copy"]
    if mp4 and subs:
        cmd += ["-c:s", "mov_text"]
    for k, t in enumerate(auds):
        cmd += [f"-disposition:a:{k}", "default" if k == 0 else "0"]
        e = edits.get(t["index"]) or {}
        if e.get("lang") is not None:
            cmd += [f"-metadata:s:a:{k}", f"language={e['lang']}"]
        if e.get("title") is not None:
            cmd += [f"-metadata:s:a:{k}", f"title={e['title']}"]
            if mp4:
                cmd += [f"-metadata:s:a:{k}", f"handler_name={e['title']}"]
    for k, t in enumerate(subs):
        e = edits.get(t["index"]) or {}
        cmd += [f"-disposition:s:{k}", "0"]
        if e.get("lang") is not None:
            cmd += [f"-metadata:s:s:{k}", f"language={e['lang']}"]
        if e.get("title") is not None:
            cmd += [f"-metadata:s:s:{k}", f"title={e['title']}"]
    if mp4:
        cmd += ["-movflags", "+faststart"]
    return cmd + [out], len(auds), len(subs)


def run(cmd, duration, progress=None, stop=None):
    """Runs the copy; progress(fraction). Returns (ok, error text)."""
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, creationflags=E.NOWIN)
    for line in p.stdout:
        if stop is not None and stop.is_set():
            p.kill()
            return False, "stopped"
        if line.startswith("out_time_ms=") and duration > 0 and progress:
            try:
                progress(min(1.0, int(line.split("=")[1]) / 1e6 / duration))
            except ValueError:
                pass
    p.wait()
    err = p.stderr.read()
    return p.returncode == 0, err[-500:]


def save_track(movie, t, out_dir=None):
    """One track on its own: audio -> .mka (copied, any codec), subtitle -> .srt (text) or .mks."""
    base = os.path.splitext(os.path.basename(movie))[0]
    out_dir = out_dir or os.path.dirname(movie)
    lang = t["lang"] or "und"
    if t["type"] == "audio":
        out = os.path.join(out_dir, f"{base}.{lang}.audio{t['n'] + 1}.mka")
        cmd = ["-map", f"0:{t['index']}", "-c", "copy"]
    else:
        text = t["codec"] in TEXT_SUBS
        out = os.path.join(out_dir, f"{base}.{lang}.{t['n'] + 1}.{'srt' if text else 'mks'}")
        cmd = ["-map", f"0:{t['index']}", "-c:s", "srt" if text else "copy"]
    r = subprocess.run(["ffmpeg", "-nostdin", "-y", "-v", "error", "-i", movie] + cmd + [out], capture_output=True,
                       creationflags=E.NOWIN)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.decode(errors="ignore")[-300:])
    return out
