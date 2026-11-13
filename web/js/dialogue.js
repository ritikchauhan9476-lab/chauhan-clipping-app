// Dialogue detection (port of the desktop dialogue.py): finds where people are TALKING in one time range.
// 1. FFmpeg extracts the range's audio (16 kHz mono).
// 2. Speech detection: Silero VAD (small neural network, onnxruntime) or the built-in voice-band detector.
// 3. Optional text editing: Whisper word timestamps; the words you list are cut out.
// 4. The export cuts picture AND sound to exactly those pieces in one FFmpeg pass.
import * as E from "./engine.js";
import { bridge } from "./bridge.js";

export const PAD_MS = 150;
export const MIN_SIL_MS = 300;
export const FADE = 0.02;
export const MIN_KEEP = 0.3;
export const HOP = 0.03;
export const MERGE_GAP = 0.15;
export const MIN_PIECE = 1.0;
export const SCENE_THR = 0.25;
export const FLASH_SHOT = 0.3;
export const MAX_CUT_RATE = 1.0;
export const SNAP = 0.5;
export const MONTAGE_DROP = 2.5;   // a fast-cut montage piece is skipped only when it is shorter (longer = real talking)

// Audio of [start, start+length] as 16 kHz mono float samples (only that range is decoded).
export async function readAudio(movie, start, length, tmpDir, job = null) {
  const raw = E.join(tmpDir, `raw_${Math.round(start * 1000)}_${Math.round(length * 1000)}_${Date.now()}.s16`);
  const r = await E.ffrun(["-nostdin", "-y", "-v", "error", "-ss", start.toFixed(3), "-t", length.toFixed(3), "-i", movie,
    "-vn", "-ac", "1", "-ar", "16000", "-f", "s16le", "-c:a", "pcm_s16le", raw], { job });
  if (r.code !== 0) {
    await bridge().remove(raw);
    if (/does not contain any stream|matches no streams|Output file #0 does not contain/i.test(r.stderr || "")) return new Float32Array(0);
    throw new Error(String(r.stderr || "ffmpeg failed").slice(-300));
  }
  const bytes = await bridge().readBytes(raw);
  await bridge().remove(raw);
  if (!bytes) return new Float32Array(0);
  const n = Math.floor(bytes.length / 2);
  const dv = new DataView(bytes.buffer, bytes.byteOffset, n * 2);
  const x = new Float32Array(n);
  for (let i = 0; i < n; i++) x[i] = dv.getInt16(i * 2, true) / 32768;
  return x;
}

export function frameDb(x, sr, hop = HOP) {
  const f = Math.floor(sr * hop), n = Math.floor(x.length / f);
  const out = new Float32Array(n);
  for (let i = 0; i < n; i++) {
    let s = 0;
    for (let j = i * f; j < (i + 1) * f; j++) s += x[j] * x[j];
    out[i] = 20 * Math.log10(Math.sqrt(s / f + 1e-12));
  }
  return out;
}

// ------------------------------------------------------------------ speech detection
// tailMs: padding AFTER speech (a sentence end fades out slowly, so it needs more than the start); default = padMs
export function finishRegions(regs, total, padMs, minSilMs, tailMs = null) {
  const gap = minSilMs / 1000, pad = padMs / 1000;
  const tail = tailMs == null ? pad : Math.max(0, tailMs / 1000);
  const merged = [];
  for (const [s, e] of regs) {
    if (merged.length && s - merged[merged.length - 1][1] < gap) merged[merged.length - 1][1] = Math.max(merged[merged.length - 1][1], e);
    else merged.push([s, e]);
  }
  const padded = merged.map(([s, e]) => [Math.max(0, s - pad), Math.min(total, e + tail)]);
  const out = [];
  for (const [s, e] of padded) {
    if (out.length && s - out[out.length - 1][1] < MERGE_GAP) out[out.length - 1][1] = Math.max(out[out.length - 1][1], e);
    else out.push([s, e]);
  }
  return out.filter(([s, e]) => e - s > 0.05);
}

function fftPower(re, im) {
  const n = re.length;
  for (let i = 1, j = 0; i < n; i++) {
    let bit = n >> 1;
    for (; j & bit; bit >>= 1) j ^= bit;
    j ^= bit;
    if (i < j) { [re[i], re[j]] = [re[j], re[i]]; [im[i], im[j]] = [im[j], im[i]]; }
  }
  for (let len = 2; len <= n; len <<= 1) {
    const ang = (-2 * Math.PI) / len, wr = Math.cos(ang), wi = Math.sin(ang);
    for (let i = 0; i < n; i += len) {
      let cr = 1, ci = 0;
      for (let k = 0; k < len / 2; k++) {
        const a = i + k, b = a + len / 2;
        const tr = re[b] * cr - im[b] * ci, ti = re[b] * ci + im[b] * cr;
        re[b] = re[a] - tr; im[b] = im[a] - ti; re[a] += tr; im[a] += ti;
        const t = cr * wr - ci * wi; ci = cr * wi + ci * wr; cr = t;
      }
    }
  }
}

function percentile(arr, p) {
  const a = Array.from(arr).sort((x, y) => x - y);
  if (!a.length) return 0;
  const k = ((a.length - 1) * p) / 100, lo = Math.floor(k), hi = Math.ceil(k);
  return a[lo] + (a[hi] - a[lo]) * (k - lo);
}

// Fallback detector (no AI): a 30 ms frame is speech when its 250-3800 Hz energy is clearly above the room noise
// AND most of its energy is in the voice band.
export function voiceBandRegions(x, sr) {
  const f = Math.floor(sr * HOP), n = Math.floor(x.length / f);
  if (n < 3) return [];
  const N = 512;
  const win = new Float32Array(f);
  for (let i = 0; i < f; i++) win[i] = 0.5 - 0.5 * Math.cos((2 * Math.PI * i) / (f - 1));
  const lo = Math.ceil((250 * N) / sr), hi = Math.floor((3800 * N) / sr);
  const db = new Float32Array(n), ratio = new Float32Array(n);
  const re = new Float64Array(N), im = new Float64Array(N);
  for (let i = 0; i < n; i++) {
    re.fill(0); im.fill(0);
    for (let j = 0; j < f; j++) re[j] = x[i * f + j] * win[j];
    fftPower(re, im);
    let eb = 1e-12, ea = 1e-12;
    for (let k = 0; k <= N / 2; k++) {
      const p = re[k] * re[k] + im[k] * im[k];
      ea += p;
      if (k >= lo && k <= hi) eb += p;
    }
    db[i] = 10 * Math.log10(eb);
    ratio[i] = eb / ea;
  }
  const floor = percentile(db, 10), peak = percentile(db, 95);
  const thr = floor + Math.max(8, (peak - floor) * 0.35);
  const active = new Uint8Array(n);
  for (let i = 0; i < n; i++) active[i] = db[i] > thr && ratio[i] > 0.35 ? 1 : 0;
  let i = 0;
  while (i < n) {
    if (!active[i]) {
      let j = i;
      while (j < n && !active[j]) j++;
      if (i > 0 && j < n && (j - i) * HOP < 0.09) active.fill(1, i, j);
      i = j;
    } else i++;
  }
  const regs = [];
  let start = null;
  for (let k = 0; k < n; k++) {
    if (active[k] && start === null) start = k * HOP;
    else if (!active[k] && start !== null) { regs.push([start, k * HOP]); start = null; }
  }
  if (start !== null) regs.push([start, n * HOP]);
  return regs.filter(([s, e]) => e - s >= 0.15);
}

// ------------------------------------------------------------------ Silero VAD (onnxruntime-web, bundled)
let silero = null, sileroFailed = false;
const warned = {};

async function loadScript(src) {
  return new Promise((resolve, reject) => {
    const el = document.createElement("script");
    el.src = src; el.onload = resolve; el.onerror = () => reject(new Error("could not load " + src));
    document.head.appendChild(el);
  });
}

async function getSilero() {
  if (silero) return silero;
  if (sileroFailed || typeof window === "undefined") throw new Error("Silero not available");
  try {
    if (!window.ort) await loadScript("vendor/ort/ort.wasm.min.js");
    const ort = window.ort;
    ort.env.wasm.wasmPaths = new URL("vendor/ort/", location.href).href;
    ort.env.wasm.numThreads = 1;
    const sess = await ort.InferenceSession.create("vendor/silero_vad.onnx", { executionProviders: ["wasm"] });
    silero = { ort, sess };
    return silero;
  } catch (e) {
    sileroFailed = true;
    throw e;
  }
}

async function sileroProbs(x) {
  const { ort, sess } = await getSilero();
  const W = 512, C = 64;
  const n = Math.ceil(x.length / W);
  let state = new ort.Tensor("float32", new Float32Array(2 * 128), [2, 1, 128]);
  const sr = new ort.Tensor("int64", BigInt64Array.from([16000n]), []);
  const ctx = new Float32Array(C);
  const out = new Float32Array(n);
  const inName = sess.inputNames;
  for (let i = 0; i < n; i++) {
    const buf = new Float32Array(C + W);
    buf.set(ctx, 0);
    buf.set(x.subarray(i * W, Math.min(x.length, (i + 1) * W)), C);
    const feeds = {};
    feeds[inName.includes("input") ? "input" : inName[0]] = new ort.Tensor("float32", buf, [1, C + W]);
    feeds[inName.includes("state") ? "state" : inName[1]] = state;
    feeds[inName.includes("sr") ? "sr" : inName[2]] = sr;
    const res = await sess.run(feeds);
    const outs = sess.outputNames;
    out[i] = res[outs[0]].data[0];
    state = res[outs[1]];
    ctx.set(buf.subarray(buf.length - C));
  }
  return out;
}

export function probsToRegions(p, step, threshold = 0.5, minSpeech = 0.2) {
  const neg = Math.max(threshold - 0.15, 0.01);
  const regs = [];
  let start = null;
  p.forEach((v, i) => {
    if (start === null) { if (v >= threshold) start = i * step; }
    else if (v < neg) { regs.push([start, i * step]); start = null; }
  });
  if (start !== null) regs.push([start, p.length * step]);
  return regs.filter(([s, e]) => e - s >= minSpeech);
}

export async function detectSpeech(x, padMs, minSilMs, log, tailMs = null, threshold = 0.5) {
  const total = x.length / 16000;
  try {
    const regs = probsToRegions(await sileroProbs(x), 512 / 16000, threshold);
    return [finishRegions(regs, total, padMs, minSilMs, tailMs), "Silero AI"];
  } catch (e) {
    if (!warned.silero) {
      warned.silero = true;
      log(`Silero AI speech detector is not available (${String(e.message || e).slice(0, 100)}) - using the built-in detector.`);
    }
  }
  return [finishRegions(voiceBandRegions(x, 16000), total, padMs, minSilMs, tailMs), "built-in detector"];
}

// ------------------------------------------------------------------ word removal helpers
export function removalSpans(words, removeList, pad = 0.03) {
  const targets = new Set(removeList.map((w) => w.trim().toLowerCase()).filter(Boolean));
  const out = [];
  for (const [s, e, w] of words || []) {
    const clean = String(w).replace(/[^\p{L}\p{N}_]/gu, "").toLowerCase();
    if (clean && targets.has(clean)) out.push([Math.max(0, s - pad), e + pad]);
  }
  return out;
}

export function subtract(spans, cuts) {
  for (const [cs, ce] of [...cuts].sort((a, b) => a[0] - b[0])) {
    const nxt = [];
    for (const [s, e] of spans) {
      if (ce <= s || cs >= e) { nxt.push([s, e]); continue; }
      if (cs > s) nxt.push([s, cs]);
      if (ce < e) nxt.push([ce, e]);
    }
    spans = nxt;
  }
  return spans;
}

// ------------------------------------------------------------------ smoother cuts
export function smoothPieces(regs, total, minPiece = MIN_PIECE) {
  const out = [];
  for (let [s, e] of [...regs].sort((a, b) => a[0] - b[0])) {
    if (e - s < minPiece) {
      const extra = (minPiece - (e - s)) / 2;
      s = Math.max(0, s - extra); e = Math.min(total, e + extra);
    }
    if (out.length && s <= out[out.length - 1][1] + MERGE_GAP) out[out.length - 1][1] = Math.max(out[out.length - 1][1], e);
    else out.push([s, e]);
  }
  return out;
}

export async function sceneCuts(movie, start, end, thr = SCENE_THR, job = null) {
  let crop = null;
  try { crop = await E.detectCrop(movie, (await E.probeInfo(movie)).duration); } catch (e) { crop = null; }
  const vf = (crop ? crop + "," : "") + `scale=160:-2:flags=fast_bilinear,select='gt(scene,${thr})',showinfo`;
  const r = await E.ffrun(["-nostdin", "-hide_banner", "-v", "info", "-skip_frame", "noref", "-ss", start.toFixed(3), "-t", Math.max(0.1, end - start).toFixed(3),
    "-i", movie, "-an", "-sn", "-vf", vf, "-f", "null", "-"], { job });
  return [...String(r.stderr).matchAll(/pts_time:([0-9.]+)/g)].map((m) => start + parseFloat(m[1])).sort((a, b) => a - b);
}

export function isMontage(s, e, cuts) {
  const inside = cuts.filter((c) => s < c && c < e);
  if (inside.length < 2) return false;
  const gaps = inside.slice(1).map((b, i) => b - inside[i]);
  if (Math.min(...gaps) < FLASH_SHOT) return true;
  return inside.length >= 3 && e - s >= 2 && inside.length / (e - s) > MAX_CUT_RATE;
}

// Drops fast-cut montage pieces and moves every start / end onto a nearby shot change. Returns [pieces, dropped, snapped].
export function pictureFix(regs, cuts, pad, lo, hi) {
  const kept = [];
  let dropped = 0, snapped = 0;
  const nearest = (arr, t) => arr.reduce((b, c) => (Math.abs(c - t) < Math.abs(b - t) ? c : b));
  for (let [s, e] of regs) {
    if (e - s < MONTAGE_DROP && isMontage(s, e, cuts)) { dropped++; continue; }   // short flash-cut burst only
    const s0 = s, e0 = e;
    let near = cuts.filter((c) => s - SNAP <= c && c <= s + pad);
    if (near.length) { const c = nearest(near, s); snapped += c !== s ? 1 : 0; s = c; }
    near = cuts.filter((c) => e - pad < c && c <= e + SNAP);
    if (near.length) { const c = nearest(near, e); snapped += c !== e ? 1 : 0; e = c; }
    let sl = cuts.filter((c) => s < c && c <= s + FLASH_SHOT && c <= s0 + pad);
    if (sl.length) { s = Math.max(...sl); snapped++; }
    sl = cuts.filter((c) => e - FLASH_SHOT <= c && c < e && c >= e0 - pad);
    if (sl.length) { e = Math.min(...sl); snapped++; }
    s = Math.max(lo, s); e = Math.min(hi, e);
    if (e - s > 0.05) kept.push([s, e]);
  }
  const out = [];
  for (const [s, e] of kept) {
    if (out.length && s <= out[out.length - 1][1] + 0.02) out[out.length - 1][1] = Math.max(out[out.length - 1][1], e);
    else out.push([s, e]);
  }
  return [out, dropped, snapped];
}

// Final clean-up: pauses shorter than minGap are NOT cut (a tiny cut only makes the picture jump - a flash cut),
// and no piece is shorter than minPiece.
export function tidy(regs, lo, hi, minPiece, minGap) {
  const out = [];
  for (const [s, e] of [...regs].sort((a, b) => a[0] - b[0])) {
    if (out.length && s - out[out.length - 1][1] < minGap) out[out.length - 1][1] = Math.max(out[out.length - 1][1], e);
    else out.push([s, e]);
  }
  const res = [];
  for (let [s, e] of out) {
    if (e - s < minPiece) { const x = (minPiece - (e - s)) / 2; s = Math.max(lo, s - x); e = Math.min(hi, e + x); }
    if (res.length && s <= res[res.length - 1][1] + MERGE_GAP) res[res.length - 1][1] = Math.max(res[res.length - 1][1], e);
    else res.push([s, e]);
  }
  return res;
}

// ------------------------------------------------------------------ clean start / end (Simple Edit)
// Looks ONLY at the first `seconds` of the part [a, b]: a silent (voice=true: or not talking) start is cut, never more
// than `seconds`. Returns [newStart, info].
export async function trimStart(movie, a, b, seconds, voice, noiseDb, tmpDir, log, job = null) {
  seconds = Math.max(0.5, +seconds);
  const winEnd = Math.min(b, a + seconds + 1.5);
  if (winEnd - a < 1) return [a, "part too short, left as it is"];
  let lead = 0, how = "";
  if (voice) {
    const info = await findSpeech(movie, a, winEnd, { pad_ms: 100, min_sil_ms: 300, min_piece: 0.3, vad: true }, tmpDir, log, job);
    if (String(info.detector).startsWith("off")) voice = false;
    else {
      const regs = info.regions.filter((r) => r[1] - r[0] >= 0.15);
      lead = regs.length ? regs[0][0] - a : seconds;
      how = "first words";
    }
  }
  if (!voice) {
    const sil = await E.detectSilence(movie, noiseDb, 0.3, null, job, [[a, winEnd]]);
    const first = sil.find((x) => x[0] <= a + 0.15);
    lead = first ? Math.max(0, first[1] - a - 0.12) : 0;
    how = "end of the silence";
  }
  lead = Math.min(lead, seconds);
  if (lead < 0.25 || b - a - lead < 1) return [a, "starts with talking already"];
  return [a + lead, `${lead.toFixed(2)}s cut (${how})`];
}

// The mirror: only the last `seconds`; the video ends right after the last words. Returns [newEnd, info].
export async function trimEnd(movie, a, b, seconds, voice, noiseDb, tmpDir, log, job = null) {
  seconds = Math.max(0.5, +seconds);
  const winStart = Math.max(a, b - seconds - 1.5);
  if (b - winStart < 1) return [b, "part too short, left as it is"];
  let trail = 0, how = "";
  if (voice) {
    const info = await findSpeech(movie, winStart, b, { pad_ms: 100, tail_ms: 350, min_sil_ms: 300, min_piece: 0.3, vad: true }, tmpDir, log, job);
    if (String(info.detector).startsWith("off")) voice = false;
    else {
      const regs = info.regions.filter((r) => r[1] - r[0] >= 0.15);
      trail = regs.length ? b - regs[regs.length - 1][1] : seconds;
      how = "last words";
    }
  }
  if (!voice) {
    const sil = await E.detectSilence(movie, noiseDb, 0.3, null, job, [[winStart, b]]);
    const last = [...sil].reverse().find((x) => x[1] >= b - 0.15);
    trail = last ? Math.max(0, b - last[0] - 0.3) : 0;
    how = "start of the final silence";
  }
  trail = Math.min(trail, seconds);
  if (trail < 0.25 || b - trail - a < 1) return [b, "ends with talking already"];
  return [b - trail, `${trail.toFixed(2)}s cut at the end (${how})`];
}

// ------------------------------------------------------------------ one range
// Where is anyone talking between start and end (movie seconds)?
// Returns {regions: [[abs_start, abs_end], ...], contour: [abs_t0, hop, dB array], detector}
export async function findSpeech(movie, start, end, opts, tmpDir, log, job = null) {
  const length = Math.max(0.1, end - start);
  const x = await readAudio(movie, start, length, tmpDir, job);
  const total = x.length / 16000;
  const pad = parseInt(opts.pad_ms ?? PAD_MS, 10);
  const minsil = parseInt(opts.min_sil_ms ?? MIN_SIL_MS, 10);
  let regs, name;
  if (!x.length) { regs = []; name = "no sound"; }
  else if (opts.vad !== false) [regs, name] = await detectSpeech(x, pad, minsil, log, opts.tail_ms == null ? null : +opts.tail_ms, +(opts.vad_threshold ?? 0.5));
  else { regs = [[0, total]]; name = "off (whole range kept)"; }
  const remove = String(opts.remove_words || "").split(/[,;]/).filter((w) => w.trim());
  if (regs.length && opts.whisper && remove.length) {
    try {
      const AI = await import("./ai.js");
      const words = await AI.transcribeWords(x, opts.language || "", log, opts.whisper_model || "base");
      if (words) {
        const cuts = removalSpans(words, remove);
        regs = subtract(regs, cuts).filter(([s, e]) => e - s >= MIN_KEEP);
        log(`  text editing: ${words.length} words, ${cuts.length} removed`);
      }
    } catch (e) {
      log(`Text editing skipped (Whisper failed: ${String(e.message || e).slice(0, 150)}). Silence cutting still applied.`);
    }
  }
  const minPiece = parseFloat(opts.min_piece ?? MIN_PIECE), minGap = (+opts.min_cut_ms || 0) / 1000;
  regs = smoothPieces(regs, total, minPiece);
  if (minGap > 0) regs = tidy(regs, 0, total, minPiece, minGap);
  let absRegs = regs.map(([s, e]) => [start + s, start + e]);
  if (opts.scan_picture && absRegs.length) {
    const cuts = await sceneCuts(movie, start, end, SCENE_THR, job);
    let dropped, snapped;
    [absRegs, dropped, snapped] = pictureFix(absRegs, cuts, pad / 1000, start, end);
    if (minGap > 0) absRegs = tidy(absRegs, start, end, minPiece, minGap);   // snapping can leave slivers
    log(`  picture scan: ${cuts.length} shot changes, ${dropped} fast-cut montage piece(s) skipped, ${snapped} cut(s) moved onto a shot change`);
  }
  return { regions: absRegs, contour: [start, HOP, frameDb(x, 16000)], detector: name };
}

export async function analyze(movie, start, end, opts, tmpDir, log, job = null) {
  const info = await findSpeech(movie, start, end, opts, tmpDir, log, job);
  log(`  speech detection: ${info.detector}, ${info.regions.length} pieces (padding ${opts.pad_ms ?? PAD_MS} ms, min silence ${opts.min_sil_ms ?? MIN_SIL_MS} ms)`);
  return info.regions.filter(([s, e]) => e - s >= MIN_KEEP).map(([s, e]) => [s, e - s]);
}

// ------------------------------------------------------------------ helpers for building clips
export function quietestPoint(contour, lo, hi) {
  const [t0, hop, db] = contour;
  if (db.length < 3) return (lo + hi) / 2;
  const a = Math.max(0, Math.floor((lo - t0) / hop)), b = Math.min(db.length, Math.floor((hi - t0) / hop) + 1);
  if (b - a < 3) return (lo + hi) / 2;
  let best = a, bestV = Infinity;
  for (let i = a; i < b; i++) {
    const v = ((i > a ? db[i - 1] : 0) + db[i] + (i + 1 < b ? db[i + 1] : 0)) / 3;   // same as np.convolve 'same'
    if (v < bestV) { bestV = v; best = i; }
  }
  return t0 + best * hop;
}

export function splitLong(regions, contour, cap) {
  const out = [];
  for (let [s, e] of regions) {
    while (e - s > cap * 1.15) {
      let t = quietestPoint(contour, s + cap * 0.5, s + cap);
      t = Math.min(Math.max(t, s + 0.5), e - 0.5);
      out.push([s, t]);
      s = t;
    }
    out.push([s, e]);
  }
  return out;
}

export function joinAdjacent(pieces, eps = 0.02) {
  const out = [];
  for (const [s, e] of pieces) {
    if (out.length && s - out[out.length - 1][1] <= eps) out[out.length - 1][1] = Math.max(out[out.length - 1][1], e);
    else out.push([s, e]);
  }
  return out.map(([s, e]) => [s, e - s]);
}
