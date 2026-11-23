"""PeakCut on a movie / downloaded video, FAST: the movie is cut into parts (copied, not re-made: seconds per part),
and each part is sent to PeakCut on its own. Clips of part 1 are ready while part 2 is still being worked on, instead
of waiting for the whole movie to be transcribed and read. Two parts are in PeakCut at a time."""
import json
import os
import subprocess
import threading
import time
import urllib.request
import uuid
import engine as E

WORK = os.path.join(E.OUTPUT_DIR, "_peakcut_parts")


def mmss(t):
    t = int(t)
    return f"{t // 3600}:{t // 60 % 60:02d}:{t % 60:02d}" if t >= 3600 else f"{t // 60:02d}:{t % 60:02d}"


def _req(base, path, data=None, ctype=None, timeout=60):
    r = urllib.request.Request(base + path, data=data, method="POST" if data is not None else "GET")
    if ctype:
        r.add_header("Content-Type", ctype)
    with urllib.request.urlopen(r, timeout=timeout) as f:
        return json.loads(f.read().decode("utf-8") or "null")


def upload(base, path, name, options):
    """POST /api/upload as multipart, streamed from the file (a part can be a few hundred MB)."""
    bnd = "----cc" + uuid.uuid4().hex
    head = (f"--{bnd}\r\nContent-Disposition: form-data; name=\"options\"\r\n\r\n{json.dumps(options)}\r\n"
            f"--{bnd}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{name}\"\r\n"
            f"Content-Type: application/octet-stream\r\n\r\n").encode("utf-8")
    tail = f"\r\n--{bnd}--\r\n".encode()
    size = len(head) + os.path.getsize(path) + len(tail)

    def body():
        yield head
        with open(path, "rb") as f:
            while True:
                b = f.read(4 * 1024 * 1024)
                if not b:
                    break
                yield b
        yield tail
    import http.client
    from urllib.parse import urlparse
    u = urlparse(base)
    c = http.client.HTTPConnection(u.hostname, u.port, timeout=600)
    c.putrequest("POST", "/api/upload")
    c.putheader("Content-Type", f"multipart/form-data; boundary={bnd}")
    c.putheader("Content-Length", str(size))
    c.endheaders()
    for chunk in body():
        c.send(chunk)
    r = c.getresponse()
    data = r.read().decode("utf-8", "ignore")
    if r.status >= 400:
        try:
            data = json.loads(data).get("detail", data)
        except Exception:
            pass
        raise RuntimeError(f"PeakCut refused the part ({r.status}): {str(data)[:300]}")
    return json.loads(data)


def plan_parts(duration, part_sec, start=0.0, end=None):
    end = duration if not end or end > duration else end
    out, t = [], max(0.0, start)
    while t < end - 1.0:
        b = min(end, t + part_sec)
        if end - b < part_sec * 0.25:            # a tiny last bit joins the part before it
            b = end
        out.append((t, b))
        t = b
    return out


def cut_part(movie, a, b, dest):
    """Stream copy (no re-encoding): a 10 minute part takes seconds. Video + the first audio track."""
    cmd = ["ffmpeg", "-nostdin", "-y", "-v", "error", "-ss", f"{a:.3f}", "-i", movie, "-t", f"{b - a:.3f}",
           "-map", "0:v:0", "-map", "0:a:0?", "-c", "copy", "-avoid_negative_ts", "make_zero", dest]
    r = subprocess.run(cmd, capture_output=True, creationflags=E.NOWIN)
    if r.returncode != 0 or not os.path.isfile(dest) or os.path.getsize(dest) < 1000:
        raise RuntimeError("Could not cut the part: " + r.stderr.decode(errors="ignore")[-300:])


class PartsJob:
    """Runs in a thread. log(text), on_part(index, state dict) are called from that thread."""

    def __init__(self, base, movie, part_sec, options, log, on_part, start=0.0, end=None, in_flight=2):
        self.base, self.movie, self.part_sec, self.options = base, movie, float(part_sec), dict(options)
        self.log, self.on_part = log, on_part
        self.start, self.end, self.in_flight = start, end, in_flight
        self.stop_flag = threading.Event()
        self.parts = []

    def run(self):
        info = E.probe_info(self.movie)
        spans = plan_parts(float(info["duration"]), self.part_sec, self.start, self.end)
        stem = os.path.splitext(os.path.basename(self.movie))[0][:60]
        self.parts = [dict(i=i, a=a, b=b, state="waiting", job=None, clips=0, progress=0.0, stage="")
                      for i, (a, b) in enumerate(spans)]
        self.log(f"{len(spans)} part(s) of about {self.part_sec / 60:.0f} min. Clips of each part appear in PeakCut "
                 f"as soon as that part is done.")
        os.makedirs(WORK, exist_ok=True)
        nxt = 0
        while not self.stop_flag.is_set():
            active = [p for p in self.parts if p["state"] in ("sent", "working")]
            if nxt < len(self.parts) and len(active) < self.in_flight:
                self._send(self.parts[nxt], stem)
                nxt += 1
                continue
            if nxt >= len(self.parts) and not active:
                break
            time.sleep(3)
            self._poll(active)
        made = sum(p["clips"] for p in self.parts)
        self.log(("Stopped. " if self.stop_flag.is_set() else "All parts done. ") + f"{made} clip(s) made.")
        return made

    def _send(self, p, stem):
        a, b = p["a"], p["b"]
        name = f"{stem} - part {p['i'] + 1:02d} ({int(a // 60):02d}m-{int(b // 60):02d}m).mkv"
        dest = os.path.join(WORK, f"part_{uuid.uuid4().hex[:8]}.mkv")
        try:
            p.update(state="cutting")
            self.on_part(p["i"], p)
            cut_part(self.movie, a, b, dest)
            p.update(state="uploading")
            self.on_part(p["i"], p)
            job = upload(self.base, dest, name, self.options)
            p.update(state="sent", job=job.get("id"))
            self.log(f"Part {p['i'] + 1}: sent to PeakCut ({mmss(a)} - {mmss(b)}).")
        except Exception as e:
            p.update(state="error", stage=str(e)[:200])
            self.log(f"Part {p['i'] + 1}: {e}")
        finally:
            try:
                os.remove(dest)
            except OSError:
                pass
            self.on_part(p["i"], p)

    def _poll(self, active):
        for p in active:
            try:
                j = _req(self.base, f"/api/jobs/{p['job']}")
            except Exception as e:
                p["stage"] = f"(cannot reach PeakCut: {str(e)[:80]})"
                self.on_part(p["i"], p)
                continue
            st = j.get("status")
            clips = j.get("clips") or []
            p.update(progress=float(j.get("progress") or 0), stage=str(j.get("stage") or ""),
                     clips=sum(1 for c in clips if c.get("status") == "done"))
            if st == "done":
                p["state"] = "done"
                self.log(f"Part {p['i'] + 1}: done - {p['clips']} clip(s).")
            elif st == "error":
                p["state"] = "error"
                p["stage"] = str(j.get("error") or "error")[:200]
                self.log(f"Part {p['i'] + 1}: PeakCut error: {p['stage']}")
            else:
                p["state"] = "working"
            self.on_part(p["i"], p)
