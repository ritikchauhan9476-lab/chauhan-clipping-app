// AI Clips tab: PeakCut + AutoClip style clipping for movies and downloaded YouTube videos, part by part.
import * as AC from "./aiclips.js";
import * as E from "./engine.js";
import * as PRJ from "./project.js";
import { bridge } from "./bridge.js";
import { chooseMedia, showOutputs } from "./files.js";
import { linkSheet } from "./linkdl.js";
import { h, clear, section, note, button, NumField, checkField, textField, selectField, Progress, LogBox, alertBox, toast } from "./ui.js";

export class AIClipsTab {
  constructor(app, simple) {
    this.app = app; this.simple = simple;
    this.movie = ""; this.job = null; this.running = false;
    this.o = { platform: Object.keys(AC.PLATFORMS)[0], count: 3, min: 20, max: 60, part: 10, from: 0, to: 0, fit: "Blur background",
      captions: true, style: "Bounce", capPos: "Bottom", hook: true, boost: true, lang: "", textLang: "" };
    this.build();
  }

  get ai() {
    const p = this.app.prefs || {};
    return p.ai || (p.ai = { provider: "gemini", key: "", model: "", base: "", stt: undefined });
  }

  build() {
    this.el = h("div", { class: "studio" });
    this.movieLbl = h("div", { class: "movie-name" }, "No video chosen");
    this.prog = new Progress();
    this.goBtn = button("MAKE AI CLIPS", () => this.start(), "primary big");
    this.stopBtn = button("Stop", () => this.stop(), "danger");
    this.stopBtn.disabled = true;
    this.list = h("div", { class: "results" }, note("No clip yet. They appear here one by one, part after part."));
    this.log = new LogBox(160);
    const top = h("div", { class: "card" },
      h("div", { class: "sub-title" }, "AI CLIPS - movie or YouTube video to ready-to-post clips"),
      this.movieLbl,
      h("div", { class: "btnrow" }, button("Choose video", () => this.choose(), "primary"), button("YouTube link", () => this.fromLink()),
        button("Use Simple Edit's video", () => this.useSimple(), "quiet")),
      h("div", { class: "btnrow" }, this.goBtn, this.stopBtn), this.prog.el,
      button("Open clips folder", () => showOutputs(this.folder()), "quiet wide"));
    this.settings = h("div", { class: "panel" });
    this.el.append(top, h("div", { class: "sect-title" }, "CLIPS (with cover + post text)"), this.list, this.settings,
      h("div", { class: "sect-title" }, "LOG"), this.log.el);
    this.buildSettings();
  }

  buildSettings() {
    const f = clear(this.settings), o = this.o, ai = this.ai, ch = () => this.app.changed();
    const saveAi = () => PRJ.writePrefs(this.app.prefs);
    const num = (label, key, lo, hi, step, fmt) => new NumField(label, lo, hi, step, o[key], { fmt, onChange: (v) => { o[key] = v; ch(); } }).el;
    const prov = AC.PROVIDERS[ai.provider] || AC.PROVIDERS.gemini;
    const keyField = textField("AI key", ai.key || "", (v) => { ai.key = String(v).trim(); saveAi(); }, { type: "password", placeholder: "paste your key" });
    const testRes = h("div", { class: "note" });
    f.append(...[
      section("AI SERVICE", "The AI listens to every part (speech to text, Hindi too) and picks the best moments. Your key stays on this phone."),
      selectField("Service", Object.keys(AC.PROVIDERS).map((k) => AC.PROVIDERS[k].label), prov.label, (v) => {
        ai.provider = Object.keys(AC.PROVIDERS).find((k) => AC.PROVIDERS[k].label === v) || "gemini"; ai.model = ""; ai.base = ""; ai.stt = undefined; saveAi(); this.buildSettings();
      }).el,
      keyField.el,
      textField("Model (empty = " + prov.model + ")", ai.model || "", (v) => { ai.model = String(v).trim(); saveAi(); }).el,
      ai.provider === "custom" || ai.provider === "openrouter" ? textField("Address (base URL)", ai.base || prov.base, (v) => { ai.base = String(v).trim(); saveAi(); }).el : null,
      prov.kind === "openai" ? textField("Speech-to-text model (empty = none)", ai.stt === undefined ? prov.stt || "" : ai.stt, (v) => { ai.stt = String(v).trim(); saveAi(); }).el : null,
      h("div", { class: "btnrow" }, button("Test the key", async () => {
        testRes.textContent = "Testing ...";
        try { testRes.textContent = (await AC.testKey(this.ai)) ? "The key works." : "The AI answered, but not as expected."; } catch (e) { testRes.textContent = String(e.message || e); }
      }, "small")),
      testRes,
      note("Free: Google Gemini (aistudio.google.com -> Get API key) does both listening and choosing with one key. Groq (console.groq.com) is free too. Without a key the app still makes clips from the moments with the most talking, but without captions or titles."),
      section("CLIPS"),
      selectField("Platform", Object.keys(AC.PLATFORMS), o.platform, (v) => { o.platform = v; const p = AC.PLATFORMS[v]; o.min = p.min; o.max = p.max; ch(); this.buildSettings(); }).el,
      num("Clips per part", "count", 1, 10, 1, 0), num("Shortest clip (s)", "min", 5, 300, 5, 0), num("Longest clip (s)", "max", 10, 600, 5, 0),
      selectField("Picture", ["Blur background", "Crop (fill frame)", "Black bars"], o.fit, (v) => { o.fit = v; ch(); }).el,
      section("PART BY PART (fast)", "The video is worked on in parts: the clips of part 1 are ready while part 2 is still being listened to."),
      num("Part length (min)", "part", 2, 30, 1, 0), num("From (min)", "from", 0, 1000, 1, 0), num("To (min, 0 = end)", "to", 0, 1000, 1, 0),
      section("CAPTIONS + HOOK"),
      checkField("Word-by-word captions (the spoken word lights up)", o.captions, (v) => { o.captions = v; ch(); }).el,
      selectField("Caption style", Object.keys(AC.CAPTION_STYLES), o.style, (v) => { o.style = v; ch(); }).el,
      selectField("Caption place", Object.keys(AC.CAPTION_POS), o.capPos, (v) => { o.capPos = v; ch(); }).el,
      checkField("Hook title for the first 3 seconds", o.hook, (v) => { o.hook = v; ch(); }).el,
      checkField("Retention boost (punch-in zoom on cuts, progress bar, even loud speech)", o.boost, (v) => { o.boost = v; ch(); }).el,
      textField("Speech language (empty = automatic; hi = Hindi, en = English)", o.lang, (v) => { o.lang = String(v).trim(); ch(); }).el,
      textField("Language of titles / hashtags (empty = like the speech)", o.textLang, (v) => { o.textLang = String(v).trim(); ch(); }, { placeholder: "e.g. Hinglish, English, Hindi" }).el,
      note("Quality, codec, bitrate, fps and colour come from Simple Edit > Export / Colour. Every clip gets a cover picture (_cover.jpg) and its post text (_post.txt: title, description, hashtags); tap 'Copy text' on a clip.")].filter(Boolean));
  }

  folder() { return E.join(this.app.paths.out, "AI Clips", this.movie ? E.stem(this.movie).replace(/[\\/:*?"<>|]+/g, "_").slice(0, 60) : ""); }

  setMovie(p) { this.movie = p || ""; this.movieLbl.textContent = this.movie ? "Video: " + E.basename(this.movie) : "No video chosen"; this.app.changed(); }
  async choose() { const p = await chooseMedia("video", "Choose a movie / video"); if (p) this.setMovie(p); }
  async fromLink() { const p = await linkSheet(this.app); if (p) this.setMovie(p); }
  useSimple() { if (!this.simple.movie) return alertBox("Simple Edit has no video yet."); this.setMovie(this.simple.movie); }

  addRow(d) {
    if (this.list.querySelector(".note")) clear(this.list);
    const img = h("img", { class: "thumb", src: bridge().fileUrl(d.cover), alt: "" });
    const row = h("div", { class: "result" }, img,
      h("div", { class: "grow" }, h("div", { class: "res-title" }, `${d.n}. ${d.title}`),
        h("div", { class: "note" }, `${d.length.toFixed(0)}s  |  score ${d.score}  |  ${E.tstr(d.start)} - ${E.tstr(d.end)}`),
        h("div", { class: "btnrow" }, button("Play", () => bridge().openFile(d.path, "video/mp4"), "small"),
          button("Share", () => bridge().share(d.path, "video/mp4"), "small"),
          button("Copy text", async () => { try { await navigator.clipboard.writeText(d.text); toast("Post text copied"); } catch (e) { alertBox(d.text); } }, "small quiet"))));
    this.list.append(row);
  }

  async start() {
    if (this.running) return;
    if (!this.movie) return alertBox("Choose a video first (Choose video, YouTube link, or Simple Edit's video).");
    const o = this.o, p = AC.PLATFORMS[o.platform] || Object.values(AC.PLATFORMS)[0];
    const opts = { ...o, aspect: p.aspect, platformName: o.platform, partSec: Math.max(60, o.part * 60), from: o.from * 60, to: o.to > 0 ? o.to * 60 : null,
      min: Math.min(o.min, o.max), max: Math.max(o.min, o.max) };
    const s = E.sanitize(this.simple.cfg);
    clear(this.list); this.list.append(note("Working on part 1 ..."));
    this.log.clear();
    this.running = true; this.goBtn.disabled = true; this.stopBtn.disabled = false;
    this.job = new AC.AIClipsJob({ movie: this.movie, settings: s, opts, ai: { ...this.ai }, outDir: this.folder(), tmpDir: this.app.paths.cache,
      log: (m) => this.log.add(m), progress: (f, t) => this.prog.set(f, t), onClip: (d) => this.addRow(d) });
    await bridge().keepAwake(true, "Chauhan Clipping", "Making AI clips ...");
    try { const made = await this.job.run(); toast(`${made.length} clip(s) made`); if (!made.length && !this.job.cancelled) { clear(this.list); this.list.append(note("No clip was made - see the log.")); } }
    catch (e) { this.log.add("ERROR: " + (e.stack || e.message || e)); }
    await this.app.releaseAwake();
    this.running = false; this.job = null; this.goBtn.disabled = false; this.stopBtn.disabled = true;
  }

  stop() { if (this.job) this.job.stop(); }

  getState() { return { movie: this.movie, o: { ...this.o } }; }
  setState(st) { st = st || {}; this.o = { ...this.o, ...(st.o || {}) }; this.setMovie(st.movie || ""); this.buildSettings(); }
}
