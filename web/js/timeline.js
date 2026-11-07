// Timeline (advanced): a CapCut-style layered editor (port of the desktop app.py Timeline + model.py).
// Text, overlay and audio blocks on 3 layers each, on top of the movie. Zoom from 0.05 to 600 pixels per second
// (pinch, buttons, slider, Fit all), drag a block to move it, drag its edge to trim, tap the ruler for the playhead.
import * as E from "./engine.js";
import * as CL from "./colour.js";
import * as P from "./preview.js";
import { FONTS } from "./textrender.js";
import { bridge } from "./bridge.js";
import { chooseMedia, showOutputs, resultRow } from "./files.js";
import {
  h, clear, section, note, button, NumField, selectField, checkField, textField, colorField, Progress, LogBox, Chips,
  alertBox, sheet, toast,
} from "./ui.js";

const RULER_H = 24, TRACK_H = 26, PAD_X = 12, MIN_LEN = 0.2;
const TRACKS = [["T", 3], ["T", 2], ["T", 1], ["O", 3], ["O", 2], ["O", 1], ["V", 1], ["A", 1], ["A", 2], ["A", 3]];
const KIND_KEY = { text: "texts", overlay: "overlays", audio: "audios" };
const KIND_LETTER = { text: "T", overlay: "O", audio: "A" };
const KIND_NAME = { text: "Text", overlay: "Overlay", audio: "Audio" };
const DEF = { text: E.TEXT_DEFAULT, overlay: E.OVERLAY_DEFAULT, audio: E.AUDIO_DEFAULT };
const FILL = { text: "#1B4D12", overlay: "#0F3B1C", audio: "#0E2F38" };
const LINE = { text: "#C6FF9A", overlay: "#39FF14", audio: "#4FE3FF" };
export const PPS_MIN = 0.05, PPS_MAX = 600;
const RULER_STEPS = [0.1, 0.2, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 1800, 3600, 7200];
const rulerStep = (pps) => RULER_STEPS.find((st) => st * pps >= 70) || RULER_STEPS[RULER_STEPS.length - 1];
export const ppsToSlider = (pps) => (100 * Math.log(Math.max(PPS_MIN, Math.min(PPS_MAX, pps)) / PPS_MIN)) / Math.log(PPS_MAX / PPS_MIN);
export const sliderToPps = (v) => PPS_MIN * (PPS_MAX / PPS_MIN) ** (v / 100);
const clampLayer = (v) => Math.min(3, Math.max(1, parseInt(v, 10) || 1));
const trackIndex = (letter, layer) => TRACKS.findIndex(([l, n]) => l === letter && n === layer);
const itemEnd = (it, dur) => (+it.end > 0 ? +it.end : dur);

export function normItem(kind, item, dur) {
  const it = { ...DEF[kind], ...item };
  it.layer = clampLayer(it.layer);
  it.start = Math.max(0, +it.start || 0);
  let end = +it.end || 0;
  if (end <= 0) end = dur > 0 ? dur : it.start + 5;
  if (end < it.start + MIN_LEN) end = it.start + MIN_LEN;
  it.end = end;
  return it;
}

export function splitItem(item, t, dur) {
  const s = +item.start, e = itemEnd(item, dur);
  if (!(s + MIN_LEN <= t && t <= e - MIN_LEN)) return null;
  const a = { ...item, end: Math.round(t * 1000) / 1000 };
  const b = { ...item, start: Math.round(t * 1000) / 1000, end: e, src_offset: (+item.src_offset || 0) + (t - s) };
  return [a, b];
}

export function dragResult(mode, s0, e0, o0, dt, kind, dur) {
  dt = Math.round(dt * 20) / 20;
  const cap = kind !== "audio" && dur > 0 ? dur : null;
  if (mode === "move") {
    const L = e0 - s0;
    let s = Math.max(0, s0 + dt);
    if (cap !== null) s = Math.min(s, Math.max(0, cap - L));
    return [s, s + L, 0];
  }
  if (mode === "trim_l") {
    const lo = Math.max(0, s0 - o0);
    const s = Math.min(Math.max(lo, s0 + dt), e0 - MIN_LEN);
    return [s, e0, s - s0];
  }
  if (mode === "trim_r") {
    let e = Math.max(s0 + MIN_LEN, e0 + dt);
    if (cap !== null) e = Math.min(e, Math.max(cap, s0 + MIN_LEN));
    return [s0, e, 0];
  }
  return [s0, e0, 0];
}

const itemLabel = (kind, it) => (kind === "text" ? String(it.text || "").trim().split("\n")[0].slice(0, 40) || "(empty text)" : E.basename(it.path) || "(no file)");

export class TimelineTab {
  constructor(app) {
    this.app = app;
    this.s = E.sanitize({});
    this.s.orig_volume = 100;
    this.movie = ""; this.info = null; this.crop = null;
    this.t = 0; this.sel = null; this.playing = false;
    this.pps = 30; this.offset = 0;       // timeline zoom (pixels per second) and scroll (seconds at the left edge)
    this.addLayer = 1;
    this.range = { start: "0", end: "" };
    this.panel = "Inspector";
    this.token = 0;
    this.build();
  }

  duration() { return this.info ? this.info.duration : 10; }
  lists() { return { text: this.s.texts, overlay: this.s.overlays, audio: this.s.audios }; }

  build() {
    this.el = h("div", { class: "studio" });
    this.movieLbl = h("div", { class: "movie-name" }, "Choose a movie");
    const top = h("div", { class: "moviebar" }, h("div", { class: "grow" }, this.movieLbl), button("Choose video", () => this.chooseMovie(), "primary"));
    this.cv = h("canvas", { class: "preview-canvas", width: 640, height: 360 });
    this.stageMsg = h("div", { class: "stage-msg" }, "Choose a video to start");
    this.stage = h("div", { class: "stage" }, this.cv, this.stageMsg);
    this.timeLbl = h("span", { class: "mono" }, "00:00.0 / 00:00.0");
    this.playBtn = button("▶ Play", () => this.togglePlay(), "small primary");
    const tr = h("div", { class: "posbar" }, button("|<", () => this.seek(0), "small"), button("<", () => this.step(-1 / 25), "small"), this.playBtn,
      button(">", () => this.step(1 / 25), "small"), this.timeLbl);
    // timeline
    this.tl = h("canvas", { class: "timeline" });
    this.zoomLbl = h("span", { class: "note" }, "30 px/s");
    this.zoom = h("input", { type: "range", min: 0, max: 100, step: 0.5, value: ppsToSlider(30), class: "grow" });
    this.zoom.addEventListener("input", () => this.setPps(sliderToPps(+this.zoom.value)));
    const zbar = h("div", { class: "posbar" },
      button("Split", () => this.splitSelected(), "small"), button("Delete", () => this.deleteSelected(), "small danger"),
      button("Edit", () => this.editSelected(), "small quiet"),
      button("−", () => this.zoomBy(1 / 1.5), "small quiet"), this.zoom, button("+", () => this.zoomBy(1.5), "small quiet"),
      button("Fit all", () => this.fit(), "small quiet"), this.zoomLbl);
    this.sticky = h("div", { class: "sticky-preview" }, top, this.stage, tr, h("div", { class: "tlwrap" }, this.tl), zbar,
      h("div", { class: "note small" }, "Pinch or +/− = zoom · drag empty space = scroll · drag a block = move · block edge = trim · tap the ruler = playhead · double-tap = edit"));
    this.chips = new Chips(["Inspector", "Add", "Colour", "Size/Crop", "Chroma", "Sound", "Export"], (n) => this.showPanel(n));
    this.body = h("div", { class: "panel" });
    this.el.append(this.sticky, this.chips.el, this.body);
    this.bindTimeline();
    this.chips.pick(this.panel);
    new ResizeObserver(() => this.redraw()).observe(this.tl);
  }

  // ---------------------------------------------------------------- movie
  async chooseMovie() { const p = await chooseMedia("video", "Choose a video"); if (p) await this.loadMovie(p); }
  async loadMovie(path) {
    let info;
    try { info = await E.probeInfo(path); } catch (e) { await alertBox("This video could not be opened:\n" + (e.message || e)); return false; }
    this.movie = path; this.info = info;
    this.movieLbl.textContent = `${E.basename(path)}  (${info.w}x${info.h}, ${(info.duration / 60).toFixed(1)} min)`;
    for (const kind of ["text", "overlay", "audio"]) this.s[KIND_KEY[kind]] = this.s[KIND_KEY[kind]].map((it) => normItem(kind, it, info.duration));
    this.crop = null;
    E.detectCrop(path, info.duration).then((c) => { if (this.movie === path) { this.crop = c; this.scheduleRender(); } });
    this.sel = null;
    this.fit();
    this.seek(0);
    this.showPanel(this.panel);
    return true;
  }
  clearMovie() {
    this.movie = ""; this.info = null; this.sel = null; this.t = 0;
    this.movieLbl.textContent = "Choose a movie";
    this.cv.getContext("2d").clearRect(0, 0, this.cv.width, this.cv.height);
    this.stageMsg.hidden = false;
    this.redraw();
  }

  // ---------------------------------------------------------------- playback / preview
  seek(t, render = true) {
    const d = this.duration();
    this.t = Math.min(Math.max(0, t), Math.max(0, d));
    this.timeLbl.textContent = `${E.tstr(this.t)} / ${E.tstr(d)}`;
    this.follow();
    this.redraw();
    if (render) this.scheduleRender();
  }
  step(dt) { if (this.movie) this.seek(this.t + dt); }
  togglePlay() {
    if (!this.movie) return;
    this.playing = !this.playing;
    this.playBtn.textContent = this.playing ? "❚❚ Pause" : "▶ Play";
    const tick = async () => {
      if (!this.playing) return;
      if (this.t >= this.duration() - 0.05) { this.playing = false; this.playBtn.textContent = "▶ Play"; return; }
      this.seek(this.t + 0.2, false);
      await this.renderNow();
      setTimeout(tick, 20);
    };
    if (this.playing) tick();
  }
  scheduleRender() { clearTimeout(this.rt); this.rt = setTimeout(() => this.renderNow(), 80); }
  async renderNow() {
    if (!this.movie) return;
    if (this.el.offsetParent === null) { this.dirtyView = true; return; }
    const tok = ++this.token;
    try {
      const r = await P.compose(this.movie, this.t, this.s, this.info, this.crop);
      if (tok !== this.token) return;
      this.cv.width = r.W; this.cv.height = r.H;
      this.cv.getContext("2d").drawImage(r.canvas, 0, 0);
      this.stageMsg.hidden = true;
    } catch (e) { if (tok === this.token) { this.stageMsg.hidden = false; this.stageMsg.textContent = "Preview error: " + (e.message || e); } }
  }
  onShow() { this.redraw(); if (this.dirtyView) { this.dirtyView = false; this.scheduleRender(); } }
  changed() { this.redraw(); this.scheduleRender(); this.app.changed(); if (this.panel === "Inspector") this.showPanel("Inspector"); }

  // ---------------------------------------------------------------- zoom / scroll
  viewW() { return Math.max(50, (this.tl.clientWidth || 360) - 2 * PAD_X); }
  clamp() { const maxOff = Math.max(0, this.duration() - this.viewW() / this.pps); this.offset = Math.min(Math.max(0, this.offset), maxOff); }
  setPps(v, anchorX = null) {
    const ax = anchorX ?? (this.t - this.offset) * this.pps;
    const tAt = this.offset + ax / this.pps;
    this.pps = Math.min(PPS_MAX, Math.max(PPS_MIN, v));
    this.offset = tAt - ax / this.pps;
    this.clamp();
    this.zoom.value = ppsToSlider(this.pps);
    this.zoomLbl.textContent = this.pps >= 10 ? `${this.pps.toFixed(0)} px/s` : `${this.pps.toFixed(2)} px/s`;
    this.redraw();
  }
  zoomBy(f) { this.setPps(this.pps * f); }
  fit() { this.offset = 0; this.setPps(this.viewW() / Math.max(1, this.duration())); }
  follow() {
    const vis = this.viewW() / this.pps;
    if (this.t < this.offset || this.t > this.offset + vis) { this.offset = this.t - vis * 0.2; this.clamp(); }
  }
  x(t) { return PAD_X + (t - this.offset) * this.pps; }
  tAt(x) { return Math.max(0, this.offset + (x - PAD_X) / this.pps); }
  rect(kind, it) {
    const y0 = RULER_H + trackIndex(KIND_LETTER[kind], clampLayer(it.layer)) * TRACK_H + 3;
    const x0 = this.x(+it.start);
    return [x0, y0, Math.max(x0 + 4, this.x(itemEnd(it, this.duration()))), y0 + TRACK_H - 6];
  }

  redraw() {
    const c = this.tl;
    const W = c.clientWidth || 360, H = RULER_H + TRACKS.length * TRACK_H + 4;
    const dpr = window.devicePixelRatio || 1;
    if (c.width !== Math.round(W * dpr) || c.height !== Math.round(H * dpr)) { c.width = Math.round(W * dpr); c.height = Math.round(H * dpr); c.style.height = H + "px"; }
    const g = c.getContext("2d");
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.fillStyle = "#050505"; g.fillRect(0, 0, W, H);
    TRACKS.forEach(([l, n], i) => {
      g.fillStyle = i % 2 ? "#121212" : "#0B0B0B";
      g.fillRect(0, RULER_H + i * TRACK_H, W, TRACK_H);
      g.fillStyle = "#4b6b45"; g.font = "10px sans-serif";
      g.fillText(`${l}${n}`, 2, RULER_H + i * TRACK_H + 12);
    });
    // ruler
    const dur = this.duration();
    const stp = rulerStep(this.pps);
    g.fillStyle = "#0E0E0E"; g.fillRect(0, 0, W, RULER_H);
    g.strokeStyle = "#1F5C12"; g.fillStyle = "#8C8C8C"; g.font = "10px monospace";
    const t0 = Math.floor(this.offset / stp) * stp;
    for (let t = t0; t <= this.offset + W / this.pps; t += stp) {
      const x = this.x(t);
      if (x < 0 || x > W) continue;
      g.beginPath(); g.moveTo(x, RULER_H - 8); g.lineTo(x, RULER_H); g.stroke();
      g.fillText(stp < 1 ? E.tstr(t) : E.mmss(t), x + 2, 12);
    }
    // movie block
    if (this.movie) {
      const y0 = RULER_H + trackIndex("V", 1) * TRACK_H + 3;
      g.fillStyle = "#1a1a1a"; g.strokeStyle = "#555";
      const a = Math.max(-10, this.x(0)), b = Math.min(W + 10, this.x(dur));
      g.fillRect(a, y0, b - a, TRACK_H - 6); g.strokeRect(a, y0, b - a, TRACK_H - 6);
      g.fillStyle = "#bbb"; g.font = "11px sans-serif";
      g.fillText(E.basename(this.movie).slice(0, 40), Math.max(a, 0) + 4, y0 + 14);
    }
    for (const kind of ["audio", "overlay", "text"]) {
      this.lists()[kind].forEach((it, i) => {
        const [x0, y0, x1, y1] = this.rect(kind, it);
        if (x1 < -5 || x0 > W + 5) return;
        const on = this.sel && this.sel[0] === kind && this.sel[1] === i;
        const a = Math.max(-5, x0), b = Math.min(W + 5, x1);
        g.fillStyle = FILL[kind]; g.fillRect(a, y0, b - a, y1 - y0);
        g.strokeStyle = on ? "#FFFFFF" : LINE[kind]; g.lineWidth = on ? 2.5 : 1; g.strokeRect(a, y0, b - a, y1 - y0);
        g.lineWidth = 1;
        g.save(); g.beginPath(); g.rect(a, y0, b - a, y1 - y0); g.clip();
        g.fillStyle = "#EAFFEA"; g.font = "11px sans-serif";
        g.fillText(itemLabel(kind, it), Math.max(a, 0) + 4, y0 + 14);
        g.restore();
        if (on) { g.fillStyle = "#FFFFFF"; g.fillRect(x0 - 2, y0 + 6, 4, y1 - y0 - 12); g.fillRect(x1 - 2, y0 + 6, 4, y1 - y0 - 12); }
      });
    }
    // playhead
    const px = this.x(this.t);
    g.strokeStyle = "#FF3B30"; g.lineWidth = 2;
    g.beginPath(); g.moveTo(px, 0); g.lineTo(px, H); g.stroke();
    g.lineWidth = 1;
  }

  hit(x, y) {
    if (y < RULER_H) return null;
    let best = null;
    for (const kind of ["audio", "overlay", "text"]) {
      this.lists()[kind].forEach((it, i) => {
        const [x0, y0, x1, y1] = this.rect(kind, it);
        if (x0 - 10 <= x && x <= x1 + 10 && y0 <= y && y <= y1) best = [kind, i, x0, x1];
      });
    }
    return best;
  }

  bindTimeline() {
    const c = this.tl;
    const pts = new Map();
    let drag = null, pinch = null, lastTap = 0;
    const pos = (e) => { const r = c.getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top]; };
    c.addEventListener("pointerdown", (e) => {
      c.setPointerCapture(e.pointerId);
      pts.set(e.pointerId, pos(e));
      if (pts.size === 2) {
        const [a, b] = [...pts.values()];
        pinch = { d: Math.hypot(a[0] - b[0], a[1] - b[1]), pps: this.pps, cx: (a[0] + b[0]) / 2 - PAD_X };
        drag = null;
        return;
      }
      const [x, y] = pos(e);
      if (y < RULER_H) { drag = { mode: "ruler" }; this.seek(this.tAt(x)); return; }
      const hit = this.hit(x, y);
      const now = Date.now();
      if (hit) {
        const [kind, i, x0, x1] = hit;
        this.sel = [kind, i];
        if (now - lastTap < 350) { lastTap = 0; this.editSelected(); return; }
        lastTap = now;
        const it = this.lists()[kind][i];
        const edge = 16;
        const mode = Math.abs(x - x0) <= edge && x1 - x0 > edge * 2.2 ? "trim_l" : Math.abs(x - x1) <= edge && x1 - x0 > edge * 2.2 ? "trim_r" : "move";
        drag = { mode, kind, i, x, y, s0: +it.start, e0: itemEnd(it, this.duration()), o0: +it.src_offset || 0, layer0: clampLayer(it.layer), moved: false };
        this.redraw();
        if (this.panel === "Inspector") this.showPanel("Inspector");
      } else {
        drag = { mode: "scroll", x, off: this.offset, moved: false, tapT: this.tAt(x) };
      }
    });
    c.addEventListener("pointermove", (e) => {
      if (!pts.has(e.pointerId)) return;
      pts.set(e.pointerId, pos(e));
      if (pinch && pts.size >= 2) {
        const [a, b] = [...pts.values()];
        const d = Math.hypot(a[0] - b[0], a[1] - b[1]);
        if (pinch.d > 10) this.setPps(pinch.pps * (d / pinch.d), pinch.cx);
        return;
      }
      if (!drag) return;
      const [x, y] = pos(e);
      if (drag.mode === "ruler") { this.seek(this.tAt(x)); return; }
      if (drag.mode === "scroll") { if (Math.abs(x - drag.x) > 4) drag.moved = true; this.offset = drag.off - (x - drag.x) / this.pps; this.clamp(); this.redraw(); return; }
      if (Math.abs(x - drag.x) > 4 || Math.abs(y - drag.y) > 8) drag.moved = true;
      if (!drag.moved) return;
      const it = this.lists()[drag.kind][drag.i];
      const [s, en, doff] = dragResult(drag.mode, drag.s0, drag.e0, drag.o0, (x - drag.x) / this.pps, drag.kind, this.duration());
      it.start = s; it.end = en;
      if (drag.mode === "trim_l") it.src_offset = Math.max(0, drag.o0 + doff);
      if (drag.mode === "move") {
        const row = Math.floor((y - RULER_H) / TRACK_H);
        const tr = TRACKS[row];
        if (tr && tr[0] === KIND_LETTER[drag.kind]) it.layer = tr[1];
      }
      this.redraw();
    });
    const up = (e) => {
      pts.delete(e.pointerId);
      if (pts.size < 2) pinch = null;
      if (drag && (drag.mode === "move" || drag.mode === "trim_l" || drag.mode === "trim_r") && drag.moved) this.changed();
      else if (drag && drag.mode === "scroll" && !drag.moved) { this.sel = null; this.seek(drag.tapT); if (this.panel === "Inspector") this.showPanel("Inspector"); }
      drag = null;
    };
    c.addEventListener("pointerup", up);
    c.addEventListener("pointercancel", up);
    c.addEventListener("wheel", (e) => {
      e.preventDefault();
      if (e.ctrlKey) this.setPps(this.pps * (e.deltaY < 0 ? 1.15 : 1 / 1.15), pos(e)[0] - PAD_X);
      else { this.offset += (e.deltaY + e.deltaX) / this.pps; this.clamp(); this.redraw(); }
    }, { passive: false });
  }

  // ---------------------------------------------------------------- items
  async addItem(kind) {
    if (!this.movie) return alertBox("Please load a movie first.");
    const dur = this.duration();
    const base = { layer: this.addLayer, start: Math.round(this.t * 100) / 100 };
    if (kind === "text") Object.assign(base, { text: "Your text", end: Math.min(dur, this.t + 4) });
    else {
      const path = await chooseMedia(kind === "overlay" ? "image_video" : "audio", kind === "overlay" ? "Choose a photo, video or GIF" : "Choose music or a sound");
      if (!path) return;
      let length = 5;
      try { if (kind === "audio" || E.isOverlayVideo(path)) length = Math.max(1, await E.probeDuration(path)); } catch (e) { length = 5; }
      Object.assign(base, { path, end: Math.round((this.t + length) * 100) / 100 });
    }
    const it = await this.itemDialog(kind, base);
    if (!it) return;
    const lst = this.lists()[kind];
    lst.push(normItem(kind, it, dur));
    this.sel = [kind, lst.length - 1];
    this.changed();
  }

  editSelected() {
    if (!this.sel) return;
    const [kind, i] = this.sel;
    this.itemDialog(kind, this.lists()[kind][i]).then((it) => {
      if (!it) return;
      const lst = this.lists()[kind];
      if (i < lst.length) lst[i] = normItem(kind, it, this.duration());
      this.changed();
    });
  }
  deleteSelected() {
    if (!this.sel) return;
    const [kind, i] = this.sel;
    this.lists()[kind].splice(i, 1);
    this.sel = null;
    this.changed();
  }
  splitSelected() {
    if (!this.sel || !this.movie) return;
    const [kind, i] = this.sel;
    const lst = this.lists()[kind];
    const parts = splitItem(lst[i], this.t, this.duration());
    if (!parts) { toast("Move the playhead inside the selected block first."); return; }
    lst.splice(i, 1, parts[0], parts[1]);
    this.sel = [kind, i + 1];
    this.changed();
  }

  itemDialog(kind, item) {
    const d = JSON.parse(JSON.stringify({ ...DEF[kind], ...(item || {}) }));
    return sheet(KIND_NAME[kind], (body, close) => {
      const num = (label, key, lo, hi, step, fmt) => new NumField(label, lo, hi, step, +d[key], { fmt, onChange: (v) => { d[key] = v; } }).el;
      const timeRow = () => [
        textField("Start (timeline sec)", d.start, (v) => { d.start = parseFloat(v) || 0; }, { inputmode: "decimal" }).el,
        textField("End (timeline sec)", d.end, (v) => { d.end = parseFloat(v) || 0; }, { inputmode: "decimal" }).el];
      const layer = selectField("Layer (3 = top)", ["1", "2", "3"], String(d.layer), (v) => { d.layer = +v; }).el;
      if (kind === "overlay" || kind === "audio") {
        const fileLbl = h("div", { class: "sub-title" }, E.basename(d.path) || "(no file)");
        body.append(fileLbl, button("Choose file", async () => {
          const p = await chooseMedia(kind === "overlay" ? "image_video" : "audio", "Choose a file");
          if (p) { d.path = p; fileLbl.textContent = E.basename(p); }
        }, "small"));
      }
      if (kind === "text") {
        const tf = textField("Text (Enter = new line)", d.text, null, { multiline: true });
        tf.input.addEventListener("input", () => { d.text = tf.input.value; });
        body.append(tf.el, selectField("Font", FONTS, FONTS.includes(d.font) ? d.font : "Noto Sans", (v) => { d.font = v; }).el,
          checkField("Bold", d.bold !== false, (v) => { d.bold = v; }).el, layer, ...timeRow(),
          num("Size (% of height)", "size", 1, 20, 0.5, 1), colorField("Text colour", d.color, (v) => { d.color = v; }).el,
          num("Opacity %", "opacity", 5, 100, 1, 0), num("Outline width", "outline", 0, 10, 1, 0),
          colorField("Outline colour", d.outline_color, (v) => { d.outline_color = v; }).el,
          checkField("Shadow", d.shadow, (v) => { d.shadow = v; }).el, checkField("Background box", d.box, (v) => { d.box = v; }).el,
          colorField("Box colour", d.box_color, (v) => { d.box_color = v; }).el, num("Box opacity %", "box_opacity", 0, 100, 1, 0),
          selectField("Position", E.POSITIONS, d.pos, (v) => { d.pos = v; }).el, num("Custom X %", "x", 0, 100, 1, 0), num("Custom Y %", "y", 0, 100, 1, 0),
          checkField("Center left-right", d.hcenter, (v) => { d.hcenter = v; }).el, checkField("Center up-down", d.vcenter, (v) => { d.vcenter = v; }).el);
      } else if (kind === "overlay") {
        body.append(layer, ...timeRow(), selectField("Position", E.POSITIONS, d.pos, (v) => { d.pos = v; }).el,
          num("Custom X %", "x", 0, 100, 1, 0), num("Custom Y %", "y", 0, 100, 1, 0), num("Size (% of width)", "scale", 3, 100, 1, 0),
          num("Opacity %", "opacity", 5, 100, 1, 0), checkField("Loop (video / GIF)", d.loop, (v) => { d.loop = v; }).el,
          checkField("Remove green screen", d.chroma, (v) => { d.chroma = v; }).el, colorField("Colour to remove", d.key_color, (v) => { d.key_color = v; }).el,
          num("Colour match", "key_sim", 0.01, 0.6, 0.01, 2), num("Edge softness", "key_blend", 0, 0.5, 0.01, 2),
          checkField("Remove colour spill on edges", d.key_spill, (v) => { d.key_spill = v; }).el);
      } else {
        body.append(layer, ...timeRow(), num("Volume %", "volume", 0, 200, 1, 0), checkField("Loop (a short file repeats)", d.loop, (v) => { d.loop = v; }).el,
          note("The movie's original sound is in the Sound tab."));
      }
      body.append(h("div", { class: "btnrow" }, button("Cancel", () => close(null), "quiet"), button("Save", async () => {
        if (+d.end <= +d.start) return alertBox("End must be bigger than Start.");
        if (kind === "text" && !String(d.text).trim()) return alertBox("Please type some text.");
        if (kind !== "text" && !d.path) return alertBox("Please choose a file first.");
        close(d);
      }, "primary")));
    });
  }

  // ---------------------------------------------------------------- panels
  showPanel(n) {
    this.panel = n;
    clear(this.body);
    const b = this.body, s = this.s;
    const re = () => { this.scheduleRender(); this.app.changed(); };
    if (n === "Inspector") {
      if (!this.sel || !this.lists()[this.sel[0]][this.sel[1]]) {
        this.sel = null;
        b.append(note("Select an item on the timeline. Tap an Overlay / Text / Audio block to change its settings here. Use 'Add' to put new items at the playhead."));
        return;
      }
      const [kind, i] = this.sel;
      const it = this.lists()[kind][i];
      const st = textField("Start (sec)", (+it.start).toFixed(2), null, { inputmode: "decimal" });
      const en = textField("End (sec)", itemEnd(it, this.duration()).toFixed(2), null, { inputmode: "decimal" });
      b.append(h("div", { class: "sub-title" }, `${KIND_NAME[kind]} #${i + 1}`), note(itemLabel(kind, it)),
        selectField("Layer", ["1", "2", "3"], String(clampLayer(it.layer)), (v) => { it.layer = +v; this.changed(); }).el,
        st.el, en.el,
        button("Apply times", () => {
          const a = parseFloat(st.get()), z = parseFloat(en.get());
          if (!Number.isFinite(a) || !Number.isFinite(z)) return alertBox("Enter Start / End as numbers (for example 12.5).");
          if (z <= a) return alertBox("End must be bigger than Start.");
          it.start = Math.max(0, a); it.end = kind !== "audio" ? Math.min(z, this.duration()) : z;
          this.changed();
        }, "primary"),
        button("Edit all properties ...", () => this.editSelected()), button("Split at playhead", () => this.splitSelected(), "quiet"),
        button("Delete", () => this.deleteSelected(), "danger"),
        note(`Layer ${it.layer} (3 = top). Drag the block up / down on the timeline to change the layer too.`));
    } else if (n === "Add") {
      b.append(section("Add to timeline (at playhead)"),
        selectField("Layer", ["1", "2", "3"], String(this.addLayer), (v) => { this.addLayer = +v; }).el,
        button("+ Overlay (photo / video)", () => this.addItem("overlay"), "primary wide"),
        button("+ Text", () => this.addItem("text"), "primary wide"),
        button("+ Audio (music / sound)", () => this.addItem("audio"), "primary wide"));
    } else if (n === "Colour") {
      b.append(section("Colour correction (live)", "Every control: -100 to +100 (0 = no change). Double-tap a name to reset it."));
      const fields = [];
      for (const [sec, items] of CL.LAYOUT) {
        b.append(h("div", { class: "sub-title" }, sec));
        for (const [key, label] of items) {
          const nf = new NumField(label, -100, 100, 1, CL.toUi(key, s[key]), { fmt: 0, def: 0, onChange: (v) => { s[key] = CL.toCfg(key, v); re(); } });
          fields.push(nf); b.append(nf.el);
        }
      }
      b.append(checkField("Remove black bars automatically", s.auto_crop, (v) => { s.auto_crop = v; re(); }).el,
        button("Reset colour", () => fields.forEach((f) => f.set(0, true)), "quiet wide"));
    } else if (n === "Size/Crop") {
      const sel = (label, key, vals) => selectField(label, vals, s[key], (v) => { s[key] = v; re(); }).el;
      const num = (label, key, lo, hi, step, fmt) => new NumField(label, lo, hi, step, s[key], { fmt, onChange: (v) => { s[key] = v; re(); } }).el;
      b.append(section("Aspect ratio & fit"), sel("Crop ratio of the movie", "src_aspect", E.ASPECTS), sel("Output ratio", "aspect", E.ASPECTS),
        sel("When the ratio is different", "fit_mode", E.FIT_MODES), colorField("Background colour", s.bg_color, (v) => { s.bg_color = v; re(); }).el,
        num("Blur strength", "blur_amount", 5, 60, 1, 0), num("Movie size in frame %", "fit_scale", 30, 100, 1, 0), num("Movie up-down in frame %", "fit_y", 0, 100, 1, 0),
        section("Crop"), num("Zoom", "zoom", 1, 3, 0.05, 2), num("Crop position X % (0 = left)", "crop_x", 0, 100, 1, 0), num("Crop position Y % (0 = top)", "crop_y", 0, 100, 1, 0),
        note("Resolution, fps, codec and bitrate are in Export."));
    } else if (n === "Chroma") {
      const num = (label, key, lo, hi, step, fmt) => new NumField(label, lo, hi, step, s[key], { fmt, onChange: (v) => { s[key] = v; re(); } }).el;
      const bgLbl = h("div", { class: "note" }, s.chroma_bg_file ? E.basename(s.chroma_bg_file) : "(no file)");
      b.append(section("Chroma key (green screen)"), checkField("Chroma key ON (main video)", s.chroma_on, (v) => { s.chroma_on = v; re(); }).el,
        colorField("Key colour", s.chroma_color, (v) => { s.chroma_color = v; re(); }).el,
        num("Similarity", "chroma_sim", 0.01, 0.5, 0.01, 2), num("Edge blend", "chroma_blend", 0, 0.5, 0.01, 2),
        checkField("Remove colour spill on edges", s.chroma_spill, (v) => { s.chroma_spill = v; re(); }).el,
        section("New background"), selectField("Background type", E.BG_TYPES, s.chroma_bg_type, (v) => { s.chroma_bg_type = v; re(); }).el,
        colorField("Background colour", s.chroma_bg_color, (v) => { s.chroma_bg_color = v; re(); }).el,
        bgLbl, button("Choose background image / video", async () => { const p = await chooseMedia("image_video", "Background"); if (p) { s.chroma_bg_file = p; bgLbl.textContent = E.basename(p); re(); } }, "small"),
        note("To remove the green screen of an overlay, tick 'Remove green screen' in the overlay's properties."));
    } else if (n === "Sound") {
      b.append(section("Original audio (the movie's sound)"),
        new NumField("Original volume %", 0, 200, 1, s.orig_volume, { fmt: 0, onChange: (v) => { s.orig_volume = v; this.app.changed(); } }).el,
        selectField("Audio mode", E.MUSIC_MODES, s.music_mode, (v) => { s.music_mode = v; this.app.changed(); }).el,
        note("Mix = original + audio layers together. Replace = only the audio layers."));
    } else if (n === "Export") this.buildExport();
  }

  buildExport() {
    const b = this.body, s = this.s;
    const set = (k) => (v) => { s[k] = v; this.app.changed(); };
    b.append(section("EXPORT THE TIMELINE", "Exports the movie with every layer, colour, crop and chroma setting of this tab. Choose the range (empty End = to the end of the movie)."),
      textField("From (sec)", this.range.start, (v) => { this.range.start = v; this.app.changed(); }, { inputmode: "decimal" }).el,
      textField("To (sec)", this.range.end, (v) => { this.range.end = v; this.app.changed(); }, { inputmode: "decimal", placeholder: "movie end" }).el,
      selectField("Quick preset", [["", "Quick preset - choose one ..."], ...Object.keys(E.EXPORT_PRESETS)], "", (v) => { if (v) { Object.assign(s, E.EXPORT_PRESETS[v]); this.app.changed(); this.showPanel("Export"); } }).el,
      selectField("Resolution (short side)", E.RES, s.resolution, set("resolution")).el,
      selectField("Frame rate", E.FPS, s.fps, set("fps")).el,
      selectField("Codec", E.CODECS, s.codec, set("codec")).el,
      selectField("Quality", Object.keys(E.QUALITY), s.quality, set("quality")).el,
      selectField("Bitrate mode", E.RATE_MODES, s.rate_mode, set("rate_mode")).el,
      textField("Bitrate (kbps)", String(s.bitrate), (v) => { const x = parseFloat(v); if (x > 0) { s.bitrate = Math.round(Math.min(E.MAX_BITRATE, Math.max(500, x))); this.app.changed(); } }, { inputmode: "numeric" }).el,
      selectField("Audio bitrate", E.ABR, s.audio_bitrate, set("audio_bitrate")).el);
    this.expGo = button("EXPORT", () => this.export(), "primary big wide");
    this.expStop = button("Stop", () => this.eng && this.eng.stop(), "danger wide");
    this.expGo.disabled = !!this.eng; this.expStop.disabled = !this.eng;
    this.prog = this.prog || new Progress();
    this.log = this.log || new LogBox(140);
    this.res = this.res || h("div", { class: "results" });
    b.append(this.expGo, this.expStop, this.prog.el, button("Open exported videos", () => showOutputs(this.outDir()), "quiet wide"), this.res, this.log.el);
  }

  outDir() { return E.join(this.app.paths.out, `${E.fileBase(this.movie)}_timeline`); }

  async export() {
    if (!this.movie) return alertBox("Please load a movie first.");
    if (this.eng) return;
    const a = Math.max(0, parseFloat(this.range.start || "0") || 0);
    const z = String(this.range.end).trim() ? Math.min(this.duration(), parseFloat(this.range.end)) : this.duration();
    if (!(z > a + 0.5)) return alertBox("The range is too short. Check From and To.");
    const s = E.sanitize(this.s);
    const eng = new E.Runner(s, (m) => this.log.add(m), null, null, this.app.paths.cache);
    eng.clipProgress = (f) => this.prog.set(f, `Exporting ... ${Math.round(f * 100)}%`);
    this.eng = eng;
    this.expGo.disabled = true; this.expStop.disabled = false;
    this.log.clear();
    const dir = this.outDir();
    await bridge().mkdirs(dir);
    const out = E.join(dir, `${E.fileBase(this.movie)}_timeline_${E.pad2(Math.floor(a / 60))}m${E.pad2(Math.floor(a % 60))}s_${Date.now() % 100000}.mp4`);
    await bridge().keepAwake(true, "Chauhan Clipping", "Exporting the timeline ...");
    let ok = false;
    try {
      const info = await E.probeInfo(this.movie);
      const crop = s.auto_crop ? await E.detectCrop(this.movie, info.duration) : null;
      ok = await eng.cut(this.movie, a, z - a, out, info, crop);
    } catch (e) { this.log.add("ERROR: " + (e.message || e)); }
    await this.app.releaseAwake();
    this.prog.set(ok ? 1 : null, ok ? "Done." : eng.stopFlag ? "Stopped." : "Export failed - see the log.");
    if (ok) this.res.prepend(resultRow({ path: out }));
    this.eng = null;
    if (this.expGo.isConnected) { this.expGo.disabled = false; this.expStop.disabled = true; }
  }

  // ---------------------------------------------------------------- project
  getState() { return { settings: JSON.parse(JSON.stringify(this.s)), movie: this.movie, t: Math.round(this.t * 1000) / 1000, range: { ...this.range }, pps: this.pps }; }
  async setState(tl, moviePath) {
    tl = tl || {};
    this.s = E.sanitize({ ...(tl.settings || {}) });
    this.range = { start: String((tl.range || {}).start ?? "0"), end: String((tl.range || {}).end ?? "") };
    if (moviePath) await this.loadMovie(moviePath);
    else this.clearMovie();
    if (tl.pps) this.setPps(+tl.pps);
    this.seek(+(tl.t || 0));
    this.showPanel(this.panel);
  }
  stopAll() { if (this.eng) this.eng.stop(); this.playing = false; }
}
