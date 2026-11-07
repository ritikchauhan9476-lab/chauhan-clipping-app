// Chauhan Clipping for Android: the main window (project bar, the four tabs, startup, autosave, back button).
import { bridge } from "./bridge.js";
import * as E from "./engine.js";
import * as PRJ from "./project.js";
import * as P from "./preview.js";
import { renderTextPng } from "./textrender.js";
import { Studio } from "./studio.js";
import { TimelineTab } from "./timeline.js";
import { AutoShortTab } from "./autoshort_ui.js";
import { chooseMedia } from "./files.js";
import { h, clear, button, ask, alertBox, promptBox, sheet, toast, closeTop, checkField, note } from "./ui.js";

const APP_NAME = "Chauhan Clipping";
const TABS = [["simple", "Simple Edit", "✂"], ["ai", "AI Clipping", "✦"], ["timeline", "Timeline", "☰"], ["auto", "Auto Short", "⚡"]];

class App {
  constructor() {
    this.projectPath = "";
    this.savedFp = null; this.savedViewFp = null;
    this.dirty = false; this.lastAutosave = Date.now();
    this.lastEncode = {};
    this.prefs = {};
    this.active = "simple";
  }

  async init() {
    window.addEventListener("error", (e) => this.reportError("Something", e.error || e.message));
    window.addEventListener("unhandledrejection", (e) => this.reportError("Something", e.reason));
    if (location.hash !== "#selftest" && !(await bridge().storageAccess())) await this.askStorage();
    this.paths = await bridge().paths();
    for (const d of [this.paths.out, this.paths.projects, this.paths.cache]) await bridge().mkdirs(d);
    P.setCacheDir(this.paths.cache);
    PRJ.setProjectDir(this.paths.projects);
    E.setTextRenderer(renderTextPng);
    this.prefs = await PRJ.readPrefs();
    this.build();
    this.baseline();
    setInterval(() => this.projectTick(), 3000);
    window.onAndroidBack = () => this.onBack();
    window.onAppPause = () => this.autosaveNow();
    if (location.hash === "#selftest") { (await import("./selftest.js")).runSelfTest(this); return; }
    await this.guard(() => this.startupRestore(), "Opening the last project")();
    // clean old temporary files (frames, text pictures) from earlier sessions
    try { for (const f of await bridge().list(this.paths.cache)) if (Date.now() - f.mtime > 2 * 86400e3) await bridge().remove(f.path || E.join(this.paths.cache, f.name), true); } catch (e) { /* ignore */ }
  }

  async askStorage() {
    await new Promise((resolve) => {
      const scr = h("div", { class: "welcome" },
        h("div", { class: "logo" }, "CHAUHAN CLIPPING"),
        h("p", {}, "To open your videos and save the edited clips in Movies/ChauhanClipping, the app needs access to your phone's files."),
        button("Allow access to files", async () => { await bridge().askStorage(); if (await bridge().storageAccess()) { scr.remove(); resolve(); } else toast("Please allow 'All files access' for Chauhan Clipping."); }, "primary big"),
        button("Continue without", () => { scr.remove(); resolve(); }, "quiet"));
      document.body.append(scr);
    });
  }

  // ---------------------------------------------------------------- layout
  build() {
    const root = document.getElementById("app");
    clear(root);
    this.projLbl = h("div", { class: "proj-name" }, "Untitled");
    this.projNote = h("div", { class: "proj-note" }, "");
    const head = h("header", { class: "topbar" },
      h("div", { class: "brand" }, "CC"),
      h("div", { class: "grow", onclick: () => this.projectMenu() }, this.projLbl, this.projNote),
      button("Save", this.guard(() => this.projectSave(), "Save"), "small primary"),
      button("☰", () => this.projectMenu(), "small quiet"));
    this.simple = new Studio(this, "simple");
    this.ai = new Studio(this, "ai");
    this.timeline = new TimelineTab(this);
    this.auto = new AutoShortTab(this, this.simple);
    this.views = { simple: this.simple, ai: this.ai, timeline: this.timeline, auto: this.auto };
    const main = h("main", { class: "views" });
    for (const [k] of TABS) { const v = h("section", { class: "view", "data-tab": k }, this.views[k].el); main.append(v); }
    this.nav = h("nav", { class: "bottomnav" }, ...TABS.map(([k, label, icon]) => h("button", { class: "navbtn", type: "button", "data-tab": k, onclick: () => this.setTab(k) }, h("span", { class: "ico" }, icon), h("span", {}, label))));
    root.append(head, main, this.nav);
    this.setTab("simple");
  }

  setTab(k) {
    if (!this.views[k]) k = "simple";
    this.active = k;
    for (const el of document.querySelectorAll(".view")) el.classList.toggle("on", el.dataset.tab === k);
    for (const el of document.querySelectorAll(".navbtn")) el.classList.toggle("on", el.dataset.tab === k);
    const v = this.views[k];
    if (v.onShow) setTimeout(() => v.onShow(), 30);
    window.scrollTo(0, 0);
  }

  onMovieChanged() { if (this.auto) this.auto.refreshMovie(); }
  changed() { /* the 3-second tick compares fingerprints */ }

  anyRunning() {
    return !!(this.simple.eng || this.simple.aiEng || this.ai.eng || this.ai.aiEng || this.timeline.eng || this.auto.running);
  }
  async releaseAwake() {
    setTimeout(async () => { if (!this.anyRunning()) await bridge().keepAwake(false); }, 300);
  }

  // ---------------------------------------------------------------- errors
  guard(fn, what) {
    return async (...a) => {
      try { return await fn(...a); } catch (e) { await this.reportError(what, e); return undefined; }
    };
  }
  async reportError(what, e) {
    const text = String((e && (e.stack || e.message)) || e);
    try {
      const f = E.join(this.paths ? this.paths.projects : "", "_error.log");
      const old = (await bridge().readText(f)) || "";
      await bridge().writeText(f, (old + `--- ${new Date().toISOString()}  ${what}\n${text}\n`).slice(-200000));
    } catch (er) { /* ignore */ }
    console.error(what, e);
    if (/ResizeObserver/.test(text)) return;
    await alertBox(`${what} did not work.\n\n${text.slice(-700)}\n\n(The same text is saved in ChauhanClipping/projects/_error.log.)`);
  }

  // ---------------------------------------------------------------- project state
  collectState() {
    return { active_tab: { simple: "Simple Edit", ai: "AI Clipping", timeline: "Timeline (advanced)", auto: "Auto Short" }[this.active],
      simple: this.simple.getState(), ai: this.ai.getState(), timeline: this.timeline.getState(), auto_short: this.auto.getState() };
  }
  static contentView(st) {
    const c = JSON.parse(JSON.stringify(st));
    delete c.active_tab;
    for (const k of ["simple", "ai"]) for (const key of ["right_tab", "part_idx", "t_rel", "sel"]) if (c[k]) delete c[k][key];
    if (c.timeline) { delete c.timeline.t; delete c.timeline.pps; }
    if (c.auto_short) delete c.auto_short.resume;
    return c;
  }
  baseline() {
    const st = this.collectState();
    this.savedFp = PRJ.fingerprint(App.contentView(st));
    this.savedViewFp = PRJ.fingerprint(st);
    this.dirty = false;
    this.refreshLabel();
  }
  refreshLabel() {
    const name = PRJ.titleOf(this.projectPath);
    this.projLbl.textContent = name + (this.dirty ? " *" : "");
    document.title = `${APP_NAME} - ${name}`;
  }
  note(t) { this.projNote.textContent = t; clearTimeout(this.noteT); this.noteT = setTimeout(() => { this.projNote.textContent = ""; }, 4000); }

  async resolveMovie(saved, cache) {
    if (!saved) return "";
    if (cache.has(saved)) return cache.get(saved);
    let found = await PRJ.findMovie(saved, this.projectPath);
    if (!found) {
      const yes = await ask(`The movie of this project was not found:\n${saved}\n\nDo you want to choose where it is now?`, [["No", false], ["Choose", true, "primary"]]);
      if (yes) found = (await chooseMedia("video", "Where is the movie?")) || "";
    }
    cache.set(saved, found);
    return found;
  }

  async applyState(st) {
    const cache = new Map();
    const problems = [];
    for (const [key, tab] of [["simple", this.simple], ["ai", this.ai]]) {
      const sub = st[key] || {};
      try { problems.push(...((await tab.setState(sub, await this.resolveMovie(sub.movie || "", cache))) || [])); } catch (e) { problems.push(`${key} tab: ${e.message || e}`); }
    }
    try { const tl = st.timeline || {}; await this.timeline.setState(tl, await this.resolveMovie(tl.movie || "", cache)); } catch (e) { problems.push(`timeline: ${e.message || e}`); }
    try { this.auto.setState(st.auto_short); await this.auto.refreshMovie(); } catch (e) { problems.push(`auto short tab: ${e.message || e}`); }
    const tabKey = { "Simple Edit": "simple", "AI Clipping": "ai", "Timeline (advanced)": "timeline", "Auto Short": "auto" }[st.active_tab] || "simple";
    this.setTab(tabKey);
    return problems;
  }
  blankState() { return { active_tab: "Simple Edit", simple: {}, ai: {}, timeline: {}, auto_short: {} }; }

  async confirmDiscard() {
    const st = this.collectState();
    if (PRJ.fingerprint(App.contentView(st)) !== this.savedFp) {
      const ans = await ask(`Do you want to save the changes to '${PRJ.titleOf(this.projectPath)}'?`, [["Cancel", null], ["Don't save", false], ["Save", true, "primary"]]);
      if (ans === null) return false;
      if (ans) { if (!(await this.projectSave())) return false; }
      else await PRJ.removeAutosave(this.projectPath);
    } else if (this.projectPath && PRJ.fingerprint(st) !== this.savedViewFp) {
      await this.writeProject(this.projectPath, true);
    }
    return true;
  }

  async projectNew() {
    if (this.anyRunning()) return alertBox("An export is still running. Stop it first.");
    if (!(await this.confirmDiscard())) return;
    const name = await promptBox("New project - choose a name", "New project");
    if (!name || !name.trim()) return;
    const path = E.join(this.paths.projects, name.trim().replace(/[\\/:*?"<>|]+/g, "_") + PRJ.EXT);
    if (await bridge().exists(path)) {
      const ok = await ask(`A project called '${name}' already exists. Replace it?`, [["Cancel", false], ["Replace", true, "danger"]]);
      if (!ok) return;
    }
    this.projectPath = "";
    await PRJ.removeAutosave("");
    const problems = await this.applyState(this.blankState());
    this.projectPath = path;
    if (!(await this.writeProject(path, true))) return;
    this.baseline();
    this.note("New project created: " + PRJ.titleOf(path));
    if (problems.length) await alertBox("The new project is ready, but:\n" + problems.slice(0, 6).join("\n"));
  }

  async projectOpen() {
    if (this.anyRunning()) return alertBox("An export is still running. Stop it first.");
    if (!(await this.confirmDiscard())) return;
    const path = await sheet("Open project", async (body, close) => {
      body.append(button("Browse files ...", async () => { const r = await bridge().pick("project"); if (r && r.path) close(r.path); }, "primary"));
      const list = h("div", { class: "media-list" });
      body.append(note("Projects in " + this.paths.projects), list);
      const items = await PRJ.listProjects();
      if (!items.length) list.append(note("No project saved yet."));
      for (const f of items) list.append(h("button", { class: "media-item", type: "button", onclick: () => close(f.path || E.join(this.paths.projects, f.name)) },
        h("div", { class: "mi-name" }, PRJ.titleOf(f.name)), h("div", { class: "mi-sub" }, new Date(f.mtime).toLocaleString())));
    });
    if (path) await this.openProject(path);
  }

  async openProject(path) {
    let st;
    try { st = await PRJ.load(path); } catch (e) { await alertBox(e.message || String(e)); return false; }
    let restored = false;
    const rec = await PRJ.newerAutosave(path);
    if (rec && (await ask("Unsaved changes from your last session were found for this project.\n\nDo you want to restore them?", [["No", false], ["Restore", true, "primary"]]))) {
      try { st = await PRJ.load(rec); restored = true; } catch (e) { /* keep the saved one */ }
    }
    this.projectPath = path;
    const problems = await this.applyState(st);
    this.baseline();
    if (restored) { this.savedFp = null; this.dirty = true; this.refreshLabel(); }
    await this.rememberLast(path);
    this.note("Project opened - you are back where you stopped.");
    if (problems.length) await alertBox("The project was opened, but these parts could not be restored:\n" + problems.slice(0, 6).join("\n"));
    return true;
  }

  async projectSave() { return this.projectPath ? this.writeProject(this.projectPath) : this.projectSaveAs(); }

  async projectSaveAs() {
    const start = this.projectPath ? PRJ.titleOf(this.projectPath) : this.simple.movie ? E.stem(this.simple.movie) : "my project";
    const name = await promptBox("Save project as", start);
    if (!name || !name.trim()) return false;
    const path = E.join(this.paths.projects, name.trim().replace(/[\\/:*?"<>|]+/g, "_") + PRJ.EXT);
    if (path !== this.projectPath && (await bridge().exists(path))) {
      const ok = await ask(`A project called '${name}' already exists. Replace it?`, [["Cancel", false], ["Replace", true, "danger"]]);
      if (!ok) return false;
    }
    return this.writeProject(path);
  }

  async writeProject(path, quiet = false) {
    const st = this.collectState();
    try { await PRJ.save(path, st); } catch (e) { await alertBox("The project could not be saved:\n" + (e.message || e)); return false; }
    const old = this.projectPath;
    this.projectPath = path;
    for (const p of new Set([path, old, ""])) await PRJ.removeAutosave(p);
    this.savedFp = PRJ.fingerprint(App.contentView(st));
    this.savedViewFp = PRJ.fingerprint(st);
    this.dirty = false;
    await this.rememberLast(path);
    this.refreshLabel();
    if (!quiet) { this.note("Saved " + new Date().toLocaleTimeString()); toast("Project saved"); }
    return true;
  }

  async rememberLast(path) {
    this.prefs.last_project = path;
    this.prefs.recent = [path, ...(this.prefs.recent || []).filter((p) => p !== path)].slice(0, 8);
    if (this.prefs.reopen_last === undefined) this.prefs.reopen_last = true;
    await PRJ.writePrefs(this.prefs);
  }

  async projectTick() {
    try {
      const st = this.collectState();
      this.dirty = PRJ.fingerprint(App.contentView(st)) !== this.savedFp;
      if (this.dirty && Date.now() - this.lastAutosave > 120000) await this.autosaveNow(st);
      this.refreshLabel();
    } catch (e) { /* never stops the app */ }
  }

  async autosaveNow(st = null) {
    try {
      st = st || this.collectState();
      if (PRJ.fingerprint(App.contentView(st)) === this.savedFp) {
        if (this.projectPath && PRJ.fingerprint(st) !== this.savedViewFp) await this.writeProject(this.projectPath, true);   // only the position changed
        return;
      }
      await PRJ.save(PRJ.autosavePath(this.projectPath), st);
      this.lastAutosave = Date.now();
    } catch (e) { /* ignore */ }
  }

  async startupRestore() {
    const last = this.prefs.last_project || "";
    if (this.prefs.reopen_last !== false && last && (await bridge().exists(last))) { await this.openProject(last); return; }
    if (await PRJ.newerAutosave("")) {
      if (await ask("Your last unsaved session was found.\n\nDo you want to restore it?", [["No", false], ["Restore", true, "primary"]])) {
        try {
          this.projectPath = "";
          await this.applyState(await PRJ.load(PRJ.autosavePath("")));
          this.baseline();
          this.savedFp = null; this.dirty = true; this.refreshLabel();
        } catch (e) { await alertBox("The saved session could not be restored."); }
      }
    }
  }

  projectMenu() {
    sheet("Project", (body, close) => {
      const go = (fn, what) => async () => { close(null); await this.guard(fn, what)(); };
      body.append(h("div", { class: "sub-title" }, PRJ.titleOf(this.projectPath) + (this.dirty ? "  (unsaved changes)" : "")),
        note(this.projectPath || "Not saved yet"),
        button("New project", go(() => this.projectNew(), "New project"), "wide"),
        button("Open project ...", go(() => this.projectOpen(), "Open"), "wide"),
        button("Save", go(() => this.projectSave(), "Save"), "primary wide"),
        button("Save as ...", go(() => this.projectSaveAs(), "Save as"), "wide"));
      const rec = (this.prefs.recent || []).filter((p) => p !== this.projectPath).slice(0, 8);
      if (rec.length) {
        body.append(h("div", { class: "sect-title" }, "RECENT PROJECTS"));
        for (const p of rec) body.append(button(PRJ.titleOf(p), go(async () => { if (await this.confirmDiscard()) await this.openProject(p); }, "Open recent"), "quiet wide"));
      }
      body.append(checkField("Open the last project at start", this.prefs.reopen_last !== false, async (v) => { this.prefs.reopen_last = v; await PRJ.writePrefs(this.prefs); }).el,
        note(`Exported videos: ${this.paths.out}`), note(`Projects: ${this.paths.projects}`));
      bridge().appInfo().then((i) => { if (i) body.append(note(`App version ${i.version || ""} ${i.abi ? "(" + i.abi + ")" : ""}`)); });
    });
  }

  onBack() {
    if (closeTop()) return true;
    if (this.active !== "simple") { this.setTab("simple"); return true; }
    this.autosaveNow();
    return false;
  }
}

const app = new App();
window.ccApp = app;
app.init().catch((e) => { document.body.append(h("pre", { class: "fatal" }, "The app could not start:\n" + (e.stack || e))); });
