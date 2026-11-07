// Self test (runs when the app is opened with #selftest, used by the automatic build on an Android emulator):
// FFmpeg starts, a test video is made, exported with colour + text + 9:16 blur, and speech detection runs.
import { bridge } from "./bridge.js";
import * as E from "./engine.js";
import * as D from "./dialogue.js";

const log = (m) => console.log("SELFTEST " + m);

export async function runSelfTest(app) {
  try {
    const info0 = await bridge().appInfo();
    log("app " + JSON.stringify(info0));
    const v = await E.ffrun(["-hide_banner", "-version"]);
    if (v.code !== 0) throw new Error("ffmpeg does not start: " + v.stderr.slice(-300));
    log("ffmpeg " + v.stdout.split("\n")[0]);
    const enc = await E.ffrun(["-hide_banner", "-encoders"]);
    log("encoders: x264=" + /libx264/.test(enc.stdout) + " mediacodec=" + /h264_mediacodec/.test(enc.stdout));
    const cache = app.paths.cache;
    const src = E.join(cache, "selftest_src.mp4");
    const g = await E.ffrun(["-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=25:duration=12",
      "-f", "lavfi", "-i", "sine=frequency=300:duration=12", "-af", "volume='if(lt(mod(t,3),2),1,0)':eval=frame",
      "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest", src]);
    if (g.code !== 0) throw new Error("test video: " + g.stderr.slice(-300));
    const info = await E.probeInfo(src);
    log(`probe ${info.w}x${info.h} ${info.duration.toFixed(1)}s audio=${info.has_audio}`);
    for (const codec of [E.CODECS[0], "H.264 (CPU)"]) {
      const out = E.join(cache, `selftest_out_${codec.includes("CPU") ? "cpu" : "hw"}.mp4`);
      const s = E.sanitize({ aspect: "9:16", fit_mode: "Blur background", resolution: "480p", codec, quality: "Fast (phone)", bitrate: 3000,
        exposure: 0.2, warmth: 0.3, vignette: 0.3, clarity: 0.3, texts: [{ text: "Part 1 नमस्ते", start: 0, end: 0, hcenter: true, vcenter: true }] });
      const r = new E.Runner(s, (m) => log("  " + m), null, null, cache);
      const ok = await r.cut(src, 1, 6, out, info, null);
      const st = await bridge().stat(out);
      log(`export ${codec}: ok=${ok} size=${st ? st.size : 0}`);
      if (!ok || !st || st.size < 10000) throw new Error("export failed with " + codec);
    }
    const pieces = await D.analyze(src, 0, 12, { pad_ms: 150, min_sil_ms: 300, min_piece: 1 }, cache, (m) => log("  " + m));
    log(`speech pieces: ${pieces.length}`);
    log("OK");
    console.log("SELFTEST OK");
  } catch (e) {
    console.log("SELFTEST FAIL " + (e.stack || e.message || e));
  }
}
