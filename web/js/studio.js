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

export const ENCODE_KEYS = ["resolution", "fps", "codec", "quality", "rate_mode", "bitrate", "audio_bitrate"];

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
    this.dl = { denoise: true, vad: true, whisper: false, pad: 150, minsil: 300, minpiece: D.MIN_PIECE, scan: false, remove: "um, uh", lang: "", model: "base" };
    this.range = { start: "0", end: "", count: "3", length: "0" };
    this.numStart = "1";
    this.panel = mode === "ai" ? "AI" : "Parts";
    this.eng = null; this.aiEng = null; this.aiFound = [];
    this.pickMode = false;
    this.token = 0; this.renderTimer = 0; this.last = null;
    this.results = [];
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
    const bar = h("div", { class: "posbar" }, this.playBtn, this.posLbl, this.pos, this.pickBtn);
    this.sticky = h("div", { class: "sticky-preview" }, top, this.stage, bar);
    const names = this.mode === "ai" ? ["AI", "Parts", "Crop", "Colour", "Overlay", "Text", "Silence", "Export", "Dialogue"]
      : ["Parts", "Crop", "Colour", "Overlay", "Text", "Silence", "Export", "Dialogue"];
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
      Export: () => this.buildExport(), Dialogue: () => this.buildDialogue(),
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
    this.silList = []; this.silKey = null; this.last = null;
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
      const sil = checkField("cut silence", p.sil, (v) => { p.sil = v; this.refreshSum(); this.app.changed(); });
      const row = h("div", { class: "part" + (i === this.partIdx ? " cur" : "") },
        h("div", { class: "part-top" }, on.el, sil.el),
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
    let t = this.parts.length ? `${n} of ${this.parts.length} parts will be exported.` : "No parts yet. Make parts above.";
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

  // ================================================================ colour
  buildColour() {
    const b = this.body;
    b.append(section("COLOUR CORRECTION (live preview)", "Every control goes from -100 to +100 (0 = no change). Drag the slider or type a number. Double-tap a name to reset that control."));
    this.colourFields = {};
    for (const [sec, items] of CL.LAYOUT) {
      b.append(h("div", { class: "sub-title" }, sec));
      for (const [key, label] of items) {
        const nf = new NumField(label, -100, 100, 1, CL.toUi(key, this.cfg[key]), { fmt: 0, def: 0, onChange: (v) => { this.cfg[key] = CL.toCfg(key, v); this.scheduleRender(); this.app.changed(); } });
        this.colourFields[key] = nf;
        b.append(nf.el);
      }
    }
    b.append(button("Reset all colour", () => { for (const nf of Object.values(this.colourFields)) nf.set(0, true); }, "quiet wide"));
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
    this.items.forEach((it, i) => {
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
      const label = kind === "text" ? String(it.text).trim().slice(0, 36) || "(empty)" : E.basename(it.path);
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
    const state = h("div", { class: "note" });
    const showState = () => { state.textContent = it.hcenter || it.vcenter ? "Centred: " + (it.hcenter ? "left-right " : "") + (it.vcenter ? "up-down" : "") : "Free position (drag it on the picture or use the sliders)"; };
    const center = (hc, vc) => { if (hc !== null) it.hcenter = hc; if (vc !== null) it.vcenter = vc; showState(); this.itemChanged(); };
    showState();
    b.append(section("TEXT"), tf.el,
      button("Make selected number = part number", makeNumber, "small"),
      note("Select only the number in your text and press the button. It becomes {n}: 1 in the first part, 2 in the second ..."),
      selectField("Font", FONTS, FONTS.includes(it.font) ? it.font : "Noto Sans", (v) => { it.font = v; this.itemChanged(); }).el,
      checkField("Bold", it.bold !== false, (v) => { it.bold = v; this.itemChanged(); }).el,
      note("Hindi works in every font (the Devanagari fonts are Noto Sans Devanagari, Hind, Mukta, Baloo 2, Rozha One, Teko)."),
      this.posSelect(it),
      h("div", { class: "grid2" },
        button("Center left-right", () => center(true, null), "small quiet"), button("Center up-down", () => center(null, true), "small quiet"),
        button("Center on screen", () => center(true, true), "small"), button("Unlock (move freely)", () => center(false, false), "small quiet")),
      state,
      this.numItem("Left-right X %", 0, 100, 0.5, it, "x", 1, true), this.numItem("Up-down Y %", 0, 100, 0.5, it, "y", 1, true),
      this.numItem("Size (% of height)", 1, 20, 0.5, it, "size", 1), this.numItem("Opacity %", 5, 100, 1, it, "opacity", 0),
      this.numItem("Outline thickness", 0, 10, 1, it, "outline", 0), ...this.timing(it),
      colorField("Text colour", it.color, (v) => { it.color = v; this.itemChanged(); }).el,
      colorField("Outline colour", it.outline_color, (v) => { it.outline_color = v; this.itemChanged(); }).el,
      checkField("Shadow", it.shadow, (v) => { it.shadow = v; this.itemChanged(); }).el,
      checkField("Background box behind text", it.box, (v) => { it.box = v; this.itemChanged(); }).el,
      colorField("Box colour", it.box_color, (v) => { it.box_color = v; this.itemChanged(); }).el,
      this.numItem("Box opacity %", 0, 100, 1, it, "box_opacity", 0),
      button("Delete this text", () => this.removeSelected(), "danger"));
  }

  // ================================================================ silence
  scanKey() { return [this.movie, +this.sil.db, +this.sil.min]; }
  buildSilence() {
    const b = this.body, S = this.sil;
    const changed = () => { this.updateSilSummary(); this.app.changed(); };
    b.append(checkField("Cut long silent pauses (only in ticked parts)", S.on, (v) => { S.on = v; changed(); }).el,
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
    if (this.silSummary) this.silSummary.textContent = "Scanning the sound of the whole movie ...";
    try {
      const segs = await E.detectSilence(this.movie, this.sil.db, this.sil.min, this.dur);
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
      const keep = E.silenceKeepRanges(this.silList, p.start, p.end, +this.sil.pad, 0.3);
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
    this.silSummary.textContent = `${this.silList.length} silent stretches, ${tot.toFixed(0)}s in total. In the ticked parts about ${this.removedSeconds().toFixed(0)}s will be cut.`;
    this.silText.textContent = this.silList.slice(0, 300).map(([s, e]) => `${E.tstr(s)} - ${E.tstr(e)}  (${(e - s).toFixed(1)}s)`).join("\n");
  }

  // ================================================================ export
  buildExport() {
    const b = this.body, c = this.cfg;
    const set = (k) => (v) => { c[k] = v; this.app.changed(); this.showPanel("Export"); };
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
      selectField("Quality (encoder speed / detail)", Object.keys(E.QUALITY), c.quality, set("quality")).el,
      selectField("Bitrate mode", E.RATE_MODES, c.rate_mode, set("rate_mode")).el,
      selectField("Bitrate (kbps)", brOpts.map((x) => [x, `${x} kbps (${(+x / 1000).toFixed(1)} Mbps)`]), String(c.bitrate), (v) => { c.bitrate = +v; this.app.changed(); }).el,
      textField("Or type a bitrate (kbps)", String(c.bitrate), (v) => { const n = parseFloat(v); if (n > 0) { c.bitrate = Math.round(Math.min(E.MAX_BITRATE, Math.max(500, n))); this.app.changed(); this.showPanel("Export"); } }, { inputmode: "numeric" }).el,
      selectField("Audio bitrate", E.ABR, c.audio_bitrate, set("audio_bitrate")).el,
      note("Exact bitrate: the file gets the bitrate you choose (12000 kbps = 12 Mbps). File size = bitrate x length. Quality mode: constant quality, the number is only an upper limit. Resolution 'Original' keeps your movie's own size. Phone hardware = fast (uses the phone's video chip); if it fails, the CPU encoder (x264, the same as the desktop software) is used automatically. With the CPU encoder 'Fast (phone)' quality exports much faster than 'High'."),
      section("PREVIEW (see your edit before exporting)"),
      button("Play selected part with sound", () => this.playPreview(false), "wide"),
      button("Play whole edit (all ticked parts)", () => this.playPreview(true), "wide"));
    this.expGo = button("EXPORT SELECTED PARTS", () => this.export(false), "primary big wide");
    this.expStop = button("Stop", () => this.eng && this.eng.stop(), "danger wide");
    this.expGo.disabled = !!this.eng; this.expStop.disabled = !this.eng;
    this.expProg = this.expProg || new Progress();
    this.expLog = this.expLog || new LogBox(160);
    this.resBox = this.resBox || h("div", { class: "results" });
    b.append(this.expGo, this.expStop, this.expProg.el, button("Open exported videos", () => this.openOutputs(), "quiet wide"), this.resBox, this.expLog.el);
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

  buildPlans(chosen) {
    const base = E.fileBase(this.movie);
    const pad = +this.sil.pad;
    return chosen.map(([idx, p]) => {
      const number = this.partNumber(idx);
      const [ovs, txs, auds] = this.localized(p, number);
      const pieces = this.sil.on && p.sil ? E.silenceKeepRanges(this.silList, p.start, p.end, pad, 0.3) : [[p.start, p.end - p.start]];
      const mm = Math.floor(p.start / 60), ss = Math.floor(p.start % 60);
      return { file: `${base}_part${String(number).padStart(2, "0")}_${E.pad2(mm)}m${E.pad2(ss)}s.mp4`, start: p.start, end: p.end, label: p.label || "", pieces, overlays: ovs, texts: txs, audios: auds, number };
    });
  }

  async export(withDialogue) {
    if (!this.movie) return alertBox("Please choose a video first.");
    if (this.eng) return;
    const chosen = this.parts.map((p, i) => [i, p]).filter(([, p]) => p.on);
    if (!this.parts.length) return alertBox("No parts yet. Make parts first (Parts).");
    if (!chosen.length) return alertBox("No part is selected. Tick at least one part.");
    for (const [i, p] of chosen) if (p.end <= p.start + 0.5 || p.start < 0 || p.end > this.dur + 0.05) return alertBox(`Part ${i + 1} has invalid times. Check its Start and End.`);
    const dl = withDialogue ? this.dialogueOpts() : null;
    const needsSilence = !withDialogue && this.sil.on && chosen.some(([, p]) => p.sil);
    if (needsSilence && JSON.stringify(this.silKey) !== JSON.stringify(this.scanKey())) {
      if (this.expProg) this.expProg.set(0, "Scanning silence first, then exporting ...");
      if (!(await this.scanSilence())) return;
    }
    const s = E.sanitize(this.cfg);
    if (withDialogue) { s.fade_sec = D.FADE; s._joint_fade = D.FADE; s._denoise = !!dl.denoise; }
    for (const k of ENCODE_KEYS) this.app.lastEncode[k] = s[k];
    const items = JSON.parse(JSON.stringify(this.items));
    const plans = this.buildPlans(chosen);
    const outDir = this.outDir(withDialogue);
    this.lastOut = outDir;
    if (this.panel !== "Export") this.chips.pick("Export");
    this.expLog.clear(); clear(this.resBox);
    const eng = new E.StudioEngine(s, (m) => this.expLog.add(m), (f, t) => this.expProg.set(f, t),
      (c) => this.resBox.prepend(resultRow({ path: c.path }, c.text)), this.app.paths.cache);
    this.eng = eng;
    this.expGo.disabled = true; this.expStop.disabled = false;
    await bridge().keepAwake(true, "Chauhan Clipping", "Exporting your parts ...");
    const movie = this.movie, tmp = this.app.paths.cache, log = (m) => this.expLog.add(m);
    let prepare = null;
    if (dl) {
      prepare = async (plan) => {
        log(`Dialogue: finding the talking in ${plan.file} (${plan.start.toFixed(1)}s - ${plan.end.toFixed(1)}s)`);
        const pieces = await D.analyze(movie, plan.start, plan.end, dl, tmp, log, eng.job);
        if (!pieces.length) return null;
        const total = pieces.reduce((a, [, d]) => a + d, 0);
        const [ovs, txs, auds] = relativeItems(items, total, plan.number);
        log(`  ${pieces.length} dialogue pieces, ${total.toFixed(1)}s of talking (from ${(plan.end - plan.start).toFixed(1)}s) - shortest piece ${Math.min(...pieces.map(([, d]) => d)).toFixed(1)}s, average ${(total / pieces.length).toFixed(1)}s`);
        return { ...plan, pieces, single_pass: true, overlays: ovs, texts: txs, audios: auds };
      };
    }
    try {
      eng.s = E.sanitize({ ...s });
      await eng.process(movie, plans.map((p) => ({ ...p })), outDir, prepare);
    } catch (e) { log("ERROR: " + (e.stack || e.message || e)); }
    await this.app.releaseAwake();
    this.eng = null;
    if (this.expGo.isConnected) { this.expGo.disabled = false; this.expStop.disabled = true; }
    toast("Export finished");
  }

  async playPreview(whole) {
    if (!this.movie) return alertBox("Please choose a video first.");
    if (this.eng) return alertBox("Wait until the current export or preview has finished.");
    const chosen = whole ? this.parts.map((p, i) => [i, p]).filter(([, p]) => p.on) : [[this.partIdx, this.currentPart()]];
    if (!chosen.length) return alertBox("No part is selected.");
    if (this.sil.on && chosen.some(([, p]) => p.sil) && JSON.stringify(this.silKey) !== JSON.stringify(this.scanKey()) && this.parts.length) {
      if (!(await this.scanSilence())) return;
    }
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
      await eng.process(this.movie, plans, out);
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
      dialogue: { denoise: this.dl.denoise, vad: this.dl.vad, whisper: this.dl.whisper, pad: +this.dl.pad, minsil: +this.dl.minsil,
        remove: this.dl.remove, lang: this.dl.lang, minpiece: +this.dl.minpiece, scan: this.dl.scan, model: this.dl.model },
      right_tab: this.panel,
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
        const q = { on: true, sil: true, start: 0, end: 0, label: "", ...p };
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
      this.dl = { denoise: d.denoise ?? true, vad: d.vad ?? true, whisper: !!d.whisper, pad: +(d.pad ?? 150), minsil: +(d.minsil ?? 300),
        minpiece: +(d.minpiece ?? D.MIN_PIECE), scan: !!d.scan, remove: String(d.remove ?? "um, uh"), lang: String(d.lang ?? ""), model: d.model || "base" };
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
