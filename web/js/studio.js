// Studio: the easy editor used by the Simple Edit and AI Clipping tabs (port of the desktop studio.py).
// Top: movie + live preview (drag overlays / text with a finger, pick a colour from the picture).
// Below: Parts (or AI), Crop, Colour, Overlay, Text, Silence, Export, Dialogue.
import * as E from "./engine.js";
import * as CL from "./colour.js";
import * as D from "./dialogue.js";
import * as P from "./preview.js";
import { AIEngine } from "./ai.js";
import { relativeItems } from "./autoshort.js";
import { FONTS } from "./textrender.js";
import { bridge } from "./bridge.js";
import { chooseMedia, playFile, showOutputs, resultRow } from "./files.js";
import {
  h, clear, section, note, button, NumField, selectField, checkField, textField, colorField, Progress, LogBox, Chips,
  alertBox, confirmBox, promptBox, toast,
} from "./ui.js";

// the overlay / text item as ONE video gets it: null = not shown on this video; a text may have its own words
export function effItem(it, ov = true, txo = null) {
  if (it.kind === "overlay") return ov ? it : null;
  if (it.kind !== "text") return it;
  const st = (txo || {})[it.uid];
  if (!st) return it;
  if (st.show === false) return null;
  const own = String(st.text || "");
  return own.trim() ? { ...it, text: own } : it;
}
export const itemsFor = (items, ov = true, txo = null) => items.map((it) => effItem(it, ov, txo)).filter(Boolean);
const uid = () => Math.random().toString(36).slice(2, 10);

const TEXT_STYLES = [
  ["Classic", { color: "#FFFFFF", outline: 3, outline_color: "#000000", glow: false, box: false, shadow: false }],
  ["Yellow bold", { color: "#FFD400", outline: 4, outline_color: "#000000", bold: true, glow: false, box: false, shadow: true }],
  ["Black box", { color: "#FFFFFF", outline: 0, box: true, box_color: "#000000", box_opacity: 75, box_pad: 30, bold: true, glow: false, shadow: false }],
  ["White box", { color: "#000000", outline: 0, box: true, box_color: "#FFFFFF", box_opacity: 100, box_pad: 30, bold: true, glow: false, shadow: false }],
  ["Red label", { color: "#FFFFFF", outline: 0, box: true, box_color: "#E1251B", box_opacity: 100, box_pad: 35, bold: true, glow: false, shadow: false }],
  ["Neon blue", { color: "#FFFFFF", outline: 0, glow: true, glow_color: "#00E5FF", glow_size: 9, box: false, bold: true, shadow: false }],
  ["Neon pink", { color: "#FFFFFF", outline: 0, glow: true, glow_color: "#FF2BD6", glow_size: 9, box: false, bold: true, shadow: false }],
  ["Gaming green", { color: "#39FF14", outline: 3, outline_color: "#000000", glow: true, glow_color: "#39FF14", glow_size: 6, bold: true, box: false, case: "UPPERCASE" }],
  ["Subtitle", { color: "#FFFFFF", outline: 0, shadow: true, shadow_dist: 3, shadow_opacity: 80, box: false, glow: false, bold: false }],
  ["Comic", { color: "#FFFFFF", outline: 6, outline_color: "#000000", bold: true, shadow: true, shadow_dist: 6, shadow_color: "#E1251B", shadow_opacity: 100, glow: false, box: false, case: "UPPERCASE" }],
  ["Gold", { color: "#FFC83D", outline: 2, outline_color: "#5A3A00", glow: true, glow_color: "#FFB000", glow_size: 5, bold: true, box: false, shadow: false }],
  ["Clean black", { color: "#111111", outline: 3, outline_color: "#FFFFFF", bold: true, box: false, glow: false, shadow: false }],
];
const STYLE_KEYS = ["font", "size", "color", "opacity", "outline", "outline_color", "shadow", "box", "box_color", "box_opacity", "bold", "italic",
  "underline", "case", "align", "line_spacing", "shadow_color", "shadow_opacity", "shadow_dist", "shadow_angle", "glow", "glow_color", "glow_size",
  "box_pad", "anim_in", "anim_in_dur", "anim_out", "anim_out_dur", "anim_loop"];

export const ENCODE_KEYS = ["resolution", "fps", "codec", "x264_preset", "quality", "rate_mode", "bitrate", "audio_bitrate"];

export class Studio {
  constructor(app, mode) {
    this.app = app;
    this.mode = mode;                       // "simple" | "ai"
    this.movie = ""; this.info = null; this.dur = 0; this.crop = null;
    this.cfg = E.sanitize({});
    this.items = [];                        // overlays, texts and music; rel_start/rel_end are relative to the part
    this.sel = null;
    this.parts = [];                        // {on, sil, start, end, label} in movie seconds
    this.partIdx = 0; this.tRel = 0;
    this.silList = []; this.silKey = null;
    this.sil = { on: true, db: -35, min: 2.0, pad: 0.25 };
    this.dl = { head_on: false, head_sec: 3, on: false, denoise: true, vad: true, whisper: false, pad: 150, minsil: 300, minpiece: D.MIN_PIECE, scan: false, remove: "um, uh", lang: "", model: "base" };
    this.range = { start: "0", end: "", count: "3", length: "0" };
    this.numStart = "1";
    this.panel = mode === "ai" ? "AI" : "Parts";
    this.eng = null; this.aiEng = null; this.aiFound = [];
    this.pickMode = false;
    this.token = 0; this.renderTimer = 0; this.last = null;
    this.results = [];
    this.trim = { on: false, sec: 3, end_on: false, end_sec: 3, voice: true };   // Simple Edit: clean start / end
    this.doneNames = new Set();             // exported parts: a stopped export continues where it stopped
    this.resumeOn = true;
    this.curOut = "";
    this.build();
  }

  // ================================================================ layout
  build() {
    this.el = h("div", { class: "studio" });
    this.movieLbl = h("div", { class: "movie-name" }, "No movie loaded");
    this.movieInfo = h("div", { class: "note" }, "");
    const top = h("div", { class: "moviebar" },
      h("div", { class: "grow" }, this.movieLbl, this.movieInfo),
      button("Choose video", () => this.chooseMovie(), "primary"));
    this.cv = h("canvas", { class: "preview-canvas", width: 640, height: 360 });
    this.ghost = h("div", { class: "ghost", hidden: true });
    this.stage = h("div", { class: "stage" }, this.cv, this.ghost, h("div", { class: "stage-msg" }, "Choose a video to start"));
    this.stageMsg = this.stage.lastChild;
    this.posLbl = h("span", { class: "mono" }, "00:00.0");
    this.pos = h("input", { type: "range", min: 0, max: 1, step: 0.04, value: 0, class: "grow" });
    this.pos.addEventListener("input", () => { this.tRel = +this.pos.value; this.posLbl.textContent = E.tstr(this.tRel); this.scheduleRender(); });
    this.playBtn = button("▶", () => this.togglePlay(), "small");
    this.pickBtn = button("Pick colour", () => this.togglePick(), "small quiet");
    const bar = h("div", { class: "posbar" }, this.playBtn, this.posLbl, this.pos,
      button("▶ Sound", () => this.playPreview(false), "small"), this.pickBtn);
    this.sticky = h("div", { class: "sticky-preview" }, top, this.stage, bar);
    // Simple Edit = editing only (no silence cut, no dialogue clean-up: those are in AI Clipping)
    const names = this.mode === "ai" ? ["AI", "Parts", "Crop", "Colour", "Effects", "Overlay", "Text", "Silence", "Export", "Dialogue"]
      : ["Parts", "Crop", "Colour", "Effects", "Overlay", "Text", "Clean", "Export"];
    this.chips = new Chips(names, (n) => this.showPanel(n));
    this.body = h("div", { class: "panel" });
    this.el.append(this.sticky, this.chips.el, this.body);
    this.bindStage();
    this.chips.pick(this.panel);
  }

  showPanel(n) {
    this.panel = n;
    clear(this.body);
    const f = {
      AI: () => this.buildAI(), Parts: () => this.buildParts(), Crop: () => this.buildCrop(), Colour: () => this.buildColour(),
      Overlay: () => this.buildOverlay(), Text: () => this.buildText(), Silence: () => this.buildSilence(),
      Export: () => this.buildExport(), Dialogue: () => this.buildDialogue(), Effects: () => this.buildFx(), Clean: () => this.buildClean(),
    }[n];
    if (f) f();
  }

  // ================================================================ movie
  async chooseMovie() {
    const p = await chooseMedia("video", "Choose a video");
    if (p) await this.loadMovie(p);
  }

  async loadMovie(path, keep = false) {
    let info;
    try { info = await E.probeInfo(path); } catch (e) { await alertBox("This video could not be opened:\n" + (e.message || e)); return false; }
    this.movie = path; this.info = info; this.dur = info.duration;
    this.movieLbl.textContent = E.basename(path);
    this.movieInfo.textContent = `${info.w}x${info.h}  |  ${(this.dur / 60).toFixed(1)} min  |  ${info.has_audio ? "with audio" : "NO audio"}`;
    if (!keep) {
      this.items = []; this.sel = null; this.parts = []; this.partIdx = 0; this.tRel = 0;
      this.silList = []; this.silKey = null; this.range.end = "";
    }
    this.crop = null;
    E.detectCrop(path, this.dur).then((c) => { if (this.movie === path) { this.crop = c; this.scheduleRender(); } });
    this.selectPart(Math.min(this.partIdx, Math.max(0, this.parts.length - 1)), keep ? this.tRel : 0);
    this.showPanel(this.panel);
    this.app.onMovieChanged(this);
    return true;
  }

  clearMovie() {
    this.movie = ""; this.info = null; this.dur = 0; this.crop = null;
    this.items = []; this.sel = null; this.parts = []; this.partIdx = 0; this.tRel = 0;
    this.silList = []; this.silKey = null; this.last = null; this.doneNames = new Set();
    this.movieLbl.textContent = "No movie loaded"; this.movieInfo.textContent = "";
    const g = this.cv.getContext("2d"); g.clearRect(0, 0, this.cv.width, this.cv.height);
    this.stageMsg.hidden = false;
    this.pos.max = 1; this.pos.value = 0; this.posLbl.textContent = "00:00.0";
    this.showPanel(this.panel);
  }

  // ================================================================ parts
  currentPart() {
    if (this.parts.length) return this.parts[Math.min(this.partIdx, this.parts.length - 1)];
    return { start: 0, end: this.dur, on: true, sil: false, label: "whole movie" };
  }
  partNumber(i) { const f = parseInt(parseFloat(this.numStart || "1"), 10); return (Number.isFinite(f) ? f : 1) + i; }

  selectPart(i, t = 0) {
    this.partIdx = this.parts.length ? Math.max(0, Math.min(i, this.parts.length - 1)) : 0;
    const p = this.currentPart();
    const len = Math.max(0.1, p.end - p.start);
    this.pos.max = len;
    this.tRel = Math.min(Math.max(0, t), len);
    this.pos.value = this.tRel;
    this.posLbl.textContent = E.tstr(this.tRel);
    if (this.panel === "Parts" || this.panel === "AI") this.refreshParts();
    this.scheduleRender();
  }

  makeParts() {
    if (!this.movie) return alertBox("Please choose a video first.");
    const a = Math.max(0, parseFloat(this.range.start || "0") || 0);
    let b = String(this.range.end).trim() ? parseFloat(this.range.end) : this.dur;
    const count = parseInt(parseFloat(this.range.count || "1"), 10);
    const length = parseFloat(this.range.length || "0") || 0;
    if (!Number.isFinite(a) || !Number.isFinite(b) || !Number.isFinite(count)) return alertBox("Enter Start, End, count and length as numbers.");
    b = Math.min(b, this.dur);
    if (b <= a + 0.5) return alertBox("End must be bigger than Start.");
    const spans = [];
    if (length > 0) {
      if (length < 2) return alertBox("Part length must be at least 2 seconds.");
      for (let t = a; t < b - 0.5; t += length) spans.push([t, Math.min(length, b - t)]);
    } else {
      const c = Math.max(1, Math.min(count, 500));
      const piece = (b - a) / c;
      for (let i = 0; i < c; i++) spans.push([a + i * piece, piece]);
    }
    this.parts = spans.map(([t, d]) => ({ on: true, sil: true, start: +t.toFixed(3), end: +(t + d).toFixed(3), label: "" }));
    this.selectPart(0);
    this.app.changed();
  }

  addPart() {
    if (!this.movie) return;
    const last = this.parts.length ? this.parts[this.parts.length - 1].end : 0;
    const st = Math.min(last, Math.max(0, this.dur - 1));
    this.parts.push({ on: true, sil: true, start: +st.toFixed(3), end: +Math.min(this.dur, st + 30).toFixed(3), label: "" });
    this.refreshParts();
    this.app.changed();
  }

  async editPart(i) {
    const p = this.parts[i];
    const v = await promptBox(`Part ${i + 1}: start and end in seconds (for example 12.5 - 70)`, `${p.start} - ${p.end}`);
    if (v === null) return;
    const m = /^\s*([\d.]+)\s*[-–,; ]\s*([\d.]+)\s*$/.exec(v);
    if (!m) return alertBox("Write it like: 12.5 - 70");
    const s = +m[1], e = +m[2];
    if (!(e > s + 0.5) || e > this.dur + 0.05) return alertBox("End must be bigger than Start and inside the movie.");
    p.start = s; p.end = e;
    this.selectPart(i);
    this.app.changed();
  }

  buildParts() {
    const b = this.body;
    if (this.mode === "simple") {
      b.append(section("1. RANGE AND PARTS"));
      const r = this.range;
      b.append(
        textField("Start (sec)", r.start, (v) => { r.start = v; this.app.changed(); }, { inputmode: "decimal", placeholder: "0 = start" }).el,
        textField("End (sec)", r.end, (v) => { r.end = v; this.app.changed(); }, { inputmode: "decimal", placeholder: "empty = whole movie" }).el,
        textField("Number of parts", r.count, (v) => { r.count = v; this.app.changed(); }, { inputmode: "numeric" }).el,
        textField("OR part length (sec)", r.length, (v) => { r.length = v; this.app.changed(); }, { inputmode: "decimal", placeholder: "0 = use the count" }).el,
        button("Make parts", () => this.makeParts(), "primary wide"));
    }
    b.append(section("PARTS"));
    b.append(h("div", { class: "btnrow" },
      button("Add part", () => this.addPart(), "small"),
      button("All on", () => { this.parts.forEach((p) => { p.on = true; }); this.refreshParts(); this.app.changed(); }, "small quiet"),
      button("All off", () => { this.parts.forEach((p) => { p.on = false; }); this.refreshParts(); this.app.changed(); }, "small quiet")));
    b.append(textField("First part number", this.numStart, (v) => { this.numStart = v; this.scheduleRender(); this.app.changed(); }, { inputmode: "numeric" }).el);
    this.partsBox = h("div", { class: "parts" });
    this.partsSum = h("div", { class: "note" });
    b.append(this.partsBox, this.partsSum);
    this.refreshParts();
  }

  refreshParts() {
    if (!this.partsBox || !this.partsBox.isConnected) return;
    clear(this.partsBox);
    this.parts.forEach((p, i) => {
      const on = checkField(`Part ${this.partNumber(i)}`, p.on, (v) => { p.on = v; this.refreshSum(); this.app.changed(); });
      const sil = this.mode === "ai" ? checkField("cut silence", p.sil, (v) => { p.sil = v; this.refreshSum(); this.app.changed(); }) : null;
      const ov = checkField("overlay", p.ov !== false, (v) => { p.ov = v; this.refreshSum(); this.scheduleRender(); this.app.changed(); });
      const row = h("div", { class: "part" + (i === this.partIdx ? " cur" : "") },
        h("div", { class: "part-top" }, on.el, sil ? sil.el : null, ov.el),
        h("div", { class: "part-bot" },
          h("span", { class: "mono" }, `${E.tstr(p.start)} → ${E.tstr(p.end)}  (${(p.end - p.start).toFixed(1)}s)`),
          h("span", { class: "grow note" }, p.label || ""),
          button("Show", () => this.selectPart(i), "small"),
          button("Edit", () => this.editPart(i), "small quiet"),
          button("✕", () => { this.parts.splice(i, 1); this.selectPart(Math.min(this.partIdx, this.parts.length - 1)); this.app.changed(); }, "small danger")));
      this.partsBox.append(row);
    });
    this.refreshSum();
  }

  refreshSum() {
    if (!this.partsSum) return;
    const n = this.parts.filter((p) => p.on).length;
    let t = this.parts.length ? `${n} of ${this.parts.length} parts will be exported. Overlay on ${this.parts.filter((p) => p.ov !== false).length} video(s).` : "No parts yet. Make parts above.";
    const rem = this.removedSeconds();
    if (rem > 0) t += `  Silence cut removes about ${rem.toFixed(0)}s.`;
    this.partsSum.textContent = t;
  }

  // ================================================================ AI
  buildAI() {
    const b = this.body, c = this.cfg;
    b.append(section("1. AI FINDS THE CLIPS", "Whisper listens to the movie and every 30-60 s window is scored: funny / emotional / relatable words, pace, loud moments, strong start."));
    const set = (k, num = true) => (v) => { c[k] = num ? parseFloat(v) : v; this.app.changed(); };
    b.append(
      selectField("Focus", E.FOCUS, c.focus, set("focus", false)).el,
      textField("Min clip (sec)", c.min_dur, set("min_dur"), { inputmode: "decimal" }).el,
      textField("Max clip (sec)", c.max_dur, set("max_dur"), { inputmode: "decimal" }).el,
      textField("Min viral score", c.min_score, set("min_score"), { inputmode: "decimal" }).el,
      textField("Max clips / 10 min", c.max_per_chunk, set("max_per_chunk"), { inputmode: "numeric" }).el,
      textField("Max total (0 = no limit)", c.max_total, set("max_total"), { inputmode: "numeric" }).el,
      selectField("Language", E.LANGS, c.language, set("language", false)).el,
      selectField("Speech model", E.WHISPER, c.whisper_model, set("whisper_model", false)).el,
      note("tiny = fastest, base = good balance, small = most accurate (slow on a phone). The model downloads once (internet needed the first time)."));
    this.aiGo = button("Find clips with AI", () => this.findClipsAI(), "primary");
    this.aiStop = button("Stop", () => this.aiEng && this.aiEng.stop(), "danger");
    this.aiStop.disabled = !this.aiEng; this.aiGo.disabled = !!this.aiEng;
    this.aiProg = this.aiProg || new Progress();
    this.aiLog = this.aiLog || new LogBox(120);
    b.append(h("div", { class: "btnrow" }, this.aiGo, this.aiStop), this.aiProg.el, this.aiLog.el);
    this.buildParts();
  }

  async findClipsAI() {
    if (!this.movie) return alertBox("Please choose a video first.");
    if (this.aiEng) return;
    const s = E.sanitize(this.cfg);
    if (s.min_dur >= s.max_dur) return alertBox("Min clip length must be smaller than the max length.");
    this.aiFound = [];
    this.aiLog.clear();
    const eng = new AIEngine(s, (m) => this.aiLog.add(m), (f, t) => this.aiProg.set(f, t),
      (c) => this.aiFound.push({ on: true, sil: true, start: +c.start.toFixed(3), end: +c.end.toFixed(3), label: `${c.category} (score ${Math.round(c.score)})` }),
      this.app.paths.cache);
    this.aiEng = eng;
    this.aiGo.disabled = true; this.aiStop.disabled = false;
    await bridge().keepAwake(true, "Chauhan Clipping", "AI is finding clips ...");
    try { await eng.process(this.movie); } catch (e) { this.aiLog.add("ERROR: " + (e.message || e)); }
    await this.app.releaseAwake();
    this.aiEng = null;
    if (this.aiGo.isConnected) { this.aiGo.disabled = false; this.aiStop.disabled = true; }
    if (this.aiFound.length) {
      this.parts = this.aiFound.sort((a, b) => a.start - b.start);
      this.selectPart(0);
      this.aiProg.set(1, `Found ${this.parts.length} clips. Untick any you don't want, then export.`);
      this.app.changed();
    }
  }

  // ================================================================ crop
  buildCrop() {
    const b = this.body, c = this.cfg;
    const re = () => { this.scheduleRender(); this.app.changed(); };
    const sel = (label, key, vals) => selectField(label, vals, c[key], (v) => { c[key] = v; re(); }).el;
    const num = (label, key, lo, hi, step, fmt) => new NumField(label, lo, hi, step, c[key], { fmt, onChange: (v) => { c[key] = v; re(); } }).el;
    b.append(section("ROTATE & FLIP"),
      sel("Rotate", "rotate", E.ROTATIONS),
      checkField("Flip left-right (mirror)", c.flip_h, (v) => { c.flip_h = v; re(); }).el,
      checkField("Flip up-down", c.flip_v, (v) => { c.flip_v = v; re(); }).el,
      section("FREE CROP (cut the edges)", "Cut any amount from each side (0 = nothing). Done before the crop ratio below."),
      num("Cut left %", "crop_l", 0, 45, 0.5, 1), num("Cut right %", "crop_r", 0, 45, 0.5, 1),
      num("Cut top %", "crop_t", 0, 45, 0.5, 1), num("Cut bottom %", "crop_b", 0, 45, 0.5, 1));
    b.append(section("1. IMPORTED MOVIE - crop it here"),
      sel("Crop ratio of the movie", "src_aspect", E.ASPECTS),
      note("This crops the movie you imported. 1:1 = square picture from a 16:9 movie."),
      num("Zoom in", "zoom", 1, 3, 0.05, 2), num("Move left-right %", "crop_x", 0, 100, 1, 0), num("Move up-down %", "crop_y", 0, 100, 1, 0),
      checkField("Remove black bars from the movie automatically", c.auto_crop, (v) => { c.auto_crop = v; re(); }).el,
      section("2. FINAL OUTPUT - the video you export"),
      sel("Output ratio", "aspect", E.ASPECTS), sel("Background of the frame", "fit_mode", E.FIT_MODES),
      colorField("Background colour", c.bg_color, (v) => { c.bg_color = v; re(); }).el,
      note("Blur = blurred copy of the movie behind it, Black bars = black, Solid colour = the colour above, Crop = fill the frame (cuts the edges). Example: movie cropped to 1:1 + output 9:16 = a tall video with the square picture in the middle."),
      num("Blur strength", "blur_amount", 5, 60, 1, 0), num("Movie size in frame %", "fit_scale", 30, 100, 1, 0), num("Movie up-down in frame %", "fit_y", 0, 100, 1, 0),
      note("Blur strength works with Blur background. Size and up-down position work with Blur, Black bars and Solid colour."));
  }

  // ================================================================ speed, fades, effects
  buildFx() {
    const b = this.body, c = this.cfg;
    const re = () => { this.scheduleRender(); this.app.changed(); };
    const num = (label, key, lo, hi, step, fmt) => new NumField(label, lo, hi, step, c[key], { fmt, onChange: (v) => { c[key] = v; re(); } }).el;
    b.append(section("SPEED"), num("Speed (x)", "speed", 0.25, 4, 0.05, 2),
      h("div", { class: "btnrow" }, ...[0.5, 0.75, 1, 1.25, 1.5, 2].map((v) => button(`${v}x`, () => { c.speed = v; re(); this.showPanel("Effects"); }, "small quiet"))),
      note("The whole video (picture, sound, text) plays faster or slower; the voice keeps its pitch. 1.5x of a 60 s part = 40 s video. Tap '▶ Sound' to hear it."),
      section("FADE (start / end)"), num("Fade in from black (s)", "vfade_in", 0, 5, 0.1, 1), num("Fade out to black (s)", "vfade_out", 0, 5, 0.1, 1),
      note("0 = off. The sound fades with the picture."),
      section("EFFECTS"),
      checkField("Black & white", c.fx_bw, (v) => { c.fx_bw = v; re(); }).el,
      checkField("Sepia (old film)", c.fx_sepia, (v) => { c.fx_sepia = v; re(); }).el,
      checkField("Clean video noise (grainy / dark movies)", c.fx_denoise, (v) => { c.fx_denoise = v; re(); }).el,
      checkField("Stabilise shaky video (export is slower)", c.fx_stab, (v) => { c.fx_stab = v; re(); }).el,
      num("Blur the whole video", "fx_blur", 0, 20, 0.5, 1),
      note("Grain, vignette, sharpness and all colour controls are in Colour. Rotate, flip and free crop are in Crop. Noise clean-up and stabilise are seen in '▶ Sound' and the export."));
  }

  // ================================================================ clean start / end (Simple Edit)
  buildClean() {
    const b = this.body, tr = this.trim, ch = () => this.app.changed();
    this.trimRes = h("div", { class: "note" });
    b.append(section("CLEAN START", "If a video begins with a silent (or not talking) stretch, it starts where the talking starts. Only the start is checked."),
      checkField("Cut the silent / non-talking START of every video", tr.on, (v) => { tr.on = v; ch(); }).el,
      textField("Look only at the first ... seconds", String(tr.sec), (v) => { tr.sec = Math.max(0.5, +String(v).replace(",", ".") || 3); ch(); }, { inputmode: "decimal" }).el,
      section("CLEAN END", "The video ends right after the last words (a short natural pause stays). Only the end is checked."),
      checkField("Cut the silent / non-talking END of every video", tr.end_on, (v) => { tr.end_on = v; ch(); }).el,
      textField("Look only at the last ... seconds", String(tr.end_sec), (v) => { tr.end_sec = Math.max(0.5, +String(v).replace(",", ".") || 3); ch(); }, { inputmode: "decimal" }).el,
      checkField("Also cut music / noise where nobody talks (uses voice detection)", tr.voice, (v) => { tr.voice = v; ch(); }).el,
      note("The middle of a video is never cut. At most the seconds above are cut. Switch both OFF and nothing is cut. Texts and overlays are timed from the new start."),
      button("Test on the part shown in the preview", () => this.trimTest(), "wide"), this.trimRes);
  }

  async trimBoth(movie, a, b, head, tail, voice, log, job = null) {
    const tmp = this.app.paths.cache, info = [];
    let na = a, nb = b;
    if (head !== null) { const [x, why] = await D.trimStart(movie, a, b, head, voice, -35, tmp, log, job); na = x; info.push("start: " + why); }
    if (tail !== null) { const [x, why] = await D.trimEnd(movie, na, b, tail, voice, -35, tmp, log, job); nb = x; info.push("end: " + why); }
    return [na, nb, info];
  }

  async trimTest() {
    if (!this.movie || !this.parts.length) return alertBox("Please choose a video and make parts first.");
    const p = this.currentPart(), n = this.partIdx + 1;
    this.trimRes.textContent = "Checking the start and the end of the shown part ...";
    try {
      const [a, b, info] = await this.trimBoth(this.movie, p.start, p.end, +this.trim.sec || 3, +this.trim.end_sec || 3, !!this.trim.voice, () => {});
      this.trimRes.textContent = `Part ${n}: ${info.join("; ")}  ->  ${(b - a).toFixed(1)}s of ${(p.end - p.start).toFixed(1)}s kept`;
    } catch (e) { this.trimRes.textContent = `Part ${n}: check failed (${String(e.message || e).slice(0, 160)})`; }
  }

  // Simple Edit: for ONE part at a time, moves its start / end to where the talking starts / ends
  trimPrepare(movie, log, items, job) {
    if (this.mode !== "simple" || !(this.trim.on || this.trim.end_on)) return null;
    const head = this.trim.on ? Math.max(0.5, +this.trim.sec || 3) : null;
    const tail = this.trim.end_on ? Math.max(0.5, +this.trim.end_sec || 3) : null;
    const voice = !!this.trim.voice;
    return async (plan) => {
      const a = plan.start, b = plan.end;
      const [na, nb, info] = await this.trimBoth(movie, a, b, head, tail, voice, log, job);
      log(`Clean start / end: ${plan.file} - ${info.join("; ")}`);
      if (na <= a && nb >= b) return plan;
      const [ovs, txs, auds] = relativeItems(itemsFor(items, plan.ov !== false, plan.txo), nb - na, plan.number);
      const off = (L) => L.map((d) => ({ ...d, start: d.start + na, end: d.end + na }));
      return { ...plan, start: na, end: nb, pieces: [[na, nb - na]], overlays: off(ovs), texts: off(txs), audios: off(auds) };
    };
  }

  // ================================================================ colour
  buildColour() {
    const b = this.body;
    if (!this.colourMode) {
      let m = "slider";
      try { m = localStorage.getItem("cc_colour_mode") || "slider"; } catch (e) { /* no storage */ }
      this.colourMode = ["slider", "precision", "drag"].includes(m) ? m : "slider";
    }
    const modes = [["slider", "Sliders"], ["precision", "Precision slider"], ["drag", "Drag to adjust"]];
    b.append(h("div", { class: "cmodes" }, ...modes.map(([id, name]) => h("button", {
      class: "chip" + (this.colourMode === id ? " on" : ""), type: "button",
      onclick: () => { this.colourMode = id; try { localStorage.setItem("cc_colour_mode", id); } catch (e) { /* ignore */ } this.showPanel("Colour"); },
    }, name))));
    const help = {
      slider: "Every control goes from -100 to +100 (0 = no change). Drag the slider or type a number. Double-tap a name to reset that control.",
      precision: "Precision mode: each control has a fine slider (covers +/-10 around the value, steps of 0.1) and -1 / -0.1 / +0.1 / +1 buttons for exact values. Double-tap a name to reset.",
      drag: "Drag to adjust: pick a control below, then drag LEFT / RIGHT on the picture or on the pad to change it. Drag UP / DOWN to switch to the next control. Double-tap = reset the control. 'Fine drag' makes it slower and more exact.",
    }[this.colourMode];
    b.append(section("COLOUR CORRECTION (live preview)", help));
    this.colourFields = {};
    if (this.colourMode === "drag") this.buildColourDrag(b);
    else {
      for (const [sec, items] of CL.LAYOUT) {
        b.append(h("div", { class: "sub-title" }, sec));
        for (const [key, label] of items) b.append(this.colourMode === "precision" ? this.precisionRow(key, label) : this.sliderRow(key, label));
      }
    }
    b.append(button("Reset all colour", () => {
      for (const k of CL.KEYS) this.cfg[k] = CL.NEUTRAL[k];
      this.scheduleRender(); this.app.changed(); this.showPanel("Colour");
    }, "quiet wide"));
  }

  colourUi(key) { return CL.toUi(key, this.cfg[key]); }
  setColourUi(key, v, dec = 0) {
    const f = 10 ** dec;
    v = Math.max(-100, Math.min(100, Math.round(v * f) / f));
    this.cfg[key] = CL.toCfg(key, v);
    this.scheduleRender(); this.app.changed();
    return v;
  }

  sliderRow(key, label) {
    const nf = new NumField(label, -100, 100, 1, this.colourUi(key), { fmt: 0, def: 0, onChange: (v) => { this.cfg[key] = CL.toCfg(key, v); this.scheduleRender(); this.app.changed(); } });
    this.colourFields[key] = nf;
    return nf.el;
  }

  // slider + fine slider (+/-10 around the value, 0.1 steps) + exact step buttons
  precisionRow(key, label) {
    let dragging = false;
    const fine = h("input", { type: "range", step: 0.1, class: "fine" });
    const sync = (v, skipFine) => {
      nf.set(v);
      if (skipFine) return;
      fine.min = Math.max(-100, v - 10); fine.max = Math.min(100, v + 10); fine.value = v;
    };
    const apply = (v) => { v = this.setColourUi(key, v, 1); sync(v, dragging); };
    const nf = new NumField(label, -100, 100, 0.1, this.colourUi(key), { fmt: 1, def: 0, onChange: (v) => apply(v) });
    this.colourFields[key] = nf;
    fine.addEventListener("input", () => { dragging = true; const v = this.setColourUi(key, +fine.value, 1); nf.set(v); });
    fine.addEventListener("change", () => { dragging = false; sync(this.colourUi(key)); });
    const step = (d) => button(d > 0 ? "+" + d : String(d).replace("-", "\u2212"), () => apply(this.colourUi(key) + d), "small quiet");
    const row = h("div", { class: "prow" }, step(-1), step(-0.1), fine, step(0.1), step(1));
    sync(this.colourUi(key));
    return h("div", { class: "pfield" }, nf.el, row);
  }

  buildColourDrag(b) {
    const keys = CL.KEYS;
    const names = Object.fromEntries(CL.LAYOUT.flatMap(([, items]) => items));
    if (!keys.includes(this.colourSel)) this.colourSel = keys[0];
    const fmtv = (v) => (Math.abs(v) < 0.05 ? "0" : (v > 0 ? "+" : "") + (Math.abs(v - Math.round(v)) < 0.05 ? Math.round(v) : v.toFixed(1)));
    const chipEls = {};
    const row = h("div", { class: "cchips" });
    for (const k of keys) {
      const c = h("button", { class: "chip", type: "button", onclick: () => { this.colourSel = k; refresh(); } });
      chipEls[k] = c; row.append(c);
    }
    const title = h("div", { class: "cd-name" });
    const val = h("div", { class: "cd-val" });
    const hint = h("div", { class: "cd-hint" }, "\u2194 drag = change value    \u2195 drag = next / previous control");
    const pad = h("div", { class: "cd-pad" }, title, val, hint);
    const fineBox = checkField("Fine drag (slower, 0.1 steps)", !!this.colourFine, (v) => { this.colourFine = v; });
    const refresh = () => {
      for (const k of keys) {
        chipEls[k].textContent = `${names[k]} ${fmtv(this.colourUi(k))}`;
        chipEls[k].classList.toggle("on", k === this.colourSel);
      }
      title.textContent = names[this.colourSel];
      val.textContent = fmtv(this.colourUi(this.colourSel));
      const on = chipEls[this.colourSel];
      if (on && on.scrollIntoView) on.scrollIntoView({ block: "nearest", inline: "center" });
    };
    this.colourRefresh = refresh;
    refresh();
    b.append(row, pad, fineBox.el);
    this.bindColourDrag(pad);
    b.append(note("Tip: you can also drag directly on the picture above."));
  }

  // finger gestures for 'Drag to adjust'. Works on the pad and on the preview picture.
  bindColourDrag(el) {
    let g = null, lastTap = 0;
    const keys = CL.KEYS;
    const hud = () => {
      if (!this.hud) return;
      const k = this.colourSel, v = this.colourUi(k);
      const names = Object.fromEntries(CL.LAYOUT.flatMap(([, items]) => items));
      this.hud.textContent = `${names[k]}  ${Math.abs(v) < 0.05 ? "0" : (v > 0 ? "+" : "") + (Math.abs(v - Math.round(v)) < 0.05 ? Math.round(v) : v.toFixed(1))}`;
      this.hud.classList.add("show");
      clearTimeout(this.hudTimer);
      this.hudTimer = setTimeout(() => this.hud.classList.remove("show"), 900);
    };
    const active = () => this.panel === "Colour" && this.colourMode === "drag" && this.colourRefresh;
    el.addEventListener("pointerdown", (e) => {
      if (!active()) return;
      if (this.pickMode) return;
      e.preventDefault(); e.stopImmediatePropagation();
      try { el.setPointerCapture(e.pointerId); } catch (err) { /* ignore */ }
      if (!keys.includes(this.colourSel)) this.colourSel = keys[0];
      g = { x: e.clientX, y: e.clientY, axis: null, base: this.colourUi(this.colourSel), idx: keys.indexOf(this.colourSel), w: el.getBoundingClientRect().width, moved: false };
    }, true);
    el.addEventListener("pointermove", (e) => {
      if (!g) return;
      const dx = e.clientX - g.x, dy = e.clientY - g.y;
      if (!g.axis && Math.max(Math.abs(dx), Math.abs(dy)) > 8) g.axis = Math.abs(dx) >= Math.abs(dy) ? "h" : "v";
      if (!g.axis) return;
      g.moved = true;
      e.preventDefault();
      if (g.axis === "h") {
        const fine = !!this.colourFine;
        const perPx = (200 / Math.max(g.w, 320)) * (fine ? 0.1 : 1);
        this.setColourUi(this.colourSel, g.base + dx * perPx, fine ? 1 : 0);
      } else {
        const i = Math.max(0, Math.min(keys.length - 1, g.idx + Math.round(dy / 34)));
        if (keys[i] !== this.colourSel) { this.colourSel = keys[i]; g.base = this.colourUi(keys[i]); }
      }
      this.colourRefresh();
      hud();
    });
    const up = () => {
      if (!g) return;
      const tap = !g.moved;
      g = null;
      if (tap) {
        const now = Date.now();
        if (now - lastTap < 350) { this.setColourUi(this.colourSel, 0); this.colourRefresh(); hud(); lastTap = 0; }
        else lastTap = now;
      }
    };
    el.addEventListener("pointerup", up);
    el.addEventListener("pointercancel", up);
  }

  // ================================================================ items (overlay / text / music)
  localizedItem(it, part, number) {
    const d = { ...it };
    const rs = +it.rel_start || 0, re = +it.rel_end || 0;
    d.start = part.start + rs;
    d.end = re > 0 ? part.start + re : part.end;
    if (it.kind === "text") d.text = String(it.text || "").split("{n}").join(String(number));
    if (it.kind === "audio") d.end = Math.min(d.end, part.end);
    return d;
  }
  localized(part, number) {
    const ovs = [], txs = [], auds = [];
    const map = { overlay: [], text: [], audio: [] };
    this.items.forEach((it0, i) => {
      if (it0.kind === "text" && !it0.uid) it0.uid = uid();
      const it = effItem(it0, part.ov !== false, part.txo);
      if (!it) return;                        // switched OFF for this video
      const d = this.localizedItem(it, part, number);
      if (d.end <= d.start) return;
      const kind = it.kind === "overlay" ? "overlay" : it.kind === "audio" ? "audio" : "text";
      ({ overlay: ovs, text: txs, audio: auds })[kind].push(d);
      map[kind].push(i);
    });
    this._map = map;
    return [ovs, txs, auds];
  }

  async addItem(kind) {
    if (!this.movie) return alertBox("Please choose a video first.");
    let it;
    if (kind === "overlay") {
      const path = await chooseMedia("image_video", "Choose a photo, video or GIF");
      if (!path) return;
      it = { ...E.OVERLAY_DEFAULT, kind: "overlay", path, pos: "Top-Right", x: 70, y: 5, scale: 25, rel_start: 0, rel_end: 0 };
    } else if (kind === "audio") {
      const path = await chooseMedia("audio", "Choose music or a sound");
      if (!path) return;
      it = { ...E.AUDIO_DEFAULT, kind: "audio", path, volume: 60, loop: true, rel_start: 0, rel_end: 0 };
    } else if (kind === "number") {
      it = { ...E.TEXT_DEFAULT, kind: "text", text: "{n}", auto_number: true, pos: "Top-Center", x: 45, y: 6, size: 9, outline: 3, shadow: true, box_opacity: 60, rel_start: 0, rel_end: 0 };
    } else {
      it = { ...E.TEXT_DEFAULT, kind: "text", text: "Your text", pos: "Bottom-Center", x: 10, y: 80, size: 5, outline: 2, shadow: true, box_opacity: 60, rel_start: 0, rel_end: 0 };
    }
    if (it.kind === "text") it.uid = uid();
    this.items.push(it);
    this.sel = this.items.length - 1;
    this.showPanel(this.panel);
    this.scheduleRender();
    this.app.changed();
  }

  removeSelected() {
    if (this.sel === null) return;
    this.items.splice(this.sel, 1);
    this.sel = null;
    this.showPanel(this.panel);
    this.scheduleRender();
    this.app.changed();
  }

  itemList(kind) {
    const box = h("div", { class: "item-list" });
    let n = 0;
    this.items.forEach((it, idx) => {
      if (it.kind !== kind) return;
      n++;
      const label = kind === "text" ? E.stripColors(String(it.text)).trim().slice(0, 36) || "(empty)" : E.basename(it.path);
      box.append(h("button", { class: "item" + (idx === this.sel ? " on" : ""), type: "button", onclick: () => { this.sel = idx; this.showPanel(this.panel); this.scheduleRender(); } }, `${n}. ${label}`));
    });
    if (!n) box.append(note("Nothing added yet"));
    return box;
  }

  posSelect(it) {
    return selectField("Position", E.POSITIONS, it.pos, (v) => { it.pos = v; it.hcenter = it.vcenter = false; this.itemChanged(); this.showPanel(this.panel); }).el;
  }
  numItem(label, lo, hi, step, it, key, fmt, custom = false) {
    return new NumField(label, lo, hi, step, +it[key], {
      fmt, onChange: (v) => {
        it[key] = Math.round(v * 1000) / 1000;
        if (custom) { it.pos = "Custom"; if (key === "x") it.hcenter = false; if (key === "y") it.vcenter = false; }
        this.itemChanged();
      },
    }).el;
  }
  timing(it) {
    return [note("WHEN IT APPEARS (seconds from the start of this part)"),
      this.numItem("Appears at (s)", 0, 3600, 0.5, it, "rel_start", 1), this.numItem("Until (s, 0 = part end)", 0, 3600, 0.5, it, "rel_end", 1)];
  }
  itemChanged() { this.scheduleRender(); this.app.changed(); }

  buildOverlay() {
    const b = this.body;
    b.append(h("div", { class: "btnrow" }, button("+ Add photo / video", () => this.addItem("overlay"), "primary"), button("Remove", () => this.removeSelected(), "danger")));
    b.append(h("div", { class: "btnrow" },
      button("Overlay: all videos", () => { this.parts.forEach((p) => { p.ov = true; }); this.showPanel(this.panel); this.itemChanged(); }, "small quiet"),
      button("Overlay: no video", () => { this.parts.forEach((p) => { p.ov = false; }); this.showPanel(this.panel); this.itemChanged(); }, "small quiet")),
      note(this.parts.length ? `Overlays are ON for ${this.parts.filter((p) => p.ov !== false).length} of ${this.parts.length} videos (tick 'overlay' on a part in Parts).` : "Make parts first, then choose which videos get overlays."));
    b.append(section("Overlays on this part"), this.itemList("overlay"));
    const it = this.sel !== null ? this.items[this.sel] : null;
    if (!it || it.kind !== "overlay") b.append(note("Select an overlay in the list, or tap '+ Add photo / video'. Drag it on the picture to move it."));
    else {
      b.append(h("div", { class: "sub-title" }, E.basename(it.path)),
        button("Change file", async () => { const p = await chooseMedia("image_video", "Choose a photo, video or GIF"); if (p) { it.path = p; this.showPanel(this.panel); this.itemChanged(); } }, "small quiet"),
        section("POSITION AND SIZE"), this.posSelect(it),
        this.numItem("Left-right X %", 0, 100, 0.5, it, "x", 1, true), this.numItem("Up-down Y %", 0, 100, 0.5, it, "y", 1, true),
        this.numItem("Size (% of width)", 3, 100, 1, it, "scale", 0), this.numItem("Opacity %", 5, 100, 1, it, "opacity", 0),
        ...this.timing(it),
        checkField("Loop (video / GIF)", it.loop, (v) => { it.loop = v; this.itemChanged(); }).el,
        section("REMOVE BACKGROUND (green / blue screen)"),
        checkField("Remove the colour I pick (background becomes transparent)", it.chroma, (v) => { it.chroma = v; this.itemChanged(); }).el,
        colorField("Colour to remove", it.key_color, (v) => { it.key_color = v; this.itemChanged(); }).el,
        button("Pick colour from picture", () => this.togglePick(), "small quiet"),
        this.numItem("Colour match (more = more removed)", 0.01, 0.6, 0.01, it, "key_sim", 2),
        this.numItem("Edge softness", 0, 0.5, 0.01, it, "key_blend", 2),
        checkField("Remove colour spill on edges", it.key_spill, (v) => { it.key_spill = v; this.itemChanged(); }).el,
        button("Delete this overlay", () => this.removeSelected(), "danger"));
    }
    // music on every part (extra on the phone)
    b.append(section("MUSIC / SOUND", "Music added here plays in every exported part, from the time you set (seconds from the start of the part)."));
    b.append(h("div", { class: "btnrow" }, button("+ Add music", () => this.addItem("audio"), "primary")));
    this.items.forEach((a, idx) => {
      if (a.kind !== "audio") return;
      b.append(h("div", { class: "card" }, h("div", { class: "sub-title" }, E.basename(a.path)),
        new NumField("Volume %", 0, 200, 1, a.volume, { fmt: 0, onChange: (v) => { a.volume = v; this.app.changed(); } }).el,
        new NumField("Starts at (s)", 0, 3600, 0.5, a.rel_start, { fmt: 1, onChange: (v) => { a.rel_start = v; this.app.changed(); } }).el,
        new NumField("Until (s, 0 = part end)", 0, 3600, 0.5, a.rel_end, { fmt: 1, onChange: (v) => { a.rel_end = v; this.app.changed(); } }).el,
        checkField("Loop (a short file repeats)", a.loop, (v) => { a.loop = v; this.app.changed(); }).el,
        button("Remove music", () => { this.items.splice(idx, 1); if (this.sel === idx) this.sel = null; this.showPanel(this.panel); this.app.changed(); }, "small danger")));
    });
    b.append(new NumField("Original movie sound %", 0, 200, 1, this.cfg.orig_volume, { fmt: 0, onChange: (v) => { this.cfg.orig_volume = v; this.app.changed(); } }).el,
      selectField("Audio mode", E.MUSIC_MODES, this.cfg.music_mode, (v) => { this.cfg.music_mode = v; this.app.changed(); }).el,
      note("Mix = movie sound + music together. Replace = only the music."));
  }

  buildText() {
    const b = this.body;
    b.append(h("div", { class: "btnrow" }, button("+ Add text", () => this.addItem("text"), "primary"), button("+ Add part number", () => this.addItem("number")), button("Remove", () => this.removeSelected(), "danger")));
    b.append(note("Part number: every part gets its own number in order (1, 2, 3 ...), starting from 'First part number' in Parts. Write {n} anywhere in a text (for example Part {n}). Drag a text on the picture to move it."));
    b.append(section("Texts on this part"), this.itemList("text"));
    const it = this.sel !== null ? this.items[this.sel] : null;
    if (!it || it.kind !== "text") { b.append(note("Select a text in the list, or tap '+ Add text'.")); return; }
    for (const [k, v] of Object.entries(E.TEXT_DEFAULT)) if (!(k in it)) it[k] = v;    // texts of older projects
    if (!it.uid) it.uid = uid();
    const re = () => { this.showPanel("Text"); this.itemChanged(); };
    const tf = textField("", it.text, null, { multiline: true });
    tf.input.addEventListener("input", () => { it.text = tf.input.value; this.itemChanged(); });
    const makeNumber = () => {
      const el = tf.input;
      let a = el.selectionStart, z = el.selectionEnd;
      if (a === z) {
        const m = /\d+/.exec(el.value);
        if (!m) return alertBox("First select the number inside the text (for example the 1 in 'Part 1 ...'), then press this button.");
        a = m.index; z = m.index + m[0].length;
      }
      el.value = el.value.slice(0, a) + "{n}" + el.value.slice(z);
      it.text = el.value;
      this.itemChanged();
    };
    // colour of the selected words only
    let selA = 0, selZ = 0;
    const keepSel = () => { selA = tf.input.selectionStart; selZ = tf.input.selectionEnd; };
    ["select", "keyup", "pointerup", "touchend"].forEach((ev) => tf.input.addEventListener(ev, keepSel));
    const picker = h("input", { type: "color", value: "#FFD400", style: "position:absolute;opacity:0;width:1px;height:1px" });
    picker.addEventListener("change", () => {
      const el = tf.input;
      const word = E.stripColors(el.value.slice(selA, selZ));
      if (!word.trim()) return;
      el.value = el.value.slice(0, selA) + `{c=${picker.value.toUpperCase()}}${word}{/c}` + el.value.slice(selZ);
      it.text = el.value;
      this.itemChanged();
    });
    const colourWords = () => {
      keepSel();
      if (selA === selZ) return alertBox("First select the word(s) inside the text (long-press a word, drag the handles), then tap this button and choose the colour.");
      picker.click();
    };
    const state = h("div", { class: "note" });
    const showState = () => { state.textContent = it.hcenter || it.vcenter ? "Centred: " + (it.hcenter ? "left-right " : "") + (it.vcenter ? "up-down" : "") : "Free position (drag it on the picture or use the sliders)"; };
    const center = (hc, vc) => { if (hc !== null) it.hcenter = hc; if (vc !== null) it.vcenter = vc; showState(); this.itemChanged(); };
    showState();
    const sel = (label, vals, key) => selectField(label, vals, it[key], (v) => { it[key] = v; this.itemChanged(); }).el;
    const chk = (label, key) => checkField(label, it[key], (v) => { it[key] = v; this.itemChanged(); }).el;
    const col = (label, key) => colorField(label, it[key], (v) => { it[key] = v; this.itemChanged(); }).el;
    b.append(this.buildPerVideo(it));
    b.append(section("TEXT"), tf.el, picker,
      h("div", { class: "btnrow" }, button("Colour selected word(s)", colourWords, "small"),
        button("Remove word colours", () => { it.text = E.stripColors(it.text); re(); }, "small quiet")),
      note("Select one or more words and tap 'Colour selected word(s)': only those words get the new colour. In the box it looks like {c=#FF0000}word{/c} - the video shows only the word."),
      button("Make selected number = part number", makeNumber, "small"),
      section("STYLES (one tap)"),
      h("div", { class: "grid3" }, ...TEXT_STYLES.map(([name, st]) => {
        const bt = button(name, () => { Object.assign(it, JSON.parse(JSON.stringify(st))); re(); }, "small");
        Object.assign(bt.style, { background: st.box ? st.box_color : "#2A2A2A", color: st.color, border: `2px solid ${st.glow ? st.glow_color : st.outline_color || "#000"}`, fontWeight: st.bold ? "700" : "400" });
        return bt;
      })),
      h("div", { class: "btnrow" }, button("Duplicate text", () => this.duplicateText(it), "small quiet"), button("Copy this style to all texts", () => this.styleToAll(it), "small quiet")),
      section("FONT"),
      selectField("Font", FONTS, FONTS.includes(it.font) ? it.font : "Noto Sans", (v) => { it.font = v; this.itemChanged(); }).el,
      h("div", { class: "grid3" }, chk("Bold", "bold"), chk("Italic", "italic"), chk("Underline", "underline")),
      sel("Letters", E.TEXT_CASES, "case"), sel("Line alignment", E.TEXT_ALIGNS, "align"),
      note("Hindi works in every font (the Devanagari fonts are Noto Sans Devanagari, Hind, Mukta, Baloo 2, Rozha One, Teko)."),
      section("POSITION AND SIZE"), this.posSelect(it),
      h("div", { class: "grid2" },
        button("Center left-right", () => center(true, null), "small quiet"), button("Center up-down", () => center(null, true), "small quiet"),
        button("Center on screen", () => center(true, true), "small"), button("Unlock (move freely)", () => center(false, false), "small quiet")),
      state,
      this.numItem("Left-right X %", 0, 100, 0.5, it, "x", 1, true), this.numItem("Up-down Y %", 0, 100, 0.5, it, "y", 1, true),
      this.numItem("Size (% of height)", 1, 20, 0.5, it, "size", 1), this.numItem("Opacity %", 5, 100, 1, it, "opacity", 0),
      this.numItem("Line spacing %", -30, 150, 5, it, "line_spacing", 0), ...this.timing(it),
      col("Text colour", "color"),
      section("OUTLINE (STROKE)"), this.numItem("Outline thickness", 0, 15, 1, it, "outline", 0), col("Outline colour", "outline_color"),
      section("SHADOW"), chk("Shadow", "shadow"), col("Shadow colour", "shadow_color"),
      this.numItem("Shadow opacity %", 0, 100, 1, it, "shadow_opacity", 0), this.numItem("Shadow distance", 0, 30, 1, it, "shadow_dist", 0),
      this.numItem("Shadow angle (deg)", 0, 360, 5, it, "shadow_angle", 0),
      section("GLOW"), chk("Glow around the letters", "glow"), col("Glow colour", "glow_color"), this.numItem("Glow size", 1, 30, 1, it, "glow_size", 0),
      section("BACKGROUND"), chk("Background box behind text", "box"), col("Box colour", "box_color"),
      this.numItem("Box opacity %", 0, 100, 1, it, "box_opacity", 0), this.numItem("Box padding %", 0, 100, 5, it, "box_pad", 0),
      section("ANIMATION", "In: how the text comes in; Out: how it goes; Loop: moves the whole time. Typewriter shows the words one by one. Tap '▶ Sound' to see it moving."),
      sel("In", E.ANIM_IN, "anim_in"), this.numItem("In duration (s)", 0.1, 3, 0.1, it, "anim_in_dur", 1),
      sel("Out", E.ANIM_OUT, "anim_out"), this.numItem("Out duration (s)", 0.1, 3, 0.1, it, "anim_out_dur", 1),
      sel("Loop", E.ANIM_LOOP, "anim_loop"),
      button("Delete this text", () => this.removeSelected(), "danger"));
  }

  // THIS VIDEO: show / hide the selected text on the shown part, or give it its own words there
  buildPerVideo(it) {
    const box = h("div", { class: "card" });
    if (!this.parts.length) { box.append(note("Make parts first - then you can choose which videos get this text and give a video its own words.")); return box; }
    const part = this.currentPart(), u = it.uid;
    part.txo = part.txo || {};
    const st = part.txo[u] || (part.txo[u] = { show: true, text: "" });
    const shown = this.parts.filter((p) => ((p.txo || {})[u] || {}).show !== false).length;
    const own = this.parts.filter((p) => String(((p.txo || {})[u] || {}).text || "").trim()).length;
    const own_tf = textField("Other words on this video only (empty = the main text)", st.text, null, { multiline: true });
    own_tf.input.addEventListener("input", () => { st.text = own_tf.input.value; this.itemChanged(); });
    const all = (show, clearWords) => { for (const p of this.parts) { p.txo = p.txo || {}; const x = p.txo[u] || (p.txo[u] = { show: true, text: "" }); if (show !== null) x.show = show; if (clearWords) x.text = ""; } this.showPanel("Text"); this.itemChanged(); };
    box.append(h("div", { class: "sub-title" }, `THIS VIDEO (part ${this.partIdx + 1} of ${this.parts.length})`),
      checkField("Show this text on this video", st.show !== false, (v) => { st.show = v; this.itemChanged(); }).el,
      own_tf.el,
      h("div", { class: "btnrow" },
        button("< Previous video", () => { this.selectPart(this.partIdx - 1); this.showPanel("Text"); }, "small quiet"),
        button("Next video >", () => { this.selectPart(this.partIdx + 1); this.showPanel("Text"); }, "small quiet")),
      h("div", { class: "btnrow" }, button("Show on all", () => all(true, false), "small quiet"), button("Hide on all", () => all(false, false), "small quiet"),
        button("Remove other words", () => all(null, true), "small quiet")),
      note(`Shown on ${shown} of ${this.parts.length} videos, ${own} with their own words.`));
    return box;
  }

  duplicateText(it) {
    const n = JSON.parse(JSON.stringify(it));
    n.uid = uid(); n.pos = "Custom"; n.hcenter = n.vcenter = false;
    n.x = Math.min(90, (+it.x || 50) + 3); n.y = Math.max(0, (+it.y || 80) - 6);
    this.items.push(n);
    this.sel = this.items.length - 1;
    this.showPanel("Text");
    this.itemChanged();
  }

  styleToAll(it) {
    let n = 0;
    for (const o of this.items) if (o !== it && o.kind === "text") { for (const k of STYLE_KEYS) if (k in it) o[k] = JSON.parse(JSON.stringify(it[k])); n++; }
    this.itemChanged();
    toast(`Style copied to ${n} other text(s)`);
  }

  // ================================================================ silence
  scanKey() {
    const base = [this.movie, +this.sil.db, +this.sil.min];
    return this.dl.head_on ? [...base, +this.dl.head_sec || 3, JSON.stringify(this.headWindows())] : base;
  }
  // "first N seconds only": just these stretches (start of every ticked part + a little margin) need the silence scan
  headWindows() {
    const h = (Math.max(0.5, +this.dl.head_sec || 3)) + 1;
    const w = this.parts.filter((p) => p.on && p.sil).map((p) => [+p.start.toFixed(3), +Math.min(p.end, p.start + h).toFixed(3)]).sort((a, b) => a[0] - b[0]);
    const m = [];
    for (const [a, b] of w) { if (m.length && a <= m[m.length - 1][1]) m[m.length - 1][1] = Math.max(m[m.length - 1][1], b); else m.push([a, b]); }
    return m;
  }
  buildSilence() {
    const b = this.body, S = this.sil;
    const changed = () => { this.updateSilSummary(); this.app.changed(); };
    b.append(checkField("Cut long silent pauses (only in ticked parts)", S.on, (v) => { S.on = v; changed(); this.updateCutInfo(); }).el,
      ...this.headControls(),
      section("SETTINGS"),
      new NumField("Quiet below (dB)", -60, -20, 1, S.db, { fmt: 0, onChange: (v) => { S.db = v; changed(); } }).el,
      new NumField("Silence longer than (s)", 0.5, 10, 0.5, S.min, { fmt: 1, onChange: (v) => { S.min = v; changed(); } }).el,
      new NumField("Keep around speech (s)", 0, 1, 0.05, S.pad, { fmt: 2, onChange: (v) => { S.pad = v; changed(); } }).el,
      note("Default: silence of 2 seconds or more (quieter than -35 dB) is cut. The amount kept around speech stops words from being clipped."),
      button("Scan this movie for silence", () => this.scanSilence(), "primary wide"));
    this.silSummary = h("div", { class: "note" });
    this.silText = h("pre", { class: "log" });
    b.append(this.silSummary, this.silText);
    this.updateSilSummary();
  }

  async scanSilence() {
    if (!this.movie) { await alertBox("Please choose a video first."); return false; }
    const key = this.scanKey();
    if (this.silSummary) this.silSummary.textContent = `${this.dl.head_on ? "Scanning the sound at the start of each part ..." : "Scanning the sound of the whole movie ..."}`;
    try {
      const segs = await E.detectSilence(this.movie, this.sil.db, this.sil.min, this.dur, null, this.dl.head_on ? this.headWindows() : null);
      this.silList = segs; this.silKey = key;
      this.updateSilSummary();
      this.app.changed();
      return true;
    } catch (e) {
      if (this.silSummary) this.silSummary.textContent = "Scan failed: " + (e.message || e);
      return false;
    }
  }

  removedSeconds() {
    if (!this.sil.on || !this.silList.length) return 0;
    let total = 0;
    for (const p of this.parts) {
      if (!(p.on && p.sil)) continue;
      const he = this.headEnd(p.start, p.end);
      const keep = this.withTail(E.silenceKeepRanges(this.silList, p.start, he ?? p.end, +this.sil.pad, 0.3), p.start, p.end);
      total += p.end - p.start - keep.reduce((a, [, d]) => a + d, 0);
    }
    return total;
  }

  updateSilSummary() {
    this.refreshSum();
    if (!this.silSummary || !this.silSummary.isConnected) return;
    const fresh = this.silKey && JSON.stringify(this.silKey) === JSON.stringify(this.scanKey());
    if (!this.silKey) { this.silSummary.textContent = "Not scanned yet"; this.silText.textContent = ""; return; }
    if (!fresh) { this.silSummary.textContent = "Settings changed. Scan again to update."; return; }
    const tot = this.silList.reduce((a, [s, e]) => a + (e - s), 0);
    this.silSummary.textContent = `${this.silList.length} silent stretches, ${tot.toFixed(0)}s in total. In the ticked parts about ${this.removedSeconds().toFixed(0)}s will be cut${this.dl.head_on ? ` (only the first ${+this.dl.head_sec || 3}s of every part)` : ""}.`;
    this.silText.textContent = this.silList.slice(0, 300).map(([s, e]) => `${E.tstr(s)} - ${E.tstr(e)}  (${(e - s).toFixed(1)}s)`).join("\n");
  }

  // ================================================================ export
  buildExport() {
    const b = this.body, c = this.cfg;
    const set = (k) => (v) => { c[k] = v; this.app.changed(); this.showPanel("Export"); };
    this.cutInfo = h("div", { class: "note" });
    if (this.mode === "ai") b.append(section("CUTTING (ON / OFF)"),
      checkField("Cut silent pauses", this.sil.on, (v) => { this.sil.on = v; this.app.changed(); this.updateCutInfo(); }).el,
      checkField("Dialogue clean-up (keep only talking)", this.dl.on, (v) => { this.dl.on = v; this.app.changed(); this.updateCutInfo(); }).el,
      ...this.headControls(),
      this.cutInfo);
    b.append(selectField("Quick preset", [["", "Quick preset - choose one ..."], ...Object.keys(E.EXPORT_PRESETS)], "", (v) => {
      if (!v) return;
      Object.assign(c, E.EXPORT_PRESETS[v]);
      this.app.changed();
      this.showPanel("Export");
      toast("Preset applied: " + v);
    }).el);
    const brOpts = E.BITRATES.includes(String(c.bitrate)) ? E.BITRATES : [String(c.bitrate), ...E.BITRATES];
    b.append(section("Video quality"),
      selectField("Resolution (short side)", E.RES, c.resolution, set("resolution")).el,
      selectField("Frame rate", E.FPS, c.fps, set("fps")).el,
      selectField("Codec", E.CODECS, c.codec, set("codec")).el,
      selectField("Encoding speed (CPU) - faster = quicker export", E.X264_PRESETS, c.x264_preset, set("x264_preset")).el,
      selectField("Quality (encoder speed / detail)", Object.keys(E.QUALITY), c.quality, set("quality")).el,
      selectField("Bitrate mode", E.RATE_MODES, c.rate_mode, set("rate_mode")).el,
      selectField("Bitrate (kbps)", brOpts.map((x) => [x, `${x} kbps (${(+x / 1000).toFixed(1)} Mbps)`]), String(c.bitrate), (v) => { c.bitrate = +v; this.app.changed(); }).el,
      textField("Or type a bitrate (kbps)", String(c.bitrate), (v) => { const n = parseFloat(v); if (n > 0) { c.bitrate = Math.round(Math.min(E.MAX_BITRATE, Math.max(500, n))); this.app.changed(); this.showPanel("Export"); } }, { inputmode: "numeric" }).el,
      selectField("Audio bitrate", E.ABR, c.audio_bitrate, set("audio_bitrate")).el,
      note("Exact bitrate: the file gets the bitrate you choose (12000 kbps = 12 Mbps). File size = bitrate x length. Quality mode: constant quality, the number is only an upper limit. Resolution 'Original' keeps your movie's own size. Phone hardware = fast (uses the phone's video chip); if it fails, the CPU encoder (x264, the same as the desktop software) is used automatically. With the CPU encoder 'Fast (phone)' quality exports much faster than 'High'."),
      section("PREVIEW (see your edit before exporting)"),
      button("Play selected part with sound", () => this.playPreview(false), "wide"),
      button("Play whole edit (all ticked parts)", () => this.playPreview(true), "wide"));
    this.resumeLbl = h("div", { class: "note" });
    b.append(checkField("If an export was stopped, continue where it stopped (skip parts already exported)", this.resumeOn, (v) => { this.resumeOn = v; this.app.changed(); this.updateResume(); }).el, this.resumeLbl);
    this.updateResume();
    this.expGo = button("EXPORT SELECTED PARTS", () => this.export(), "primary big wide");
    this.expStop = button("Stop", () => this.eng && this.eng.stop(), "danger wide");
    this.expGo.disabled = !!this.eng; this.expStop.disabled = !this.eng;
    this.expProg = this.expProg || new Progress();
    this.expLog = this.expLog || new LogBox(160);
    this.resBox = this.resBox || h("div", { class: "results" });
    b.append(this.expGo, this.expStop, this.expProg.el, button("Open exported videos", () => this.openOutputs(), "quiet wide"), this.resBox, this.expLog.el);
    this.updateCutInfo();
  }

  // the two controls for "first N seconds only" (shown in the Export, Silence and Dialogue panels)
  headControls() {
    const upd = () => { this.app.changed(); this.updateCutInfo(); this.updateSilSummary(); };
    return [
      checkField("Apply only to the first few seconds of every part (rest stays normal)", this.dl.head_on, (v) => { this.dl.head_on = v; upd(); }).el,
      textField("Seconds at the start of every part", String(this.dl.head_sec), (v) => { this.dl.head_sec = Math.max(0.5, +String(v).replace(",", ".") || 3); upd(); }, { type: "number", inputmode: "decimal" }).el,
    ];
  }

  // "first N seconds only": end of the part that gets cut (null = whole part)
  headEnd(start, end) {
    if (!this.dl.head_on) return null;
    const h = start + Math.max(0.5, +this.dl.head_sec || 3);
    return h < end - 0.05 ? h : null;
  }
  withTail(pieces, start, end) {
    const h = this.headEnd(start, end);
    return h === null ? pieces : [...pieces, [h, end - h]];
  }

  // what the export button will do with the two switches
  updateCutInfo() {
    if (this.mode !== "ai") return;
    const dl = !!this.dl.on, sl = !!this.sil.on;
    if (this.cutInfo) this.cutInfo.textContent = dl
      ? "Dialogue clean-up is ON: only the talking is kept in every ticked part (silence and pauses are removed)."
      : sl ? "Silence cut is ON: long silent pauses are removed from the ticked parts (parts with 'cut silence' ticked)."
        : "Both OFF: the movie is only converted into parts. Nothing is removed - no silence, no dialogue cut.";
    if (this.cutInfo && (dl || sl) && this.dl.head_on) this.cutInfo.textContent += `  Only the first ${+this.dl.head_sec || 3} s of every part is cut; the rest stays as it is.`;
    if (this.expGo) this.expGo.textContent = "EXPORT SELECTED PARTS" + (dl ? " (DIALOGUE CLEAN-UP)" : sl ? " (SILENCE CUT)" : " (PLAIN PARTS)");
  }

  outDir(withDialogue) {
    return E.join(this.app.paths.out, `${E.fileBase(this.movie)}_${this.mode === "simple" ? "simple" : "ai"}` + (withDialogue ? "_dialogue" : ""));
  }
  openOutputs() { if (!this.movie) return; showOutputs(this.lastOut || this.outDir(false)); }

  dialogueOpts() {
    const d = this.dl;
    return { denoise: !!d.denoise, vad: !!d.vad, whisper: !!d.whisper, remove_words: d.remove, language: String(d.lang || "").trim(),
      pad_ms: parseInt(d.pad, 10), min_sil_ms: parseInt(d.minsil, 10), min_piece: +d.minpiece, scan_picture: !!d.scan, whisper_model: d.model };
  }

  // returns a function that, for ONE part at a time, scans only that part's sound and builds its pieces
  silencePrepare(movie, log, job) {
    if (this.mode !== "ai" || !this.sil.on) return null;
    const db = +this.sil.db, mn = +this.sil.min, pad = +this.sil.pad;
    const head = this.dl.head_on ? Math.max(0.5, +this.dl.head_sec || 3) : null;
    return async (plan) => {
      if (!plan.sil) return plan;
      const a = plan.start, b = plan.end;
      const he = head !== null && a + head < b - 0.05 ? a + head : null;
      const scanEnd = he ?? b;
      log(`Silence: scanning only this part (${a.toFixed(1)}s - ${scanEnd.toFixed(1)}s) ...`);
      const sil = await E.detectSilence(movie, db, mn, null, job, [[a, scanEnd]]);
      const keep = E.silenceKeepRanges(sil, a, scanEnd, pad, 0.3);
      const pieces = he !== null ? [...keep, [he, b - he]] : keep;
      log(`  ${sil.length} silent stretch(es) found, ${((b - a) - pieces.reduce((x, [, d]) => x + d, 0)).toFixed(1)}s removed`);
      return { ...plan, pieces };
    };
  }

  buildPlans(chosen) {
    const base = E.fileBase(this.movie);
    const pad = +this.sil.pad;
    return chosen.map(([idx, p]) => {
      const number = this.partNumber(idx);
      const [ovs, txs, auds] = this.localized(p, number);
      const pieces = [[p.start, p.end - p.start]];      // silencePrepare cuts the silence of THIS part when its turn comes
      return { file: this.planFile(idx, p, base), start: p.start, end: p.end, label: p.label || "", pieces, overlays: ovs, texts: txs, audios: auds, number,
        sil: !!(this.mode === "ai" && this.sil.on && p.sil), ov: p.ov !== false, txo: JSON.parse(JSON.stringify(p.txo || {})) };
    });
  }

  planFile(idx, p, base = null) {
    const mm = Math.floor(p.start / 60), ss = Math.floor(p.start % 60);
    return `${base || E.fileBase(this.movie)}_part${String(this.partNumber(idx)).padStart(2, "0")}_${E.pad2(mm)}m${E.pad2(ss)}s.mp4`;
  }
  doneKey(outDir, file) { return `${E.basename(outDir)}/${file}`; }
  async pendingParts(outDir) {
    const done = [], todo = [];
    for (let i = 0; i < this.parts.length; i++) {
      const p = this.parts[i];
      if (!p.on) continue;
      const f = this.planFile(i, p);
      const ok = this.doneNames.has(this.doneKey(outDir, f)) && await bridge().exists(E.join(outDir, f));
      (ok ? done : todo).push(i + 1);
    }
    return [done, todo];
  }
  async updateResume() {
    if (!this.resumeLbl) return;
    if (!this.movie || !this.parts.length) { this.resumeLbl.textContent = ""; return; }
    const [done, todo] = await this.pendingParts(this.outDir(this.mode === "ai" && !!this.dl.on));
    this.resumeLbl.textContent = done.length && todo.length && this.resumeOn ? `${done.length} part(s) already exported. Export continues with part ${todo[0]} (${todo.length} left).`
      : done.length && !todo.length ? "All ticked parts are already exported." : "";
  }

  async export(withDialogue) {
    if (withDialogue === undefined || withDialogue === null) withDialogue = !!this.dl.on;
    if (this.mode !== "ai") withDialogue = false;      // Simple Edit: editing only, nothing is cut out
    if (!this.movie) return alertBox("Please choose a video first.");
    if (this.eng) return;
    const chosen = this.parts.map((p, i) => [i, p]).filter(([, p]) => p.on);
    if (!this.parts.length) return alertBox("No parts yet. Make parts first (Parts).");
    if (!chosen.length) return alertBox("No part is selected. Tick at least one part.");
    for (const [i, p] of chosen) if (p.end <= p.start + 0.5 || p.start < 0 || p.end > this.dur + 0.05) return alertBox(`Part ${i + 1} has invalid times. Check its Start and End.`);
    const dl = withDialogue ? this.dialogueOpts() : null;
    // silence is NOT scanned for the whole movie: every part is scanned only when its turn comes
    // (scan this part -> export it -> next part), see silencePrepare
    const s = E.sanitize(this.cfg);
    if (withDialogue) { s.fade_sec = D.FADE; s._joint_fade = D.FADE; s._denoise = !!dl.denoise; }
    for (const k of ENCODE_KEYS) this.app.lastEncode[k] = s[k];
    const items = JSON.parse(JSON.stringify(this.items));
    let plans = this.buildPlans(chosen);
    const outDir = this.outDir(withDialogue);
    this.lastOut = outDir;
    if (this.panel !== "Export") this.chips.pick("Export");
    this.expLog.clear(); clear(this.resBox);
    // an export that was stopped continues where it stopped: finished parts are skipped
    const doneFiles = new Set();
    for (const pl of plans) if (this.doneNames.has(this.doneKey(outDir, pl.file)) && await bridge().exists(E.join(outDir, pl.file))) doneFiles.add(pl.file);
    if (doneFiles.size && this.resumeOn) {
      if (doneFiles.size === plans.length) {
        if (!(await confirmBox("All ticked parts are already exported.\n\nExport all of them again from the beginning?"))) return;
        for (const f of doneFiles) this.doneNames.delete(this.doneKey(outDir, f));
      } else {
        plans = plans.filter((pl) => !doneFiles.has(pl.file));
        this.expLog.add(`Continuing where the last export stopped: ${doneFiles.size} part(s) are already exported and skipped, ${plans.length} left.`);
      }
    } else for (const pl of plans) this.doneNames.delete(this.doneKey(outDir, pl.file));
    this.curOut = outDir;
    const eng = new E.StudioEngine(s, (m) => this.expLog.add(m), (f, t) => this.expProg.set(f, t),
      (c) => { this.resBox.prepend(resultRow({ path: c.path }, c.text)); this.doneNames.add(this.doneKey(outDir, E.basename(c.path))); this.app.changed(); this.updateResume(); },
      this.app.paths.cache);
    this.eng = eng;
    this.expGo.disabled = true; this.expStop.disabled = false;
    await bridge().keepAwake(true, "Chauhan Clipping", "Exporting your parts ...");
    const movie = this.movie, tmp = this.app.paths.cache, log = (m) => this.expLog.add(m);
    let prepare = withDialogue ? null : (this.silencePrepare(movie, log, eng.job) || this.trimPrepare(movie, log, items, eng.job));
    if (dl) {
      prepare = async (plan) => {
        log(`Dialogue: finding the talking in ${plan.file} (${plan.start.toFixed(1)}s - ${plan.end.toFixed(1)}s)`);
        const he = this.headEnd(plan.start, plan.end);
        let pieces = await D.analyze(movie, plan.start, he ?? plan.end, dl, tmp, log, eng.job);
        if (he !== null) {
          if (!pieces.length) pieces = [[plan.start, he - plan.start]];   // nothing to keep at the start: leave it as it is
          pieces = this.withTail(pieces, plan.start, plan.end);
        }
        if (!pieces.length) return null;
        const total = pieces.reduce((a, [, d]) => a + d, 0);
        const [ovs, txs, auds] = relativeItems(itemsFor(items, plan.ov !== false, plan.txo), total, plan.number);
        log(`  ${pieces.length} dialogue pieces, ${total.toFixed(1)}s of talking (from ${(plan.end - plan.start).toFixed(1)}s) - shortest piece ${Math.min(...pieces.map(([, d]) => d)).toFixed(1)}s, average ${(total / pieces.length).toFixed(1)}s`);
        return { ...plan, pieces, single_pass: true, overlays: ovs, texts: txs, audios: auds };
      };
    }
    try {
      eng.s = E.sanitize({ ...s });
      await eng.process(movie, plans.map((p) => ({ ...p })), outDir, prepare);
    } catch (e) { log("ERROR: " + (e.stack || e.message || e)); }
    await this.app.releaseAwake();
    const stopped = !!eng.stopFlag;
    this.eng = null;
    if (this.expGo.isConnected) { this.expGo.disabled = false; this.expStop.disabled = true; }
    this.updateResume();
    toast(stopped ? "Stopped. The next export continues from where it stopped." : "Export finished");
  }

  async playPreview(whole) {
    if (!this.movie) return alertBox("Please choose a video first.");
    if (this.eng) return alertBox("Wait until the current export or preview has finished.");
    const chosen = whole ? this.parts.map((p, i) => [i, p]).filter(([, p]) => p.on) : [[this.partIdx, this.currentPart()]];
    if (!chosen.length) return alertBox("No part is selected.");
    const s = E.sanitize(this.cfg);
    s._fast = true;
    s.resolution = "480p";
    const plans = this.buildPlans(chosen);
    const out = E.join(this.app.paths.cache, "_preview");
    await bridge().remove(out, true);
    if (this.panel !== "Export") this.chips.pick("Export");
    this.expLog.clear();
    const eng = new E.StudioEngine(s, (m) => this.expLog.add(m), (f, t) => this.expProg.set(f, "Preview: " + t), () => {}, this.app.paths.cache);
    this.eng = eng;
    this.expGo.disabled = true; this.expStop.disabled = false;
    try {
      await eng.process(this.movie, plans, out, this.silencePrepare(this.movie, (m) => this.expLog.add(m), eng.job));
      const files = [];
      for (const p of plans) { const f = E.join(out, p.file); if (await bridge().exists(f)) files.push(f); }
      if (!files.length) throw new Error("No preview could be rendered (see the log).");
      let target = files[0];
      if (files.length > 1) {
        target = E.join(out, "preview_full.mp4");
        const [ok, err] = await E.concatFiles(files, target, this.app.paths.cache);
        if (!ok) throw new Error("Joining the preview failed: " + err);
      }
      if (!eng.stopFlag) { this.expProg.set(1, "Playing preview ..."); await playFile(target); }
    } catch (e) { this.expLog.add("ERROR: " + (e.message || e)); this.expProg.set(null, "Preview failed - see the log."); }
    this.eng = null;
    if (this.expGo.isConnected) { this.expGo.disabled = false; this.expStop.disabled = true; }
  }

  // ================================================================ dialogue
  buildDialogue() {
    const b = this.body, d = this.dl;
    const ch = () => this.app.changed();
    b.append(section("DIALOGUE CLEAN-UP (selected parts only)", "Works only on the ticked parts' time ranges, so it is fast. Every ticked part gets its own clean-up and is exported with it."),
      checkField("Dialogue clean-up ON (the Export tab's export button uses it)", d.on, (v) => { d.on = v; ch(); this.updateCutInfo(); }).el,
      ...this.headControls(),
      checkField("Noise reduction (FFmpeg)", d.denoise, (v) => { d.denoise = v; ch(); }).el,
      checkField("Keep only talking (Silero AI, else built-in detector)", d.vad, (v) => { d.vad = v; ch(); }).el,
      checkField("Text editing with Whisper (word list below)", d.whisper, (v) => { d.whisper = v; ch(); }).el,
      selectField("Whisper model for text editing", E.WHISPER, d.model, (v) => { d.model = v; ch(); }).el,
      new NumField("Speech padding (ms)", 0, 500, 10, d.pad, { fmt: 0, onChange: (v) => { d.pad = v; ch(); } }).el,
      new NumField("Minimum silence (ms)", 50, 1000, 10, d.minsil, { fmt: 0, onChange: (v) => { d.minsil = v; ch(); } }).el,
      new NumField("Shortest clip (s)", 0, 5, 0.1, d.minpiece, { fmt: 1, onChange: (v) => { d.minpiece = v; ch(); } }).el,
      note("Shortest clip: a dialogue piece shorter than this is made longer with the sound and picture around it, so no 0.2 second flash cuts are left (1.0 is a good value)."),
      checkField("Scan the picture: skip fast-cut montage, cut on shot changes (slower)", d.scan, (v) => { d.scan = v; ch(); }).el,
      textField("Words to remove (comma separated)", d.remove, (v) => { d.remove = v; ch(); }).el,
      textField("Language code (blank = auto, e.g. hi or en)", d.lang, (v) => { d.lang = v; ch(); }).el,
      note("Wherever nobody is talking, BOTH the picture and the sound are cut, so you get one continuous talking video. Picture and sound are cut together in one pass (always in sync) and every cut has a 20 ms fade (no clicks). Overlay and text times count from the start of the joined clip."),
      button("EXPORT TICKED PARTS WITH DIALOGUE CLEAN-UP", () => this.export(true), "primary big wide"));
  }

  // ================================================================ preview
  previewSettings(part, number) {
    const [ovs, txs, auds] = this.localized(part, number);
    return { ...this.cfg, overlays: ovs, texts: txs, audios: auds, _map: this._map };
  }

  scheduleRender() {
    clearTimeout(this.renderTimer);
    this.renderTimer = setTimeout(() => this.renderNow(), 90);
  }

  async renderNow() {
    if (!this.movie || !this.info) return;
    if (!this.el.isConnected || this.el.offsetParent === null) { this.dirtyView = true; return; }
    this.dirtyView = false;
    const tok = ++this.token;
    const p = this.currentPart();
    const t = p.start + this.tRel;
    try {
      const ps = this.previewSettings(p, this.partNumber(this.partIdx));
      const r = await P.compose(this.movie, t, ps, this.info, this.crop);
      if (tok !== this.token) return;
      r.map = ps._map;
      this.last = r;
      this.cv.width = r.W; this.cv.height = r.H;
      this.cv.getContext("2d").drawImage(r.canvas, 0, 0);
      this.stageMsg.hidden = true;
      this.drawBoxes();
    } catch (e) {
      if (tok !== this.token) return;
      this.stageMsg.hidden = false;
      this.stageMsg.textContent = "Preview: " + (e.message || e);
    }
  }

  onShow() { if (this.dirtyView || !this.last) this.scheduleRender(); }

  drawBoxes() {
    if (!this.last) return;
    const g = this.cv.getContext("2d");
    for (const bx of this.last.boxes) {
      const idx = this.itemIndexOf(bx);
      const on = idx === this.sel;
      g.save();
      g.strokeStyle = on ? "#39FF14" : "rgba(57,255,20,0.45)";
      g.lineWidth = on ? 3 : 1.5;
      g.setLineDash(on ? [] : [6, 4]);
      g.strokeRect(bx.x, bx.y, bx.w, bx.h);
      g.restore();
    }
  }

  // index in this.items of a preview box (the preview only gets the items visible in this part)
  itemIndexOf(bx) {
    const m = this.last && this.last.map;
    return m && m[bx.kind] && m[bx.kind][bx.index] !== undefined ? m[bx.kind][bx.index] : -1;
  }

  bindStage() {
    const cv = this.cv;
    this.hud = h("div", { class: "cd-hud" });
    if (cv.parentElement) cv.parentElement.append(this.hud);
    this.bindColourDrag(cv);
    const toFrame = (e) => {
      const r = cv.getBoundingClientRect();
      return [((e.clientX - r.left) / r.width) * cv.width, ((e.clientY - r.top) / r.height) * cv.height, r];
    };
    cv.addEventListener("pointerdown", (e) => {
      if (!this.last) return;
      const [x, y, r] = toFrame(e);
      if (this.pickMode) { this.pickAt(x, y); return; }
      const hit = [...this.last.boxes].reverse().find((b) => x >= b.x - 12 && x <= b.x + b.w + 12 && y >= b.y - 12 && y <= b.y + b.h + 12);
      if (!hit) return;
      const idx = this.itemIndexOf(hit);
      if (idx < 0) return;
      e.preventDefault();
      cv.setPointerCapture(e.pointerId);
      this.drag = { idx, hit, sx: x, sy: y, scale: r.width / cv.width, rect: r, moved: false };
      if (this.sel !== idx) { this.sel = idx; if (this.panel === "Overlay" || this.panel === "Text") this.showPanel(this.items[idx].kind === "text" ? "Text" : "Overlay"); }
    });
    cv.addEventListener("pointermove", (e) => {
      const d = this.drag;
      if (!d) return;
      const [x, y] = toFrame(e);
      d.dx = x - d.sx; d.dy = y - d.sy; d.moved = true;
      const g = this.ghost;
      g.hidden = false;
      const k = d.scale, off = cv.offsetLeft, offT = cv.offsetTop;
      Object.assign(g.style, { left: `${off + (d.hit.x + d.dx) * k}px`, top: `${offT + (d.hit.y + d.dy) * k}px`, width: `${d.hit.w * k}px`, height: `${d.hit.h * k}px` });
    });
    const end = () => {
      const d = this.drag;
      this.drag = null;
      this.ghost.hidden = true;
      if (!d || !d.moved || !this.last) return;
      const it = this.items[d.idx];
      const W = this.last.W, H = this.last.H;
      it.pos = "Custom"; it.hcenter = false; it.vcenter = false;
      it.x = Math.round(Math.max(0, Math.min(100, ((d.hit.x + d.dx) / W) * 100)) * 10) / 10;
      it.y = Math.round(Math.max(0, Math.min(100, ((d.hit.y + d.dy) / H) * 100)) * 10) / 10;
      if (this.panel === "Overlay" || this.panel === "Text") this.showPanel(this.panel);
      this.itemChanged();
    };
    cv.addEventListener("pointerup", end);
    cv.addEventListener("pointercancel", end);
  }

  togglePick() {
    const it = this.sel !== null ? this.items[this.sel] : null;
    if (!this.pickMode && (!it || it.kind !== "overlay")) { toast("Select an overlay first, then tap the colour to remove on the picture."); return; }
    this.pickMode = !this.pickMode;
    this.pickBtn.classList.toggle("on", this.pickMode);
    if (this.pickMode) toast("Tap the colour to remove on the picture");
  }

  pickAt(x, y) {
    this.pickMode = false;
    this.pickBtn.classList.remove("on");
    const it = this.sel !== null ? this.items[this.sel] : null;
    if (!it || it.kind !== "overlay" || !this.last) return;
    const d = this.last.canvas.getContext("2d").getImageData(Math.max(0, Math.min(this.last.W - 1, Math.round(x))), Math.max(0, Math.min(this.last.H - 1, Math.round(y))), 1, 1).data;
    it.key_color = "#" + [d[0], d[1], d[2]].map((v) => v.toString(16).padStart(2, "0")).join("").toUpperCase();
    it.chroma = true;
    toast("Colour picked: " + it.key_color);
    if (this.panel === "Overlay") this.showPanel("Overlay");
    this.itemChanged();
  }

  togglePlay() {
    if (this.playing) { this.playing = false; this.playBtn.textContent = "▶"; return; }
    if (!this.movie) return;
    this.playing = true;
    this.playBtn.textContent = "❚❚";
    const tick = async () => {
      if (!this.playing) return;
      const len = +this.pos.max;
      if (this.tRel >= len - 0.05) { this.playing = false; this.playBtn.textContent = "▶"; return; }
      this.tRel = Math.min(len, this.tRel + 0.25);
      this.pos.value = this.tRel; this.posLbl.textContent = E.tstr(this.tRel);
      await this.renderNow();
      setTimeout(tick, 30);
    };
    tick();
  }

  // ================================================================ project (save / open)
  getState() {
    const st = {
      movie: this.movie, cfg: JSON.parse(JSON.stringify(this.cfg)), items: JSON.parse(JSON.stringify(this.items)),
      parts: JSON.parse(JSON.stringify(this.parts)), part_idx: this.partIdx, t_rel: Math.round(this.tRel * 1000) / 1000, sel: this.sel,
      num_start: this.numStart,
      silence: { on: this.sil.on, db: +this.sil.db, min: +this.sil.min, pad: +this.sil.pad, key: this.silKey, list: this.silList },
      dialogue: { head_on: !!this.dl.head_on, head_sec: +this.dl.head_sec || 3, on: !!this.dl.on, denoise: this.dl.denoise, vad: this.dl.vad, whisper: this.dl.whisper, pad: +this.dl.pad, minsil: +this.dl.minsil,
        remove: this.dl.remove, lang: this.dl.lang, minpiece: +this.dl.minpiece, scan: this.dl.scan, model: this.dl.model },
      right_tab: this.panel,
      trim: { ...this.trim }, exported: [...this.doneNames], resume: !!this.resumeOn,
    };
    if (this.mode === "simple") st.range = { ...this.range };
    return st;
  }

  async setState(st, moviePath) {
    st = st || {};
    const problems = [];
    const step = async (label, fn) => { try { await fn(); } catch (e) { problems.push(`${this.mode} tab, ${label}: ${e.message || e}`); } };
    await step("movie", async () => { if (moviePath) { const ok = await this.loadMovie(moviePath); if (!ok) throw new Error("movie could not be opened"); } else this.clearMovie(); });
    await step("colour and settings", () => { this.cfg = E.sanitize({ ...(st.cfg || {}) }); });
    await step("texts and parts", () => {
      this.items = JSON.parse(JSON.stringify(st.items || []));
      this.parts = (st.parts || []).map((p) => {
        const q = { on: true, sil: true, ov: true, start: 0, end: 0, label: "", ...p };
        if (this.dur > 0) { q.start = Math.min(+q.start, this.dur); q.end = Math.min(+q.end, this.dur); }
        return q;
      });
      this.numStart = String(st.num_start ?? "1");
      if (this.mode === "simple") { const r = st.range || {}; this.range = { start: String(r.start ?? "0"), end: String(r.end ?? ""), count: String(r.count ?? "3"), length: String(r.length ?? "0") }; }
    });
    await step("silence", () => {
      const sl = st.silence || {};
      this.sil = { on: sl.on ?? true, db: +(sl.db ?? -35), min: +(sl.min ?? 2), pad: +(sl.pad ?? 0.25) };
      this.silList = []; this.silKey = null;
      if (this.movie && sl.key && sl.list && JSON.stringify(sl.key) === JSON.stringify(this.scanKey())) { this.silList = sl.list; this.silKey = sl.key; }
    });
    await step("dialogue", () => {
      const d = st.dialogue || {};
      this.dl = { head_on: !!d.head_on, head_sec: +(d.head_sec ?? 3) || 3, on: !!d.on, denoise: d.denoise ?? true, vad: d.vad ?? true, whisper: !!d.whisper, pad: +(d.pad ?? 150), minsil: +(d.minsil ?? 300),
        minpiece: +(d.minpiece ?? D.MIN_PIECE), scan: !!d.scan, remove: String(d.remove ?? "um, uh"), lang: String(d.lang ?? ""), model: d.model || "base" };
    });
    await step("clean start / resume", () => {
      const t = st.trim || {};
      this.trim = { on: !!t.on, sec: +(t.sec ?? 3) || 3, end_on: !!t.end_on, end_sec: +(t.end_sec ?? 3) || 3, voice: t.voice ?? true };
      this.doneNames = new Set(st.exported || []);
      this.resumeOn = st.resume ?? true;
    });
    await step("position", () => {
      const idx = parseInt(st.part_idx || 0, 10) || 0;
      this.sel = Number.isInteger(st.sel) && st.sel >= 0 && st.sel < this.items.length ? st.sel : null;
      this.panel = st.right_tab && this.chips.btns[st.right_tab] ? st.right_tab : this.panel;
      this.selectPart(Math.min(Math.max(0, idx), Math.max(0, this.parts.length - 1)), +(st.t_rel || 0));   // exactly where the work stopped
      this.chips.pick(this.panel);
    });
    return problems;
  }

  stopAll() { if (this.eng) this.eng.stop(); if (this.aiEng) this.aiEng.stop(); this.playing = false; }
}
