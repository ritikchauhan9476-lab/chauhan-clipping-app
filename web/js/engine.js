// The export engine (port of the desktop engine.py): settings, the single FFmpeg command for a clip, encoder
// options, silence detection, and the runners that export parts. The FFmpeg command is the same one the
// desktop software builds, so the result looks the same.
import * as CL from "./colour.js";
import { bridge } from "./bridge.js";

export const VIDEO_EXT = [".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm", ".m4v", ".ts", ".3gp"];
export const IMAGE_EXT = [".png", ".jpg", ".jpeg", ".webp", ".bmp"];
export const OVERLAY_VIDEO_EXT = [...VIDEO_EXT, ".gif"];
export const AUDIO_EXT = [".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".wma", ".opus", ".amr"];

export const FOCUS = ["Funny", "Emotional", "Funny + Emotional"];
export const LANGS = ["hi", "en", "auto"];
export const WHISPER = ["tiny", "base", "small"];
export const ASPECTS = ["Original", "1:1", "4:3", "3:4", "3:2", "2:3", "16:9", "9:16", "4:5", "5:4", "21:9"];
export const ROTATIONS = ["No rotation", "90° right", "180°", "90° left"];
export const FIT_MODES = ["Crop (fill frame)", "Blur background", "Black bars", "Solid colour"];
export const RES = ["Original", "480p", "720p", "1080p", "1440p", "2160p (4K)"];
export const FPS = ["Original", "24", "25", "30", "50", "60"];
export const CODECS = ["H.264 (phone hardware - fast)", "H.265 (phone hardware)", "H.264 (CPU)"];
export const ABR = ["96k", "128k", "192k", "256k", "320k"];
export const BITRATES = ["2000", "3000", "4000", "6000", "8000", "12000", "16000", "20000", "25000", "30000",
  "40000", "50000", "60000", "80000", "100000", "150000"];
export const MAX_BITRATE = 150000;
export const RATE_MODES = ["Exact bitrate (use my number)", "Quality (bitrate is only a limit)"];
export const X264_PRESETS = ["ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow"];
export const QUALITY = {
  High: { crf: 18, x264: "slow" },
  Balanced: { crf: 21, x264: "medium" },
  "Small file": { crf: 24, x264: "fast" },
  "Fast (phone)": { crf: 22, x264: "veryfast" },
};
export const EXPORT_PRESETS = {
  "CapCut max (1080p, 60 fps, 50 Mbps)": { resolution: "1080p", fps: "60", quality: "High", rate_mode: RATE_MODES[0], bitrate: 50000, audio_bitrate: "320k" },
  "Reels / Shorts - best quality (1080p, 12 Mbps)": { resolution: "1080p", fps: "Original", quality: "High", rate_mode: RATE_MODES[0], bitrate: 12000, audio_bitrate: "192k" },
  "YouTube 1080p (16 Mbps)": { resolution: "1080p", fps: "Original", quality: "High", rate_mode: RATE_MODES[0], bitrate: 16000, audio_bitrate: "192k" },
  "Small file for WhatsApp (720p, 3 Mbps)": { resolution: "720p", fps: "Original", quality: "Balanced", rate_mode: RATE_MODES[0], bitrate: 3000, audio_bitrate: "128k" },
  "Fast phone export (1080p, 10 Mbps)": { resolution: "1080p", fps: "Original", quality: "Fast (phone)", rate_mode: RATE_MODES[0], bitrate: 10000, audio_bitrate: "192k", codec: CODECS[2], x264_preset: "ultrafast" },
};
export const MUSIC_MODES = ["Mix with original audio", "Replace original audio"];
export const BG_TYPES = ["Color", "Image", "Video"];
export const POSITIONS = ["Top-Left", "Top-Center", "Top-Right", "Middle-Left", "Center", "Middle-Right",
  "Bottom-Left", "Bottom-Center", "Bottom-Right", "Custom"];

export const OVERLAY_DEFAULT = {
  path: "", pos: "Top-Right", x: 70, y: 5, scale: 20, opacity: 100, start: 0, end: 0, chroma: false, loop: true,
  layer: 1, src_offset: 0, key_color: "#00FF00", key_sim: 0.3, key_blend: 0.1, key_spill: true,
};
export const TEXT_DEFAULT = {
  text: "Your text", font: "Noto Sans", size: 6.0, color: "#FFFFFF", opacity: 100, outline: 2,
  outline_color: "#000000", shadow: false, box: false, box_color: "#000000", box_opacity: 50,
  pos: "Bottom-Center", x: 50, y: 80, start: 0, end: 0, layer: 1, hcenter: false, vcenter: false, bold: true,
  // CapCut-style text options
  italic: false, underline: false, case: "As typed", align: "Center", line_spacing: 0, shadow_color: "#000000",
  shadow_opacity: 60, shadow_dist: 3, shadow_angle: 45, glow: false, glow_color: "#00E5FF", glow_size: 8, box_pad: 30,
  anim_in: "None", anim_in_dur: 0.5, anim_out: "None", anim_out_dur: 0.5, anim_loop: "None",
};
export const TEXT_CASES = ["As typed", "UPPERCASE", "lowercase", "Title Case"];
export const TEXT_ALIGNS = ["Left", "Center", "Right"];
export const ANIM_IN = ["None", "Fade", "Slide up", "Slide down", "Slide left", "Slide right", "Pop", "Typewriter"];
export const ANIM_OUT = ["None", "Fade", "Slide up", "Slide down", "Slide left", "Slide right", "Pop"];
export const ANIM_LOOP = ["None", "Pulse", "Bounce", "Shake", "Blink"];

// coloured words inside a text: "Hello {c=#FF0000}world{/c}"
export const COLOR_TAG = /\{c=#?([0-9A-Fa-f]{6})\}([\s\S]*?)\{\/c\}/gi;
export const stripColors = (t) => String(t).replace(COLOR_TAG, (m, c, w) => w);
export function applyCase(text, cs) {
  if (cs === "UPPERCASE") return text.toUpperCase();
  if (cs === "lowercase") return text.toLowerCase();
  if (cs === "Title Case") return text.replace(/(^|[\s}])(\p{L})/gu, (m, a, b) => a + b.toUpperCase());
  return text;
}
// text -> [[[run, "#RRGGBB"], ...] per line]
export function colorLines(text, base) {
  const runs = [];
  let pos = 0;
  for (const m of text.matchAll(COLOR_TAG)) {
    if (m.index > pos) runs.push([text.slice(pos, m.index), base]);
    runs.push([m[2], "#" + m[1].toUpperCase()]);
    pos = m.index + m[0].length;
  }
  if (pos < text.length) runs.push([text.slice(pos), base]);
  const lines = [[]];
  for (const [t, c] of runs) t.split("\n").forEach((chunk, i) => { if (i) lines.push([]); if (chunk) lines[lines.length - 1].push([chunk, c]); });
  return lines;
}
export const AUDIO_DEFAULT = { path: "", layer: 1, start: 0, end: 0, src_offset: 0, volume: 100, loop: true };

export const DEFAULTS = {
  focus: "Funny + Emotional", min_dur: 30, max_dur: 60, min_score: 40, max_per_chunk: 3, max_total: 0,
  language: "hi", whisper_model: "base",
  part_len: 60, trim_start: 0, trim_end: 0, min_last: 5,
  brightness: 0, contrast: 1, saturation: 1, gamma: 1, sharpness: 0, hue: 0, warmth: 0, auto_crop: true,
  src_aspect: "Original", aspect: "Original", fit_mode: "Blur background", resolution: "1080p", fps: "60",
  zoom: 1.0, crop_x: 50, crop_y: 50,
  // pro editing: rotate / flip / free crop / speed / fades / effects
  rotate: "No rotation", flip_h: false, flip_v: false, crop_l: 0, crop_r: 0, crop_t: 0, crop_b: 0,
  speed: 1.0, vfade_in: 0, vfade_out: 0, fx_bw: false, fx_sepia: false, fx_blur: 0, fx_denoise: false, fx_stab: false,
  bg_color: "#1E1E1E", blur_amount: 25, fit_scale: 100, fit_y: 50,
  ...CL.NEW_DEFAULTS,
  chroma_on: false, chroma_color: "#00FF00", chroma_sim: 0.15, chroma_blend: 0.1, chroma_spill: true,
  chroma_bg_type: "Color", chroma_bg_color: "#1E1E1E", chroma_bg_file: "",
  overlays: [], texts: [], audios: [],
  music_mode: "Mix with original audio", orig_volume: 100,
  codec: CODECS[2], x264_preset: "veryfast", quality: "High", bitrate: 50000, audio_bitrate: "320k", rate_mode: RATE_MODES[0],
  fade_sec: 0.15,
};
const CHOICES = {
  rotate: ROTATIONS, src_aspect: ASPECTS, aspect: ASPECTS, fit_mode: FIT_MODES, resolution: RES, fps: FPS, codec: CODECS, x264_preset: X264_PRESETS,
  rate_mode: RATE_MODES, audio_bitrate: ABR, focus: FOCUS, language: LANGS, whisper_model: WHISPER,
  music_mode: MUSIC_MODES, chroma_bg_type: BG_TYPES, quality: Object.keys(QUALITY),
};
// desktop codec names -> the phone's
const CODEC_ALIAS = {
  "H.264 (NVIDIA GPU - fast)": CODECS[0], "H.265 (NVIDIA GPU)": CODECS[1], "H.265 (CPU - slow)": CODECS[1],
};

export const clone = (x) => JSON.parse(JSON.stringify(x));

export function sanitize(src) {
  const s = { ...(src || {}) };
  if (s.codec in CODEC_ALIAS) s.codec = CODEC_ALIAS[s.codec];
  if (s.whisper_model === "medium") s.whisper_model = "small";
  for (const [k, d] of Object.entries(DEFAULTS)) {
    if (!(k in s) || s[k] === undefined || s[k] === null) { s[k] = clone(d); continue; }
    if (typeof d === "boolean") s[k] = !!s[k];
    else if (typeof d === "number") { const v = parseFloat(s[k]); s[k] = Number.isFinite(v) ? v : d; }
    else if (Array.isArray(d)) { if (!Array.isArray(s[k])) s[k] = []; }
    else s[k] = String(s[k]);
  }
  for (const [k, vals] of Object.entries(CHOICES)) if (!vals.includes(s[k])) s[k] = DEFAULTS[k];
  s.bitrate = Math.round(Math.min(MAX_BITRATE, Math.max(500, s.bitrate)));
  s.blur_amount = Math.round(Math.min(60, Math.max(5, s.blur_amount)));
  s.fit_scale = Math.min(100, Math.max(30, s.fit_scale));
  s.fit_y = Math.min(100, Math.max(0, s.fit_y));
  CL.clamp(s);
  s.audios = s.audios.filter((a) => a && typeof a === "object").map((a) => ({ ...AUDIO_DEFAULT, ...a }));
  s.overlays = s.overlays.filter((a) => a && typeof a === "object").map((a) => ({ ...OVERLAY_DEFAULT, ...a }));
  s.texts = s.texts.filter((a) => a && typeof a === "object").map((a) => ({ ...TEXT_DEFAULT, ...a }));
  s.speed = Math.min(4, Math.max(0.25, s.speed || 1));
  return s;
}

// ------------------------------------------------------------------ pro editing helpers
// free crop: % cut from each side -> [x, y, w, h] (even numbers)
export function freeCropBox(s, sw, sh) {
  const c = (k) => Math.max(0, Math.min(45, +s[k] || 0)) / 100;
  const l = c("crop_l"), r = c("crop_r"), t = c("crop_t"), b = c("crop_b");
  const w = Math.max(16, Math.floor((sw * (1 - l - r)) / 2) * 2), h = Math.max(16, Math.floor((sh * (1 - t - b)) / 2) * 2);
  return [Math.floor((sw * l) / 2) * 2, Math.floor((sh * t) / 2) * 2, w, h];
}
// rotate, flip, free crop, stabilise, denoise of the imported movie -> [filters, w, h]
export function geometryFilters(s, sw, sh) {
  const f = [];
  if (s.fx_stab) f.push("deshake=rx=32:ry=32:edge=mirror");
  if (s.fx_denoise) f.push("hqdn3d=3:3:6:6");
  const rot = String(s.rotate || "");
  if (rot.startsWith("90° right")) { f.push("transpose=1"); [sw, sh] = [sh, sw]; }
  else if (rot.startsWith("90° left")) { f.push("transpose=2"); [sw, sh] = [sh, sw]; }
  else if (rot.startsWith("180")) f.push("hflip,vflip");
  if (s.flip_h) f.push("hflip");
  if (s.flip_v) f.push("vflip");
  const [x, y, w, h] = freeCropBox(s, sw, sh);
  if (w !== sw || h !== sh) { f.push(`crop=${w}:${h}:${x}:${y}`); sw = w; sh = h; }
  return [f, sw, sh];
}
export function effectFilters(s) {
  const f = [];
  if (s.fx_bw) f.push("hue=s=0");
  if (s.fx_sepia) f.push("colorchannelmixer=.393:.769:.189:0:.349:.686:.168:0:.272:.534:.131");
  if (+s.fx_blur > 0) f.push(`gblur=sigma=${(+s.fx_blur * 0.4).toFixed(2)}`);
  return f;
}
// atempo takes 0.5 - 2.0 per step
export function atempoChain(speed) {
  const out = [];
  let sp = +speed;
  while (sp > 2) { out.push("atempo=2.0"); sp /= 2; }
  while (sp < 0.5) { out.push("atempo=0.5"); sp /= 0.5; }
  out.push(`atempo=${sp.toFixed(4)}`);
  return out.join(",");
}

// ------------------------------------------------------------------ small path helpers (Android / Linux paths)
export const basename = (p) => String(p || "").replace(/\\/g, "/").split("/").pop();
export const dirname = (p) => { const s = String(p || "").replace(/\\/g, "/"); const i = s.lastIndexOf("/"); return i > 0 ? s.slice(0, i) : "/"; };
export const join = (...a) => a.filter((x) => x !== "" && x != null).join("/").replace(/\/+/g, "/");
export const ext = (p) => { const b = basename(p); const i = b.lastIndexOf("."); return i > 0 ? b.slice(i).toLowerCase() : ""; };
export const stem = (p) => { const b = basename(p); const i = b.lastIndexOf("."); return i > 0 ? b.slice(0, i) : b; };
export const safeName = (movie) => stem(movie).replace(/[^\w\-]+/g, "_").slice(0, 50);
export const fileBase = (movie) => [...stem(movie)].map((ch) => (/[A-Za-z0-9\-_]/.test(ch) ? ch : "_")).join("").slice(0, 40);
export const isVideo = (p) => VIDEO_EXT.includes(ext(p));
export const isOverlayVideo = (p) => OVERLAY_VIDEO_EXT.includes(ext(p));
export const pad2 = (n) => String(Math.floor(n)).padStart(2, "0");

export function tstr(t) {
  t = Math.max(0, Number(t) || 0);
  const m = Math.floor(t / 60), s = t - m * 60;
  return `${pad2(m)}:${s.toFixed(1).padStart(4, "0")}`;
}
export function mmss(t) {
  t = Math.floor(Math.max(0, t));
  const h = Math.floor(t / 3600), m = Math.floor((t % 3600) / 60), s = t % 60;
  return h ? `${h}:${pad2(m)}:${pad2(s)}` : `${pad2(m)}:${pad2(s)}`;
}

export const ev = (x) => Math.max(2, Math.round(x / 2) * 2);
export const evUp = (x) => Math.max(2, Math.ceil(x / 2) * 2);
export function hex0x(c, def = "FFFFFF") {
  c = String(c || "").trim().replace(/^#/, "");
  return "0x" + (/^[0-9a-fA-F]{6}$/.test(c) ? c.toUpperCase() : def);
}

// ------------------------------------------------------------------ running FFmpeg through the bridge
export async function ffrun(args, { tool = "ffmpeg", onLog = null, job = null } = {}) {
  const h = bridge().start(tool, args, onLog);
  if (job) job.current = h;
  const r = await h.done;
  if (job && job.current === h) job.current = null;
  return r || { code: -1, stdout: "", stderr: "" };
}

const infoCache = new Map();
export async function probeInfo(path) {
  if (infoCache.has(path)) return infoCache.get(path);
  const r = await ffrun(["-v", "error", "-show_entries", "stream=codec_type,width,height,r_frame_rate:stream_tags=rotate:stream_side_data=rotation",
    "-show_entries", "format=duration", "-of", "json", path], { tool: "ffprobe" });
  let d;
  try { d = JSON.parse(r.stdout || ""); } catch (e) { throw new Error("This file could not be read. " + String(r.stderr || "").slice(-200)); }
  const st = d.streams || [];
  const v = st.find((x) => x.codec_type === "video" && x.width);
  if (!v) throw new Error("No video stream found in this file.");
  let fps = v.r_frame_rate || "25/1";
  const [n, dn] = String(fps).split("/").map(Number);
  if (!(n / dn > 0 && n / dn <= 240)) fps = "25/1";
  let w = +v.width, h = +v.height;
  // phone videos are often stored sideways with a rotation flag; FFmpeg turns them upright automatically
  let rot = 0;
  if (v.tags && v.tags.rotate) rot = +v.tags.rotate;
  for (const sd of v.side_data_list || []) if (sd.rotation !== undefined) rot = +sd.rotation;
  if (Math.abs(rot) % 180 === 90) [w, h] = [h, w];
  const info = {
    w, h, fps, has_audio: st.some((x) => x.codec_type === "audio"),
    duration: parseFloat((d.format || {}).duration) || 0,
  };
  infoCache.set(path, info);
  return info;
}
export async function probeDuration(p) {
  const r = await ffrun(["-v", "error", "-show_entries", "format=duration", "-of", "json", p], { tool: "ffprobe" });
  try { return parseFloat(JSON.parse(r.stdout).format.duration) || 0; } catch (e) { return 0; }
}

const cropCache = new Map();
export async function detectCrop(path, dur) {
  if (cropCache.has(path)) return cropCache.get(path);
  let res = null;
  try {
    const r = await ffrun(["-nostdin", "-hide_banner", "-ss", (dur * 0.3).toFixed(0), "-t", "20", "-i", path,
      "-vf", "cropdetect=24:2:0", "-an", "-f", "null", "-"]);
    const m = [...String(r.stderr).matchAll(/crop=(\d+:\d+:\d+:\d+)/g)].map((x) => x[1]);
    if (m.length) {
      const cnt = {};
      for (const k of m) cnt[k] = (cnt[k] || 0) + 1;
      res = "crop=" + Object.entries(cnt).sort((a, b) => b[1] - a[1])[0][0];
    }
  } catch (e) { res = null; }
  cropCache.set(path, res);
  return res;
}

export function keyChain(s) {
  const col = hex0x(s.chroma_color, "00FF00");
  let c = `chromakey=color=${col}:similarity=${(+s.chroma_sim).toFixed(3)}:blend=${(+s.chroma_blend).toFixed(3)}`;
  if (s.chroma_spill) {
    const r = parseInt(col.slice(2, 4), 16), g = parseInt(col.slice(4, 6), 16), b = parseInt(col.slice(6, 8), 16);
    if (g >= b && g > r) c += ",despill=type=green";
    else if (b > g && b > r) c += ",despill=type=blue";
  }
  return c;
}

// Crop of the imported movie: ratio (src_aspect), zoom and position. Returns [x, y, w, h], all even.
export function sourceCropBox(s, sw, sh) {
  const a = String(s.src_aspect || "Original");
  let ratio = sw / sh;
  if (a !== "Original") { const [p, q] = a.split(":").map(Number); ratio = p / q; }
  let bw, bh;
  if (sw / sh > ratio) { bh = sh; bw = sh * ratio; } else { bw = sw; bh = sw / ratio; }
  const z = Math.max(1, +s.zoom || 1);
  const w = Math.min(sw, Math.max(2, Math.floor(Math.floor(bw / z) / 2) * 2));
  const h = Math.min(sh, Math.max(2, Math.floor(Math.floor(bh / z) / 2) * 2));
  const cx = Math.min(100, Math.max(0, +s.crop_x));
  const cy = Math.min(100, Math.max(0, +s.crop_y));
  const x = Math.floor(Math.floor(((sw - w) * cx) / 100) / 2) * 2;
  const y = Math.floor(Math.floor(((sh - h) * cy) / 100) / 2) * 2;
  return [x, y, w, h];
}

export function outSize(s, sw, sh) {
  const short = { "480p": 480, "720p": 720, "1080p": 1080, "1440p": 1440, "2160p (4K)": 2160 }[s.resolution];
  if (s.aspect === "Original") {
    if (!short) return [ev(sw), ev(sh)];
    return sw >= sh ? [ev((sw * short) / sh), ev(short)] : [ev(short), ev((sh * short) / sw)];
  }
  const [a, b] = s.aspect.split(":").map(Number);
  const sh2 = short || Math.min(sw, sh);
  return a >= b ? [ev((sh2 * a) / b), ev(sh2)] : [ev(sh2), ev((sh2 * b) / a)];
}

export const isHardware = (codec) => String(codec).includes("hardware");

export function encoderArgs(s, codec = null) {
  codec = codec || s.codec;
  const q = QUALITY[s.quality] || QUALITY.High;
  const br = Math.round(Math.min(MAX_BITRATE, Math.max(500, +s.bitrate)));
  const exact = String(s.rate_mode || RATE_MODES[0]).startsWith("Exact");
  const cap = ["-maxrate", `${br}k`, "-bufsize", `${br * 2}k`];
  let v;
  if (s._fast) v = ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "28"];
  else if (isHardware(codec)) {
    const h265 = codec.includes("265");
    v = ["-c:v", h265 ? "hevc_mediacodec" : "h264_mediacodec", "-b:v", `${br}k`,
      "-bitrate_mode", exact ? "cbr" : "vbr"].concat(h265 ? ["-tag:v", "hvc1"] : []);
  } else {
    const rc = exact
      ? ["-b:v", `${br}k`, "-minrate", `${br}k`, "-maxrate", `${br}k`, "-bufsize", `${br * 2}k`, "-x264-params", "nal-hrd=cbr"]
      : ["-crf", String(q.crf), ...cap];
    v = ["-c:v", "libx264", "-preset", X264_PRESETS.includes(s.x264_preset) ? s.x264_preset : q.x264, ...rc, "-profile:v", "high"];
  }
  if (String(s.fps) !== "Original") v.push("-r", String(s.fps));
  return [...v, "-c:a", "aac", "-b:a", s.audio_bitrate, "-ac", "2"];
}

const layerKey = (it) => { const v = parseInt(it.layer, 10); return Number.isFinite(v) ? v : 1; };
const byLayer = (a, b) => layerKey(a) - layerKey(b);

// Timeline item -> [delay, end] inside clip [t0, t0+d], relative to the clip start. null = not visible.
export function span(item, t0, d) {
  const st = +item.start || 0;
  let en = +item.end || 0;
  if (en <= 0) en = 1e9;
  if (en <= t0 || st >= t0 + d) return null;
  return [Math.max(0, st - t0), Math.min(en, t0 + d) - t0];
}

export function frameRate(info) {
  const [n, d] = String(info.fps).split("/").map(Number);
  return n / d > 0 ? n / d : 25;
}

// Filter lines that keep only `pieces` ([[abs_start, length], ...]) of the input and join them. Picture and
// sound are cut and joined in the SAME concat filter, so they can never drift apart.
// ------------------------------------------------------------------ retention boost (Auto Short)
export const BOOST_DEFAULT = { zoom: true, zoom_pct: 8, bar: true, loud: true, crisp: true, part_label: true, hook: "" };

// Times (s from the start of the clip) where the picture switches between normal and punched-in: on the dialogue
// cuts (a jump cut then looks planned), plus every `step` s in a calm stretch. Never closer than minGap.
export function zoomToggles(bounds, dur, minGap = 2.5, maxGap = 5.5, step = 4.0) {
  const out = [];
  let last = 0;
  for (const c of [...bounds.map(Number).sort((a, b) => a - b), dur + maxGap + 1]) {
    while (c - last > maxGap && last + step < dur - 1) { last += step; out.push(Math.round(last * 1000) / 1000); }
    if (c < dur - 1 && c - last >= minGap) { out.push(Math.round(c * 1000) / 1000); last = c; }
  }
  return out;
}
export function zoomExpr(toggles, pct) {
  const amt = Math.max(0, +pct) / 100;
  if (!toggles.length || amt <= 0) return "1";
  return `1+${amt.toFixed(3)}*mod(${toggles.map((t) => `gte(t,${t.toFixed(3)})`).join("+")},2)`;
}

export function piecesGraph(pieces, base, fr, hasAudio, fade = 0.02) {
  const n = pieces.length;
  const rel = pieces.map(([a, d]) => {
    const s = Math.round((a - base) * fr) / fr;
    let e = Math.round((a - base + d) * fr) / fr;
    if (e - s < 1 / fr) e = s + 1 / fr;
    const s0 = Math.max(0, s);
    return [s0, s0 + (e - s)];
  });
  const fl = [];
  let vsrc;
  if (n === 1) {
    vsrc = ["[0:v:0]"];
    if (hasAudio) fl.push("[0:a:0]aformat=sample_rates=48000:channel_layouts=stereo[as0]");
  } else {
    fl.push(`[0:v:0]split=${n}` + rel.map((_, i) => `[vs${i}]`).join(""));
    vsrc = rel.map((_, i) => `[vs${i}]`);
    if (hasAudio) fl.push("[0:a:0]aformat=sample_rates=48000:channel_layouts=stereo," + `asplit=${n}` + rel.map((_, i) => `[as${i}]`).join(""));
  }
  let joined = "", total = 0;
  rel.forEach(([s, e], i) => {
    const L = e - s;
    total += L;
    fl.push(`${vsrc[i]}trim=start=${s.toFixed(5)}:end=${e.toFixed(5)},setpts=PTS-STARTPTS[vt${i}]`);
    joined += `[vt${i}]`;
    if (hasAudio) {
      const f = Math.max(0.001, Math.min(fade, L / 2));
      fl.push(`[as${i}]atrim=start=${s.toFixed(5)}:end=${e.toFixed(5)},asetpts=PTS-STARTPTS,` +
        `afade=t=in:d=${f.toFixed(3)},afade=t=out:st=${Math.max(0, L - f).toFixed(5)}:d=${f.toFixed(3)}[at${i}]`);
      joined += `[at${i}]`;
    }
  });
  fl.push(`${joined}concat=n=${n}:v=1:a=${hasAudio ? 1 : 0}[vcat]` + (hasAudio ? "[acat]" : ""));
  return [fl, "[vcat]", hasAudio ? "[acat]" : null, total];
}

// The text renderer turns a text item into a transparent PNG (Android's own text drawing, so Hindi and every
// other script is shaped correctly). Set by the app (textrender.js) or by the tests.
let textRenderer = null;
export function setTextRenderer(fn) { textRenderer = fn; }

// The frame size after auto-crop + the movie crop + the output ratio: [sw, sh, OW, OH]
export function frameGeometry(s, info, crop) {
  let sw = info.w, sh = info.h;
  if (crop && s.auto_crop) {
    const m = /crop=(\d+):(\d+):/.exec(crop);
    if (m) { sw = +m[1]; sh = +m[2]; }
  }
  [, sw, sh] = geometryFilters(s, sw, sh);
  const [, , cw, ch] = sourceCropBox(s, sw, sh);
  const [OW, OH] = outSize(s, cw, ch);
  return { srcW: sw, srcH: sh, cropW: cw, cropH: ch, OW, OH };
}

// One FFmpeg command for the clip [start, start+dur]. Order: auto-crop > chroma > colour > crop > fit >
// finish > overlays > text > audio.
// pieces=[[abs_start, length], ...]: keep only these pieces of the movie and join them in one pass (dialogue
// cut / Auto Short). Overlay, text and audio times are then relative to the START OF THE JOINED CLIP.
let _ffNew = null;
async function ffNewSyntax() {
  if (_ffNew === null) {
    try {
      const v = await ffrun(["-hide_banner", "-version"]);
      const m = /version\s+n?(\d+)\./.exec(v.stdout || "");
      _ffNew = m ? +m[1] >= 7 : true;
    } catch (e) { _ffNew = true; }
  }
  return _ffNew;
}

// In / Out / Loop animation of a text picture: FFmpeg expressions (position offsets, size, fades, blink, typewriter)
export function textAnim(t, tst, ten, OW, OH) {
  const span = Math.max(0.1, ten - tst);
  const aIn = String(t.anim_in || "None"), aOut = String(t.anim_out || "None"), loop = String(t.anim_loop || "None");
  const din = aIn !== "None" ? Math.min(Math.max(0.05, +t.anim_in_dur || 0.5), span / 2) : 0;
  const dout = aOut !== "None" ? Math.min(Math.max(0.05, +t.anim_out_dur || 0.5), span / 2) : 0;
  const pin = din ? `clip((t-${tst.toFixed(3)})/${din.toFixed(3)},0,1)` : "1";
  const pout = dout ? `clip((${ten.toFixed(3)}-t)/${dout.toFixed(3)},0,1)` : "1";
  const eIn = `(1-pow(1-${pin},2))`, eOut = `(1-pow(1-${pout},2))`, lt = `(t-${tst.toFixed(3)})`;
  const dx = [], dy = [], sc = [], fades = [];
  const distx = 0.12 * OW, disty = 0.08 * OH;
  const dirs = { "Slide up": [0, 1], "Slide down": [0, -1], "Slide left": [1, 0], "Slide right": [-1, 0] };
  if (dirs[aIn]) { const [a, b] = dirs[aIn]; if (a) dx.push(`${(a * distx).toFixed(1)}*(1-${eIn})`); else dy.push(`${(b * disty).toFixed(1)}*(1-${eIn})`); }
  if (dirs[aOut]) { const [a, b] = dirs[aOut]; if (a) dx.push(`${(-a * distx).toFixed(1)}*(1-${eOut})`); else dy.push(`${(-b * disty).toFixed(1)}*(1-${eOut})`); }
  if (aIn === "Pop") sc.push(`(0.3+0.7*${eIn}+0.15*sin(PI*${pin}))`);
  if (aOut === "Pop") sc.push(`(0.2+0.8*${eOut})`);
  if (loop === "Pulse") sc.push(`(1+0.07*sin(2*PI*${lt}/0.9))`);
  else if (loop === "Bounce") dy.push(`-${(0.018 * OH).toFixed(1)}*abs(sin(2*PI*${lt}/1.4))`);
  else if (loop === "Shake") dx.push(`${Math.max(2, (4 * OH) / 1080).toFixed(1)}*sin(2*PI*${lt}*9)`);
  if (din && aIn !== "Typewriter") fades.push(`fade=t=in:st=${tst.toFixed(3)}:d=${din.toFixed(3)}:alpha=1`);
  if (dout) fades.push(`fade=t=out:st=${(ten - dout).toFixed(3)}:d=${dout.toFixed(3)}:alpha=1`);
  const blink = loop === "Blink" ? `*lt(mod(t-${tst.toFixed(3)},0.8),0.55)` : "";
  // typewriter: the words appear one by one during the 'In' time (a word is never split: fine for Hindi too)
  let words = 0, steps = [];
  if (aIn === "Typewriter" && din) {
    words = stripColors(t.text).split(/\s+/).filter(Boolean).length;
    if (words > 1) {
      const group = Math.max(1, Math.ceil(words / 40));
      const counts = [];
      for (let k = group; k < words; k += group) counts.push(k);
      const step = din / (counts.length + 1);
      steps = counts.map((k, i) => [k, tst + i * step, tst + (i + 1) * step]);
      steps.push([null, tst + counts.length * step, ten]);
    }
  }
  return { dx: dx.join("+") || "0", dy: dy.join("+") || "0", scale: sc.join("*"), fades, blink, words, steps };
}

export async function buildCommand(movie, start, dur, out, sIn, info, { crop = null, codec = null, pieces = null, tmpDir = "" } = {}) {
  const s = sanitize(sIn);
  const inp = [], fl = [], tmp = [];
  let vin = "[0:v:0]", ain = "[0:a:0]", ssBase = null, readLen = 0;
  if (pieces && pieces.length) {
    pieces = pieces.map(([a, d]) => [+a, +d]).filter(([, d]) => d > 0.02);
    ssBase = Math.max(0, pieces[0][0]);
    const [gl, v, a, total] = piecesGraph(pieces, ssBase, frameRate(info), info.has_audio, +(s._joint_fade ?? 0.02));
    fl.push(...gl);
    vin = v; ain = a;
    start = 0; dur = total;
    readLen = Math.max(...pieces.map(([a2, d]) => a2 + d)) - ssBase + 0.3;
  }
  const st = { idx: 1, n: 0, cur: "[v0]" };
  const fps = info.fps;
  let sw = info.w, sh = info.h;
  const pre = [];
  if (crop && s.auto_crop) {
    const m = /crop=(\d+):(\d+):/.exec(crop);
    if (m) { sw = +m[1]; sh = +m[2]; pre.push(crop); }
  }
  const [geo, gw, gh] = geometryFilters(s, sw, sh);
  pre.push(...geo);
  sw = gw; sh = gh;
  pre.push("setsar=1");
  fl.push(`${vin}${pre.join(",")}[v0]`);
  const newlab = () => `[s${++st.n}]`;
  const add = (chain) => { const lab = newlab(); fl.push(`${st.cur}${chain}${lab}`); st.cur = lab; };
  const addInput = (args) => { inp.push(args); return st.idx++; };

  // chroma key (green screen) + new background
  if (s.chroma_on) {
    add(keyChain(s) + ",format=yuva420p");
    const fg = st.cur;
    if (s.chroma_bg_type === "Color" || !s.chroma_bg_file) {
      fl.push(`color=c=${hex0x(s.chroma_bg_color, "1E1E1E")}:s=${sw}x${sh}:r=${fps}[bg]`);
    } else {
      const i = addInput([...(s.chroma_bg_type === "Image" ? ["-loop", "1"] : ["-stream_loop", "-1"]), "-i", s.chroma_bg_file]);
      fl.push(`[${i}:v:0]scale=${sw}:${sh}:force_original_aspect_ratio=increase,crop=${sw}:${sh},setsar=1,fps=${fps},format=yuv420p[bg]`);
    }
    const lab = newlab();
    fl.push(`[bg]${fg}overlay=0:0:shortest=1:format=auto${lab}`);
    st.cur = lab;
  }

  const cf = [...CL.ffmpegColour(s, sw), ...effectFilters(s)];
  if (cf.length) add(cf.join(","));

  // 1) IMPORTED MOVIE crop
  const [cx, cy, cw, ch] = sourceCropBox(s, sw, sh);
  if (cw !== sw || ch !== sh) add(`crop=${cw}:${ch}:${cx}:${cy},setsar=1`);
  sw = cw; sh = ch;

  // 2) FINAL OUTPUT frame
  const [OW, OH] = outSize(s, sw, sh);
  const cropMode = s.fit_mode.startsWith("Crop");
  const pct = cropMode ? 100 : +s.fit_scale;
  const sameRatio = Math.abs(OW / OH - sw / sh) < 0.01;
  if (sameRatio && pct >= 99.5) add(`scale=${OW}:${OH}:flags=lanczos,setsar=1`);
  else if (cropMode) {
    const f = Math.max(OW / sw, OH / sh);
    const nw = Math.max(OW, evUp(sw * f)), nh = Math.max(OH, evUp(sh * f));
    add(`scale=${nw}:${nh}:flags=lanczos,crop=${OW}:${OH}:${Math.floor((nw - OW) / 2)}:${Math.floor((nh - OH) / 2)},setsar=1`);
  } else {
    const k = (Math.min(OW / sw, OH / sh) * pct) / 100;
    const fw = Math.min(OW, ev(sw * k)), fh = Math.min(OH, ev(sh * k));
    const fy = (+s.fit_y / 100).toFixed(4);
    if (s.fit_mode.startsWith("Blur")) {
      const n = st.n + 1;
      const amt = Math.max(2, Math.min(Math.round(+s.blur_amount), Math.floor(Math.min(OW, OH) / 4)));
      fl.push(`${st.cur}split=2[ga${n}][gb${n}]`);
      const bw = Math.max(16, ev(OW / 4)), bh = Math.max(16, ev(OH / 4)), amt4 = Math.max(1, Math.round(amt / 4));
      fl.push(`[ga${n}]scale=${bw}:${bh}:force_original_aspect_ratio=increase:flags=fast_bilinear,crop=${bw}:${bh},boxblur=${amt4}:2,scale=${OW}:${OH}:flags=bilinear[gk${n}]`);
      fl.push(`[gb${n}]scale=${fw}:${fh}:flags=lanczos[gf${n}]`);
      const lab = newlab();
      fl.push(`[gk${n}][gf${n}]overlay=(W-w)/2:(H-h)*${fy}${lab}`);
      st.cur = lab;
    } else {
      const col = s.fit_mode.startsWith("Black") ? "black" : hex0x(s.bg_color, "1E1E1E");
      add(`scale=${fw}:${fh}:flags=lanczos,pad=${OW}:${OH}:(ow-iw)/2:(oh-ih)*${fy}:${col},setsar=1`);
    }
  }

  const ff = CL.ffmpegFinish(s);
  if (ff.length) add(ff.join(","));

  // retention boost: crisp look, punch-in zoom on the cuts (light filters, same single pass)
  const boost = s._boost || {};
  if (boost.crisp) add("eq=contrast=1.05:saturation=1.10,unsharp=luma_msize_x=3:luma_msize_y=3:luma_amount=0.6:chroma_amount=0");
  if (boost.zoom) {
    const bounds = [];
    let acc = 0;
    for (const [, d] of (pieces || []).slice(0, -1)) { acc += d; bounds.push(acc); }
    const z = zoomExpr(zoomToggles(bounds, dur), boost.zoom_pct ?? 8);
    if (z !== "1") add(`scale=w='trunc(${OW}*(${z})/2)*2':h='trunc(${OH}*(${z})/2)*2':eval=frame:flags=bilinear,crop=${OW}:${OH},setsar=1`);
  }

  // overlays (photo / video / GIF) - higher layer on top
  for (const ov0 of [...s.overlays].sort(byLayer)) {
    const ov = { ...OVERLAY_DEFAULT, ...ov0 };
    if (!ov.path) continue;
    const sp = span(ov, start, dur);
    if (!sp) continue;
    const [ost, oen] = sp;
    const voff = (+ov.src_offset || 0) + Math.max(0, start - +ov.start);
    const isvid = isOverlayVideo(ov.path);
    const args = isvid
      ? [...(ov.loop ? ["-stream_loop", "-1"] : []), ...(voff > 0 ? ["-ss", voff.toFixed(3)] : []), "-i", ov.path]
      : ["-loop", "1", "-i", ov.path];
    const i = addInput(args);
    const steps = [];
    if (isvid) steps.push(`setpts=PTS-STARTPTS+${ost.toFixed(3)}/TB`);
    steps.push(`scale=${ev((OW * Math.max(1, +ov.scale)) / 100)}:-2`, "format=yuva420p");
    if (ov.chroma) steps.push(keyChain({ ...s, chroma_color: ov.key_color, chroma_sim: ov.key_sim, chroma_blend: ov.key_blend, chroma_spill: ov.key_spill }));
    if (+ov.opacity < 100) steps.push(`colorchannelmixer=aa=${(Math.max(0, +ov.opacity) / 100).toFixed(2)}`);
    fl.push(`[${i}:v:0]${steps.join(",")}[o${i}]`);
    const mx = Math.floor(OW * 0.03), my = Math.floor(OH * 0.03);
    const px = { Left: String(mx), Center: "(W-w)/2", Right: `W-w-${mx}` };
    const py = { Top: String(my), Middle: "(H-h)/2", Bottom: `H-h-${my}` };
    let xe, ye;
    if (ov.pos === "Custom") { xe = `W*${(+ov.x / 100).toFixed(4)}`; ye = `H*${(+ov.y / 100).toFixed(4)}`; }
    else if (ov.pos === "Center") { xe = px.Center; ye = py.Middle; }
    else { const [vert, horz] = ov.pos.split("-"); xe = px[horz]; ye = py[vert]; }
    const lab = newlab();
    fl.push(`${st.cur}[o${i}]overlay=x=${xe}:y=${ye}:enable='between(t,${ost.toFixed(3)},${oen.toFixed(3)})':eof_action=pass:format=auto${lab}`);
    st.cur = lab;
  }

  // text layers: drawn by the phone into transparent pictures, placed with overlay (+ In / Out / Loop animations)
  for (const t0 of [...s.texts].sort(byLayer)) {
    const t = { ...TEXT_DEFAULT, ...t0 };
    if (!stripColors(t.text).trim()) continue;
    const sp = span(t, start, dur);
    if (!sp) continue;
    if (!textRenderer) throw new Error("Text drawing is not ready.");
    const [tst, ten] = sp;
    const A = textAnim(t, tst, ten, OW, OH);
    // typewriter: one picture per number of words shown, each for its own moment
    const frames = A.words > 1 ? A.steps : [[null, tst, ten]];
    for (const [reveal, a, b] of frames) {
      const img = await textRenderer(reveal === null ? t : { ...t, _reveal: reveal }, OW, OH, tmpDir);
      if (!img) continue;
      tmp.push(img.path);
      const i = addInput(["-loop", "1", "-i", img.path]);
      const steps = ["format=yuva420p"];
      if (A.scale) steps.push(`scale=w='max(2,trunc(iw*(${A.scale})/2)*2)':h='max(2,trunc(ih*(${A.scale})/2)*2)':eval=frame`);
      steps.push(...A.fades);
      fl.push(`[${i}:v:0]${steps.join(",")}[t${i}]`);
      const lab = newlab();
      // the picture keeps its centre when it grows / shrinks (pop, pulse)
      const cx = A.scale ? `${Math.round(img.x)}+(${img.w || 0}-w)/2` : String(Math.round(img.x));
      const cy = A.scale ? `${Math.round(img.y)}+(${img.h || 0}-h)/2` : String(Math.round(img.y));
      fl.push(`${st.cur}[t${i}]overlay=x='${cx}+${A.dx}':y='${cy}+${A.dy}':enable='between(t,${a.toFixed(3)},${b.toFixed(3)})${A.blink}':eval=frame:eof_action=pass:format=auto${lab}`);
      st.cur = lab;
    }
  }

  if (boost.bar && dur > 1) {                      // thin progress bar along the top: viewers stay to see it fill
    const bh = Math.max(4, Math.floor(Math.floor(OH / 200) / 2) * 2);
    fl.push(`color=c=0xFFD400:s=${OW}x${bh}:r=${fps},format=yuv420p[pbar]`);
    const lab = newlab();
    fl.push(`${st.cur}[pbar]overlay=x='-w+w*t/${dur.toFixed(3)}':y=0:shortest=1:format=auto${lab}`);
    st.cur = lab;
  }
  const speed = Math.max(0.25, Math.min(4, +s.speed || 1));
  const fi = +s.vfade_in || 0, fo = +s.vfade_out || 0;
  const endf = [];
  if (fi > 0) endf.push(`fade=t=in:st=0:d=${Math.min(fi, dur / 2).toFixed(3)}`);
  if (fo > 0) endf.push(`fade=t=out:st=${Math.max(0, dur - Math.min(fo, dur / 2)).toFixed(3)}:d=${Math.min(fo, dur / 2).toFixed(3)}`);
  if (Math.abs(speed - 1) > 1e-3) endf.push(`setpts=PTS/${speed.toFixed(4)}`);
  endf.push("format=yuv420p");
  fl.push(`${st.cur}${endf.join(",")}[vout]`);

  // audio: original track (optional) + any number of audio layers, mixed
  const fsec = Math.max(0.005, +(s.fade_sec ?? 0.15));
  const fai = Math.max(fsec, Math.min(fi, dur / 2)), fao = Math.max(fsec, Math.min(fo, dur / 2));   // picture fade = sound fade
  let fades = `afade=t=in:d=${fai.toFixed(3)},afade=t=out:st=${Math.max(0, dur - fao).toFixed(3)}:d=${fao.toFixed(3)}`;
  if (Math.abs(speed - 1) > 1e-3) fades += "," + atempoChain(speed);
  let amap = ["-an"];
  const auds = [];
  for (const a0 of [...s.audios].sort(byLayer)) {
    const a = { ...AUDIO_DEFAULT, ...a0 };
    if (!a.path) continue;
    const sp = span(a, start, dur);
    if (!sp) continue;
    const [ast, aen] = sp;
    const off = (+a.src_offset || 0) + Math.max(0, start - +a.start);
    auds.push([a, ast, off, aen - ast]);
  }
  const replace = String(s.music_mode).startsWith("Replace") && auds.length > 0;
  const labels = [];
  if (info.has_audio && !replace) {
    const ovVol = Math.max(0, +s.orig_volume) / 100;
    const clean = s._denoise ? "highpass=f=70,afftdn=nf=-25," : "";
    const loud = boost.loud ? "dynaudnorm=f=250:g=15," : "";
    fl.push(`${ain}aformat=sample_rates=48000:channel_layouts=stereo,${clean}${loud}volume=${ovVol.toFixed(3)}[oa]`);
    labels.push("[oa]");
  }
  auds.forEach(([a, ast, off, L], k) => {
    const i = addInput([...(a.loop ? ["-stream_loop", "-1"] : []), "-i", a.path]);
    const vol = Math.max(0, +a.volume) / 100;
    fl.push(`[${i}:a:0]aformat=sample_rates=48000:channel_layouts=stereo,atrim=start=${off.toFixed(3)}:duration=${L.toFixed(3)},asetpts=PTS-STARTPTS,` +
      `adelay=${Math.round(ast * 1000)}:all=1,volume=${vol.toFixed(3)}[ax${k}]`);
    labels.push(`[ax${k}]`);
  });
  if (labels.length) {
    if (labels.length === 1) fl.push(`${labels[0]}atrim=0:${dur.toFixed(3)},${fades}[aout]`);
    else fl.push(labels.join("") + `amix=inputs=${labels.length}:duration=longest:dropout_transition=0:normalize=0,atrim=0:${dur.toFixed(3)},${fades}[aout]`);
    amap = ["-map", "[aout]"];
  }

  const cmd = ["-nostdin", "-y", "-hide_banner", "-v", "error", "-stats_period", "0.5", "-progress", "pipe:2"];
  if (ssBase !== null) cmd.push("-ss", ssBase.toFixed(3), "-t", readLen.toFixed(3), "-i", movie);
  else cmd.push("-ss", start.toFixed(2), "-t", dur.toFixed(2), "-i", movie);
  for (const a of inp) cmd.push(...a);
  // a very long graph (a movie with hundreds of dialogue pieces) does not fit on the command line: pass it as a file
  const graph = fl.join(";");
  if (graph.length > 20000) {
    const gp = join(tmpDir || ".", `graph_${Date.now()}_${Math.random().toString(36).slice(2, 8)}.txt`);
    await bridge().writeText(gp, graph);
    tmp.push(gp);
    cmd.push((await ffNewSyntax()) ? "-/filter_complex" : "-filter_complex_script", gp);
  } else cmd.push("-filter_complex", graph);
  cmd.push("-map", "[vout]", ...amap, "-t", (dur / speed).toFixed(3),
    ...encoderArgs(s, codec), "-movflags", "+faststart", "-f", "mp4", out);
  return { cmd, tmp, dur: dur / speed, OW, OH };
}

// video bitrate (kbps) of a finished file, 0 when unknown
export async function videoKbps(path) {
  const r = await ffrun(["-v", "error", "-select_streams", "v:0", "-show_entries", "stream=bit_rate:format=bit_rate,duration,size", "-of", "json", path], { tool: "ffprobe" });
  try {
    const d = JSON.parse(r.stdout);
    const v = +((d.streams || [])[0] || {}).bit_rate;
    if (v > 0) return Math.round(v / 1000);
    const f = d.format || {};
    if (+f.size > 0 && +f.duration > 0) return Math.round((+f.size * 8) / +f.duration / 1000);
  } catch (e) { /* unknown */ }
  return 0;
}

// once a phone's hardware encoder has missed the bitrate, the CPU encoder is used directly for the rest of the session
let hardwareWeak = false;
// the phone's hardware encoder could not start at all (FFmpeg runs as its own process on Android and often cannot reach the video chip): the CPU encoder is used directly from then on
let hardwareBroken = false;

// ------------------------------------------------------------------ runners
export class Runner {
  constructor(settings, log, progress, onClip, tmpDir) {
    this.s = sanitize(settings);
    this.log = log || (() => {});
    this.progress = progress || (() => {});
    this.onClip = onClip || (() => {});
    this.tmpDir = tmpDir;
    this.stopFlag = false;
    this.job = { current: null };
    this.clipProgress = null;      // (fraction of the clip being exported) -> void
  }

  stop() {
    this.stopFlag = true;
    if (this.job.current) this.job.current.cancel();
  }

  async cut(movie, start, dur, out, info, crop, settings = null, pieces = null) {
    const S = settings || this.s;
    const part = out + ".part";
    const run = async (codec) => {
      const { cmd, tmp, dur: total } = await buildCommand(movie, start, dur, part, S, info, { crop, codec, pieces, tmpDir: this.tmpDir });
      let err = "";
      const r = await ffrun(cmd, {
        job: this.job,
        onLog: (line) => {
          const m = /^out_time_(?:us|ms)=(\d+)/.exec(line);
          if (m) { if (this.clipProgress && total > 0) this.clipProgress(Math.min(1, +m[1] / 1e6 / total)); return; }
          if (/^(frame|fps|stream_|bitrate|total_size|out_time|dup_frames|drop_frames|speed|progress)=/.test(line)) return;
          err += line + "\n";
        },
      });
      for (const t of tmp) bridge().remove(t);
      return [r.code === 0, err || r.stderr || ""];
    };
    const first = isHardware(S.codec) && (hardwareBroken || (hardwareWeak && String(S.rate_mode).startsWith("Exact"))) ? "H.264 (CPU)" : S.codec;
    let [ok, err] = await run(first);
    if (!ok && !this.stopFlag && isHardware(first)) {
      this.log("Phone hardware encoder is not available here - using the CPU encoder (fast x264) for all exports.");
      hardwareBroken = true;
      [ok, err] = await run("H.264 (CPU)");
    } else if (ok && !this.stopFlag && isHardware(first) && !S._fast && String(S.rate_mode).startsWith("Exact")) {
      // some phones' video chips ignore the bitrate: then the clip is made again with x264, which always obeys it
      const got = await videoKbps(part);
      const want = Math.round(+S.bitrate);
      if (got > 0 && got < want * 0.7) {
        this.log(`This phone's hardware encoder gave only ${got} kbps (you asked ${want} kbps) - exporting again with the CPU encoder for the exact bitrate ...`);
        hardwareWeak = true;
        [ok, err] = await run("H.264 (CPU)");
      }
    }
    if (ok && !this.stopFlag) {
      await bridge().remove(out);
      await bridge().rename(part, out);
      await bridge().scanFile(out);
    } else {
      await bridge().remove(part);
      if (!this.stopFlag) this.log("ffmpeg error: " + String(err).slice(-600));
    }
    return ok && !this.stopFlag;
  }
}

// Split [a, b] into [start, length] pieces of `part` seconds (0 = one piece). A final piece shorter than
// min_last is merged into the previous part. Returns [ranges, merged_seconds].
export function makeRanges(a, b, part, minLast) {
  part = +part || Math.max(1, b - a);
  const pieces = [];
  let t = a;
  while (t < b - 0.5) { pieces.push([t, Math.min(part, b - t)]); t += part; }
  let merged = 0;
  const threshold = Math.min(+minLast, part);
  if (pieces.length > 1 && pieces[pieces.length - 1][1] < threshold - 1e-6) {
    merged = pieces[pieces.length - 1][1];
    pieces[pieces.length - 2][1] += merged;
    pieces.pop();
  }
  return [pieces.filter(([, d]) => d > 0.5), merged];
}

// ------------------------------------------------------------------ silence
export async function detectSilence(path, noiseDb = -35, minSec = 2, dur = null, job = null, windows = null) {
  // windows = [[a, b], ...]: scan ONLY these stretches (jumps straight to them - the whole movie is never read)
  const one = async (start, length) => {
    const pre = start === null ? [] : ["-ss", start.toFixed(3), "-t", length.toFixed(3)];
    const r = await ffrun(["-nostdin", "-hide_banner", "-v", "info", ...pre, "-i", path, "-vn", "-af",
      `aresample=8000,aformat=channel_layouts=mono,silencedetect=noise=${+noiseDb}dB:d=${+minSec}`, "-f", "null", "-"], { job });
    const off = start || 0, res = [];
    let cur = null;
    for (const m of String(r.stderr).matchAll(/silence_(start|end):\s*(-?[\d.]+)/g)) {
      const v = parseFloat(m[2]);
      if (m[1] === "start") cur = Math.max(0, v);
      else if (cur !== null) { res.push([cur + off, v + off]); cur = null; }
    }
    if (cur !== null) res.push([cur + off, (length || dur || cur) + off]);
    return res;
  };
  if (!windows) return one(null, dur);
  const all = [];
  for (const [a, b] of windows) all.push(...(await one(a, b - a)));
  return all;
}

// Silent stretches are cut, keeping `pad` seconds of silence on both sides. Returns [[start, length], ...].
export function silenceKeepRanges(silences, a, b, pad = 0.25, minKeep = 0.3, flags = null) {
  const cuts = [];
  silences.forEach(([s, e], i) => {
    if (flags && !flags[i]) return;
    const cs = s + pad, ce = e - pad;
    if (ce - cs > 0.05) cuts.push([Math.max(cs, a), Math.min(ce, b)]);
  });
  cuts.sort((x, y) => x[0] - y[0]);
  const keep = [];
  let t = a;
  for (const [cs, ce] of cuts) {
    if (ce <= cs) continue;
    if (cs - t >= minKeep) keep.push([t, cs - t]);
    t = Math.max(t, ce);
  }
  if (b - t >= minKeep) keep.push([t, b - t]);
  return keep;
}

// Join already-encoded pieces with the concat demuxer (stream copy, no re-encode).
export async function concatFiles(paths, out, tmpDir) {
  const listf = join(tmpDir, `_list_${Date.now()}.txt`);
  await bridge().writeText(listf, paths.map((p) => `file '${String(p).replace(/'/g, "'\\''")}'`).join("\n") + "\n");
  const r = await ffrun(["-nostdin", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", listf, "-c", "copy",
    "-movflags", "+faststart", "-f", "mp4", out + ".part"]);
  await bridge().remove(listf);
  const ok = r.code === 0;
  if (ok) { await bridge().remove(out); await bridge().rename(out + ".part", out); await bridge().scanFile(out); }
  else await bridge().remove(out + ".part");
  return [ok, String(r.stderr).slice(-400)];
}

// plans: [{file, start, end, label, pieces: [[t0, d], ...], overlays, texts, number}]. Each plan = one file.
// plan.single_pass (dialogue cut): picture and sound are cut and joined in ONE FFmpeg pass.
// prepare(plan) -> plan or null: called right before each plan is rendered (dialogue analysis of that part).
export class StudioEngine extends Runner {
  async process(movie, plans, outDir, prepare = null) {
    const info = await probeInfo(movie);
    const crop = this.s.auto_crop ? await detectCrop(movie, info.duration) : null;
    await bridge().mkdirs(outDir);
    const total = plans.length;
    let done = 0;
    for (let i = 1; i <= total; i++) {
      if (this.stopFlag) break;
      let p = plans[i - 1];
      const base = (i - 1) / Math.max(1, total);
      this.progress(base, `Part ${i}/${total}: ${p.file}`);
      this.clipProgress = (f) => this.progress(base + f / Math.max(1, total), `Part ${i}/${total}: ${Math.round(f * 100)}%`);
      if (prepare) {
        try { p = await prepare(p); } catch (e) { this.log(`Part ${i}: analysis failed (${String(e.message || e).slice(0, 200)}) - skipped.`); p = null; }
        if (this.stopFlag) break;
        if (!p) { this.log(`Part ${i}: no dialogue found - skipped.`); continue; }
      }
      const final = join(outDir, p.file);
      const pieces = p.pieces.filter((pc) => pc[1] > 0.3);
      if (!pieces.length) { this.log(`Part ${i}: nothing is left after removing silence - skipped.`); continue; }
      const S = { ...this.s, overlays: p.overlays || [], texts: p.texts || [], audios: p.audios || this.s.audios };
      let ok;
      if (p.single_pass) {
        this.log(`Part ${i}: cutting ${pieces.length} dialogue piece(s) into one clip ...`);
        ok = await this.cut(movie, pieces[0][0], 0, final, info, crop, S, pieces);
      } else if (pieces.length === 1) {
        ok = await this.cut(movie, pieces[0][0], pieces[0][1], final, info, crop, S);
      } else {
        const seg = join(this.tmpDir, `_seg${String(i).padStart(3, "0")}_${Date.now()}`);
        await bridge().mkdirs(seg);
        const segs = [];
        ok = true;
        for (let k = 0; k < pieces.length; k++) {
          const [t0, d] = pieces[k];
          const sp = join(seg, `p${String(k + 1).padStart(3, "0")}.mp4`);
          this.log(`Part ${i}: piece ${k + 1}/${pieces.length} ...`);
          // overlay / text times of a normal part are movie times, so every piece keeps its own slice of them
          ok = (await this.cut(movie, t0, d, sp, info, crop, S)) && ok;
          segs.push(sp);
          if (this.stopFlag) break;
        }
        if (ok && !this.stopFlag) {
          const [ok2, err] = await concatFiles(segs, final, this.tmpDir);
          ok = ok2;
          if (!ok) this.log("Join error: " + err);
        }
        await bridge().remove(seg, true);
      }
      if (this.stopFlag) break;
      if (ok) {
        done++;
        this.onClip({ path: final, n: i, start: p.start, end: p.end, category: "Clip", text: p.label || "" });
        this.log(`Saved: ${final}`);
      } else this.log(`Part ${i} failed (see the error above).`);
    }
    this.clipProgress = null;
    this.progress(this.stopFlag ? done / Math.max(1, total) : 1, this.stopFlag ? "Stopped." : `Done - ${done}/${total} parts exported.`);
    this.log(`Finished. ${done}/${total} parts in: ${outDir}`);
    return done;
  }
}
