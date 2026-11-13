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
  return `${t.italic ? "italic " : ""}${t.bold === false ? 400 : 700} ${px}px "${fam}", "Noto Sans", "Noto Sans Devanagari", sans-serif`;
}

export async function ensureFont(t, px) {
  try { if (document.fonts) await document.fonts.load(fontString(t, px), E.stripColors(String(t.text || "A")) || "A"); } catch (e) { /* use fallback */ }
}

// Geometry of a text item in a frame W x H: the text box (x, y, tw, th), every line's coloured runs and widths.
export function layout(t0, W, H, ctx) {
  const t = { ...E.TEXT_DEFAULT, ...t0 };
  const text = E.applyCase(String(t.text).replace(/\n+$/, ""), t.case);
  const lines = E.colorLines(text, t.color);
  const plain = lines.map((ln) => ln.map(([r]) => r).join(""));
  const fs = Math.max(8, Math.floor((H * +t.size) / 100));
  const sw = +t.outline > 0 ? Math.max(1, Math.round((+t.outline * H) / 1080)) : 0;
  const spacing = Math.floor(fs * 0.15 + (fs * (+t.line_spacing || 0)) / 100);
  ctx.font = fontString(t, fs);
  const m = ctx.measureText("Hgजो");
  const asc = m.fontBoundingBoxAscent || fs * 0.92, desc = m.fontBoundingBoxDescent || fs * 0.26;
  const lineH = asc + desc;
  const widths = plain.map((l) => ctx.measureText(l).width);
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
  return { t, lines, plain, widths, fs, sw, spacing, asc, desc, lineH, tw, th, x, y };
}

// Draws the text into its own small canvas. Returns {canvas, x, y, box} = where its top-left goes in the frame.
// t._reveal = number of words to show (typewriter); the words stay where the full text will be.
export function drawText(t0, W, H) {
  const probe = document.createElement("canvas").getContext("2d");
  const L = layout(t0, W, H, probe);
  const { t } = L;
  const sc = H / 1080;
  const pad = t.box ? Math.floor((L.fs * +(t.box_pad ?? 30)) / 100) : 0;
  const ang = (+(t.shadow_angle ?? 45) * Math.PI) / 180, dist = t.shadow ? (+t.shadow_dist || 0) * sc : 0;
  const sdx = Math.round(dist * Math.cos(ang)), sdy = Math.round(dist * Math.sin(ang));
  const glow = t.glow ? Math.max(1, Math.round((+t.glow_size || 8) * sc)) : 0;
  const margin = pad + 2 + glow * 3 + Math.ceil(L.fs * 0.1);
  const cw = L.tw + 2 * margin + Math.abs(sdx), ch = L.th + 2 * margin + Math.abs(sdy);
  const c = document.createElement("canvas");
  c.width = Math.max(2, cw); c.height = Math.max(2, ch);
  const ctx = c.getContext("2d");
  const ox = margin + Math.max(0, -sdx), oy = margin + Math.max(0, -sdy);   // text box top-left inside the small canvas
  const op = Math.max(0, Math.min(100, +t.opacity)) / 100;
  if (t.box) {
    ctx.fillStyle = hexRgba(t.box_color, (Math.max(0, Math.min(100, +t.box_opacity)) / 100) * op);
    ctx.fillRect(ox - pad, oy - pad, L.tw + 2 * pad, L.th + 2 * pad);
  }
  ctx.font = fontString(t, L.fs);
  ctx.textBaseline = "alphabetic";
  ctx.textAlign = "left";
  ctx.lineJoin = "round";
  // which characters are visible (typewriter)
  let budget = Infinity;
  if (Number.isFinite(t._reveal)) {
    const all = L.plain.join("\n");
    let n = 0, i = 0;
    const re = /\S+/g;
    let m;
    while ((m = re.exec(all)) && n < t._reveal) { n++; i = m.index + m[0].length; }
    budget = i;
  }
  const pieces = [];               // [text, colour, x, y]
  let used = 0;
  L.lines.forEach((ln, li) => {
    const inner = L.tw - 2 * L.sw;
    const lx = ox + L.sw + ({ Left: 0, Right: inner - L.widths[li] }[t.align] ?? (inner - L.widths[li]) / 2);
    const by = oy + L.sw + li * (L.lineH + L.spacing) + L.asc;
    let k = 0;
    for (const [run, col] of ln) {
      let r = run;
      if (used + r.length > budget) r = r.slice(0, Math.max(0, budget - used));
      if (r) pieces.push([r, col, lx + probe.measureText(L.plain[li].slice(0, k)).width, by, li]);
      k += run.length;
      used += run.length;
    }
    used += 1;                     // the line break
  });
  const draw = (fn) => pieces.forEach(([r, col, x, y]) => fn(r, col, x, y));
  if (glow) {
    const g = hexRgba(t.glow_color, 0.9 * op);
    ctx.save();
    ctx.shadowColor = g; ctx.shadowBlur = glow * 2.2;
    ctx.strokeStyle = hexRgba(t.glow_color, 0.55 * op); ctx.lineWidth = glow + L.sw * 2;
    for (let k = 0; k < 2; k++) draw((r, col, x, y) => ctx.strokeText(r, x, y));
    ctx.restore();
  }
  if (t.shadow) {
    ctx.fillStyle = hexRgba(t.shadow_color, (+(t.shadow_opacity ?? 60) / 100) * op);
    ctx.strokeStyle = ctx.fillStyle; ctx.lineWidth = L.sw * 2;
    draw((r, col, x, y) => { if (L.sw) ctx.strokeText(r, x + sdx, y + sdy); ctx.fillText(r, x + sdx, y + sdy); });
  }
  if (L.sw > 0) {
    ctx.strokeStyle = hexRgba(t.outline_color, op);
    ctx.lineWidth = L.sw * 2;
    draw((r, col, x, y) => ctx.strokeText(r, x, y));
  }
  draw((r, col, x, y) => { ctx.fillStyle = hexRgba(col, op); ctx.fillText(r, x, y); });
  if (t.underline) {
    const uh = Math.max(2, Math.round(L.fs * 0.06));
    ctx.fillStyle = hexRgba(t.color, op);
    const byLine = {};
    for (const [r, , x, y, li] of pieces) {
      const w = probe.measureText(r).width;
      const b = byLine[li] || (byLine[li] = [x, x + w, y]);
      b[0] = Math.min(b[0], x); b[1] = Math.max(b[1], x + w);
    }
    for (const [a, z, y] of Object.values(byLine)) ctx.fillRect(a, y + L.fs * 0.12, z - a, uh);
  }
  return { canvas: c, x: L.x - ox, y: L.y - oy, box: [L.x, L.y, L.tw, L.th] };
}

// engine.js calls this while it builds an export command
export async function renderTextPng(t, OW, OH, tmpDir) {
  await ensureFont(t, Math.max(8, Math.floor((OH * +t.size) / 100)));
  const { canvas, x, y } = drawText(t, OW, OH);
  const w = canvas.width, h = canvas.height;
  const url = canvas.toDataURL("image/png");
  const p = E.join(tmpDir, `text_${Date.now()}_${Math.random().toString(36).slice(2, 8)}.png`);
  await bridge().writeBase64(p, url.slice(url.indexOf(",") + 1));
  return { path: p, x, y, w, h };
}

export { bytesToB64 };
