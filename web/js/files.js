// Choosing files on the phone (videos, photos, music, projects) and the list of exported videos.
import { h, sheet, button, toast, confirmBox, clear } from "./ui.js";
import { bridge } from "./bridge.js";
import * as E from "./engine.js";

const fmtSize = (b) => (b > 1e9 ? (b / 1e9).toFixed(2) + " GB" : b > 1e6 ? (b / 1e6).toFixed(1) + " MB" : Math.max(1, Math.round(b / 1e3)) + " KB");
const fmtDur = (ms) => (ms ? E.mmss(ms / 1000) : "");

// kind: "video" | "image_video" | "audio". Returns a file path or null.
export async function chooseMedia(kind, title) {
  return sheet(title, async (body, close) => {
    const browse = button("Browse files ...", async () => {
      const r = await bridge().pick(kind);
      if (r && r.path) close(r.path);
      else if (r && r.error) toast(r.error);
    }, "primary");
    const search = h("input", { type: "search", placeholder: "Search by name" });
    const list = h("div", { class: "media-list" }, h("div", { class: "note" }, "Loading the files on your phone ..."));
    body.append(h("div", { class: "row" }, browse), search, list);
    let items = [];
    try { items = await bridge().media(kind); } catch (e) { items = []; }
    const draw = () => {
      clear(list);
      const q = search.value.trim().toLowerCase();
      const shown = items.filter((m) => !q || m.name.toLowerCase().includes(q)).slice(0, 400);
      if (!shown.length) list.append(h("div", { class: "note" }, items.length ? "Nothing matches." : "No files found. Use 'Browse files'."));
      for (const m of shown) {
        list.append(h("button", { class: "media-item", type: "button", onclick: () => close(m.path) },
          h("div", { class: "mi-name" }, m.name),
          h("div", { class: "mi-sub" }, [fmtDur(m.duration), m.size ? fmtSize(m.size) : "", m.folder || ""].filter(Boolean).join("  ·  "))));
      }
    };
    search.addEventListener("input", draw);
    draw();
  });
}

export async function playFile(path) {
  const r = await bridge().openFile(path, E.isVideo(path) ? "video/mp4" : "");
  if (r === false) toast("No app found to play this file.");
}
export async function shareFile(path) { await bridge().share(path, E.isVideo(path) ? "video/mp4" : ""); }

// all exported videos of a folder (newest first) with Play / Share / Delete
export async function showOutputs(folder, title = "Exported videos") {
  return sheet(title, async (body) => {
    body.append(h("div", { class: "note" }, "Folder: " + folder));
    const list = h("div", { class: "media-list" });
    body.append(list);
    const draw = async () => {
      clear(list);
      const files = (await bridge().list(folder)).filter((f) => !f.isDir && /\.(mp4|mov|mkv)$/i.test(f.name)).sort((a, b) => b.mtime - a.mtime);
      if (!files.length) list.append(h("div", { class: "note" }, "No video here yet."));
      for (const f of files) {
        const p = f.path || E.join(folder, f.name);
        list.append(h("div", { class: "out-item" },
          h("div", { class: "mi-name" }, f.name), h("div", { class: "mi-sub" }, fmtSize(f.size)),
          h("div", { class: "btnrow" },
            button("Play", () => playFile(p), "small primary"), button("Share", () => shareFile(p), "small"),
            button("Delete", async () => { if (await confirmBox(`Delete ${f.name}?`)) { await bridge().remove(p); draw(); } }, "small danger"))));
      }
    };
    await draw();
  });
}

export function resultRow(d, extra = "") {
  return h("div", { class: "out-item" },
    h("div", { class: "mi-name" }, d.name || E.basename(d.path)), extra ? h("div", { class: "mi-sub" }, extra) : null,
    h("div", { class: "btnrow" }, button("Play", () => playFile(d.path), "small primary"), button("Share", () => shareFile(d.path), "small")));
}
