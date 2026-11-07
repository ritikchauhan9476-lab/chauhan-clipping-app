// AI Clipping (port of the desktop AIEngine + scoring.py): Whisper turns the speech into text with times, then
// every window of 30-60 s is scored for funny / emotional / relatable words, pace, loud peaks and a strong hook.
// Whisper runs on the phone with transformers.js (the model is downloaded once, then it works offline).
import * as D from "./dialogue.js";
import * as E from "./engine.js";

const lex = (items) => [new Set(items.filter((w) => !w.includes(" "))), items.filter((w) => w.includes(" "))];
const words = (s) => s.split(/\s+/).filter(Boolean);
export const FUNNY = lex([...words(`हाहा haha hahaha lol lmao मज़ाक मजाक मज़ेदार मजेदार पागल बेवकूफ गधा गधे उल्लू अबे ओए
 बकवास तमाशा नौटंकी कमीने कमीना साले साला भाई यार joke funny hilarious idiot stupid crazy mad silly fool dumb`),
  "shut up", "क्या बात", "kya baat", "पक्का यार", "हद है", "कसम से", "चुप कर", "are you serious", "क्या बकवास", "मर जाऊंगा"]);
export const EMO = lex([...words(`माँ मां मम्मी पापा बाप बेटा बेटी बेटे आंसू आँसू रो रोना रोया दिल प्यार मोहब्बत इश्क़ इश्क
 जुदाई याद माफ़ माफ़ी कसम वादा अकेला अकेली दर्द तकलीफ़ मौत धोखा सच झूठ भरोसा क़ुर्बानी हमेशा
 mother mom dad father love heart cry crying tears sorry miss forgive promise alone pain death
 trust betray truth lie sacrifice family forever`), "तुम्हारी वजह", "छोड़ के मत जा", "मुझे माफ़", "i love you", "miss you", "don't leave", "मेरी ग़लती"]);
export const REL = lex([...words(`ज़िंदगी जिंदगी सपना सपने दोस्ती दोस्त भाई बहन शादी नौकरी पैसा पैसे किस्मत इज़्ज़त इज्जत
 ज़िम्मेदारी समाज लोग life dream dreams friend friends job money marriage society struggle future career parents`),
  "क्या कहेंगे", "लोग क्या कहेंगे", "कुछ बनना है"]);
const LAUGH_RE = /(?:ha){2,}h?|हा(?:हा)+|हे(?:हे)+|hehe+/gi;

export const tokenize = (text) => text.toLowerCase().split(/[\s,.!?।\-"'…:;()[\]]+/).filter(Boolean);
function counter(toks) { const c = new Map(); for (const t of toks) c.set(t, (c.get(t) || 0) + 1); return c; }
export function hits(text, toks, [ws, phrases]) {
  const low = text.toLowerCase();
  let n = 0;
  for (const w of ws) n += toks.get(w) || 0;
  for (const p of phrases) n += low.split(p).length - 1;
  return n;
}

export function makeCandidates(segs, minD, maxD, maxGap = 4.0) {
  const out = [];
  for (let i = 0; i < segs.length; i++) {
    for (let j = i; j < segs.length; j++) {
      if (j > i && segs[j].start - segs[j - 1].end > maxGap) break;
      const d = segs[j].end - segs[i].start;
      if (d > maxD - 0.8) break;
      if (d >= minD - 0.8) out.push([i, j]);
    }
  }
  return out;
}

export function rmsFrames(audio, sr = 16000, hop = 0.5) {
  const n = Math.floor(sr * hop), k = Math.floor(audio.length / n);
  if (k === 0) return Float32Array.from([1e-4]);
  const out = new Float32Array(k);
  for (let i = 0; i < k; i++) {
    let s = 0;
    for (let j = i * n; j < (i + 1) * n; j++) s += audio[j] * audio[j];
    out[i] = Math.sqrt(s / n + 1e-10);
  }
  return out;
}

const clip01 = (v) => Math.min(1, Math.max(0, v));
function pct(arr, p) {
  const a = Array.from(arr).sort((x, y) => x - y);
  const k = ((a.length - 1) * p) / 100, lo = Math.floor(k), hi = Math.ceil(k);
  return a[lo] + (a[hi] - a[lo]) * (k - lo);
}

export function scoreWindow(segs, i, j, chunkT0, rms, med, focus, hop = 0.5) {
  const win = segs.slice(i, j + 1);
  const start = win[0].start, end = win[win.length - 1].end;
  const dur = Math.max(end - start, 1);
  const text = win.map((x) => x.text).join(" ");
  const toks = counter(tokenize(text));
  const F = hits(text, toks, FUNNY) + 2 * (text.match(LAUGH_RE) || []).length;
  const Em = hits(text, toks, EMO);
  const R = hits(text, toks, REL);
  const [wf, we, wr] = { Funny: [1, 0.3, 0.4], Emotional: [0.3, 1, 0.4] }[focus] || [1, 1, 0.5];
  const kw = Math.min(1, (wf * F + we * Em + wr * R) / 4);
  const punct = Math.min(1, ((text.match(/!/g) || []).length + (text.match(/\?/g) || []).length) / 5);
  const wps = text.split(/\s+/).filter(Boolean).length / dur;
  const rate = clip01((wps - 1) / 2);
  const a = Math.floor(Math.max(0, (start - chunkT0) / hop)), b = Math.floor(Math.max(1, (end - chunkT0) / hop));
  let w = b > a ? rms.slice(a, b) : rms.slice(-1);
  if (!w.length) w = rms.slice(-1);
  const peak = pct(w, 95) / med;
  const audioPeak = clip01((peak - 1.5) / 3);
  const mean = w.reduce((x, y) => x + y, 0) / w.length;
  const std = Math.sqrt(w.reduce((x, y) => x + (y - mean) ** 2, 0) / w.length);
  const dyn = clip01(std / (mean + 1e-9));
  const first = win[0].text, ftoks = counter(tokenize(first));
  const hook = first.includes("?") || first.includes("!") || hits(first, ftoks, FUNNY) + hits(first, ftoks, EMO) > 0 ? 1 : 0.3;
  const last = win[win.length - 1].text.trim();
  const endOk = last && ".?!।…".includes(last[last.length - 1]) ? 1 : 0.5;
  const cov = Math.min(1, win.reduce((x, s) => x + Math.max(0, Math.min(s.end, end) - Math.max(s.start, start)), 0) / dur);
  const score = 100 * (0.3 * kw + 0.15 * punct + 0.1 * rate + 0.15 * audioPeak + 0.1 * dyn + 0.08 * hook + 0.04 * endOk + 0.08 * cov);
  const cats = { Funny: wf * F, Emotional: we * Em, Relatable: wr * R };
  const best = Object.entries(cats).sort((x, y) => y[1] - x[1])[0];
  const cat = best[1] > 0 ? best[0] : punct > 0.4 ? "Drama" : "Dialogue";
  const reason = `${cat} | keywords F${F}/E${Em}/R${R} | loud-peak x${peak.toFixed(1)} | pace ${wps.toFixed(1)} words/s`;
  return { start, end, score, category: cat, text, reason };
}

export const overlaps = (a, b, taken, gap = 2.0) => taken.some(([s, e]) => a < e + gap && b > s - gap);

// ------------------------------------------------------------------ Whisper (transformers.js)
const MODELS = { tiny: "Xenova/whisper-tiny", base: "Xenova/whisper-base", small: "Xenova/whisper-small" };
const LANG_NAMES = { hi: "hindi", en: "english" };
let TF = null;
const pipes = {};

async function transformers() {
  if (TF) return TF;
  TF = await import(new URL("../vendor/transformers/transformers.min.js", import.meta.url).href);
  TF.env.allowLocalModels = false;
  TF.env.useBrowserCache = true;
  // use the AI runtime files that ship inside the app when they are there (else they come from the internet)
  try {
    const base = new URL("../vendor/transformers/", import.meta.url).href;
    const r = await fetch(base + "ort-wasm-simd-threaded.jsep.wasm", { method: "HEAD" });
    if (r.ok) TF.env.backends.onnx.wasm.wasmPaths = base;
  } catch (e) { /* default */ }
  return TF;
}

export async function whisper(size, log) {
  const id = MODELS[size] || MODELS.base;
  if (pipes[id]) return pipes[id];
  const tf = await transformers();
  log(`Loading the Whisper '${size}' speech model (the first time it is downloaded: tiny ~40 MB, base ~80 MB, small ~250 MB; internet needed once)...`);
  let lastPct = -10;
  pipes[id] = await tf.pipeline("automatic-speech-recognition", id, {
    dtype: "q8", device: "wasm",
    progress_callback: (p) => {
      if (p.status === "progress" && p.total > 1e6) {
        const pc = Math.round(p.progress || 0);
        if (pc >= lastPct + 10) { lastPct = pc; log(`  downloading ${p.file}: ${pc}%`); }
      }
    },
  });
  log("Whisper model ready.");
  return pipes[id];
}

// segments [{start, end, text}] of a 16 kHz mono Float32Array
export async function transcribe(audio, language, size, log, offset = 0) {
  const asr = await whisper(size, log);
  const lang = LANG_NAMES[language];
  const out = await asr(audio, {
    language: lang, task: "transcribe", return_timestamps: true, chunk_length_s: 30, stride_length_s: 5,
  });
  return (out.chunks || []).filter((c) => c.text && c.text.trim()).map((c) => ({
    start: offset + (c.timestamp[0] ?? 0), end: offset + (c.timestamp[1] ?? (c.timestamp[0] ?? 0) + 2), text: c.text.trim(),
  }));
}

// word timestamps [[start, end, word]] (used to cut "um", "uh", ... out of the dialogue)
export async function transcribeWords(audio, language, log, size = "base") {
  const asr = await whisper(size, log);
  const out = await asr(audio, {
    language: LANG_NAMES[language], task: "transcribe", return_timestamps: "word", chunk_length_s: 30, stride_length_s: 5,
  });
  return (out.chunks || []).map((c) => [c.timestamp[0] ?? 0, c.timestamp[1] ?? (c.timestamp[0] ?? 0) + 0.3, String(c.text).trim()]);
}

// ------------------------------------------------------------------ the AI clip finder
export class AIEngine {
  constructor(settings, log, progress, onClip, tmpDir) {
    this.s = E.sanitize(settings);
    this.log = log; this.progress = progress; this.onClip = onClip; this.tmpDir = tmpDir;
    this.stopFlag = false;
    this.job = { current: null };
  }
  stop() { this.stopFlag = true; if (this.job.current) this.job.current.cancel(); }

  // Finds clips and reports them (start, end, score, category, text); the Simple Edit export makes the files.
  async process(movie) {
    const s = this.s, CHUNK = 600, OVER = 60;
    const info = await E.probeInfo(movie);
    const dur = info.duration;
    this.log(`Movie: ${E.basename(movie)}  (${(dur / 60).toFixed(1)} min)`);
    const taken = [];
    let count = 0, t = 0, ci = 0;
    const nChunks = Math.max(1, Math.ceil(dur / CHUNK));
    const minD = +s.min_dur, maxD = +s.max_dur, perChunk = parseInt(s.max_per_chunk, 10), maxTotal = parseInt(s.max_total, 10);
    while (t < dur - 5 && !this.stopFlag) {
      ci++;
      const last = t + CHUNK >= dur;
      const length = Math.min(CHUNK + OVER, dur - t);
      this.progress(t / dur, `Analysing ${(t / 60).toFixed(0)}-${((t + length) / 60).toFixed(0)} min  (part ${ci}/${nChunks})`);
      const audio = await D.readAudio(movie, t, length, this.tmpDir, this.job);
      if (this.stopFlag) break;
      if (audio.length > 16000 * 5) {
        const segs = await transcribe(audio, s.language, s.whisper_model, this.log, t);
        if (this.stopFlag) break;
        this.log(`  ${segs.length} sentences heard between ${E.mmss(t)} and ${E.mmss(t + length)}`);
        const rms = rmsFrames(audio);
        const pos = Array.from(rms).filter((v) => v > 1e-4);
        const med = pos.length ? pct(pos, 50) : 1e-3;
        const scored = [];
        for (const [i, j] of makeCandidates(segs, minD, maxD)) {
          if (!last && segs[i].start >= t + CHUNK) continue;
          scored.push(scoreWindow(segs, i, j, t, rms, med, s.focus));
        }
        scored.sort((a, b) => b.score - a.score);
        const pool = [], rng = [];
        for (const c of scored) {
          if (c.score < s.min_score) break;
          if (overlaps(c.start, c.end, [...taken, ...rng])) continue;
          pool.push(c); rng.push([c.start, c.end]);
          if (pool.length >= perChunk) break;
        }
        for (const c of pool) {
          if (this.stopFlag || (maxTotal && count >= maxTotal)) break;
          const st = Math.max(0, c.start - 0.3);
          const d = Math.min(c.end + 0.5 - st, maxD);
          count++;
          taken.push([st, st + d]);
          this.onClip({ n: count, start: st, end: Math.min(dur, st + d), score: c.score, category: c.category, text: c.text, reason: c.reason });
          this.log(`  clip ${count}: ${E.mmss(st)} - ${E.mmss(st + d)}  score ${c.score.toFixed(0)}  (${c.category})`);
        }
        if (maxTotal && count >= maxTotal) { this.log("Reached max total clips."); break; }
      }
      t += CHUNK;
    }
    this.progress(this.stopFlag ? t / dur : 1, this.stopFlag ? "Stopped." : `Done - ${count} clips found.`);
    this.log(`Finished. ${count} clips found.`);
    return count;
  }
}
