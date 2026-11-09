// Engine tests with the real ffmpeg: export with every kind of edit, exact bitrate, dialogue cut, silence,
// Auto Short with Stop + Continue. Run: node tests/engine.test.mjs
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import assert from "node:assert/strict";
import { setBridge } from "../web/js/bridge.js";
import * as E from "../web/js/engine.js";
import * as D from "../web/js/dialogue.js";
import * as A from "../web/js/autoshort.js";
import * as CL from "../web/js/colour.js";
import { nodeBridge } from "./nodebridge.mjs";
import { makeMedia } from "./make_media.mjs";

const ROOT = process.env.CC_TEST_DIR || "/tmp/cc-test";
const B = nodeBridge({ root: ROOT });
setBridge(B);
const media = makeMedia(path.join(ROOT, "media"));
const paths = await B.paths();
const log = (m) => console.log("   log:", m);

function probe(p) {
  const j = JSON.parse(execFileSync("ffprobe", ["-v", "error", "-show_entries", "format=duration,bit_rate:stream=codec_type,width,height,bit_rate",
    "-of", "json", p]).toString());
  return j;
}

// fake text renderer: a solid PNG of the right-ish size (the app draws real text with the phone's fonts)
const textPng = path.join(paths.cache, "fake_text.png");
execFileSync("ffmpeg", ["-y", "-v", "error", "-f", "lavfi", "-i", "color=c=white:s=300x80", "-frames:v", "1", textPng]);
E.setTextRenderer(async (t, OW, OH) => {
  const p = path.join(paths.cache, `t_${Math.random().toString(36).slice(2)}.png`);
  fs.copyFileSync(textPng, p);
  return { path: p, x: (OW - 300) / 2, y: OH * 0.1 };
});

let failures = 0;
async function test(name, fn) {
  const t0 = Date.now();
  try { await fn(); console.log(`ok   ${name} (${((Date.now() - t0) / 1000).toFixed(1)}s)`); }
  catch (e) { failures++; console.log(`FAIL ${name}\n`, e); }
}

await test("colour mapping round trip", () => {
  for (const k of CL.KEYS) for (const u of [-100, -37, 0, 52, 100]) {
    assert.ok(Math.abs(CL.toUi(k, CL.toCfg(k, u)) - u) < 1e-6, `${k} ${u}`);
  }
  const s = E.sanitize({ exposure: 0.3, shadows: -0.2, clarity: 0.5, sharpness: 1, warmth: 0.4, tint: -0.3, hue: 10, vignette: -0.5, grain: 0.4 });
  const f = CL.ffmpegColour(s, 1920);
  assert.ok(f[0].startsWith("curves=all='0.0000/"));
  assert.ok(f.some((x) => x.startsWith("unsharp=13:13:0.750")));
  assert.deepEqual(CL.ffmpegFinish(s), ["noise=alls=14:allf=t+u", "negate,vignette=angle=0.4500:dither=0,negate"]);
});

let info;
await test("probe + black bars", async () => {
  info = await E.probeInfo(media.movie);
  assert.equal(info.w, 1280); assert.equal(info.h, 720); assert.ok(info.has_audio);
  assert.ok(Math.abs(info.duration - 240) < 1);
  const crop = await E.detectCrop(media.movie, info.duration);
  console.log("   crop:", crop);
  assert.match(crop, /^crop=1280:5\d\d:0:\d+$/);
});

await test("export with everything (exact 8 Mbps, 9:16 blur, colour, overlay, text, music)", async () => {
  const out = path.join(paths.out, "full_edit.mp4");
  const s = E.sanitize({
    aspect: "9:16", fit_mode: "Blur background", resolution: "720p", codec: "H.264 (CPU)", quality: "Fast (phone)",
    rate_mode: E.RATE_MODES[0], bitrate: 8000, exposure: 0.2, contrast: 1.2, saturation: 1.3, warmth: 0.3, tint: 0.1,
    hue: 5, clarity: 0.4, sharpness: 0.5, grain: 0.2, vignette: 0.4, fade: 0.1, shadows: 0.2, fit_scale: 90, fit_y: 40,
    overlays: [{ path: media.image, pos: "Top-Right", scale: 25, opacity: 80, start: 2, end: 8, chroma: true }],
    texts: [{ text: "Part 1", start: 0, end: 0 }],
    audios: [{ path: media.music, start: 3, end: 15, volume: 50 }],
  });
  const crop = await E.detectCrop(media.movie, info.duration);
  const r = new E.Runner(s, log, null, null, paths.cache);
  const ok = await r.cut(media.movie, 10, 20, out, info, crop);
  assert.ok(ok, "export failed");
  const p = probe(out);
  const v = p.streams.find((x) => x.codec_type === "video");
  assert.equal(v.width, 720); assert.equal(v.height, 1280);
  assert.ok(Math.abs(+p.format.duration - 20) < 0.3, "duration " + p.format.duration);
  const kbps = +v.bit_rate / 1000;
  console.log("   video bitrate:", kbps.toFixed(0), "kbps (asked 8000)");
  assert.ok(kbps > 7000 && kbps < 9000, "bitrate " + kbps);
});

await test("other fit modes, crop, chroma, quality mode, hardware fallback", async () => {
  const crop = await E.detectCrop(media.movie, info.duration);
  for (const [i, extra] of [
    { aspect: "1:1", fit_mode: "Crop (fill frame)", src_aspect: "4:3", zoom: 1.3, crop_x: 20 },
    { aspect: "9:16", fit_mode: "Solid colour", bg_color: "#FF0000", fit_scale: 60 },
    { aspect: "4:5", fit_mode: "Black bars", rate_mode: E.RATE_MODES[1], chroma_on: true, chroma_bg_type: "Color" },
    { codec: E.CODECS[0], resolution: "480p" },           // no MediaCodec here: must fall back to the CPU
  ].entries()) {
    const out = path.join(paths.out, `mode_${i}.mp4`);
    const s = E.sanitize({ codec: "H.264 (CPU)", quality: "Fast (phone)", bitrate: 3000, ...extra });
    const ok = await new E.Runner(s, log, null, null, paths.cache).cut(media.movie, 30, 6, out, info, crop);
    assert.ok(ok, "mode " + i);
  }
});

let pieces;
await test("dialogue detection (built-in detector) finds the talking", async () => {
  pieces = await D.analyze(media.movie, 0, 60, { pad_ms: 150, min_sil_ms: 300, min_piece: 1.0 }, paths.cache, log);
  assert.ok(pieces.length >= 3, "pieces " + pieces.length);
  const truth = media.schedule.filter(([a]) => a < 60);
  const talk = truth.reduce((x, [a, b]) => x + Math.min(b, 60) - a, 0);
  const found = pieces.reduce((x, [, d]) => x + d, 0);
  console.log(`   talking: true ${talk.toFixed(1)}s, found ${found.toFixed(1)}s in ${pieces.length} pieces`);
  assert.ok(found > talk * 0.85 && found < talk * 1.3);
});

await test("single-pass dialogue export keeps picture and sound in sync", async () => {
  const out = path.join(paths.out, "dialogue.mp4");
  const s = E.sanitize({ codec: "H.264 (CPU)", quality: "Fast (phone)", bitrate: 4000, _joint_fade: 0.02, fade_sec: 0.02, _denoise: true });
  const crop = await E.detectCrop(media.movie, info.duration);
  const ok = await new E.Runner(s, log, null, null, paths.cache).cut(media.movie, pieces[0][0], 0, out, info, crop, s, pieces);
  assert.ok(ok);
  const p = probe(out);
  const total = pieces.reduce((x, [, d]) => x + d, 0);
  const a = p.streams.find((x) => x.codec_type === "audio"), v = p.streams.find((x) => x.codec_type === "video");
  assert.ok(a && v);
  assert.ok(Math.abs(+p.format.duration - total) < 0.4, `${p.format.duration} vs ${total}`);
});

await test("silence detection + keep ranges", async () => {
  const sil = await E.detectSilence(media.movie, -35, 2, info.duration);
  assert.ok(sil.length >= 3, "silences " + sil.length);
  const keep = E.silenceKeepRanges(sil, 0, 120, 0.25, 0.3);
  assert.ok(keep.length >= 2);
});

await test("silence scan of only the start of parts (windows) matches the full scan", async () => {
  const full = await E.detectSilence(media.movie, -35, 2, info.duration);
  const inside = full.find(([a, b]) => b - a >= 2 && b < info.duration - 5);
  assert.ok(inside, "no silence to test with");
  const w = [Math.max(0, inside[0] - 3), inside[1] + 2];
  const t0 = Date.now();
  const part = await E.detectSilence(media.movie, -35, 2, w[1] - w[0], null, [w]);
  const hit = part.find(([a, b]) => Math.abs(a - inside[0]) < 0.3 && Math.abs(b - inside[1]) < 0.3);
  assert.ok(hit, `window scan ${JSON.stringify(part)} vs full ${JSON.stringify(inside)}`);
  assert.deepEqual(await E.detectSilence(media.movie, -35, 2, 10, null, []), []);
});

await test("studio engine: parts with silence cut joined + numbering", async () => {
  const sil = await E.detectSilence(media.movie, -35, 2, info.duration);
  const s = E.sanitize({ codec: "H.264 (CPU)", quality: "Fast (phone)", bitrate: 3000, resolution: "480p" });
  const plans = [0, 1].map((i) => ({
    file: `t_part${i + 1}.mp4`, start: i * 40, end: i * 40 + 40, label: "", number: i + 1, overlays: [], texts: [],
    pieces: E.silenceKeepRanges(sil, i * 40, i * 40 + 40, 0.25, 0.3),
  }));
  const eng = new E.StudioEngine(s, log, () => {}, () => {}, paths.cache);
  const done = await eng.process(media.movie, plans, path.join(paths.out, "studio"));
  assert.equal(done, 2);
});

await test("auto short: stop after the first short, then continue", async () => {
  const outDir = path.join(paths.out, "auto");
  fs.rmSync(outDir, { recursive: true, force: true });
  const s = E.sanitize({ codec: "H.264 (CPU)", quality: "Fast (phone)", bitrate: 3000, resolution: "480p", aspect: "9:16" });
  const items = [{ kind: "text", text: "Part {n}", rel_start: 0, rel_end: 0 }];
  let resume = null;
  const made = [];
  let job;
  const mk = (extra) => new A.AutoShortJob({
    movie: media.movie, opts: { pad_ms: 150, min_sil_ms: 300, min_piece: 1, denoise: true, vad: true }, settings: s, items,
    outDir, tmpDir: paths.cache, log, progress: () => {}, minLen: 20, maxLen: 30, chunk: 60,
    onShort: (d) => { made.push(d); if (made.length === 1) job.stop(); }, onResume: (r) => { resume = r; }, ...extra,
  });
  job = mk({ ranges: [[0, 200]] });
  await job.run();
  assert.equal(made.length, 1, "first run made " + made.length);
  assert.ok(resume && !resume.finished, "no resume point");
  const saved = JSON.parse(fs.readFileSync(path.join(outDir, "_resume.json")));
  assert.equal(saved.next_number, 2);
  // continue
  const r = saved;
  const all = r.ranges, ri = r.range_index;
  const ranges = [[Math.max(all[ri][0], Math.min(r.pos, all[ri][1])), all[ri][1]], ...all.slice(ri + 1)];
  job = mk({ ranges, allRanges: all, indexBase: ri, priorMade: r.made, firstNumber: r.next_number, onShort: (d) => made.push(d) });
  await job.run();
  const nums = made.map((d) => d.number);
  console.log("   shorts:", made.map((d) => `${d.number}@${d.start.toFixed(1)}s/${d.length.toFixed(1)}s`).join(" "));
  assert.deepEqual(nums, nums.map((_, i) => i + 1));
  for (let i = 1; i < made.length; i++) assert.ok(made[i].start >= made[i - 1].start + made[i - 1].length - 0.5, "overlap");
  for (const d of made) assert.ok(d.length >= 20 - 0.01 && d.length <= 30 + 0.01, "length " + d.length);
  const fin = JSON.parse(fs.readFileSync(path.join(outDir, "_resume.json")));
  assert.ok(fin.finished);
});

console.log(failures ? `\n${failures} test(s) failed` : "\nall engine tests passed");
process.exit(failures ? 1 : 0);
