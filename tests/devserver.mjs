// Development server: serves web/ and answers the /dev/ bridge calls with the machine's ffmpeg, so the whole
// app can be tested in a desktop browser. Run: node tests/devserver.mjs [port] [media-folder]
import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { nodeBridge } from "./nodebridge.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const WEB = path.join(HERE, "..", "web");
const PORT = +(process.argv[2] || 8765);
const MEDIA = process.argv[3] || "/tmp/cc-test/media";
const ROOT = process.env.CC_DEV_ROOT || "/tmp/cc-dev";
const B = nodeBridge({ root: ROOT });
const jobs = new Map();
const TYPES = { ".html": "text/html", ".js": "text/javascript", ".mjs": "text/javascript", ".css": "text/css", ".png": "image/png",
  ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".wasm": "application/wasm", ".ttf": "font/ttf", ".json": "application/json", ".onnx": "application/octet-stream" };
const KINDS = { video: /\.(mp4|mkv|mov|avi|webm|m4v|ts)$/i, image_video: /\.(png|jpe?g|webp|gif|mp4|mov|webm)$/i, audio: /\.(mp3|m4a|aac|wav|ogg|flac)$/i, project: /\.ccproj$/i };

function mediaList(kind) {
  const re = KINDS[kind] || /./;
  return fs.readdirSync(MEDIA).filter((n) => re.test(n)).map((name) => {
    const p = path.join(MEDIA, name), st = fs.statSync(p);
    return { name, path: p, size: st.size, folder: MEDIA };
  });
}

const api = {
  async run({ id, tool, args }) {
    const j = { lines: [], done: false, result: null };
    const h = B.start(tool, args, (l) => j.lines.push(l));
    j.h = h;
    jobs.set(id, j);
    h.done.then((r) => { j.done = true; j.result = r; setTimeout(() => jobs.delete(id), 60000); });
    return true;
  },
  async poll({ id, off }) {
    const j = jobs.get(id);
    if (!j) return { lines: [], off, done: true, result: { code: -1, stdout: "", stderr: "unknown job" } };
    const lines = j.lines.slice(off);
    return { lines, off: off + lines.length, done: j.done && off + lines.length >= j.lines.length, result: j.result };
  },
  async cancel({ id }) { const j = jobs.get(id); if (j) j.h.cancel(); return true; },
  async readText({ p }) { const t = await B.readText(p); return t === null ? null : { text: t }; },
  async writeText({ p, text }) { return B.writeText(p, text); },
  async writeBase64({ p, b64, append }) { return append ? B.appendBase64(p, b64) : B.writeBase64(p, b64); },
  async readBase64({ p, offset, length }) { const b = await B.readBytes(p, offset, length); return b ? { b64: Buffer.from(b).toString("base64") } : null; },
  async exists({ p }) { return B.exists(p); },
  async stat({ p }) { return B.stat(p); },
  async list({ p }) { return B.list(p); },
  async mkdirs({ p }) { return B.mkdirs(p); },
  async remove({ p, recursive }) { return B.remove(p, recursive); },
  async rename({ a, b }) { return B.rename(a, b); },
  async copy({ a, b }) { return B.copy(a, b); },
  async paths() { return B.paths(); },
  async media({ kind }) { return mediaList(kind); },
  async pick({ kind }) { const env = process.env["CC_PICK_" + String(kind).toUpperCase()]; if (env) return { path: env }; const l = mediaList(kind); return l.length ? { path: l[0].path } : null; },
  async openFile({ p }) { console.log("OPEN FILE", p); globalThis.lastOpened = p; return true; },
  async share({ p }) { console.log("SHARE", p); return true; },
  async openFolder({ p }) { console.log("OPEN FOLDER", p); return true; },
};

http.createServer(async (req, res) => {
  try {
    const url = new URL(req.url, "http://x");
    if (url.pathname === "/dev/file") {
      const p = url.searchParams.get("p");
      if (!fs.existsSync(p)) { res.writeHead(404); return res.end(); }
      res.writeHead(200, { "Content-Type": TYPES[path.extname(p).toLowerCase()] || "application/octet-stream", "Cache-Control": "no-store" });
      return fs.createReadStream(p).pipe(res);
    }
    if (url.pathname === "/dev/last-opened") { res.writeHead(200); return res.end(String(globalThis.lastOpened || "")); }
    if (url.pathname.startsWith("/dev/")) {
      const name = url.pathname.slice(5);
      let body = "";
      for await (const c of req) body += c;
      const out = await api[name](body ? JSON.parse(body) : {});
      res.writeHead(200, { "Content-Type": "application/json" });
      return res.end(JSON.stringify(out ?? null));
    }
    let p = path.join(WEB, decodeURIComponent(url.pathname === "/" ? "/index.html" : url.pathname));
    if (!p.startsWith(WEB) || !fs.existsSync(p) || fs.statSync(p).isDirectory()) { res.writeHead(404); return res.end("not found"); }
    res.writeHead(200, { "Content-Type": TYPES[path.extname(p)] || "application/octet-stream", "Cache-Control": "no-store" });
    fs.createReadStream(p).pipe(res);
  } catch (e) {
    res.writeHead(500); res.end(String(e.stack || e));
  }
}).listen(PORT, () => console.log(`dev server on http://localhost:${PORT}  (media: ${MEDIA}, data: ${ROOT})`));
