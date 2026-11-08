"""Viral scoring helpers (heuristic AI): lexicons, window scoring, optional Ollama re-rank."""
import re, json, urllib.request
from collections import Counter
from dataclasses import dataclass
import numpy as np

def _lex(items):
    return (set(w for w in items if " " not in w), [w for w in items if " " in w])

FUNNY = _lex("""हाहा haha hahaha lol lmao मज़ाक मजाक मज़ेदार मजेदार पागल बेवकूफ गधा गधे उल्लू अबे ओए
 बकवास तमाशा नौटंकी कमीने कमीना साले साला भाई यार joke funny hilarious idiot stupid crazy mad
 silly fool dumb shut\u00a0up क्या\u00a0बात kya\u00a0baat पक्का\u00a0यार हद\u00a0है कसम\u00a0से चुप\u00a0कर""".replace("\u00a0", " ").split() +
 ["क्या बात", "हद है", "कसम से", "चुप कर", "shut up", "are you serious", "क्या बकवास", "मर जाऊंगा"])
EMO = _lex("""माँ मां मम्मी पापा बाप बेटा बेटी बेटे आंसू आँसू रो रोना रोया दिल प्यार मोहब्बत इश्क़ इश्क
 जुदाई याद माफ़ माफ़ी कसम वादा अकेला अकेली दर्द तकलीफ़ मौत धोखा सच झूठ भरोसा क़ुर्बानी हमेशा
 mother mom dad father love heart cry crying tears sorry miss forgive promise alone pain death
 trust betray truth lie sacrifice family forever""".split() +
 ["तुम्हारी वजह", "छोड़ के मत जा", "मुझे माफ़", "i love you", "miss you", "don't leave", "मेरी ग़लती"])
REL = _lex("""ज़िंदगी जिंदगी सपना सपने दोस्ती दोस्त भाई बहन शादी नौकरी पैसा पैसे किस्मत इज़्ज़त इज्जत
 ज़िम्मेदारी समाज लोग क्या\u00a0कहेंगे life dream dreams friend friends job money marriage society
 struggle future career parents""".replace("\u00a0", " ").split() + ["लोग क्या कहेंगे", "कुछ बनना है"])
LAUGH_RE = re.compile(r"(?:ha){2,}h?|हा(?:हा)+|हे(?:हे)+|hehe+", re.I)

def tokenize(text):
    return [t for t in re.split(r"[\s,.!?।\-\"'…:;()\[\]]+", text.lower()) if t]

def hits(text, toks, lex):
    words, phrases = lex
    low = text.lower()
    return sum(toks[w] for w in words) + sum(low.count(p) for p in phrases)

@dataclass
class Seg:
    start: float
    end: float
    text: str

def make_candidates(segs, min_d, max_d, max_gap=4.0):
    out = []
    for i in range(len(segs)):
        for j in range(i, len(segs)):
            if j > i and segs[j].start - segs[j - 1].end > max_gap:
                break
            d = segs[j].end - segs[i].start
            if d > max_d - 0.8:
                break
            if d >= min_d - 0.8:
                out.append((i, j))
    return out

def rms_frames(audio, sr=16000, hop=0.5):
    n = int(sr * hop)
    k = len(audio) // n
    if k == 0:
        return np.ones(1) * 1e-4
    fr = audio[:k * n].reshape(k, n)
    return np.sqrt((fr ** 2).mean(1) + 1e-10)

def score_window(segs, i, j, chunk_t0, rms, med, focus, hop=0.5):
    win = segs[i:j + 1]
    start, end = win[0].start, win[-1].end
    dur = max(end - start, 1.0)
    text = " ".join(x.text for x in win)
    toks = Counter(tokenize(text))
    F = hits(text, toks, FUNNY) + 2 * len(LAUGH_RE.findall(text))
    E = hits(text, toks, EMO)
    R = hits(text, toks, REL)
    wf, we, wr = {"Funny": (1, .3, .4), "Emotional": (.3, 1, .4)}.get(focus, (1, 1, .5))
    kw = min(1.0, (wf * F + we * E + wr * R) / 4.0)
    punct = min(1.0, (text.count("!") + text.count("?")) / 5.0)
    wps = len(text.split()) / dur
    rate = float(np.clip((wps - 1.0) / 2.0, 0, 1))
    a, b = int(max(0, (start - chunk_t0) / hop)), int(max(1, (end - chunk_t0) / hop))
    w = rms[a:b] if b > a else rms[-1:]
    if len(w) == 0:
        w = rms[-1:]
    peak = float(np.percentile(w, 95) / med)
    audio_peak = float(np.clip((peak - 1.5) / 3.0, 0, 1))
    dyn = float(np.clip(w.std() / (w.mean() + 1e-9), 0, 1))
    first = win[0].text
    hook = 1.0 if ("?" in first or "!" in first or hits(first, Counter(tokenize(first)), FUNNY) +
                   hits(first, Counter(tokenize(first)), EMO) > 0) else 0.3
    last = win[-1].text.strip()
    end_ok = 1.0 if last and last[-1] in ".?!।…" else 0.5
    cov = min(1.0, sum(max(0, min(x.end, end) - max(x.start, start)) for x in win) / dur)
    score = 100 * (0.30 * kw + 0.15 * punct + 0.10 * rate + 0.15 * audio_peak +
                   0.10 * dyn + 0.08 * hook + 0.04 * end_ok + 0.08 * cov)
    cats = {"Funny": wf * F, "Emotional": we * E, "Relatable": wr * R}
    cat = max(cats, key=cats.get) if max(cats.values()) > 0 else ("Drama" if punct > .4 else "Dialogue")
    reason = f"{cat} | keywords F{F}/E{E}/R{R} | loud-peak x{peak:.1f} | pace {wps:.1f} words/s"
    return dict(start=start, end=end, score=score, category=cat, text=text, reason=reason)

def llm_score(text, model, focus):
    prompt = ("You are a viral short-video editor. Rate this movie dialogue excerpt (Hindi/English) "
              f"for its potential as a {focus} Instagram Reel / YouTube Short (30-60s). "
              "High score = very funny, emotional, relatable, strong hook, self-contained. "
              'Reply ONLY JSON: {"score": 0-100, "reason": "short reason"}.\n\nExcerpt:\n' + text[:3000])
    body = json.dumps({"model": model, "prompt": prompt, "stream": False, "format": "json",
                       "options": {"temperature": 0.2}}).encode()
    req = urllib.request.Request("http://localhost:11434/api/generate", body,
                                 {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as r:
        d = json.loads(json.loads(r.read())["response"])
    return float(d.get("score", 0)), str(d.get("reason", ""))

def overlaps(a, b, taken, gap=2.0):
    return any(a < e + gap and b > s - gap for s, e in taken)

