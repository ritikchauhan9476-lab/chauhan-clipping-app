// One small API between the app and the phone (or the test machine).
// - In the Android app: window.AndroidBridge (Kotlin, see MainActivity.kt / Bridge.kt).
// - In a desktop browser for testing: the dev server (tests/devserver.mjs) under /dev/.
// - In Node tests: setBridge(nodeBridge) from tests/nodebridge.mjs.

let impl = null;
let seq = 0;
const pending = new Map();      // id -> {resolve, onLog}

export function setBridge(b) { impl = b; }
export function bridge() {
  if (!impl) impl = typeof window !== "undefined" && window.AndroidBridge ? androidBridge() : devBridge();
  return impl;
}

function b64ToBytes(b64) {
  const bin = atob(b64);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

export function bytesToB64(bytes) {
  let s = "";
  const step = 0x8000;
  for (let i = 0; i < bytes.length; i += step) s += String.fromCharCode.apply(null, bytes.subarray(i, i + step));
  return btoa(s);
}

// ------------------------------------------------------------------ Android
function androidBridge() {
  const A = window.AndroidBridge;
  window.__bridgeCb = (id, json) => {
    const p = pending.get(id);
    if (!p) return;
    pending.delete(id);
    let v = null;
    try { v = JSON.parse(json); } catch (e) { v = null; }
    p.resolve(v);
  };
  window.__bridgeLog = (id, line) => {
    const p = pending.get(id);
    if (p && p.onLog) {
      try { p.onLog(line); } catch (e) { /* a bad log handler must not stop the job */ }
    }
  };
  const call = (fn, ...args) => {
    const r = A[fn](...args);
    if (r === undefined || r === null || r === "") return null;
    try { return JSON.parse(r); } catch (e) { return r; }
  };
  const asyncCall = (fn, onLog, ...args) => {
    const id = "j" + (++seq) + "_" + Date.now();
    const done = new Promise((resolve) => pending.set(id, { resolve, onLog }));
    A[fn](id, ...args);
    return { id, done };
  };
  return {
    kind: "android",
    start(tool, args, onLog) {
      const { id, done } = asyncCall("run", onLog, tool, JSON.stringify(args));
      return { id, done: done.then((v) => v || { code: -1, stdout: "", stderr: "bridge error" }), cancel: () => A.cancel(id) };
    },
    async readText(p) { return call("readText", p); },
    async writeText(p, t) { return call("writeText", p, t); },
    async writeBase64(p, b64) { return call("writeBase64", p, b64, false); },
    async appendBase64(p, b64) { return call("writeBase64", p, b64, true); },
    async readBytes(p, offset = 0, length = -1) {
      // read in 3 MB slices: very long strings through the Android bridge are slow and can run out of memory
      if (length < 0) { const st = call("stat", p); if (!st) return null; length = Math.max(0, st.size - offset); }
      const CH = 3 * 1024 * 1024;
      const out = new Uint8Array(length);
      let pos = 0;
      while (pos < length) {
        const n = Math.min(CH, length - pos);
        const b64 = A.readBase64(p, offset + pos, n);
        if (!b64) break;
        const bytes = b64ToBytes(b64);
        out.set(bytes, pos);
        pos += bytes.length;
        if (bytes.length < n) break;
      }
      return out.subarray(0, pos);
    },
    async exists(p) { return call("exists", p) === true; },
    async stat(p) { return call("stat", p); },
    async list(p) { return call("list", p) || []; },
    async mkdirs(p) { return call("mkdirs", p); },
    async remove(p, recursive = false) { return call("remove", p, recursive); },
    async rename(a, b) { return call("rename", a, b); },
    async copy(a, b) { const { done } = asyncCall("copy", null, a, b); return done; },
    async paths() { return call("paths"); },
    async media(kind) { const { done } = asyncCall("media", null, kind); return (await done) || []; },
    async pick(kind) { const { done } = asyncCall("pick", null, kind); const r = await done; return r && r.path ? r : null; },
    fileUrl(p) { return "https://appassets.androidplatform.net/file?p=" + encodeURIComponent(p) + "&t=" + Date.now(); },
    async openFile(p, mime) { return call("openFile", p, mime || ""); },
    async share(p, mime) { return call("share", p, mime || ""); },
    async openFolder(p) { return call("openFolder", p); },
    async scanFile(p) { return call("scanFile", p); },
    async keepAwake(on, title, text) { return call("keepAwake", !!on, title || "", text || ""); },
    async toast(m) { return call("toast", String(m)); },
    async appInfo() { return call("appInfo"); },
    async storageAccess() { return call("storageAccess"); },
    async askStorage() { const { done } = asyncCall("askStorage", null); return done; },
  };
}

// ------------------------------------------------------------------ dev server (desktop browser tests)
function devBridge() {
  const post = async (path, body) => {
    const r = await fetch("/dev/" + path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });
    const t = await r.text();
    try { return JSON.parse(t); } catch (e) { return t; }
  };
  return {
    kind: "dev",
    start(tool, args, onLog) {
      const id = "d" + (++seq);
      let stopped = false;
      const done = (async () => {
        await post("run", { id, tool, args });
        let res = null, off = 0;
        while (!res) {
          const st = await post("poll", { id, off });
          for (const line of st.lines || []) { try { onLog && onLog(line); } catch (e) { /* ignore */ } }
          off = st.off;
          if (st.done) res = st.result;
          else await new Promise((r) => setTimeout(r, stopped ? 50 : 150));
        }
        return res;
      })();
      return { id, done, cancel: () => { stopped = true; post("cancel", { id }); } };
    },
    async readText(p) { const r = await post("readText", { p }); return r === null ? null : r.text; },
    async writeText(p, text) { return post("writeText", { p, text }); },
    async writeBase64(p, b64) { return post("writeBase64", { p, b64 }); },
    async appendBase64(p, b64) { return post("writeBase64", { p, b64, append: true }); },
    async readBytes(p, offset = 0, length = -1) {
      const r = await post("readBase64", { p, offset, length });
      return r && r.b64 !== undefined ? b64ToBytes(r.b64) : null;
    },
    async exists(p) { return (await post("exists", { p })) === true; },
    async stat(p) { return post("stat", { p }); },
    async list(p) { return (await post("list", { p })) || []; },
    async mkdirs(p) { return post("mkdirs", { p }); },
    async remove(p, recursive = false) { return post("remove", { p, recursive }); },
    async rename(a, b) { return post("rename", { a, b }); },
    async copy(a, b) { return post("copy", { a, b }); },
    async paths() { return post("paths", {}); },
    async media(kind) { return (await post("media", { kind })) || []; },
    async pick(kind) { const r = await post("pick", { kind }); return r && r.path ? r : null; },
    fileUrl(p) { return "/dev/file?p=" + encodeURIComponent(p) + "&t=" + Date.now(); },
    async openFile(p) { return post("openFile", { p }); },
    async share(p) { return post("share", { p }); },
    async openFolder(p) { return post("openFolder", { p }); },
    async scanFile() { return true; },
    async keepAwake() { return true; },
    async toast(m) { console.log("TOAST:", m); return true; },
    async appInfo() { return { version: "dev", abi: "dev" }; },
    async storageAccess() { return true; },
    async askStorage() { return true; },
  };
}
