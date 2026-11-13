// Live preview (port of the desktop preview.py): one frame through the same edit pipeline as the export
// (black bars -> chroma -> colour -> crop -> fit -> particles / vignette -> overlays -> text).
import * as E from "./engine.js";
import * as CL from "./colour.js";
import { bridge } from "./bridge.js";
import { drawText, ensureFont } from "./textrender.js";

export const SHORT = 540;
const frames = new Map();
let cacheDir = "";
export function setCacheDir(d) { cacheDir = d; }

export function loadImage(url) {
  return new Promise((resolve, reject) => {
    const im = new Image();
    im.decoding = "async";
    im.onload = () => resolve(im);
    im.onerror = () => reject(new Error("could not load the picture"));
    im.src = url;
  });
}

const q = (t) => Math.round(Math.max(0, t) * 25) / 25;

// one decoded frame of a video file at time t (cached)
export async function frameAt(path, t, width = 960) {
  t = q(t);
  const key = `${path}|${t}|${width}`;
  if (frames.has(key)) { const v = frames.get(key); frames.delete(key); frames.set(key, v); return v; }
  const out = E.join(cacheDir, `frame_${(Math.abs(hash(key)) % 1e9)}.jpg`);
  const r = await E.ffrun(["-nostdin", "-y", "-v", "error", "-ss", t.toFixed(3), "-i", path, "-frames:v", "1",
    "-vf", `scale=${width}:-2`, "-q:v", "3", "-f", "image2", out]);
  if (r.code !== 0) throw new Error("No frame at this time (outside the video or at the very end).");
  const im = await loadImage(bridge().fileUrl(out));
  frames.set(key, im);
  while (frames.size > 40) frames.delete(frames.keys().next().value);
  return im;
}

function hash(s) { let h = 0; for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0; return h; }

const stills = new Map();
async function still(path) {
  if (!stills.has(path)) stills.set(path, loadImage(bridge().fileUrl(path)).catch(() => null));
  return stills.get(path);
}

function canvas(w, h) { const c = document.createElement("canvas"); c.width = Math.max(1, Math.round(w)); c.height = Math.max(1, Math.round(h)); return c; }
const hexRgb = (c, d = "00FF00") => {
  c = String(c || "").replace("#", "");
  if (!/^[0-9a-fA-F]{6}$/.test(c)) c = d;
  return [parseInt(c.slice(0, 2), 16), parseInt(c.slice(2, 4), 16), parseInt(c.slice(4, 6), 16)];
};

// alpha of every pixel after the green-screen key: 0 = keyed away, 1 = kept
function keyAlpha(data, n, col, sim, blend) {
  const [kr, kg, kb] = hexRgb(col).map((v) => v / 255);
  const out = new Float32Array(n);
  const bl = Math.max(blend, 1e-3);
  for (let i = 0; i < n; i++) {
    const r = data[i * 4] / 255, g = data[i * 4 + 1] / 255, b = data[i * 4 + 2] / 255;
    const d = Math.sqrt((r - kr) ** 2 + (g - kg) ** 2 + (b - kb) ** 2) / Math.sqrt(3);
    out[i] = Math.min(1, Math.max(0, (d - sim) / bl));
  }
  return out;
}

function cover(ctx, img, iw, ih, W, H) {
  const k = Math.max(W / iw, H / ih);
  const w = iw * k, h = ih * k;
  ctx.drawImage(img, (W - w) / 2, (H - h) / 2, w, h);
}

export function previewSize(s, sw, sh, short = SHORT) {
  let ratio = sw / sh;
  if (s.aspect !== "Original") { const [a, b] = s.aspect.split(":").map(Number); ratio = a / b; }
  let W, H;
  if (ratio >= 1) { W = Math.round(short * ratio); H = short; } else { W = short; H = Math.round(short / ratio); }
  return [Math.floor(W / 2) * 2, Math.floor(H / 2) * 2];
}

function posXY(pos, x, y, W, H, w, h) {
  if (pos === "Custom") return [Math.floor((W * x) / 100), Math.floor((H * y) / 100)];
  if (pos === "Center") return [Math.floor((W - w) / 2), Math.floor((H - h) / 2)];
  const mx = Math.floor(W * 0.03), my = Math.floor(H * 0.03);
  const [vert, horz] = pos.split("-");
  return [{ Left: mx, Center: Math.floor((W - w) / 2), Right: W - w - mx }[horz], { Top: my, Middle: Math.floor((H - h) / 2), Bottom: H - h - my }[vert]];
}

const visible = (it, t) => { const S = +it.start || 0; let en = +it.end || 0; if (en <= 0) en = 1e9; return S <= t && t < en; };
const layerOf = (it) => parseInt(it.layer, 10) || 1;

// Full preview frame at movie time t. Returns {canvas, W, H, boxes:[{kind, index, x, y, w, h}]}
export async function compose(movie, t, sIn, info, crop = null) {
  const s = E.sanitize(sIn);
  t = Math.min(Math.max(0, t), Math.max(0, info.duration - 0.05));
  const src = await frameAt(movie, t, 960);
  // black bars (same box as the export, scaled to this frame)
  let sx = 0, sy = 0, sw = src.naturalWidth, sh = src.naturalHeight;
  const kx = sw / info.w, ky = sh / info.h;
  if (crop && s.auto_crop) {
    const m = /crop=(\d+):(\d+):(\d+):(\d+)/.exec(crop);
    if (m) { sw = Math.round(+m[1] * kx); sh = Math.round(+m[2] * ky); sx = Math.round(+m[3] * kx); sy = Math.round(+m[4] * ky); }
  }
  let c0 = canvas(sw, sh);
  let x0 = c0.getContext("2d", { willReadFrequently: true });
  x0.drawImage(src, sx, sy, sw, sh, 0, 0, sw, sh);
  // rotate / flip / free crop (same as the export)
  const rot = String(s.rotate || "");
  if (rot.startsWith("90") || rot.startsWith("180") || s.flip_h || s.flip_v) {
    const turn = rot.startsWith("90");
    const c1 = canvas(turn ? sh : sw, turn ? sw : sh), x1 = c1.getContext("2d", { willReadFrequently: true });
    x1.translate(c1.width / 2, c1.height / 2);
    if (rot.startsWith("90° right")) x1.rotate(Math.PI / 2);
    else if (rot.startsWith("90° left")) x1.rotate(-Math.PI / 2);
    else if (rot.startsWith("180")) x1.rotate(Math.PI);
    x1.scale(s.flip_h ? (turn ? 1 : -1) : 1, s.flip_v ? (turn ? 1 : -1) : 1);
    x1.drawImage(c0, -sw / 2, -sh / 2);
    if (turn && (s.flip_h || s.flip_v)) {      // flips happen after the turn: mirror the turned picture
      const c2 = canvas(c1.width, c1.height), x2 = c2.getContext("2d", { willReadFrequently: true });
      x2.translate(s.flip_h ? c2.width : 0, s.flip_v ? c2.height : 0);
      x2.scale(s.flip_h ? -1 : 1, s.flip_v ? -1 : 1);
      x2.drawImage(c1, 0, 0);
      c0 = c2; x0 = x2;
    } else { c0 = c1; x0 = x1; }
    x0.setTransform(1, 0, 0, 1, 0, 0);
    sw = c0.width; sh = c0.height;
  }
  {
    const [fx0, fy0, fw0, fh0] = E.freeCropBox(s, sw, sh);
    if (fw0 !== sw || fh0 !== sh) {
      const c1 = canvas(fw0, fh0), x1 = c1.getContext("2d", { willReadFrequently: true });
      x1.drawImage(c0, fx0, fy0, fw0, fh0, 0, 0, fw0, fh0);
      c0 = c1; x0 = x1; sw = fw0; sh = fh0;
    }
  }
  // chroma key + new background
  if (s.chroma_on) {
    const id = x0.getImageData(0, 0, sw, sh);
    const a = keyAlpha(id.data, sw * sh, s.chroma_color, +s.chroma_sim, +s.chroma_blend);
    const bgc = canvas(sw, sh), bx = bgc.getContext("2d", { willReadFrequently: true });
    if (s.chroma_bg_type === "Color" || !s.chroma_bg_file) { bx.fillStyle = s.chroma_bg_color; bx.fillRect(0, 0, sw, sh); }
    else {
      try {
        const bimg = E.isVideo(s.chroma_bg_file) ? await frameAt(s.chroma_bg_file, t, 960) : await still(s.chroma_bg_file);
        if (bimg) cover(bx, bimg, bimg.naturalWidth, bimg.naturalHeight, sw, sh);
      } catch (e) { bx.fillStyle = "#1e1e1e"; bx.fillRect(0, 0, sw, sh); }
    }
    const bd = bx.getImageData(0, 0, sw, sh).data;
    for (let i = 0; i < sw * sh; i++) for (let k = 0; k < 3; k++) id.data[i * 4 + k] = id.data[i * 4 + k] * a[i] + bd[i * 4 + k] * (1 - a[i]);
    x0.putImageData(id, 0, 0);
  }
  // colour (720 px wide is plenty for the phone screen and keeps the sliders fast)
  const cw0 = Math.min(sw, 720), ch0 = Math.round((sh * cw0) / sw);
  if (cw0 !== sw) { const c1 = canvas(cw0, ch0); c1.getContext("2d").drawImage(c0, 0, 0, cw0, ch0); c0 = c1; x0 = c0.getContext("2d", { willReadFrequently: true }); }
  const colour = CL.applyColour(x0.getImageData(0, 0, c0.width, c0.height), s);
  x0.putImageData(colour, 0, 0);
  const fxs = [s.fx_bw ? "grayscale(1)" : "", s.fx_sepia ? "sepia(1)" : "", +s.fx_blur > 0 ? `blur(${((+s.fx_blur * 0.4 * c0.width) / 1280).toFixed(1)}px)` : ""].filter(Boolean);
  if (fxs.length) {
    const c1 = canvas(c0.width, c0.height), x1 = c1.getContext("2d", { willReadFrequently: true });
    x1.filter = fxs.join(" ");
    x1.drawImage(c0, 0, 0);
    c0 = c1; x0 = x1;
  }
  // the movie's own crop
  const [cx, cy, cw, ch] = E.sourceCropBox(s, c0.width, c0.height);
  // final frame
  const [W, H] = previewSize(s, cw, ch);
  const fr = canvas(W, H), fx = fr.getContext("2d", { willReadFrequently: true });
  const cropMode = s.fit_mode.startsWith("Crop");
  const pct = cropMode ? 100 : +s.fit_scale;
  const geo = E.frameGeometry(s, info, crop);
  if (Math.abs(W / H - cw / ch) < 0.01 && pct >= 99.5) fx.drawImage(c0, cx, cy, cw, ch, 0, 0, W, H);
  else if (cropMode) {
    const k = Math.max(W / cw, H / ch);
    fx.drawImage(c0, cx, cy, cw, ch, (W - cw * k) / 2, (H - ch * k) / 2, cw * k, ch * k);
  } else {
    const k = (Math.min(W / cw, H / ch) * pct) / 100;
    const fw = Math.max(1, Math.min(W, Math.round(cw * k))), fh = Math.max(1, Math.min(H, Math.round(ch * k)));
    if (s.fit_mode.startsWith("Blur")) {
      const amt = Math.max(2, Math.min(Math.round(+s.blur_amount), Math.floor(Math.min(geo.OW, geo.OH) / 4)));
      fx.filter = `blur(${Math.max(1, (amt * W) / geo.OW).toFixed(1)}px)`;
      const kk = Math.max(W / cw, H / ch) * 1.06;
      fx.drawImage(c0, cx, cy, cw, ch, (W - cw * kk) / 2, (H - ch * kk) / 2, cw * kk, ch * kk);
      fx.filter = "none";
    } else {
      fx.fillStyle = s.fit_mode.startsWith("Solid") ? s.bg_color : "#000000";
      fx.fillRect(0, 0, W, H);
    }
    fx.drawImage(c0, cx, cy, cw, ch, Math.floor((W - fw) / 2), Math.floor(((H - fh) * +s.fit_y) / 100), fw, fh);
  }
  if (Math.abs(+s.grain) > 1e-6 || Math.abs(+s.vignette) > 1e-6) fx.putImageData(CL.applyFinish(fx.getImageData(0, 0, W, H), s), 0, 0);

  const boxes = [];
  // overlays
  const ovs = s.overlays.map((o, i) => ({ o, i })).sort((a, b) => layerOf(a.o) - layerOf(b.o));
  for (const { o, i } of ovs) {
    const ov = { ...E.OVERLAY_DEFAULT, ...o };
    if (!ov.path || !visible(ov, t)) continue;
    const local = t - (+ov.start || 0) + (+ov.src_offset || 0);
    let img = null;
    try { img = E.isOverlayVideo(ov.path) ? await frameAt(ov.path, Math.max(0, local), 640) : await still(ov.path); } catch (e) { img = null; }
    if (!img) continue;
    const ow = Math.max(2, Math.floor((W * Math.max(1, +ov.scale)) / 100));
    const oh = Math.max(2, Math.floor((img.naturalHeight * ow) / img.naturalWidth));
    const oc = canvas(ow, oh), ox = oc.getContext("2d", { willReadFrequently: true });
    ox.drawImage(img, 0, 0, ow, oh);
    if (ov.chroma || +ov.opacity < 100) {
      const id = ox.getImageData(0, 0, ow, oh);
      const a = ov.chroma ? keyAlpha(id.data, ow * oh, ov.key_color, +ov.key_sim, +ov.key_blend) : null;
      const op = +ov.opacity / 100;
      for (let p = 0; p < ow * oh; p++) id.data[p * 4 + 3] = id.data[p * 4 + 3] * op * (a ? a[p] : 1);
      ox.putImageData(id, 0, 0);
    }
    let [x, y] = posXY(ov.pos, +ov.x, +ov.y, W, H, ow, oh);
    x = Math.max(0, Math.min(x, W - ow)); y = Math.max(0, Math.min(y, H - oh));
    fx.drawImage(oc, x, y);
    boxes.push({ kind: "overlay", index: i, x, y, w: ow, h: oh });
  }
  // texts
  const txs = s.texts.map((o, i) => ({ o, i })).sort((a, b) => layerOf(a.o) - layerOf(b.o));
  for (const { o, i } of txs) {
    if (!E.stripColors(String(o.text || "")).trim() || !visible(o, t)) continue;
    await ensureFont(o, Math.max(8, Math.floor((H * +o.size) / 100)));
    const d = drawText(o, W, H);
    fx.drawImage(d.canvas, d.x, d.y);
    const [bx, by, bw, bh] = d.box;
    boxes.push({ kind: "text", index: i, x: bx, y: by, w: bw, h: bh });
  }
  return { canvas: fr, W, H, boxes, geo };
}

// colour of the movie frame at a point of the preview (for "pick colour from picture")
export async function pickColour(movie, t, info, crop, s, fx, fy) {
  const src = await frameAt(movie, t, 960);
  const c = canvas(src.naturalWidth, src.naturalHeight), x = c.getContext("2d", { willReadFrequently: true });
  x.drawImage(src, 0, 0);
  const px = Math.min(c.width - 1, Math.max(0, Math.round(fx * c.width))), py = Math.min(c.height - 1, Math.max(0, Math.round(fy * c.height)));
  const d = x.getImageData(px, py, 1, 1).data;
  return "#" + [d[0], d[1], d[2]].map((v) => v.toString(16).padStart(2, "0")).join("").toUpperCase();
}
