// Makes test media: a movie with "talking" (voiced bursts like syllables) and pauses, a picture, a music file.
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

// a dual / triple audio movie like the ones MKVToolNix is used for: 3 audio languages + a subtitle
export function makeLangMovie(dir) {
  const out = path.join(dir, "movie_langs.mkv");
  if (fs.existsSync(out)) return out;
  const srt = path.join(dir, "subs.srt");
  fs.writeFileSync(srt, "1\n00:00:01,000 --> 00:00:03,000\nHello\n");
  execFileSync("ffmpeg", ["-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=25:duration=12",
    "-f", "lavfi", "-i", "sine=frequency=300:duration=12", "-f", "lavfi", "-i", "sine=frequency=500:duration=12",
    "-f", "lavfi", "-i", "sine=frequency=700:duration=12", "-i", srt,
    "-map", "0:v", "-map", "1:a", "-map", "2:a", "-map", "3:a", "-map", "4:s",
    "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-c:s", "srt",
    "-metadata:s:a:0", "language=eng", "-metadata:s:a:1", "language=hin", "-metadata:s:a:1", "title=Hindi 5.1",
    "-metadata:s:a:2", "language=tam", "-metadata:s:s:0", "language=eng", "-disposition:a:0", "default", out]);
  fs.unlinkSync(srt);
  return out;
}

export function makeMedia(dir, seconds = 240) {
  fs.mkdirSync(dir, { recursive: true });
  try { makeLangMovie(dir); } catch (e) { /* only for the track tool test */ }
  const movie = path.join(dir, "movie_talk.mp4");
  if (fs.existsSync(movie)) return { movie, image: path.join(dir, "logo.png"), music: path.join(dir, "music.m4a"), schedule: JSON.parse(fs.readFileSync(path.join(dir, "schedule.json"))) };
  const sr = 16000, n = sr * seconds;
  const x = new Float32Array(n);
  // talk / pause schedule: deterministic pseudo random
  let seed = 7;
  const rnd = () => { seed = (seed * 1103515245 + 12345) & 0x7fffffff; return seed / 0x7fffffff; };
  const schedule = [];
  let t = 1.0;
  while (t < seconds - 2) {
    const talk = 2 + rnd() * 7, pause = rnd() < 0.3 ? 2.5 + rnd() * 3 : 0.4 + rnd() * 0.9;
    const end = Math.min(seconds - 1, t + talk);
    schedule.push([t, end]);
    t = end + pause;
  }
  for (const [a, b] of schedule) {
    const f0 = 110 + rnd() * 80;
    for (let i = Math.floor(a * sr); i < Math.floor(b * sr); i++) {
      const tt = i / sr;
      const syl = 0.5 + 0.5 * Math.sin(2 * Math.PI * 4.2 * tt);                 // syllables
      let v = 0;
      for (let h = 1; h <= 20; h++) v += Math.sin(2 * Math.PI * f0 * h * tt) / h * (h > 2 && h < 12 ? 1.4 : 0.6);
      x[i] = 0.12 * v * syl * syl;
    }
  }
  for (let i = 0; i < n; i++) x[i] += (rnd() - 0.5) * 0.002;                    // room noise
  const pcm = Buffer.alloc(n * 2);
  for (let i = 0; i < n; i++) pcm.writeInt16LE(Math.max(-32767, Math.min(32767, Math.round(x[i] * 32767))), i * 2);
  const raw = path.join(dir, "talk.s16");
  fs.writeFileSync(raw, pcm);
  execFileSync("ffmpeg", ["-y", "-v", "error", "-f", "lavfi", "-i", `testsrc2=size=1280x720:rate=30:duration=${seconds}`,
    "-f", "s16le", "-ar", "16000", "-ac", "1", "-i", raw,
    "-vf", "drawbox=x=0:y=0:w=1280:h=90:color=black:t=fill,drawbox=x=0:y=630:w=1280:h=90:color=black:t=fill",
    "-c:v", "libx264", "-preset", "ultrafast", "-crf", "30", "-c:a", "aac", "-b:a", "96k", "-shortest", movie]);
  fs.unlinkSync(raw);
  const image = path.join(dir, "logo.png");
  execFileSync("ffmpeg", ["-y", "-v", "error", "-f", "lavfi", "-i", "color=c=0x39FF14:s=320x120", "-frames:v", "1", image]);
  const music = path.join(dir, "music.m4a");
  execFileSync("ffmpeg", ["-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=20", "-c:a", "aac", music]);
  fs.writeFileSync(path.join(dir, "schedule.json"), JSON.stringify(schedule));
  return { movie, image, music, schedule };
}
