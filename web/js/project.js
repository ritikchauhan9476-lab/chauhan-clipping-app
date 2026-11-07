// Project files (port of the desktop project.py): the whole editing session in one .ccproj (JSON) file,
// written atomically, with autosave, crash recovery, recent projects. Same format as the desktop software.
import * as E from "./engine.js";
import { bridge } from "./bridge.js";

export const EXT = ".ccproj";
export const FORMAT = 1;
let DIR = "";
export function setProjectDir(d) { DIR = d; }
export const projectDir = () => DIR;
const prefsFile = () => E.join(DIR, "_prefs.json");
const untitledAutosave = () => E.join(DIR, "_untitled.autosave");

export class ProjectError extends Error {}

export function jsonable(x) {
  if (Array.isArray(x)) return x.map(jsonable);
  if (x && typeof x === "object") { const o = {}; for (const [k, v] of Object.entries(x)) if (v !== undefined && typeof v !== "function") o[k] = jsonable(v); return o; }
  if (typeof x === "number" && !Number.isFinite(x)) return 0;
  return x;
}

function sortKeys(x) {
  if (Array.isArray(x)) return x.map(sortKeys);
  if (x && typeof x === "object") { const o = {}; for (const k of Object.keys(x).sort()) o[k] = sortKeys(x[k]); return o; }
  return x;
}
export const fingerprint = (state) => JSON.stringify(sortKeys(jsonable(state)));

function stamp() {
  const d = new Date(), p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}

export async function save(path, state) {
  const data = { app: "ChauhanClipping", format: FORMAT, saved: stamp(), state: jsonable(state) };
  await bridge().mkdirs(E.dirname(path));
  const tmp = path + ".tmp";
  const ok = await bridge().writeText(tmp, JSON.stringify(data, null, 1));
  if (ok === false) throw new ProjectError("The project could not be written: " + path);
  await bridge().remove(path);
  if ((await bridge().rename(tmp, path)) === false) throw new ProjectError("The project could not be saved: " + path);
}

export async function load(path) {
  const txt = await bridge().readText(path);
  if (txt === null || txt === undefined) throw new ProjectError("The project file was not found:\n" + path);
  let data;
  try { data = JSON.parse(txt); } catch (e) { throw new ProjectError("This project file is damaged and could not be read."); }
  if (!data || data.app !== "ChauhanClipping" || !("state" in data)) throw new ProjectError("This is not a Chauhan Clipping project file.");
  if (parseInt(data.format || 1, 10) > FORMAT) throw new ProjectError("This project was saved by a newer version of the software. Please update the app.");
  return data.state;
}

// The movie of a saved project: the saved path, or a phone video with the same file name.
export async function findMovie(saved, projectPath = "") {
  if (!saved) return "";
  if (await bridge().exists(saved)) return saved;
  const name = E.basename(saved);
  if (projectPath) {
    const near = E.join(E.dirname(projectPath), name);
    if (await bridge().exists(near)) return near;
  }
  try {
    const vids = await bridge().media("video");
    const hit = vids.find((v) => v.name === name);
    if (hit) return hit.path;
  } catch (e) { /* no media list */ }
  return "";
}

export const autosavePath = (p) => (p ? p + ".autosave" : untitledAutosave());

export async function newerAutosave(projectPath) {
  const a = autosavePath(projectPath);
  const sa = await bridge().stat(a);
  if (!sa) return "";
  if (projectPath) {
    const sp = await bridge().stat(projectPath);
    if (sp && sa.mtime <= sp.mtime) return "";
  }
  return a;
}

export async function removeAutosave(p) { await bridge().remove(autosavePath(p)); }

export async function readPrefs() {
  try { const d = JSON.parse((await bridge().readText(prefsFile())) || "{}"); return d && typeof d === "object" ? d : {}; } catch (e) { return {}; }
}
export async function writePrefs(prefs) { try { await bridge().writeText(prefsFile(), JSON.stringify(prefs, null, 1)); } catch (e) { /* ignore */ } }

export const titleOf = (p) => (p ? E.stem(p).replace(/\.ccproj$/, "") : "Untitled");

export async function listProjects() {
  const items = await bridge().list(DIR);
  return items.filter((f) => !f.isDir && f.name.endsWith(EXT)).sort((a, b) => b.mtime - a.mtime);
}
