// Auto Short (port of the desktop auto_short.py): continuous-dialogue shorts, made clip by clip.
// The movie (or the chosen range / parts) is scanned in small chunks. As soon as enough dialogue has been found
// for one short, that short is cut and exported while the scan goes on. Silence is removed from the picture AND
// the sound. Stop + Continue: the resume point is saved after every chunk and every short (_resume.json).
import * as D from "./dialogue.js";
import * as E from "./engine.js";
import { bridge } from "./bridge.js";

export const MIN_LEN = 45;
export const MAX_LEN = 59;
export const CHUNK = 120;
export const GOOD_GAP = 1.0;
export const MAX_PIECES = 120;

export const pieceCap = (minLen, maxLen) => Math.min(12, Math.max(1, (maxLen - minLen) * 0.9));
export const totalLen = (buf) => buf.reduce((a, [s, e]) => a + (e - s), 0);

// buf: [[start, end], ...] in time order. Returns [group, rest], or null when more dialogue is needed.
export function pickGroup(buf, minLen, maxLen, final = false) {
  let total = 0, n = 0;
  for (const [s, e] of buf) {
    if (total + (e - s) > maxLen) break;
    total += e - s;
    n++;
  }
  const overflow = n < buf.length;
  if (!overflow) {
    if (final && total >= minLen) return [buf, []];
    return null;
  }
  if (total < minLen) return null;
  let bestK = n, bestGap = -1, acc = 0;
  for (let k = 1; k <= n; k++) {
    acc += buf[k - 1][1] - buf[k - 1][0];
    if (acc >= minLen && k < buf.length) {
      const gap = buf[k][0] - buf[k - 1][1];
      if (gap >= GOOD_GAP && gap >= bestGap) { bestK = k; bestGap = gap; }
    }
  }
  return [buf.slice(0, bestK), buf.slice(bestK)];
}

// [[start, length], ...]: if there are too many, the smallest gaps are bridged (nothing is dropped).
export function limitPieces(pieces, maxN = MAX_PIECES) {
  pieces = pieces.map((p) => [...p]);
  while (pieces.length > maxN) {
    let bi = 0, bg = Infinity;
    for (let i = 0; i < pieces.length - 1; i++) {
      const g = pieces[i + 1][0] - (pieces[i][0] + pieces[i][1]);
      if (g < bg) { bg = g; bi = i; }
    }
    pieces[bi][1] = pieces[bi + 1][0] + pieces[bi + 1][1] - pieces[bi][0];
    pieces.splice(bi + 1, 1);
  }
  return pieces;
}

// Overlay / text items of the Simple Edit tab -> items timed from the START of a short.
export function relativeItems(items, total, number) {
  const ovs = [], txs = [], auds = [];
  for (const it of items) {
    const d = { ...it };
    const rs = +it.rel_start || 0, re = +it.rel_end || 0;
    d.start = rs;
    d.end = re > 0 ? Math.min(total, re) : total;
    if (it.kind === "text") d.text = String(it.text || "").split("{n}").join(String(number));
    if (d.end <= d.start) continue;
    (it.kind === "overlay" ? ovs : it.kind === "audio" ? auds : txs).push(d);
  }
  return [ovs, txs, auds];
}

export class AutoShortJob {
  // ranges: [[start, end], ...] in movie seconds. A short never mixes dialogue from two different ranges.
  constructor({ movie, ranges, opts, settings, items, outDir, tmpDir, log, progress, onShort, minLen = MIN_LEN,
    maxLen = MAX_LEN, firstNumber = 1, keepLast = false, chunk = CHUNK, allRanges = null, indexBase = 0,
    priorMade = null, onResume = null }) {
    Object.assign(this, { movie, ranges, items, outDir, tmpDir, log, progress, onShort, keepLast, onResume });
    this.opts = { ...opts };
    this.minLen = +minLen; this.maxLen = +maxLen;
    this.number = parseInt(firstNumber, 10) || 1;
    this.chunk = +chunk;
    const s = { ...settings, _denoise: !!(opts.denoise ?? true), _joint_fade: D.FADE, fade_sec: 0.05 };
    s._boost = opts.boost && Object.keys(opts.boost).length ? { ...E.BOOST_DEFAULT, ...opts.boost } : {};   // retention boost
    this.runner = new E.Runner(s, log, null, null, tmpDir);
    this.made = 0;
    this.stopped = false;
    this.allRanges = (allRanges || ranges).map((r) => r.map(Number));
    this.indexBase = parseInt(indexBase, 10) || 0;
    this.madeList = [...(priorMade || [])];
    this.ri = 0;
    this.job = { current: null };
  }

  stop() {
    this.stopped = true;
    this.runner.stop();
    if (this.job.current) this.job.current.cancel();
  }

  get resumePos() { return this._resumePos ?? this.ranges[0][0]; }

  async run() {
    this.info = await E.probeInfo(this.movie);
    this.crop = this.runner.s.auto_crop ? await E.detectCrop(this.movie, this.info.duration) : null;
    if (this.crop) this.log(`Black bars detection: ${this.crop}`);
    this.base = E.safeName(this.movie).slice(0, 40);
    await bridge().mkdirs(this.outDir);
    this.spanTotal = Math.max(1, this.ranges.reduce((a, [x, y]) => a + (y - x), 0));
    this.spanDone = 0;
    await this.mark(this.ranges[0][0]);
    let carry = [];
    for (let ri = 0; ri < this.ranges.length; ri++) {
      if (this.stopped) break;
      this.ri = ri;
      const [a, b] = this.ranges[ri];
      if (this.ranges.length > 1) this.log(`--- Range ${ri + 1}/${this.ranges.length}: ${E.mmss(a)} - ${E.mmss(b)} ---`);
      // ranges that follow each other directly (e.g. many 45 s parts) are one stretch of movie: the dialogue left over
      // at the end of one range goes on into the next range instead of being thrown away
      const joins = ri + 1 < this.ranges.length && Math.abs(this.ranges[ri + 1][0] - b) < 1;
      carry = (await this.scanRange(a, b, carry, !joins)) || [];
      if (this.stopped) break;
      this.spanDone += b - a;
      if (ri + 1 < this.ranges.length) { this.ri = ri + 1; await this.mark(this.ranges[ri + 1][0]); }
      else await this.mark(b, true);
    }
    if (this.stopped) this.progress(this.spanDone / this.spanTotal, `Stopped - ${this.made} short(s) ready. You can continue from ${E.mmss(this.resumePos)}.`);
    else this.progress(1, `Done - ${this.made} short(s) ready.`);
    this.log(`Finished. ${this.made} short(s) in: ${this.outDir}`);
    return this.made;
  }

  async scanRange(a, b, carry = [], flush = true) {
    const cap = pieceCap(this.minLen, this.maxLen);
    let buf = [...carry], t = a;
    while (t < b - 0.5 && !this.stopped) {
      const cEnd = Math.min(b, t + this.chunk);
      let info;
      try {
        info = await D.findSpeech(this.movie, t, cEnd, this.opts, this.tmpDir, this.log, this.job);
      } catch (e) {
        if (this.stopped) break;
        throw e;
      }
      if (this.stopped) break;
      let regs = info.regions, nxt = cEnd;
      if (cEnd < b - 0.5 && regs.length) {
        const [ls, le] = regs[regs.length - 1];
        if (le >= cEnd - 0.35 && ls > t + 1.0) { regs = regs.slice(0, -1); nxt = ls; }   // speech runs past the edge
      }
      regs = D.splitLong(regs, info.contour, cap);
      buf.push(...regs);
      const speech = regs.reduce((x, [s, e]) => x + (e - s), 0);
      this.log(`[${E.mmss(t)} - ${E.mmss(cEnd)}] ${info.detector}: ${regs.length} dialogue pieces, ${speech.toFixed(0)}s of talking`);
      t = nxt;
      this.progress((this.spanDone + (t - a)) / this.spanTotal, `Scanned up to ${E.mmss(t)} - ${this.made} short(s) ready`);
      await this.mark(buf.length ? Math.min(buf[0][0], t) : t);
      while (!this.stopped) {
        const g = pickGroup(buf, this.minLen, this.maxLen);
        if (!g) break;
        let group;
        [group, buf] = g;
        if (!(await this.render(group))) buf = [...group, ...buf];   // stopped in the middle: still to do
        await this.mark(buf.length ? Math.min(buf[0][0], t) : t);
      }
    }
    if (!flush && !this.stopped) {
      if (buf.length) this.log(`${totalLen(buf).toFixed(0)}s of dialogue carried on into the next range (not enough for a short yet).`);
      return buf;
    }
    while (buf.length && !this.stopped) {
      const g = pickGroup(buf, this.minLen, this.maxLen, true);
      if (g) {
        let group;
        [group, buf] = g;
        if (!(await this.render(group))) { buf = [...group, ...buf]; await this.mark(buf[0][0]); break; }
        continue;
      }
      const left = totalLen(buf);
      if (this.keepLast && left >= 3) {
        this.log(`Last short is only ${left.toFixed(0)}s (shorter than ${this.minLen.toFixed(0)}s) - kept as you asked.`);
        if (!(await this.render(buf))) await this.mark(buf[0][0]);
      } else {
        this.log(`${left.toFixed(0)}s of dialogue left at the end of this range, shorter than ${this.minLen.toFixed(0)}s - no short made from it.`);
      }
      break;
    }
  }

  async mark(pos, finished = false) {
    this._resumePos = +pos;
    const info = {
      movie: this.movie, ranges: this.allRanges, range_index: this.indexBase + this.ri, pos: Math.round(+pos * 1000) / 1000,
      next_number: this.number, finished: !!finished, out_dir: this.outDir, made: this.madeList,
    };
    try {
      const tmp = E.join(this.outDir, "_resume.json.tmp");
      await bridge().writeText(tmp, JSON.stringify(info));
      await bridge().rename(tmp, E.join(this.outDir, "_resume.json"));
    } catch (e) { /* not fatal */ }
    if (this.onResume) this.onResume(info);
  }

  // Exports one short. Returns false when it was stopped in the middle (nothing is kept of it).
  // 'PART n' label and optional opening text for the first seconds of a short
  boostTexts(n, total) {
    const bo = this.runner.s._boost || {}, out = [], end = Math.min(3, total);
    if (bo.hook) out.push({ ...E.TEXT_DEFAULT, text: String(bo.hook).split("{n}").join(String(n)), start: 0, end, size: 7, pos: "Custom", hcenter: true, y: 18, outline: 3, box: true, box_opacity: 45, bold: true });
    if (bo.part_label) out.push({ ...E.TEXT_DEFAULT, text: `PART ${n}`, start: 0, end, size: 4.5, pos: "Top-Center", hcenter: true, outline: 2, shadow: true });
    return out;
  }

  async render(group) {
    const pieces = limitPieces(D.joinAdjacent(group));
    const total = pieces.reduce((a, [, d]) => a + d, 0);
    const n = this.number;
    this.number++;
    const mm = Math.floor(pieces[0][0] / 60), ss = Math.floor(pieces[0][0] % 60);
    const name = `${this.base}_short${String(n).padStart(2, "0")}_${E.pad2(mm)}m${E.pad2(ss)}s.mp4`;
    const final = E.join(this.outDir, name);
    const [ovs, txs, auds] = relativeItems(this.items, total, n);
    const S = { ...this.runner.s, overlays: ovs, texts: [...txs, ...this.boostTexts(n, total)], audios: auds };
    const shortest = Math.min(...pieces.map(([, d]) => d));
    this.log(`Short ${n}: ${total.toFixed(1)}s of dialogue from ${E.mmss(pieces[0][0])} - ${pieces.length} piece(s), ` +
      `${pieces.length - 1} cut(s), shortest piece ${shortest.toFixed(1)}s, average ${(total / pieces.length).toFixed(1)}s - exporting ...`);
    const ok = await this.runner.cut(this.movie, pieces[0][0], total, final, this.info, this.crop, S, pieces);
    if (this.stopped) {
      this.number = n;                     // this number is used again when you continue
      await bridge().remove(final);
      await bridge().remove(final + ".part");
      return false;
    }
    if (ok) {
      this.made++;
      const d = { path: final, name, number: n, length: total, start: pieces[0][0] };
      this.madeList.push(d);
      this.log(`Short ${n} ready: ${name}`);
      this.onShort(d);
    } else this.log(`Short ${n} failed (see the error above).`);
    return true;
  }
}
