"""Viral Clips: turns a movie, a downloaded YouTube video or a running live stream into ready-to-post clips.

The work is done PART BY PART (10 min by default): the sound of one part is turned into words (Whisper on this PC,
the video's own captions, or a cloud speech service), the best moments are picked (built-in scoring, or an AI
service with your key: Gemini, Groq, OpenAI, Grok, Claude, DeepSeek, Qwen, OpenRouter, a local Ollama / LM Studio)
and every clip is exported at once with all the edits of the tab (colour, crop, overlays, text, effects, export
quality) plus word-by-word captions, a hook title, a speaker-following / facecam / interview layout, a cover
picture and the post text (title, description, hashtags). While part 1 is exported, part 2 is already listened to.

Only the engine lives here (no windows): viral_ui.py is the tab.
"""
import base64
import csv
import json
import math
import os
import re
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
import zipfile

import numpy as np

import engine as E
import scoring as SC

# ------------------------------------------------------------------ platforms
PLATFORMS = {
    "TikTok (9:16, 20-60 s)": dict(aspect="9:16", min=20, max=60, tags=["#tiktok", "#fyp", "#viral"]),
    "Instagram Reels (9:16, 15-90 s)": dict(aspect="9:16", min=15, max=90, tags=["#reels", "#instagram", "#viral"]),
    "YouTube Shorts (9:16, 20-60 s)": dict(aspect="9:16", min=20, max=60, tags=["#shorts", "#youtubeshorts"]),
    "YouTube Shorts long (9:16, up to 3 min)": dict(aspect="9:16", min=45, max=180, tags=["#shorts", "#youtubeshorts"]),
    "Facebook Reels (9:16, 15-90 s)": dict(aspect="9:16", min=15, max=90, tags=["#reels", "#facebookreels"]),
    "Moj / Josh (9:16, 15-60 s)": dict(aspect="9:16", min=15, max=60, tags=["#moj", "#josh", "#trending"]),
    "YouTube video (16:9, 1-5 min)": dict(aspect="16:9", min=60, max=300, tags=["#youtube", "#clip"]),
    "Instagram post (4:5)": dict(aspect="4:5", min=15, max=60, tags=["#instagram", "#viral"]),
    "Square (1:1)": dict(aspect="1:1", min=20, max=60, tags=["#viral", "#clip"]),
    "Xiaohongshu (3:4)": dict(aspect="3:4", min=20, max=120, tags=["#xiaohongshu"]),
    "Douyin (9:16)": dict(aspect="9:16", min=15, max=60, tags=["#douyin"]),
    "Bilibili (16:9)": dict(aspect="16:9", min=30, max=300, tags=["#bilibili"]),
}

# ------------------------------------------------------------------ AI services
PROVIDERS = {
    "offline": dict(label="Built-in (offline, no key)", kind="offline"),
    "gemini": dict(label="Google Gemini (free key: aistudio.google.com)", kind="gemini",
                   base="https://generativelanguage.googleapis.com/v1beta", model="gemini-2.5-flash"),
    "groq": dict(label="Groq (free key: console.groq.com)", kind="openai", base="https://api.groq.com/openai/v1",
                 model="llama-3.3-70b-versatile", stt="whisper-large-v3-turbo"),
    "openai": dict(label="OpenAI (ChatGPT)", kind="openai", base="https://api.openai.com/v1", model="gpt-4o-mini",
                   stt="whisper-1"),
    "xai": dict(label="xAI Grok", kind="openai", base="https://api.x.ai/v1", model="grok-3-mini"),
    "anthropic": dict(label="Anthropic Claude", kind="anthropic", base="https://api.anthropic.com/v1",
                      model="claude-haiku-5-5"),
    "deepseek": dict(label="DeepSeek", kind="openai", base="https://api.deepseek.com/v1", model="deepseek-chat"),
    "qwen": dict(label="Qwen (Alibaba DashScope)", kind="openai",
                 base="https://dashscope-intl.aliyuncs.com/compatible-mode/v1", model="qwen-plus"),
    "openrouter": dict(label="OpenRouter (many models, one key)", kind="openai", base="https://openrouter.ai/api/v1",
                       model="google/gemini-2.5-flash"),
    "ollama": dict(label="Ollama on this PC (no key)", kind="openai", base="http://localhost:11434/v1",
                   model="qwen2.5:3b"),
    "lmstudio": dict(label="LM Studio on this PC (no key)", kind="openai", base="http://localhost:1234/v1",
                     model="local-model"),
    "custom": dict(label="Other (OpenAI-compatible address)", kind="openai", base="http://localhost:8000/v1",
                   model="model"),
}
PROVIDER_BY_LABEL = {v["label"]: k for k, v in PROVIDERS.items()}

SPEECH = {
    "local": "Whisper on this PC (offline, Hindi + English)",
    "captions": "The video's own captions (YouTube subtitles)",
    "cloud": "Cloud speech-to-text (Groq / OpenAI key)",
    "gemini": "Gemini listens (Gemini key)",
}
SPEECH_BY_LABEL = {v: k for k, v in SPEECH.items()}

# ------------------------------------------------------------------ captions, hook, layouts
# per = words per caption page; active = colour of the word being spoken ("" = no highlight)
import captions as CAP
CAPTION_STYLES = CAP.STYLES          # every caption style of the software (captions.py)
CAPTION_POS = {"Bottom": 72.0, "Lower middle": 62.0, "Middle": 48.0, "Top": 16.0}
HOOK_STYLES = {
    "White box": dict(font="Arial Black", size=5.0, color="#111111", box=True, box_color="#FFFFFF", box_opacity=100,
                      box_pad=35, outline=0, anim_in="Pop", anim_in_dur=0.35),
    "Yellow box": dict(font="Arial Black", size=5.0, color="#111111", box=True, box_color="#FFD400", box_opacity=100,
                       box_pad=35, outline=0, anim_in="Pop", anim_in_dur=0.35),
    "Outline": dict(font="Impact", size=6.4, color="#FFFFFF", outline=8, anim_in="Slide down", anim_in_dur=0.35),
    "Red news bar": dict(font="Arial", bold=True, size=4.6, color="#FFFFFF", box=True, box_color="#C8102E",
                         box_opacity=95, box_pad=30, outline=0, anim_in="Slide left", anim_in_dur=0.35),
}
LAYOUTS = {
    "Normal": "Picture as set in Aspect & Crop",
    "Follow the speaker": "Vertical crop that follows the face of whoever is talking",
    "Facecam on top (gaming)": "The streamer's face cam above, the game below",
    "Interview (two people)": "Two people stacked: one in the top half, one in the bottom half",
}
LAYOUT_KEY = {"Follow the speaker": "speaker", "Facecam on top (gaming)": "facecam", "Interview (two people)": "interview"}


def tstr(t):
    t = max(0.0, float(t))
    return f"{int(t // 60):02d}:{t % 60:04.1f}"


def slug(t, n=40):
    t = re.sub(r'[\\/:*?"<>|#\n\r\t]+', " ", str(t or "")).strip()
    t = re.sub(r"\s+", " ", t)
    return t[:n].strip() or "clip"


def clip_file(base, number, title):
    return f"{base}_clip{int(number):02d}_{slug(title, 36).replace(' ', '_')}.mp4"


# ================================================================== talking to AI services
class AIError(RuntimeError):
    pass


def resolve(ai):
    ai = ai or {}
    p = PROVIDERS.get(ai.get("provider") or "offline", PROVIDERS["offline"])
    stt = ai.get("stt")
    return dict(kind=p["kind"], provider=ai.get("provider") or "offline",
                base=str(ai.get("base") or p.get("base", "")).rstrip("/"),
                model=str(ai.get("model") or p.get("model", "")).strip(),
                stt=(p.get("stt", "") if stt in (None, "") else str(stt)).strip(),
                key=str(ai.get("key") or "").strip())


def _post(url, body, headers, timeout=300):
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        txt = e.read().decode("utf-8", "replace")
        try:
            j = json.loads(txt)
            err = j.get("error")
            msg = (err.get("message") if isinstance(err, dict) else err) or j.get("message") or txt
        except Exception:
            msg = txt
        raise AIError(f"{e.code}: {str(msg)[:400]}")
    except urllib.error.URLError as e:
        raise AIError(f"cannot reach {url.split('?')[0]} ({e.reason})")


def parse_json(text):
    t = str(text or "").strip()
    t = re.sub(r"^\s*```(?:json)?", "", t, flags=re.I)
    t = re.sub(r"```\s*$", "", t).strip()
    try:
        return json.loads(t)
    except Exception:
        a, b = t.find("{"), t.rfind("}")
        if a >= 0 and b > a:
            return json.loads(t[a:b + 1])
    raise AIError("the AI did not answer in the expected form: " + t[:200])


class Usage:
    """How much AI one run used (shown in the tab: calls, tokens, minutes of audio)."""
    def __init__(self):
        self.calls = self.tin = self.tout = 0
        self.audio = 0.0
        self.lock = threading.Lock()

    def add(self, tin=0, tout=0, audio=0.0):
        with self.lock:
            self.calls += 1
            self.tin += int(tin or 0)
            self.tout += int(tout or 0)
            self.audio += float(audio or 0)

    def text(self):
        if not self.calls:
            return "AI used: nothing (built-in / offline)"
        a = f", {self.audio / 60:.1f} min of sound" if self.audio else ""
        return f"AI used: {self.calls} call(s), {self.tin:,} tokens in / {self.tout:,} out{a}"


def ask(ai, system, user, usage=None, json_mode=True):
    """One question to the AI service. Returns the parsed JSON (or the text)."""
    c = resolve(ai)
    if c["kind"] == "offline":
        raise AIError("no AI service chosen")
    if c["kind"] == "gemini":
        url = f"{c['base']}/models/{c['model']}:generateContent?key={urllib.request.quote(c['key'])}"
        body = {"systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": user}]}],
                "generationConfig": {"temperature": 0.4, **({"responseMimeType": "application/json"} if json_mode else {})}}
        _, txt = _post(url, json.dumps(body).encode(), {"Content-Type": "application/json"})
        d = json.loads(txt)
        um = d.get("usageMetadata") or {}
        if usage:
            usage.add(um.get("promptTokenCount"), um.get("candidatesTokenCount"))
        parts = (((d.get("candidates") or [{}])[0].get("content") or {}).get("parts") or [])
        text = "".join(p.get("text", "") for p in parts)
    elif c["kind"] == "anthropic":
        body = {"model": c["model"], "max_tokens": 4000, "temperature": 0.4, "system": system,
                "messages": [{"role": "user", "content": user}]}
        _, txt = _post(f"{c['base']}/messages", json.dumps(body).encode(),
                       {"Content-Type": "application/json", "x-api-key": c["key"], "anthropic-version": "2023-06-01"})
        d = json.loads(txt)
        u = d.get("usage") or {}
        if usage:
            usage.add(u.get("input_tokens"), u.get("output_tokens"))
        text = "".join(b.get("text", "") for b in (d.get("content") or []) if b.get("type") == "text")
    else:
        body = {"model": c["model"], "temperature": 0.4,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
        if json_mode and c["provider"] in ("openai", "groq", "xai", "deepseek", "qwen"):
            body["response_format"] = {"type": "json_object"}
        h = {"Content-Type": "application/json"}
        if c["key"]:
            h["Authorization"] = "Bearer " + c["key"]
        if c["provider"] == "openrouter":
            h["X-Title"] = "Chauhan Clipping"
        _, txt = _post(f"{c['base']}/chat/completions", json.dumps(body).encode(), h)
        d = json.loads(txt)
        u = d.get("usage") or {}
        if usage:
            usage.add(u.get("prompt_tokens"), u.get("completion_tokens"))
        text = (((d.get("choices") or [{}])[0].get("message") or {}).get("content")) or ""
    return parse_json(text) if json_mode else text


def test_key(ai):
    r = ask(ai, "You answer with JSON only.", 'Answer exactly {"ok": true}')
    return bool(isinstance(r, dict) and r.get("ok"))


def _multipart(fields, file_field, path, mime):
    bnd = "----cc" + uuid.uuid4().hex
    out = []
    for k, v in fields.items():
        for x in (v if isinstance(v, (list, tuple)) else [v]):
            out.append(f"--{bnd}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{x}\r\n".encode())
    with open(path, "rb") as f:
        data = f.read()
    out.append(f"--{bnd}\r\nContent-Disposition: form-data; name=\"{file_field}\"; filename=\"{os.path.basename(path)}\"\r\n"
               f"Content-Type: {mime}\r\n\r\n".encode() + data + b"\r\n")
    out.append(f"--{bnd}--\r\n".encode())
    return b"".join(out), f"multipart/form-data; boundary={bnd}"


# ================================================================== speech to text
def words_from_segments(segs):
    """Spread every sentence's time over its words (when the source has no word times)."""
    out = []
    for a, b, text in segs:
        ws = str(text).split()
        if not ws:
            continue
        b = max(a + 0.1, b)
        total = sum(len(w) + 1 for w in ws)
        t = a
        for w in ws:
            d = (b - a) * (len(w) + 1) / total
            out.append((w, t, t + d))
            t += d
    return out


def segments_from_words(words, max_gap=0.8, max_len=8.0):
    """Words -> sentence-like lines (new line at a pause, a sentence end, or after max_len seconds)."""
    segs, cur = [], []
    for w in words:
        if cur and (w[1] - cur[-1][2] > max_gap or w[2] - cur[0][1] > max_len):
            segs.append((cur[0][1], cur[-1][2], " ".join(x[0] for x in cur)))
            cur = []
        cur.append(w)
        if w[0].rstrip().endswith((".", "?", "!", "।")):
            segs.append((cur[0][1], cur[-1][2], " ".join(x[0] for x in cur)))
            cur = []
    if cur:
        segs.append((cur[0][1], cur[-1][2], " ".join(x[0] for x in cur)))
    return segs


TS = re.compile(r"(\d+):(\d\d):(\d\d)[.,](\d{3})|(\d\d):(\d\d)[.,](\d{3})")


def _ts(s):
    m = TS.search(s)
    if not m:
        return None
    if m.group(1) is not None:
        return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3)) + int(m.group(4)) / 1000
    return int(m.group(5)) * 60 + int(m.group(6)) + int(m.group(7)) / 1000


def parse_subtitles(path):
    """.vtt / .srt -> words [(word, start, end)]. YouTube's automatic captions carry a time for every word
    (<00:00:01.240><c> word</c>); their repeated 'rolling' lines are skipped."""
    raw = open(path, encoding="utf-8", errors="replace").read().replace("\r", "")
    blocks = re.split(r"\n\s*\n", raw)
    words, segs, last_line = [], [], ""
    for bl in blocks:
        lines = [x for x in bl.split("\n") if x.strip()]
        tl = next((i for i, x in enumerate(lines) if "-->" in x), None)
        if tl is None:
            continue
        a, b = (_ts(p) for p in lines[tl].split("-->")[:2])
        if a is None or b is None:
            continue
        body = lines[tl + 1:]
        if not body:
            continue
        timed = [x for x in body if "<c>" in x or re.search(r"<\d\d:\d\d", x)]
        if timed:
            for x in timed:
                parts = re.split(r"<(\d\d:\d\d:\d\d\.\d{3}|\d\d:\d\d\.\d{3})>", x)
                t = a
                items = [(t, parts[0])]
                for k in range(1, len(parts) - 1, 2):
                    items.append((_ts(parts[k]), parts[k + 1]))
                for k, (t0, txt) in enumerate(items):
                    w = re.sub(r"<[^>]+>", "", txt).strip()
                    if not w:
                        continue
                    t1 = items[k + 1][0] if k + 1 < len(items) else b
                    for j, ww in enumerate(w.split()):
                        words.append((ww, t0, max(t0 + 0.05, t1)))
            continue
        text = re.sub(r"<[^>]+>", "", " ".join(body)).strip()
        text = re.sub(r"\{\\[^}]*\}", "", text)
        if not text or text == last_line or b - a < 0.05:
            continue
        if last_line and text.startswith(last_line):
            text = text[len(last_line):].strip()
        last_line = " ".join(body).strip()
        if text:
            segs.append((a, b, text))
    if not words:
        words = words_from_segments(segs)
    words.sort(key=lambda w: w[1])
    return words


def find_subtitles(movie):
    """Subtitle files that belong to this video (downloaded next to it): '<name>.<lang>.vtt' / .srt."""
    base = os.path.splitext(movie)[0]
    d = os.path.dirname(movie) or "."
    out = []
    try:
        for f in os.listdir(d):
            p = os.path.join(d, f)
            if p.startswith(base + ".") and f.lower().endswith((".vtt", ".srt")):
                out.append(p)
    except OSError:
        pass
    pref = lambda p: (0 if ".hi" in p else 1 if ".en" in p else 2, len(p))
    return sorted(out, key=pref)


def extract_audio(movie, a, length, out, codec="aac"):
    args = ["ffmpeg", "-nostdin", "-y", "-v", "error", "-ss", f"{a:.3f}", "-t", f"{length:.3f}", "-i", movie,
            "-map", "0:a:0", "-vn", "-ac", "1", "-ar", "16000"]
    args += ["-c:a", "aac", "-b:a", "32k"] + (["-f", "adts"] if out.endswith(".aac") else []) + [out]
    r = subprocess.run(args, capture_output=True, creationflags=E.NOWIN)
    if r.returncode != 0:
        raise RuntimeError("could not read the sound: " + r.stderr.decode(errors="ignore")[-300:])
    return out


class Listener:
    """Speech to text for one time range. Returns words [(word, start, end)] in movie seconds."""
    def __init__(self, speech, ai, lang="", whisper_model="small", log=print, usage=None, tmp=None):
        self.speech, self.ai, self.lang = speech, ai or {}, (lang or "").strip()
        self.whisper_model, self.log, self.usage = whisper_model, log, usage or Usage()
        self.tmp = tmp or tempfile.gettempdir()
        self.model = None
        self.subs = None
        self.lock = threading.Lock()

    def _whisper(self):
        if self.model is None:
            from faster_whisper import WhisperModel
            src = E.whisper_source(self.whisper_model)
            dev = "cpu"
            try:
                if E.setup_cuda_paths():
                    self.model = WhisperModel(src, device="cuda", compute_type="int8_float16")
                    dev = "GPU"
            except Exception:
                self.model = None
            if self.model is None:
                self.model = WhisperModel(src, device="cpu", compute_type="int8")
            self.log(f"Whisper '{self.whisper_model}' ready ({dev}).")
        return self.model

    def listen(self, movie, a, b):
        sp = self.speech
        if sp == "captions":
            if self.subs is None:
                files = find_subtitles(movie)
                if not files:
                    raise RuntimeError("this video has no caption file next to it (download it with 'YouTube link' "
                                       "to get its captions), choose another speech option")
                self.log(f"Using the video's captions: {os.path.basename(files[0])}")
                self.subs = parse_subtitles(files[0])
            return [w for w in self.subs if a - 0.5 <= w[1] < b]
        if sp == "local":
            with self.lock:
                model = self._whisper()
                audio = E.read_audio(movie, a, b - a)
                if len(audio) < 16000:
                    return []
                lang = None if self.lang in ("", "auto") else self.lang
                segs, _ = model.transcribe(audio, language=lang, vad_filter=True, beam_size=1, word_timestamps=True,
                                           condition_on_previous_text=False)
                out = []
                for s in segs:
                    if s.words:
                        out += [(w.word.strip(), a + w.start, a + w.end) for w in s.words if w.word.strip()]
                    elif s.text.strip():
                        out += [(w, a + x, a + y) for w, x, y in words_from_segments([(s.start, s.end, s.text.strip())])]
                return out
        c = resolve(self.ai)
        if sp == "gemini" or (sp == "cloud" and c["kind"] == "gemini"):
            if c["kind"] != "gemini":
                raise RuntimeError("'Gemini listens' needs the AI service Google Gemini and its key")
            f = os.path.join(self.tmp, f"vc_listen_{uuid.uuid4().hex[:8]}.aac")
            try:
                extract_audio(movie, a, b - a, f)
                data = base64.b64encode(open(f, "rb").read()).decode()
            finally:
                _rm(f)
            prompt = ("Transcribe this audio exactly as spoken, in its own language (Hindi in Devanagari script, "
                      "English in Latin). Return JSON {\"segments\":[{\"start\":seconds,\"end\":seconds,\"text\":\"...\"}]} "
                      "with one segment per sentence or short phrase (2-8 seconds), times in seconds from the start "
                      "of the audio. Do not translate, do not summarise.")
            url = f"{c['base']}/models/{c['model']}:generateContent?key={urllib.request.quote(c['key'])}"
            body = {"contents": [{"role": "user", "parts": [{"inline_data": {"mime_type": "audio/aac", "data": data}},
                                                             {"text": prompt}]}],
                    "generationConfig": {"temperature": 0, "responseMimeType": "application/json"}}
            _, txt = _post(url, json.dumps(body).encode(), {"Content-Type": "application/json"}, timeout=600)
            d = json.loads(txt)
            um = d.get("usageMetadata") or {}
            self.usage.add(um.get("promptTokenCount"), um.get("candidatesTokenCount"), b - a)
            parts = (((d.get("candidates") or [{}])[0].get("content") or {}).get("parts") or [])
            segs = parse_json("".join(p.get("text", "") for p in parts)).get("segments") or []
            segs = [(a + float(s.get("start", 0)), a + float(s.get("end", 0)), str(s.get("text", ""))) for s in segs]
            return words_from_segments(segs)
        # OpenAI-style speech to text (Groq / OpenAI / custom)
        if not c["stt"]:
            raise RuntimeError(f"{PROVIDERS[c['provider']]['label']} has no speech-to-text: choose Whisper on this PC")
        f = os.path.join(self.tmp, f"vc_listen_{uuid.uuid4().hex[:8]}.m4a")
        try:
            extract_audio(movie, a, b - a, f)
            fields = {"model": c["stt"], "response_format": "verbose_json",
                      "timestamp_granularities[]": ["word", "segment"]}
            if self.lang and self.lang != "auto":
                fields["language"] = self.lang
            body, ctype = _multipart(fields, "file", f, "audio/mp4")
        finally:
            _rm(f)
        h = {"Content-Type": ctype}
        if c["key"]:
            h["Authorization"] = "Bearer " + c["key"]
        _, txt = _post(f"{c['base']}/audio/transcriptions", body, h, timeout=600)
        d = json.loads(txt)
        self.usage.add(0, 0, b - a)
        ws = [(str(w.get("word", "")).strip(), a + float(w["start"]), a + float(w["end"]))
              for w in (d.get("words") or []) if str(w.get("word", "")).strip()]
        if not ws:
            segs = [(a + float(s["start"]), a + float(s["end"]), str(s.get("text", "")).strip()) for s in (d.get("segments") or [])]
            ws = words_from_segments(segs or [(a, b, d.get("text", ""))])
        return ws


def _rm(p):
    try:
        os.remove(p)
    except OSError:
        pass


# ================================================================== choosing the moments
PICK_SYSTEM = ("You are a top short-form video editor (TikTok, Reels, YouTube Shorts). You find the moments of a video "
               "that make people stop scrolling and watch to the end: strong emotion, a punchline, a surprising fact, "
               "drama, a clear story with a payoff, a quotable line. Each clip must make sense on its own, start at the "
               "beginning of a sentence and end after a finished sentence. Answer with JSON only.")


def _clean_tags(tags, extra=()):
    if isinstance(tags, str):
        tags = re.split(r"[\s,]+", tags)
    out = []
    for h in list(tags or []) + list(extra):
        h = str(h).strip()
        if not h:
            continue
        h = h if h.startswith("#") else "#" + h
        h = re.sub(r"\s+", "", h)
        if h.lower() not in [x.lower() for x in out]:
            out.append(h)
    return out[:12]


def pick_ai(ai, lines, o, a, b, usage, avoid=()):
    focus = o.get("focus") or "the most viral moments"
    user = (f"Transcript of a part of \"{o.get('title', 'video')}\" (times in seconds; the speech may be Hindi, "
            f"English or mixed):\n" + "\n".join(f"[{s:.1f}-{e:.1f}] {t}" for s, e, t in lines) +
            f"\n\nFind the {o['count']} best clips for {o['platform']} ({focus}). Every clip {o['min']:.0f}-"
            f"{o['max']:.0f} seconds long, inside {a:.0f}-{b:.0f}." +
            (f" Do not use these times again: {', '.join(f'{x:.0f}-{y:.0f}' for x, y in avoid)}." if avoid else "") +
            f" Write titles, hooks, descriptions and hashtags in "
            f"{o.get('text_lang') or 'the language of the speech (Hindi in Devanagari, or Hinglish if mixed)'}."
            "\nReturn {\"clips\":[{\"start\":seconds,\"end\":seconds,\"score\":1-100,\"title\":\"short catchy title\","
            "\"hook\":\"3-7 word hook shown at the start\",\"description\":\"1-2 sentences for the post\","
            "\"hashtags\":[\"#tag\"],\"category\":\"Funny / Emotional / Drama / Fact / Story / Action\","
            "\"reason\":\"why it works\"}]} best first.")
    r = ask(ai, PICK_SYSTEM, user, usage)
    out = []
    for c in (r.get("clips") or []) if isinstance(r, dict) else []:
        try:
            s, e = float(c["start"]), float(c["end"])
        except (KeyError, TypeError, ValueError):
            continue
        if e > s:
            out.append(dict(start=s, end=e, score=float(c.get("score") or 50), title=str(c.get("title") or "").strip(),
                            hook=str(c.get("hook") or "").strip(), description=str(c.get("description") or "").strip(),
                            hashtags=_clean_tags(c.get("hashtags")), category=str(c.get("category") or "").strip(),
                            reason=str(c.get("reason") or "").strip()))
    return out


STOP = set("the a an and or but to of in on at is are was were be it this that i you he she we they my your me "
           "है हैं था थी थे का की के को में से पर और भी तो ही ये वो यह वह मैं तुम आप हम क्या नहीं ना हाँ हां".split())


def offline_texts(c, words, movie_title):
    """Title, hook, description and hashtags without an AI: from the clip's own words."""
    ws = [w for w in words if c["start"] <= w[1] < c["end"]]
    text = " ".join(w[0] for w in ws).strip()
    sents = [x.strip() for x in re.split(r"(?<=[.?!।])\s+", text) if x.strip()]
    first = sents[0] if sents else text
    title = " ".join(first.split()[:9]).rstrip(",;:") or slug(movie_title)
    hook = " ".join(first.split()[:6]).rstrip(",;:.")
    from collections import Counter
    cnt = Counter(t for t in SC.tokenize(text) if len(t) > 3 and t not in STOP)
    tags = ["#" + t for t, _ in cnt.most_common(4)]
    mt = re.sub(r"[^\w]+", "", movie_title.split("[")[0])[:24]
    return dict(title=title[:80], hook=hook[:60], description=" ".join(sents[:2])[:220],
                hashtags=_clean_tags(tags + ([f"#{mt}"] if mt else [])))


def pick_offline(words, o, a, b, audio=None, avoid=()):
    """Built-in scoring (no AI service): funny / emotional / relatable words, loud peaks, pace, hook, finished
    sentence - the same scoring as the AI Clipping tab. Without words: the most talking + loudest windows."""
    segs = [SC.Seg(s, e, t) for s, e, t in segments_from_words(words)]
    out, taken = [], list(avoid)
    if len(segs) >= 2:
        if audio is None or not len(audio):
            audio = np.ones(int(16000 * (b - a)), dtype=np.float32) * 0.05
        rms = SC.rms_frames(audio)
        med = float(np.median(rms[rms > 1e-4])) if np.any(rms > 1e-4) else 1e-3
        cands = [SC.score_window(segs, i, j, a, rms, med, o.get("focus_offline", "Funny + Emotional"))
                 for i, j in SC.make_candidates(segs, o["min"], o["max"])]
        cands = [c for c in cands if c["start"] >= a - 1 and c["end"] <= b + 1]
        cands.sort(key=lambda c: -c["score"])
        for c in cands:
            if len(out) >= o["count"]:
                break
            if c["score"] < o.get("min_score", 0) or SC.overlaps(c["start"], c["end"], taken):
                continue
            taken.append((c["start"], c["end"]))
            out.append(dict(start=c["start"], end=c["end"], score=round(c["score"]), category=c["category"],
                            reason=c["reason"]))
        return out
    # no words at all: loudness only
    if audio is None or not len(audio):
        return []
    L = min(o["max"], max(o["min"], (o["min"] + o["max"]) / 2))
    hop = 0.5
    rms = SC.rms_frames(audio, hop=hop)
    db = 20 * np.log10(rms + 1e-9)
    win = max(1, int(L / hop))
    if len(db) < win:
        return []
    sc = np.convolve(np.clip(db + 60, 0, None), np.ones(win), "valid") / win
    for i in np.argsort(-sc)[::3]:
        if len(out) >= o["count"]:
            break
        s = a + i * hop
        if SC.overlaps(s, s + L, taken):
            continue
        taken.append((s, s + L))
        out.append(dict(start=s, end=s + L, score=round(float(sc[i])), category="Loud", reason="most talking / loudest"))
    return out


def snap_to_words(c, words, lo, hi, mn, mx):
    """Clip edges onto words: start at a word, end after a finished word (+ a breath)."""
    s, e = max(lo, c["start"]), min(hi, c["end"])
    if words:
        first = next((w for w in words if w[2] > s), None)
        if first:
            s = max(lo, min(s, first[1]) - 0.15)
        last = next((w for w in reversed(words) if w[1] < e), None)
        if last:
            e = min(hi, last[2] + 0.35)
        # end after a finished sentence when one is close
        ends = [w[2] for w in words if s + mn <= w[2] <= min(hi, s + mx) and w[0].rstrip().endswith((".", "?", "!", "।"))]
        if ends and not any(abs(x - e) < 0.05 for x in ends):
            near = min(ends, key=lambda x: abs(x - e))
            if abs(near - e) < 4.0:
                e = min(hi, near + 0.35)
    if e - s < mn:
        e = min(hi, s + mn)
    if e - s > mx:
        e = s + mx
    return dict(c, start=round(s, 3), end=round(e, 3))


def caption_events(words, a, b, style, map_t=None):
    """Word-by-word caption pages of one clip: [(t0, t1, text)] in clip seconds. The spoken word gets the
    highlight colour ({c=#RRGGBB}word{/c}); `per` words per page."""
    st = CAPTION_STYLES.get(style, style) if isinstance(style, str) else style
    per = max(1, int(st.get("per", 3)))
    act = st.get("active") or ""
    ws = [w for w in words if w[2] > a and w[1] < b]
    if map_t:
        ws2 = []
        for w, s, e in ws:
            ms, me = map_t(s), map_t(e)
            if ms is None and me is None:
                continue
            ws2.append((w, ms if ms is not None else me - 0.2, me if me is not None else ms + 0.2))
        ws = ws2
    else:
        ws = [(w, s - a, e - a) for w, s, e in ws]
    if st.get("upper"):
        ws = [(w.upper(), s, e) for w, s, e in ws]
    ev = []
    for i in range(0, len(ws), per):
        g = ws[i:i + per]
        if act:
            for k, (w, s, e) in enumerate(g):
                t0 = max(0.0, s)
                t1 = (g[k + 1][1] if k + 1 < len(g) else g[-1][2] + 0.25)
                text = " ".join(f"{{c={act}}}{x[0]}{{/c}}" if j == k else x[0] for j, x in enumerate(g))
                ev.append([t0, max(t0 + 0.05, t1), text])
        else:
            ev.append([max(0.0, g[0][1]), g[-1][2] + 0.25, " ".join(x[0] for x in g)])
    for i in range(len(ev) - 1):
        if ev[i][1] > ev[i + 1][0]:
            ev[i][1] = ev[i + 1][0]
    return [tuple(e) for e in ev if e[1] - e[0] > 0.02]


def caption_item(style, pos_y, text):
    st = CAPTION_STYLES.get(style, style) if isinstance(style, str) else style
    t = {k: v for k, v in st.items() if k in E.TEXT_DEFAULT}
    t.update(text=text, pos="Custom", x=50, y=pos_y, hcenter=True, layer=99)
    return t


def hook_item(style, text):
    st = HOOK_STYLES.get(style, HOOK_STYLES["White box"])
    t = {k: v for k, v in st.items() if k in E.TEXT_DEFAULT}
    t.update(text=text, pos="Top-Center", hcenter=True, layer=100)
    return t


def plan_parts(duration, part_sec, start=0.0, end=None):
    end = duration if not end or end > duration else end
    out, t = [], max(0.0, float(start))
    while t < end - 1:
        b = min(end, t + part_sec)
        if end - b < part_sec * 0.25:
            b = end
        out.append((round(t, 3), round(b, 3)))
        t = b
    return out


# ================================================================== faces and layouts
_CASCADE = None


def _cascade():
    global _CASCADE
    if _CASCADE is None:
        import cv2
        for d in (getattr(getattr(cv2, "data", None), "haarcascades", "") or "", os.path.join(E.BASE, "models")):
            p = os.path.join(d, "haarcascade_frontalface_default.xml")
            if os.path.isfile(p):
                c = cv2.CascadeClassifier(p)
                if not c.empty():
                    _CASCADE = c
                    break
        if _CASCADE is None:
            raise RuntimeError("the face model (haarcascade_frontalface_default.xml) is missing")
    return _CASCADE


def faces_available():
    try:
        _cascade()
        return True
    except Exception:
        return False


def sample_faces(movie, a, b, step=1.0, width=480, info=None):
    """Faces in one time range, sampled every `step` seconds: [(t, [(cx, cy, w, h), ...])] in fractions of the
    frame (0-1). Only this range of the movie is read."""
    import cv2
    info = info or E.probe_info(movie)
    W = width
    H = max(2, int(round(width * info["h"] / max(1, info["w"]) / 2)) * 2)
    cmd = ["ffmpeg", "-nostdin", "-v", "error", "-ss", f"{a:.3f}", "-t", f"{max(0.5, b - a):.3f}", "-i", movie,
           "-an", "-vf", f"fps=1/{step:g},scale={W}:{H},format=gray", "-f", "rawvideo", "-"]
    raw = subprocess.run(cmd, capture_output=True, creationflags=E.NOWIN).stdout
    n = len(raw) // (W * H)
    frames = np.frombuffer(raw[:n * W * H], dtype=np.uint8).reshape(n, H, W) if n else []
    cas = _cascade()
    out = []
    for i, fr in enumerate(frames):
        fr = cv2.equalizeHist(fr)
        found = cas.detectMultiScale(fr, scaleFactor=1.1, minNeighbors=5, minSize=(max(14, W // 30), max(14, W // 30)))
        out.append((a + i * step, [((x + w / 2) / W, (y + h / 2) / H, w / W, h / H) for x, y, w, h in found]))
    return out


def plan_speaker(samples):
    """Crop centre (x) over time that follows the biggest face, smoothed. None when no face is seen."""
    xs, prev = [], None
    seen = 0
    for t, fs in samples:
        if fs:
            seen += 1
            if prev is not None:      # stay with the face nearest to the last one, unless another is much bigger
                f = max(fs, key=lambda f: f[2] * f[3] - 0.5 * abs(f[0] - prev) * f[2])
            else:
                f = max(fs, key=lambda f: f[2] * f[3])
            prev = f[0]
        xs.append((t, prev))
    if seen < max(1, len(samples) // 5):
        return None
    first = next(x for _, x in xs if x is not None)
    vals = []
    for t, x in xs:
        x = first if x is None else x
        first = x
        vals.append((t, x))
    sm, cur = [], vals[0][1]                 # smooth: the camera moves, it does not jump
    for t, x in vals:
        cur = cur + 0.45 * (x - cur)
        sm.append((t, round(cur, 4)))
    keys = [sm[0]]
    for t, x in sm[1:]:
        if abs(x - keys[-1][1]) > 0.025:
            keys.append((t, x))
    if keys[-1][0] != sm[-1][0]:
        keys.append(sm[-1])
    while len(keys) > 40:
        keys = keys[::2] + ([keys[-1]] if len(keys) % 2 == 0 else [])
    return dict(mode="speaker", keys=keys)


def plan_facecam(samples):
    """A small face that stays in the same place (a streamer's face cam): its box. None when there is none."""
    small = [f for _, fs in samples for f in fs if f[2] < 0.25]
    if len(small) < max(2, len(samples) // 3):
        return None
    cx = float(np.median([f[0] for f in small]))
    cy = float(np.median([f[1] for f in small]))
    near = [f for f in small if abs(f[0] - cx) < 0.08 and abs(f[1] - cy) < 0.08]
    if len(near) < max(2, len(samples) // 3):
        return None
    fw = float(np.median([f[2] for f in near]))
    fh = float(np.median([f[3] for f in near]))
    w, h = min(0.6, fw * 2.8), min(0.7, fh * 2.6)
    x, y = min(max(0.0, cx - w / 2), 1 - w), min(max(0.0, cy - h / 2 + fh * 0.15), 1 - h)
    return dict(mode="facecam", cam=[round(x, 4), round(y, 4), round(w, 4), round(h, 4)])


def plan_interview(samples):
    """Two people side by side: the centre of each. None when there are not two."""
    pts = [(f[0], f[1]) for _, fs in samples for f in fs if f[2] > 0.04]
    if len(pts) < 4:
        return None
    xs = np.array([p[0] for p in pts])
    c1, c2 = float(xs.min()), float(xs.max())
    for _ in range(10):
        g1 = [p for p in pts if abs(p[0] - c1) <= abs(p[0] - c2)]
        g2 = [p for p in pts if abs(p[0] - c1) > abs(p[0] - c2)]
        if not g1 or not g2:
            return None
        c1, c2 = float(np.mean([p[0] for p in g1])), float(np.mean([p[0] for p in g2]))
    if abs(c2 - c1) < 0.2 or min(len(g1), len(g2)) < max(2, len(samples) // 6):
        return None
    y1, y2 = float(np.mean([p[1] for p in g1])), float(np.mean([p[1] for p in g2]))
    return dict(mode="interview", faces=[[round(c1, 4), round(y1, 4)], [round(c2, 4), round(y2, 4)]])


def plan_layout(movie, a, b, mode, info=None, log=None, cam_box=None):
    """mode: speaker / facecam / interview. Returns the layout dict for engine.build_command (or None)."""
    if mode == "facecam" and cam_box:
        return dict(mode="facecam", cam=list(cam_box))
    if not faces_available():
        if log:
            log("Face finding is not available in this copy (OpenCV missing): normal picture.")
        return None
    step = max(0.5, min(2.0, (b - a) / 60))
    samples = sample_faces(movie, a, b, step, info=info)
    lay = {"speaker": plan_speaker, "facecam": plan_facecam, "interview": plan_interview}[mode](samples)
    if lay is None and mode == "interview":
        lay = plan_speaker(samples)
    if lay is None and log:
        log(f"  {tstr(a)}: no {'face cam' if mode == 'facecam' else 'face'} found - normal picture for this clip.")
    return lay


# ================================================================== the clip's extra settings
def clip_extras(clip, o):
    """Settings added on top of the tab's own settings for one clip (captions, hook, layout, retention boost)."""
    ex = {}
    if o.get("captions") and clip.get("words"):
        ex["_capwords"] = [list(w) for w in clip["words"]]
        ex["_capstyle"] = o.get("cap_style") or next(iter(CAPTION_STYLES))
        ex["_cappos"] = CAPTION_POS.get(o.get("cap_pos"), 72.0)
    hook = (clip.get("hook") or "").strip()
    if o.get("hook") and hook:
        ex["_hook"] = dict(text=hook, style=o.get("hook_style") or "White box", sec=float(o.get("hook_sec", 3) or 3))
    mode = LAYOUT_KEY.get(o.get("layout") or "Normal")
    if mode:
        lay = clip.get("layout")
        if lay and lay.get("req") == mode and lay.get("cam_req") == (o.get("cam_box") or None):
            if lay.get("mode") != "none":
                ex["_layout"] = lay                      # found when the clip was found
        else:
            ex["_layout_req"] = dict(mode=mode, cam=o.get("cam_box") or None)
    b = o.get("boost") or {}
    if b:
        ex["_boost"] = dict(b)
    return ex


def post_text(clip, movie, platform_tags=()):
    tags = _clean_tags(clip.get("hashtags") or [], platform_tags)
    lines = [clip.get("title") or "", "", clip.get("description") or "", "", " ".join(tags), "",
             f"(from {os.path.basename(movie)}  {tstr(clip['start'])} - {tstr(clip['end'])}  score "
             f"{int(clip.get('score') or 0)}{'  -  ' + clip['reason'] if clip.get('reason') else ''})"]
    return "\n".join(lines).strip() + "\n"


def make_kit(video, clip, movie, platform_tags=(), zip_kit=False):
    """Cover picture (_cover.jpg), post text (_post.txt) and, if asked, a ZIP with all three."""
    base = os.path.splitext(video)[0]
    cover = base + "_cover.jpg"
    try:
        d = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", video],
                                 capture_output=True, text=True, creationflags=E.NOWIN).stdout.strip() or 2)
    except ValueError:
        d = 2.0
    subprocess.run(["ffmpeg", "-nostdin", "-y", "-v", "error", "-ss", f"{min(1.2, d / 2):.2f}", "-i", video,
                    "-frames:v", "1", "-q:v", "3", cover], capture_output=True, creationflags=E.NOWIN)
    txt = base + "_post.txt"
    with open(txt, "w", encoding="utf-8") as f:
        f.write(post_text(clip, movie, platform_tags))
    out = dict(cover=cover if os.path.isfile(cover) else "", post=txt)
    if zip_kit:
        z = base + "_kit.zip"
        with zipfile.ZipFile(z, "w", zipfile.ZIP_STORED) as zf:
            for p in (video, out["cover"], txt):
                if p and os.path.isfile(p):
                    zf.write(p, os.path.basename(p))
        out["zip"] = z
    return out


def append_csv(folder, clip, file):
    p = os.path.join(folder, "clips.csv")
    new = not os.path.exists(p)
    with open(p, "a", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["file", "start", "end", "score", "category", "title", "hook", "hashtags", "reason"])
        w.writerow([os.path.basename(file), f"{clip['start']:.1f}", f"{clip['end']:.1f}", int(clip.get("score") or 0),
                    clip.get("category", ""), clip.get("title", ""), clip.get("hook", ""),
                    " ".join(clip.get("hashtags") or []), clip.get("reason", "")])


def export_clip(runner, movie, clip, settings, o, out_dir, base, info=None, items_fn=None, log=print):
    """Exports one clip with every edit of the tab + the clip's captions / hook / layout, then its cover, post text
    (and ZIP kit). Returns the file path or None. runner: an engine.Runner (it can be stopped)."""
    os.makedirs(out_dir, exist_ok=True)
    info = info or E.probe_info(movie)
    ovs, txs = items_fn(clip) if items_fn else ([], [])
    S = dict(settings, overlays=list(ovs), texts=list(txs))
    S.update(clip_extras(clip, o))
    req = S.pop("_layout_req", None)
    if req:
        lay = plan_layout(movie, clip["start"], clip["end"], req["mode"], info, log, req.get("cam"))
        clip["layout"] = dict(lay or {"mode": "none"}, req=req["mode"], cam_req=req.get("cam"))
        if lay:
            S["_layout"] = lay
    S = E.sanitize(S)
    if not hasattr(runner, "_crop"):
        runner._crop = E.detect_crop(movie, info["duration"]) if S["auto_crop"] else None
    file = os.path.join(out_dir, clip_file(base, clip["n"], clip.get("title")))
    if not runner.cut(movie, clip["start"], clip["end"] - clip["start"], file, info, runner._crop, S):
        return None
    tags = (PLATFORMS.get(o.get("platform")) or {}).get("tags", [])
    kit = make_kit(file, clip, movie, tags if o.get("platform_tags", True) else (), bool(o.get("zip_kit")))
    clip.update(cover=kit.get("cover", ""), post=kit.get("post", ""), zip=kit.get("zip", ""))
    append_csv(out_dir, clip, file)
    return file


# ================================================================== live streams
class LiveRecorder:
    """Records a running live stream (YouTube, Twitch, Kick ... through yt-dlp) into a .ts file that keeps
    growing; `seconds` is how much is recorded. The Viral Clips job clips it part by part while it records."""
    def __init__(self, url, out, log=print):
        self.url, self.out, self.log = url, out, log
        self.seconds = 0.0
        self.proc = None
        self.error = ""
        self.done = threading.Event()

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        try:
            import yt_dlp
            import ytdl
            ytdl._env_path()
            with yt_dlp.YoutubeDL({"quiet": True, "noplaylist": True,
                                   "format": "b[height<=1080]/bv*[height<=1080]+ba/b"}) as y:
                info = y.extract_info(self.url, download=False)
            fmts = info.get("requested_formats") or [info]
            urls = [f.get("url") for f in fmts if f.get("url")]
            hdrs = (fmts[0].get("http_headers") or info.get("http_headers") or {})
            if not urls:
                raise RuntimeError("no stream address found")
            self.log(f"Recording live: {info.get('title', '')[:80]}")
            cmd = ["ffmpeg", "-nostdin", "-y", "-v", "error", "-progress", "pipe:1"]
            for u in urls:
                if hdrs:
                    cmd += ["-headers", "".join(f"{k}: {v}\r\n" for k, v in hdrs.items())]
                cmd += ["-i", u]
            if len(urls) > 1:
                cmd += ["-map", "0:v:0", "-map", "1:a:0"]
            cmd += ["-c", "copy", "-f", "mpegts", self.out]
            self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                         creationflags=E.NOWIN)
            for line in self.proc.stdout:
                if line.startswith("out_time_ms="):
                    try:
                        self.seconds = max(self.seconds, int(line.split("=")[1]) / 1e6)
                    except ValueError:
                        pass
            self.proc.wait()
            if self.proc.returncode not in (0, 255, None) and self.seconds < 5:
                self.error = (self.proc.stderr.read() or "")[-400:]
        except Exception as e:
            self.error = str(e)[:400]
        finally:
            self.done.set()

    def stop(self):
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.stdin and self.proc.stdin.close()
            except Exception:
                pass
            self.proc.terminate()

    @property
    def alive(self):
        return not self.done.is_set()


# ================================================================== the job
class ViralJob:
    """Finds (and optionally exports) the clips of a movie, part by part.

    opts: platform, count, min, max, part_sec, start, end, speech, lang, whisper_model, text_lang, focus,
          min_score, captions, cap_style, cap_pos, hook, hook_style, layout, cam_box, boost, title
    on_clip(clip) is called for every clip (in this worker thread) - with clip['file'] when it was exported.
    export(clip) -> file path or None: exports one clip (called in this worker thread) when auto-export is on.
    live: a LiveRecorder - the movie keeps growing and is clipped while it records.
    cache: {(a, b): words} - parts already listened to (Find more uses them again)."""

    def __init__(self, movie, opts, ai, log=print, progress=None, on_clip=None, export=None, live=None,
                 cache=None, avoid=(), tmp=None, first_number=1):
        self.movie, self.o, self.ai = movie, dict(opts), dict(ai or {})
        self.log = log
        self.progress = progress or (lambda f, t: None)
        self.on_clip = on_clip or (lambda c: None)
        self.export = export
        self.live = live
        self.cache = cache if cache is not None else {}
        self.avoid = [tuple(x) for x in avoid]
        self.tmp = tmp or tempfile.gettempdir()
        self.usage = Usage()
        self.stop_flag = False
        self.found = []
        self.number = first_number
        self.listener = Listener(self.o.get("speech", "local"), self.ai, self.o.get("lang", ""),
                                 self.o.get("whisper_model", "small"), log, self.usage, self.tmp)
        self.info = None

    def stop(self):
        self.stop_flag = True
        if self.live:
            self.live.stop()

    # ---- one part
    def hear(self, a, b):
        key = (round(a, 3), round(b, 3))
        if key in self.cache:
            return self.cache[key]
        try:
            words = self.listener.listen(self.movie, a, b)
        except Exception as e:
            self.log(f"Speech to text failed for {tstr(a)}-{tstr(b)}: {str(e)[:300]}")
            if self.o.get("speech") == "local":
                words = None
            else:
                raise
        if words is not None:
            self.cache[key] = words
        return words or []

    def choose(self, a, b, words):
        o = self.o
        avoid = self.avoid + [(c["start"], c["end"]) for c in self.found]
        kind = resolve(self.ai)["kind"]
        clips = []
        if kind != "offline" and words:
            lines = segments_from_words(words)
            try:
                clips = pick_ai(self.ai, lines, o, a, b, self.usage, [x for x in avoid if a <= x[0] <= b])
            except Exception as e:
                self.log(f"AI choice failed ({str(e)[:300]}) - using the built-in scoring for this part.")
                clips = []
        if not clips:
            audio = E.read_audio(self.movie, a, b - a)
            clips = pick_offline(words, o, a, b, audio, avoid)
            for c in clips:
                c.update({k: v for k, v in offline_texts(c, words, o.get("title") or "").items() if not c.get(k)})
        out = []
        for c in clips:
            c = snap_to_words(c, words, max(a - 2, 0.0), b + 2, o["min"], o["max"])
            if c["end"] - c["start"] < 3 or SC.overlaps(c["start"], c["end"], avoid + [(x["start"], x["end"]) for x in out], 1.0):
                continue
            if c.get("score", 100) < o.get("min_score", 0):
                continue
            for k in ("title", "hook", "description", "category", "reason"):
                c.setdefault(k, "")
            c.setdefault("hashtags", [])
            c["words"] = [[w, round(s, 3), round(e, 3)] for w, s, e in words if s < c["end"] and e > c["start"]]
            out.append(c)
            if len(out) >= o["count"]:
                break
        return out

    def finish_clip(self, c):
        mode = LAYOUT_KEY.get(self.o.get("layout") or "Normal")
        if mode and not self.stop_flag:
            try:
                lay = plan_layout(self.movie, c["start"], c["end"], mode, self.info, self.log, self.o.get("cam_box"))
                c["layout"] = dict(lay or {"mode": "none"}, req=mode, cam_req=self.o.get("cam_box") or None)
            except Exception as e:
                self.log(f"Face finding failed ({str(e)[:200]}) - normal picture.")
        c["n"] = self.number
        self.number += 1
        self.found.append(c)
        if self.export and not self.stop_flag:
            try:
                c["file"] = self.export(c)
            except Exception as e:
                self.log(f"Export of clip {c['n']} failed: {str(e)[:300]}")
        self.on_clip(c)

    # ---- the whole run
    def available(self):
        if self.live:
            return self.live.seconds
        return self.info["duration"]

    def run(self):
        o = self.o
        part = max(30.0, float(o.get("part_sec", 600)))
        if not self.live:
            self.info = E.probe_info(self.movie)
            parts = plan_parts(self.info["duration"], part, float(o.get("start") or 0), o.get("end") or None)
            if not parts:
                self.log("Nothing to work on (check From / To).")
                return self.found
            self.log(f"{len(parts)} part(s) of {part / 60:.0f} min. The clips of part 1 are ready while part 2 is "
                     f"still being listened to.")
            return self._run_parts(parts)
        return self._run_live(part)

    def _run_parts(self, parts):
        total = len(parts)
        nxt = {}

        def prefetch(i):
            if i < total and not self.stop_flag:
                a, b = parts[i]
                box = nxt.setdefault(i, {})

                def work():
                    try:
                        box["words"] = self.hear(a, b)
                    except Exception as e:
                        box["error"] = e
                box["thread"] = threading.Thread(target=work, daemon=True)
                box["thread"].start()
        prefetch(0)
        for i, (a, b) in enumerate(parts):
            if self.stop_flag:
                break
            self.progress(i / total, f"Part {i + 1}/{total} ({tstr(a)}-{tstr(b)}): listening ...")
            box = nxt[i]
            while box["thread"].is_alive() and not self.stop_flag:
                box["thread"].join(0.2)
            if self.stop_flag:
                break
            prefetch(i + 1)                     # the next part is listened to while this one is cut
            if "error" in box:
                raise box["error"]
            words = box.get("words") or []
            self.log(f"Part {i + 1}/{total}: {len(words)} words heard. Choosing the best moments ...")
            self.progress((i + 0.3) / total, f"Part {i + 1}/{total}: choosing moments ...")
            clips = self.choose(a, b, words)
            self.log(f"Part {i + 1}/{total}: {len(clips)} clip(s).")
            for k, c in enumerate(clips):
                if self.stop_flag:
                    break
                self.progress((i + 0.4 + 0.6 * k / max(1, len(clips))) / total,
                              f"Part {i + 1}/{total}: clip {k + 1}/{len(clips)} ({tstr(c['start'])})")
                self.finish_clip(c)
        self.progress(1.0 if not self.stop_flag else 0.0,
                      "Stopped." if self.stop_flag else f"Done - {len(self.found)} clip(s).")
        return self.found

    def _run_live(self, part):
        t = 0.0
        i = 0
        while not self.stop_flag:
            have = self.live.seconds
            alive = self.live.alive
            if have - t >= part or (not alive and have - t > max(20.0, self.o["min"])):
                b = min(have, t + part) if alive else have
                i += 1
                if self.info is None:
                    try:
                        self.info = E.probe_info(self.movie)
                    except Exception:
                        self.info = None
                self.progress(0.0, f"Live part {i} ({tstr(t)}-{tstr(b)}): listening ...")
                words = self.hear(t, b)
                clips = self.choose(t, b, words)
                self.log(f"Live part {i}: {len(words)} words, {len(clips)} clip(s).")
                for c in clips:
                    if self.stop_flag:
                        break
                    self.finish_clip(c)
                t = b
                continue
            if not alive:
                if self.live.error and not self.found:
                    raise RuntimeError("live recording failed: " + self.live.error)
                break
            self.progress(min(0.99, (have - t) / part), f"Recording live: {tstr(have)} recorded, next part at "
                                                         f"{tstr(t + part)}")
            time.sleep(1.0)
        self.progress(1.0, f"Live finished - {len(self.found)} clip(s).")
        return self.found
