// Auto Short tab (port of the desktop auto_short_ui.py): one button, continuous-dialogue shorts one by one.
// Colour, Crop, Overlay, Text, Music and Export settings come from the Simple Edit tab. Stop + Continue, also
// after closing the app (the resume point is saved in the project and in the output folder).
import * as A from "./autoshort.js";
import * as D from "./dialogue.js";
import * as E from "./engine.js";
import { bridge } from "./bridge.js";
import { showOutputs, resultRow } from "./files.js";
import { h, clear, section, note, button, NumField, checkField, textField, Progress, LogBox, alertBox } from "./ui.js";

export class AutoShortTab {
  constructor(app, simple) {
    this.app = app; this.simple = simple;
    this.running = false; this.job = null; this.resume = null; this.outDir = "";
    this.o = { use_parts: false, start: "0", end: "", min_len: A.MIN_LEN, max_len: A.MAX_LEN, keep_last: false, pad: D.PAD_MS,
      minsil: D.MIN_SIL_MS, denoise: true, min_piece: D.MIN_PIECE, scan_picture: true };
    this.build();
  }

  build() {
    this.el = h("div", { class: "studio" });
    this.movieLbl = h("div", { class: "movie-name" }, "Movie: (choose a movie in the Simple Edit tab)");
    this.goBtn = button("CREATE AUTO SHORTS", () => this.start(), "primary big");
    this.stopBtn = button("Stop", () => this.stop(), "danger");
    this.contBtn = button("Continue", () => this.continueRun(), "primary");
    this.resumeLbl = h("div", { class: "note" }, "");
    this.stopBtn.disabled = true; this.contBtn.disabled = true;
    this.prog = new Progress();
    this.list = h("div", { class: "results" }, note("No short yet."));
    this.log = new LogBox(160);
    const top = h("div", { class: "card" }, this.movieLbl, h("div", { class: "btnrow" }, this.goBtn, this.stopBtn, this.contBtn), this.resumeLbl,
      this.prog.el, button("Open folder", () => showOutputs(this.folder()), "quiet wide"));
    this.settings = h("div", { class: "panel" });
    this.el.append(top, h("div", { class: "sect-title" }, "SHORTS READY (they appear one by one)"), this.list, this.settings,
      h("div", { class: "sect-title" }, "LOG"), this.log.el);
    this.buildSettings();
  }

  buildSettings() {
    const f = clear(this.settings), o = this.o, ch = () => this.app.changed();
    f.append(section("WHICH PART OF THE MOVIE"),
      checkField("Only the parts ticked in the Simple Edit tab", o.use_parts, (v) => { o.use_parts = v; ch(); }).el,
      textField("Start (sec)", o.start, (v) => { o.start = v; ch(); }, { inputmode: "decimal" }).el,
      textField("End (sec)", o.end, (v) => { o.end = v; ch(); }, { inputmode: "decimal", placeholder: "movie end" }).el,
      note("Leave End empty to scan to the end of the movie. With 'ticked parts', every ticked part is scanned on its own, one after the other."),
      section("SHORT LENGTH"),
      new NumField("Minimum (sec)", 5, 120, 1, o.min_len, { fmt: 0, onChange: (v) => { o.min_len = v; ch(); } }).el,
      new NumField("Maximum (sec)", 10, 180, 1, o.max_len, { fmt: 0, onChange: (v) => { o.max_len = v; ch(); } }).el,
      checkField("Keep the last short even if it is shorter than the minimum", o.keep_last, (v) => { o.keep_last = v; ch(); }).el,
      section("TALKING DETECTION (AI)"),
      new NumField("Speech padding (ms)", 0, 500, 10, o.pad, { fmt: 0, onChange: (v) => { o.pad = v; ch(); } }).el,
      new NumField("Minimum silence (ms)", 50, 1000, 10, o.minsil, { fmt: 0, onChange: (v) => { o.minsil = v; ch(); } }).el,
      new NumField("Shortest clip (s)", 0, 5, 0.1, o.min_piece, { fmt: 1, onChange: (v) => { o.min_piece = v; ch(); } }).el,
      checkField("Noise reduction on the sound", o.denoise, (v) => { o.denoise = v; ch(); }).el,
      checkField("Scan the picture: skip fast-cut montage, cut on shot changes", o.scan_picture, (v) => { o.scan_picture = v; ch(); }).el,
      note("Everything where nobody is talking is cut from the picture AND the sound. Smaller padding = tighter, faster talking. Shortest clip: no piece is shorter than this, so there are no 0.2 s flashes. Scan the picture: parts with very fast picture cuts (action montage, music) are skipped and every cut is moved onto a real shot change (a little slower). The detector is the Silero AI model; without it a simpler built-in detector is used."),
      section("LOOK OF THE SHORTS"),
      note("Colour, Crop, Overlay, Text, Music and Export (quality, codec, bitrate) settings come from the Simple Edit tab. Overlay and text times count from the start of each short. Use {n} in a text to get Part 1, Part 2, ... Text editing with Whisper (words to remove) uses the Simple Edit > Dialogue tab."));
  }

  folder() { return this.simple.movie ? E.join(this.app.paths.out, `${E.fileBase(this.simple.movie)}_auto_short`) : this.app.paths.out; }

  onShow() { this.refreshMovie(); }

  async refreshMovie() {
    const mv = this.simple.movie;
    this.movieLbl.textContent = mv ? "Movie: " + E.basename(mv) : "Movie: (choose a movie in the Simple Edit tab)";
    if (!this.running) { try { this.setResume(await this.findResume()); } catch (e) { this.setResume(null); } }
  }

  setResume(r) {
    if (r && !r.finished && r.ranges && r.ranges.length) {
      this.resume = { ...r };
      this.contBtn.disabled = this.running;
      this.resumeLbl.textContent = `Stopped at ${E.mmss(+r.pos || 0)} - press Continue (next short: ${parseInt(r.next_number || 1, 10)})`;
    } else {
      this.resume = null;
      this.contBtn.disabled = true;
      this.resumeLbl.textContent = "";
    }
  }

  async findResume() {
    const mv = this.simple.movie;
    const r = this.resume;
    if (r && r.movie === mv) return r;
    if (mv) {
      try {
        const d = JSON.parse((await bridge().readText(E.join(this.folder(), "_resume.json"))) || "null");
        if (d && !d.finished && d.movie === mv) return d;
      } catch (e) { /* none */ }
    }
    return null;
  }

  async continueRun() {
    const r = await this.findResume();
    if (!r) { this.setResume(null); return alertBox("There is nothing to continue for this movie."); }
    return this.start(r);
  }

  addRow(d) {
    if (this.list.firstChild && this.list.firstChild.classList.contains("note")) clear(this.list);
    this.list.prepend(resultRow({ path: d.path, name: `Short ${d.number}  -  ${Math.round(d.length)} s` }, d.name));
  }

  async start(resume = null) {
    if (this.running) return;
    const sm = this.simple;
    await this.refreshMovie();
    if (!sm.movie) return alertBox("Choose a movie in the Simple Edit tab first.");
    const o = this.o;
    const minLen = +o.min_len, maxLen = +o.max_len;
    if (maxLen - minLen < 3) return alertBox("Maximum length must be at least 3 seconds longer than the minimum.");
    let ranges, ri = 0;
    if (resume) {
      const all = resume.ranges.map((x) => x.map(Number));
      ri = Math.min(Math.max(0, parseInt(resume.range_index || 0, 10)), all.length - 1);
      const pos = +(resume.pos ?? all[ri][0]);
      const [a, b] = all[ri];
      ranges = [[Math.max(a, Math.min(pos, b)), b], ...all.slice(ri + 1)].filter(([x, y]) => y - x > 0.5);
      if (!ranges.length) { this.setResume(null); return alertBox("This run was already finished - nothing is left to continue."); }
    } else if (o.use_parts) {
      ranges = sm.parts.filter((p) => p.on).map((p) => [+p.start, +p.end]);
      if (!ranges.length) return alertBox("No part is ticked in the Simple Edit tab.");
    } else {
      const a = Math.max(0, parseFloat(String(o.start).trim() || "0"));
      let b = String(o.end).trim() ? parseFloat(o.end) : sm.dur;
      if (!Number.isFinite(a) || !Number.isFinite(b)) return alertBox("Please enter the Start / End values as numbers.");
      b = Math.min(b, sm.dur);
      if (b - a < minLen) return alertBox("The range is shorter than the minimum short length.");
      ranges = [[a, b]];
    }
    const opts = { ...sm.dialogueOpts(), pad_ms: parseInt(o.pad, 10), min_sil_ms: parseInt(o.minsil, 10), denoise: !!o.denoise, vad: true,
      min_piece: +o.min_piece, scan_picture: !!o.scan_picture };
    const s = E.sanitize(sm.cfg);
    this.outDir = this.folder();
    this.log.clear();
    clear(this.list);
    this.prog.set(0, resume ? "Continuing ..." : "Starting ...");
    this.running = true;
    this.goBtn.disabled = true; this.contBtn.disabled = true; this.stopBtn.disabled = false;
    let first, prior, allRanges, base;
    if (resume) {
      first = parseInt(resume.next_number || sm.partNumber(0), 10);
      prior = [];
      for (const d of resume.made || []) if (await bridge().exists(d.path)) prior.push(d);
      for (const d of prior) this.addRow(d);
      allRanges = resume.ranges; base = ri;
      this.log.add(`Continuing from ${ranges[0][0].toFixed(0)}s - ${prior.length} short(s) were already made, the next one is number ${first}.`);
    } else { first = sm.partNumber(0); prior = []; allRanges = ranges.map((x) => [...x]); base = 0; }
    if (!prior.length) this.list.append(note("No short yet."));
    const job = new A.AutoShortJob({
      movie: sm.movie, ranges, opts, settings: s, items: JSON.parse(JSON.stringify(sm.items)), outDir: this.outDir, tmpDir: this.app.paths.cache,
      log: (m) => this.log.add(m), progress: (f, t) => this.prog.set(f, t), onShort: (d) => this.addRow(d),
      minLen, maxLen, firstNumber: first, keepLast: !!o.keep_last, allRanges, indexBase: base, priorMade: prior,
      onResume: (info) => { this.resume = info; this.app.changed(); },
    });
    this.job = job;
    await bridge().keepAwake(true, "Chauhan Clipping", "Making auto shorts ...");
    try { await job.run(); } catch (e) { this.log.add("ERROR: " + (e.stack || e.message || e)); }
    await this.app.releaseAwake();
    this.running = false; this.job = null;
    this.goBtn.disabled = false; this.stopBtn.disabled = true;
    this.setResume(this.resume);
  }

  stop() { if (this.job) { this.prog.set(null, "Stopping ..."); this.job.stop(); } }
  stopAll() { this.stop(); }

  getState() { return { resume: this.resume ? JSON.parse(JSON.stringify(this.resume)) : null, ...this.o }; }
  setState(st) {
    st = st || {};
    const o = this.o;
    o.use_parts = !!st.use_parts; o.start = String(st.start ?? "0"); o.end = String(st.end ?? "");
    o.min_len = +(st.min_len ?? A.MIN_LEN); o.max_len = +(st.max_len ?? A.MAX_LEN); o.keep_last = !!st.keep_last;
    o.pad = +(st.pad ?? D.PAD_MS); o.minsil = +(st.minsil ?? D.MIN_SIL_MS); o.denoise = st.denoise ?? true;
    o.min_piece = +(st.min_piece ?? D.MIN_PIECE); o.scan_picture = st.scan_picture ?? true;
    this.resume = null;
    this.setResume(st.resume || null);
    this.buildSettings();
  }
}
