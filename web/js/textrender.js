// Text layers are drawn here (Chromium's text engine: Hindi and every other script are shaped correctly) and
// placed with the same rules as the desktop software. The SAME drawing is used for the live preview and for the
// export (saved as a transparent PNG and laid over the video by FFmpeg), so what you see is what you get.
import * as E from "./engine.js";
import { bridge, bytesToB64 } from "./bridge.js";

export const FONTS = [
  "Noto Sans", "Noto Sans Devanagari", "Hind", "Mukta", "Baloo 2", "Rozha One", "Teko", "Poppins", "Montserrat",
  "Anton", "Bebas Neue", "Oswald", "Bangers", "Lobster", "Roboto",
];

const hexRgba = (c, a) => {
  c = String(c || "").replace("#", "");
  if (!/^[0-9a-fA-F]{6}$/.test(c)) c = "FFFFFF";
  return `rgba(${parseInt(c.slice(0, 2), 16)},${parseInt(c.slice(2, 4), 16)},${parseInt(c.slice(4, 6), 16)},${a})`;
};

export function fontString(t, px) {
  const fam = String(t.font || "Noto Sans").replace(/"/g, "");
  return `${t.bold === false ? 400 : 700} ${px}px "${fam}", "Noto Sans", "Noto Sans Devanagari", sans-serif`;
}

export async function ensureFont(t, px) {
  try { if (document.fonts) await document.fonts.load(fontString(t, px), String(t.text || "A")); } catch (e) { /* use fallback */ }
}

// Geometry of a text item in a frame W x H: the text box (x, y, tw, th) and drawing details.
export function layout(t0, W, H, ctx) {
  const t = { ...E.TEXT_DEFAULT, ...t0 };
  const text = String(t.text).replace(/\n+$/, "");
  const lines = text.split("\n");
  const fs = Math.max(8, Math.floor((H * +t.size) / 100));
  const sw = +t.outline > 0 ? Math.max(1, Math.round((+t.outline * H) / 1080)) : 0;
  const spacing = Math.floor(fs * 0.15);
  ctx.font = fontString(t, fs);
  const m = ctx.measureText("Hgजो");
  const asc = m.fontBoundingBoxAscent || fs * 0.92, desc = m.fontBoundingBoxDescent || fs * 0.26;
  const lineH = asc + desc;
  const widths = lines.map((l) => ctx.measureText(l).width);
  const tw = Math.ceil(Math.max(1, ...widths) + 2 * sw);
  const th = Math.ceil(lines.length * lineH + (lines.length - 1) * spacing + 2 * sw);
  const mx = Math.floor(W * 0.04), my = Math.floor(H * 0.05);
  let x, y;
  if (t.pos === "Custom") { x = Math.floor((W * +t.x) / 100); y = Math.floor((H * +t.y) / 100); }
  else if (t.pos === "Center") { x = Math.floor((W - tw) / 2); y = Math.floor((H - th) / 2); }
  else {
    const [vert, horz] = String(t.pos).split("-");
    x = { Left: mx, Center: Math.floor((W - tw) / 2), Right: W - tw - mx }[horz] ?? mx;
    y = { Top: my, Middle: Math.floor((H - th) / 2), Bottom: H - th - my }[vert] ?? my;
  }
  if (t.hcenter) x = Math.floor((W - tw) / 2);
  if (t.vcenter) y = Math.floor((H - th) / 2);
  return { t, lines, widths, fs, sw, spacing, asc, desc, lineH, tw, th, x, y };
}

// Draws the text into its own small canvas. Returns {canvas, x, y} = where its top-left goes in the frame.
export function drawText(t0, W, H) {
  const probe = document.createElement("canvas").getContext("2d");
  const L = layout(t0, W, H, probe);
  const { t } = L;
  const pad = t.box ? Math.floor(L.fs * 0.3) : 0;
  const sd = t.shadow ? Math.max(1, Math.floor((3 * H) / 1080)) : 0;
  const margin = pad + 2;
  const cw = L.tw + 2 * margin + sd, ch = L.th + 2 * margin + sd;
  const c = document.createElement("canvas");
  c.width = Math.max(2, cw); c.height = Math.max(2, ch);
  const ctx = c.getContext("2d");
  const ox = margin, oy = margin;           // text box top-left inside the small canvas
  if (t.box) {
    ctx.fillStyle = hexRgba(t.box_color, Math.max(0, Math.min(100, +t.box_opacity)) / 100);
    ctx.fillRect(ox - pad, oy - pad, L.tw + 2 * pad, L.th + 2 * pad);
  }
  ctx.font = fontString(t, L.fs);
  ctx.textBaseline = "alphabetic";
  ctx.textAlign = "center";
  ctx.lineJoin = "round";
  const op = Math.max(0, Math.min(100, +t.opacity)) / 100;
  const cx = ox + L.tw / 2;
  L.lines.forEach((line, i) => {
    const by = oy + L.sw + i * (L.lineH + L.spacing) + L.asc;
    if (t.shadow) { ctx.fillStyle = `rgba(0,0,0,${0.6 * op})`; ctx.fillText(line, cx + sd, by + sd); }
    if (L.sw > 0) {
      ctx.strokeStyle = hexRgba(t.outline_color, op);
      ctx.lineWidth = L.sw * 2;
      ctx.strokeText(line, cx, by);
    }
    ctx.fillStyle = hexRgba(t.color, op);
    ctx.fillText(line, cx, by);
  });
  return { canvas: c, x: L.x - margin, y: L.y - margin, box: [L.x, L.y, L.tw, L.th] };
}

// engine.js calls this while it builds an export command
export async function renderTextPng(t, OW, OH, tmpDir) {
  await ensureFont(t, Math.max(8, Math.floor((OH * +t.size) / 100)));
  const { canvas, x, y } = drawText(t, OW, OH);
  const url = canvas.toDataURL("image/png");
  const p = E.join(tmpDir, `text_${Date.now()}_${Math.random().toString(36).slice(2, 8)}.png`);
  await bridge().writeBase64(p, url.slice(url.indexOf(",") + 1));
  return { path: p, x, y };
}

export { bytesToB64 };
