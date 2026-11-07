// The bridge API implemented with Node + the machine's own ffmpeg / ffprobe (tests and the dev server).
import { spawn } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

export function nodeBridge({ root = "/tmp/cc-test", ffmpeg = "ffmpeg", ffprobe = "ffprobe" } = {}) {
  const dirs = { out: path.join(root, "out"), projects: path.join(root, "projects"), cache: path.join(root, "cache") };
  for (const d of Object.values(dirs)) fs.mkdirSync(d, { recursive: true });
  const jobs = new Map();
  let seq = 0;
  return {
    kind: "node",
    jobs,
    start(tool, args, onLog) {
      const id = "n" + ++seq;
      const p = spawn(tool === "ffprobe" ? ffprobe : ffmpeg, args, { stdio: ["ignore", "pipe", "pipe"] });
      let out = "", err = "", partial = "";
      p.stdout.on("data", (d) => { out += d.toString(); });
      p.stderr.on("data", (d) => {
        const s = d.toString();
        err += s;
        if (err.length > 4e6) err = err.slice(-2e6);
        partial += s;
        const lines = partial.split(/\r?\n|\r/);
        partial = lines.pop();
        for (const l of lines) if (onLog) onLog(l);
      });
      const done = new Promise((resolve) => p.on("close", (code) => {
        if (partial && onLog) onLog(partial);
        jobs.delete(id);
        resolve({ code: code ?? -1, stdout: out, stderr: err });
      }));
      jobs.set(id, p);
      return { id, done, cancel: () => { try { p.kill("SIGKILL"); } catch (e) { /* already gone */ } } };
    },
    async readText(p) { try { return fs.readFileSync(p, "utf8"); } catch (e) { return null; } },
    async writeText(p, t) { fs.mkdirSync(path.dirname(p), { recursive: true }); fs.writeFileSync(p, t); return true; },
    async writeBase64(p, b64) { fs.mkdirSync(path.dirname(p), { recursive: true }); fs.writeFileSync(p, Buffer.from(b64, "base64")); return true; },
    async appendBase64(p, b64) { fs.appendFileSync(p, Buffer.from(b64, "base64")); return true; },
    async readBytes(p, offset = 0, length = -1) {
      try {
        const buf = fs.readFileSync(p);
        const end = length < 0 ? buf.length : Math.min(buf.length, offset + length);
        return new Uint8Array(buf.subarray(offset, end));
      } catch (e) { return null; }
    },
    async exists(p) { return fs.existsSync(p); },
    async stat(p) { try { const s = fs.statSync(p); return { size: s.size, mtime: s.mtimeMs, isDir: s.isDirectory() }; } catch (e) { return null; } },
    async list(p) {
      try {
        return fs.readdirSync(p).map((name) => {
          const s = fs.statSync(path.join(p, name));
          return { name, path: path.join(p, name), isDir: s.isDirectory(), size: s.size, mtime: s.mtimeMs };
        });
      } catch (e) { return []; }
    },
    async mkdirs(p) { fs.mkdirSync(p, { recursive: true }); return true; },
    async remove(p, recursive = false) { try { fs.rmSync(p, { recursive, force: true }); } catch (e) { /* ignore */ } return true; },
    async rename(a, b) { try { fs.renameSync(a, b); return true; } catch (e) { return false; } },
    async copy(a, b) { fs.copyFileSync(a, b); return { ok: true }; },
    async paths() { return { ...dirs }; },
    async media() { return []; },
    async pick() { return null; },
    fileUrl(p) { return "file://" + p; },
    async openFile() { return true; },
    async share() { return true; },
    async openFolder() { return true; },
    async scanFile() { return true; },
    async keepAwake() { return true; },
    async toast() { return true; },
    async appInfo() { return { version: "node" }; },
    async storageAccess() { return true; },
    async askStorage() { return true; },
  };
}
