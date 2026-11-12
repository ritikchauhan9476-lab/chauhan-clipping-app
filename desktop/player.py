"""Live player for the editor preview (like CapCut / Filmora): plays the part WITH every edit - crop, colour,
effects, speed, overlays, text animations, music - by running the real export pipeline (engine.build_command) at
preview size and streaming the frames into the window. Sound: the same edit's audio as a WAV file (Windows)."""
import os, queue, subprocess, threading, time
from PIL import Image
import engine as E

try:
    import winsound                     # Windows only; elsewhere the player plays without sound
except ImportError:
    winsound = None


class LivePlayer:
    def __init__(self):
        self.proc = None
        self.frames = queue.Queue(maxsize=90)
        self.reader = None
        self.active = False
        self.started = False
        self.t0 = 0.0
        self.live = {}
        self.error = ""
        self.done_reading = False
        self.sound = False
        self._n = 0

    # ------------------------------------------------------------------ control
    def start(self, movie, a, dur, s, info, box, mute=False):
        """Starts playing the movie from a (s) for dur (s) with the settings s. Returns at once; frames arrive in
        self.frames. The sound (if any) starts with the first frame (see tick)."""
        self.stop()
        self._n += 1
        self.live = dict(box=box, wav=os.path.join(E.OUTPUT_DIR, f"_live_{os.getpid()}_{self._n}.wav"))
        cmd, tmp = E.build_command(movie, a, dur, "-", s, info, None, live=self.live)
        self.tmp = tmp
        self.frames = queue.Queue(maxsize=90)
        self.active, self.started, self.done_reading, self.error = True, False, False, ""
        self.sound = False
        want_sound = (not mute) and winsound is not None and "audio_cmd" in self.live
        token = self._n

        def work():
            if want_sound:
                try:
                    os.makedirs(os.path.dirname(self.live["wav"]), exist_ok=True)
                    r = subprocess.run(self.live["audio_cmd"], capture_output=True, creationflags=E.NOWIN, timeout=120)
                    self.sound = r.returncode == 0 and os.path.isfile(self.live["wav"])
                except Exception:
                    self.sound = False
            if token != self._n or not self.active:
                return
            try:
                self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                             creationflags=E.NOWIN, bufsize=0)
            except Exception as e:
                self.error = str(e)
                self.done_reading = True
                return
            w, h = self.live["w"], self.live["h"]
            size, idx = w * h * 3, 0
            out = self.proc.stdout
            while self.active and token == self._n:
                buf = bytearray()
                while len(buf) < size:
                    chunk = out.read(size - len(buf))
                    if not chunk:
                        break
                    buf += chunk
                if len(buf) < size:
                    break
                while self.active and token == self._n:
                    try:
                        self.frames.put((idx, bytes(buf)), timeout=0.2)
                        break
                    except queue.Full:
                        continue
                idx += 1
            if token == self._n:
                try:
                    err = self.proc.stderr.read().decode(errors="ignore")
                    if idx == 0 and err.strip():
                        self.error = err[-400:]
                except Exception:
                    pass
                self.done_reading = True
        self.reader = threading.Thread(target=work, daemon=True)
        self.reader.start()

    def stop(self):
        self.active = False
        self._n += 1
        if winsound is not None and self.sound:
            try:
                winsound.PlaySound(None, winsound.SND_PURGE)
            except Exception:
                pass
        self.sound = False
        p = self.proc
        self.proc = None
        if p and p.poll() is None:
            try:
                p.kill()
            except Exception:
                pass
        for t in getattr(self, "tmp", []) or []:
            try:
                os.remove(t)
            except OSError:
                pass
        self.tmp = []
        wav = self.live.get("wav")
        if wav:
            threading.Thread(target=self._remove_later, args=(wav,), daemon=True).start()

    @staticmethod
    def _remove_later(path):
        time.sleep(1.5)
        try:
            os.remove(path)
        except OSError:
            pass

    # ------------------------------------------------------------------ clock
    def tick(self):
        """Call often (every ~15 ms) from the UI thread. Returns (image or None, output time or None, finished)."""
        if not self.active:
            return None, None, True
        if not self.started:
            try:
                first = self.frames.get_nowait()
            except queue.Empty:
                return None, None, self.done_reading
            self.started = True
            if self.sound:
                try:
                    winsound.PlaySound(self.live["wav"], winsound.SND_FILENAME | winsound.SND_ASYNC
                                       | winsound.SND_NODEFAULT)
                except Exception:
                    self.sound = False
            self.t0 = time.perf_counter()
            return self._img(first[1]), 0.0, False
        fps = self.live.get("fps", 25.0)
        target = int((time.perf_counter() - self.t0) * fps)
        got = None
        while True:
            try:
                idx, data = self.frames.queue[0]          # peek
            except IndexError:
                break
            if idx > target:
                break
            got = self.frames.get_nowait()
        if got is None:
            return None, None, self.done_reading and self.frames.empty()
        return self._img(got[1]), got[0] / fps, False

    def _img(self, data):
        return Image.frombytes("RGB", (self.live["w"], self.live["h"]), data)
