"""AI smart edit for Auto Short (Hindi / English / Hinglish): cuts silence the way a human editor does and makes
captions from the same words.

1. The words of every scanned stretch are heard with their times (Whisper on this PC, Groq / OpenAI speech-to-text,
   or Gemini) - so a cut never falls inside a word.
2. Pauses are cut by meaning: a short breath inside a sentence stays (cutting it sounds robotic), a pause after a
   finished sentence is cut, leaving a natural little gap; filler sounds (umm, aa, uh) can be removed.
3. With an AI service (Google Gemini free key, Groq, OpenAI, a local Ollama / LM Studio model ...) the AI reads the
   lines and cuts stammering, false starts (keeps the last complete try), repeats and meaningless fragments - and
   can fix the caption text (Hindi in Devanagari / Hinglish in Roman letters / English).
Every step can be switched off; without words the normal talking detection is used unchanged."""
import re

import viral as V

FILLERS = {"um", "umm", "ummm", "uh", "uhh", "uhm", "erm", "er", "hmm", "hm", "hmmm", "mm", "mmm", "ah", "aah", "aa",
           "aaa", "eh", "uff", "अं", "उम्म", "हम्म", "आ", "आं", "अ", "उं", "एं"}
SCRIPTS = ["As spoken", "Hindi (Devanagari)", "Hinglish (Roman letters)", "English"]

EDIT_SYSTEM = ("You are an expert video editor for Hindi, English and Hinglish talking videos (movie dialogue, "
               "podcasts, vlogs, interviews). You decide which transcript lines to CUT so that the final edit feels "
               "made by a skilled human editor, not by software. CUT: lines that are only filler sounds or verbal "
               "tics (umm, aa, uh, matlab, you know), stammering and false starts (when a speaker restarts the same "
               "sentence, keep only the last complete try), exact repetitions, coughs / noise written as words, and "
               "meaningless fragments. KEEP: everything that carries meaning, emotion, a joke, a punchline or a "
               "reaction - even very short lines like 'haan', 'nahi', 'kya?', 'wow'. Never cut more than a third of "
               "the lines. Answer with JSON only.")


def norm(w):
    return re.sub(r"[^\wऀ-ॿ]+", "", str(w).lower())


def is_filler(w):
    n = norm(w)
    return bool(n) and (n in FILLERS or re.fullmatch(r"(u+m+|u+h+|h+m+|a+h*|e+r+m*)", n) is not None)


def sentence_end(w):
    return str(w).rstrip().endswith((".", "?", "!", "।", "…"))


class SmartCut:
    """o: smart (bool), fillers (bool), ai_cut (bool), captions (bool), cap_style, cap_pos, script, speech, lang,
    whisper_model, mid_gap, end_gap, pad_in, pad_out."""

    def __init__(self, o, ai, log=print, tmp=None):
        self.o = dict(o)
        self.ai = dict(ai or {})
        self.log = log
        self.usage = V.Usage()
        self.listener = V.Listener(self.o.get("speech", "local"), self.ai, self.o.get("lang", ""),
                                   self.o.get("whisper_model", "small"), log, self.usage, tmp)
        self.failed = False
        self.ai_off = V.resolve(self.ai)["kind"] == "offline"

    # ---------------------------------------------------------------- words
    def hear(self, movie, a, b):
        if self.failed or b - a < 0.3:
            return []
        try:
            return self.listener.listen(movie, a, b)
        except Exception as e:
            self.failed = True
            self.log(f"AI smart edit: speech to text failed ({str(e)[:240]}) - the normal talking detection is used.")
            return []

    # ---------------------------------------------------------------- the AI pass
    def ai_pass(self, words):
        """Asks the AI which lines to cut (and the corrected caption text). Returns (cut line ids, {id: text},
        lines)."""
        lines = V.segments_from_words(words, max_gap=0.7, max_len=7.0)
        if self.ai_off or not lines or not (self.o.get("ai_cut") or self.want_fix()):
            return set(), {}, lines
        script = self.o.get("script", "As spoken")
        fix = self.want_fix()
        user = ("Transcript lines (number, seconds, text):\n" +
                "\n".join(f"[{i}] ({s:.1f}-{e:.1f}) {t}" for i, (s, e, t) in enumerate(lines)) +
                "\n\nReturn {\"cut\": [line numbers to cut]" +
                (f", \"lines\": [{{\"id\": number, \"text\": \"the same line for captions, spelling fixed, in "
                 f"{script} (keep the meaning and roughly the same words, add punctuation)\"}}]" if fix else "") + "}" +
                ("" if self.o.get("ai_cut") else "\nDo not cut anything: return \"cut\": []."))
        try:
            r = V.ask(self.ai, EDIT_SYSTEM, user, self.usage)
        except Exception as e:
            self.log(f"AI smart edit: the AI did not answer ({str(e)[:200]}) - cutting by the words only.")
            return set(), {}, lines
        cut = set()
        for x in (r.get("cut") or []) if isinstance(r, dict) else []:
            try:
                cut.add(int(x))
            except (TypeError, ValueError):
                pass
        if len(cut) > len(lines) * 0.4:                  # a safety net: never let the AI throw away the story
            cut = set(sorted(cut)[:int(len(lines) * 0.4)])
        texts = {}
        for x in (r.get("lines") or []) if isinstance(r, dict) else []:
            try:
                texts[int(x.get("id"))] = str(x.get("text") or "").strip()
            except (TypeError, ValueError, AttributeError):
                pass
        return cut, texts, lines

    def want_fix(self):
        return bool(self.o.get("captions")) and self.o.get("script", "As spoken") != "As spoken"

    # ---------------------------------------------------------------- cutting
    def refine(self, regs, words, a, b):
        """VAD talking regions + words -> the pieces to keep (movie seconds), and the words for captions."""
        if not words:
            return regs, []
        # words that fall into silence are usually the speech model 'hearing' music or noise
        if regs:
            near = [(s - 0.4, e + 0.4) for s, e in regs]
            words = [w for w in words if any(w[1] < e and w[2] > s for s, e in near)]
        cut_ids, texts, lines = self.ai_pass(words)
        cap_words = list(words)
        if texts:                                         # corrected caption text, spread over each line's time
            cap_words = []
            for i, (s, e, t) in enumerate(lines):
                txt = texts.get(i) or t
                cap_words += V.words_from_segments([(s, e, txt)])
        if not self.o.get("smart"):
            return regs, cap_words
        keep = []
        for i, (s, e, t) in enumerate(lines):
            if i in cut_ids:
                continue
            keep += [w for w in words if s - 0.01 <= w[1] <= e + 0.01]
        if self.o.get("fillers"):
            keep = [w for w in keep if not is_filler(w[0])]
        if not keep:
            return [], cap_words
        mid, end_gap = float(self.o.get("mid_gap", 0.75)), float(self.o.get("end_gap", 0.35))
        pre, post, tail = float(self.o.get("pad_in", 0.10)), float(self.o.get("pad_out", 0.16)), 0.30
        spans, cur = [], [keep[0][1], keep[0][2], sentence_end(keep[0][0])]
        for w, s, e in keep[1:]:
            gap = s - cur[1]
            allowed = end_gap if cur[2] else mid
            if gap > allowed:
                spans.append(cur)
                cur = [s, e, sentence_end(w)]
            else:
                cur[1], cur[2] = max(cur[1], e), sentence_end(w)
        spans.append(cur)
        out = []
        for s, e, ended in spans:
            s, e = max(a, s - pre), min(b, e + (tail if ended else post))
            if out and s <= out[-1][1] + 0.05:
                out[-1] = (out[-1][0], max(out[-1][1], e))
            elif e - s > 0.12:
                out.append((s, e))
        if cut_ids:
            self.log(f"  AI edit: {len(cut_ids)} of {len(lines)} line(s) cut (stammering / repeats / fillers)")
        return out, cap_words


def caption_settings(o, words):
    """The '_captions' settings for one short from the heard words."""
    import captions as CAP
    if not o.get("captions") or not words:
        return None
    c = dict(CAP.DEFAULT, on=True, style=o.get("cap_style") or next(iter(CAP.STYLES)), mode="word",
             pos=o.get("cap_pos") or "Lower third", words=[list(w) for w in words], cues=[])
    return c
