// AI Clips (the PeakCut + AutoClip ideas, made for the phone): a movie or a downloaded YouTube video is worked on
// PART BY PART - listen to the part (speech to text with word times), let an AI pick the best moments, cut each one
// to 9:16 with word-by-word captions, a hook title, a cover picture and the post text (title, description,
// hashtags). Clips of part 1 are ready while part 2 is still being listened to.
// Without an AI key the loudest / busiest talking moments are picked and no captions are made.
import * as E from "./engine.js";
import * as D from "./dialogue.js";
import { bridge, bytesToB64 } from "./bridge.js";

export const PROVIDERS = {
  gemini: { label: "Google Gemini (free key: aistudio.google.com)", base: "https://generativelanguage.googleapis.com/v1beta", model: "gemini-2.5-flash", kind: "gemini" },
  groq: { label: "Groq (free key: console.groq.com)", base: "https://api.groq.com/openai/v1", model: "llama-3.3-70b-versatile", stt: "whisper-large-v3-turbo", kind: "openai" },
  openai: { label: "OpenAI", base: "https://api.openai.com/v1", model: "gpt-4o-mini", stt: "whisper-1", kind: "openai" },
  openrouter: { label: "OpenRouter (AI only, no speech to text)", base: "https://openrouter.ai/api/v1", model: "google/gemini-2.5-flash", stt: "", kind: "openai" },
  custom: { label: "Other OpenAI-compatible (Ollama, LM Studio ...)", base: "http://192.168.1.10:11434/v1", model: "llama3.1", stt: "", kind: "openai" },
};

export const PLATFORMS = {
  "TikTok / Reels / Shorts (9:16)": { aspect: "9:16", min: 20, max: 60 },
  "YouTube Shorts long (9:16, up to 3 min)": { aspect: "9:16", min: 45, max: 180 },
  "YouTube landscape (16:9)": { aspect: "16:9", min: 60, max: 300 },
  "Square (1:1)": { aspect: "1:1", min: 20, max: 60 },
};

export const CAPTION_STYLES = {
  Bounce: { font: "Poppins", size: 6.0, color: "#FFFFFF", active: "#00F0FF", outline: 7, upper: true, per: 3 },
  Hype: { font: "Anton", size: 7.0, color: "#FFFFFF", active: "#FFD400", outline: 7, upper: true, per: 2 },
  Clean: { font: "Poppins", size: 4.6, color: "#FFFFFF", active: "#6BD7FF", outline: 5, upper: false, per: 4 },
  Hindi: { font: "Noto Sans Devanagari", size: 5.4, color: "#FFFFFF", active: "#FFD400", outline: 6, upper: false, per: 3 },
};
export const CAPTION_POS = { Bottom: 70, Middle: 52, Top: 18 };

// ------------------------------------------------------------------ talking to the AI service
const strip = (t) => String(t || "").replace(/^\s*```(?:json)?/i, "").replace(/```\s*$/, "").trim();
function parseJson(text) {
  const t = strip(text);
  try { return JSON.parse(t); } catch (e) { /* take the first {...} */ }
  const a = t.indexOf("{"), b = t.lastIndexOf("}");
  if (a >= 0 && b > a) return JSON.parse(t.slice(a, b + 1));
  throw new Error("The AI did not answer in the expected form: " + t.slice(0, 200));
}
const fail = (r, what) => {
  let msg = r.error || "";
  try { const j = JSON.parse(r.body || ""); msg = (j.error && (j.error.message || j.error)) || j.message || msg; } catch (e) { msg = msg || String(r.body || "").slice(0, 300); }
  throw new Error(`${what} failed (${r.status}): ${String(msg).slice(0, 400)}`);
};

export function resolve(ai) {
  const p = PROVIDERS[ai.provider] || PROVIDERS.gemini;
  return { kind: p.kind, base: String(ai.base || p.base).replace(/\/+$/, ""), model: ai.model || p.model,
    stt: ai.stt === undefined || ai.stt === "" ? p.stt || "" : ai.stt, key: String(ai.key || "").trim(), provider: ai.provider };
}

export async function ask(ai, system, user, json = true) {
  const c = resolve(ai);
  if (c.kind === "gemini") {
    const url = `${c.base}/models/${encodeURIComponent(c.model)}:generateContent?key=${encodeURIComponent(c.key)}`;
    const body = { systemInstruction: { parts: [{ text: system }] }, contents: [{ role: "user", parts: [{ text: user }] }],
      generationConfig: { temperature: 0.4, ...(json ? { responseMimeType: "application/json" } : {}) } };
    const r = await bridge().http("POST", url, { "Content-Type": "application/json" }, JSON.stringify(body));
    if (r.status !== 200) fail(r, "The AI");
    const d = JSON.parse(r.body);
    const text = (((d.candidates || [])[0] || {}).content || { parts: [] }).parts.map((p) => p.text || "").join("");
    return json ? parseJson(text) : text;
  }
  const body = { model: c.model, temperature: 0.4, messages: [{ role: "system", content: system }, { role: "user", content: user }] };
  if (json && c.provider !== "custom") body.response_format = { type: "json_object" };
  const headers = { "Content-Type": "application/json" };
  if (c.key) headers.Authorization = "Bearer " + c.key;
  const r = await bridge().http("POST", `${c.base}/chat/completions`, headers, JSON.stringify(body));
  if (r.status !== 200) fail(r, "The AI");
  const d = JSON.parse(r.body);
  const text = (((d.choices || [])[0] || {}).message || {}).content || "";
  return json ? parseJson(text) : text;
}

export async function testKey(ai) {
  const r = await ask(ai, "You answer with JSON only.", 'Answer exactly {"ok": true}');
  return !!(r && r.ok);
}

// spread a segment's time over its words (when the service gives no word times)
export function wordsFromSegments(segs) {
  const out = [];
  for (const s of segs) {
    const ws = String(s.text || "").trim().split(/\s+/).filter(Boolean);
    if (!ws.length) continue;
    const a = +s.start, b = Math.max(a + 0.1, +s.end);
    const total = ws.reduce((n, w) => n + w.length + 1, 0);
    let t = a;
    for (const w of ws) { const d = ((b - a) * (w.length + 1)) / total; out.push({ word: w, start: t, end: t + d }); t += d; }
  }
  return out;
}

// Speech to text of an audio file. Returns {words:[{word,start,end}], segments:[{start,end,text}]} (times in the file).
export async function transcribe(ai, audioPath, lang = "") {
  const c = resolve(ai);
  if (c.kind === "gemini") {
    const bytes = await bridge().readBytes(audioPath);
    const prompt = "Transcribe this audio exactly as spoken, in its own language (Hindi in Devanagari script, English in Latin). " +
      'Return JSON {"segments":[{"start":seconds,"end":seconds,"text":"..."}]} with one segment per sentence or short phrase ' +
      "(2-8 seconds), times in seconds from the start of the audio. Do not translate, do not summarise.";
    const url = `${c.base}/models/${encodeURIComponent(c.model)}:generateContent?key=${encodeURIComponent(c.key)}`;
    const body = { contents: [{ role: "user", parts: [{ inline_data: { mime_type: "audio/aac", data: bytesToB64(bytes) } }, { text: prompt }] }],
      generationConfig: { temperature: 0, responseMimeType: "application/json" } };
    const r = await bridge().http("POST", url, { "Content-Type": "application/json" }, JSON.stringify(body));
    if (r.status !== 200) fail(r, "Speech to text");
    const d = JSON.parse(r.body);
    const text = (((d.candidates || [])[0] || {}).content || { parts: [] }).parts.map((p) => p.text || "").join("");
    const segs = (parseJson(text).segments || []).map((s) => ({ start: +s.start || 0, end: +s.end || 0, text: String(s.text || "") }));
    return { segments: segs, words: wordsFromSegments(segs) };
  }
  if (!c.stt) return null;
  const fields = { model: c.stt, response_format: "verbose_json", "timestamp_granularities[]": ["word", "segment"] };
  if (lang) fields.language = lang;
  const headers = c.key ? { Authorization: "Bearer " + c.key } : {};
  const r = await bridge().upload(`${c.base}/audio/transcriptions`, headers, fields, "file", audioPath, "audio/mp4");
  if (r.status !== 200) fail(r, "Speech to text");
  const d = JSON.parse(r.body);
  const segs = (d.segments || []).map((s) => ({ start: +s.start, end: +s.end, text: String(s.text || "").trim() }));
  let words = (d.words || []).map((w) => ({ word: String(w.word || "").trim(), start: +w.start, end: +w.end })).filter((w) => w.word);
  if (!words.length) words = wordsFromSegments(segs.length ? segs : [{ start: 0, end: d.duration || 1, text: d.text || "" }]);
  return { segments: segs.length ? segs : [{ start: 0, end: words.length ? words[words.length - 1].end : 0, text: d.text || "" }], words };
}

// ------------------------------------------------------------------ choosing the moments
const PICK_SYSTEM = "You are a top short-form video editor (TikTok, Reels, YouTube Shorts). You find the moments of a video that " +
  "make people stop scrolling and watch to the end: strong emotion, a punchline, a surprising fact, drama, a clear story with a payoff, " +
  "a quotable line. Each clip must make sense on its own, start at the beginning of a sentence and end after a finished sentence. " +
  "Answer with JSON only.";

export async function pickMoments(ai, lines, opts) {
  const user = `Transcript of a part of "${opts.title}" (times in seconds; the speech may be Hindi, English or mixed):\n` +
    lines.map((l) => `[${l.start.toFixed(1)}-${l.end.toFixed(1)}] ${l.text}`).join("\n") +
    `\n\nFind the ${opts.count} best clips for ${opts.platform}. Every clip ${opts.min}-${opts.max} seconds long, inside ${opts.a.toFixed(0)}-${opts.b.toFixed(0)}.` +
    ` Write titles, hooks, descriptions and hashtags in ${opts.textLang || "the language of the speech (Hindi in Devanagari or Hinglish if mixed)"}.` +
    `\nReturn {"clips":[{"start":seconds,"end":seconds,"score":1-100,"title":"short catchy title","hook":"3-7 word hook shown at the start",` +
    `"description":"1-2 sentences for the post","hashtags":["#tag", ...],"reason":"why it works"}]} best first.`;
  const r = await ask(ai, PICK_SYSTEM, user);
  return (r.clips || []).map((c) => ({ start: +c.start, end: +c.end, score: +c.score || 50, title: String(c.title || "").trim(),
    hook: String(c.hook || "").trim(), description: String(c.description || "").trim(),
    hashtags: (Array.isArray(c.hashtags) ? c.hashtags : String(c.hashtags || "").split(/[\s,]+/)).map((h) => String(h).trim()).filter(Boolean)
      .map((h) => (h.startsWith("#") ? h : "#" + h)).slice(0, 10), reason: String(c.reason || "") }))
    .filter((c) => c.end > c.start);
}

// no AI key: the windows with the most (and loudest) talking
export function pickByLoudness(x, sr, regs, a, n, minLen, maxLen) {
  const len = Math.min(maxLen, Math.max(minLen, (minLen + maxLen) / 2));
  const db = D.frameDb(x, sr, 0.5), step = 0.5;
  const talk = new Float32Array(db.length);
  for (const [s, e] of regs) for (let i = Math.floor(s / step); i < Math.min(db.length, Math.ceil(e / step)); i++) talk[i] = 1;
  const win = Math.round(len / step), cands = [];
  for (let i = 0; i + win <= db.length; i += 2) {
    let sc = 0;
    for (let j = i; j < i + win; j++) sc += talk[j] * Math.max(0, db[j] + 60);
    cands.push([sc, i * step]);
  }
  cands.sort((p, q) => q[0] - p[0]);
  const out = [];
  for (const [sc, t] of cands) {
    if (out.length >= n) break;
    if (out.some((c) => Math.abs(c.start - (a + t)) < len)) continue;
    out.push({ start: a + t, end: a + t + len, score: Math.round(sc / win), title: "", hook: "", description: "", hashtags: [], reason: "most talking / loudest" });
  }
  return out;
}

// clip edges onto words: start at a word, end after a finished word (+ a breath)
export function snapToWords(c, words, minLen, maxLen, lo, hi) {
  let s = Math.max(lo, c.start), e = Math.min(hi, c.end);
  if (words && words.length) {
    const first = words.find((w) => w.end > s);
    if (first) s = Math.max(lo, Math.min(s, first.start) - 0.15);
    const lastIn = [...words].reverse().find((w) => w.start < e);
    if (lastIn) e = Math.min(hi, lastIn.end + 0.35);
  }
  if (e - s < minLen) e = Math.min(hi, s + minLen);
  if (e - s > maxLen) e = s + maxLen;
  return { ...c, start: s, end: e };
}

// word-by-word captions of one clip: groups of `per` words, the spoken word in the highlight colour
export function captionEvents(words, a, b, style) {
  const ws = words.filter((w) => w.end > a && w.start < b).map((w) => ({ ...w, word: style.upper ? w.word.toUpperCase() : w.word }));
  const ev = [];
  for (let i = 0; i < ws.length; i += style.per) {
    const g = ws.slice(i, i + style.per);
    g.forEach((w, k) => {
      const t0 = Math.max(0, w.start - a), t1 = Math.max(t0 + 0.05, (k + 1 < g.length ? g[k + 1].start : g[g.length - 1].end + 0.25) - a);
      const text = g.map((x, j) => (j === k ? `{c=${style.active}}${x.word}{/c}` : x.word)).join(" ");
      ev.push({ t0, t1: Math.min(t1, b - a), text });
    });
  }
  for (let i = 0; i + 1 < ev.length; i++) if (ev[i].t1 > ev[i + 1].t0) ev[i].t1 = ev[i + 1].t0;
  return ev;
}

export function planParts(duration, partSec, start = 0, end = null) {
  end = !end || end > duration ? duration : end;
  const out = [];
  let t = Math.max(0, start);
  while (t < end - 1) {
    let b = Math.min(end, t + partSec);
    if (end - b < partSec * 0.25) b = end;
    out.push([t, b]);
    t = b;
  }
  return out;
}

const safeName = (t) => String(t || "clip").replace(/[\\/:*?"<>|#\n\r]+/g, " ").replace(/\s+/g, " ").trim().slice(0, 50) || "clip";

// ------------------------------------------------------------------ the job
export class AIClipsJob {
  constructor({ movie, settings, opts, ai, outDir, tmpDir, log, progress, onClip }) {
    Object.assign(this, { movie, settings, opts, ai, outDir, tmpDir });
    this.log = log || (() => {}); this.progress = progress || (() => {}); this.onClip = onClip || (() => {});
    this.cancelled = false;
    this.job = { current: null };
    this.made = [];
  }

  stop() { this.cancelled = true; if (this.job.current) this.job.current.cancel(); if (this.runner) this.runner.stop(); }

  hasAI() { const c = resolve(this.ai || {}); return !!(c.key || c.provider === "custom"); }

  async listen(a, b) {
    const o = this.opts;
    const out = E.join(this.tmpDir, `aiclips_${Math.round(a)}_${Date.now()}.${resolve(this.ai).kind === "gemini" ? "aac" : "m4a"}`);
    const args = ["-nostdin", "-y", "-v", "error", "-ss", a.toFixed(3), "-t", (b - a).toFixed(3), "-i", this.movie, "-vn", "-map", "0:a:0?",
      "-ac", "1", "-ar", "16000", "-c:a", "aac", "-b:a", "32k"];
    if (out.endsWith(".aac")) args.push("-f", "adts");
    args.push(out);
    const r = await E.ffrun(args, { job: this.job });
    if (r.code !== 0) throw new Error("Could not read the sound: " + String(r.stderr || "").slice(-200));
    try {
      const t = await transcribe(this.ai, out, o.lang || "");
      if (!t) return null;
      const shift = (x) => ({ ...x, start: x.start + a, end: x.end + a });
      return { words: t.words.map(shift), segments: t.segments.map(shift) };
    } finally { await bridge().remove(out); }
  }

  async choose(a, b, heard) {
    const o = this.opts;
    if (this.hasAI() && heard && heard.segments.length) {
      const clips = await pickMoments(this.ai, heard.segments, { title: E.stem(this.movie), count: o.count, platform: o.platformName,
        min: o.min, max: o.max, a, b, textLang: o.textLang });
      return clips.filter((c) => c.start >= a - 5 && c.end <= b + 5).map((c) => snapToWords(c, heard.words, o.min, o.max, a, b));
    }
    if (this.hasAI() && !heard) {        // AI without speech to text (OpenRouter / local): ask with no transcript is useless
      this.log("  this AI service has no speech to text - picking by talking + loudness instead");
    }
    const x = await D.readAudio(this.movie, a, b - a, this.tmpDir, this.job);
    if (!x.length) return [];
    const [regs] = await D.detectSpeech(x, 150, 300, this.log, 350, 0.45);
    return pickByLoudness(x, 16000, regs, a, o.count, o.min, o.max);
  }

  async render(c, n, heard, info) {
    const o = this.opts, st = CAPTION_STYLES[o.style] || CAPTION_STYLES.Bounce;
    const len = c.end - c.start;
    const base = `${String(n).padStart(2, "0")}_${safeName(c.title || `clip ${Math.round(c.start)}s`)}`;
    const out = E.join(this.outDir, base + ".mp4");
    const texts = [];
    if (o.hook && (c.hook || c.title)) {
      texts.push({ ...E.TEXT_DEFAULT, text: c.hook || c.title, start: 0, end: Math.min(3, len), pos: "Custom", hcenter: true, y: 14,
        size: 5.6, font: st.font, color: "#000000", box: true, box_color: "#FFFFFF", box_opacity: 100, box_pad: 30, outline: 0,
        shadow: false, anim_in: "Pop", anim_in_dur: 0.35 });
    }
    const S = E.sanitize({ ...this.settings, aspect: o.aspect, fit_mode: o.fit, texts, overlays: [], audios: [] });
    S._fast = false;
    if (o.boost) S._boost = { ...E.BOOST_DEFAULT, part_label: false, hook: "" };
    if (o.captions && heard && heard.words.length) {
      S._captions = { events: captionEvents(heard.words, c.start, c.end, st),
        style: { font: st.font, size: st.size, color: st.color, outline: st.outline, outline_color: "#000000", shadow: true, shadow_dist: 4,
          shadow_opacity: 70, bold: true, pos: "Custom", hcenter: true, y: CAPTION_POS[o.capPos] || 70, box: false, align: "Center" } };
    }
    this.runner = new E.Runner(S, this.log, null, null, this.tmpDir);
    this.runner.job = this.job;
    this.runner.clipProgress = (f) => this.progress(this.partFrac + f * this.clipShare, `Part ${this.partNo}: clip ${n} - ${Math.round(f * 100)}%`);
    const ok = await this.runner.cut(this.movie, c.start, len, out, info, null);
    if (!ok) return null;
    const cover = E.join(this.outDir, base + "_cover.jpg");
    await E.ffrun(["-nostdin", "-y", "-v", "error", "-ss", Math.min(1.2, len / 2).toFixed(2), "-i", out, "-frames:v", "1", "-q:v", "3", cover], { job: this.job });
    const tags = (c.hashtags || []).join(" ");
    const kit = `${c.title || base}\n\n${c.description || ""}\n\n${tags}\n\n(from ${E.basename(this.movie)}  ${E.tstr ? E.tstr(c.start) : c.start.toFixed(0)} - ${E.tstr ? E.tstr(c.end) : c.end.toFixed(0)}  score ${c.score}${c.reason ? "  -  " + c.reason : ""})\n`;
    const kitPath = E.join(this.outDir, base + "_post.txt");
    await bridge().writeText(kitPath, kit);
    await bridge().scanFile(out);
    const d = { path: out, cover, kit: kitPath, title: c.title || `Clip ${n} (${E.tstr(c.start)})`, text: kit, score: c.score, start: c.start, end: c.end, length: len, n };
    this.made.push(d);
    this.onClip(d);
    return d;
  }

  async run() {
    const o = this.opts;
    const info = await E.probeInfo(this.movie);
    const parts = planParts(info.duration, o.partSec, o.from || 0, o.to || null);
    await bridge().mkdirs(this.outDir);
    this.log(`${parts.length} part(s) of about ${Math.round(o.partSec / 60)} min. ` +
      (this.hasAI() ? `AI: ${resolve(this.ai).model}.` : "No AI key: picking by talking + loudness, no captions."));
    let n = 0, next = null;
    const listen = (i) => (this.hasAI() ? this.listen(parts[i][0], parts[i][1]).catch((e) => { this.log(`  part ${i + 1}: ${e.message || e}`); return null; }) : Promise.resolve(null));
    for (let i = 0; i < parts.length && !this.cancelled; i++) {
      const [a, b] = parts[i];
      this.partNo = i + 1; this.partFrac = i / parts.length;
      this.progress(this.partFrac, `Part ${i + 1} of ${parts.length}: listening ...`);
      this.log(`Part ${i + 1}: ${a.toFixed(0)}s - ${b.toFixed(0)}s`);
      const heard = await (next || listen(i));
      next = i + 1 < parts.length ? listen(i + 1) : null;       // the next part is heard while this one is cut
      if (this.cancelled) break;
      if (heard) this.log(`  heard ${heard.words.length} words`);
      let clips = [];
      try { clips = await this.choose(a, b, heard); } catch (e) { this.log(`  choosing failed: ${e.message || e}`); }
      clips = clips.sort((p, q) => q.score - p.score).slice(0, o.count);
      this.log(`  ${clips.length} clip(s) chosen`);
      this.clipShare = 1 / parts.length / Math.max(1, clips.length);
      for (const [k, c] of clips.entries()) {
        if (this.cancelled) break;
        this.partFrac = i / parts.length + k * this.clipShare;
        n++;
        try {
          const d = await this.render(c, n, heard, info);
          if (d) this.log(`  saved ${E.basename(d.path)}`);
        } catch (e) { this.log(`  clip ${n} failed: ${e.message || e}`); }
      }
    }
    this.progress(1, this.cancelled ? "Stopped" : `Finished - ${this.made.length} clip(s)`);
    return this.made;
  }
}
