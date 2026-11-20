// Audio / subtitle track tool (like MKVToolNix): see every language track of a movie, remove the ones you do not
// need and choose the default one. The new file is made by COPYING the tracks (no re-encoding): fast, same quality.
import * as E from "./engine.js";
import { bridge } from "./bridge.js";
import { h, clear, button, note, Progress, alertBox, confirmBox, toast, sheet } from "./ui.js";

const LANGS = {
  hin: "Hindi", eng: "English", tam: "Tamil", tel: "Telugu", mal: "Malayalam", kan: "Kannada", ben: "Bengali",
  mar: "Marathi", guj: "Gujarati", pan: "Punjabi", urd: "Urdu", ori: "Odia", ory: "Odia", asm: "Assamese", bho: "Bhojpuri",
  jpn: "Japanese", kor: "Korean", chi: "Chinese", zho: "Chinese", spa: "Spanish", fre: "French", fra: "French",
  ger: "German", deu: "German", ita: "Italian", por: "Portuguese", rus: "Russian", ara: "Arabic", tur: "Turkish",
  tha: "Thai", ind: "Indonesian", vie: "Vietnamese", und: "Unknown", "": "Unknown",
};
export const langName = (code) => LANGS[String(code || "").toLowerCase()] || String(code || "Unknown");

// every stream of the file: [{index, type, codec, lang, title, channels, isDefault, typeIndex}]
export async function probeTracks(path) {
  const r = await E.ffrun(["-v", "error", "-show_entries",
    "stream=index,codec_type,codec_name,channels,width,height:stream_tags=language,title:stream_disposition=default,attached_pic",
    "-show_entries", "format=duration,format_name,size", "-of", "json", path], { tool: "ffprobe" });
  let d;
  try { d = JSON.parse(r.stdout || ""); } catch (e) { throw new Error("This file could not be read. " + String(r.stderr || "").slice(-200)); }
  const count = {};
  const tracks = (d.streams || []).map((s) => {
    const type = s.codec_type === "video" && s.disposition && s.disposition.attached_pic ? "cover" : s.codec_type;
    count[type] = (count[type] || 0);
    return {
      index: s.index, type, codec: s.codec_name || "?", lang: ((s.tags || {}).language || "und").toLowerCase(),
      title: (s.tags || {}).title || "", channels: s.channels || 0, w: s.width || 0, h: s.height || 0,
      isDefault: !!(s.disposition && s.disposition.default), typeIndex: count[type]++,
    };
  });
  const f = d.format || {};
  return { tracks, duration: parseFloat(f.duration) || 0, size: +f.size || 0, format: f.format_name || "" };
}

export const isMp4 = (p) => /\.(mp4|m4v|mov)$/i.test(p);
// text subtitles an MP4 can carry
const MP4_SUBS = new Set(["mov_text"]);

// The output name: same name + the kept languages, in the app's output folder. MP4 stays MP4, everything else -> MKV
export function outName(path, outDir, keptAudio) {
  const langs = [...new Set(keptAudio.map((t) => t.lang))].filter((l) => l !== "und").join("-") || "tracks";
  const base = E.stem(path).replace(/[\\/:*?"<>|]+/g, "_").slice(0, 80) || "movie";
  return E.join(outDir, `${base}_${langs}.${isMp4(path) ? "mp4" : "mkv"}`);
}

// FFmpeg arguments: copy the kept streams; the chosen default audio goes FIRST (the editor uses the first audio track)
export function remuxArgs(path, out, tracks, keep, defaultAudio) {
  const kept = tracks.filter((t) => keep.has(t.index));
  const vids = kept.filter((t) => t.type === "video");
  let auds = kept.filter((t) => t.type === "audio");
  const def = auds.find((t) => t.index === defaultAudio) || auds[0];
  if (def) auds = [def, ...auds.filter((t) => t !== def)];
  const mp4 = isMp4(out);
  const subs = kept.filter((t) => t.type === "subtitle" && (!mp4 || MP4_SUBS.has(t.codec)));
  const other = mp4 ? [] : kept.filter((t) => t.type === "attachment" || t.type === "cover");
  const order = [...vids, ...auds, ...subs, ...other];
  const args = ["-nostdin", "-y", "-hide_banner", "-v", "error", "-stats_period", "0.5", "-progress", "pipe:2", "-i", path];
  for (const t of order) args.push("-map", `0:${t.index}`);
  args.push("-map_metadata", "0", "-map_chapters", "0", "-c", "copy");
  auds.forEach((t, i) => args.push(`-disposition:a:${i}`, i === 0 ? "default" : "0"));
  subs.forEach((t, i) => args.push(`-disposition:s:${i}`, "0"));
  if (mp4) args.push("-movflags", "+faststart");
  args.push(out);
  return { args, order, dropped: kept.length - order.length };
}

export async function remux(path, out, tracks, keep, defaultAudio, onProgress = () => {}, job = null, duration = 0) {
  const { args, dropped } = remuxArgs(path, out, tracks, keep, defaultAudio);
  await bridge().mkdirs(E.dirname(out));
  const r = await E.ffrun(args, {
    job, onLog: (line) => {
      const m = /^out_time_(?:us|ms)=(\d+)/.exec(line);
      if (m && duration > 0) onProgress(Math.min(1, +m[1] / 1e6 / duration));
    },
  });
  if (r.code !== 0) {
    try { await bridge().remove(out); } catch (e) { /* ignore */ }
    throw new Error(String(r.stderr || "FFmpeg failed").slice(-400));
  }
  onProgress(1);
  return { out, dropped };
}

const size = (b) => (b > 1e9 ? `${(b / 1e9).toFixed(2)} GB` : `${(b / 1e6).toFixed(0)} MB`);

// The sheet: tick the tracks to keep, choose the default audio, make the new file.
// Resolves with the new file's path when the user taps 'Use the new file in the editor', else null.
export async function openTrackTool(path, outDir) {
  let info;
  try { info = await probeTracks(path); } catch (e) { return alertBox(String(e.message || e)); }
  const auds = info.tracks.filter((t) => t.type === "audio");
  const keep = new Set(info.tracks.filter((t) => t.type !== "data").map((t) => t.index));
  let def = (auds.find((t) => t.isDefault) || auds[0] || {}).index;
  return sheet("Audio language tracks", (body, close) => {
    const list = h("div", { class: "tracks" });
    const summary = h("div", { class: "note" });
    const prog = new Progress();
    const res = h("div");
    const draw = () => {
      clear(list);
      for (const t of info.tracks) {
        if (t.type === "data") continue;
        const locked = t.type === "video";
        const cb = h("input", { type: "checkbox" });
        cb.checked = keep.has(t.index); cb.disabled = locked;
        cb.addEventListener("change", () => { if (cb.checked) keep.add(t.index); else keep.delete(t.index); if (!keep.has(def)) def = (auds.find((a) => keep.has(a.index)) || {}).index; draw(); });
        const what = t.type === "video" ? `Video  ${t.w}x${t.h}  ${t.codec}`
          : t.type === "audio" ? `Audio ${t.typeIndex + 1}:  ${langName(t.lang)}  (${t.lang})  ${t.codec}${t.channels ? `  ${t.channels === 6 ? "5.1" : t.channels === 8 ? "7.1" : t.channels + " ch"}` : ""}`
            : t.type === "subtitle" ? `Subtitle:  ${langName(t.lang)}  ${t.codec}`
              : t.type === "cover" ? "Cover picture" : `${t.type}  ${t.codec}`;
        const rd = t.type === "audio" ? h("label", { class: "chk small" }, (() => {
          const r = h("input", { type: "radio", name: "defaud" });
          r.checked = t.index === def; r.disabled = !keep.has(t.index);
          r.addEventListener("change", () => { def = t.index; draw(); });
          return r;
        })(), " default") : null;
        list.append(h("div", { class: "track" + (keep.has(t.index) ? "" : " off") },
          h("label", { class: "chk" }, cb, " ", h("span", {}, what)), t.title ? h("div", { class: "note" }, t.title) : null, rd));
      }
      const ka = auds.filter((a) => keep.has(a.index));
      summary.textContent = `${ka.length} of ${auds.length} audio track(s) kept` + (ka.length ? `; default: ${langName((auds.find((a) => a.index === def) || ka[0]).lang)}` : " - the new video will have NO sound");
    };
    const only = (lang) => { for (const a of auds) { if (a.lang === lang) keep.add(a.index); else keep.delete(a.index); } def = (auds.find((a) => a.lang === lang) || {}).index; draw(); };
    const langs = [...new Set(auds.map((a) => a.lang))];
    let job = null;
    const go = button("MAKE NEW FILE WITH THESE TRACKS", async () => {
      const ka = auds.filter((a) => keep.has(a.index));
      if (!ka.length && auds.length && !(await confirmBox("No audio track is ticked: the new video will be silent. Continue?"))) return;
      const out = outName(path, outDir, ka.length ? ka : []);
      go.disabled = true; stop.disabled = false; clear(res);
      job = { cancelled: false };
      try {
        const r = await remux(path, out, info.tracks, keep, def, (f) => prog.set(f, `Copying tracks: ${Math.round(f * 100)}%`), job, info.duration);
        prog.set(1, "Done");
        res.append(note(`New file: ${out}` + (r.dropped ? `  (${r.dropped} subtitle / extra track(s) an MP4 cannot hold were left out)` : "")),
          button("Use the new file in the editor", () => close(out), "primary wide"));
        toast("New file made");
      } catch (e) {
        prog.set(0, job && job.cancelled ? "Stopped" : "Failed");
        if (!(job && job.cancelled)) alertBox("Could not make the file:\n" + (e.message || e));
      }
      go.disabled = false; stop.disabled = true; job = null;
    }, "primary big wide");
    const stop = button("Stop", () => { if (job) { job.cancelled = true; if (job.current) job.current.cancel(); } }, "danger");
    stop.disabled = true;
    body.append(note(`${E.basename(path)}  |  ${size(info.size)}  |  ${auds.length} audio track(s)`),
      langs.length > 1 ? h("div", { class: "btnrow" }, ...langs.map((l) => button(`Only ${langName(l)}`, () => only(l), "small quiet"))) : null,
      list, summary,
      note("Untick the languages you do not want. The tracks are copied, not re-made: it is fast and the quality stays the same. The default audio becomes the first track (the editor uses it). Your original file is not changed."),
      go, stop, prog.el, res);
    draw();
  });
}
