// Colour correction in one place (port of the desktop colour.py): the controls (every one is a number from
// -100 to +100, 0 = no change), the FFmpeg filters used by the export, and the matching maths used by the
// live preview.
//
// Stored settings keep the desktop units so desktop projects open here too: warmth -1..1, saturation 0..2.5,
// contrast 0.5..1.8, brightness -0.4..0.4, gamma 0.5..2, sharpness -2..2, hue -45..45 degrees. The newer
// controls are stored as -1..1 (= the number / 100).

export const NEW_DEFAULTS = {
  tint: 0, exposure: 0, highlights: 0, shadows: 0, whites: 0, blacks: 0,
  brilliance: 0, clarity: 0, grain: 0, fade: 0, vignette: 0,
};

export const LAYOUT = [
  ["COLOUR", [["warmth", "Temperature"], ["tint", "Tint"], ["saturation", "Saturation"], ["hue", "Hue"]]],
  ["LIGHTNESS", [["exposure", "Exposure"], ["contrast", "Contrast"], ["highlights", "Highlights"],
    ["shadows", "Shadows"], ["whites", "Whites"], ["blacks", "Blacks"], ["brilliance", "Brilliance"]]],
  ["EFFECTS", [["sharpness", "Sharpen"], ["clarity", "Clarity"], ["grain", "Particles"], ["fade", "Fade"],
    ["vignette", "Vignette"]]],
  ["ADVANCED", [["brightness", "Brightness"], ["gamma", "Gamma"]]],
];
export const KEYS = LAYOUT.flatMap(([, items]) => items.map(([k]) => k));
export const NEUTRAL = {
  ...NEW_DEFAULTS, warmth: 0, saturation: 1, hue: 0, contrast: 1, sharpness: 0, brightness: 0, gamma: 1,
};

function twoSided(neg, pos) {
  return [
    (u) => 1 + (u / 100) * (u > 0 ? pos : neg),
    (c) => (c > 1 ? ((c - 1) / pos) * 100 : ((c - 1) / neg) * 100),
  ];
}

const MAP = {
  saturation: twoSided(1.0, 1.5),
  contrast: twoSided(0.5, 0.8),
  gamma: twoSided(0.5, 1.0),
  hue: [(u) => (u / 100) * 45, (c) => (c / 45) * 100],
  sharpness: [(u) => (u / 100) * 2, (c) => (c / 2) * 100],
  brightness: [(u) => (u / 100) * 0.4, (c) => (c / 0.4) * 100],
};

const RANGES = {
  saturation: [0, 2.5], contrast: [0.5, 1.8], gamma: [0.5, 2.0], hue: [-45, 45],
  sharpness: [-2, 2], brightness: [-0.4, 0.4],
};

export function toCfg(key, ui) {
  ui = Math.max(-100, Math.min(100, Number(ui) || 0));
  return key in MAP ? MAP[key][0](ui) : ui / 100;
}

export function toUi(key, cfg) {
  const v = Number(cfg);
  const ui = key in MAP ? MAP[key][1](v) : v * 100;
  return Math.max(-100, Math.min(100, Number.isFinite(ui) ? ui : 0));
}

export function clamp(s) {
  for (const k of KEYS) {
    const [lo, hi] = RANGES[k] || [-1, 1];
    let v = Number(s[k]);
    if (!Number.isFinite(v)) v = NEUTRAL[k];
    s[k] = Math.min(hi, Math.max(lo, v));
  }
  return s;
}

// ------------------------------------------------------------------ tone curve (shared by export and preview)
const bump = (x, c, w) => Math.exp(-(((x - c) / w) ** 2));

export function toneActive(s) {
  return ["exposure", "shadows", "highlights", "whites", "blacks", "brilliance", "fade"]
    .some((k) => Math.abs(Number(s[k] || 0)) > 1e-6);
}

export function toneArray(xs, s) {
  const e = +s.exposure, sh = +s.shadows, hi = +s.highlights, wh = +s.whites, bl = +s.blacks;
  const br = +s.brilliance, fa = +s.fade;
  const out = new Float64Array(xs.length);
  let run = 0;
  for (let i = 0; i < xs.length; i++) {
    const x = xs[i];
    let y = x * 2 ** (1.5 * e);
    y += 0.22 * sh * bump(x, 0.22, 0.2) + 0.22 * hi * bump(x, 0.78, 0.2);
    y += 0.18 * wh * bump(x, 0.9, 0.15) + 0.14 * bl * bump(x, 0.08, 0.12);
    y += br * (0.14 * bump(x, 0.33, 0.28) - 0.07 * bump(x, 0.85, 0.15));
    if (fa >= 0) y = y * (1 - 0.3 * fa) + 0.14 * fa;
    else { const k = 0.12 * -fa; y = (y - k) / (1 - k); }
    y = Math.min(1, Math.max(0, y));
    run = i === 0 ? y : Math.max(run, y);      // never goes backwards, whatever the sliders do
    out[i] = run;
  }
  return out;
}

export function tonePoints(s, n = 33) {
  if (!toneActive(s)) return null;
  const xs = Array.from({ length: n }, (_, i) => i / (n - 1));
  return [xs, Array.from(toneArray(xs, s))];
}

// FFmpeg's eq works on limited-range luma
export function eqLuma(yFull, contrast, brightness, gamma) {
  let y = (16 + 219 * yFull) / 255;
  y = Math.min(1, Math.max(0, (y - 0.5) * contrast + 0.5));
  y = Math.min(1, Math.max(0, y + brightness));
  y = y ** (1 / gamma);
  return Math.min(1, Math.max(0, (y * 255 - 16) / 219));
}

export function mixerGains(s) {
  const t = +s.warmth, n = +s.tint;
  return [1 + 0.15 * t + 0.06 * n, 1 - 0.12 * n, 1 - 0.15 * t + 0.06 * n];
}

// Clarity radius = FFmpeg unsharp matrix size. FFmpeg refuses anything above 13 x 13.
export function msize(width) {
  return Math.max(5, Math.round(13 * Math.min(1, width / 1280)) | 1);
}

// ------------------------------------------------------------------ FFmpeg filters
const f4 = (v) => Number(v).toFixed(4);
const f3 = (v) => Number(v).toFixed(3);

export function ffmpegColour(s, width) {
  const f = [];
  const pts = tonePoints(s);
  if (pts) f.push("curves=all='" + pts[0].map((x, i) => `${f4(x)}/${f4(pts[1][i])}`).join(" ") + "'");
  const c = +s.contrast, b = +s.brightness, sat = +s.saturation, g = +s.gamma;
  if (Math.abs(c - 1) > 1e-6 || Math.abs(b) > 1e-6 || Math.abs(sat - 1) > 1e-6 || Math.abs(g - 1) > 1e-6) {
    f.push(`eq=brightness=${f3(b)}:contrast=${f3(c)}:saturation=${f3(sat)}:gamma=${f3(g)}`);
  }
  if (Math.abs(+s.warmth) > 1e-6 || Math.abs(+s.tint) > 1e-6) {
    const [r, gg, bb] = mixerGains(s);
    f.push(`colorchannelmixer=rr=${f4(r)}:gg=${f4(gg)}:bb=${f4(bb)}`);
  }
  if (Math.abs(+s.hue) > 1e-6) f.push(`hue=h=${Number(s.hue).toFixed(1)}`);
  const cl = +s.clarity;
  if (Math.abs(cl) > 1e-6) {
    const m = msize(width);
    f.push(`unsharp=${m}:${m}:${f3(cl * 1.5)}:5:5:0`);
  }
  const sh = +s.sharpness;
  if (Math.abs(sh) > 1e-6) f.push(`unsharp=5:5:${sh.toFixed(2)}:5:5:0`);
  return f;
}

export const vignetteAngle = (p) => 0.9 * Math.abs(p);

export function ffmpegFinish(s) {
  const f = [];
  const g = +s.grain;
  if (g > 1e-6) f.push(`noise=alls=${Math.max(1, Math.round(35 * g))}:allf=t+u`);
  else if (g < -1e-6) {
    const a = Math.abs(g);
    f.push(`hqdn3d=${(10 * a).toFixed(1)}:${(10 * a).toFixed(1)}:${(8 * a).toFixed(1)}:${(8 * a).toFixed(1)}`);
  }
  const v = +s.vignette;
  if (v > 1e-6) f.push(`vignette=angle=${f4(vignetteAngle(v))}:dither=0`);
  else if (v < -1e-6) f.push(`negate,vignette=angle=${f4(vignetteAngle(v))}:dither=0,negate`);
  return f;
}

// ------------------------------------------------------------------ preview maths (works on canvas ImageData)
function gaussKernel(sigma) {
  const r = Math.max(1, Math.ceil(sigma * 2.5));
  const k = new Float32Array(2 * r + 1);
  let sum = 0;
  for (let i = -r; i <= r; i++) { k[i + r] = Math.exp(-(i * i) / (2 * sigma * sigma)); sum += k[i + r]; }
  for (let i = 0; i < k.length; i++) k[i] /= sum;
  return [k, r];
}

// separable gaussian blur of a float RGB buffer (3 values per pixel)
export function blurRGB(src, w, h, sigma) {
  if (sigma <= 0.05) return src.slice();
  const [k, r] = gaussKernel(sigma);
  const tmp = new Float32Array(src.length), out = new Float32Array(src.length);
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      let a = 0, b = 0, c = 0;
      for (let i = -r; i <= r; i++) {
        const xx = Math.min(w - 1, Math.max(0, x + i));
        const p = (y * w + xx) * 3, kk = k[i + r];
        a += src[p] * kk; b += src[p + 1] * kk; c += src[p + 2] * kk;
      }
      const q = (y * w + x) * 3;
      tmp[q] = a; tmp[q + 1] = b; tmp[q + 2] = c;
    }
  }
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      let a = 0, b = 0, c = 0;
      for (let i = -r; i <= r; i++) {
        const yy = Math.min(h - 1, Math.max(0, y + i));
        const p = (yy * w + x) * 3, kk = k[i + r];
        a += tmp[p] * kk; b += tmp[p + 1] * kk; c += tmp[p + 2] * kk;
      }
      const q = (y * w + x) * 3;
      out[q] = a; out[q + 1] = b; out[q + 2] = c;
    }
  }
  return out;
}

function unsharp(buf, w, h, sigma, amount) {
  const bl = blurRGB(buf, w, h, sigma);
  for (let i = 0; i < buf.length; i++) buf[i] = buf[i] + (buf[i] - bl[i]) * amount;
  return buf;
}

const luma = (r, g, b) => r * 0.299 + g * 0.587 + b * 0.114;

// ImageData -> ImageData with the main colour stage applied (same maths as the export)
export function applyColour(img, s) {
  const { width: w, height: h, data } = img;
  const n = w * h;
  const buf = new Float32Array(n * 3);
  for (let i = 0; i < n; i++) {
    buf[i * 3] = data[i * 4] / 255; buf[i * 3 + 1] = data[i * 4 + 1] / 255; buf[i * 3 + 2] = data[i * 4 + 2] / 255;
  }
  const pts = tonePoints(s);
  if (pts) {
    const lut = new Float32Array(1024);
    const xs = pts[0], ys = pts[1];
    for (let i = 0; i < 1024; i++) {
      const x = i / 1023;
      let j = Math.min(xs.length - 2, Math.floor(x * (xs.length - 1)));
      const t = (x - xs[j]) / (xs[j + 1] - xs[j]);
      lut[i] = ys[j] + (ys[j + 1] - ys[j]) * t;
    }
    for (let i = 0; i < buf.length; i++) buf[i] = lut[Math.round(Math.min(1, Math.max(0, buf[i])) * 1023)];
  }
  const c = +s.contrast, b = +s.brightness, sat = +s.saturation, g = +s.gamma;
  if (Math.abs(c - 1) > 1e-6 || Math.abs(b) > 1e-6 || Math.abs(g - 1) > 1e-6) {
    const lut = new Float32Array(1024);
    for (let i = 0; i < 1024; i++) lut[i] = eqLuma(i / 1023, c, b, g);
    for (let i = 0; i < n; i++) {
      const p = i * 3;
      const y = luma(buf[p], buf[p + 1], buf[p + 2]);
      const d = lut[Math.round(Math.min(1, Math.max(0, y)) * 1023)] - y;
      buf[p] += d; buf[p + 1] += d; buf[p + 2] += d;
    }
  }
  if (Math.abs(sat - 1) > 1e-6) {
    for (let i = 0; i < n; i++) {
      const p = i * 3;
      const y = luma(buf[p], buf[p + 1], buf[p + 2]);
      buf[p] = y + (buf[p] - y) * sat; buf[p + 1] = y + (buf[p + 1] - y) * sat; buf[p + 2] = y + (buf[p + 2] - y) * sat;
    }
  }
  if (Math.abs(+s.warmth) > 1e-6 || Math.abs(+s.tint) > 1e-6) {
    const [gr, gg, gb] = mixerGains(s);
    for (let i = 0; i < n; i++) { buf[i * 3] *= gr; buf[i * 3 + 1] *= gg; buf[i * 3 + 2] *= gb; }
  }
  if (Math.abs(+s.hue) > 1e-6) {
    const th = (-Number(s.hue) * Math.PI) / 180, co = Math.cos(th), si = Math.sin(th);
    for (let i = 0; i < n; i++) {
      const p = i * 3;
      const y = luma(buf[p], buf[p + 1], buf[p + 2]);
      const u = (buf[p + 2] - y) / 1.772, v = (buf[p] - y) / 1.402;
      const u2 = u * co + v * si, v2 = v * co - u * si;
      const r = y + 1.402 * v2, bb = y + 1.772 * u2;
      buf[p] = r; buf[p + 2] = bb; buf[p + 1] = (y - 0.299 * r - 0.114 * bb) / 0.587;
    }
  }
  for (let i = 0; i < buf.length; i++) buf[i] = Math.min(1, Math.max(0, buf[i]));
  const m = msize(w);
  const cl = +s.clarity;
  if (cl > 1e-6) unsharp(buf, w, h, 0.154 * m, cl * 1.17);
  else if (cl < -1e-6) {
    const bl = blurRGB(buf, w, h, Math.max(0.5, (-cl / 0.6) * (m / 13)));
    buf.set(bl);
  }
  const sh = +s.sharpness;
  if (sh > 1e-6) unsharp(buf, w, h, 2, sh * 0.6);
  else if (sh < -1e-6) buf.set(blurRGB(buf, w, h, -sh * 1.15));
  const out = new ImageData(w, h);
  for (let i = 0; i < n; i++) {
    out.data[i * 4] = Math.round(Math.min(1, Math.max(0, buf[i * 3])) * 255);
    out.data[i * 4 + 1] = Math.round(Math.min(1, Math.max(0, buf[i * 3 + 1])) * 255);
    out.data[i * 4 + 2] = Math.round(Math.min(1, Math.max(0, buf[i * 3 + 2])) * 255);
    out.data[i * 4 + 3] = 255;
  }
  return out;
}

// seeded random numbers, so the preview grain does not flicker while dragging a slider
function rng(seed) {
  let x = seed >>> 0 || 1;
  return () => { x ^= x << 13; x >>>= 0; x ^= x >>> 17; x ^= x << 5; x >>>= 0; return x / 4294967296; };
}

// ImageData of the finished frame -> particles (grain) and vignette applied
export function applyFinish(img, s) {
  const g = +s.grain, v = +s.vignette;
  if (Math.abs(g) < 1e-6 && Math.abs(v) < 1e-6) return img;
  const { width: w, height: h } = img;
  const n = w * h;
  let buf = new Float32Array(n * 3);
  for (let i = 0; i < n; i++) {
    buf[i * 3] = img.data[i * 4] / 255; buf[i * 3 + 1] = img.data[i * 4 + 1] / 255; buf[i * 3 + 2] = img.data[i * 4 + 2] / 255;
  }
  if (g > 1e-6) {
    const r = rng(1), amp = (35 * g) / 2 / 255;
    for (let i = 0; i < n; i++) {
      const d = (r() * 2 - 1) * amp;
      buf[i * 3] += d; buf[i * 3 + 1] += d; buf[i * 3 + 2] += d;
    }
  } else if (g < -1e-6) {
    buf = blurRGB(buf, w, h, 0.6 * -g * Math.max(1, w / 720));
  }
  if (Math.abs(v) > 1e-6) {
    const ang = vignetteAngle(v), half = Math.hypot(w / 2, h / 2);
    for (let y = 0; y < h; y++) {
      for (let x = 0; x < w; x++) {
        const r = Math.hypot(x - w / 2 + 0.5, y - h / 2 + 0.5);
        const m = Math.cos(Math.min((ang * r) / half, Math.PI / 2)) ** 4;
        const p = (y * w + x) * 3;
        for (let c = 0; c < 3; c++) {
          const a = Math.min(1, Math.max(0, buf[p + c]));
          buf[p + c] = v > 0 ? a * m : 1 - (1 - a) * m;
        }
      }
    }
  }
  const out = new ImageData(w, h);
  for (let i = 0; i < n; i++) {
    out.data[i * 4] = Math.round(Math.min(1, Math.max(0, buf[i * 3])) * 255);
    out.data[i * 4 + 1] = Math.round(Math.min(1, Math.max(0, buf[i * 3 + 1])) * 255);
    out.data[i * 4 + 2] = Math.round(Math.min(1, Math.max(0, buf[i * 3 + 2])) * 255);
    out.data[i * 4 + 3] = 255;
  }
  return out;
}
