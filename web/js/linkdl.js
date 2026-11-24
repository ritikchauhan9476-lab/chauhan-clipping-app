// Download a video from a YouTube (and many other sites) link on the phone: the app finds the stream addresses
// (NewPipe Extractor, in the Android part), downloads picture + sound in pieces and joins them (copied, no re-making).
import * as E from "./engine.js";
import { bridge } from "./bridge.js";
import { h, clear, button, note, Progress, alertBox, sheet, toast, textField, selectField } from "./ui.js";

export const QUALITIES = { "Best up to 1080p": 1080, "Best up to 720p": 720, "Best up to 480p": 480, "Best up to 4K": 2160 };
const safe = (t) => String(t || "video").replace(/[\\/:*?"<>|#\n\r]+/g, " ").replace(/\s+/g, " ").trim().slice(0, 80) || "video";

// pick the streams: MP4 (H.264) + M4A when they exist (so the joined file is a normal MP4), else the best of anything
export function chooseStreams(info, maxH) {
  const vids = (info.video || []).filter((v) => v.height && v.height <= maxH);
  const score = (v) => v.height * 10 + (v.fps || 30) / 10 + (/mp4|avc/i.test(v.ext + v.codec + v.mime) ? 5 : 0);
  const only = vids.filter((v) => v.videoOnly).sort((a, b) => score(b) - score(a));
  const prog = vids.filter((v) => !v.videoOnly).sort((a, b) => score(b) - score(a));
  const auds = [...(info.audio || [])].sort((a, b) => {
    const pa = /ORIGINAL/i.test(a.type) ? 1 : 0, pb = /ORIGINAL/i.test(b.type) ? 1 : 0;
    return pb - pa || (/m4a|mp4|aac/i.test(b.ext + b.codec) ? 1 : 0) - (/m4a|mp4|aac/i.test(a.ext + a.codec) ? 1 : 0) || (b.bitrate || 0) - (a.bitrate || 0);
  });
  if (only.length && auds.length && (!prog.length || only[0].height > prog[0].height)) return { video: only[0], audio: auds[0] };
  if (prog.length) return { video: prog[0], audio: null };
  if (only.length) return { video: only[0], audio: auds[0] || null };
  return null;
}

export async function downloadLink(url, outDir, maxH, onProgress, ctl = {}) {
  onProgress && onProgress(0, "Reading the link ...");
  const r = await bridge().linkInfo(url);
  if (!r || !r.ok) throw new Error("This link could not be read: " + ((r && r.error) || "unknown"));
  const info = r.info;
  const pick = chooseStreams(info, maxH);
  if (!pick) throw new Error("No downloadable video was found for this link.");
  await bridge().mkdirs(outDir);
  const tmp = await bridge().paths();
  const vPath = E.join(tmp.cache, `dl_v_${Date.now()}.${pick.video.ext || "mp4"}`);
  const aPath = pick.audio ? E.join(tmp.cache, `dl_a_${Date.now()}.${pick.audio.ext || "m4a"}`) : null;
  const mp4ok = /mp4|avc|m4v/i.test(pick.video.ext + pick.video.codec) && (!pick.audio || /m4a|mp4|aac/i.test(pick.audio.ext + pick.audio.codec));
  const out = E.join(outDir, `${safe(info.title)} ${pick.video.height}p.${mp4ok ? "mp4" : "mkv"}`);
  const get = async (u, p, label, from, share) => {
    const d = bridge().download(u, p, {}, (got, total) => {
      if (onProgress) onProgress(from + (total > 0 ? (got / total) * share : 0), `${label}: ${(got / 1e6).toFixed(0)}${total > 0 ? " / " + (total / 1e6).toFixed(0) : ""} MB`);
    });
    ctl.cancel = d.cancel;
    const res = await d.done;
    if (!res.ok) throw new Error(`${label} download failed: ${res.error}`);
  };
  try {
    await get(pick.video.url, vPath, "Picture", 0, pick.audio ? 0.85 : 0.97);
    if (ctl.stopped) throw new Error("stopped");
    if (aPath) await get(pick.audio.url, aPath, "Sound", 0.85, 0.12);
    if (ctl.stopped) throw new Error("stopped");
    onProgress && onProgress(0.98, "Joining picture and sound ...");
    const args = ["-nostdin", "-y", "-v", "error", "-i", vPath];
    if (aPath) args.push("-i", aPath, "-map", "0:v:0", "-map", "1:a:0");
    args.push("-c", "copy");
    if (out.endsWith(".mp4")) args.push("-movflags", "+faststart");
    args.push(out);
    const m = await E.ffrun(args);
    if (m.code !== 0) throw new Error("Joining failed: " + String(m.stderr || "").slice(-300));
  } finally {
    await bridge().remove(vPath);
    if (aPath) await bridge().remove(aPath);
  }
  await bridge().scanFile(out);
  onProgress && onProgress(1, "Downloaded");
  return { path: out, title: info.title, height: pick.video.height, duration: info.duration };
}

// the sheet: paste a link, choose the quality, download. Resolves with the file path (or null).
export async function linkSheet(app) {
  return sheet("Download from a link", (body, close) => {
    const link = textField("YouTube / Instagram / Facebook / X ... link", "", null, { placeholder: "https://www.youtube.com/watch?v=..." });
    let q = "Best up to 1080p";
    const prog = new Progress();
    const res = h("div");
    const ctl = {};
    if (navigator.clipboard && navigator.clipboard.readText) navigator.clipboard.readText().then((t) => { if (/^https?:\/\/\S+$/.test(String(t).trim()) && !link.input.value) link.input.value = String(t).trim(); }).catch(() => {});
    const go = button("DOWNLOAD", async () => {
      const url = String(link.input.value || "").trim();
      if (!/^https?:\/\/\S+$/.test(url)) return alertBox("Please paste a full link (starting with https://).");
      go.disabled = true; stop.disabled = false; ctl.stopped = false; clear(res);
      try {
        const d = await downloadLink(url, E.join(app.paths.out, "Downloads"), QUALITIES[q], (f, t) => prog.set(f, t), ctl);
        res.append(note(`Saved: ${d.path}`), button("Use this video", () => close(d.path), "primary wide"));
        toast("Downloaded");
      } catch (e) {
        prog.set(0, ctl.stopped ? "Stopped" : "Failed");
        if (!ctl.stopped) alertBox(String(e.message || e) + "\n\nIf YouTube says 'sign in to confirm you are not a bot', try again later or on Wi-Fi / another network.");
      }
      go.disabled = false; stop.disabled = true;
    }, "primary big wide");
    const stop = button("Stop", () => { ctl.stopped = true; if (ctl.cancel) ctl.cancel(); }, "danger");
    stop.disabled = true;
    body.append(link.el, selectField("Quality", Object.keys(QUALITIES), q, (v) => { q = v; }).el, go, stop, prog.el, res,
      note("The video is saved in Movies/ChauhanClipping/Downloads. Download only videos you are allowed to use."));
  });
}
